#!/usr/bin/env python3
"""
Inline Reddit 处理器
支持在 inline mode 中解析 Reddit 帖子并发送
"""

import logging
import time
from uuid import uuid4
from typing import Dict, Any

from telegram import Update, InlineQueryResultArticle, InputTextMessageContent, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# 全局缓存：存储视频解析结果（5分钟TTL）
_reddit_video_cache: Dict[str, Dict[str, Any]] = {}
_cache_timestamps: Dict[str, float] = {}
CACHE_TTL = 300  # 5分钟


async def handle_inline_reddit_query(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    query: str
) -> list:
    """
    处理 inline Reddit 查询

    Args:
        update: Telegram Update
        context: Context
        query: 查询字符串（Reddit URL）

    Returns:
        InlineQueryResult 列表
    """
    # 获取 Reddit 客户端
    from commands import reddit_command
    reddit_client = reddit_command._reddit_client
    cache_manager = reddit_command._cache_manager
    ai_summarizer = reddit_command._ai_summarizer

    if not reddit_client:
        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="❌ Reddit 功能未初始化",
                description="Reddit 功能未配置",
                input_message_content=InputTextMessageContent(
                    message_text="❌ Reddit 功能未初始化，请联系管理员"
                ),
            )
        ]

    # 验证 URL
    if 'reddit.com' not in query:
        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="❌ 无效的 Reddit 链接",
                description=query[:50],
                input_message_content=InputTextMessageContent(
                    message_text="❌ 无效的 Reddit 链接"
                ),
            )
        ]

    # 解析帖子
    try:
        post = await reddit_client.get_post_by_url(query)

        if not post:
            return [
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title="❌ 获取帖子失败",
                    description="请检查链接是否正确",
                    input_message_content=InputTextMessageContent(
                        message_text="❌ 获取帖子失败，请检查链接是否正确"
                    ),
                )
            ]

        # 构建消息内容
        from commands.reddit_command import _escape_markdown, _format_timestamp
        caption_parts = []
        caption_parts.append(f"**{_escape_markdown(post.title)}**")
        caption_parts.append(f"👤 u/{_escape_markdown(post.author)} \\| 📊 {post.score} ⬆️ \\| 💬 {post.num_comments}")
        caption_parts.append(f"📍 r/{_escape_markdown(post.subreddit)} \\| 🕐 {_escape_markdown(_format_timestamp(post.created_utc))}")

        # 添加文本内容（如果是自发帖）
        if post.is_self and post.selftext:
            text_preview = post.selftext[:200]
            if len(post.selftext) > 200:
                text_preview += "..."
            caption_parts.append(f"\n{_escape_markdown(text_preview)}")

        caption_parts.append(f"\n🔗 [原帖链接]({post.permalink})")
        caption = "\n\n".join(caption_parts)

        # 创建 inline keyboard
        from utils.reddit_client import RedditClient
        url_hash = RedditClient.get_url_hash(post.permalink)

        buttons = [[InlineKeyboardButton("🔗 原帖链接", url=post.permalink)]]

        # 如果启用了 AI 总结，添加 AI 总结按钮
        if ai_summarizer:
            buttons[0].append(InlineKeyboardButton("📝 AI总结", callback_data=f"reddit_summary_{url_hash}"))

        reply_markup = InlineKeyboardMarkup(buttons)

        # 缓存帖子数据用于 AI 总结
        if cache_manager and ai_summarizer:
            cache_data = {
                'url': post.permalink,
                'title': post.title,
                'content': post.selftext,
                'author': post.author,
                'subreddit': post.subreddit,
                'score': post.score,
                'num_comments': post.num_comments,
                'created_utc': post.created_utc
            }
            await cache_manager.set(
                f"reddit_summary:{url_hash}",
                cache_data,
                ttl=86400,
                subdirectory="reddit"
            )

        # 返回结果 - 根据内容类型返回不同的结果
        from telegram import InlineQueryResultPhoto

        # Gallery：返回多张图片（缓存后在 chosen handler 中下载上传）
        if post.gallery_items and len(post.gallery_items) > 1:
            results = []
            for index, img_url in enumerate(post.gallery_items[:10], 1):  # 最多10张
                result_id = f"reddit_image_{uuid4()}"

                # 缓存图片信息（用于 chosen handler）
                _reddit_video_cache[result_id] = {
                    "post": post,
                    "caption": caption,
                    "url_hash": url_hash,
                    "reply_markup": reply_markup,
                    "image_url": img_url,
                    "image_index": index
                }
                _cache_timestamps[result_id] = time.time()

                # Reddit CDN 可能无法访问，使用 Article 类型 + fallback 图标
                results.append(
                    InlineQueryResultArticle(
                        id=result_id,
                        title=f"🖼️ 图片 {index}/{len(post.gallery_items)} - {post.title[:40]}",
                        description=f"r/{post.subreddit} | ⬆️ {post.score} | 💬 {post.num_comments}",
                        thumbnail_url="https://img.icons8.com/color/96/000000/image.png",
                        input_message_content=InputTextMessageContent(
                            message_text=caption,
                            parse_mode="MarkdownV2",
                            link_preview_options={"is_disabled": True}
                        ),
                        reply_markup=reply_markup
                    )
                )
            return results
        # 视频：返回缩略图照片，用户选择后自动下载并上传
        elif post.is_video and post.video_url and post.preview_image_url:
            result_id = f"reddit_video_{uuid4()}"
            # 缓存视频信息（用于 chosen handler）
            _reddit_video_cache[result_id] = {
                "post": post,
                "caption": caption,
                "url_hash": url_hash,
                "reply_markup": reply_markup
            }
            _cache_timestamps[result_id] = time.time()

            # Reddit CDN 可能无法访问，使用 Article 类型 + fallback 图标
            return [
                InlineQueryResultArticle(
                    id=result_id,
                    title=f"🎬 {post.title[:60]}",
                    description=f"r/{post.subreddit} | ⬆️ {post.score} | 💬 {post.num_comments}",
                    thumbnail_url="https://img.icons8.com/color/96/000000/video.png",
                    input_message_content=InputTextMessageContent(
                        message_text=caption,
                        parse_mode="MarkdownV2",
                        link_preview_options={"is_disabled": True}
                    ),
                    reply_markup=reply_markup
                )
            ]
        # 图片：返回图片（缓存后在 chosen handler 中下载上传）
        elif post.preview_image_url:
            result_id = f"reddit_image_{uuid4()}"

            # 缓存图片信息（用于 chosen handler）
            _reddit_video_cache[result_id] = {
                "post": post,
                "caption": caption,
                "url_hash": url_hash,
                "reply_markup": reply_markup,
                "image_url": post.preview_image_url,
                "image_index": 1
            }
            _cache_timestamps[result_id] = time.time()

            # Reddit CDN 可能无法访问，使用 Article 类型 + fallback 图标
            return [
                InlineQueryResultArticle(
                    id=result_id,
                    title=f"📝 {post.title[:60]}",
                    description=f"r/{post.subreddit} | ⬆️ {post.score} | 💬 {post.num_comments}",
                    thumbnail_url="https://img.icons8.com/color/96/000000/image.png",
                    input_message_content=InputTextMessageContent(
                        message_text=caption,
                        parse_mode="MarkdownV2",
                        link_preview_options={"is_disabled": True}
                    ),
                    reply_markup=reply_markup
                )
            ]
        # 无图片/视频：返回纯文本
        else:
            return [
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title=f"📝 {post.title[:60]}",
                    description=f"r/{post.subreddit} | ⬆️ {post.score} | 💬 {post.num_comments}",
                    input_message_content=InputTextMessageContent(
                        message_text=caption,
                        parse_mode="MarkdownV2",
                        link_preview_options={"is_disabled": True}
                    ),
                    reply_markup=reply_markup
                )
            ]

    except Exception as e:
        logger.error(f"Reddit inline 解析失败: {e}", exc_info=True)
        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="❌ 解析失败",
                description=str(e)[:100],
                input_message_content=InputTextMessageContent(
                    message_text=f"❌ 解析失败: {str(e)}"
                ),
            )
        ]


async def handle_inline_reddit_list(
    command_text: str,
    context: ContextTypes.DEFAULT_TYPE
) -> list:
    """
    处理 inline Reddit 列表查询 (hot/top)

    Args:
        command_text: 命令文本，如 "reddit hot python" 或 "reddit top python week"
        context: Context

    Returns:
        InlineQueryResult 列表
    """
    # 获取 Reddit 客户端
    from commands import reddit_command
    reddit_client = reddit_command._reddit_client

    if not reddit_client:
        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="❌ Reddit 功能未初始化",
                description="Reddit 功能未配置",
                input_message_content=InputTextMessageContent(
                    message_text="❌ Reddit 功能未初始化，请联系管理员"
                ),
            )
        ]

    # 解析命令
    parts = command_text.split()
    if len(parts) < 2:
        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="📝 使用方法",
                description="reddit hot/top/new [subreddit] [time]",
                input_message_content=InputTextMessageContent(
                    message_text="**📝 Reddit Inline 使用方法：**\n\n"
                                "• `reddit hot [subreddit]` - 热门帖子\n"
                                "• `reddit top [subreddit] [time]` - Top帖子\n"
                                "• `reddit new [subreddit]` - 最新帖子\n\n"
                                "**示例：**\n"
                                "• `reddit hot python`\n"
                                "• `reddit top python week`\n"
                                "• `reddit new python`",
                    parse_mode="Markdown"
                ),
            )
        ]

    list_type = parts[1].lower()  # hot, top 或 new

    # 获取帖子列表
    try:
        subreddit = None
        time_filter = 'day'  # 默认值

        if list_type == "hot":
            # 检查第二个参数是否是时间关键词（如果是，说明没有指定subreddit）
            subreddit = None
            if len(parts) > 2:
                second_arg = parts[2].lower()
                # 如果不是时间关键词，才当作subreddit
                if second_arg not in ['hour', 'day', 'week', 'month', 'year', 'all']:
                    subreddit = parts[2]

            posts = await reddit_client.get_hot_posts(subreddit=subreddit, limit=10)
            title_prefix = f"🔥 r/{subreddit} 热门" if subreddit else "🔥 Reddit 全站热门"
        elif list_type == "top":
            subreddit = None
            time_filter = 'day'

            # 解析参数：可能是 "top week" 或 "top python week"
            if len(parts) > 2:
                second_arg = parts[2].lower()
                if second_arg in ['hour', 'day', 'week', 'month', 'year', 'all']:
                    # 第二个参数是时间，没有subreddit
                    time_filter = second_arg
                else:
                    # 第二个参数是subreddit
                    subreddit = parts[2]
                    # 检查第三个参数是否是时间
                    if len(parts) > 3:
                        third_arg = parts[3].lower()
                        if third_arg in ['hour', 'day', 'week', 'month', 'year', 'all']:
                            time_filter = third_arg

            posts = await reddit_client.get_top_posts(subreddit=subreddit, time_filter=time_filter, limit=10)
            time_map = {'hour': '本小时', 'day': '今日', 'week': '本周', 'month': '本月', 'year': '今年', 'all': '全部时间'}
            time_text = time_map.get(time_filter, time_filter)
            # 转义括号
            title_prefix = f"🏆 r/{subreddit} Top \\({time_text}\\)" if subreddit else f"🏆 Reddit 全站 Top \\({time_text}\\)"
        elif list_type == "new":
            subreddit = None
            if len(parts) > 2:
                subreddit = parts[2]

            posts = await reddit_client.get_new_posts(subreddit=subreddit, limit=10)
            title_prefix = f"🆕 r/{subreddit} 最新" if subreddit else "🆕 Reddit 全站最新"
        else:
            return [
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title="❌ 无效的命令",
                    description="请使用 hot, top 或 new",
                    input_message_content=InputTextMessageContent(
                        message_text="❌ 无效的命令，请使用 `reddit hot`, `reddit top` 或 `reddit new`",
                        parse_mode="Markdown"
                    ),
                )
            ]

        if not posts:
            return [
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title="❌ 未找到帖子",
                    description="请检查 subreddit 名称",
                    input_message_content=InputTextMessageContent(
                        message_text="❌ 未找到帖子"
                    ),
                )
            ]

        # 构建消息
        from commands.reddit_command import _escape_markdown
        lines = [f"**{title_prefix}**\n"]

        for i, post in enumerate(posts, 1):
            post_title = _escape_markdown(post.title[:80])
            if len(post.title) > 80:
                post_title += "\\.\\.\\."

            lines.append(
                f"{i}\\. [{post_title}]({post.permalink})\n"
                f"   👤 u/{_escape_markdown(post.author)} \\| "
                f"⬆️ {post.score} \\| 💬 {post.num_comments}"
            )

        message_text = "\n".join(lines)

        # 创建 inline keyboard（添加 AI 翻译按钮）
        keyboard = []
        cache_manager = reddit_command._cache_manager
        ai_summarizer = reddit_command._ai_summarizer

        if ai_summarizer and cache_manager:
            # 缓存帖子列表数据用于AI翻译
            import hashlib
            # hot 命令没有 time_filter，使用空字符串
            hash_time = time_filter if list_type == "top" else ""
            list_hash = hashlib.md5(f"{list_type}_{subreddit}_{hash_time}_{len(posts)}".encode()).hexdigest()[:16]

            # 保存帖子完整信息到缓存
            titles_data = [{
                "title": p.title,
                "permalink": p.permalink,
                "author": p.author,
                "score": p.score,
                "num_comments": p.num_comments
            } for p in posts]
            await cache_manager.set(
                f"reddit_list:{list_hash}",
                titles_data,
                ttl=3600,  # 1小时
                subdirectory="reddit"
            )

            keyboard.append([
                InlineKeyboardButton("🌐 AI翻译", callback_data=f"reddit_translate_{list_hash}")
            ])

        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None

        # 返回单个结果
        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title=title_prefix,
                description=f"{len(posts)} 个帖子",
                input_message_content=InputTextMessageContent(
                    message_text=message_text,
                    parse_mode="MarkdownV2",
                    link_preview_options={"is_disabled": True}
                ),
                reply_markup=reply_markup
            )
        ]

    except Exception as e:
        logger.error(f"Reddit inline 列表获取失败: {e}", exc_info=True)
        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="❌ 获取失败",
                description=str(e)[:100],
                input_message_content=InputTextMessageContent(
                    message_text=f"❌ 获取失败: {str(e)}"
                ),
            )
        ]


async def handle_inline_reddit_chosen(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    处理用户选择 inline Reddit 视频结果后的下载和上传

    Args:
        update: Telegram Update
        context: Context
    """
    chosen_result = update.chosen_inline_result
    inline_message_id = chosen_result.inline_message_id
    result_id = chosen_result.result_id

    logger.info(f"[Inline Reddit Chosen] result_id={result_id}, inline_message_id={inline_message_id}")

    # 处理视频和图片
    if not (result_id.startswith("reddit_video_") or result_id.startswith("reddit_image_")):
        logger.info(f"[Inline Reddit Chosen] 跳过非 Reddit 媒体: {result_id}")
        return

    # 从缓存中获取视频信息
    cached_data = _reddit_video_cache.get(result_id, None)

    if not cached_data:
        # 缓存过期
        logger.warning(f"[Inline Reddit Chosen] 缓存未找到: {result_id}")
        try:
            await context.bot.edit_message_text(
                inline_message_id=inline_message_id,
                text="❌ 信息已过期，请重新查询"
            )
        except Exception:
            pass
        return

    logger.info(f"[Inline Reddit Chosen] 找到缓存，开始处理媒体")

    post = cached_data["post"]
    caption = cached_data["caption"]
    reply_markup = cached_data["reply_markup"]
    is_video = result_id.startswith("reddit_video_")
    is_image = result_id.startswith("reddit_image_")

    try:
        import tempfile
        from pathlib import Path
        from commands.reddit_command import _download_video, _download_image

        # 更新状态
        status_text = "📥 下载视频中..." if is_video else "📥 下载图片中..."
        await context.bot.edit_message_text(
            inline_message_id=inline_message_id,
            text=status_text
        )

        # 下载媒体
        temp_dir = Path(tempfile.gettempdir()) / "domobot_reddit"
        temp_dir.mkdir(exist_ok=True)

        if is_video:
            # 下载视频
            video_path = await _download_video(post.video_url, temp_dir)
            media_size_mb = video_path.stat().st_size / (1024 * 1024)
            media_path = video_path
            media_type = "video"
        else:
            # 下载图片
            image_url = cached_data.get("image_url", post.preview_image_url)
            image_path = await _download_image(image_url, temp_dir)
            media_size_mb = image_path.stat().st_size / (1024 * 1024)
            media_path = image_path
            media_type = "image"

        logger.info(f"[Inline Reddit] {media_type}下载完成: {media_size_mb:.1f}MB")

        # 检查文件大小
        if media_size_mb > 2048:
            # 超过 2GB，无法上传
            await context.bot.edit_message_text(
                inline_message_id=inline_message_id,
                text=f"{caption}\n\n⚠️ {media_type}过大 ({media_size_mb:.1f}MB)，无法上传",
                parse_mode="MarkdownV2",
                reply_markup=reply_markup,
                link_preview_options={"is_disabled": True}
            )
            # 清理缓存
            _reddit_video_cache.pop(result_id, None)
            _cache_timestamps.pop(result_id, None)
            return

        # 更新状态
        await context.bot.edit_message_text(
            inline_message_id=inline_message_id,
            text=f"📤 上传{media_type}中... ({media_size_mb:.1f}MB)"
        )

        # 使用 Pyrogram 上传（支持大文件）
        from commands import reddit_command
        pyrogram_helper = reddit_command._pyrogram_helper

        if is_video and pyrogram_helper and pyrogram_helper.is_started and pyrogram_helper.client:
            from pyrogram.types import InputMediaVideo as PyrogramInputMediaVideo
            from pyrogram.enums import ParseMode as PyrogramParseMode

            # 将 MarkdownV2 caption 转换为 HTML
            html_caption = caption.replace("\\", "")

            await pyrogram_helper.client.edit_inline_media(
                inline_message_id=inline_message_id,
                media=PyrogramInputMediaVideo(
                    media=str(media_path),
                    caption=html_caption,
                    parse_mode=PyrogramParseMode.HTML,
                    supports_streaming=True,
                )
            )
            logger.info(f"[Inline Reddit] Pyrogram 上传成功: {media_size_mb:.1f}MB")
        elif is_image or (is_video and media_size_mb <= 50):
            # 图片或小视频：使用 python-telegram-bot (<=50MB)
            from telegram import InputMediaVideo, InputMediaPhoto
            from utils.config_manager import ConfigManager

            config_manager = ConfigManager()
            temp_channel_id = config_manager.config.inline_parse_temp_channel

            if not temp_channel_id:
                await context.bot.edit_message_text(
                    inline_message_id=inline_message_id,
                    text=f"{caption}\n\n❌ 配置错误：未设置临时存储频道",
                    parse_mode="MarkdownV2",
                    reply_markup=reply_markup,
                    link_preview_options={"is_disabled": True}
                )
                return

            # 先上传到临时频道
            with open(media_path, 'rb') as media_file:
                if is_image:
                    sent_message = await context.bot.send_photo(
                        chat_id=temp_channel_id,
                        photo=media_file,
                        read_timeout=300,
                        write_timeout=300,
                        connect_timeout=30
                    )
                    file_id = sent_message.photo[-1].file_id
                    input_media = InputMediaPhoto(
                        media=file_id,
                        caption=caption,
                        parse_mode="MarkdownV2"
                    )
                else:
                    sent_message = await context.bot.send_video(
                        chat_id=temp_channel_id,
                        video=media_file,
                        supports_streaming=True,
                        read_timeout=300,
                        write_timeout=300,
                        connect_timeout=30
                    )
                    file_id = sent_message.video.file_id
                    input_media = InputMediaVideo(
                        media=file_id,
                        caption=caption,
                        parse_mode="MarkdownV2",
                        supports_streaming=True
                    )

            # 使用 file_id 编辑 inline 消息
            await context.bot.edit_message_media(
                inline_message_id=inline_message_id,
                media=input_media,
                reply_markup=reply_markup
            )

            # 删除临时频道的消息
            try:
                await context.bot.delete_message(chat_id=temp_channel_id, message_id=sent_message.message_id)
            except Exception:
                pass

            logger.info(f"[Inline Reddit] python-telegram-bot 上传成功: {media_size_mb:.1f}MB")
        else:
            # >50MB 且 Pyrogram 不可用
            await context.bot.edit_message_text(
                inline_message_id=inline_message_id,
                text=f"{caption}\n\n⚠️ 视频过大 ({media_size_mb:.1f}MB)，无法上传",
                parse_mode="MarkdownV2",
                reply_markup=reply_markup,
                link_preview_options={"is_disabled": True}
            )

        # 清理缓存和临时文件
        _reddit_video_cache.pop(result_id, None)
        _cache_timestamps.pop(result_id, None)
        try:
            media_path.unlink()
        except Exception:
            pass

    except Exception as e:
        logger.error(f"[Inline Reddit] {media_type if 'media_type' in locals() else '媒体'}处理失败: {e}", exc_info=True)
        try:
            await context.bot.edit_message_text(
                inline_message_id=inline_message_id,
                text=f"{caption}\n\n❌ 处理失败: {str(e)}",
                parse_mode="MarkdownV2",
                reply_markup=reply_markup,
                link_preview_options={"is_disabled": True}
            )
        except Exception:
            pass
