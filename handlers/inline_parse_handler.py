#!/usr/bin/env python3
"""
Inline Parse 处理器
支持在 inline mode 中解析社交媒体链接并发送视频/图片
"""

import asyncio
import logging
import time
from pathlib import Path
from typing import Optional, Dict, Any
from uuid import uuid4

from telegram import Update, InlineQueryResultArticle, InlineQueryResultPhoto, InlineQueryResultCachedVideo, InlineQueryResultCachedPhoto, InputTextMessageContent, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from utils.config_manager import ConfigManager
from utils.media_helpers import get_media_dimensions

logger = logging.getLogger(__name__)

# 全局缓存：存储解析结果（5分钟TTL）
_parse_cache: Dict[str, Dict[str, Any]] = {}
_cache_timestamps: Dict[str, float] = {}
CACHE_TTL = 300  # 5分钟
CACHE_CLEANUP_INTERVAL = 60  # 清理间隔：60秒

# 后台清理任务
_cleanup_task: Optional[asyncio.Task] = None


async def _cache_cleanup_loop():
    """后台缓存清理循环任务"""
    while True:
        try:
            await asyncio.sleep(CACHE_CLEANUP_INTERVAL)
            current_time = time.time()
            expired_keys = [
                key for key, timestamp in _cache_timestamps.items()
                if current_time - timestamp > CACHE_TTL
            ]
            for key in expired_keys:
                _parse_cache.pop(key, None)
                _cache_timestamps.pop(key, None)

            if expired_keys:
                logger.debug(f"[Cache] 清理了 {len(expired_keys)} 个过期缓存项，当前缓存数: {len(_parse_cache)}")
        except Exception as e:
            logger.error(f"[Cache] 清理任务异常: {e}", exc_info=True)


def start_cache_cleanup_task():
    """启动后台缓存清理任务"""
    global _cleanup_task
    if _cleanup_task is None or _cleanup_task.done():
        _cleanup_task = asyncio.create_task(_cache_cleanup_loop())
        logger.info("[Cache] 后台清理任务已启动")


def stop_cache_cleanup_task():
    """停止后台缓存清理任务"""
    global _cleanup_task
    if _cleanup_task and not _cleanup_task.done():
        _cleanup_task.cancel()
        logger.info("[Cache] 后台清理任务已停止")


def _clean_expired_cache():
    """清理过期缓存（已弃用，保留用于兼容性）"""
    # 现在由后台任务处理，这个函数保留但不做任何事
    pass


def _build_cached_inline_results(cached_data: dict, url: str) -> list:

    """使用file_id缓存构建inline结果（直接使用Telegram服务器上的文件）"""
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 原链接", url=url)]])

    file_id = cached_data.get("file_id")
    file_type = cached_data.get("file_type", "video")
    title = (cached_data.get("title", "") or "").strip() or "无标题"
    title = title[:60]  # Telegram限制
    caption = cached_data.get("caption", "")

    if file_type == "video":
        return [
            InlineQueryResultCachedVideo(
                id=str(uuid4()),
                video_file_id=file_id,
                title=f"🎬 {title}",
                caption=caption,
                reply_markup=keyboard,
            )
        ]
    elif file_type == "photo":
        return [
            InlineQueryResultCachedPhoto(
                id=str(uuid4()),
                photo_file_id=file_id,
                title=f"🖼️ {title}",
                caption=caption,
                reply_markup=keyboard,
            )
        ]
    else:
        # 未知类型，返回普通结果
        return []


def _clean_expired_cache():
    """清理过期缓存"""
    current_time = time.time()
    expired_keys = [
        key for key, timestamp in _cache_timestamps.items()
        if current_time - timestamp > CACHE_TTL
    ]
    for key in expired_keys:
        _parse_cache.pop(key, None)
        _cache_timestamps.pop(key, None)


def _remove_cache_entry(result_id: str):
    """删除指定的缓存条目（上传成功后调用）"""
    _parse_cache.pop(result_id, None)
    _cache_timestamps.pop(result_id, None)


async def handle_inline_parse_query(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    query: str
) -> list:
    """
    处理 inline parse 查询

    Args:
        update: Telegram Update
        context: Context
        query: 查询字符串（URL）

    Returns:
        InlineQueryResult 列表
    """
    # 获取 parse_adapter
    parse_adapter = context.bot_data.get("parse_adapter")
    if not parse_adapter:
        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="❌ 解析功能未初始化",
                description="Parse 功能未配置",
                input_message_content=InputTextMessageContent(
                    message_text="❌ 解析功能未初始化，请联系管理员"
                ),
            )
        ]

    # 提取原始URL
    url = await parse_adapter._extract_url(query)
    if not url:
        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="❌ 未找到有效URL",
                description=query[:50],
                input_message_content=InputTextMessageContent(
                    message_text="❌ 未找到有效的URL"
                ),
            )
        ]

    # 检查file_id缓存
    cache_manager = context.bot_data.get("cache_manager")
    if cache_manager:
        try:
            cached_data = await cache_manager.get(url, subdirectory="inline_parse")
            if cached_data:
                logger.info(f"[Inline Parse] file_id缓存命中: {url[:50]}...")
                return _build_cached_inline_results(cached_data, url)
        except Exception as e:
            logger.warning(f"[Inline Parse] 读取file_id缓存失败: {e}")

    # 检查是否支持该 URL
    is_supported = await parse_adapter.check_url_supported(query)
    if not is_supported:
        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="❌ 不支持的平台",
                description=f"URL: {query[:50]}...",
                input_message_content=InputTextMessageContent(
                    message_text=f"❌ 不支持的平台\n\n支持：抖音、B站、YouTube、TikTok、小红书、Twitter等20+平台"
                ),
            )
        ]

    # 快速解析（只解析，不下载）
    try:
        from parsehub import ParseHub
        parsehub = ParseHub()

        # 提取 URL
        url = await parse_adapter._extract_url(query)
        if not url:
            return [
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title="❌ 未找到有效URL",
                    description=query[:50],
                    input_message_content=InputTextMessageContent(
                        message_text="❌ 未找到有效的URL"
                    ),
                )
            ]

        # 解析（不下载）
        parse_result = await parsehub.parse(url)
        if not parse_result:
            return [
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title="❌ 解析失败",
                    description=url[:50],
                    input_message_content=InputTextMessageContent(
                        message_text="❌ 解析失败，请检查链接是否正确"
                    ),
                )
            ]

        # 记录解析结果类型
        logger.info(f"[Inline Parse] URL: {url[:50]}... | 类型: {type(parse_result).__name__} | 标题: {parse_result.title[:30] if parse_result.title else 'None'}")

        # 构建 inline 结果
        from parsehub.types import VideoParseResult, ImageParseResult, RichTextParseResult, MultimediaParseResult

        title = ((parse_result.title or "").strip() or "无标题")[:60]  # Telegram限制64字符
        description = ((parse_result.content or "").strip() or "点击下载")[:100]

        # 获取缩略图
        thumb_url = None
        if isinstance(parse_result, VideoParseResult) and parse_result.media:
            thumb_url = getattr(parse_result.media, 'thumb_url', None)
        elif isinstance(parse_result, ImageParseResult) and parse_result.media:
            if isinstance(parse_result.media, list) and len(parse_result.media) > 0:
                thumb_url = str(parse_result.media[0].path) if hasattr(parse_result.media[0], 'path') else None

        # InlineQueryResultPhoto 的 photo_url 不支持 WebP，跳过使用默认图片
        if thumb_url and thumb_url.endswith('.webp'):
            thumb_url = None
        # Instagram/Threads/XHS CDN 链接有时效性，Telegram 服务器可能无法访问
        if thumb_url and ('cdninstagram.com' in thumb_url or 'fbcdn.net' in thumb_url or 'xhscdn.com' in thumb_url):
            thumb_url = None

        # 根据类型返回不同的结果
        if isinstance(parse_result, RichTextParseResult):
            # 富文本 → 提示将发布到 Telegraph
            result_id = f"parse_richtext_{uuid4()}"
            # 缓存解析结果（使用 result_id）
            _parse_cache[result_id] = {
                "url": url,
                "parse_result": parse_result,
                "query": query,
            }
            _cache_timestamps[result_id] = time.time()

            # 添加原链接按钮
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 原链接", url=url)]])

            return [
                InlineQueryResultArticle(
                    id=result_id,
                    title=f"📰 {title}",
                    description="富文本内容 - 点击发布到 Telegraph",
                    thumbnail_url=thumb_url or "https://img.icons8.com/color/96/000000/news.png",
                    input_message_content=InputTextMessageContent(
                        message_text="⏳ 正在发布到 Telegraph..."
                    ),
                    reply_markup=keyboard,
                )
            ]
        elif isinstance(parse_result, VideoParseResult):
            # 视频 → 返回缩略图照片，用户选择后自动下载并替换成视频
            result_id = f"parse_video_{uuid4()}"
            # 构建 caption（用于inline结果预览）
            caption_parts = []
            if parse_result.title:
                caption_parts.append(parse_result.title)
            if parse_result.content:
                caption_parts.append(parse_result.content[:100])
            caption_text = "\n\n".join(caption_parts) if caption_parts else "⏳ 下载中..."

            # 添加原链接按钮
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 原链接", url=url)]])

            # 判断是否有有效缩略图
            is_article = not thumb_url

            # 缓存解析结果（使用 result_id），记录消息类型
            _parse_cache[result_id] = {
                "url": url,
                "parse_result": parse_result,
                "query": query,
                "is_article": is_article,
            }
            _cache_timestamps[result_id] = time.time()

            logger.info(f"[Inline Parse] 构建视频结果: title={title[:30]}, thumb={thumb_url}, is_article={is_article}, caption_len={len(caption_text)}")

            if not is_article:
                # 有有效缩略图 → 使用 InlineQueryResultPhoto
                return [
                    InlineQueryResultPhoto(
                        id=result_id,
                        photo_url=thumb_url,
                        thumbnail_url=thumb_url,
                        title=f"🎬 视频 {title}",
                        description=description,
                        caption=caption_text,
                        reply_markup=keyboard,
                    )
                ]
            else:
                # 无缩略图（WebP等不支持的格式） → 使用 InlineQueryResultArticle
                logger.info(f"[Inline Parse] 无有效缩略图，使用 Article 类型: {title[:30]}")
                return [
                    InlineQueryResultArticle(
                        id=result_id,
                        title=f"🎬 视频 {title}",
                        description=description,
                        thumbnail_url="https://img.icons8.com/color/96/000000/video.png",
                        input_message_content=InputTextMessageContent(
                            message_text=caption_text or "⏳ 下载中..."
                        ),
                        reply_markup=keyboard,
                    )
                ]
        elif isinstance(parse_result, (ImageParseResult, MultimediaParseResult)):
            # 图片/混合媒体 → 返回多个结果（每个媒体一个）
            results = []
            media_list = parse_result.media if isinstance(parse_result.media, list) else [parse_result.media]

            # 构建 caption
            caption_parts = []
            if parse_result.title:
                caption_parts.append(parse_result.title)
            if parse_result.content:
                caption_parts.append(parse_result.content[:100])
            caption_text = "\n\n".join(caption_parts) if caption_parts else ""

            # 添加原链接按钮
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 原链接", url=url)]])

            for index, media_item in enumerate(media_list):
                # 获取该媒体项的 URL 和缩略图
                item_url = None
                item_thumb = None
                if hasattr(media_item, 'url'):
                    item_url = media_item.url
                if hasattr(media_item, 'thumb_url'):
                    item_thumb = media_item.thumb_url

                # 判断媒体类型
                from parsehub.types import VideoRef, AniRef, ImageRef

                if isinstance(media_item, ImageRef):
                    # 图片 → 直接用 InlineQueryResultPhoto（不需要下载）
                    width, height = get_media_dimensions(media_item)
                    results.append(
                        InlineQueryResultPhoto(
                            id=f"parse_image_{uuid4()}",
                            photo_url=item_url or item_thumb or "https://img.icons8.com/color/512/000000/image.png",
                            thumbnail_url=item_thumb or item_url or "https://img.icons8.com/color/96/000000/image.png",
                            title=f"🖼️ 图片 {index + 1}/{len(media_list)} - {title}",
                            description=description,
                            caption=caption_text,
                            photo_width=width,
                            photo_height=height,
                            reply_markup=keyboard,
                        )
                    )
                elif isinstance(media_item, (VideoRef, AniRef)):
                    # 视频/动画 → 返回照片（缩略图），用户选择后自动下载
                    result_id = f"parse_video_{uuid4()}"
                    # 检查缩略图有效性（WebP不支持，CDN链接可能被Telegram拒绝）
                    valid_thumb = item_thumb
                    if valid_thumb and valid_thumb.endswith('.webp'):
                        valid_thumb = None
                    # Instagram/Threads/XHS CDN 链接有时效性，Telegram 服务器可能无法访问
                    if valid_thumb and ('cdninstagram.com' in valid_thumb or 'fbcdn.net' in valid_thumb or 'xhscdn.com' in valid_thumb):
                        valid_thumb = None
                    mm_is_article = not valid_thumb
                    # 缓存解析结果（使用 result_id，包含 media_index）
                    _parse_cache[result_id] = {
                        "url": url,
                        "parse_result": parse_result,
                        "query": query,
                        "media_index": index,
                        "is_article": mm_is_article,
                    }
                    _cache_timestamps[result_id] = time.time()

                    if valid_thumb:
                        results.append(
                            InlineQueryResultPhoto(
                                id=result_id,
                                photo_url=valid_thumb,
                                thumbnail_url=valid_thumb,
                                title=f"🎬 视频 {index + 1}/{len(media_list)} - {title}",
                                description=description,
                                caption=caption_text,
                                reply_markup=keyboard,
                            )
                        )
                    else:
                        results.append(
                            InlineQueryResultArticle(
                                id=result_id,
                                title=f"🎬 视频 {index + 1}/{len(media_list)} - {title}",
                                description=description,
                                thumbnail_url="https://img.icons8.com/color/96/000000/video.png",
                                input_message_content=InputTextMessageContent(
                                    message_text=caption_text or "⏳ 下载中..."
                                ),
                                reply_markup=keyboard,
                            )
                        )
                else:
                    # 未知类型 → 返回 Article
                    results.append(
                        InlineQueryResultArticle(
                            id=f"parse_unknown_{uuid4()}",
                            title=f"📄 媒体 {index + 1}/{len(media_list)} - {title}",
                            description=description,
                            thumbnail_url=item_thumb or "https://img.icons8.com/color/96/000000/file.png",
                            input_message_content=InputTextMessageContent(
                                message_text=f"{caption_text}\n\n🔗 [原链接]({url})",
                                parse_mode=ParseMode.MARKDOWN
                            ),
                        )
                    )

            return results if results else [
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title="❌ 无可用媒体",
                    description="该内容没有可显示的图片或视频",
                    input_message_content=InputTextMessageContent(
                        message_text=f"❌ 无可用媒体\n\n{title}\n\n🔗 原链接: {url}"
                    ),
                )
            ]
        else:
            return [
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title=f"📄 {title}",
                    description=description,
                    input_message_content=InputTextMessageContent(
                        message_text=f"**{title}**\n\n{description}\n\n🔗 [原链接]({url})",
                        parse_mode=ParseMode.MARKDOWN
                    ),
                )
            ]

    except Exception as e:
        logger.error(f"Inline parse 查询失败: {e}", exc_info=True)
        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="❌ 解析失败",
                description=str(e)[:100],
                input_message_content=InputTextMessageContent(
                    message_text=f"**❌ 解析失败:**\n```\n{str(e)}\n```"
                ),
            )
        ]


async def handle_inline_parse_chosen(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    处理用户选择 inline parse 结果后的下载和上传（仅处理视频）

    Args:
        update: Telegram Update
        context: Context
    """
    chosen_result = update.chosen_inline_result
    inline_message_id = chosen_result.inline_message_id
    result_id = chosen_result.result_id

    # 只处理视频和富文本，图片直接用 URL 不需要下载
    if not (result_id.startswith("parse_video_") or result_id.startswith("parse_richtext_")):
        return

    # 从缓存中获取解析结果（使用 result_id）
    # 注意：不立即删除缓存，等上传成功后再删除，这样失败时用户可以重试
    cached_data = _parse_cache.get(result_id, None)

    if not cached_data:
        # 缓存过期或不存在，不知道原始消息类型，尝试两种方式
        try:
            await context.bot.edit_message_text(
                inline_message_id=inline_message_id,
                text="❌ 解析结果已过期，请重新查询"
            )
        except Exception:
            try:
                await context.bot.edit_message_caption(
                    inline_message_id=inline_message_id,
                    caption="❌ 解析结果已过期，请重新查询"
                )
            except Exception:
                pass
        return

    parse_result = cached_data["parse_result"]
    url = cached_data["url"]
    media_index = cached_data.get("media_index", 0)  # 获取媒体索引（混合媒体用）
    is_article = cached_data.get("is_article", False)  # 是否为 Article 类型（无缩略图时）

    # 获取 parse_adapter
    parse_adapter = context.bot_data.get("parse_adapter")
    if not parse_adapter:
        try:
            if is_article:
                await context.bot.edit_message_text(
                    inline_message_id=inline_message_id,
                    text="❌ 解析功能未初始化"
                )
            else:
                await context.bot.edit_message_caption(
                    inline_message_id=inline_message_id,
                    caption="❌ 解析功能未初始化"
                )
        except Exception:
            pass
        return

    try:
        from parsehub.types import VideoParseResult, ImageParseResult, RichTextParseResult, MultimediaParseResult
        from commands.social_parser import _escape_markdown, _format_text

        # 构建 caption（使用 HTML 格式）
        from html import escape as html_escape

        caption_parts = []
        if parse_result.title:
            caption_parts.append(f"<b>{html_escape(parse_result.title)}</b>")

        if parse_result.content:
            content = _format_text(parse_result.content)
            caption_parts.append(html_escape(content))

        # 先构建内容部分（不含链接）
        content_text = "\n\n".join(caption_parts) if caption_parts else "无标题"

        # 链接部分（URL 也需要转义）
        escaped_url = html_escape(url)
        link_part = f'\n\n<b>🔗 <a href="{escaped_url}">原链接</a></b>'

        # Telegram caption 限制 1024 字节（不是字符！），必须严格控制
        max_total_bytes = 1020
        link_bytes = len(link_part.encode('utf-8'))
        max_content_bytes = max_total_bytes - link_bytes

        # 按字节截断内容
        content_bytes = content_text.encode('utf-8')
        if len(content_bytes) > max_content_bytes:
            # 截断到安全长度，避免截断到多字节字符中间
            safe_bytes = max_content_bytes - 10  # 留出 "..." 和安全边界
            content_text = content_bytes[:safe_bytes].decode('utf-8', errors='ignore') + "..."

        caption = content_text + link_part


        # 根据类型处理
        if isinstance(parse_result, RichTextParseResult):
            # 富文本 → 发布到 Telegraph
            await _handle_richtext_inline(
                context, inline_message_id, parse_result, parse_adapter, caption, url, result_id
            )
        elif isinstance(parse_result, (VideoParseResult, ImageParseResult, MultimediaParseResult)):
            # 视频/混合媒体中的视频
            await _handle_video_inline(
                context, inline_message_id, parse_result, parse_adapter, caption, url, media_index, is_article, result_id
            )
        else:
            # 其他类型（不应该到这里，因为前面已经过滤了）
            if is_article:
                await context.bot.edit_message_text(
                    inline_message_id=inline_message_id,
                    text=caption,
                    parse_mode=ParseMode.MARKDOWN_V2
                )
            else:
                await context.bot.edit_message_caption(
                    inline_message_id=inline_message_id,
                    caption=caption,
                    parse_mode=ParseMode.MARKDOWN_V2
                )

    except Exception as e:
        logger.error(f"[Inline Parse] 处理失败: {e}", exc_info=True)
        try:
            if is_article:
                await context.bot.edit_message_text(
                    inline_message_id=inline_message_id,
                    text=f"**❌ 处理失败:**\n```\n{str(e)}\n```"
                )
            else:
                await context.bot.edit_message_caption(
                    inline_message_id=inline_message_id,
                    caption=f"**❌ 处理失败:**\n```\n{str(e)}\n```"
                )
        except Exception as ex:
            logger.error(f"[Inline Parse] 更新错误消息失败: {ex}")


async def _handle_richtext_inline(
    context: ContextTypes.DEFAULT_TYPE,
    inline_message_id: str,
    parse_result,
    parse_adapter,
    caption: str,
    url: str,
    result_id: str
) -> None:
    """处理富文本 inline 结果（发布到 Telegraph）"""
    try:
        from markdown import markdown

        # 更新状态
        await context.bot.edit_message_text(
            inline_message_id=inline_message_id,
            text="📰 发布到 Telegraph 中..."
        )

        # 转换为 HTML
        md_content = parse_result.markdown_content
        if parse_result.platform.id == 'weixin':
            md_content = md_content.replace("mmbiz.qpic.cn", "mmbiz.qpic.cn.in")
        elif parse_result.platform.id == 'coolapk':
            md_content = md_content.replace("image.coolapk.com", "qpic.cn.in/image.coolapk.com")

        html_content = markdown(md_content)

        # 发布到 Telegraph
        telegraph_url = await parse_adapter.publish_to_telegraph(parse_result, html_content)

        if telegraph_url:
            # 成功 → 清理缓存
            _remove_cache_entry(result_id)
            await context.bot.edit_message_text(
                inline_message_id=inline_message_id,
                text=f"{caption}\n\n📰 <a href=\"{telegraph_url}\">查看完整文章</a>",
                parse_mode=ParseMode.HTML
            )
        else:
            # 失败 → 保留缓存以便重试
            await context.bot.edit_message_text(
                inline_message_id=inline_message_id,
                text=f"{caption}\n\n❌ Telegraph 发布失败",
                parse_mode=ParseMode.HTML
            )
    except Exception as e:
        logger.error(f"富文本 inline 处理失败: {e}", exc_info=True)
        # 失败 → 保留缓存以便重试
        await context.bot.edit_message_text(
            inline_message_id=inline_message_id,
            text=f"**❌ Telegraph 发布失败:**\n```\n{str(e)}\n```"
        )


async def _handle_video_inline(
    context: ContextTypes.DEFAULT_TYPE,
    inline_message_id: str,
    parse_result,
    parse_adapter,
    caption: str,
    url: str,
    media_index: int = 0,
    is_article: bool = False,
    result_id: str = None
) -> None:
    """处理视频 inline 结果"""
    try:
        # Helper: Article 类型用 edit_message_text，Photo 类型用 edit_message_caption
        async def _update_status(text: str, parse_mode=None):
            if is_article:
                await context.bot.edit_message_text(
                    inline_message_id=inline_message_id,
                    text=text,
                    parse_mode=parse_mode
                )
            else:
                await context.bot.edit_message_caption(
                    inline_message_id=inline_message_id,
                    caption=text,
                    parse_mode=parse_mode
                )

        # 更新状态
        await _update_status("📥 下载中...")

        # 下载视频
        download_result = await parse_result.download(
            path=parse_adapter.temp_dir,
            proxy=parse_adapter.config.downloader_proxy if parse_adapter.config else None
        )

        if not download_result or not download_result.media:
            await _update_status(f"{caption}\n\n❌ 下载失败")
            return

        media = download_result.media
        if isinstance(media, list):
            media = media[0]
        video_path = Path(media.path)

        # 检查文件大小
        from utils.video_splitter import ensure_h264

        video_path = Path(await ensure_h264(str(video_path)))
        video_size_mb = video_path.stat().st_size / (1024 * 1024)

        if video_size_mb <= 2048:  # 2GB limit via Pyrogram MTProto
            await _update_status(f"📤 上传中... ({video_size_mb:.1f}MB)")

            # 使用 Pyrogram 的 edit_inline_media 直接上传文件到 inline message
            # Pyrogram 通过 MTProto 协议，支持上传新文件到 inline message，无需临时频道
            from commands.social_parser import _adapter as parse_adapter_instance
            pyrogram_helper = getattr(parse_adapter_instance, 'pyrogram_helper', None)

            if pyrogram_helper and pyrogram_helper.is_started and pyrogram_helper.client:
                from pyrogram.types import InputMediaVideo as PyrogramInputMediaVideo
                from pyrogram.enums import ParseMode as PyrogramParseMode

                await pyrogram_helper.client.edit_inline_media(
                    inline_message_id=inline_message_id,
                    media=PyrogramInputMediaVideo(
                        media=str(video_path),
                        caption=caption,
                        parse_mode=PyrogramParseMode.HTML,
                        width=media.width or 0,
                        height=media.height or 0,
                        duration=media.duration or 0,
                        supports_streaming=True,
                    )
                )
                logger.info(f"[Inline Parse] Pyrogram edit_inline_media 成功: {url[:50]}...")
                # 上传成功 → 清理缓存
                if result_id:
                    _remove_cache_entry(result_id)
            else:
                # Pyrogram 不可用，fallback 到临时频道方案 (50MB 限制)
                if video_size_mb > 50:
                    # 超过 50MB 且无 Pyrogram，上传到图床
                    await _update_status(f"📤 视频过大 ({video_size_mb:.1f}MB)，上传到图床中...")
                    image_host_url = await parse_adapter.upload_to_image_host(video_path)
                    if image_host_url:
                        plain_caption = f"{parse_result.title or '无标题'}\n\n⚠️ 视频文件过大 ({video_size_mb:.1f}MB)\n📤 已上传到图床\n🔗 点击查看视频: {image_host_url}\n\n原链接: {url}"
                        # 上传成功 → 清理缓存
                        if result_id:
                            _remove_cache_entry(result_id)
                    else:
                        plain_caption = f"{parse_result.title or '无标题'}\n\n⚠️ 视频文件过大 ({video_size_mb:.1f}MB)，无法上传\n💡 请使用 /parse 命令获取完整视频\n\n原链接: {url}"
                        # 上传失败 → 保留缓存以便重试
                    await _update_status(plain_caption)
                else:
                    # ≤50MB，用临时频道方案
                    from telegram import InputMediaVideo
                    config_manager = ConfigManager()
                    temp_channel_id = config_manager.config.inline_parse_temp_channel

                    if not temp_channel_id:
                        logger.error("INLINE_PARSE_TEMP_CHANNEL not configured and Pyrogram not available")
                        await _update_status("❌ 配置错误：未设置临时存储频道且 Pyrogram 不可用")
                        return

                    with open(video_path, 'rb') as video_file:
                        sent_message = await context.bot.send_video(
                            chat_id=temp_channel_id,
                            video=video_file,
                            width=media.width or 0,
                            height=media.height or 0,
                            duration=media.duration or 0,
                            supports_streaming=True,
                            read_timeout=300,
                            write_timeout=300,
                            connect_timeout=30
                        )

                    result = await context.bot.edit_message_media(
                        inline_message_id=inline_message_id,
                        media=InputMediaVideo(
                            media=sent_message.video.file_id,
                            caption=caption,
                            parse_mode=ParseMode.HTML,
                            width=media.width or 0,
                            height=media.height or 0,
                            duration=media.duration or 0,
                            supports_streaming=True,
                        ),
                    )

                    # 上传成功 → 清理缓存
                    if result_id:
                        _remove_cache_entry(result_id)

                    try:
                        await context.bot.delete_message(chat_id=temp_channel_id, message_id=sent_message.message_id)
                    except Exception:
                        pass
        else:
            # >2GB → 上传到图床
            await _update_status(f"📤 视频过大 ({video_size_mb:.1f}MB)，上传到图床中...")
            image_host_url = await parse_adapter.upload_to_image_host(video_path)
            if image_host_url:
                plain_caption = f"{parse_result.title or '无标题'}\n\n⚠️ 视频文件过大 ({video_size_mb:.1f}MB)\n📤 已上传到图床\n🔗 点击查看视频: {image_host_url}\n\n原链接: {url}"
                # 上传成功 → 清理缓存
                if result_id:
                    _remove_cache_entry(result_id)
            else:
                plain_caption = f"{parse_result.title or '无标题'}\n\n⚠️ 视频文件过大 ({video_size_mb:.1f}MB)，无法上传\n💡 请使用 /parse 命令获取完整视频\n\n原链接: {url}"
                # 上传失败 → 保留缓存以便重试
            await _update_status(plain_caption)

        # 清理临时文件
        try:
            import shutil
            shutil.rmtree(download_result.output_dir, ignore_errors=True)
        except Exception:
            pass

    except Exception as e:
        logger.error(f"视频 inline 处理失败: {e}", exc_info=True)
        try:
            await _update_status(f"**❌ 视频处理失败:**\n```\n{str(e)}\n```")
        except Exception:
            pass


async def _handle_image_inline(
    context: ContextTypes.DEFAULT_TYPE,
    inline_message_id: str,
    parse_result,
    parse_adapter,
    caption: str,
    url: str,
    media_index: int = 0
) -> None:
    """处理图片 inline 结果"""
    try:
        # 更新状态
        await context.bot.edit_message_text(
            inline_message_id=inline_message_id,
            text="📥 下载中..."
        )

        # 下载图片
        download_result = await parse_result.download(
            path=parse_adapter.temp_dir,
            proxy=parse_adapter.config.downloader_proxy if parse_adapter.config else None
        )

        if not download_result or not download_result.media:
            await context.bot.edit_message_text(
                inline_message_id=inline_message_id,
                text=f"{caption}\n\n❌ 下载失败",
                parse_mode=ParseMode.MARKDOWN_V2
            )
            return

        media_list = download_result.media if isinstance(download_result.media, list) else [download_result.media]
        media_list = [m for m in media_list if m and hasattr(m, 'path') and m.path]

        # 如果指定了 media_index，只处理该索引的媒体
        if media_index > 0 and media_index < len(media_list):
            media_list = [media_list[media_index]]

        if len(media_list) == 0:
            await context.bot.edit_message_text(
                inline_message_id=inline_message_id,
                text=f"{caption}\n\n❌ 没有可用的图片",
                parse_mode=ParseMode.MARKDOWN_V2
            )
            return
        elif len(media_list) == 1:
            # 单张图片 → 直接发送
            await context.bot.edit_message_text(
                inline_message_id=inline_message_id,
                text="📤 上传中..."
            )

            from telegram import InputMediaPhoto
            from commands.social_parser import _convert_image_to_webp

            # 转换格式
            converted_path = _convert_image_to_webp(Path(media_list[0].path))

            with open(converted_path, 'rb') as photo_file:
                await context.bot.edit_message_media(
                    inline_message_id=inline_message_id,
                    media=InputMediaPhoto(
                        media=photo_file,
                        caption=caption,
                        parse_mode=ParseMode.MARKDOWN_V2,
                    ),
                )
        else:
            # 多张图片 → Telegraph
            await context.bot.edit_message_text(
                inline_message_id=inline_message_id,
                text=f"📤 {len(media_list)} 张图片，上传到图床中..."
            )

            from commands.social_parser import _generate_thumbnail
            from markdown import markdown

            # 上传到图床
            uploaded_urls = []
            for img in media_list:
                thumb_path = _generate_thumbnail(Path(img.path), max_width=800, quality=70)
                img_url = await parse_adapter.upload_to_image_host(thumb_path)
                if img_url:
                    uploaded_urls.append(img_url)

                # 清理缩略图
                if thumb_path != Path(img.path):
                    try:
                        thumb_path.unlink()
                    except Exception:
                        pass

            if uploaded_urls:
                # 创建 HTML
                html_content = ""
                if parse_result.content:
                    html_content += f"<p>{parse_result.content}</p>"

                for idx, img_url in enumerate(uploaded_urls):
                    loading = "eager" if idx < 3 else "lazy"
                    html_content += f'<figure><img src="{img_url}" loading="{loading}"/></figure>'

                html_content += f'<p><i>共 {len(uploaded_urls)} 张图片</i></p>'

                # 发布到 Telegraph
                telegraph_url = await parse_adapter.publish_to_telegraph(parse_result, html_content)

                if telegraph_url:
                    await context.bot.edit_message_text(
                        inline_message_id=inline_message_id,
                        text=f"{caption}\n\n📷 共 {len(media_list)} 张图片\n🔗 [查看完整图集]({telegraph_url})",
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
                else:
                    await context.bot.edit_message_text(
                        inline_message_id=inline_message_id,
                        text=f"{caption}\n\n📷 共 {len(media_list)} 张图片\n❌ Telegraph 发布失败",
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
            else:
                await context.bot.edit_message_text(
                    inline_message_id=inline_message_id,
                    text=f"{caption}\n\n📷 共 {len(media_list)} 张图片\n❌ 图床上传失败",
                    parse_mode=ParseMode.MARKDOWN_V2
                )

        # 清理临时文件
        try:
            import shutil
            shutil.rmtree(download_result.output_dir, ignore_errors=True)
        except Exception:
            pass

    except Exception as e:
        logger.error(f"图片 inline 处理失败: {e}", exc_info=True)
        await context.bot.edit_message_text(
            inline_message_id=inline_message_id,
            text=f"**❌ 图片处理失败:**\n```\n{str(e)}\n```"
        )
