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

logger = logging.getLogger(__name__)

# 全局缓存：存储解析结果（5分钟TTL）
_parse_cache: Dict[str, Dict[str, Any]] = {}
_cache_timestamps: Dict[str, float] = {}
CACHE_TTL = 300  # 5分钟


def _build_cached_inline_results(cached_data: dict, url: str) -> list:
    """使用file_id缓存构建inline结果（直接使用Telegram服务器上的文件）"""
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 原链接", url=url)]])

    file_id = cached_data.get("file_id")
    file_type = cached_data.get("file_type", "video")
    title = cached_data.get("title", "无标题")[:60]
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
    # 清理过期缓存
    _clean_expired_cache()

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

        title = (parse_result.title or "无标题")[:60]  # Telegram限制64字符
        description = (parse_result.content or "点击下载")[:100]

        # 获取缩略图
        thumb_url = None
        if isinstance(parse_result, VideoParseResult) and parse_result.media:
            thumb_url = getattr(parse_result.media, 'thumb_url', None)
        elif isinstance(parse_result, ImageParseResult) and parse_result.media:
            if isinstance(parse_result.media, list) and len(parse_result.media) > 0:
                thumb_url = str(parse_result.media[0].path) if hasattr(parse_result.media[0], 'path') else None

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
            # 缓存解析结果（使用 result_id）
            _parse_cache[result_id] = {
                "url": url,
                "parse_result": parse_result,
                "query": query,
            }
            _cache_timestamps[result_id] = time.time()

            # 构建 caption（用于inline结果预览）
            caption_parts = []
            if parse_result.title:
                caption_parts.append(parse_result.title)
            if parse_result.content:
                caption_parts.append(parse_result.content[:100])
            caption_text = "\n\n".join(caption_parts) if caption_parts else "⏳ 下载中..."

            # 添加原链接按钮
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 原链接", url=url)]])

            return [
                InlineQueryResultPhoto(
                    id=result_id,
                    photo_url=thumb_url or "https://img.icons8.com/color/512/000000/video.png",
                    thumbnail_url=thumb_url or "https://img.icons8.com/color/96/000000/video.png",
                    title=f"🎬 视频 {title}",
                    description=description,
                    caption=caption_text,
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
                    results.append(
                        InlineQueryResultPhoto(
                            id=f"parse_image_{uuid4()}",
                            photo_url=item_url or item_thumb or "https://img.icons8.com/color/512/000000/image.png",
                            thumbnail_url=item_thumb or item_url or "https://img.icons8.com/color/96/000000/image.png",
                            title=f"🖼️ 图片 {index + 1}/{len(media_list)} - {title}",
                            description=description,
                            caption=caption_text,
                            photo_width=getattr(media_item, 'width', None) or 300,
                            photo_height=getattr(media_item, 'height', None) or 300,
                            reply_markup=keyboard,
                        )
                    )
                elif isinstance(media_item, (VideoRef, AniRef)):
                    # 视频/动画 → 返回照片（缩略图），用户选择后自动下载
                    result_id = f"parse_video_{uuid4()}"
                    # 缓存解析结果（使用 result_id，包含 media_index）
                    _parse_cache[result_id] = {
                        "url": url,
                        "parse_result": parse_result,
                        "query": query,
                        "media_index": index,
                    }
                    _cache_timestamps[result_id] = time.time()

                    results.append(
                        InlineQueryResultPhoto(
                            id=result_id,
                            photo_url=item_thumb or "https://img.icons8.com/color/512/000000/video.png",
                            thumbnail_url=item_thumb or "https://img.icons8.com/color/96/000000/video.png",
                            title=f"🎬 视频 {index + 1}/{len(media_list)} - {title}",
                            description=description,
                            caption=caption_text,
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
                    message_text=f"❌ 解析失败\n\n错误: {str(e)}"
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

    # 只处理视频（ID 以 parse_video_ 开头），图片直接用 URL 不需要下载
    if not result_id.startswith("parse_video_"):
        return

    # 从缓存中获取解析结果（使用 result_id）
    cached_data = _parse_cache.pop(result_id, None)
    _cache_timestamps.pop(result_id, None)

    if not cached_data:
        # 缓存过期或不存在
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

    # 获取 parse_adapter
    parse_adapter = context.bot_data.get("parse_adapter")
    if not parse_adapter:
        try:
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

        # 构建 caption（不使用 HTML 格式，避免解析问题）
        caption_parts = []
        if parse_result.title:
            caption_parts.append(parse_result.title)

        if parse_result.content:
            content = _format_text(parse_result.content)
            caption_parts.append(content)

        # 先构建内容部分（不含链接）
        content_text = "\n\n".join(caption_parts) if caption_parts else "无标题"

        # 链接部分（纯文本）
        link_part = f'\n\n🔗 原链接: {url}'

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


        # 根据类型处理（只处理视频和混合媒体中的视频）
        if isinstance(parse_result, (VideoParseResult, ImageParseResult, MultimediaParseResult)):
            # 视频/混合媒体中的视频
            await _handle_video_inline(
                context, inline_message_id, parse_result, parse_adapter, caption, url, media_index
            )
        else:
            # 其他类型（不应该到这里，因为前面已经过滤了）
            await context.bot.edit_message_caption(
                inline_message_id=inline_message_id,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN_V2
            )

    except Exception as e:
        logger.error(f"[Inline Parse] 处理失败: {e}", exc_info=True)
        try:
            await context.bot.edit_message_caption(
                inline_message_id=inline_message_id,
                caption=f"❌ 处理失败\n\n错误: {str(e)}"
            )
        except Exception as ex:
            logger.error(f"[Inline Parse] 更新错误消息失败: {ex}")


async def _handle_richtext_inline(
    context: ContextTypes.DEFAULT_TYPE,
    inline_message_id: str,
    parse_result,
    parse_adapter,
    caption: str,
    url: str
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
            # 成功
            await context.bot.edit_message_text(
                inline_message_id=inline_message_id,
                text=f"{caption}\n\n📰 [查看完整文章]({telegraph_url})",
                parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            # 失败
            await context.bot.edit_message_text(
                inline_message_id=inline_message_id,
                text=f"{caption}\n\n❌ Telegraph 发布失败",
                parse_mode=ParseMode.MARKDOWN_V2
            )
    except Exception as e:
        logger.error(f"富文本 inline 处理失败: {e}", exc_info=True)
        await context.bot.edit_message_text(
            inline_message_id=inline_message_id,
            text=f"❌ Telegraph 发布失败\n\n错误: {str(e)}"
        )


async def _handle_video_inline(
    context: ContextTypes.DEFAULT_TYPE,
    inline_message_id: str,
    parse_result,
    parse_adapter,
    caption: str,
    url: str,
    media_index: int = 0
) -> None:
    """处理视频 inline 结果"""
    try:
        # 更新状态（现在是照片消息，用 edit_message_caption）
        await context.bot.edit_message_caption(
            inline_message_id=inline_message_id,
            caption="📥 下载中..."
        )

        # 下载视频
        download_result = await parse_result.download(
            path=parse_adapter.temp_dir,
            proxy=parse_adapter.config.downloader_proxy if parse_adapter.config else None
        )

        if not download_result or not download_result.media:
            await context.bot.edit_message_caption(
                inline_message_id=inline_message_id,
                caption=f"{caption}\n\n❌ 下载失败",
                parse_mode=ParseMode.MARKDOWN_V2
            )
            return

        media = download_result.media
        video_path = Path(media.path)

        # 检查文件大小
        from utils.video_splitter import ensure_h264

        video_path = Path(await ensure_h264(str(video_path)))
        video_size_mb = video_path.stat().st_size / (1024 * 1024)

        if video_size_mb <= 50:
            # ≤50MB → 直接上传（替换照片为视频）
            await context.bot.edit_message_caption(
                inline_message_id=inline_message_id,
                caption=f"📤 上传中... ({video_size_mb:.1f}MB)"
            )

            from telegram import InputMediaVideo

            with open(video_path, 'rb') as video_file:
                # 构建 InputMediaVideo 参数（不使用 parse_mode）
                media_kwargs = {
                    "media": video_file,
                    "caption": caption,
                    "width": media.width or 0,
                    "height": media.height or 0,
                    "duration": media.duration or 0,
                    "supports_streaming": True,
                }

                result = await context.bot.edit_message_media(
                    inline_message_id=inline_message_id,
                    media=InputMediaVideo(**media_kwargs),
                )

                # 保存file_id到缓存
                if result and hasattr(result, 'video') and result.video:
                    cache_manager = context.bot_data.get("cache_manager")
                    if cache_manager:
                        try:
                            await cache_manager.set(
                                url,
                                {
                                    "file_id": result.video.file_id,
                                    "file_type": "video",
                                    "title": parse_result.title or "无标题",
                                    "caption": caption,
                                },
                                subdirectory="inline_parse"
                            )
                            logger.info(f"[Inline Parse] 已保存file_id到缓存: {url[:50]}...")
                        except Exception as e:
                            logger.warning(f"[Inline Parse] 保存file_id失败: {e}")
        else:
            # >50MB → 上传到图床
            await context.bot.edit_message_caption(
                inline_message_id=inline_message_id,
                caption=f"📤 视频过大 ({video_size_mb:.1f}MB)，上传到图床中..."
            )

            image_host_url = await parse_adapter.upload_to_image_host(video_path)

            if image_host_url:
                # 图床成功
                size_text = f"{video_size_mb:.1f}".replace(".", "\\.")
                await context.bot.edit_message_caption(
                    inline_message_id=inline_message_id,
                    caption=f"{caption}\n\n⚠️ 视频文件过大 \\({size_text}MB\\)\n📤 已上传到图床\n🔗 [点击查看视频]({image_host_url})",
                    parse_mode=ParseMode.MARKDOWN_V2
                )
            else:
                # 图床失败
                size_text = f"{video_size_mb:.1f}".replace(".", "\\.")
                await context.bot.edit_message_caption(
                    inline_message_id=inline_message_id,
                    caption=f"{caption}\n\n⚠️ 视频文件过大 \\({size_text}MB\\)，无法上传\n💡 请使用 `/parse {url}` 命令获取完整视频",
                    parse_mode=ParseMode.MARKDOWN_V2
                )

        # 清理临时文件
        try:
            import shutil
            shutil.rmtree(download_result.output_dir, ignore_errors=True)
        except Exception:
            pass

    except Exception as e:
        logger.error(f"视频 inline 处理失败: {e}", exc_info=True)
        await context.bot.edit_message_caption(
            inline_message_id=inline_message_id,
            caption=f"❌ 视频处理失败\n\n错误: {str(e)}"
        )


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
            text=f"❌ 图片处理失败\n\n错误: {str(e)}"
        )
