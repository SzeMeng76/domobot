"""
自动解析处理器
在启用的群组中自动监听并解析社交媒体链接（包括 Reddit）
"""

import asyncio
import logging
import re
from telegram import Update, ReplyParameters
from telegram.ext import ContextTypes, MessageHandler, filters

logger = logging.getLogger(__name__)

# 全局适配器实例
_adapter = None
_reddit_client = None


def set_adapter(adapter):
    """设置 ParseHub 适配器"""
    global _adapter
    _adapter = adapter


def set_reddit_client(client):
    """设置 Reddit 客户端"""
    global _reddit_client
    _reddit_client = client


async def auto_parse_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    自动解析处理器
    在启用自动解析的群组中，检测并解析社交媒体链接（包括 Reddit）
    """
    if not _adapter:
        return

    # 只处理群组消息
    if update.effective_chat.type not in ["group", "supergroup"]:
        return

    message = update.message
    if not message:
        return

    # 去重：检查这条消息是否已经被处理过
    message_id = message.message_id
    chat_id = update.effective_chat.id

    # 使用 chat_data 存储已处理的消息ID（避免重复处理）
    if 'processed_messages' not in context.chat_data:
        context.chat_data['processed_messages'] = set()

    # 如果已处理过，直接返回
    if message_id in context.chat_data['processed_messages']:
        logger.debug(f"消息 {message_id} 已被处理过，跳过")
        return

    # 标记为已处理
    context.chat_data['processed_messages'].add(message_id)

    # 清理旧的消息ID（只保留最近100条）
    if len(context.chat_data['processed_messages']) > 100:
        # 转换为列表，删除最旧的50条
        old_ids = list(context.chat_data['processed_messages'])[:50]
        for old_id in old_ids:
            context.chat_data['processed_messages'].discard(old_id)

    # 获取消息文本
    text = message.text or message.caption
    if not text:
        return

    user_id = update.effective_user.id
    group_id = update.effective_chat.id

    # 检查群组是否启用自动解析
    if not await _adapter.is_auto_parse_enabled(group_id):
        return

    # 提取所有 URL（包括 Reddit）
    all_urls = []

    # 1. 提取 ParseHub 支持的 URL
    social_urls = await _adapter.extract_all_urls(text)
    all_urls.extend(social_urls)

    # 2. 提取 Reddit URL
    reddit_urls = []
    if _reddit_client:
        url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+(?:\?[^\s<>"{}|\\^`\[\]]*)?(?:#[^\s<>"{}|\\^`\[\]]*)?'
        raw_urls = re.findall(url_pattern, text)
        for url in raw_urls:
            if 'reddit.com' in url and url not in social_urls:
                reddit_urls.append(url)

    all_urls.extend(reddit_urls)

    if not all_urls:
        return

    logger.info(f"群组 {group_id} 检测到 {len(all_urls)} 条链接（{len(social_urls)} 社交媒体 + {len(reddit_urls)} Reddit），开始自动解析")

    # 并发解析所有 URL，每条 URL 独立发送结果
    tasks = []
    for url in all_urls:
        if url in reddit_urls:
            tasks.append(_auto_parse_reddit(url, user_id, group_id, message, context))
        else:
            tasks.append(_auto_parse_single(url, user_id, group_id, message, context))

    await asyncio.gather(*tasks)

    # 删除原始消息（用户发的链接）
    from commands.social_parser import delete_user_command
    await delete_user_command(context, group_id, message.message_id)


async def _auto_parse_single(url: str, user_id: int, group_id: int, message, context: ContextTypes.DEFAULT_TYPE) -> None:
    """自动解析单条 URL 并发送结果"""
    status_msg = await message.reply_text("🔄 检测到链接，自动解析中...")

    try:
        result, parse_result, platform, parse_time, error_msg = await _adapter.parse_url(url, user_id, group_id)

        # 检查是否解析失败（parse_result 为 None 表示解析失败）
        if not parse_result:
            if error_msg:
                error_text = f"**❌ 自动解析失败:**\n```\n{error_msg}\n```"
            else:
                error_text = "❌ 自动解析失败"
            error_msg_obj = await status_msg.edit_text(error_text)

            from commands.social_parser import delete_user_command, _schedule_deletion, get_config
            config = get_config()
            await _schedule_deletion(context, group_id, error_msg_obj.message_id, 5)
            return

        # 更新状态
        if result:
            await status_msg.edit_text("📥 下载中...")
        else:
            await status_msg.edit_text("📥 解析成功，准备发送...")

        # 格式化结果
        formatted = await _adapter.format_result(result, platform, parse_result=parse_result)

        from commands.social_parser import _escape_markdown, _format_text

        caption_parts = []
        if formatted['title']:
            caption_parts.append(f"**{_escape_markdown(formatted['title'])}**")
        if formatted['content']:
            caption_parts.append(_escape_markdown(_format_text(formatted['content'])))

        caption = "\n\n".join(caption_parts) if caption_parts else "无标题"

        if formatted['url']:
            caption += f"\n\n🔗 [原链接]({formatted['url']})"
        caption += f"\n\n📱 平台: {platform.upper()}"
        caption += f"\n🤖 自动解析"

        # 更新状态
        await status_msg.edit_text("📤 上传中...")

        from commands.social_parser import _send_media, get_url_hash, _schedule_deletion, get_config
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        url_hash = get_url_hash(formatted['url'] or '')
        buttons = [[InlineKeyboardButton("🔗 原链接", url=formatted['url'])]] if formatted['url'] else []

        reply_markup = None
        if _adapter.config and _adapter.config.enable_ai_summary and buttons:
            buttons[0].append(InlineKeyboardButton("📝 AI总结", callback_data=f"summary_{url_hash}"))
            reply_markup = InlineKeyboardMarkup(buttons)

            if _adapter.cache_manager:
                # 序列化 parse_result（保存图片URL等信息）
                parse_result_dict = None

                if parse_result:
                    logger.info(f"📍 parse_result存在: type={type(parse_result).__name__}, title={getattr(parse_result, 'title', 'N/A')}")
                    parse_result_dict = {
                        'type': type(parse_result).__name__,
                        'title': getattr(parse_result, 'title', ''),
                        'content': getattr(parse_result, 'content', ''),
                        'platform': getattr(parse_result, 'platform', platform),
                    }
                    # 保存媒体URL（图片/视频）
                    if hasattr(parse_result, 'media') and parse_result.media:
                        media = parse_result.media
                        media_list = media if isinstance(media, list) else [media]
                        parse_result_dict['media'] = []
                        for m in media_list:
                            if hasattr(m, 'url'):
                                parse_result_dict['media'].append({
                                    'type': type(m).__name__,
                                    'url': m.url,
                                    'width': getattr(m, 'width', 0),
                                    'height': getattr(m, 'height', 0),
                                })
                        logger.info(f"📍 parse_result.media: {len(parse_result_dict['media'])} items")
                    else:
                        logger.warning(f"⚠️ parse_result没有media或media为空")
                else:
                    logger.error(f"❌ parse_result是None！无法缓存媒体信息")

                # 缓存 download_result 到内存（用于AI总结，包含本地文件）
                if result:
                    from handlers.ai_summary_callback_handler import cache_download_result
                    cache_download_result(url_hash, result)
                    logger.info(f"✅ 已缓存 download_result 到内存: {url_hash}")

                cache_data = {
                    'url': formatted['url'],
                    'caption': caption,
                    'title': formatted.get('title', ''),
                    'content': formatted.get('content', ''),
                    'platform': platform,
                    'parse_result': parse_result_dict
                }
                await _adapter.cache_manager.set(
                    f"summary:{url_hash}",
                    cache_data,
                    ttl=86400,
                    subdirectory="social_parser"
                )
                logger.info(f"✅ 已缓存解析数据（含parse_result）: cache:social_parser:summary:{url_hash}")
        else:
            reply_markup = InlineKeyboardMarkup(buttons)

        reply_params = ReplyParameters(message_id=message.message_id)
        sent_messages = await _send_media(context, group_id, result, caption, reply_params, reply_markup, parse_result=parse_result)

        await status_msg.delete()

        config = get_config()
        if sent_messages:
            for msg in sent_messages:
                msg_id = getattr(msg, 'message_id', None) or getattr(msg, 'id', None)
                if msg_id:
                    await _schedule_deletion(context, group_id, msg_id, config.auto_delete_delay)

        logger.info(f"群组 {group_id} 自动解析成功: {platform} - {formatted['title']}")

    except Exception as e:
        logger.error(f"自动解析失败: {e}", exc_info=True)
        try:
            from commands.social_parser import _schedule_deletion
            error_msg_obj = await status_msg.edit_text(f"**❌ 自动解析失败:**\n```\n{str(e)}\n```")
            await _schedule_deletion(context, group_id, error_msg_obj.message_id, 5)
        except Exception:
            pass


async def _auto_parse_reddit(url: str, user_id: int, group_id: int, message, context: ContextTypes.DEFAULT_TYPE) -> None:
    """自动解析 Reddit URL 并发送结果"""
    status_msg = await message.reply_text("🔄 检测到 Reddit 链接，自动解析中...")

    try:
        # 获取帖子
        post = await _reddit_client.get_post_by_url(url)

        if not post:
            error_msg_obj = await status_msg.edit_text("❌ Reddit 自动解析失败：获取帖子失败")
            from commands.social_parser import _schedule_deletion
            await _schedule_deletion(context, group_id, error_msg_obj.message_id, 5)
            return

        # 更新状态
        await status_msg.edit_text("📥 下载中...")

        # 构建 caption
        from commands.reddit_command import _escape_markdown, _format_timestamp

        caption_parts = []
        caption_parts.append(f"**{_escape_markdown(post.title)}**")
        caption_parts.append(f"👤 u/{_escape_markdown(post.author)} \\| 📊 {post.score} ⬆️ \\| 💬 {post.num_comments}")
        caption_parts.append(f"📍 r/{_escape_markdown(post.subreddit)} \\| 🕐 {_escape_markdown(_format_timestamp(post.created_utc))}")

        # 添加文本内容（如果是自发帖）
        if post.is_self and post.selftext:
            text_preview = post.selftext[:500]
            if len(post.selftext) > 500:
                text_preview += "..."
            caption_parts.append(f"\n{_escape_markdown(text_preview)}")

        caption_parts.append(f"🔗 [原帖链接]({post.permalink})")
        caption_parts.append(f"📱 平台: REDDIT")
        caption_parts.append("🤖 自动解析")

        caption = "\n".join(caption_parts)

        # 生成 URL 哈希（用于 AI 总结 callback）
        from utils.reddit_client import RedditClient
        from commands.reddit_command import _ai_summarizer, _cache_manager
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        url_hash = RedditClient.get_url_hash(post.permalink)

        # 创建 inline keyboard 按钮
        buttons = [[InlineKeyboardButton("🔗 原帖链接", url=post.permalink)]]

        # 如果启用了 AI 总结，添加 AI 总结按钮
        from utils.config_manager import get_config
        config = get_config()
        reply_markup = None

        if config and config.enable_ai_summary and _ai_summarizer:
            buttons[0].append(InlineKeyboardButton("📝 AI总结", callback_data=f"reddit_summary_{url_hash}"))
            reply_markup = InlineKeyboardMarkup(buttons)

            # 缓存帖子数据到 Redis（用于 AI 总结回调）
            if _cache_manager:
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
        else:
            reply_markup = InlineKeyboardMarkup(buttons)

        # 更新状态
        await status_msg.edit_text("📤 上传中...")

        # 发送媒体
        from commands.reddit_command import _send_reddit_media

        reply_params = ReplyParameters(message_id=message.message_id)
        sent_messages = await _send_reddit_media(
            context,
            group_id,
            post,
            caption,
            reply_markup
        )

        # 删除状态消息
        await status_msg.delete()

        # 调度自动删除
        from commands.social_parser import _schedule_deletion
        if sent_messages:
            for msg in sent_messages:
                msg_id = getattr(msg, 'message_id', None) or getattr(msg, 'id', None)
                if msg_id:
                    await _schedule_deletion(context, group_id, msg_id, config.auto_delete_delay)

        logger.info(f"群组 {group_id} Reddit 自动解析成功: {post.title}")

    except Exception as e:
        logger.error(f"Reddit 自动解析失败: {e}", exc_info=True)
        try:
            from commands.social_parser import _schedule_deletion
            error_msg_obj = await status_msg.edit_text(f"**❌ Reddit 自动解析失败:**\n```\n{str(e)}\n```")
            await _schedule_deletion(context, group_id, error_msg_obj.message_id, 5)
        except Exception:
            pass


def setup_auto_parse_handler(application):
    """
    设置自动解析处理器

    Args:
        application: Telegram Application 实例
    """
    # 监听群组中的文本和图片说明消息
    # 优先级要低，避免干扰其他命令
    handler = MessageHandler(
        filters.ChatType.GROUPS & (filters.TEXT | filters.CAPTION) & ~filters.COMMAND,
        auto_parse_handler
    )

    # 添加到应用程序（添加到最后，优先级最低）
    application.add_handler(handler, group=99)

    logger.info("✅ 自动解析处理器已注册")
