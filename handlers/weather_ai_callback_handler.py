"""
Weather AI日报按钮callback handler
处理天气查询结果的AI日报生成功能
点击按钮生成AI日报
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes, CallbackQueryHandler

logger = logging.getLogger(__name__)


async def weather_ai_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理Weather AI日报按钮点击"""
    query = update.callback_query

    try:
        # 解析callback_data
        if not query.data or not query.data.startswith("weather_ai_"):
            return

        # 提取城市hash
        city_hash = query.data.replace("weather_ai_", "")

        # 从缓存读取城市名
        cache_manager = context.bot_data.get("cache_manager")
        if not cache_manager:
            await query.answer("❌ 缓存服务未初始化", show_alert=True)
            return

        city = await cache_manager.get(
            f"weather_city:{city_hash}",
            subdirectory="weather"
        )

        if not city:
            await query.answer("❌ 查询已过期，请重新查询", show_alert=True)
            return

        # 立即answer移除加载圈
        await query.answer()

        # 立即编辑消息显示"生成中..."状态
        loading_text = "🤖 AI日报生成中，请稍候..."
        try:
            await query.edit_message_text(
                text=loading_text
            )
        except Exception as e:
            if "Message is not modified" not in str(e):
                logger.warning(f"更新加载状态失败: {e}")

        # 生成AI日报
        from commands.weather import weather_inline_execute
        from utils.formatter import foldable_text_with_markdown_v2

        result = await weather_inline_execute(city, use_ai_report=True)

        if result["success"]:
            # AI 日报是纯文本，使用普通 Markdown
            if "🤖" in result.get("title", "") or "敏敏" in result.get("message", ""):
                await query.edit_message_text(
                    text=result["message"],
                    parse_mode="Markdown"
                )
            else:
                await query.edit_message_text(
                    text=foldable_text_with_markdown_v2(result["message"]),
                    parse_mode="MarkdownV2"
                )
        else:
            error_message = f"❌ *{result['title']}*\n\n{result['message']}"
            await query.edit_message_text(
                text=foldable_text_with_markdown_v2(error_message),
                parse_mode="MarkdownV2"
            )

    except Exception as e:
        logger.error(f"处理Weather AI回调失败: {e}", exc_info=True)
        try:
            await query.answer("❌ 生成AI日报失败", show_alert=True)
        except Exception:
            pass


def get_handler():
    """返回CallbackQueryHandler"""
    return CallbackQueryHandler(weather_ai_callback, pattern=r"^weather_ai_")
