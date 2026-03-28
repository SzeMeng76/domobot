"""
Reddit JSON API 客户端（无需 OAuth）
使用 Reddit 公开的 JSON 端点，不需要 API key
使用 curl_cffi 模拟浏览器 TLS 指纹绕过反爬虫检测
支持多浏览器轮询以避免检测
实现 circuit breaker 和自动 cooldown 机制
"""

import asyncio
import hashlib
import logging
import random
import time
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

try:
    from curl_cffi.requests import AsyncSession, BrowserType
    CURL_CFFI_AVAILABLE = True
except ImportError:
    CURL_CFFI_AVAILABLE = False
    logging.warning("curl_cffi not installed, Reddit JSON client will not work")

logger = logging.getLogger(__name__)


# 可用的浏览器指纹列表（curl-cffi 0.14+ 支持，优先使用最新版本）
BROWSER_POOL = [
    'chrome142',
    'chrome136',
    'chrome133a',
    'chrome131',
    'chrome124',
    'chrome123',
    'chrome120',
    'safari260',
    'safari2601',
    'safari184',
    'firefox144',
    'firefox135',
    'edge101',
]

# Cooldown 配置
COOLDOWN_FALLBACK_MIN = 300  # 5 分钟
COOLDOWN_FALLBACK_MAX = 600  # 10 分钟
COOLDOWN_JITTER_MIN = 5
COOLDOWN_JITTER_MAX = 15


@dataclass
class RedditPost:
    """Reddit 帖子数据类"""
    id: str
    title: str
    author: str
    subreddit: str
    score: int
    num_comments: int
    url: str
    permalink: str
    created_utc: float
    is_self: bool
    selftext: str = ""
    post_hint: str = ""
    is_video: bool = False
    preview_image_url: str = ""
    video_url: str = ""
    gallery_items: List[str] = None

    def __post_init__(self):
        if self.gallery_items is None:
            self.gallery_items = []


@dataclass
class RedditComment:
    """Reddit 评论数据类"""
    id: str
    author: str
    body: str
    score: int
    created_utc: float


class RedditJsonClient:
    """Reddit JSON API 客户端（使用 TLS 指纹伪装 + 浏览器轮询 + Circuit Breaker）"""

    def __init__(
        self,
        user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        proxy: Optional[str] = None,
        rotate_browser: bool = True,
        concurrency: int = 6
    ):
        if not CURL_CFFI_AVAILABLE:
            raise ImportError("curl_cffi is required for RedditJsonClient. Install with: pip install curl_cffi")

        self.user_agent = user_agent
        self.proxy = proxy
        self.base_url = "https://www.reddit.com"
        self.rotate_browser = rotate_browser  # 是否轮询浏览器
        self.session: Optional[AsyncSession] = None
        self.current_browser = random.choice(BROWSER_POOL)  # 随机选择初始浏览器

        # Circuit breaker 状态
        self.cooldown_until: float = 0.0  # 冷却结束时间（monotonic time）
        self.semaphore = asyncio.Semaphore(concurrency)  # 并发控制

    def is_available(self) -> bool:
        """检查是否可用（未在冷却期）"""
        return time.monotonic() >= self.cooldown_until

    def cooldown_remaining(self) -> float:
        """返回剩余冷却时间（秒）"""
        return max(0.0, self.cooldown_until - time.monotonic())

    def _parse_rate_limit_headers(self, response) -> Optional[float]:
        """解析 rate limit headers，返回 reset 时间（秒）"""
        try:
            # Reddit 使用 X-Ratelimit-Reset (Unix timestamp)
            reset_header = response.headers.get('x-ratelimit-reset') or response.headers.get('X-Ratelimit-Reset')
            if reset_header:
                reset_timestamp = float(reset_header)
                now = time.time()
                return max(0, reset_timestamp - now)
        except (ValueError, TypeError):
            pass
        return None

    def _set_cooldown(self, status_code: int, response=None) -> None:
        """设置冷却期"""
        now = time.monotonic()

        # 尝试从 headers 获取 reset 时间
        reset_seconds = None
        if response:
            reset_seconds = self._parse_rate_limit_headers(response)

        # 如果没有 reset header，使用随机回退时间
        if reset_seconds is None:
            base = random.uniform(COOLDOWN_FALLBACK_MIN, COOLDOWN_FALLBACK_MAX)
        else:
            base = reset_seconds

        # 添加随机 jitter 避免同时重试
        total = base + random.uniform(COOLDOWN_JITTER_MIN, COOLDOWN_JITTER_MAX)

        previous_until = self.cooldown_until
        new_until = max(previous_until, now + total)
        self.cooldown_until = new_until

        if previous_until <= now:
            logger.warning(f"🚫 Reddit JSON API 进入冷却期: {status_code}, 冷却 {total:.0f} 秒")
        else:
            logger.debug(f"延长冷却期至 {new_until - now:.0f} 秒")

    async def _get_session(self) -> AsyncSession:
        """获取或创建 session"""
        if self.session is None:
            proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None
            self.session = AsyncSession(
                impersonate=self.current_browser,
                proxies=proxies
            )
            logger.info(f"🌐 Reddit JSON 客户端使用浏览器指纹: {self.current_browser}")
        return self.session

    async def _rotate_browser(self):
        """轮换浏览器指纹"""
        if not self.rotate_browser:
            return

        # 关闭旧 session
        if self.session:
            await self.session.close()
            self.session = None

        # 随机选择新浏览器（排除当前浏览器）
        available = [b for b in BROWSER_POOL if b != self.current_browser]
        self.current_browser = random.choice(available)
        logger.info(f"🔄 切换浏览器指纹: {self.current_browser}")

    async def _make_request(self, url: str, retry_on_403: bool = True) -> Dict[str, Any]:
        """发送 HTTP 请求（带 circuit breaker 和并发控制）"""
        # 检查是否在冷却期
        if not self.is_available():
            remaining = self.cooldown_remaining()
            raise Exception(f"Reddit JSON API 冷却中，剩余 {remaining:.0f} 秒")

        # 并发控制
        async with self.semaphore:
            try:
                session = await self._get_session()
                # 完整的浏览器 headers，模拟真实浏览器行为
                headers = {
                    'User-Agent': self.user_agent,
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'DNT': '1',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'none',
                    'Sec-Fetch-User': '?1',
                }

                response = await session.get(url, headers=headers, timeout=15)

                # Circuit breaker: 处理 429/403
                if response.status_code in (429, 403):
                    self._set_cooldown(response.status_code, response)

                    # 如果是 403 且允许重试，尝试轮换浏览器
                    if response.status_code == 403 and retry_on_403 and self.rotate_browser:
                        logger.warning(f"⚠️ 收到 403 响应，尝试轮换浏览器重试...")
                        await self._rotate_browser()
                        return await self._make_request(url, retry_on_403=False)  # 只重试一次

                    # 抛出异常让上层处理（可能回退到 OAuth）
                    raise Exception(f"Reddit API {response.status_code}: 已进入冷却期")

                response.raise_for_status()
                return response.json()

            except Exception as e:
                logger.error(f"Reddit JSON 请求失败 ({url}): {e}")
                raise

    def _parse_post(self, post_data: Dict[str, Any]) -> RedditPost:
        """解析帖子数据"""
        preview_image_url = ""
        if 'preview' in post_data and 'images' in post_data['preview']:
            images = post_data['preview']['images']
            if images:
                preview_image_url = images[0]['source']['url'].replace('&amp;', '&')

        video_url = ""
        is_video = post_data.get('is_video', False)
        if is_video and 'media' in post_data and post_data['media']:
            reddit_video = post_data['media'].get('reddit_video', {})
            video_url = reddit_video.get('fallback_url', '')

        gallery_items = []
        if 'gallery_data' in post_data:
            gallery_data = post_data['gallery_data']
            if 'items' in gallery_data:
                for item in gallery_data['items']:
                    media_id = item['media_id']
                    if 'media_metadata' in post_data and media_id in post_data['media_metadata']:
                        media = post_data['media_metadata'][media_id]
                        if 's' in media and 'u' in media['s']:
                            img_url = media['s']['u'].replace('&amp;', '&')
                            gallery_items.append(img_url)

        return RedditPost(
            id=post_data['id'],
            title=post_data['title'],
            author=post_data.get('author', '[deleted]'),
            subreddit=post_data['subreddit'],
            score=post_data['score'],
            num_comments=post_data['num_comments'],
            url=post_data['url'],
            permalink=f"https://www.reddit.com{post_data['permalink']}",
            created_utc=post_data['created_utc'],
            is_self=post_data['is_self'],
            selftext=post_data.get('selftext', ''),
            post_hint=post_data.get('post_hint', ''),
            is_video=is_video,
            preview_image_url=preview_image_url,
            video_url=video_url,
            gallery_items=gallery_items
        )

    async def get_post_by_id(self, post_id: str) -> Optional[RedditPost]:
        """通过 ID 获取帖子"""
        try:
            clean_id = post_id.replace('t3_', '')
            url = f"{self.base_url}/comments/{clean_id}.json?limit=1"

            data = await self._make_request(url)

            if isinstance(data, list) and len(data) > 0:
                post_data = data[0]['data']['children'][0]['data']
                return self._parse_post(post_data)

            return None

        except Exception as e:
            logger.error(f"获取帖子失败 (ID: {post_id}): {e}")
            return None

    async def get_post_by_url(self, url: str) -> Optional[RedditPost]:
        """通过 URL 获取帖子"""
        try:
            if not url.endswith('.json'):
                url = url.rstrip('/') + '.json'

            data = await self._make_request(url)

            if isinstance(data, list) and len(data) > 0:
                post_data = data[0]['data']['children'][0]['data']
                return self._parse_post(post_data)

            return None

        except Exception as e:
            logger.error(f"获取帖子失败 ({url}): {e}")
            return None

    async def get_hot_posts(self, subreddit: Optional[str] = None, limit: int = 10) -> List[RedditPost]:
        """获取热门帖子"""
        try:
            if subreddit:
                url = f"{self.base_url}/r/{subreddit}/hot.json?limit={limit}"
            else:
                url = f"{self.base_url}/hot.json?limit={limit}"

            data = await self._make_request(url)
            posts = []

            for item in data['data']['children']:
                post_data = item['data']
                posts.append(self._parse_post(post_data))

            logger.info(f"✅ 获取到 {len(posts)} 个热门帖子")
            return posts

        except Exception as e:
            logger.error(f"获取热门帖子失败: {e}")
            return []

    async def get_top_posts(self, subreddit: Optional[str] = None, time_filter: str = 'day', limit: int = 10) -> List[RedditPost]:
        """获取 Top 帖子"""
        try:
            if subreddit:
                url = f"{self.base_url}/r/{subreddit}/top.json?t={time_filter}&limit={limit}"
            else:
                url = f"{self.base_url}/top.json?t={time_filter}&limit={limit}"

            data = await self._make_request(url)
            posts = []

            for item in data['data']['children']:
                post_data = item['data']
                posts.append(self._parse_post(post_data))

            logger.info(f"✅ 获取到 {len(posts)} 个 Top 帖子")
            return posts

        except Exception as e:
            logger.error(f"获取 Top 帖子失败: {e}")
            return []

    async def get_new_posts(self, subreddit: Optional[str] = None, limit: int = 10) -> List[RedditPost]:
        """获取最新帖子"""
        try:
            if subreddit:
                url = f"{self.base_url}/r/{subreddit}/new.json?limit={limit}"
            else:
                url = f"{self.base_url}/new.json?limit={limit}"

            data = await self._make_request(url)
            posts = []

            for item in data['data']['children']:
                post_data = item['data']
                posts.append(self._parse_post(post_data))

            logger.info(f"✅ 获取到 {len(posts)} 个最新帖子")
            return posts

        except Exception as e:
            logger.error(f"获取最新帖子失败: {e}")
            return []

    async def get_comments(self, post_id: str, limit: int = 10, sort: str = 'top') -> List[RedditComment]:
        """获取评论"""
        try:
            clean_id = post_id.replace('t3_', '')
            url = f"{self.base_url}/comments/{clean_id}.json?sort={sort}&limit={limit}"

            data = await self._make_request(url)

            if isinstance(data, list) and len(data) > 1:
                comments_listing = data[1]['data']['children']
                comments = []

                for item in comments_listing:
                    if item['kind'] == 't1':
                        comment_data = item['data']
                        if comment_data.get('body'):
                            comments.append(RedditComment(
                                id=comment_data['id'],
                                author=comment_data.get('author', '[deleted]'),
                                body=comment_data['body'],
                                score=comment_data['score'],
                                created_utc=comment_data['created_utc']
                            ))

                        if len(comments) >= limit:
                            break

                logger.info(f"✅ 获取到 {len(comments)} 条评论")
                return comments

            return []

        except Exception as e:
            logger.error(f"获取评论失败: {e}")
            return []

    async def close(self):
        """关闭 session"""
        if self.session:
            await self.session.close()
            self.session = None

    @staticmethod
    def get_url_hash(url: str) -> str:
        """生成 URL 的哈希值"""
        return hashlib.md5(url.encode()).hexdigest()[:16]
