"""
Reddit 命令模块
支持解析 Reddit 帖子，显示内容、图片、视频，并提供 AI 总结功能
"""

import asyncio
import logging
import tempfile
from pathlib import Path
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyParameters
from telegram.ext import ContextTypes

from utils.command_factory import command_factory
from utils.error_handling import with_error_handling, with_telegram_retry
from utils.message_manager import send_error, delete_user_command, _schedule_deletion
from utils.permissions import Permission
from utils.config_manager import get_config

logger = logging.getLogger(__name__)

# 全局 Reddit 客户端
_reddit_client = None
_cache_manager = None
_ai_summarizer = None


def set_reddit_client(client):
    """设置 Reddit 客户端"""
    global _reddit_client
    _reddit_client = client


def set_cache_manager(cache_manager):
    """设置缓存管理器"""
    global _cache_manager
    _cache_manager = cache_manager


def set_ai_summarizer(summarizer):
    """设置 AI 总结器"""
    global _ai_summarizer
    _ai_summarizer = summarizer


def _escape_markdown(text: str) -> str:
    """转义 MarkdownV2 特殊字符"""
    if not text:
        return text
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text


def _format_timestamp(timestamp: float) -> str:
    """格式化时间戳"""
    dt = datetime.fromtimestamp(timestamp)
    return dt.strftime('%Y-%m-%d %H:%M')


async def _download_image(url: str, temp_dir: Path) -> Path:
    """下载图片到临时目录"""
    import urllib.request
    import hashlib

    # 生成文件名
    url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
    file_ext = '.jpg'
    if '.png' in url:
        file_ext = '.png'
    elif '.gif' in url:
        file_ext = '.gif'

    file_path = temp_dir / f"reddit_{url_hash}{file_ext}"

    # 下载
    await asyncio.to_thread(urllib.request.urlretrieve, url, str(file_path))
    return file_path


@with_error_handling
async def reddit_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /reddit <URL> - 解析 Reddit 帖子
    """
    if not _reddit_client:
        await send_error(context, update.effective_chat.id, "❌ Reddit 功能未初始化")
        return

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    # 获取 URL
    if not context.args:
        help_text = (
            "📝 *使用方法：*\n\n"
            "• `/reddit <Reddit链接>` \\- 解析 Reddit 帖子\n\n"
            "🌐 *示例：*\n"
            "`/reddit https://www.reddit.com/r/python/comments/xxx/`"
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=help_text,
            parse_mode="MarkdownV2"
        )
        if update.message:
            await delete_user_command(context, chat_id, update.message.message_id)
        return

    url = context.args[0]

    # 验证 URL
    if 'reddit.com' not in url:
        await send_error(context, chat_id, "❌ 无效的 Reddit 链接")
        if update.message:
            await delete_user_command(context, chat_id, update.message.message_id)
        return

    # 发送状态消息
    status_msg = await context.bot.send_message(chat_id=chat_id, text="🔄 解析中...")

    try:
        # 获取帖子
        post = await _reddit_client.get_post_by_url(url)

        if not post:
            await status_msg.edit_text("❌ 获取帖子失败，请检查链接是否正确")
            return

        # 更新状态
        await status_msg.edit_text("📥 下载中...")

        # 构建 caption
        caption_parts = []
        caption_parts.append(f"**{_escape_markdown(post.title)}**")
        caption_parts.append(f"👤 u/{_escape_markdown(post.author)} \\| 📊 {post.score} ⬆️ \\| 💬 {post.num_comments}")
        caption_parts.append(f"📍 r/{_escape_markdown(post.subreddit)} \\| 🕐 {_escape_markdown(_format_timestamp(post.created_utc))}")

        # 添加文本内容（如果是自发帖）
        if post.is_self and post.selftext:
            # 截断长文本
            text_preview = post.selftext[:500]
            if len(post.selftext) > 500:
                text_preview += "..."
            caption_parts.append(f"\n{_escape_markdown(text_preview)}")

        caption_parts.append(f"\n🔗 [原帖链接]({post.permalink})")

        caption = "\n\n".join(caption_parts)

        # 生成 URL 哈希（用于 AI 总结 callback）
        from utils.reddit_client import RedditClient
        url_hash = RedditClient.get_url_hash(post.permalink)

        # 创建 inline keyboard 按钮
        buttons = [[InlineKeyboardButton("🔗 原帖链接", url=post.permalink)]]

        # 如果启用了 AI 总结，添加 AI 总结按钮
        config = get_config()
        if config and config.enable_ai_summary and _ai_summarizer:
            buttons[0].append(InlineKeyboardButton("📝 AI总结", callback_data=f"reddit_summary_{url_hash}"))
            logger.info(f"✅ AI总结按钮已添加: reddit_summary_{url_hash}")

        reply_markup = InlineKeyboardMarkup(buttons)

        # 缓存帖子数据到 Redis（用于 AI 总结回调）
        if config and config.enable_ai_summary and _cache_manager:
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
            await _cache_manager.set(
                f"reddit_summary:{url_hash}",
                cache_data,
                ttl=86400,
                subdirectory="reddit"
            )
            logger.info(f"✅ 已缓存 Reddit 数据: cache:reddit:reddit_summary:{url_hash}")

        # 更新状态
        await status_msg.edit_text("📤 上传中...")

        # 发送媒体
        sent_messages = await _send_reddit_media(
            context,
            chat_id,
            post,
            caption,
            reply_markup
        )

        # 删除状态消息
        await status_msg.delete()

        # 删除用户命令消息
        if update.message:
            await delete_user_command(context, chat_id, update.message.message_id)

        # 调度自动删除
        if sent_messages:
            for msg in sent_messages:
                await _schedule_deletion(context, chat_id, msg.message_id, config.auto_delete_delay)

        logger.info(f"用户 {user_id} 解析 Reddit 成功: {post.title}")

    except Exception as e:
        logger.error(f"Reddit 解析失败: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ 处理失败: {str(e)}")


async def _send_reddit_media(context, chat_id, post, caption, reply_markup):
    """发送 Reddit 媒体内容"""
    from telegram import InputMediaPhoto

    temp_dir = Path(tempfile.gettempdir()) / "domobot_reddit"
    temp_dir.mkdir(exist_ok=True)

    try:
        # 图集
        if post.gallery_items:
            logger.info(f"发送图集: {len(post.gallery_items)} 张图片")

            # 下载所有图片
            image_paths = []
            for img_url in post.gallery_items[:10]:  # 最多10张
                try:
                    img_path = await _download_image(img_url, temp_dir)
                    image_paths.append(img_path)
                except Exception as e:
                    logger.warning(f"下载图片失败: {e}")

            if image_paths:
                # 构建 media group
                media_group = []
                for img_path in image_paths:
                    with open(img_path, 'rb') as f:
                        media_group.append(InputMediaPhoto(media=f.read()))

                # 将 caption 附加到最后一张图片
                media_group[-1].caption = caption
                media_group[-1].parse_mode = "MarkdownV2"

                @with_telegram_retry(max_retries=5)
                async def _send_media_group():
                    return await context.bot.send_media_group(
                        chat_id=chat_id,
                        media=media_group
                    )

                messages = await _send_media_group()

                # 如果有按钮，单独发送
                if reply_markup:
                    @with_telegram_retry(max_retries=5)
                    async def _send_button_msg():
                        return await context.bot.send_message(
                            chat_id=chat_id,
                            text="🔗 更多操作",
                            reply_parameters=ReplyParameters(message_id=messages[-1].message_id),
                            reply_markup=reply_markup
                        )
                    button_msg = await _send_button_msg()
                    return list(messages) + [button_msg]

                return list(messages)

        # 单张图片
        elif post.preview_image_url:
            logger.info(f"发送单张图片: {post.preview_image_url}")

            img_path = await _download_image(post.preview_image_url, temp_dir)

            @with_telegram_retry(max_retries=5)
            async def _send_photo():
                with open(img_path, 'rb') as f:
                    return await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=f,
                        caption=caption,
                        parse_mode="MarkdownV2",
                        reply_markup=reply_markup
                    )

            msg = await _send_photo()
            return [msg]

        # 视频（暂不支持下载，只发送链接）
        elif post.is_video and post.video_url:
            logger.info(f"发送视频链接: {post.video_url}")

            video_caption = f"{caption}\n\n🎥 [视频链接]({_escape_markdown(post.video_url)})"

            @with_telegram_retry(max_retries=5)
            async def _send_video_link():
                return await context.bot.send_message(
                    chat_id=chat_id,
                    text=video_caption,
                    parse_mode="MarkdownV2",
                    disable_web_page_preview=False,
                    reply_markup=reply_markup
                )

            msg = await _send_video_link()
            return [msg]

        # 纯文本
        else:
            logger.info("发送纯文本")

            @with_telegram_retry(max_retries=5)
            async def _send_text():
                return await context.bot.send_message(
                    chat_id=chat_id,
                    text=caption,
                    parse_mode="MarkdownV2",
                    disable_web_page_preview=True,
                    reply_markup=reply_markup
                )

            msg = await _send_text()
            return [msg]

    finally:
        # 清理临时文件
        try:
            for file in temp_dir.glob("reddit_*"):
                file.unlink()
        except Exception as e:
            logger.debug(f"清理临时文件失败: {e}")


# 注册命令
command_factory.register_command(
    "reddit",
    reddit_command,
    permission=Permission.USER,  # 白名单用户可用
    description="解析 Reddit 帖子"
)
