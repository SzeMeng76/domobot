#!/usr/bin/env python3
"""
Inline Reddit 处理器
支持在 inline mode 中解析 Reddit 帖子并发送
"""

import logging
from uuid import uuid4

from telegram import Update, InlineQueryResultArticle, InputTextMessageContent, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


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
            buttons.append([InlineKeyboardButton("📝 AI总结", callback_data=f"reddit_summary_{url_hash}")])

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

        # 返回结果
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
                description="reddit hot [subreddit] 或 reddit top [subreddit] [time]",
                input_message_content=InputTextMessageContent(
                    message_text="**📝 Reddit Inline 使用方法：**\n\n"
                                "• `reddit hot [subreddit]` - 热门帖子\n"
                                "• `reddit top [subreddit] [time]` - Top帖子\n\n"
                                "**示例：**\n"
                                "• `reddit hot python`\n"
                                "• `reddit top python week`",
                    parse_mode="Markdown"
                ),
            )
        ]

    list_type = parts[1].lower()  # hot 或 top
    subreddit = parts[2] if len(parts) > 2 else None
    time_filter = parts[3] if len(parts) > 3 else "day"

    # 获取帖子列表
    try:
        if list_type == "hot":
            posts = await reddit_client.get_hot_posts(subreddit=subreddit, limit=10)
            title_prefix = f"🔥 r/{subreddit} 热门" if subreddit else "🔥 Reddit 全站热门"
        elif list_type == "top":
            posts = await reddit_client.get_top_posts(subreddit=subreddit, time_filter=time_filter, limit=10)
            time_map = {'hour': '本小时', 'day': '今日', 'week': '本周', 'month': '本月', 'year': '今年', 'all': '全部时间'}
            time_text = time_map.get(time_filter, time_filter)
            title_prefix = f"🏆 r/{subreddit} Top ({time_text})" if subreddit else f"🏆 Reddit 全站 Top ({time_text})"
        else:
            return [
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title="❌ 无效的命令",
                    description="请使用 hot 或 top",
                    input_message_content=InputTextMessageContent(
                        message_text="❌ 无效的命令，请使用 `reddit hot` 或 `reddit top`",
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
