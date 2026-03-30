"""
AI总结按钮callback handler
处理社交媒体解析结果的AI总结功能
点击按钮切换显示/隐藏AI总结内容
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions
from telegram.ext import ContextTypes, CallbackQueryHandler

logger = logging.getLogger(__name__)

# Global adapter reference
_adapter = None

# 缓存原始caption和AI总结
# 格式: {message_id: {"original": "原始caption", "summary": "AI总结内容", "url": "原始URL"}}
_message_cache = {}

# 缓存 download_result（用于AI总结）
# 格式: {url_hash: download_result}
# 短期缓存（1小时），避免内存泄漏
_download_result_cache = {}


def set_adapter(adapter):
    """设置ParseHubAdapter实例"""
    global _adapter
    _adapter = adapter


def cache_download_result(url_hash: str, download_result):
    """缓存 download_result（用于AI总结）"""
    global _download_result_cache
    _download_result_cache[url_hash] = download_result

    # 清理旧缓存（只保留最近 50 个）
    if len(_download_result_cache) > 50:
        # 删除最旧的 10 个
        keys_to_delete = list(_download_result_cache.keys())[:10]
        for key in keys_to_delete:
            del _download_result_cache[key]


async def ai_summary_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理AI总结按钮点击 - 切换显示/隐藏AI总结"""
    query = update.callback_query

    try:
        # 解析callback_data
        if not query.data:
            return

        # callback_data格式: summary_<url_hash> 或 unsummary_<url_hash>
        # 类似parse_hub_bot的实现
        if not ("summary_" in query.data or "unsummary_" in query.data):
            logger.warning(f"未知的callback_data格式: {query.data}")
            return

        action, url_hash = query.data.split("_", 1)

        # 判断是否为 inline 消息
        is_inline = query.inline_message_id is not None
        inline_message_id = query.inline_message_id if is_inline else None
        message_id = None if is_inline else query.message.message_id
        current_caption = None if is_inline else (query.message.caption or query.message.text)

        if action == "summary":
            # 立即answer移除加载圈
            await query.answer()

            # 立即编辑消息显示"生成中..."状态
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
                # 忽略"消息未修改"错误（Message is not modified）
                if "Message is not modified" not in str(e):
                    logger.warning(f"更新加载状态失败: {e}")

            # URL哈希已从callback_data提取
            logger.info(f"🔑 URL哈希: {url_hash}")

            # 检查 adapter 是否可用
            if not _adapter:
                # 恢复原始内容
                try:
                    if is_inline:
                        try:
                            await context.bot.edit_message_text(
                                inline_message_id=inline_message_id,
                                text="❌ 解析功能未初始化"
                            )
                        except Exception:
                            await context.bot.edit_message_caption(
                                inline_message_id=inline_message_id,
                                caption="❌ 解析功能未初始化"
                            )
                    elif current_caption:
                        await query.edit_message_caption(
                            caption=current_caption,
                            parse_mode="Markdown",
                            reply_markup=query.message.reply_markup
                        )
                    else:
                        await query.edit_message_text(
                            text=current_caption,
                            parse_mode="Markdown",
                            reply_markup=query.message.reply_markup,
                            link_preview_options=LinkPreviewOptions(is_disabled=True)
                        )
                except Exception:
                    pass

                await query.answer("❌ 解析功能未初始化", show_alert=True)
                return

            # 从Redis缓存读取解析数据
            cache_data = await _adapter.cache_manager.get(
                f"summary:{url_hash}",
                subdirectory="social_parser"
            )
            if not cache_data:
                logger.error(f"❌ 缓存已失效: cache:social_parser:summary:{url_hash}")

                # 恢复原始内容（移除"生成中"状态）
                try:
                    if is_inline:
                        # Inline 消息无法恢复，只能显示错误
                        try:
                            await context.bot.edit_message_text(
                                inline_message_id=inline_message_id,
                                text="❌ 缓存已失效，请重新发送链接"
                            )
                        except Exception:
                            await context.bot.edit_message_caption(
                                inline_message_id=inline_message_id,
                                caption="❌ 缓存已失效，请重新发送链接"
                            )
                    elif current_caption:
                        # 恢复原始 caption
                        await query.edit_message_caption(
                            caption=current_caption,
                            parse_mode="Markdown",
                            reply_markup=query.message.reply_markup
                        )
                    else:
                        # 恢复原始 text
                        await query.edit_message_text(
                            text=current_caption,
                            parse_mode="Markdown",
                            reply_markup=query.message.reply_markup,
                            link_preview_options=LinkPreviewOptions(is_disabled=True)
                        )
                except Exception as restore_error:
                    logger.warning(f"恢复原始内容失败: {restore_error}")

                await query.answer("❌ 缓存已失效，请重新发送链接", show_alert=True)
                return

            logger.info(f"✅ 从缓存读取数据: {cache_data.get('title', 'N/A')}")
            original_url = cache_data.get('url', '')

            # 检查是否已有AI总结缓存
            ai_summary_cache = await _adapter.cache_manager.get(
                f"ai_summary:{url_hash}",
                subdirectory="social_parser"
            )

            if ai_summary_cache:
                # 从缓存中提取AI总结文本
                ai_summary = ai_summary_cache.get('summary', '')
                logger.info(f"✅ 使用缓存的AI总结")
            else:
                # 没有缓存，从Redis读取parse_result并生成AI总结
                logger.info(f"📍 使用缓存的parse_result生成AI总结")

                # 优先从内存中获取 download_result（包含本地文件）
                download_result = _download_result_cache.get(url_hash)
                if download_result:
                    logger.info(f"✅ 从内存缓存读取 download_result")
                else:
                    logger.info(f"⚠️ 内存中没有 download_result，将使用图片URL")

                # 从缓存中重建parse_result对象
                parse_result_dict = cache_data.get('parse_result')
                if not parse_result_dict:
                    # 兼容旧缓存：如果没有parse_result，只用文本生成总结
                    logger.warning(f"⚠️ 缓存中没有parse_result，使用纯文本生成总结")
                    from types import SimpleNamespace
                    parse_result = SimpleNamespace(
                        title=cache_data.get('title', ''),
                        content=cache_data.get('content', ''),
                        platform=cache_data.get('platform', ''),
                        media=[]
                    )
                else:
                    # 重建简化的parse_result对象
                    from types import SimpleNamespace
                    parse_result = SimpleNamespace(
                        title=parse_result_dict.get('title', ''),
                        content=parse_result_dict.get('content', ''),
                        platform=parse_result_dict.get('platform', ''),
                        media=[]
                    )

                    # 重建media列表（包含图片URL）
                    media_list = parse_result_dict.get('media', [])
                    for m in media_list:
                        media_obj = SimpleNamespace(
                            url=m.get('url', ''),
                            width=m.get('width', 0),
                            height=m.get('height', 0),
                            type=m.get('type', '')
                        )
                        parse_result.media.append(media_obj)

                    logger.info(f"📍 重建parse_result: title={parse_result.title}, media_count={len(parse_result.media)}")

                # 生成AI总结（优先使用 download_result 中的本地文件）
                logger.info(f"📍 准备调用 generate_ai_summary")
                ai_summary = await _adapter.generate_ai_summary(parse_result, download_result=download_result)
                logger.info(f"📍 generate_ai_summary 调用完成")

                if not ai_summary:
                    # 恢复原始内容
                    try:
                        if is_inline:
                            # Inline 消息无法恢复原始内容（没有缓存），只能显示错误
                            try:
                                await context.bot.edit_message_text(
                                    inline_message_id=inline_message_id,
                                    text="❌ AI总结生成失败"
                                )
                            except Exception:
                                await context.bot.edit_message_caption(
                                    inline_message_id=inline_message_id,
                                    caption="❌ AI总结生成失败"
                                )
                        elif query.message.caption:
                            await query.edit_message_caption(
                                caption=current_caption,
                                parse_mode="Markdown",
                                reply_markup=query.message.reply_markup
                            )
                        else:
                            await query.edit_message_text(
                                text=current_caption,
                                parse_mode="Markdown",
                                reply_markup=query.message.reply_markup,
                                link_preview_options=LinkPreviewOptions(is_disabled=True)
                            )
                    except Exception as restore_error:
                        logger.warning(f"恢复原始内容失败: {restore_error}")

                    await query.answer("❌ AI总结生成失败，请稍后重试", show_alert=True)
                    return

                # 缓存AI总结（24小时）
                await _adapter.cache_manager.set(
                    f"ai_summary:{url_hash}",
                    {'summary': ai_summary},
                    ttl=86400,
                    subdirectory="social_parser"
                )
                logger.info(f"✅ AI总结已缓存: cache:social_parser:ai_summary:{url_hash}")

            # 缓存原始caption到内存（用于恢复）- inline 消息不缓存
            if not is_inline and message_id not in _message_cache:
                _message_cache[message_id] = {
                    "original": current_caption,
                    "url_hash": url_hash
                }

            # 缓存AI总结到内存 - inline 消息不缓存
            if not is_inline:
                _message_cache[message_id]["summary"] = ai_summary

            # 替换模式：只显示AI总结（类似parse_hub_bot）
            # 构建新caption：只包含AI总结和原链接
            # 清理AI总结中的不支持的HTML标签
            cleaned_summary = _clean_html_tags(ai_summary)
            summary_caption = f"📝 AI总结:\n\n{cleaned_summary}"

            # 添加原链接（从缓存数据中获取）
            if cache_data and cache_data.get('url'):
                summary_caption += f"\n\n🔗 原链接: {cache_data['url']}"

            # 更新按钮为"已显示"状态（✅表示已显示，点击可恢复原内容）
            # Inline 消息需要特殊处理按钮
            if is_inline:
                # Inline 消息：构建新按钮（原链接 + AI总结✅）
                buttons = [[InlineKeyboardButton("🔗 原链接", url=cache_data.get('url', ''))]]
                buttons[0].append(InlineKeyboardButton("📝 AI总结✅", callback_data=f"unsummary_{url_hash}"))
                new_markup = InlineKeyboardMarkup(buttons)
            else:
                new_markup = _get_buttons_with_hide(query.message.reply_markup, url_hash)

            # 判断消息类型：有caption用edit_caption，无caption用edit_text
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
                # 图片/视频消息（有caption）
                await query.edit_message_caption(
                    caption=summary_caption,
                    parse_mode="HTML",
                    reply_markup=new_markup
                )
            else:
                # 纯文本消息（无caption）
                await query.edit_message_text(
                    text=summary_caption,
                    parse_mode="HTML",
                    reply_markup=new_markup,
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )

            # 不需要第二次answer，已在第49行answer过
            # await query.answer("✅ 已显示AI总结", show_alert=False)

        elif action == "unsummary":
            # 隐藏AI总结，恢复原始caption
            await query.answer("隐藏中...")  # 立即answer避免超时

            # Inline 消息无法恢复原始内容（没有缓存），显示提示
            if is_inline:
                # 检查 adapter 是否可用
                if not _adapter:
                    await query.answer("❌ 解析功能未初始化", show_alert=True)
                    return

                # 从 Redis 缓存读取原始数据
                cache_data = await _adapter.cache_manager.get(
                    f"summary:{url_hash}",
                    subdirectory="social_parser"
                )
                if cache_data:
                    # 构建原始 caption
                    caption_parts = []
                    if cache_data.get('title'):
                        caption_parts.append(f"<b>{cache_data['title']}</b>")
                    if cache_data.get('content'):
                        caption_parts.append(cache_data['content'][:500])
                    original_caption = "\n\n".join(caption_parts) if caption_parts else "无标题"
                    if cache_data.get('url'):
                        original_caption += f"\n\n🔗 <a href=\"{cache_data['url']}\">原链接</a>"

                    # 恢复按钮为"显示"状态
                    buttons = [[InlineKeyboardButton("🔗 原链接", url=cache_data.get('url', ''))]]
                    buttons[0].append(InlineKeyboardButton("📝 AI总结", callback_data=f"summary_{url_hash}"))
                    new_markup = InlineKeyboardMarkup(buttons)

                    try:
                        await context.bot.edit_message_text(
                            inline_message_id=inline_message_id,
                            text=original_caption,
                            parse_mode="HTML",
                            reply_markup=new_markup,
                            link_preview_options=LinkPreviewOptions(is_disabled=True)
                        )
                    except Exception:
                        await context.bot.edit_message_caption(
                            inline_message_id=inline_message_id,
                            caption=original_caption,
                            parse_mode="HTML",
                            reply_markup=new_markup
                        )
                else:
                    await query.answer("❌ 无法恢复原始内容", show_alert=True)
            elif message_id in _message_cache and _message_cache[message_id].get("original"):
                original_caption = _message_cache[message_id]["original"]

                # 恢复按钮为"显示"状态
                new_markup = _get_buttons_with_show(query.message.reply_markup, url_hash)

                # 判断消息类型：有caption用edit_caption，无caption用edit_text
                if query.message.caption:
                    # 图片/视频消息（有caption）
                    await query.edit_message_caption(
                        caption=original_caption,
                        parse_mode="Markdown",
                        reply_markup=new_markup
                    )
                else:
                    # 纯文本消息（无caption）
                    await query.edit_message_text(
                        text=original_caption,
                        parse_mode="Markdown",
                        reply_markup=new_markup,
                        disable_web_page_preview=True
                    )

                # 不需要第二次answer，已在上面answer过
                # await query.answer("AI总结已隐藏", show_alert=False)
            # else分支已被删除：无法恢复时在上面已经answer过了，不需要额外处理

    except Exception as e:
        logger.error(f"AI总结callback处理失败: {e}", exc_info=True)
        await query.answer("❌ 处理失败", show_alert=True)


def _clean_html_tags(text: str) -> str:
    """
    清理不支持的HTML标签，只保留Telegram支持的标签
    Telegram支持的HTML标签: b, strong, i, em, u, ins, s, strike, del, code, pre, a, blockquote
    """
    import re

    # 替换 <br> 标签为换行
    text = text.replace('<br>', '\n').replace('<br/>', '\n').replace('<br />', '\n')

    # 移除所有不支持的标签（保留内容）
    # 匹配所有 <xxx> 和 </xxx> 标签，但排除支持的标签
    allowed_tags = r'(?!/?(?:b|strong|i|em|u|ins|s|strike|del|code|pre|a|blockquote)\b)'

    # 移除不支持的开始标签和结束标签（包括带属性的）
    text = re.sub(r'<' + allowed_tags + r'[^>]*?>', '', text)

    return text


def _get_buttons_with_hide(original_markup, url_hash: str):
    """生成带"隐藏AI总结"按钮的markup（✅表示已显示）"""
    if not original_markup or not original_markup.inline_keyboard:
        return None

    new_buttons = []
    for row in original_markup.inline_keyboard:
        new_row = []
        for btn in row:
            if "AI总结" in btn.text:
                # 替换为"已显示"按钮（类似parse_hub_bot的✅）
                new_row.append(InlineKeyboardButton("📝 AI总结✅", callback_data=f"unsummary_{url_hash}"))
            else:
                new_row.append(btn)
        new_buttons.append(new_row)

    return InlineKeyboardMarkup(new_buttons)


def _get_buttons_with_show(original_markup, url_hash: str):
    """生成带"显示AI总结"按钮的markup"""
    if not original_markup or not original_markup.inline_keyboard:
        return None

    new_buttons = []
    for row in original_markup.inline_keyboard:
        new_row = []
        for btn in row:
            if "AI总结" in btn.text:
                # 恢复为"显示"按钮
                new_row.append(InlineKeyboardButton("📝 AI总结", callback_data=f"summary_{url_hash}"))
            else:
                new_row.append(btn)
        new_buttons.append(new_row)

    return InlineKeyboardMarkup(new_buttons)


# 创建handler
def get_ai_summary_handler():
    """获取AI总结callback handler"""
    # 匹配 summary_<hash> 和 unsummary_<hash> 格式
    return CallbackQueryHandler(ai_summary_callback, pattern=r"^(summary|unsummary)_")
