"""
Map Nearby 附近搜索按钮 callback handler
处理地图附近搜索的 category 按钮点击
支持 inline 和普通消息
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)

# Global references
_map_service = None
_telegraph_service = None

# Category 映射
CATEGORY_MAP = {
    "restaurant": {"name": "餐厅", "emoji": "🍽️"},
    "hospital": {"name": "医院", "emoji": "🏥"},
    "bank": {"name": "银行", "emoji": "🏦"},
    "gas_station": {"name": "加油站", "emoji": "⛽"},
    "supermarket": {"name": "超市", "emoji": "🏪"},
    "hotel": {"name": "酒店", "emoji": "🏨"}
}


def set_map_service(service):
    """设置地图服务"""
    global _map_service
    _map_service = service


def set_telegraph_service(service):
    """设置 Telegraph 服务"""
    global _telegraph_service
    _telegraph_service = service


async def map_nearby_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理地图附近搜索按钮点击"""
    query = update.callback_query

    try:
        if not query.data or not query.data.startswith("map_nearby_"):
            return

        # callback_data 格式: map_nearby_{type}_{lat}_{lng}
        parts = query.data.split("_")
        if len(parts) < 5:
            await query.answer("❌ 数据格式错误", show_alert=True)
            return

        category_type = parts[2]  # restaurant, hospital, etc.
        lat = parts[3]
        lng = parts[4]

        # 验证 category
        if category_type not in CATEGORY_MAP:
            await query.answer("❌ 未知的类别", show_alert=True)
            return

        category_info = CATEGORY_MAP[category_type]
        category_name = category_info["name"]
        category_emoji = category_info["emoji"]

        # 判断是否为 inline 消息
        is_inline = query.inline_message_id is not None
        inline_message_id = query.inline_message_id if is_inline else None

        # 立即 answer 移除加载圈
        await query.answer()

        # 显示"搜索中..."状态
        loading_text = f"🔍 正在搜索附近的{category_name}..."
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
            elif query.message:
                if query.message.caption:
                    await query.edit_message_caption(
                        caption=loading_text,
                        reply_markup=query.message.reply_markup
                    )
                else:
                    await query.edit_message_text(
                        text=loading_text,
                        reply_markup=query.message.reply_markup
                    )
        except Exception as e:
            if "Message is not modified" not in str(e):
                logger.warning(f"更新加载状态失败: {e}")

        # 检查依赖
        if not _map_service:
            await query.answer("❌ 地图服务未初始化", show_alert=True)
            return

        # 搜索附近地点
        try:
            places = await _map_service.search_nearby_places(
                float(lat),
                float(lng),
                category_type,
                radius=2000
            )

            if not places:
                result_text = f"❌ 附近没有找到{category_name}"

                if is_inline:
                    try:
                        await context.bot.edit_message_text(
                            inline_message_id=inline_message_id,
                            text=result_text
                        )
                    except Exception:
                        await context.bot.edit_message_caption(
                            inline_message_id=inline_message_id,
                            caption=result_text
                        )
                elif query.message:
                    if query.message.caption:
                        await query.edit_message_caption(caption=result_text)
                    else:
                        await query.edit_message_text(text=result_text)
                return

            # 格式化结果
            result_lines = [f"{category_emoji} *附近的{category_name}*\n"]

            for idx, place in enumerate(places[:10], 1):
                name = place.get("name", "未知")
                address = place.get("address", "")
                distance = place.get("distance", 0)
                rating = place.get("rating", 0)

                # 转义特殊字符
                from telegram.helpers import escape_markdown
                safe_name = escape_markdown(name, version=2)
                safe_address = escape_markdown(address, version=2) if address else ""

                line = f"{idx}\\. *{safe_name}*"
                if rating > 0:
                    line += f" ⭐ {rating}"
                if distance > 0:
                    if distance < 1000:
                        line += f" \\({int(distance)}m\\)"
                    else:
                        line += f" \\({distance/1000:.1f}km\\)"
                if safe_address:
                    line += f"\n   📍 {safe_address}"

                result_lines.append(line)

            result_text = "\n\n".join(result_lines)

            # 检查长度，如果太长则使用 Telegraph
            if len(result_text) > 1024 and _telegraph_service:
                # 创建 Telegraph 页面
                telegraph_content = f"<h3>{category_emoji} 附近的{category_name}</h3>"
                for idx, place in enumerate(places, 1):
                    name = place.get("name", "未知")
                    address = place.get("address", "")
                    distance = place.get("distance", 0)
                    rating = place.get("rating", 0)

                    telegraph_content += f"<p><strong>{idx}. {name}</strong>"
                    if rating > 0:
                        telegraph_content += f" ⭐ {rating}"
                    if distance > 0:
                        if distance < 1000:
                            telegraph_content += f" ({int(distance)}m)"
                        else:
                            telegraph_content += f" ({distance/1000:.1f}km)"
                    telegraph_content += "</p>"
                    if address:
                        telegraph_content += f"<p>📍 {address}</p>"

                telegraph_url = await _telegraph_service.create_page(
                    title=f"附近的{category_name}",
                    content=telegraph_content
                )

                result_text = f"{category_emoji} *附近的{category_name}*\n\n找到 {len(places)} 个地点\n\n[📄 查看完整列表]({telegraph_url})"

            # 编辑消息
            if is_inline:
                try:
                    await context.bot.edit_message_text(
                        inline_message_id=inline_message_id,
                        text=result_text,
                        parse_mode=ParseMode.MARKDOWN_V2,
                        disable_web_page_preview=True
                    )
                except Exception:
                    await context.bot.edit_message_caption(
                        inline_message_id=inline_message_id,
                        caption=result_text,
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
            elif query.message:
                if query.message.caption:
                    await query.edit_message_caption(
                        caption=result_text,
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
                else:
                    await query.edit_message_text(
                        text=result_text,
                        parse_mode=ParseMode.MARKDOWN_V2,
                        disable_web_page_preview=True
                    )

        except Exception as e:
            logger.error(f"附近搜索失败: {e}", exc_info=True)
            error_text = f"❌ 搜索{category_name}失败: {str(e)}"

            if is_inline:
                try:
                    await context.bot.edit_message_text(
                        inline_message_id=inline_message_id,
                        text=error_text
                    )
                except Exception:
                    await context.bot.edit_message_caption(
                        inline_message_id=inline_message_id,
                        caption=error_text
                    )
            elif query.message:
                if query.message.caption:
                    await query.edit_message_caption(caption=error_text)
                else:
                    await query.edit_message_text(text=error_text)

    except Exception as e:
        logger.error(f"Map nearby callback 处理失败: {e}", exc_info=True)
        await query.answer("❌ 处理失败", show_alert=True)


# 创建 handler
def get_map_nearby_handler():
    """获取 Map Nearby callback handler"""
    return CallbackQueryHandler(map_nearby_callback, pattern=r"^map_nearby_")
