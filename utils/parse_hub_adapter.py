"""
ParseHub 适配器
将 ParseHub 库适配到 python-telegram-bot 框架
整合所有高级功能：图床上传、AI总结、Telegraph发布、视频分割、转录等
"""

import asyncio
import hashlib
import logging
import tempfile
import time
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any

# Apply monkey patch to fix Facebook/YouTube parsing (ParseHub 1.5.10 format bug)
from utils.parsehub_patch import patch_parsehub_yt_dlp
patch_parsehub_yt_dlp()

from parsehub import ParseHub
from parsehub.config import GlobalConfig
from parsehub.types import ParseResult, VideoParseResult, ImageParseResult, MultimediaParseResult

logger = logging.getLogger(__name__)

# Singleflight: 同一 URL 只会有一条解析任务在执行，后续请求等待完成
_inflight: Dict[str, asyncio.Event] = {}
_inflight_results: Dict[str, Any] = {}


class ParseHubAdapter:
    """ParseHub 适配器类"""

    def __init__(self, cache_manager=None, user_manager=None, config=None, pyrogram_helper=None):
        """
        初始化适配器

        Args:
            cache_manager: Redis 缓存管理器
            user_manager: MySQL 用户管理器
            config: Bot配置对象
            pyrogram_helper: Pyrogram客户端（用于大文件上传）
        """
        self.cache_manager = cache_manager
        self.user_manager = user_manager
        self.config = config
        self.pyrogram_helper = pyrogram_helper  # 存储Pyrogram helper
        self.parsehub = ParseHub()
        self.temp_dir = Path(tempfile.gettempdir()) / "domobot_parse"
        self.temp_dir.mkdir(exist_ok=True)

        # 配置 ParseHub GlobalConfig
        if config:
            if config.douyin_api:
                GlobalConfig.douyin_api = config.douyin_api
                logger.info(f"✅ 配置抖音API: {config.douyin_api}")

            # 配置伪装User-Agent（绕过反爬虫）
            GlobalConfig.ua = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            )
            logger.info(f"✅ 配置伪装User-Agent: Chrome/131.0.0.0")

    async def get_supported_platforms(self) -> List[str]:
        """获取支持的平台列表"""
        try:
            platforms = self.parsehub.get_platforms()
            return [f"{p['name']}: {'|'.join(p['supported_types'])}" for p in platforms]
        except Exception as e:
            logger.error(f"获取支持的平台列表失败: {e}")
            return []

    async def check_url_supported(self, text: str) -> bool:
        """
        检查文本中是否包含支持的平台URL

        Args:
            text: 待检查的文本

        Returns:
            bool: 是否包含支持的URL
        """
        try:
            # 提取 URL
            url = await self._extract_url(text)
            if not url:
                return False

            # 检查是否支持
            parser = self.parsehub._select_parser(url)
            return parser is not None
        except Exception as e:
            logger.error(f"检查URL支持失败: {e}")
            return False

    async def parse_url(
        self,
        text: str,
        user_id: int,
        group_id: Optional[int] = None,
        proxy: Optional[str] = None,
        use_singleflight: bool = True
    ) -> Tuple[Optional[Any], Optional[Any], Optional[str], float, Optional[str]]:
        """
        解析URL并下载媒体（带 Singleflight 机制）

        Args:
            text: 包含URL的文本
            user_id: 用户ID
            group_id: 群组ID（可选）
            proxy: 代理地址（可选，不传则使用配置中的代理）
            use_singleflight: 是否使用 Singleflight 机制（默认True）

        Returns:
            (DownloadResult, ParseResult, platform_name, parse_time, error_msg)
        """
        # 提取 URL 用于 Singleflight key
        url = await self._extract_url(text)
        if not url or not use_singleflight:
            # 如果没有URL或禁用Singleflight，直接调用实现
            return await self._parse_url_impl(text, user_id, group_id, proxy)

        # Singleflight 机制：检查是否已有相同 URL 正在解析
        if url in _inflight:
            logger.info(f"[Singleflight] 等待已有解析任务: {url[:50]}...")
            # 等待已有任务完成
            await _inflight[url].wait()
            # 从结果缓存中获取
            result = _inflight_results.get(url)
            if result:
                logger.info(f"[Singleflight] 获取到缓存结果: {url[:50]}...")
                return result
            else:
                # 缓存已被清理，重新解析
                logger.warning(f"[Singleflight] 缓存已清理，重新解析: {url[:50]}...")
                return await self._parse_url_impl(text, user_id, group_id, proxy)

        # 创建 Event 标记正在解析
        event = asyncio.Event()
        _inflight[url] = event

        try:
            # 执行实际解析
            result = await self._parse_url_impl(text, user_id, group_id, proxy)
            # 缓存结果（5秒内有效，避免内存泄漏）
            _inflight_results[url] = result
            # 5秒后清理结果缓存
            asyncio.create_task(self._cleanup_singleflight_result(url, 5))
            return result
        finally:
            # 完成后释放等待者
            event.set()
            _inflight.pop(url, None)

    async def _cleanup_singleflight_result(self, url: str, delay: int):
        """清理 Singleflight 结果缓存"""
        await asyncio.sleep(delay)
        _inflight_results.pop(url, None)
        logger.debug(f"[Singleflight] 清理结果缓存: {url[:50]}...")

    async def _parse_url_impl(
        self,
        text: str,
        user_id: int,
        group_id: Optional[int] = None,
        proxy: Optional[str] = None
    ) -> Tuple[Optional[Any], Optional[Any], Optional[str], float, Optional[str]]:
        """
        解析URL并下载媒体（实际实现）

        Args:
            text: 包含URL的文本
            user_id: 用户ID
            group_id: 群组ID（可选）
            proxy: 代理地址（可选，不传则使用配置中的代理）

        Returns:
            (DownloadResult, ParseResult, platform_name, parse_time, error_msg)
        """
        start_time = time.time()

        try:
            # 提取 URL
            url = await self._extract_url(text)
            if not url:
                return None, None, None, 0, "未找到有效的URL"

            # 注意：DownloadResult包含文件对象，不能序列化到Redis缓存
            # 每次都需要重新解析和下载
            # cache_key = self._get_cache_key(url)

            # 选择解析器
            parser = self.parsehub._select_parser(url)
            if not parser:
                logger.error(f"不支持的平台: {url}")
                return None, None, None, 0, "不支持的平台"

            # 获取平台ID
            platform_obj = getattr(parser, '__platform__', None)
            if platform_obj and hasattr(platform_obj, 'id'):
                platform_id = platform_obj.id
            else:
                platform_id = getattr(parser, '__platform_id__', '')
            platform_name = platform_id or "unknown"

            # 配置代理（优先使用传入的proxy，否则使用配置中的proxy）
            # 注意：PARSER_PROXY 已弃用，改用 TIKTOK_REDIRECT_PROXY（仅用于TikTok短链接重定向）
            parser_proxy = proxy  # 不再使用全局 parser_proxy 配置
            downloader_proxy = proxy or (self.config.downloader_proxy if self.config else None)

            # 根据平台选择 Cookie（ParseConfig会自动将字符串转换为dict）
            # 支持：Twitter, Instagram, Bilibili, Kuaishou, YouTube (通过patch), Tieba
            # 不支持：Facebook (基于yt-dlp，ParseHub库限制)
            platform_cookie = None
            if self.config:
                logger.info(f"🔍 平台: {platform_id}")
                if platform_id == 'twitter' and self.config.twitter_cookie:
                    platform_cookie = self.config.twitter_cookie
                    logger.info(f"✅ 使用Twitter cookie: {platform_cookie[:50]}...")
                elif platform_id == 'instagram' and self.config.instagram_cookie:
                    platform_cookie = self.config.instagram_cookie
                    logger.info(f"✅ 使用Instagram cookie: {platform_cookie[:50]}...")
                elif platform_id == 'bilibili' and self.config.bilibili_cookie:
                    platform_cookie = self.config.bilibili_cookie
                    logger.info(f"✅ 使用Bilibili cookie: {platform_cookie[:50]}...")
                elif platform_id == 'kuaishou' and self.config.kuaishou_cookie:
                    platform_cookie = self.config.kuaishou_cookie
                    logger.info(f"✅ 使用Kuaishou cookie")
                elif platform_id == 'tieba' and self.config.tieba_cookie:
                    platform_cookie = self.config.tieba_cookie
                    logger.info(f"✅ 使用Tieba cookie (绕过安全验证): {platform_cookie[:50]}...")
                elif platform_id == 'youtube' and self.config.youtube_cookie:
                    # YouTube cookie是文件路径，不能传给ParseConfig（会被解析成dict）
                    # 直接在parsehub_patch.py中通过环境变量 YOUTUBE_COOKIE 读取
                    platform_cookie = None
                    logger.info(f"✅ YouTube cookie配置存在，通过patch从环境变量读取")
                else:
                    logger.info(f"⚠️ 平台 {platform_id} 未配置cookie或不匹配")

            # 配置平台特定的headers（用于绕过反爬虫）
            download_headers = {
                'User-Agent': GlobalConfig.ua,
            }

            # 根据平台添加 Referer 和 Origin（类似内置代理的策略）
            if platform_id == 'bilibili':
                download_headers.update({
                    'Referer': 'https://www.bilibili.com/',
                    'Origin': 'https://www.bilibili.com',
                })
                logger.info(f"✅ 配置Bilibili headers: Referer + Origin")
            elif platform_id == 'youtube':
                download_headers.update({
                    'Referer': 'https://www.youtube.com/',
                    'Origin': 'https://www.youtube.com',
                })
                logger.info(f"✅ 配置YouTube headers: Referer + Origin")
            elif platform_id == 'twitter':
                download_headers.update({
                    'Referer': 'https://twitter.com/',
                    'Origin': 'https://twitter.com',
                })
                logger.info(f"✅ 配置Twitter headers: Referer + Origin")
            elif platform_id == 'tiktok':
                download_headers.update({
                    'Referer': 'https://www.tiktok.com/',
                    'Origin': 'https://www.tiktok.com',
                })
                logger.info(f"✅ 配置TikTok headers: Referer + Origin")
            elif platform_id == 'xiaohongshu':
                # 小红书CDN需要完整的浏览器headers才能绕过反爬虫
                download_headers.update({
                    'Referer': 'https://www.xiaohongshu.com/',
                    'Origin': 'https://www.xiaohongshu.com',
                    'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
                    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Sec-Fetch-Dest': 'image',
                    'Sec-Fetch-Mode': 'no-cors',
                    'Sec-Fetch-Site': 'same-site',
                    'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                    'sec-ch-ua-mobile': '?0',
                    'sec-ch-ua-platform': '"Windows"',
                })
                logger.info(f"✅ 配置小红书 headers: 完整浏览器特征（绕过CDN反爬虫）")
            elif platform_id == 'weibo':
                download_headers.update({
                    'Referer': 'https://weibo.com/',
                })
                logger.info(f"✅ 配置微博 headers: Referer")

            # 创建ParseHub实例并直接传入proxy和cookie
            if platform_cookie:
                cookie_preview = str(platform_cookie)[:100] if not isinstance(platform_cookie, dict) else f"dict with {len(platform_cookie)} keys"
                logger.info(f"🍪 传递给ParseHub的cookie - 类型: {type(platform_cookie)}, 预览: {cookie_preview}")
            else:
                logger.info(f"⚠️ 未传递cookie给ParseHub")

            # 解析URL（带重试机制，最多3次）
            parsehub = ParseHub()
            max_retries = 3
            result = None
            last_error = None

            for attempt in range(1, max_retries + 1):
                try:
                    logger.debug(f"🔄 解析尝试 {attempt}/{max_retries}: {url[:50]}...")
                    result = await parsehub.parse(url, proxy=parser_proxy, cookie=platform_cookie)
                    if result:
                        logger.debug(f"✅ 解析成功 (尝试 {attempt}/{max_retries})")
                        break
                    else:
                        logger.warning(f"⚠️ 解析返回空结果 (尝试 {attempt}/{max_retries})")
                        last_error = "解析失败，未返回结果"
                except Exception as parse_error:
                    last_error = str(parse_error)
                    logger.warning(f"⚠️ 解析失败 (尝试 {attempt}/{max_retries}): {last_error}")
                    if attempt < max_retries:
                        await asyncio.sleep(1)  # 重试前等待1秒
                    else:
                        raise parse_error

            if not result:
                return None, None, None, 0, last_error or "解析失败，未返回结果"

            # 下载媒体
            try:
                download_result = await result.download(path=self.temp_dir, proxy=downloader_proxy)
            except Exception as download_error:
                # 下载失败（例如小红书CDN 500错误），但解析成功
                # 返回解析结果但没有下载的媒体文件
                logger.warning(f"媒体下载失败但解析成功: {download_error}")
                download_result = None

            parse_time = time.time() - start_time

            # 注意：DownloadResult不能序列化，不缓存到Redis
            # ParseHub自己有内存缓存机制处理重复URL

            # 记录统计
            await self._record_stats(user_id, group_id, platform_name, url, True, parse_time * 1000)

            return download_result, result, platform_name, parse_time, None

        except Exception as e:
            parse_time = time.time() - start_time
            error_msg = self._format_error_message(e)
            logger.error(f"解析URL失败: {error_msg}", exc_info=True)

            # 记录失败统计
            await self._record_stats(
                user_id,
                group_id,
                "unknown",
                text,
                False,
                parse_time * 1000,
                error_msg
            )

            return None, None, None, parse_time, error_msg

    def _format_error_message(self, error: Exception) -> str:
        """格式化错误信息，使其对用户更友好"""
        error_str = str(error)

        # Bilibili相关错误
        if "412" in error_str or "Precondition Failed" in error_str:
            return "Bilibili风控限制（412错误），请检查cookie配置或稍后重试"
        if "Bilibili解析失败" in error_str:
            return "Bilibili解析失败，可能是链接失效或需要登录"

        # YouTube相关错误
        if "Sign in to confirm" in error_str or "not a bot" in error_str:
            return "YouTube需要登录验证，请检查cookie配置"
        if "Requested format is not available" in error_str:
            return "YouTube视频格式不可用，可能需要安装Node.js或视频已被删除"
        if "No supported JavaScript runtime" in error_str:
            return "缺少JavaScript运行环境，YouTube解析可能受限"

        # Twitter/X相关错误
        if "twitter" in error_str.lower() or "x.com" in error_str.lower():
            return f"Twitter/X解析失败：{error_str}"

        # 通用网络错误
        if "timeout" in error_str.lower():
            return "请求超时，请稍后重试"
        if "connection" in error_str.lower():
            return "网络连接失败，请检查网络或代理设置"
        if "404" in error_str:
            return "内容不存在（404），链接可能已失效"
        if "403" in error_str:
            return "访问被拒绝（403），可能需要登录或cookie"
        if "500" in error_str or "502" in error_str or "503" in error_str:
            return "服务器错误，平台服务可能暂时不可用"

        # Cookie相关错误
        if "cookie" in error_str.lower():
            return f"Cookie配置问题：{error_str}"

        # 下载失败
        if "download" in error_str.lower():
            return f"下载失败：{error_str}"

        # 其他错误，返回原始错误信息（截断过长的信息）
        if len(error_str) > 150:
            return error_str[:150] + "..."
        return error_str

    async def format_result(self, download_result, platform: str, parse_result=None) -> dict:
        """
        格式化下载结果

        Args:
            download_result: DownloadResult 下载结果
            platform: 平台名称
            parse_result: ParseResult 解析结果（parsehub 2.0.0+ 不再存储在 DownloadResult 中）

        Returns:
            dict: 格式化后的结果
        """
        try:
            pr = parse_result
            if not pr:
                return {}
            formatted = {
                "title": pr.title or "",  # 保持原始值，不要在这里添加"无标题"
                "content": pr.content or "",
                "platform": platform,
                "url": pr.raw_url,
                "media_type": self._get_media_type(pr),
                "media_count": 0,
                "media_paths": []
            }

            # 获取媒体路径
            media = download_result.media if download_result else None
            if isinstance(media, list):
                formatted["media_count"] = len(media)
                # ParseHub 2.0.1+: MediaFile.exists() 方法直接检查文件是否存在
                formatted["media_paths"] = [str(m.path) for m in media if m.exists()]
            elif media and media.exists():
                formatted["media_count"] = 1
                formatted["media_paths"] = [str(media.path)]

            return formatted

        except Exception as e:
            logger.error(f"格式化结果失败: {e}")
            return {}

    def _get_media_type(self, result: ParseResult) -> str:
        """获取媒体类型"""
        if isinstance(result, VideoParseResult):
            return "video"
        elif isinstance(result, ImageParseResult):
            return "image"
        elif isinstance(result, MultimediaParseResult):
            return "multimedia"
        else:
            return "unknown"

    async def _extract_url(self, text: str) -> Optional[str]:
        """从文本中提取URL"""
        import re
        import httpx

        try:
            # 1. 先从文本中提取URL
            # Fixed: Support query parameters (?v=, &param=, etc.) and fragments (#hash)
            # Original regex stopped at '?' character, breaking Facebook watch/?v= URLs
            url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+(?:\?[^\s<>"{}|\\^`\[\]]*)?(?:#[^\s<>"{}|\\^`\[\]]*)?'
            match = re.search(url_pattern, text)
            if not match:
                return None

            url = match.group(0)
            logger.debug(f"提取原始URL: {url}")

            # 2. 检查是否为短链接（需要重定向）
            short_domains = ['b23.tv', 't.co', 'bit.ly', 'youtu.be', 'tiktok.com/t/', 'vt.tiktok.com', 'vm.tiktok.com', 'douyin.com/']
            is_short = any(domain in url for domain in short_domains)

            if is_short:
                # 跟随重定向获取真实URL
                # 添加 User-Agent 避免被 TikTok 重定向到 notfound 页面
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
                }
                # 使用代理避免地区限制（仅用于TikTok短链接重定向）
                import os
                # 检查是否是TikTok短链接
                is_tiktok_short = any(domain in url for domain in ['vt.tiktok.com', 'vm.tiktok.com'])
                proxy = os.getenv('TIKTOK_REDIRECT_PROXY') if is_tiktok_short else None

                # TikTok 住宅代理可能间歇性 502，重试最多3次
                max_retries = 3 if (is_tiktok_short and proxy) else 1
                redirect_success = False
                for attempt in range(max_retries):
                    try:
                        if proxy:
                            logger.info(f"✅ [TikTok短链接] 使用代理重定向 (尝试 {attempt+1}/{max_retries}): {proxy[:30]}...")
                        async with httpx.AsyncClient(follow_redirects=True, timeout=10, headers=headers, proxy=proxy) as client:
                            response = await client.head(url)
                            final_url = str(response.url)
                            logger.info(f"短链接重定向: {url} -> {final_url}")

                            # 检查是否重定向到 notfound 页面（地区限制）
                            if '/notfound' in final_url.lower():
                                logger.warning(f"重定向到notfound (尝试 {attempt+1}/{max_retries}): {final_url}")
                                if attempt < max_retries - 1:
                                    import asyncio
                                    await asyncio.sleep(1)
                                    continue
                                logger.error(f"视频不可用（可能地区限制）: {final_url}")
                                return None

                            url = final_url
                            redirect_success = True
                            break
                    except Exception as e:
                        logger.warning(f"重定向失败 (尝试 {attempt+1}/{max_retries}): {e}")
                        if attempt < max_retries - 1:
                            import asyncio
                            await asyncio.sleep(1)
                            continue
                        if is_tiktok_short:
                            logger.error(f"TikTok短链接重定向全部失败，无法解析")
                            return None
                        logger.warning(f"重定向失败，使用原URL")

            # 3. 验证URL是否被支持
            parser = self.parsehub._select_parser(url)
            if not parser:
                logger.error(f"不支持的平台: {url}")
                return None

            logger.debug(f"识别平台: {parser.__platform__}")
            return url

        except Exception as e:
            logger.error(f"提取URL失败: {text}, 错误: {e}", exc_info=True)
            return None

    def _get_cache_key(self, url: str) -> str:
        """生成缓存键"""
        url_hash = hashlib.md5(url.encode()).hexdigest()
        return f"parse:result:{url_hash}"

    async def _record_stats(
        self,
        user_id: int,
        group_id: Optional[int],
        platform: str,
        url: str,
        success: bool,
        parse_time_ms: float,
        error_message: Optional[str] = None
    ):
        """记录解析统计"""
        if not self.user_manager:
            return

        try:
            async with self.user_manager.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO social_parser_stats
                        (user_id, group_id, platform, url, parse_success, parse_time_ms, error_message)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (user_id, group_id, platform, url, success, int(parse_time_ms), error_message)
                    )
                    await conn.commit()
        except Exception as e:
            logger.error(f"记录解析统计失败: {e}")

    async def cleanup_temp_files(self, older_than_hours: int = 24):
        """清理临时文件"""
        try:
            import shutil
            cutoff_time = time.time() - (older_than_hours * 3600)

            for item in self.temp_dir.iterdir():
                if item.is_dir() and item.stat().st_mtime < cutoff_time:
                    shutil.rmtree(item, ignore_errors=True)
                    logger.info(f"清理临时目录: {item}")
        except Exception as e:
            logger.error(f"清理临时文件失败: {e}")

    async def is_auto_parse_enabled(self, group_id: int) -> bool:
        """
        检查群组是否启用了自动解析

        Args:
            group_id: 群组ID

        Returns:
            bool: 是否启用
        """
        if not self.user_manager:
            return False

        try:
            async with self.user_manager.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "SELECT auto_parse_enabled FROM social_parser_config WHERE group_id = %s",
                        (group_id,)
                    )
                    result = await cursor.fetchone()
                    logger.debug(f"查询结果: result={result}, type={type(result)}")
                    if not result:
                        logger.debug(f"群组 {group_id} 没有配置记录，返回False")
                        return False

                    # 安全地获取值
                    try:
                        if isinstance(result, (tuple, list)):
                            enabled = result[0]
                        elif isinstance(result, dict):
                            enabled = result.get('auto_parse_enabled', 0)
                        else:
                            logger.warning(f"未知的result类型: {type(result)}")
                            enabled = 0

                        logger.debug(f"群组 {group_id} auto_parse_enabled值: {enabled}")
                        return bool(enabled)
                    except (IndexError, KeyError, TypeError) as e:
                        logger.error(f"解析result失败: {e}, result={result}")
                        return False
        except Exception as e:
            logger.error(f"检查自动解析状态失败: {e}", exc_info=True)
            return False

    async def enable_auto_parse(self, group_id: int, enabled_by: int) -> bool:
        """
        启用群组自动解析

        Args:
            group_id: 群组ID
            enabled_by: 启用者ID

        Returns:
            bool: 是否成功
        """
        if not self.user_manager:
            return False

        try:
            async with self.user_manager.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO social_parser_config (group_id, auto_parse_enabled, enabled_by)
                        VALUES (%s, TRUE, %s)
                        ON DUPLICATE KEY UPDATE
                            auto_parse_enabled = TRUE,
                            enabled_by = %s,
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        (group_id, enabled_by, enabled_by)
                    )
                    await conn.commit()
                    logger.info(f"群组 {group_id} 启用自动解析")
                    return True
        except Exception as e:
            logger.error(f"启用自动解析失败: {e}")
            return False

    async def disable_auto_parse(self, group_id: int) -> bool:
        """
        禁用群组自动解析

        Args:
            group_id: 群组ID

        Returns:
            bool: 是否成功
        """
        if not self.user_manager:
            return False

        try:
            async with self.user_manager.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        UPDATE social_parser_config
                        SET auto_parse_enabled = FALSE,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE group_id = %s
                        """,
                        (group_id,)
                    )
                    await conn.commit()
                    logger.info(f"群组 {group_id} 禁用自动解析")
                    return True
        except Exception as e:
            logger.error(f"禁用自动解析失败: {e}")
            return False

    async def get_auto_parse_groups(self) -> List[int]:
        """
        获取所有启用自动解析的群组

        Returns:
            List[int]: 群组ID列表
        """
        if not self.user_manager:
            return []

        try:
            async with self.user_manager.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "SELECT group_id FROM social_parser_config WHERE auto_parse_enabled = TRUE"
                    )
                    results = await cursor.fetchall()
                    return [row[0] for row in results]
        except Exception as e:
            logger.error(f"获取自动解析群组列表失败: {e}")
            return []

    # ==================== 高级功能 ====================

    async def upload_to_image_host(self, file_path: Path) -> Optional[str]:
        """
        上传文件到图床

        Args:
            file_path: 文件路径

        Returns:
            图床URL，失败返回None
        """
        if not self.config or not self.config.enable_image_host:
            return None

        try:
            from utils.image_host import ImageHostUploader

            proxy = self.config.downloader_proxy if self.config else None
            kwargs = {}
            if self.config.catbox_userhash:
                kwargs["catbox_userhash"] = self.config.catbox_userhash
            if self.config.zioooo_storage_id:
                kwargs["zioooo_storage_id"] = self.config.zioooo_storage_id
            if self.config.pixeldrain_api_key:
                kwargs["pixeldrain_api_key"] = self.config.pixeldrain_api_key

            async with ImageHostUploader(
                service=self.config.image_host_service,
                proxy=proxy,
                **kwargs
            ) as uploader:
                url = await uploader.upload(file_path)
                return url

        except Exception as e:
            logger.error(f"上传到图床失败: {e}")
            return None

    async def split_large_video(self, video_path: Path) -> List[Path]:
        """
        分割大视频文件

        Args:
            video_path: 视频路径

        Returns:
            分割后的文件路径列表（如果不需要分割，返回原文件）
        """
        if not self.config or not self.config.enable_video_split:
            return [video_path]

        try:
            from utils.video_splitter import split_video_if_needed

            parts = await split_video_if_needed(
                video_path,
                max_size_mb=self.config.video_split_size,
                ffmpeg_path=self.config.ffmpeg_path
            )
            return parts

        except Exception as e:
            logger.error(f"视频分割失败: {e}")
            return [video_path]

    async def generate_ai_summary(self, parse_result, download_result=None) -> Optional[str]:
        """
        AI总结功能

        Args:
            parse_result: ParseResult 解析结果
            download_result: DownloadResult 下载结果（可选，用于视频转录和图片识别）

        Returns:
            AI总结文本，失败返回None
        """
        if not self.config or not self.config.enable_ai_summary:
            return None

        if not self.config.openai_api_key:
            logger.warning("AI总结未配置：缺少 OPENAI_API_KEY")
            return None

        try:
            from utils.ai_summary import AISummarizer

            summarizer = AISummarizer(
                api_key=self.config.openai_api_key,
                base_url=self.config.openai_base_url or None,
                model=self.config.ai_summary_model or "gpt-5-mini",
                transcription_provider=self.config.transcription_provider or "openai",
                transcription_api_key=self.config.transcription_api_key,
                transcription_base_url=self.config.transcription_base_url,
            )
            return await summarizer.summarize(parse_result, download_result)

        except Exception as e:
            logger.error(f"AI总结生成失败: {e}", exc_info=True)
            return None

    async def publish_to_telegraph(self, result: ParseResult, content_html: str) -> Optional[str]:
        """
        发布内容到 Telegraph（自动判断，无需配置开关）

        参考 parse_hub_bot 实现：
        - 微信文章自动发布
        - 酷安图文自动发布
        - 超过9张图片自动发布

        Args:
            result: 解析结果（可以为None）
            content_html: HTML内容

        Returns:
            Telegraph URL，失败返回None
        """
        try:
            from utils.telegraph_helper import TelegraphPublisher

            # 获取 telegraph token（如果已配置）
            telegraph_token = self.config.telegraph_token if self.config else None
            author_name = self.config.telegraph_author if self.config else "DomoBot"

            publisher = TelegraphPublisher(
                access_token=telegraph_token,
                author_name=author_name
            )

            # 获取标题
            title = "解析内容"
            if result and hasattr(result, 'title') and result.title:
                title = result.title

            url = await publisher.create_page(
                title=title,
                content=content_html
            )

            # 保存自动创建的token（如果是第一次使用）
            if url and self.config and not self.config.telegraph_token:
                self.config.telegraph_token = publisher.access_token
                logger.info(f"Telegraph token已自动创建并保存")

            return url

        except Exception as e:
            logger.error(f"Telegraph发布失败: {e}")
            return None

