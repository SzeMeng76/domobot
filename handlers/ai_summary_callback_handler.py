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


def set_adapter(adapter):
    """设置ParseHubAdapter实例"""
    global _adapter
    _adapter = adapter


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

        message_id = query.message.message_id
        current_caption = query.message.caption or query.message.text

        if action == "summary":
            # 显示AI总结
            await query.answer("📝 生成中...")

            # URL哈希已从callback_data提取
            logger.info(f"🔑 URL哈希: {url_hash}")

            # 从Redis缓存读取解析数据
            cache_data = await _adapter.cache_manager.get(
                f"summary:{url_hash}",
                subdirectory="social_parser"
            )
            if not cache_data:
                logger.error(f"❌ 缓存已失效: cache:social_parser:summary:{url_hash}")
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
                # 没有缓存，重新解析URL并生成AI总结（类似parse_hub_bot）
                logger.info(f"📍 重新解析URL: {original_url}")

                # 重新解析获取完整的DownloadResult
                download_result, platform, _, error_msg = await _adapter.parse_url(
                    original_url,
                    user_id=query.from_user.id,
                    group_id=None
                )

                if not download_result:
                    await query.answer("❌ 重新解析失败，无法生成总结", show_alert=True)
                    return

                # 生成AI总结（传递完整的DownloadResult）
                logger.info(f"📍 准备调用 generate_ai_summary")
                ai_summary = await _adapter.generate_ai_summary(download_result)
                logger.info(f"📍 generate_ai_summary 调用完成")

                if not ai_summary:
                    await query.answer("❌ AI总结生成失败", show_alert=True)
                    return

                # 缓存AI总结（24小时）
                await _adapter.cache_manager.set(
                    f"ai_summary:{url_hash}",
                    {'summary': ai_summary},
                    ttl=86400,
                    subdirectory="social_parser"
                )
                logger.info(f"✅ AI总结已缓存: cache:social_parser:ai_summary:{url_hash}")

            # 缓存原始caption到内存（用于恢复）
            if message_id not in _message_cache:
                _message_cache[message_id] = {
                    "original": current_caption,
                    "url_hash": url_hash
                }

            # 缓存AI总结到内存
            _message_cache[message_id]["summary"] = ai_summary

            # 替换模式：只显示AI总结（类似parse_hub_bot）
            # 构建新caption：只包含AI总结和原链接
            summary_caption = f"📝 AI总结:\n\n{ai_summary}"

            # 添加原链接（从缓存数据中获取）
            if cache_data and cache_data.get('url'):
                summary_caption += f"\n\n🔗 原链接: {cache_data['url']}"

            # 更新按钮为"已显示"状态（✅表示已显示，点击可恢复原内容）
            new_markup = _get_buttons_with_hide(query.message.reply_markup, url_hash)

            # 判断消息类型：有caption用edit_caption，无caption用edit_text
            if query.message.caption:
                # 图片/视频消息（有caption）
                await query.edit_message_caption(
                    caption=summary_caption,
                    reply_markup=new_markup
                )
            else:
                # 纯文本消息（无caption）
                await query.edit_message_text(
                    text=summary_caption,
                    reply_markup=new_markup,
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )

            # 不需要第二次answer，已在第49行answer过
            # await query.answer("✅ 已显示AI总结", show_alert=False)

        elif action == "unsummary":
            # 隐藏AI总结，恢复原始caption
            await query.answer("隐藏中...")  # 立即answer避免超时

            if message_id in _message_cache and _message_cache[message_id].get("original"):
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
