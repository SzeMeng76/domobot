# Description: Steam 模块的回调处理器
# 从原 steam.py 拆分

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from utils.command_factory import command_factory
from utils.formatter import foldable_text_v2, foldable_text_with_markdown_v2
from utils.permissions import Permission
from utils.session_manager import steam_search_sessions

from .formatter import format_bundle_info, search_multiple_countries
from .models import Config
from .parser import get_country_code
from .search import get_bundle_details, search_game
from .ui import (
    create_steam_search_keyboard,
    format_steam_search_results,
)

logger = logging.getLogger(__name__)
config = Config()


async def steam_callback_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """处理Steam搜索结果的内联键盘回调"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    callback_data = query.data

    # 检查用户是否有活跃的搜索会话
    if user_id not in steam_search_sessions:
        await query.edit_message_text(
            foldable_text_v2("❌ 搜索会话已过期，请重新搜索"), parse_mode="MarkdownV2"
        )
        return

    session = steam_search_sessions[user_id]
    search_data = session["search_data"]

    try:
        if callback_data.startswith("steam_select_"):
            # 用户选择了一个游戏
            parts = callback_data.split("_")
            game_index = int(parts[2])
            page = int(parts[3])

            # 计算实际的游戏索引
            actual_index = (page - 1) * search_data["per_page"] + game_index

            if actual_index < len(search_data["all_results"]):
                selected_item = search_data["all_results"][actual_index]
                item_id = selected_item.get("id")
                item_type = selected_item.get("type", "game")

                if item_id:
                    # 显示加载消息
                    await query.edit_message_text(
                        foldable_text_v2("🔍 正在获取详细信息... ⏳"),
                        parse_mode="MarkdownV2",
                    )

                    # 根据类型处理不同的内容
                    if item_type == "bundle":
                        # 处理捆绑包
                        country_inputs = session["country_inputs"]
                        cc = get_country_code(country_inputs[0]) or config.DEFAULT_CC
                        bundle_details = await get_bundle_details(str(item_id), cc)

                        if bundle_details:
                            result = await format_bundle_info(bundle_details, cc)
                        else:
                            result = "❌ 无法获取捆绑包信息"
                    else:
                        # 处理游戏和DLC
                        country_inputs = session["country_inputs"]
                        result = await search_multiple_countries(
                            str(item_id), country_inputs
                        )

                    await query.edit_message_text(
                        foldable_text_with_markdown_v2(result), parse_mode="MarkdownV2"
                    )

                    # 清理用户会话
                    if user_id in steam_search_sessions:
                        del steam_search_sessions[user_id]
                else:
                    await query.edit_message_text(
                        foldable_text_v2("❌ 无法获取内容ID"), parse_mode="MarkdownV2"
                    )
            else:
                await query.edit_message_text(
                    foldable_text_v2("❌ 选择的内容索引无效"), parse_mode="MarkdownV2"
                )

        elif callback_data.startswith("steam_page_"):
            # 分页操作
            if callback_data == "steam_page_info":
                return

            page_num = int(callback_data.split("_")[2])
            current_page = search_data["current_page"]
            total_pages = search_data["total_pages"]

            if 1 <= page_num <= total_pages and page_num != current_page:
                # 更新页面数据
                per_page = search_data["per_page"]
                start_index = (page_num - 1) * per_page
                end_index = start_index + per_page
                page_results = search_data["all_results"][start_index:end_index]

                search_data["current_page"] = page_num
                search_data["results"] = page_results

                # 更新键盘和消息
                result_text = format_steam_search_results(search_data)
                keyboard = create_steam_search_keyboard(search_data)

                await query.edit_message_text(
                    foldable_text_v2(result_text),
                    reply_markup=keyboard,
                    parse_mode="MarkdownV2",
                )

        elif callback_data == "steam_new_search":
            # 新搜索
            await query.edit_message_text(
                foldable_text_v2("🔍 请使用 /steam [游戏名称] 开始新的搜索"),
                parse_mode="MarkdownV2",
            )

            # 清理用户会话
            if user_id in steam_search_sessions:
                del steam_search_sessions[user_id]

        elif callback_data == "steam_change_region":
            # 更改搜索地区
            change_region_text = "请选择新的搜索地区："

            # 定义地区按钮
            region_buttons = [
                InlineKeyboardButton("🇨🇳 中国", callback_data="steam_region_CN"),
                InlineKeyboardButton("🇭🇰 香港", callback_data="steam_region_HK"),
                InlineKeyboardButton("🇹🇼 台湾", callback_data="steam_region_TW"),
                InlineKeyboardButton("🇯🇵 日本", callback_data="steam_region_JP"),
                InlineKeyboardButton("🇺🇸 美国", callback_data="steam_region_US"),
                InlineKeyboardButton("🇬🇧 英国", callback_data="steam_region_GB"),
                InlineKeyboardButton("🇷🇺 俄罗斯", callback_data="steam_region_RU"),
                InlineKeyboardButton("🇹🇷 土耳其", callback_data="steam_region_TR"),
                InlineKeyboardButton("🇦🇷 阿根廷", callback_data="steam_region_AR"),
                InlineKeyboardButton("❌ 关闭", callback_data="steam_close"),
            ]

            # 每行2个按钮
            keyboard = [
                region_buttons[i : i + 2] for i in range(0, len(region_buttons), 2)
            ]

            await query.edit_message_text(
                foldable_text_v2(change_region_text),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="MarkdownV2",
            )

        elif callback_data.startswith("steam_region_"):
            # 用户选择了新的搜索地区
            country_code = callback_data.split("_")[2]

            # 更新会话中的国家输入
            session["country_inputs"] = [country_code]
            search_data["country_inputs"] = [country_code]

            # 显示重新搜索消息
            query_text = search_data["query"]
            loading_message = (
                f"🔍 正在在 {country_code.upper()} 区域重新搜索 '{query_text}'..."
            )
            await query.edit_message_text(
                foldable_text_v2(loading_message), parse_mode="MarkdownV2"
            )

            # 重新搜索游戏
            try:
                search_results = await search_game(
                    query_text, country_code, use_cache=False
                )

                if not search_results:
                    error_message = f"🔍 在 {country_code.upper()} 区域没有找到关键词 '{query_text}' 的相关内容"
                    await query.edit_message_text(
                        foldable_text_v2(error_message), parse_mode="MarkdownV2"
                    )
                    return

                # 更新搜索数据
                per_page = 5
                total_results = len(search_results)
                total_pages = (
                    min(10, (total_results + per_page - 1) // per_page)
                    if total_results > 0
                    else 1
                )
                page_results = search_results[0:per_page]

                search_data.update(
                    {
                        "all_results": search_results,
                        "current_page": 1,
                        "total_pages": total_pages,
                        "total_results": total_results,
                        "per_page": per_page,
                        "results": page_results,
                    }
                )

                # 显示新的搜索结果
                result_text = format_steam_search_results(search_data)
                keyboard = create_steam_search_keyboard(search_data)

                await query.edit_message_text(
                    foldable_text_v2(result_text),
                    reply_markup=keyboard,
                    parse_mode="MarkdownV2",
                    disable_web_page_preview=True,
                )

            except Exception as e:
                error_message = f"❌ 重新搜索失败: {e!s}"
                await query.edit_message_text(
                    foldable_text_v2(error_message), parse_mode="MarkdownV2"
                )

        elif callback_data == "steam_close":
            # 关闭搜索
            await query.edit_message_text(
                foldable_text_v2("🎮 Steam搜索已关闭"), parse_mode="MarkdownV2"
            )

            # 清理用户会话
            if user_id in steam_search_sessions:
                del steam_search_sessions[user_id]

    except Exception as e:
        logger.error(f"Error in steam callback handler: {e}")
        await query.edit_message_text(
            foldable_text_v2(f"❌ 处理请求时发生错误: {e!s}"), parse_mode="MarkdownV2"
        )

# 注册回调处理器
command_factory.register_callback(
    "^steam_",
    steam_callback_handler,
    permission=Permission.USER,
    description="Steam搜索回调处理",
)
