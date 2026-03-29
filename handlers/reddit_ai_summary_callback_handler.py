"""
Reddit AI 总结按钮 callback handler
处理 Reddit 帖子的 AI 总结功能
点击按钮切换显示/隐藏 AI 总结内容
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions
from telegram.ext import ContextTypes, CallbackQueryHandler

logger = logging.getLogger(__name__)

# Global references
_reddit_client = None
_cache_manager = None
_ai_summarizer = None

# 缓存原始 caption 和 AI 总结
_message_cache = {}


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


# Reddit AI 总结的 prompt（针对英文内容优化）
REDDIT_SUMMARY_PROMPT = """你是一个专业的 Reddit 内容总结助手，帮助中文用户快速了解英文 Reddit 帖子的内容。

请用生动有趣的方式总结这个 Reddit 帖子，要求：

**格式要求：**
- 使用 HTML 格式，仅允许以下标签：<b>粗体</b>、<i>斜体</i>、<code>代码</code>、<strong>加粗</strong>、<blockquote>引用</blockquote>、<a href="url">链接</a>
- **严禁使用其他 HTML 标签**（如 <div>、<span> 等都不允许）
- 中英文之间需要空格
- 技术关键词使用 <code>行内代码</code>
- 重要引用使用 <blockquote>引用内容</blockquote>
- 适当使用 emoji 让内容更友好（但不要过度）
- **禁止使用 Markdown 格式**（不要用 **、``、>、# 等符号）

**内容结构：**
1. <b>核心内容</b> - 用 1-2 句话说明主题（用粗体）
2. <b>关键要点</b> - 3-5 个要点，使用列表格式（每行用 - 开头）
3. <b>热门评论观点</b> - 如果有评论，总结 Top 评论的主要观点

**语气风格：**
- 保持轻松友好，像朋友聊天一样
- 对有趣的内容可以加点俏皮评论
- 重要信息要清晰准确，不夸大不遗漏
- **必须使用中文回复**（将英文内容翻译成中文后再总结）

**注意事项：**
- Reddit 帖子通常是英文，请翻译成中文
- 关注帖子的讨论氛围和社区反应
- 如果有技术内容，用通俗易懂的方式解释
- 总长度控制在 200-500 字左右

现在请总结以下 Reddit 帖子："""


async def reddit_ai_summary_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 Reddit AI 总结按钮点击"""
    query = update.callback_query

    try:
        if not query.data:
            return

        # callback_data 格式: reddit_summary_<url_hash> 或 reddit_unsummary_<url_hash>
        if not ("reddit_summary_" in query.data or "reddit_unsummary_" in query.data):
            return

        parts = query.data.split("_", 2)
        if len(parts) < 3:
            return

        action = parts[1]  # summary 或 unsummary
        url_hash = parts[2]

        # 判断是否为 inline 消息
        is_inline = query.inline_message_id is not None
        inline_message_id = query.inline_message_id if is_inline else None
        message_id = None if is_inline else (query.message.message_id if query.message else None)
        current_caption = None if is_inline else (query.message.caption or query.message.text if query.message else None)

        if action == "summary":
            # 立即 answer 移除加载圈
            await query.answer()

            # 显示"生成中..."状态
            loading_text = "📝 AI总结生成中，请稍候..."
            try:
                if is_inline:
                    # Inline 消息：尝试 edit_message_text（可能是 Article）或 edit_message_caption（可能是 Photo）
                    try:
                        await context.bot.edit_message_text(
                            inline_message_id=inline_message_id,
                            text=loading_text
                        )
                    except Exception:
                        # 如果是 Photo 类型，需要用 edit_message_caption
                        await context.bot.edit_message_caption(
                            inline_message_id=inline_message_id,
                            caption=loading_text
                        )
                elif query.message.caption:
                    await query.edit_message_caption(
                        caption=loading_text,
                        reply_markup=query.message.reply_markup
                    )
                else:
                    await query.edit_message_text(
                        text=loading_text,
                        reply_markup=query.message.reply_markup,
                        link_preview_options=LinkPreviewOptions(is_disabled=True)
                    )
            except Exception as e:
                if "Message is not modified" not in str(e):
                    logger.warning(f"更新加载状态失败: {e}")

            # 检查依赖
            if not _reddit_client or not _cache_manager or not _ai_summarizer:
                await query.answer("❌ Reddit 功能未初始化", show_alert=True)
                return

            # 从 Redis 缓存读取帖子数据
            cache_data = await _cache_manager.get(
                f"reddit_summary:{url_hash}",
                subdirectory="reddit"
            )
            if not cache_data:
                logger.error(f"❌ 缓存已失效: cache:reddit:reddit_summary:{url_hash}")
                await query.answer("❌ 缓存已失效，请重新发送链接", show_alert=True)
                return

            logger.info(f"✅ 从缓存读取 Reddit 数据: {cache_data.get('title', 'N/A')}")
            post_url = cache_data.get('url', '')

            # 检查是否已有 AI 总结缓存
            ai_summary_cache = await _cache_manager.get(
                f"reddit_ai_summary:{url_hash}",
                subdirectory="reddit"
            )

            if ai_summary_cache:
                ai_summary = ai_summary_cache.get('summary', '')
                logger.info(f"✅ 使用缓存的 AI 总结")
            else:
                # 重新获取帖子和评论
                logger.info(f"📍 重新获取 Reddit 帖子: {post_url}")

                post = await _reddit_client.get_post_by_url(post_url)
                if not post:
                    await query.answer("❌ 重新获取帖子失败", show_alert=True)
                    return

                # 获取 Top 评论
                comments = await _reddit_client.get_comments(post.id, limit=5, sort='top')

                # 构建总结内容
                content_parts = []
                content_parts.append(f"标题: {post.title}")
                if post.selftext:
                    content_parts.append(f"正文: {post.selftext}")
                content_parts.append(f"作者: u/{post.author}")
                content_parts.append(f"Subreddit: r/{post.subreddit}")
                content_parts.append(f"评分: {post.score} | 评论数: {post.num_comments}")

                if comments:
                    content_parts.append("\nTop 评论:")
                    for idx, comment in enumerate(comments[:5], 1):
                        content_parts.append(f"{idx}. u/{comment.author} ({comment.score}⬆️): {comment.body[:200]}")

                content_text = "\n\n".join(content_parts)

                # 处理媒体（图片/视频）
                image_base64_list = []
                video_subtitles = ""
                video_path = None

                # 1. 检查是否是YouTube链接 - 使用ParseHub下载
                if post.url and ('youtube.com/watch' in post.url or 'youtu.be/' in post.url):
                    logger.info(f"🎬 检测到 YouTube 链接: {post.url}")

                    try:
                        from utils.parse_hub_adapter import get_parse_adapter
                        parse_adapter = get_parse_adapter()

                        if parse_adapter:
                            logger.info(f"📥 使用 ParseHub 下载 YouTube 视频...")

                            # 解析并下载YouTube视频
                            download_result, parse_result, platform, _, error_msg = await parse_adapter.parse_url(
                                post.url,
                                user_id=None,
                                group_id=None
                            )

                            if download_result and download_result.media:
                                media = download_result.media if not isinstance(download_result.media, list) else download_result.media[0]
                                video_path = media.path
                                logger.info(f"✅ YouTube 视频已下载: {video_path}")
                            else:
                                logger.warning(f"⚠️ YouTube 下载失败: {error_msg}")
                        else:
                            logger.warning("ParseHub 未初始化")

                    except Exception as e:
                        logger.warning(f"⚠️ YouTube 处理失败: {e}")

                # 2. 检查是否是Reddit原生视频
                elif post.is_video and post.video_url:
                    logger.info(f"🎬 检测到 Reddit 视频: {post.video_url}")

                    try:
                        import tempfile
                        import httpx
                        from pathlib import Path

                        # 检查视频大小
                        async with httpx.AsyncClient(timeout=30.0) as client:
                            head_response = await client.head(post.video_url)
                            video_size = int(head_response.headers.get('content-length', 0))
                            video_size_mb = video_size / (1024 * 1024)

                            logger.info(f"📊 视频大小: {video_size_mb:.2f}MB")

                            # 只处理<50MB的视频
                            if video_size_mb < 50:
                                logger.info(f"📥 下载视频...")

                                # 下载视频
                                response = await client.get(post.video_url)
                                response.raise_for_status()

                                temp_dir = Path(tempfile.gettempdir()) / "domobot_reddit_ai"
                                temp_dir.mkdir(exist_ok=True)

                                video_path = temp_dir / f"reddit_{url_hash}.mp4"
                                with open(video_path, 'wb') as f:
                                    f.write(response.content)

                                logger.info(f"✅ 视频已下载: {video_path}")
                            else:
                                logger.info(f"⚠️ 视频过大 ({video_size_mb:.2f}MB)，跳过处理")

                    except Exception as e:
                        logger.warning(f"⚠️ 视频处理失败: {e}")

                # 统一处理视频转录/截图（YouTube或Reddit视频）
                if video_path:
                    # 尝试转录视频
                    if _ai_summarizer and hasattr(_ai_summarizer, 'transcription_api_key') and _ai_summarizer.transcription_api_key:
                        try:
                            from utils.ai_summary import AISummarizer
                            summarizer = AISummarizer(
                                api_key=_ai_summarizer.api_key,
                                base_url=_ai_summarizer.base_url,
                                model=_ai_summarizer.model,
                                transcription_provider=getattr(_ai_summarizer, 'transcription_provider', 'openai'),
                                transcription_api_key=_ai_summarizer.transcription_api_key,
                                transcription_base_url=getattr(_ai_summarizer, 'transcription_base_url', '')
                            )
                            video_subtitles = await summarizer._video_to_subtitles(str(video_path))
                            if video_subtitles:
                                logger.info(f"✅ 视频转录成功: {len(video_subtitles)} 字符")
                                content_parts.append(f"\n视频字幕: {video_subtitles}")
                                content_text = "\n\n".join(content_parts)
                        except Exception as e:
                            logger.warning(f"⚠️ 视频转录失败: {e}")

                    # Fallback: 提取视频截图
                    if not video_subtitles:
                        try:
                            import base64
                            from utils.ai_summary import _video_to_screenshot, _image_to_base64
                            import asyncio

                            logger.info(f"📸 提取视频截图...")
                            img_path = await asyncio.to_thread(_video_to_screenshot, str(video_path))
                            # _image_to_base64 是 async 函数，直接 await 而不是用 to_thread
                            img_b64 = await _image_to_base64(img_path)
                            image_base64_list.append(img_b64)
                            logger.info(f"✅ 视频截图已转换为base64")
                        except Exception as e:
                            logger.warning(f"⚠️ 视频截图提取失败: {e}")

                    # 清理临时文件
                    try:
                        from pathlib import Path
                        Path(video_path).unlink()
                    except Exception:
                        pass

                # 3. 处理图片
                else:
                    image_urls = []

                    # Gallery（多图）
                    if post.gallery_items:
                        image_urls.extend(post.gallery_items[:5])  # 最多5张
                        logger.info(f"📷 检测到 Gallery: {len(post.gallery_items)} 张图片")
                    # 单图：优先使用 post.url（JSON endpoint），否则使用 preview_image_url（OAuth）
                    elif post.url and post.url.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                        image_urls.append(post.url)
                    elif post.preview_image_url:
                        image_urls.append(post.preview_image_url)

                    # 下载并转换图片
                    if image_urls:
                        try:
                            import tempfile
                            import httpx
                            import base64
                            from pathlib import Path

                            logger.info(f"📷 下载 {len(image_urls)} 张 Reddit 图片...")

                            temp_dir = Path(tempfile.gettempdir()) / "domobot_reddit_ai"
                            temp_dir.mkdir(exist_ok=True)

                            async with httpx.AsyncClient(timeout=30.0) as client:
                                for idx, image_url in enumerate(image_urls):
                                    try:
                                        # 下载图片
                                        response = await client.get(image_url)
                                        response.raise_for_status()

                                        # 保存到临时文件
                                        img_path = temp_dir / f"reddit_{url_hash}_{idx}.jpg"
                                        with open(img_path, 'wb') as f:
                                            f.write(response.content)

                                        # 转换为base64
                                        with open(img_path, 'rb') as f:
                                            img_b64 = base64.b64encode(f.read()).decode('utf-8')
                                            image_base64_list.append(img_b64)

                                        # 清理临时文件
                                        img_path.unlink()

                                    except Exception as e:
                                        logger.warning(f"⚠️ 图片 {idx+1} 下载失败: {e}")
                                        continue

                            logger.info(f"✅ 成功转换 {len(image_base64_list)} 张图片为base64")

                        except Exception as e:
                            logger.warning(f"⚠️ 图片处理失败: {e}")

                # 调用 AI 总结（使用自定义 prompt + 图片）
                from openai import AsyncOpenAI

                try:
                    client = AsyncOpenAI(
                        api_key=_ai_summarizer.api_key,
                        base_url=_ai_summarizer.base_url
                    )

                    # 构建消息内容（文本 + 图片）
                    from typing import Any, Dict, List
                    content: List[Dict[str, Any]] = [{"type": "text", "text": content_text}]

                    # 添加图片
                    for img_b64 in image_base64_list:
                        content.append({
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{img_b64}",
                                "detail": "low"
                            }
                        })

                    messages = [
                        {"role": "system", "content": REDDIT_SUMMARY_PROMPT},
                        {"role": "user", "content": content},
                        {"role": "user", "content": "请对以上 Reddit 帖子进行总结！"}
                    ]

                    stream = await client.chat.completions.create(
                        model=_ai_summarizer.model,
                        messages=messages,
                        stream=True
                    )

                    ai_summary = ""
                    async for chunk in stream:
                        if chunk.choices and chunk.choices[0].delta.content:
                            ai_summary += chunk.choices[0].delta.content


                except Exception as e:
                    logger.error(f"AI 总结生成失败: {e}", exc_info=True)
                    await query.answer("❌ AI总结生成失败，请稍后重试", show_alert=True)
                    return

                if not ai_summary:
                    await query.answer("❌ AI总结生成失败", show_alert=True)
                    return

                # 缓存 AI 总结
                await _cache_manager.set(
                    f"reddit_ai_summary:{url_hash}",
                    {'summary': ai_summary},
                    ttl=86400,
                    subdirectory="reddit"
                )
                logger.info(f"✅ AI总结已缓存: cache:reddit:reddit_ai_summary:{url_hash}")

            # 缓存原始 caption 到内存（用于恢复）- inline 消息不缓存
            if not is_inline and message_id and message_id not in _message_cache:
                _message_cache[message_id] = {
                    "original": current_caption,
                    "url_hash": url_hash
                }

            # 缓存 AI 总结到内存 - inline 消息不缓存
            if not is_inline and message_id:
                _message_cache[message_id]["summary"] = ai_summary

            # 构建总结 caption
            cleaned_summary = _clean_html_tags(ai_summary)
            summary_caption = f"📝 AI总结:\n\n{cleaned_summary}"

            if cache_data.get('url'):
                summary_caption += f"\n\n🔗 原帖链接: {cache_data['url']}"

            # 更新按钮为"已显示"状态
            # Inline 消息需要特殊处理按钮
            if is_inline:
                # Inline 消息：构建新按钮（原链接 + AI总结✅）
                buttons = [[InlineKeyboardButton("🔗 原帖链接", url=cache_data.get('url', ''))]]
                buttons[0].append(InlineKeyboardButton("📝 AI总结✅", callback_data=f"reddit_unsummary_{url_hash}"))
                new_markup = InlineKeyboardMarkup(buttons)
            else:
                new_markup = _get_buttons_with_hide(query.message.reply_markup, url_hash)

            # 编辑消息
            if is_inline:
                # Inline 消息：尝试两种方式
                try:
                    await context.bot.edit_message_text(
                        inline_message_id=inline_message_id,
                        text=summary_caption,
                        parse_mode="HTML",
                        reply_markup=new_markup,
                        link_preview_options=LinkPreviewOptions(is_disabled=True)
                    )
                except Exception:
                    # 如果是 Photo 类型，需要用 edit_message_caption
                    await context.bot.edit_message_caption(
                        inline_message_id=inline_message_id,
                        caption=summary_caption,
                        parse_mode="HTML",
                        reply_markup=new_markup
                    )
            elif query.message.caption:
                await query.edit_message_caption(
                    caption=summary_caption,
                    parse_mode="HTML",
                    reply_markup=new_markup
                )
            else:
                await query.edit_message_text(
                    text=summary_caption,
                    parse_mode="HTML",
                    reply_markup=new_markup,
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )

        elif action == "unsummary":
            # 隐藏 AI 总结，恢复原始 caption
            await query.answer("隐藏中...")

            # Inline 消息无法恢复原始内容（没有缓存），显示提示
            if is_inline:
                # 从缓存读取原始数据重新构建
                if not _cache_manager:
                    await query.answer("❌ 缓存功能未初始化", show_alert=True)
                    return

                cache_data = await _cache_manager.get(
                    f"reddit_summary:{url_hash}",
                    subdirectory="reddit"
                )
                if cache_data:
                    # 重新构建原始 caption
                    from commands.reddit_command import _escape_markdown, _format_timestamp
                    caption_parts = []
                    caption_parts.append(f"**{_escape_markdown(cache_data['title'])}**")
                    caption_parts.append(f"👤 u/{_escape_markdown(cache_data['author'])} \\| 📊 {cache_data['score']} ⬆️ \\| 💬 {cache_data['num_comments']}")
                    caption_parts.append(f"📍 r/{_escape_markdown(cache_data['subreddit'])} \\| 🕐 {_escape_markdown(_format_timestamp(cache_data['created_utc']))}")

                    if cache_data.get('content'):
                        text_preview = cache_data['content'][:200]
                        if len(cache_data['content']) > 200:
                            text_preview += "\\.\\.\\."
                        caption_parts.append(f"\n{_escape_markdown(text_preview)}")

                    caption_parts.append(f"\n🔗 [原帖链接]({cache_data['url']})")
                    original_caption = "\n\n".join(caption_parts)

                    # 恢复按钮为"显示"状态
                    buttons = [[InlineKeyboardButton("🔗 原帖链接", url=cache_data.get('url', ''))]]
                    buttons[0].append(InlineKeyboardButton("📝 AI总结", callback_data=f"reddit_summary_{url_hash}"))
                    new_markup = InlineKeyboardMarkup(buttons)

                    try:
                        await context.bot.edit_message_text(
                            inline_message_id=inline_message_id,
                            text=original_caption,
                            parse_mode="MarkdownV2",
                            reply_markup=new_markup,
                            link_preview_options=LinkPreviewOptions(is_disabled=True)
                        )
                    except Exception:
                        await context.bot.edit_message_caption(
                            inline_message_id=inline_message_id,
                            caption=original_caption,
                            parse_mode="MarkdownV2",
                            reply_markup=new_markup
                        )
                else:
                    await query.answer("❌ 无法恢复原始内容", show_alert=True)
            elif message_id and message_id in _message_cache and _message_cache[message_id].get("original"):
                original_caption = _message_cache[message_id]["original"]

                # 恢复按钮为"显示"状态
                new_markup = _get_buttons_with_show(query.message.reply_markup, url_hash)

                if query.message.caption:
                    await query.edit_message_caption(
                        caption=original_caption,
                        parse_mode="MarkdownV2",
                        reply_markup=new_markup
                    )
                else:
                    await query.edit_message_text(
                        text=original_caption,
                        parse_mode="MarkdownV2",
                        reply_markup=new_markup,
                        disable_web_page_preview=True
                    )

    except Exception as e:
        logger.error(f"Reddit AI 总结 callback 处理失败: {e}", exc_info=True)
        await query.answer("❌ 处理失败", show_alert=True)


def _clean_html_tags(text: str) -> str:
    """清理不支持的 HTML 标签"""
    import re

    text = text.replace('<br>', '\n').replace('<br/>', '\n').replace('<br />', '\n')

    allowed_tags = r'(?!/?(?:b|strong|i|em|u|ins|s|strike|del|code|pre|a|blockquote)\b)'
    text = re.sub(r'<' + allowed_tags + r'[^>]*?>', '', text)

    return text


def _get_buttons_with_hide(original_markup, url_hash: str):
    """生成带"隐藏 AI 总结"按钮的 markup"""
    if not original_markup or not original_markup.inline_keyboard:
        return None

    new_buttons = []
    for row in original_markup.inline_keyboard:
        new_row = []
        for btn in row:
            if "AI总结" in btn.text:
                new_row.append(InlineKeyboardButton("📝 AI总结✅", callback_data=f"reddit_unsummary_{url_hash}"))
            else:
                new_row.append(btn)
        new_buttons.append(new_row)

    return InlineKeyboardMarkup(new_buttons)


def _get_buttons_with_show(original_markup, url_hash: str):
    """生成带"显示 AI 总结"按钮的 markup"""
    if not original_markup or not original_markup.inline_keyboard:
        return None

    new_buttons = []
    for row in original_markup.inline_keyboard:
        new_row = []
        for btn in row:
            if "AI总结" in btn.text:
                new_row.append(InlineKeyboardButton("📝 AI总结", callback_data=f"reddit_summary_{url_hash}"))
            else:
                new_row.append(btn)
        new_buttons.append(new_row)

    return InlineKeyboardMarkup(new_buttons)


# 创建 handler
def get_reddit_ai_summary_handler():
    """获取 Reddit AI 总结 callback handler"""
    return CallbackQueryHandler(reddit_ai_summary_callback, pattern=r"^reddit_(summary|unsummary)_")
