import asyncio
import json
import logging
import re
import shlex
import time
from datetime import datetime

import httpx
from bs4 import BeautifulSoup
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from utils.command_factory import command_factory
from utils.config_manager import config_manager, get_config
from utils.country_data import COUNTRY_NAME_TO_CODE, SUPPORTED_COUNTRIES, get_country_flag
from utils.formatter import foldable_text_v2, foldable_text_with_markdown_v2
from utils.message_manager import (
    cancel_session_deletions,
    send_message_with_auto_delete,
    send_error,
    send_help,
    send_success,
    delete_user_command,
    MessageType
)
from utils.permissions import Permission
from utils.price_parser import extract_currency_and_price
from utils.session_manager import app_search_sessions as user_search_sessions


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Default search countries if none are specified by the user
DEFAULT_COUNTRIES = ["CN", "NG", "TR", "IN", "MY", "US"]

# iTunes Search API base URL
ITUNES_API_URL = "https://itunes.apple.com/"

# Headers for iTunes API requests
ITUNES_HEADERS = {
    "User-Agent": "iTunes/12.11.3 (Windows; Microsoft Windows 10 x64 Professional Edition (Build 19041); x64) AppleWebKit/7611.1022.4001.1 (KHTML, like Gecko) Version/14.1.1 Safari/7611.1022.4001.1",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
}

# Global variables (will be set by main.py)
rate_converter = None
cache_manager = None


def set_rate_converter(converter):
    global rate_converter
    rate_converter = converter


def set_cache_manager(manager):
    global cache_manager
    cache_manager = manager


class SappSearchAPI:
    """调用iTunes Search API进行App搜索的API类"""

    @staticmethod
    async def search_apps(query: str, country: str = "us", app_type: str = "software", limit: int = 50) -> dict:
        """
        使用iTunes Search API搜索App

        Args:
            query: 搜索关键词
            country: 国家代码 (默认us)
            app_type: 应用类型 (software, macSoftware, iPadSoftware)
            limit: 返回结果数量

        Returns:
            包含搜索结果的字典
        """
        try:
            async with httpx.AsyncClient(verify=False) as client:
                params = {"term": query, "country": country, "media": "software", "limit": limit, "entity": app_type}

                response = await client.get(
                    f"{ITUNES_API_URL}search", params=params, headers=ITUNES_HEADERS, timeout=15
                )
                response.raise_for_status()
                data = response.json()

                # Fallback search logic from py/sapp.py
                if (
                    not data.get("results") and app_type != "software"
                ):  # Only try fallback if not already general software
                    fallback_params = {
                        "term": query,
                        "country": country,
                        "media": "software",
                        "limit": limit,
                        "explicit": "Yes",
                    }
                    fallback_response = await client.get(
                        f"{ITUNES_API_URL}search", params=fallback_params, headers=ITUNES_HEADERS, timeout=15
                    )
                    fallback_response.raise_for_status()
                    fallback_data = fallback_response.json()
                    if fallback_data.get("results"):
                        data = fallback_data

                # 根据请求的平台类型过滤结果
                results = data.get("results", [])
                filtered_results = SappSearchAPI._filter_results_by_platform(results, app_type)

                return {"results": filtered_results, "query": query, "country": country, "app_type": app_type}

        except Exception as e:
            logger.error(f"App search error: {e}")
            return {"results": [], "query": query, "country": country, "app_type": app_type, "error": str(e)}

    @staticmethod
    def _filter_results_by_platform(results: list[dict], requested_app_type: str) -> list[dict]:
        """
        根据请求的平台类型过滤搜索结果

        Args:
            results: iTunes API 返回的原始结果
            requested_app_type: 请求的应用类型 (software, macSoftware, iPadSoftware)

        Returns:
            过滤后的结果列表
        """
        if requested_app_type == "software":
            # iOS 应用：过滤掉 macOS 应用
            return [app for app in results if app.get("kind") != "mac-software"]

        elif requested_app_type == "macSoftware":
            # macOS 应用：只保留 mac-software
            return [app for app in results if app.get("kind") == "mac-software"]

        elif requested_app_type == "iPadSoftware":
            # iPadOS 应用：过滤掉 macOS 应用，保留支持 iPad 的应用
            filtered = []
            for app in results:
                if app.get("kind") == "mac-software":
                    continue
                # 检查是否支持 iPad
                supported_devices = app.get("supportedDevices", [])
                if any("iPad" in device for device in supported_devices) or (not supported_devices and app.get("kind") != "mac-software"):
                    filtered.append(app)
            return filtered

        # 默认返回所有结果
        return results

    @staticmethod
    async def get_app_details(app_id: str, country: str = "us") -> dict | None:
        """
        根据App ID获取详细信息

        Args:
            app_id: App ID
            country: 国家代码

        Returns:
            App详细信息
        """
        try:
            async with httpx.AsyncClient(verify=False) as client:
                params = {"id": app_id, "country": country.lower()}

                response = await client.get(
                    f"{ITUNES_API_URL}lookup", params=params, headers=ITUNES_HEADERS, timeout=15
                )
                response.raise_for_status()
                data = response.json()

                results = data.get("results", [])
                return results[0] if results else None

        except Exception as e:
            logger.error(f"Error getting app details: {e}")
            return None


def format_search_results(search_data: dict) -> str:
    """Formats the search result message to be a simple prompt."""
    if search_data.get("error"):
        return f"❌ 搜索失败: {search_data['error']}"

    results = search_data["results"]
    app_type = search_data.get("app_type", "software")

    # 确定平台名称
    platform_name = {"software": "iOS", "macSoftware": "macOS", "iPadSoftware": "iPadOS"}.get(app_type, "iOS")

    if not results:
        return f"🔍 没有找到关键词 '{search_data['query']}' 的相关 {platform_name} 应用 (国家: {search_data['country'].upper()})"

    return f"请从下方选择您要查询的 {platform_name} 应用："


def create_search_keyboard(search_data: dict) -> InlineKeyboardMarkup:
    """创建搜索结果的内联键盘"""
    keyboard = []

    # 应用选择按钮 (每行1个，显示更多信息)
    results = search_data["results"]
    app_type = search_data.get("app_type", "software")

    # 确定平台图标
    platform_icon = {"software": "📱", "macSoftware": "💻", "iPadSoftware": "📱"}.get(app_type, "📱")

    # Only create buttons for the first 5 results, consistent with display
    for i in range(min(len(results), 5)):
        app = results[i]
        track_name = app.get("trackName", "未知应用")
        app_kind = app.get("kind", "")

        # 根据实际的应用类型确定图标，而不仅仅是搜索类型
        if app_kind == "mac-software":
            icon = "💻"
        elif any("iPad" in device for device in app.get("supportedDevices", [])):
            icon = "📱"  # iPad 应用
        else:
            icon = platform_icon  # 使用默认平台图标

        # 创建按钮文本，只显示应用名称和平台图标
        button_text = f"{icon} {i + 1}. {track_name}"

        callback_data = f"app_select_{i}_{search_data.get('current_page', 1)}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])

    current_page = search_data.get("current_page", 1)
    total_pages = search_data.get("total_pages", 1)

    nav_row = []
    if current_page > 1:
        nav_row.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"app_page_{current_page - 1}"))

    nav_row.append(InlineKeyboardButton(f"📄 {current_page}/{total_pages}", callback_data="app_page_info"))

    if current_page < total_pages:
        nav_row.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"app_page_{current_page + 1}"))

    if nav_row:
        keyboard.append(nav_row)

    # Operation buttons
    action_row = [
        InlineKeyboardButton("🌍 更改搜索地区", callback_data="app_change_region"),
        InlineKeyboardButton("❌ 关闭", callback_data="app_close"),
    ]
    keyboard.append(action_row)

    return InlineKeyboardMarkup(keyboard)


async def app_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /app 命令，使用iTunes API进行分页搜索"""
    if not update.message:
        return

    if not context.args:
        help_message = (
            "🔍 *App Store 搜索*\n\n"
            "支持应用名称搜索和App ID直接查询：\n\n"
            "**基本用法:**\n"
            "`/app 微信` - 搜索 iOS 应用\n"
            "`/app WhatsApp US` - 在美区搜索 iOS 应用\n\n"
            "**App ID 直接查询:**\n"
            "`/app id363590051` - 直接查询指定 App ID\n"
            "`/app id363590051 US CN JP` - 查询多国价格\n\n"
            "**平台筛选:**\n"
            "`/app Photoshop -mac` - 搜索 macOS 应用\n"
            "`/app id497799835 -mac` - 查询 macOS 应用价格\n"
            "`/app Procreate -ipad` - 搜索 iPadOS 应用\n\n"
            "💡 App ID 查询跳过搜索，直接显示价格对比。\n"
            "🔄 支持的平台: iOS (默认)、macOS、iPadOS"
        )
        if update.effective_chat:
            await send_help(context, update.effective_chat.id, foldable_text_with_markdown_v2(help_message), parse_mode="MarkdownV2")
            await delete_user_command(context, update.effective_chat.id, update.message.message_id)
        return

    user_id = update.effective_user.id if update.effective_user else None
    if not user_id:
        return

    args_str_full = " ".join(context.args)

    # 检测是否为 App ID 查询（格式：id + 数字）
    first_arg = context.args[0].lower()
    if first_arg.startswith("id") and first_arg[2:].isdigit():
        # App ID 直接查询
        await handle_app_id_query(update, context, args_str_full)
        return

    loading_text = "🔍 正在解析参数并准备搜索..."
    if not update.effective_chat:
        return

    message = await context.bot.send_message(
        chat_id=update.effective_chat.id, text=foldable_text_v2(loading_text), parse_mode="MarkdownV2"
    )

    try:
        # --- Start: Copied and adapted argument parsing logic from app_command ---
        args_str_processed = args_str_full
        app_type = "software"

        if "-mac" in args_str_processed:
            app_type = "macSoftware"
            args_str_processed = args_str_processed.replace("-mac", "").strip()
        elif "-ipad" in args_str_processed:
            app_type = "iPadSoftware"
            args_str_processed = args_str_processed.replace("-ipad", "").strip()
        args_str_processed = " ".join(args_str_processed.split())

        countries_parsed: list[str] = []
        app_name_to_search = None

        if not args_str_processed:
            error_message = "❌ 请输入应用名称。"
            await message.delete()
            config = get_config()
            await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
            return

        try:
            param_lexer = shlex.shlex(args_str_processed, posix=True)
            param_lexer.quotes = '"""＂'
            param_lexer.whitespace_split = True
            all_params_list = [p for p in list(param_lexer) if p]
        except ValueError as e:
            error_message = f"❌ 参数解析错误: {e!s}"
            await message.delete()
            config = get_config()
            await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
            return

        if not all_params_list:
            error_message = "❌ 参数解析后为空，请输入应用名称。"
            await message.delete()
            config = get_config()
            await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
            return

        app_name_parts_collected = []
        for param_idx, param_val in enumerate(all_params_list):
            is_country = param_val.upper() in SUPPORTED_COUNTRIES or param_val in COUNTRY_NAME_TO_CODE
            if is_country:
                countries_parsed.extend(all_params_list[param_idx:])
                break
            app_name_parts_collected.append(param_val)

        if not app_name_parts_collected:
            error_message = "❌ 未能从输入中解析出有效的应用名称。"
            await message.delete()
            config = get_config()
            await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
            return
        app_name_to_search = " ".join(app_name_parts_collected)

        final_countries_to_search = []
        if not countries_parsed:
            final_countries_to_search = None  # Will use DEFAULT_COUNTRIES later
        else:
            for country_input_str in countries_parsed:
                resolved_code = COUNTRY_NAME_TO_CODE.get(country_input_str, country_input_str.upper())
                if resolved_code in SUPPORTED_COUNTRIES and resolved_code not in final_countries_to_search:
                    final_countries_to_search.append(resolved_code)

        # Store user-specified countries in session for later use in show_app_details
        # 生成唯一的会话ID
        session_id = f"app_search_{user_id}_{int(time.time())}"

        # 如果用户已经有活跃的搜索会话，取消旧的删除任务
        if user_id in user_search_sessions:
            old_session = user_search_sessions[user_id]
            old_session_id = old_session.get("session_id")
            if old_session_id:
                cancelled_count = await cancel_session_deletions(old_session_id, context)
                logger.info(f"🔄 用户 {user_id} 有现有搜索会话，已取消 {cancelled_count} 个旧的删除任务")
            logger.info(
                f"🔄 User {user_id} has existing search session (message: {old_session.get('message_id')}, query: '{old_session.get('query')}'), will be replaced with new search"
            )

        user_search_sessions[user_id] = {"user_specified_countries": final_countries_to_search or None}

        # For search, we only use the first specified country.
        country_code = (final_countries_to_search[0] if final_countries_to_search else "US").lower()
        final_query = app_name_to_search
        # --- End: Argument parsing logic ---

        # 确定平台名称用于显示
        platform_display = {"software": "iOS", "macSoftware": "macOS", "iPadSoftware": "iPadOS"}.get(app_type, "iOS")

        search_status_message = f"🔍 正在在 {country_code.upper()} 区域搜索 {platform_display} 应用 '{final_query}' ..."
        await message.edit_text(foldable_text_v2(search_status_message), parse_mode="MarkdownV2")

        # 生成搜索缓存键
        search_cache_key = f"search_{final_query}_{country_code}_{app_type}"

        # 尝试从缓存加载搜索结果
        cached_search_data = await cache_manager.load_cache(
            search_cache_key,
            max_age_seconds=config_manager.config.app_store_search_cache_duration,
            subdirectory="app_store",
        )

        if cached_search_data:
            # 使用缓存的搜索结果
            all_results = cached_search_data.get("results", [])
            logger.info(f"使用缓存的搜索结果: {final_query} in {country_code}")
        else:
            # 从API获取搜索结果
            raw_search_data = await SappSearchAPI.search_apps(
                final_query, country=country_code, app_type=app_type, limit=200
            )
            all_results = raw_search_data.get("results", [])

            # 保存搜索结果到缓存
            search_cache_data = {
                "query": final_query,
                "country": country_code,
                "app_type": app_type,
                "results": all_results,
                "timestamp": time.time(),
            }
            await cache_manager.save_cache(search_cache_key, search_cache_data, subdirectory="app_store")
            logger.info(f"缓存搜索结果: {final_query} in {country_code}, 找到 {len(all_results)} 个结果")

        per_page = 5
        total_results = len(all_results)
        total_pages = min(10, (total_results + per_page - 1) // per_page) if total_results > 0 else 1

        page_results = all_results[0:per_page]

        search_data_for_session = {
            "query": final_query,
            "country": country_code,
            "app_type": app_type,
            "all_results": all_results,
            "current_page": 1,
            "total_pages": total_pages,
            "total_results": total_results,
            "per_page": per_page,
            "results": page_results,
        }

        user_search_sessions[user_id] = {
            "query": final_query,
            "search_data": search_data_for_session,
            "message_id": message.message_id,
            "user_specified_countries": final_countries_to_search or None,
            "chat_id": update.effective_chat.id,  # 获取 chat_id
            "session_id": session_id,  # 添加会话ID
            "created_at": datetime.now(),  # 添加创建时间
        }

        logger.info(
            f"✅ Created new search session for user {user_id}: message {message.message_id}, query '{final_query}', chat {update.effective_chat.id}, session {session_id}"
        )

        # Format and display results
        result_text = format_search_results(search_data_for_session)
        keyboard = create_search_keyboard(search_data_for_session)

        # 删除搜索进度消息，然后发送新的搜索结果消息
        await message.delete()
        
        # 使用统一的消息发送API发送搜索结果
        new_message = await send_message_with_auto_delete(
            context, 
            update.effective_chat.id, 
            foldable_text_v2(result_text), 
            MessageType.SEARCH_RESULT,
            session_id=session_id,
            reply_markup=keyboard, 
            parse_mode="MarkdownV2", 
            disable_web_page_preview=True
        )
        
        # 更新会话中的消息ID
        if new_message:
            user_search_sessions[user_id]["message_id"] = new_message.message_id

        # 删除用户命令消息
        if update.message:
            await delete_user_command(context, update.effective_chat.id, update.message.message_id, session_id=session_id)

    except Exception as e:
        logger.error(f"Search process error: {e}")
        error_message = f"❌ 搜索失败: {e!s}\n\n请稍后重试或联系管理员."
        await message.delete()
        config = get_config()
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")


async def handle_app_search_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理App搜索相关的回调查询"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    data = query.data

    # 检查用户是否有搜索会话
    if user_id not in user_search_sessions:
        logger.warning(f"❌ User {user_id} has no active search session for callback: {data}")
        error_message = "❌ 搜索会话已过期，请重新搜索。"
        await query.message.delete()
        await send_error(context, query.message.chat_id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        return

    session = user_search_sessions[user_id]
    logger.info(f"🔍 Processing callback for user {user_id}: {data}, session message: {session.get('message_id')}")

    try:
        if data.startswith("app_select_"):
            # 用户选择了某个应用
            parts = data.split("_")
            app_index = int(parts[2])

            # 获取选中的应用
            search_data = session["search_data"]
            if app_index < len(search_data["results"]):
                selected_app = search_data["results"][app_index]
                app_id = selected_app.get("trackId")

                if app_id:
                    loading_message = f"🔍 正在获取 '{selected_app.get('trackName', '应用')}' 的详细价格信息"
                    await query.edit_message_text(foldable_text_v2(loading_message), parse_mode="MarkdownV2")
                    await show_app_details(query, app_id, selected_app, context, session)
                else:
                    error_message = "❌ 无法获取应用ID，请重新选择。"
                    await query.edit_message_text(foldable_text_v2(error_message), parse_mode="MarkdownV2")

        elif data.startswith("app_page_"):
            if data == "app_page_info":
                return

            page = int(data.split("_")[2])
            session["search_data"]["current_page"] = page

            search_data = session["search_data"]
            all_results = search_data["all_results"]
            per_page = search_data["per_page"]

            start_index = (page - 1) * per_page
            end_index = start_index + per_page
            page_results = all_results[start_index:end_index]

            search_data["results"] = page_results

            result_text = format_search_results(search_data)
            keyboard = create_search_keyboard(search_data)

            await query.edit_message_text(foldable_text_v2(result_text), reply_markup=keyboard, parse_mode="MarkdownV2")

        elif data == "app_change_region":
            # 更改搜索地区
            change_region_text = "请选择新的搜索地区："

            # 定义地区按钮
            region_buttons = [
                InlineKeyboardButton("🇨🇳 中国", callback_data="app_region_CN"),
                InlineKeyboardButton("🇭🇰 香港", callback_data="app_region_HK"),
                InlineKeyboardButton("🇹🇼 台湾", callback_data="app_region_TW"),
                InlineKeyboardButton("🇯🇵 日本", callback_data="app_region_JP"),
                InlineKeyboardButton("🇬🇧 英国", callback_data="app_region_GB"),
                InlineKeyboardButton("❌ 关闭", callback_data="app_close"),
            ]

            # 每行2个按钮
            keyboard = [region_buttons[i : i + 2] for i in range(0, len(region_buttons), 2)]

            await query.edit_message_text(
                foldable_text_v2(change_region_text),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="MarkdownV2",
            )

        elif data.startswith("app_region_"):
            # 用户选择了新的搜索地区
            country_code = data.split("_")[2]

            # 从现有会话中获取基本信息
            final_query = session["query"]
            app_type = session["search_data"]["app_type"]

            loading_message = f"🔍 正在在 {country_code.upper()} 区域重新搜索 '{final_query}'..."
            await query.edit_message_text(foldable_text_v2(loading_message), parse_mode="MarkdownV2")

            # --- 开始重建会话 ---
            # 1. 获取新的搜索结果
            search_cache_key = f"search_{final_query}_{country_code.lower()}_{app_type}"
            cached_search_data = await cache_manager.load_cache(
                search_cache_key,
                max_age_seconds=config_manager.config.app_store_search_cache_duration,
                subdirectory="app_store",
            )

            if cached_search_data:
                all_results = cached_search_data.get("results", [])
                logger.info(f"使用缓存的搜索结果: {final_query} in {country_code.lower()}")
            else:
                raw_search_data = await SappSearchAPI.search_apps(
                    final_query, country=country_code.lower(), app_type=app_type, limit=200
                )
                all_results = raw_search_data.get("results", [])
                search_cache_data = {
                    "query": final_query,
                    "country": country_code.lower(),
                    "app_type": app_type,
                    "results": all_results,
                    "timestamp": time.time(),
                }
                await cache_manager.save_cache(search_cache_key, search_cache_data, subdirectory="app_store")
                logger.info(f"缓存搜索结果: {final_query} in {country_code.lower()}, 找到 {len(all_results)} 个结果")

            # 2. 准备分页和新的 search_data
            per_page = 5
            total_results = len(all_results)
            total_pages = min(10, (total_results + per_page - 1) // per_page) if total_results > 0 else 1
            page_results = all_results[0:per_page]

            search_data_for_session = {
                "query": final_query,
                "country": country_code.lower(),
                "app_type": app_type,
                "all_results": all_results,
                "current_page": 1,
                "total_pages": total_pages,
                "total_results": total_results,
                "per_page": per_page,
                "results": page_results,
            }

            # 3. 完全重建会话对象，而不是修补
            user_search_sessions[user_id] = {
                "query": final_query,
                "search_data": search_data_for_session,
                "message_id": query.message.message_id,
                "user_specified_countries": session.get("user_specified_countries"),
                "chat_id": query.message.chat_id,
                "session_id": session.get("session_id"),
                "created_at": datetime.now(),
            }
            logger.info(f"✅ Region changed. Rebuilt search session for user {user_id}")

            # 4. 显示新结果
            result_text = format_search_results(search_data_for_session)
            keyboard = create_search_keyboard(search_data_for_session)

            await query.edit_message_text(
                foldable_text_v2(result_text),
                reply_markup=keyboard,
                parse_mode="MarkdownV2",
                disable_web_page_preview=True,
            )

        elif data == "app_back_to_search":
            # 返回搜索结果
            search_data = session["search_data"]
            result_text = format_search_results(search_data)
            keyboard = create_search_keyboard(search_data)

            await query.edit_message_text(foldable_text_v2(result_text), reply_markup=keyboard, parse_mode="MarkdownV2")

        elif data == "app_new_search":
            # 开始新搜索
            new_search_message = "🔍 *开始新的搜索*\n\n请使用 `/app 应用名称` 命令开始新的搜索。\n\n例如: `/app 微信`"
            await query.edit_message_text(foldable_text_with_markdown_v2(new_search_message), parse_mode="MarkdownV2")
            # 清除会话
            if user_id in user_search_sessions:
                del user_search_sessions[user_id]

        elif data == "app_close":
            # 关闭搜索
            close_message = "🔍 搜索已关闭。\n\n使用 `/app 应用名称` 开始新的搜索。"
            await query.message.delete()
            await send_info(context, query.message.chat_id, foldable_text_v2(close_message), parse_mode="MarkdownV2")

            # 清除会话
            if user_id in user_search_sessions:
                del user_search_sessions[user_id]

    except Exception as e:
        logger.error(f"处理回调查询时发生错误: {e}")
        error_message = f"❌ 操作失败: {e!s}\n\n请重新搜索或联系管理员."
        await query.message.delete()
        await send_error(context, query.message.chat_id, foldable_text_v2(error_message), parse_mode="MarkdownV2")


async def show_app_details(
    query, app_id: str, app_info: dict, context: ContextTypes.DEFAULT_TYPE, session: dict
) -> None:
    try:
        user_specified_countries = session.get("user_specified_countries")
        countries_to_check = user_specified_countries or DEFAULT_COUNTRIES

        app_name = app_info.get("trackName", "未知应用")
        app_type = session.get("search_data", {}).get("app_type", "software")

        price_tasks = [get_app_prices(app_name, country, app_id, app_type, context) for country in countries_to_check]
        price_results_raw = await asyncio.gather(*price_tasks)

        target_plan = find_common_plan(price_results_raw)
        successful_results = [res for res in price_results_raw if res["status"] == "ok"]
        sorted_results = sorted(successful_results, key=lambda res: sort_key_func(res, target_plan))

        # --- 格式化消息 ---
        # 确定平台图标和名称
        platform_info = {
            "software": {"icon": "📱", "name": "iOS"},
            "macSoftware": {"icon": "💻", "name": "macOS"},
            "iPadSoftware": {"icon": "📱", "name": "iPadOS"},
        }.get(app_type, {"icon": "📱", "name": "iOS"})

        # Build header with MarkdownV2 formatting - will be handled by smart formatter
        header_lines = [f"{platform_info['icon']} *{app_name}*"]
        header_lines.append(f"🎯 平台: {platform_info['name']}")
        #        header_lines.append(f"👤 开发者: {developer}")
        #        if genre:
        #            header_lines.append(f"📂 分类: {genre}")
        header_lines.append(f"🆔 App ID: `id{app_id}`")

        raw_header = "\n".join(header_lines)

        price_details_lines = []
        if not sorted_results:
            price_details_lines.append("在可查询的区域中未找到该应用的价格信息。")
        else:
            for res in sorted_results:
                country_name = res["country_name"]
                app_price_str = res["app_price_str"]

                price_details_lines.append(f"🌍 国家/地区: {country_name}")
                price_details_lines.append(f"💰 应用价格 : {app_price_str}")
                if res["app_price_cny"] is not None and res["app_price_cny"] > 0:
                    price_details_lines[-1] += f" (约 ¥{res['app_price_cny']:.2f} CNY)"

                if res.get("in_app_purchases"):
                    for iap in res["in_app_purchases"]:
                        iap_name = iap["name"]
                        iap_price = iap["price_str"]
                        iap_line = f"  •   {iap_name}: {iap_price}"
                        if iap["cny_price"] is not None and iap["cny_price"] != float("inf"):
                            iap_line += f" (约 ¥{iap['cny_price']:.2f} CNY)"
                        price_details_lines.append(iap_line)
                price_details_lines.append("")

        price_details_text = "\n".join(price_details_lines)

        # --- 构建完整的原始消息 ---
        full_raw_message = f"{raw_header}\n\n{price_details_text}"

        # --- 使用新的智能 formatter 模块进行格式化和折叠 ---
        formatted_message = foldable_text_with_markdown_v2(full_raw_message)

        await query.edit_message_text(formatted_message, parse_mode="MarkdownV2", disable_web_page_preview=True)

    except Exception as e:
        logger.error(f"显示应用详情时发生错误: {e}", exc_info=True)
        error_message = f"❌ 获取应用详情失败: {e!s}"
        await query.edit_message_text(foldable_text_v2(error_message), parse_mode="MarkdownV2")


async def handle_app_id_query(update: Update, context: ContextTypes.DEFAULT_TYPE, args_str_full: str) -> None:
    """处理 App ID 直接查询"""
    if not update.effective_chat:
        return

    user_id = update.effective_user.id if update.effective_user else None
    if not user_id:
        return

    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=foldable_text_v2("🔍 正在解析 App ID 并获取应用信息..."),
        parse_mode="MarkdownV2",
    )

    try:
        # 解析参数
        args_str_processed = args_str_full
        app_type = "software"

        # 处理平台参数
        if "-mac" in args_str_processed:
            app_type = "macSoftware"
            args_str_processed = args_str_processed.replace("-mac", "").strip()
        elif "-ipad" in args_str_processed:
            app_type = "iPadSoftware"
            args_str_processed = args_str_processed.replace("-ipad", "").strip()

        args_str_processed = " ".join(args_str_processed.split())

        try:
            param_lexer = shlex.shlex(args_str_processed, posix=True)
            param_lexer.quotes = '"""＂'
            param_lexer.whitespace_split = True
            all_params_list = [p for p in list(param_lexer) if p]
        except ValueError as e:
            error_message = f"❌ 参数解析错误: {e!s}"
            await message.edit_text(foldable_text_v2(error_message), parse_mode="MarkdownV2")
            return

        if not all_params_list:
            error_message = "❌ 参数解析后为空，请提供 App ID。"
            await message.edit_text(foldable_text_v2(error_message), parse_mode="MarkdownV2")
            return

        # 提取 App ID
        app_id_param = all_params_list[0]
        if not (app_id_param.lower().startswith("id") and app_id_param[2:].isdigit()):
            error_message = "❌ 无效的 App ID 格式，请使用 id + 数字，如 id363590051"
            await message.edit_text(foldable_text_v2(error_message), parse_mode="MarkdownV2")
            return

        app_id = app_id_param[2:]  # 移除 'id' 前缀

        # 解析国家参数
        countries_parsed = []
        for param_val in all_params_list[1:]:
            is_country = param_val.upper() in SUPPORTED_COUNTRIES or param_val in COUNTRY_NAME_TO_CODE
            if is_country:
                resolved_code = COUNTRY_NAME_TO_CODE.get(param_val, param_val.upper())
                if resolved_code in SUPPORTED_COUNTRIES and resolved_code not in countries_parsed:
                    countries_parsed.append(resolved_code)

        # 确定要查询的国家
        countries_to_check = countries_parsed if countries_parsed else DEFAULT_COUNTRIES

        # 生成缓存键（基于 App ID、国家列表和平台类型）
        countries_hash = "_".join(sorted(countries_to_check))
        detail_cache_key = f"app_details_{app_id}_{countries_hash}_{app_type}"

        # 尝试从缓存加载完整的格式化结果
        cached_detail = await cache_manager.load_cache(
            detail_cache_key, max_age_seconds=config_manager.config.app_store_cache_duration, subdirectory="app_store"
        )

        if cached_detail:
            # 使用缓存的完整结果
            logger.info(f"使用缓存的应用详情: App ID {app_id}")
            formatted_message = cached_detail.get("formatted_message", "❌ 缓存数据格式错误")
            await message.edit_text(formatted_message, parse_mode="MarkdownV2", disable_web_page_preview=True)
            return

        # 直接使用 App ID 作为应用名称，先开始获取价格信息
        app_name = f"App ID {app_id}"

        # 获取多国价格信息
        await message.edit_text(foldable_text_v2(f"💰 正在获取 {app_name} 的多国价格信息..."), parse_mode="MarkdownV2")

        price_tasks = [
            get_app_prices(app_name, country, int(app_id), app_type, context) for country in countries_to_check
        ]
        price_results_raw = await asyncio.gather(*price_tasks)

        # 格式化结果
        target_plan = find_common_plan(price_results_raw)
        successful_results = [res for res in price_results_raw if res["status"] == "ok"]

        # 如果没有找到任何有效结果，显示错误
        if not successful_results:
            countries_str = ", ".join(countries_to_check)
            error_message = (
                f"❌ 在以下区域均未找到 App ID {app_id}：{countries_str}\\n\\n请检查 ID 是否正确或尝试其他区域"
            )
            await message.edit_text(foldable_text_v2(error_message), parse_mode="MarkdownV2")
            return

        # 从第一个成功的结果中获取真实的应用名称
        real_app_name = None
        for res in successful_results:
            if res.get("real_app_name"):
                real_app_name = res["real_app_name"]
                break

        # 如果获取到了真实的应用名称，使用它；否则保持原来的 App ID 格式
        if real_app_name:
            app_name = real_app_name

        sorted_results = sorted(successful_results, key=lambda res: sort_key_func(res, target_plan))

        # 确定平台图标和名称
        platform_info = {
            "software": {"icon": "📱", "name": "iOS"},
            "macSoftware": {"icon": "💻", "name": "macOS"},
            "iPadSoftware": {"icon": "📱", "name": "iPadOS"},
        }.get(app_type, {"icon": "📱", "name": "iOS"})

        # 构建消息头部
        header_lines = [f"{platform_info['icon']} *{app_name}*"]
        header_lines.append(f"🎯 平台: {platform_info['name']}")
        header_lines.append(f"🆔 App ID: `id{app_id}`")

        raw_header = "\n".join(header_lines)

        # 构建价格详情
        price_details_lines = []
        if not sorted_results:
            price_details_lines.append("在可查询的区域中未找到该应用的价格信息。")
        else:
            for res in sorted_results:
                country_name = res["country_name"]
                app_price_str = res["app_price_str"]

                price_details_lines.append(f"🌍 国家/地区: {country_name}")
                price_details_lines.append(f"💰 应用价格 : {app_price_str}")
                if res["app_price_cny"] is not None and res["app_price_cny"] > 0:
                    price_details_lines[-1] += f" (约 ¥{res['app_price_cny']:.2f} CNY)"

                if res.get("in_app_purchases"):
                    for iap in res["in_app_purchases"]:
                        iap_name = iap["name"]
                        iap_price = iap["price_str"]
                        iap_line = f"  •   {iap_name}: {iap_price}"
                        if iap["cny_price"] is not None and iap["cny_price"] != float("inf"):
                            iap_line += f" (约 ¥{iap['cny_price']:.2f} CNY)"
                        price_details_lines.append(iap_line)
                price_details_lines.append("")

        price_details_text = "\n".join(price_details_lines)

        # 构建完整消息
        full_raw_message = f"{raw_header}\n\n{price_details_text}"
        formatted_message = foldable_text_with_markdown_v2(full_raw_message)

        # 保存格式化结果到缓存
        cache_data = {
            "app_id": app_id,
            "app_name": app_name,
            "app_type": app_type,
            "countries": countries_to_check,
            "formatted_message": formatted_message,
            "timestamp": time.time(),
        }
        await cache_manager.save_cache(detail_cache_key, cache_data, subdirectory="app_store")
        logger.info(f"缓存应用详情: App ID {app_id}, 国家: {countries_hash}")

        # 生成会话ID用于消息管理
        session_id = f"app_id_query_{user_id}_{int(time.time())}"
        
        # 删除搜索进度消息，然后发送结果
        await message.delete()
        await send_message_with_auto_delete(
            context,
            update.effective_chat.id,
            formatted_message,
            MessageType.SEARCH_RESULT,
            session_id=session_id,
            parse_mode="MarkdownV2",
            disable_web_page_preview=True
        )

        # 删除用户命令消息
        if update.message:
            await delete_user_command(context, update.effective_chat.id, update.message.message_id, session_id=session_id)

    except Exception as e:
        logger.error(f"App ID 查询过程出错: {e}")
        error_message = f"❌ 查询失败: {e!s}\n\n请稍后重试或联系管理员。"
        await message.edit_text(foldable_text_v2(error_message), parse_mode="MarkdownV2")


async def get_app_prices(
    app_name: str, country_code: str, app_id: int, app_type: str, context: ContextTypes.DEFAULT_TYPE
) -> dict:
    """Fetches and formats app and in-app purchase prices for a given country."""
    global cache_manager, rate_converter

    cache_key = f"app_prices_{app_id}_{country_code}_{app_type}"

    # Check cache first (using app_store subdirectory)
    cached_data = await cache_manager.load_cache(
        cache_key, max_age_seconds=config_manager.config.app_store_cache_duration, subdirectory="app_store"
    )
    if cached_data:
        cache_timestamp = await cache_manager.get_cache_timestamp(cache_key, subdirectory="app_store")
        cache_info = (
            f"*(缓存于: {datetime.fromtimestamp(cache_timestamp).strftime('%Y-%m-%d %H:%M')})*"
            if cache_timestamp
            else ""
        )
        return {
            "country_code": country_code,
            "country_name": SUPPORTED_COUNTRIES.get(country_code, {}).get("name", country_code),
            "flag_emoji": get_country_flag(country_code),
            "status": "ok",
            "app_price_str": cached_data.get("app_price_str"),
            "app_price_cny": cached_data.get("app_price_cny"),
            "in_app_purchases": cached_data.get("in_app_purchases", []),
            "cache_info": cache_info,
            "real_app_name": cached_data.get("real_app_name"),  # 添加真实应用名称
        }

    country_info = SUPPORTED_COUNTRIES.get(country_code, {})
    country_name = country_info.get("name", country_code)
    flag_emoji = get_country_flag(country_code)

    url = f"https://apps.apple.com/{country_code.lower()}/app/id{app_id}"

    try:
        async with httpx.AsyncClient(follow_redirects=True, verify=False) as client:
            response = await client.get(url, timeout=12)
            response.raise_for_status()
            content = response.text
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            logger.info(f"App 'id{app_id}' not found in {country_code} (404).")
            return {
                "country_code": country_code,
                "country_name": country_name,
                "flag_emoji": flag_emoji,
                "status": "not_listed",
                "error_message": "未上架",
            }
        else:
            logger.error(f"HTTP error fetching prices for {app_name} in {country_code}: {e}")
            return {
                "country_code": country_code,
                "country_name": country_name,
                "flag_emoji": flag_emoji,
                "status": "error",
                "error_message": f"获取失败 (HTTP {e.response.status_code})",
            }
    except httpx.RequestError as e:
        logger.error(f"Failed to fetch prices for {app_name} in {country_code}: {e}")
        return {
            "country_code": country_code,
            "country_name": country_name,
            "flag_emoji": flag_emoji,
            "status": "error",
            "error_message": "获取失败 (网络错误)",
        }
    except Exception as e:
        logger.error(f"Unknown error fetching prices for {app_name} in {country_code}: {e}")
        return {
            "country_code": country_code,
            "country_name": country_name,
            "flag_emoji": flag_emoji,
            "status": "error",
            "error_message": "获取失败 (未知错误)",
        }

    try:
        # Try lxml first, fall back to html.parser if not available
        try:
            soup = BeautifulSoup(content, "lxml")
        except Exception:
            soup = BeautifulSoup(content, "html.parser")

        app_price_str = "免费"
        app_price_cny = 0.0
        real_app_name = None

        script_tags = soup.find_all("script", type="application/ld+json")
        for script in script_tags:
            try:
                json_data = json.loads(script.string)
                if isinstance(json_data, dict) and json_data.get("@type") == "SoftwareApplication":
                    # 获取应用名称
                    if not real_app_name:
                        real_app_name = json_data.get("name", "").strip()

                    offers = json_data.get("offers", {})
                    if offers:
                        price = offers.get("price", 0)
                        currency = offers.get("priceCurrency", "USD")
                        category = offers.get("category", "").lower()
                        if category != "free" and float(price) > 0:
                            app_price_str = f"{price} {currency}"
                            if country_code != "CN" and rate_converter:
                                cny_price = await rate_converter.convert(float(price), currency, "CNY")
                                if cny_price is not None:
                                    app_price_cny = cny_price
                    break
            except (json.JSONDecodeError, TypeError, ValueError):
                continue

        in_app_items = soup.select("li.list-with-numbers__item")
        unique_items = set()
        in_app_purchases = []

        if in_app_items:
            for item in in_app_items:
                name_tag = item.find("span", class_="truncate-single-line truncate-single-line--block")
                price_tag = item.find("span", class_="list-with-numbers__item__price medium-show-tablecell")

                if name_tag and price_tag:
                    name = name_tag.text.strip()
                    price_str = price_tag.text.strip()

                    if (name, price_str) not in unique_items:
                        unique_items.add((name, price_str))

                        in_app_cny_price = None
                        if country_code != "CN" and rate_converter:
                            detected_currency, price_value = extract_currency_and_price(price_str, country_code)
                            if price_value is not None:
                                cny_price = await rate_converter.convert(price_value, detected_currency, "CNY")
                                if cny_price is not None:
                                    in_app_cny_price = cny_price
                        in_app_purchases.append({"name": name, "price_str": price_str, "cny_price": in_app_cny_price})

        result_data = {
            "country_code": country_code,
            "country_name": country_name,
            "flag_emoji": flag_emoji,
            "status": "ok",
            "app_price_str": app_price_str,
            "app_price_cny": app_price_cny,
            "in_app_purchases": in_app_purchases,
            "real_app_name": real_app_name,  # 添加真实应用名称
        }

        # Save to cache before returning (using app_store subdirectory)
        await cache_manager.save_cache(cache_key, result_data, subdirectory="app_store")
        return result_data

    except Exception as e:
        logger.error(f"Error parsing prices for {app_name} in {country_code}: {e}")
        return {
            "country_code": country_code,
            "country_name": country_name,
            "flag_emoji": flag_emoji,
            "status": "error",
            "error_message": "解析失败",
        }


def extract_cny_price(price_str: str) -> float:
    """Extracts CNY price from a formatted string for sorting."""
    if "免费" in price_str:
        return 0.0

    # Matches "(约 ¥123.45)"
    match = re.search(r"\(约 ¥([\d,.]+)\)", price_str)
    if match:
        try:
            return float(match.group(1).replace(",", ""))
        except ValueError:
            return float("inf")

    return float("inf")


def find_common_plan(all_price_data: list[dict]) -> str | None:
    """Finds the most common subscription plan name across all results for sorting."""
    plan_counts = {}

    for price_data in all_price_data:
        if price_data["status"] == "ok":
            for iap in price_data.get("in_app_purchases", []):
                plan_name = iap["name"]
                plan_counts[plan_name] = plan_counts.get(plan_name, 0) + 1

    if not plan_counts:
        return None

    max_count = max(plan_counts.values())
    common_plans = [plan for plan, count in plan_counts.items() if count == max_count]

    for keyword in ["Pro", "Premium", "Plus", "Standard"]:
        for plan in common_plans:
            if keyword in plan:
                return plan

    return common_plans[0] if common_plans else None


def sort_key_func(price_data: dict, target_plan: str | None = None) -> tuple[float, float]:
    """Sorting key function for price results, prioritizing target plan or cheapest in-app/app price."""
    if price_data["status"] != "ok":
        return (float("inf"), float("inf"))  # Place non-ok statuses at the end

    app_price = price_data.get("app_price_cny", float("inf"))

    target_plan_price = float("inf")
    min_in_app_price = float("inf")

    in_app_purchases = price_data.get("in_app_purchases", [])

    for iap in in_app_purchases:
        cny_price = iap.get("cny_price")
        if cny_price is not None:
            if iap["name"] == target_plan:
                target_plan_price = cny_price
            min_in_app_price = min(min_in_app_price, cny_price)

    # Determine the effective price for sorting
    if target_plan_price != float("inf"):
        effective_price = target_plan_price
    elif min_in_app_price != float("inf"):
        effective_price = min_in_app_price
    else:
        effective_price = app_price

    # Return a tuple: the effective price and the main app price (for tie-breaking)
    return (effective_price, app_price)


async def app_store_clean_cache_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """清理App Store缓存"""
    if not update.effective_user or not update.effective_chat or not update.message:
        return

    user_id = update.effective_user.id
    config = get_config()

    # 删除用户命令消息
    await delete_user_command(context, update.message.chat_id, update.message.message_id)

    # 使用 MySQL 用户管理器进行权限检查
    user_manager = context.bot_data.get("user_cache_manager")
    if not user_manager:
        await send_error(context, update.effective_chat.id, "❌ 用户管理器未初始化。")
        return

    if not (await user_manager.is_super_admin(user_id) or await user_manager.is_admin(user_id)):
        await send_error(context, update.effective_chat.id, "❌ 你没有缓存管理权限。")
        return

    try:
        cache_manager = context.bot_data.get("cache_manager")
        if not cache_manager:
            await send_error(context, update.effective_chat.id, "❌ 缓存管理器未初始化。")
            return

        await cache_manager.clear_cache(subdirectory="app_store")

        result_text = "✅ App Store 相关的所有缓存已清理完成。\n\n包括：搜索结果、应用详情和价格信息。"

        await send_success(context, update.effective_chat.id, foldable_text_v2(result_text), parse_mode="MarkdownV2")

    except Exception as e:
        logger.error(f"App Store缓存清理失败: {e}")
        await send_error(context, update.effective_chat.id, f"❌ 缓存清理失败: {e!s}")


# Register commands
command_factory.register_command(
    "app", app_command, permission=Permission.USER, description="App Store应用搜索（支持iOS/macOS/iPadOS平台筛选）"
)
command_factory.register_command(
    "app_cleancache", app_store_clean_cache_command, permission=Permission.ADMIN, description="清理App Store缓存"
)
command_factory.register_callback(
    "^app_", handle_app_search_callback, permission=Permission.USER, description="App搜索回调处理"
)
