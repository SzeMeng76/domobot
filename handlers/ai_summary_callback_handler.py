"""
AI总结按钮callback handler
处理社交媒体解析结果的AI总结功能
点击按钮切换显示/隐藏AI总结内容
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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

        # "ai_summary:parse_id" - 显示AI总结
        # "hide_summary:parse_id" - 隐藏AI总结
        action, parse_id = query.data.split(":", 1)

        message_id = query.message.message_id
        current_caption = query.message.caption or query.message.text

        if action == "ai_summary":
            # 显示AI总结
            await query.answer("📝 生成中...")

            # 检查缓存
            if message_id in _message_cache and _message_cache[message_id].get("summary"):
                # 使用缓存的AI总结
                ai_summary = _message_cache[message_id]["summary"]
            else:
                # 提取原始URL
                import re
                url_match = re.search(r'🔗 \[原链接\]\((https?://[^\)]+)\)', current_caption)

                if not url_match:
                    await query.answer("❌ 无法找到原链接", show_alert=True)
                    return

                original_url = url_match.group(1)

                # 缓存原始caption
                if message_id not in _message_cache:
                    _message_cache[message_id] = {"original": current_caption, "url": original_url}

                # 重新解析URL
                user_id = query.from_user.id
                result, platform, _ = await _adapter.parse_url(original_url, user_id)

                if not result or not result.pr:
                    await query.answer("❌ 解析失败", show_alert=True)
                    return

                # 生成AI总结
                ai_summary = await _adapter.generate_ai_summary(result.pr)

                if not ai_summary:
                    await query.answer("❌ AI总结生成失败", show_alert=True)
                    return

                # 缓存AI总结
                _message_cache[message_id]["summary"] = ai_summary

            # 构建新caption（原始内容 + AI总结）
            new_caption = _message_cache[message_id]["original"] + f"\n\n📝 *AI总结:*\n{ai_summary}"

            # 更新按钮为"已显示"状态
            new_markup = _get_buttons_with_hide(query.message.reply_markup, parse_id)

            await query.edit_message_caption(
                caption=new_caption,
                parse_mode="Markdown",
                reply_markup=new_markup
            )

            await query.answer("✅ AI总结已显示", show_alert=False)

        elif action == "hide_summary":
            # 隐藏AI总结，恢复原始caption
            if message_id in _message_cache and _message_cache[message_id].get("original"):
                original_caption = _message_cache[message_id]["original"]

                # 恢复按钮为"显示"状态
                new_markup = _get_buttons_with_show(query.message.reply_markup, parse_id)

                await query.edit_message_caption(
                    caption=original_caption,
                    parse_mode="Markdown",
                    reply_markup=new_markup
                )

                await query.answer("AI总结已隐藏", show_alert=False)
            else:
                await query.answer("无法恢复原始内容", show_alert=True)

    except Exception as e:
        logger.error(f"AI总结callback处理失败: {e}", exc_info=True)
        await query.answer("❌ 处理失败", show_alert=True)


def _get_buttons_with_hide(original_markup, parse_id: str):
    """生成带"隐藏AI总结"按钮的markup"""
    if not original_markup or not original_markup.inline_keyboard:
        return None

    new_buttons = []
    for row in original_markup.inline_keyboard:
        new_row = []
        for btn in row:
            if "AI总结" in btn.text or "生成中" in btn.text:
                # 替换为"隐藏"按钮
                new_row.append(InlineKeyboardButton("📝 AI总结✅", callback_data=f"hide_summary:{parse_id}"))
            else:
                new_row.append(btn)
        new_buttons.append(new_row)

    return InlineKeyboardMarkup(new_buttons)


def _get_buttons_with_show(original_markup, parse_id: str):
    """生成带"显示AI总结"按钮的markup"""
    if not original_markup or not original_markup.inline_keyboard:
        return None

    new_buttons = []
    for row in original_markup.inline_keyboard:
        new_row = []
        for btn in row:
            if "AI总结" in btn.text:
                # 替换为"显示"按钮
                new_row.append(InlineKeyboardButton("📝 AI总结", callback_data=f"ai_summary:{parse_id}"))
            else:
                new_row.append(btn)
        new_buttons.append(new_row)

    return InlineKeyboardMarkup(new_buttons)


# 创建handler
def get_ai_summary_handler():
    """获取AI总结callback handler"""
    return CallbackQueryHandler(ai_summary_callback, pattern=r"^(ai_summary|hide_summary):")
