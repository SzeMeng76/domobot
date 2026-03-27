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
_pyrogram_helper = None


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


def set_pyrogram_helper(helper):
    """设置 Pyrogram 助手"""
    global _pyrogram_helper
    _pyrogram_helper = helper


def _escape_markdown(text: str) -> str:
    """转义 MarkdownV2 特殊字符"""
    if not text:
        return text
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text


def _escape_markdown_link_text(text: str) -> str:
    """转义 MarkdownV2 链接文本中的特殊字符

    在 [text](url) 中，text 部分只需要转义这些字符：
    _ * [ ] ( ) ~ `

    其他字符如 . - ! 不需要转义
    """
    if not text:
        return text
    # 只转义链接文本中必须转义的字符
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`']
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


async def _download_video(url: str, temp_dir: Path) -> Path:
    """下载视频到临时目录"""
    import urllib.request
    import hashlib

    # 生成文件名
    url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
    file_path = temp_dir / f"reddit_{url_hash}.mp4"

    # 下载
    logger.info(f"开始下载视频: {url}")
    await asyncio.to_thread(urllib.request.urlretrieve, url, str(file_path))
    logger.info(f"视频下载完成: {file_path}")
    return file_path


async def _show_hot_posts(context: ContextTypes.DEFAULT_TYPE, chat_id: int, subreddit: str = None, message=None):
    """显示热门帖子列表"""
    status_msg = await context.bot.send_message(chat_id=chat_id, text="🔄 获取热门帖子...")

    try:
        posts = await _reddit_client.get_hot_posts(subreddit=subreddit, limit=10)

        if not posts:
            await status_msg.edit_text("❌ 未找到帖子")
            return

        # 构建消息
        title = f"🔥 r/{subreddit} 热门帖子" if subreddit else "🔥 Reddit 全站热门"
        lines = [f"**{title}**\n"]

        for i, post in enumerate(posts, 1):
            # 转义链接文本中的特殊字符
            post_title = _escape_markdown_link_text(post.title[:80])
            if len(post.title) > 80:
                post_title += "..."

            lines.append(
                f"{i}\\. [{post_title}]({post.permalink})\n"
                f"   👤 u/{_escape_markdown(post.author)} \\| "
                f"⬆️ {post.score} \\| 💬 {post.num_comments}"
            )

        message_text = "\n".join(lines)

        # 创建 inline keyboard
        keyboard = []
        # 如果启用了 AI 总结，添加 AI 翻译按钮
        if _ai_summarizer:
            # 缓存帖子列表数据用于AI翻译
            import hashlib
            list_hash = hashlib.md5(f"hot_{subreddit}_{len(posts)}".encode()).hexdigest()[:16]

            # 保存帖子标题列表到缓存
            if _cache_manager:
                titles_data = [{"title": p.title, "permalink": p.permalink} for p in posts]
                await _cache_manager.set(
                    f"reddit_list:{list_hash}",
                    titles_data,
                    ttl=3600,  # 1小时
                    subdirectory="reddit"
                )

            keyboard.append([
                InlineKeyboardButton("🌐 AI翻译", callback_data=f"reddit_translate_{list_hash}")
            ])

        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None

        await status_msg.edit_text(
            message_text,
            parse_mode="MarkdownV2",
            disable_web_page_preview=True,
            reply_markup=reply_markup
        )

        # 删除用户命令
        if message:
            await delete_user_command(context, chat_id, message.message_id)

        # 调度删除
        config = get_config()
        await _schedule_deletion(context, chat_id, status_msg.message_id, config.auto_delete_delay)

    except Exception as e:
        logger.error(f"获取热门帖子失败: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ 获取失败: {str(e)}")


async def _show_top_posts(context: ContextTypes.DEFAULT_TYPE, chat_id: int, subreddit: str = None, time_filter: str = 'day', message=None):
    """显示Top帖子列表"""
    status_msg = await context.bot.send_message(chat_id=chat_id, text="🔄 获取Top帖子...")

    try:
        posts = await _reddit_client.get_top_posts(subreddit=subreddit, time_filter=time_filter, limit=10)

        if not posts:
            await status_msg.edit_text("❌ 未找到帖子")
            return

        # 时间范围映射
        time_map = {
            'hour': '本小时',
            'day': '今日',
            'week': '本周',
            'month': '本月',
            'year': '今年',
            'all': '全部时间'
        }
        time_text = time_map.get(time_filter, time_filter)

        # 构建消息（转义括号）
        title = f"🏆 r/{subreddit} Top \\({time_text}\\)" if subreddit else f"🏆 Reddit 全站 Top \\({time_text}\\)"
        lines = [f"**{title}**\n"]

        for i, post in enumerate(posts, 1):
            # 转义链接文本中的特殊字符
            post_title = _escape_markdown_link_text(post.title[:80])
            if len(post.title) > 80:
                post_title += "..."

            lines.append(
                f"{i}\\. [{post_title}]({post.permalink})\n"
                f"   👤 u/{_escape_markdown(post.author)} \\| "
                f"⬆️ {post.score} \\| 💬 {post.num_comments}"
            )

        message_text = "\n".join(lines)

        # 创建 inline keyboard
        keyboard = []
        # 如果启用了 AI 总结，添加 AI 翻译按钮
        if _ai_summarizer:
            # 缓存帖子列表数据用于AI翻译
            import hashlib
            list_hash = hashlib.md5(f"top_{subreddit}_{time_filter}_{len(posts)}".encode()).hexdigest()[:16]

            # 保存帖子标题列表到缓存
            if _cache_manager:
                titles_data = [{"title": p.title, "permalink": p.permalink} for p in posts]
                await _cache_manager.set(
                    f"reddit_list:{list_hash}",
                    titles_data,
                    ttl=3600,  # 1小时
                    subdirectory="reddit"
                )

            keyboard.append([
                InlineKeyboardButton("🌐 AI翻译", callback_data=f"reddit_translate_{list_hash}")
            ])

        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None

        await status_msg.edit_text(
            message_text,
            parse_mode="MarkdownV2",
            disable_web_page_preview=True,
            reply_markup=reply_markup
        )

        # 删除用户命令
        if message:
            await delete_user_command(context, chat_id, message.message_id)

        # 调度删除
        config = get_config()
        await _schedule_deletion(context, chat_id, status_msg.message_id, config.auto_delete_delay)

    except Exception as e:
        logger.error(f"获取Top帖子失败: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ 获取失败: {str(e)}")


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

    # 获取参数
    if not context.args:
        help_text = (
            "📝 *使用方法：*\n\n"
            "• `/reddit <Reddit链接>` \\- 解析 Reddit 帖子\n"
            "• `/reddit hot [subreddit]` \\- 热门帖子\n"
            "• `/reddit top [subreddit] [day|week|month|year|all]` \\- Top帖子\n\n"
            "🌐 *示例：*\n"
            "`/reddit https://www.reddit.com/r/python/comments/xxx/`\n"
            "`/reddit hot python` \\- r/python 热门\n"
            "`/reddit top python week` \\- r/python 本周Top"
        )
        help_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=help_text,
            parse_mode="MarkdownV2"
        )
        if update.message:
            await delete_user_command(context, chat_id, update.message.message_id)

        # 调度删除帮助消息
        config = get_config()
        await _schedule_deletion(context, chat_id, help_msg.message_id, config.auto_delete_delay)
        return

    first_arg = context.args[0].lower()

    # 热门帖子
    if first_arg == 'hot':
        # 检查第二个参数是否是时间关键词（如果是，说明没有指定subreddit）
        subreddit = None
        if len(context.args) > 1:
            second_arg = context.args[1].lower()
            # 如果不是时间关键词，才当作subreddit
            if second_arg not in ['hour', 'day', 'week', 'month', 'year', 'all']:
                subreddit = context.args[1]
        await _show_hot_posts(context, chat_id, subreddit, update.message)
        return

    # Top帖子
    if first_arg == 'top':
        subreddit = None
        time_filter = 'day'

        # 解析参数：可能是 "top week" 或 "top python week"
        if len(context.args) > 1:
            second_arg = context.args[1].lower()
            if second_arg in ['hour', 'day', 'week', 'month', 'year', 'all']:
                # 第二个参数是时间，没有subreddit
                time_filter = second_arg
            else:
                # 第二个参数是subreddit
                subreddit = context.args[1]
                # 检查第三个参数是否是时间
                if len(context.args) > 2:
                    third_arg = context.args[2].lower()
                    if third_arg in ['hour', 'day', 'week', 'month', 'year', 'all']:
                        time_filter = third_arg

        await _show_top_posts(context, chat_id, subreddit, time_filter, update.message)
        return

    # 解析链接
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

        # 视频
        elif post.is_video and post.video_url:
            logger.info(f"下载并发送视频: {post.video_url}")

            try:
                # 下载视频
                video_path = await _download_video(post.video_url, temp_dir)
                video_size_mb = video_path.stat().st_size / 1024 / 1024

                logger.info(f"视频下载完成: {video_size_mb:.2f}MB")

                # >2GB: 只发送链接
                if video_size_mb > 2048:
                    logger.warning(f"视频过大 ({video_size_mb:.1f}MB)，只发送链接")
                    video_caption = f"{caption}\n\n🎥 视频过大 \\({video_size_mb:.1f}MB\\)，请点击链接观看：\n[视频链接]({_escape_markdown(post.video_url)})"

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

                # <=2GB: 优先 Pyrogram，失败 fallback python-telegram-bot
                if _pyrogram_helper and _pyrogram_helper.is_started:
                    try:
                        logger.info(f"🚀 使用 Pyrogram 上传 {video_size_mb:.1f}MB 视频")

                        video_msg = await _pyrogram_helper.send_large_video(
                            chat_id=chat_id,
                            video_path=str(video_path),
                            caption=caption,
                            reply_markup=reply_markup,
                            parse_mode="MarkdownV2"
                        )

                        logger.info(f"✅ Pyrogram 上传成功: {video_size_mb:.1f}MB")
                        return [video_msg]
                    except Exception as e:
                        logger.warning(f"⚠️ Pyrogram 上传失败，降级到 python-telegram-bot: {e}")

                # Fallback: python-telegram-bot (<=50MB)
                if video_size_mb <= 50:
                    logger.info(f"使用 python-telegram-bot 上传 {video_size_mb:.1f}MB 视频")

                    @with_telegram_retry(max_retries=5)
                    async def _send_video():
                        with open(video_path, 'rb') as f:
                            return await context.bot.send_video(
                                chat_id=chat_id,
                                video=f,
                                caption=caption,
                                parse_mode="MarkdownV2",
                                reply_markup=reply_markup,
                                supports_streaming=True,
                                read_timeout=300,
                                write_timeout=300
                            )

                    msg = await _send_video()
                    return [msg]
                else:
                    # Pyrogram失败且>50MB，发送链接
                    logger.warning(f"Pyrogram 不可用且视频 >50MB ({video_size_mb:.1f}MB)，发送链接")
                    video_caption = f"{caption}\n\n🎥 视频过大 \\({video_size_mb:.1f}MB\\)，请点击链接观看：\n[视频链接]({_escape_markdown(post.video_url)})"

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

            except Exception as e:
                logger.error(f"视频处理失败: {e}", exc_info=True)
                # 降级：发送链接
                video_caption = f"{caption}\n\n🎥 视频处理失败，请点击链接观看：\n[视频链接]({_escape_markdown(post.video_url)})"

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


@with_error_handling
async def reddit_translate_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 Reddit 列表翻译按钮"""
    query = update.callback_query

    try:
        if not query.data or not query.data.startswith("reddit_translate_"):
            return

        await query.answer()

        list_hash = query.data.replace("reddit_translate_", "")

        # 显示翻译中状态
        await query.edit_message_text(
            text="🌐 AI翻译中，请稍候...",
            reply_markup=query.message.reply_markup
        )

        # 检查依赖
        if not _cache_manager or not _ai_summarizer:
            await query.answer("❌ AI翻译功能未启用", show_alert=True)
            return

        # 从缓存读取列表数据
        titles_data = await _cache_manager.get(
            f"reddit_list:{list_hash}",
            subdirectory="reddit"
        )

        if not titles_data:
            await query.answer("❌ 缓存已失效，请重新获取列表", show_alert=True)
            return

        # 构建翻译prompt
        titles_text = "\n".join([f"{i+1}. {item['title']}" for i, item in enumerate(titles_data)])
        prompt = f"""请将以下Reddit帖子标题翻译成中文，保持编号格式：

{titles_text}

要求：
- 保持编号格式 (1. 2. 3. ...)
- 翻译要准确、自然、易懂
- 保留技术术语的英文（如Python, API等）
- 每行一个标题"""

        # 调用AI翻译（直接调用OpenAI API）
        from openai import AsyncOpenAI
        client = AsyncOpenAI(
            api_key=_ai_summarizer.api_key,
            base_url=_ai_summarizer.base_url
        )

        response = await client.chat.completions.create(
            model=_ai_summarizer.model,
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )

        translated = response.choices[0].message.content

        if not translated:
            await query.answer("❌ AI翻译失败", show_alert=True)
            return

        # 构建翻译后的消息
        lines = ["**🌐 AI翻译结果**\n"]
        translated_lines = translated.strip().split('\n')

        for i, (item, trans_line) in enumerate(zip(titles_data, translated_lines), 1):
            # 清理翻译结果中的编号
            trans_title = trans_line.strip()
            if trans_title.startswith(f"{i}."):
                trans_title = trans_title[len(f"{i}."):].strip()

            lines.append(
                f"{i}\\. [{_escape_markdown(trans_title)}]({item['permalink']})"
            )

        message_text = "\n".join(lines)

        # 添加"显示原文"按钮
        keyboard = [[
            InlineKeyboardButton("🔙 显示原文", callback_data=f"reddit_untranslate_{list_hash}")
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            text=message_text,
            parse_mode="MarkdownV2",
            disable_web_page_preview=True,
            reply_markup=reply_markup
        )

        logger.info(f"✅ Reddit列表翻译完成: {list_hash}")

    except Exception as e:
        logger.error(f"Reddit列表翻译失败: {e}", exc_info=True)
        try:
            await query.edit_message_text(
                text=f"❌ 翻译失败: {str(e)}",
                reply_markup=query.message.reply_markup
            )
        except:
            pass


@with_error_handling
async def reddit_untranslate_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理显示原文按钮"""
    query = update.callback_query

    try:
        if not query.data or not query.data.startswith("reddit_untranslate_"):
            return

        await query.answer()

        list_hash = query.data.replace("reddit_untranslate_", "")

        # 从缓存读取原始数据
        if not _cache_manager:
            await query.answer("❌ 功能未启用", show_alert=True)
            return

        titles_data = await _cache_manager.get(
            f"reddit_list:{list_hash}",
            subdirectory="reddit"
        )

        if not titles_data:
            await query.answer("❌ 缓存已失效", show_alert=True)
            return

        # 重新构建原文消息
        lines = []
        for i, item in enumerate(titles_data, 1):
            post_title = _escape_markdown_link_text(item['title'][:80])
            if len(item['title']) > 80:
                post_title += "..."
            lines.append(f"{i}\\. [{post_title}]({item['permalink']})")

        message_text = "\n".join(lines)

        # 恢复翻译按钮
        keyboard = [[
            InlineKeyboardButton("🌐 AI翻译", callback_data=f"reddit_translate_{list_hash}")
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            text=message_text,
            parse_mode="MarkdownV2",
            disable_web_page_preview=True,
            reply_markup=reply_markup
        )

    except Exception as e:
        logger.error(f"显示原文失败: {e}", exc_info=True)


# 注册命令
command_factory.register_command(
    "reddit",
    reddit_command,
    permission=Permission.USER,  # 白名单用户可用
    description="解析 Reddit 帖子"
)

# 注册callback handlers
command_factory.register_callback(
    "^reddit_translate_",
    reddit_translate_callback,
    permission=Permission.USER,
    description="Reddit列表AI翻译"
)

command_factory.register_callback(
    "^reddit_untranslate_",
    reddit_untranslate_callback,
    permission=Permission.USER,
    description="Reddit列表显示原文"
)

logger.info("Reddit 命令模块已加载")
