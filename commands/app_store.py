"""
App Store 应用搜索和价格查询

重构版本 - 使用模块化架构
支持 iOS/iPadOS/macOS/tvOS/watchOS/visionOS 全平台
"""

import logging
import shlex
import time
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

# 导入新的模块化组件
from commands.app_store_modules import (
    DEFAULT_COUNTRIES,
    PLATFORM_FLAGS,
    PLATFORM_INFO,
)
from utils.command_factory import command_factory
from utils.constants import (
    APP_STORE_MAX_PAGES,
    APP_STORE_RESULTS_PER_PAGE,
    APP_STORE_SEARCH_LIMIT,
    DEFAULT_APP_STORE_PLATFORM,
)
from utils.formatter import foldable_text_v2, foldable_text_with_markdown_v2
from utils.message_manager import (
    MessageType,
    cancel_session_deletions,
    delete_user_command,
    send_error,
    send_help,
    send_info,
    send_message_with_auto_delete,
    send_success,
)
from utils.permissions import Permission
from utils.session_manager import app_search_sessions as user_search_sessions

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 使用 constants.py 中定义的常量
RESULTS_PER_PAGE = APP_STORE_RESULTS_PER_PAGE
MAX_TOTAL_PAGES = APP_STORE_MAX_PAGES
SEARCH_RESULT_LIMIT = APP_STORE_SEARCH_LIMIT


# ======= 辅助函数 =======


def parse_command_args(args_str: str) -> list[str]:
    """解析命令参数

    Args:
        args_str: 原始参数字符串

    Returns:
        list[str]: 解析后的参数列表

    Raises:
        ValueError: 参数解析错误
    """
    param_lexer = shlex.shlex(args_str, posix=True)
    param_lexer.quotes = '"""＂'
    param_lexer.whitespace_split = True
    return [p for p in list(param_lexer) if p]


def extract_platform_flag(args_str: str) -> tuple[str, str]:
    """提取平台参数

    Args:
        args_str: 原始参数字符串

    Returns:
        tuple[str, str]: (平台类型, 清理后的参数字符串)
    """
    platform = DEFAULT_APP_STORE_PLATFORM  # 默认平台
    cleaned_args = args_str

    for flag, platform_type in PLATFORM_FLAGS.items():
        if flag in args_str:
            platform = platform_type
            cleaned_args = args_str.replace(flag, "").strip()
            break

    return platform, " ".join(cleaned_args.split())


def is_valid_country(param: str) -> bool:
    """检查参数是否为有效的国家代码或名称

    支持输入:
    - 国家代码: US, TR, CN
    - 中文名称: 美国, 土耳其, 中国
    - 英文全名: USA, Turkey, China

    Args:
        param: 待检查的参数

    Returns:
        bool: 是否为有效国家
    """
    from utils.country_mapper import is_valid_country_input

    return is_valid_country_input(param)


def parse_countries(params: list[str]) -> list[str]:
    """从参数列表中解析国家代码

    Args:
        params: 参数列表

    Returns:
        list[str]: 解析出的国家代码列表（已去重）
    """
    from utils.country_mapper import get_country_code

    countries = []
    for param in params:
        resolved_code = get_country_code(param)
        if resolved_code and resolved_code not in countries:
            countries.append(resolved_code)
    return countries


async def send_error_and_delete_message(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    error_msg: str,
    message_to_delete=None,
) -> None:
    """发送错误消息并删除指定消息

    Args:
        context: Telegram 上下文
        chat_id: 聊天 ID
        error_msg: 错误消息文本
        message_to_delete: 需要删除的消息对象（可选）
    """
    if message_to_delete:
        await message_to_delete.delete()
    await send_error(
        context, chat_id, foldable_text_v2(error_msg), parse_mode="MarkdownV2"
    )


class CacheKeyBuilder:
    """缓存键构建器"""

    @staticmethod
    def app_prices(app_id: int, country_code: str, platform: str) -> str:
        """构建应用价格缓存键"""
        return f"app_prices_{app_id}_{country_code.lower()}_{platform}"

    @staticmethod
    def search(query: str, country_code: str, platform: str) -> str:
        """构建搜索结果缓存键"""
        return f"search_{query}_{country_code.lower()}_{platform}"

    @staticmethod
    def app_details(app_id: int, countries: list[str], platform: str) -> str:
        """构建应用详情缓存键"""
        countries_hash = "_".join(sorted(c.lower() for c in countries))
        return f"app_details_{app_id}_{countries_hash}_{platform}"


def build_search_session_data(
    query: str, country: str, platform: str, all_results: list[dict]
) -> dict:
    """构建搜索会话数据

    Args:
        query: 搜索关键词
        country: 国家代码
        platform: 平台类型
        all_results: 所有搜索结果

    Returns:
        dict: 会话数据字典
    """
    total_results = len(all_results)
    total_pages = (
        min(MAX_TOTAL_PAGES, (total_results + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE)
        if total_results > 0
        else 1
    )
    page_results = all_results[0:RESULTS_PER_PAGE]

    return {
        "query": query,
        "country": country,
        "platform": platform,
        "all_results": all_results,
        "current_page": 1,
        "total_pages": total_pages,
        "total_results": total_results,
        "per_page": RESULTS_PER_PAGE,
        "results": page_results,
    }


def calculate_effective_price(
    price_data: dict, target_plan: str = None
) -> tuple[float, float]:
    """计算用于排序的有效价格

    优先级：
    1. 目标订阅计划价格（如果指定）
    2. 最低内购价格
    3. 应用价格

    Args:
        price_data: 价格数据字典
        target_plan: 目标订阅计划名称（可选）

    Returns:
        tuple[float, float]: (有效价格, 应用价格)
    """
    if price_data.get("status") != "ok":
        return (float("inf"), float("inf"))

    app_price = price_data.get("app_price_cny", float("inf"))
    target_plan_price = float("inf")
    min_in_app_price = float("inf")

    in_app_purchases = price_data.get("in_app_purchases", [])
    for iap in in_app_purchases:
        cny_price = iap.get("cny_price")
        if cny_price is not None:
            if target_plan and iap["name"] == target_plan:
                target_plan_price = cny_price
            min_in_app_price = min(min_in_app_price, cny_price)

    # 确定有效价格
    if target_plan_price != float("inf"):
        effective_price = target_plan_price
    elif min_in_app_price != float("inf"):
        effective_price = min_in_app_price
    else:
        effective_price = app_price

    return (effective_price, app_price)


def format_help_message() -> str:
    """格式化帮助消息"""
    return (
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
        "`/app Procreate -ipad` - 搜索 iPadOS 应用\n"
        "`/app Netflix -tv` - 搜索 tvOS 应用\n"
        "`/app Fitness -watch` - 搜索 watchOS 应用\n"
        "`/app Safari -vision` - 搜索 visionOS 应用\n\n"
        "💡 App ID 查询跳过搜索，直接显示价格对比。\n"
        "🔄 支持的平台: iOS (默认)、iPadOS、macOS、tvOS、watchOS、visionOS"
    )


def format_search_results(search_data: dict) -> str:
    """格式化搜索结果消息"""
    if search_data.get("error"):
        return f"❌ {search_data['error']}"

    results = search_data["results"]
    platform = search_data.get("platform", DEFAULT_APP_STORE_PLATFORM)

    # 获取平台显示信息
    platform_info = PLATFORM_INFO.get(platform, {"name": "iOS"})
    platform_name = platform_info["name"]

    if not results:
        query = search_data.get("query", "")
        country = search_data.get("country", "").upper()
        return (
            f"🔍 没有找到关键词 '{query}' 的相关 {platform_name} 应用 (国家: {country})"
        )

    return f"请从下方选择您要查询的 {platform_name} 应用："


def create_search_keyboard(search_data: dict) -> InlineKeyboardMarkup:
    """创建搜索结果的内联键盘"""
    results = search_data["results"]
    current_page = search_data.get("current_page", 1)
    total_pages = search_data.get("total_pages", 1)

    keyboard = []

    # 添加应用列表按钮
    for idx, app in enumerate(results[:RESULTS_PER_PAGE]):
        app_kind = app.get("kind", "")
        # 根据应用类型确定图标
        icon = "💻" if app_kind == "mac-software" else "📱"
        app_name = app.get("trackName", "未知应用")[:35]

        keyboard.append(
            [
                InlineKeyboardButton(
                    f"{icon} {app_name}", callback_data=f"app_select_{idx}"
                )
            ]
        )

    # 添加分页按钮
    page_buttons = []
    if current_page > 1:
        page_buttons.append(
            InlineKeyboardButton(
                "◀️ 上一页", callback_data=f"app_page_{current_page - 1}"
            )
        )

    page_buttons.append(
        InlineKeyboardButton(
            f"📄 {current_page}/{total_pages}", callback_data="app_page_info"
        )
    )

    if current_page < total_pages:
        page_buttons.append(
            InlineKeyboardButton(
                "下一页 ▶️", callback_data=f"app_page_{current_page + 1}"
            )
        )

    if page_buttons:
        keyboard.append(page_buttons)

    # 添加功能按钮
    keyboard.append(
        [
            InlineKeyboardButton("🌍 切换地区", callback_data="app_change_region"),
            InlineKeyboardButton("❌ 关闭", callback_data="app_close"),
        ]
    )

    return InlineKeyboardMarkup(keyboard)


def find_common_plan(price_results: list[dict]) -> str | None:
    """找到最常见的订阅计划名称用于排序"""
    plan_counts = {}

    for price_data in price_results:
        if price_data.get("status") == "ok":
            for iap in price_data.get("in_app_purchases", []):
                plan_name = iap["name"]
                plan_counts[plan_name] = plan_counts.get(plan_name, 0) + 1

    if not plan_counts:
        return None

    max_count = max(plan_counts.values())
    common_plans = [plan for plan, count in plan_counts.items() if count == max_count]

    # 优先选择特定关键词的计划
    for keyword in ["Pro", "Premium", "Plus", "Standard"]:
        for plan in common_plans:
            if keyword in plan:
                return plan

    return common_plans[0] if common_plans else None


def format_app_details(
    app_name: str,
    app_id: str,
    platform: str,
    price_results: list[dict],
    target_plan: str = None,
) -> str:
    """格式化应用详情消息"""
    # 获取平台信息
    platform_info = PLATFORM_INFO.get(platform, {"icon": "📱", "name": "iOS"})

    # 构建消息头部
    header_lines = [f"{platform_info['icon']} *{app_name}*"]
    header_lines.append(f"🎯 平台: {platform_info['name']}")
    header_lines.append(f"🆔 App ID: `id{app_id}`")

    raw_header = "\n".join(header_lines)

    # 构建价格详情
    price_details_lines = []

    # 过滤出成功的结果
    successful_results = [res for res in price_results if res.get("status") == "ok"]

    if not successful_results:
        price_details_lines.append("在可查询的区域中未找到该应用的价格信息。")
    else:
        # 按价格排序 - 使用提取的函数
        sorted_results = sorted(
            successful_results,
            key=lambda price_data: calculate_effective_price(price_data, target_plan),
        )

        for res in sorted_results:
            country_name = res["country_name"]
            app_price_str = res["app_price_str"]

            price_details_lines.append(f"🌍 国家/地区: {country_name}")
            price_details_lines.append(f"💰 应用价格 : {app_price_str}")

            if res["app_price_cny"] is not None and res["app_price_cny"] > 0:
                price_details_lines[-1] += f" (约 ¥{res['app_price_cny']:.2f} CNY)"

            # 内购项目
            if res.get("in_app_purchases"):
                for iap in res["in_app_purchases"]:
                    iap_name = iap["name"]
                    iap_price = iap["price_str"]
                    iap_line = f"  •   {iap_name}: {iap_price}"
                    if iap["cny_price"] is not None and iap["cny_price"] != float(
                        "inf"
                    ):
                        iap_line += f" (约 ¥{iap['cny_price']:.2f} CNY)"
                    price_details_lines.append(iap_line)

            price_details_lines.append("")

    price_details_text = "\n".join(price_details_lines)

    # 构建完整消息
    full_raw_message = f"{raw_header}\n\n{price_details_text}"

    return full_raw_message


async def app_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /app 命令，使用新的模块化架构"""
    # 从 context.bot_data 获取 AppStorePriceBot 实例
    bot = context.bot_data.get("app_store_price_bot")
    if not bot:
        error_message = "❌ 错误：App Store 查询服务未初始化。"
        if update.effective_chat:
            await send_error(
                context,
                update.effective_chat.id,
                foldable_text_v2(error_message),
                parse_mode="MarkdownV2",
            )
        return

    if not update.message:
        return

    if not context.args:
        # 生成帮助消息
        help_message = format_help_message()
        if update.effective_chat:
            await send_help(
                context,
                update.effective_chat.id,
                foldable_text_with_markdown_v2(help_message),
                parse_mode="MarkdownV2",
            )
            await delete_user_command(
                context, update.effective_chat.id, update.message.message_id
            )
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
        chat_id=update.effective_chat.id,
        text=foldable_text_v2(loading_text),
        parse_mode="MarkdownV2",
    )

    try:
        # 解析参数（包括新的平台参数）
        platform, args_str_processed = extract_platform_flag(args_str_full)

        # 解析国家和应用名称
        if not args_str_processed:
            error_message = "❌ 请输入应用名称。"
            await send_error_and_delete_message(
                context, update.effective_chat.id, error_message, message
            )
            return

        try:
            all_params_list = parse_command_args(args_str_processed)
        except ValueError as e:
            error_message = f"❌ 参数解析错误: {e!s}"
            await send_error_and_delete_message(
                context, update.effective_chat.id, error_message, message
            )
            return

        if not all_params_list:
            error_message = "❌ 参数解析后为空，请输入应用名称。"
            await send_error_and_delete_message(
                context, update.effective_chat.id, error_message, message
            )
            return

        app_name_parts_collected = []
        countries_parsed = []
        for param_idx, param_val in enumerate(all_params_list):
            if is_valid_country(param_val):
                countries_parsed = all_params_list[param_idx:]
                break
            app_name_parts_collected.append(param_val)

        if not app_name_parts_collected:
            error_message = "❌ 未能从输入中解析出有效的应用名称。"
            await send_error_and_delete_message(
                context, update.effective_chat.id, error_message, message
            )
            return

        app_name_to_search = " ".join(app_name_parts_collected)

        # 解析国家参数
        final_countries_to_search = (
            parse_countries(countries_parsed) if countries_parsed else None
        )

        # 生成唯一的会话ID
        session_id = f"app_search_{user_id}_{int(time.time())}"

        # 如果用户已经有活跃的搜索会话，取消旧的删除任务
        if user_id in user_search_sessions:
            old_session = user_search_sessions[user_id]
            old_session_id = old_session.get("session_id")
            if old_session_id:
                cancelled_count = await cancel_session_deletions(
                    old_session_id, context
                )
                logger.info(
                    f"🔄 用户 {user_id} 有现有搜索会话，已取消 {cancelled_count} 个旧的删除任务"
                )

        # For search, we only use the first specified country.
        country_code = (
            final_countries_to_search[0] if final_countries_to_search else "US"
        ).lower()
        final_query = app_name_to_search

        # 获取平台显示信息
        platform_info = PLATFORM_INFO.get(platform, {"name": "iOS"})
        platform_display = platform_info["name"]

        search_status_message = f"🔍 正在在 {country_code.upper()} 区域搜索 {platform_display} 应用 '{final_query}' ..."
        await message.edit_text(
            foldable_text_v2(search_status_message), parse_mode="MarkdownV2"
        )

        # 使用新的搜索缓存加载函数
        all_results = await bot.load_or_fetch_search_results(
            final_query, country_code, platform
        )

        # 使用新的分页数据构建函数
        search_data_for_session = build_search_session_data(
            final_query, country_code, platform, all_results
        )

        user_search_sessions[user_id] = {
            "query": final_query,
            "search_data": search_data_for_session,
            "message_id": message.message_id,
            "user_specified_countries": final_countries_to_search or None,
            "chat_id": update.effective_chat.id,
            "session_id": session_id,
            "created_at": datetime.now(),
        }

        logger.info(
            f"✅ Created new search session for user {user_id}: message {message.message_id}, query '{final_query}', platform {platform}"
        )

        # 使用新的格式化器
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
            disable_web_page_preview=True,
        )

        # 更新会话中的消息ID
        if new_message:
            user_search_sessions[user_id]["message_id"] = new_message.message_id

        # 删除用户命令消息
        if update.message:
            await delete_user_command(
                context,
                update.effective_chat.id,
                update.message.message_id,
                session_id=session_id,
            )

    except Exception as e:
        logger.error(f"Search process error: {e}")
        error_message = f"❌ 搜索失败: {e!s}\n\n请稍后重试或联系管理员."
        await message.delete()
        await send_error(
            context,
            update.effective_chat.id,
            foldable_text_v2(error_message),
            parse_mode="MarkdownV2",
        )


async def handle_app_id_query(
    update: Update, context: ContextTypes.DEFAULT_TYPE, args_str_full: str
) -> None:
    """处理 App ID 直接查询"""
    # 从 context.bot_data 获取 AppStorePriceBot 实例
    bot = context.bot_data.get("app_store_price_bot")
    if not bot:
        if update.effective_chat:
            await send_error(
                context,
                update.effective_chat.id,
                foldable_text_v2("❌ 错误：App Store 查询服务未初始化。"),
                parse_mode="MarkdownV2",
            )
        return

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
        platform, args_str_processed = extract_platform_flag(args_str_full)

        try:
            all_params_list = parse_command_args(args_str_processed)
        except ValueError as e:
            error_message = f"❌ 参数解析错误: {e!s}"
            await message.edit_text(
                foldable_text_v2(error_message), parse_mode="MarkdownV2"
            )
            return

        if not all_params_list:
            error_message = "❌ 参数解析后为空，请提供 App ID。"
            await message.edit_text(
                foldable_text_v2(error_message), parse_mode="MarkdownV2"
            )
            return

        # 提取 App ID
        app_id_param = all_params_list[0]
        if not (app_id_param.lower().startswith("id") and app_id_param[2:].isdigit()):
            error_message = "❌ 无效的 App ID 格式，请使用 id + 数字，如 id363590051"
            await message.edit_text(
                foldable_text_v2(error_message), parse_mode="MarkdownV2"
            )
            return

        app_id = app_id_param[2:]  # 移除 'id' 前缀

        # 解析国家参数 - 使用新的解析函数
        countries_parsed = parse_countries(all_params_list[1:])

        # 确定要查询的国家
        countries_to_check = countries_parsed if countries_parsed else DEFAULT_COUNTRIES

        # 生成缓存键（使用新的缓存键构建器）
        detail_cache_key = CacheKeyBuilder.app_details(
            int(app_id), countries_to_check, platform
        )

        # 尝试从缓存加载完整的格式化结果
        cached_detail = await bot.cache_manager.load_cache(
            detail_cache_key,
            max_age_seconds=bot.redis_cache_duration,
            subdirectory="app_store",
        )

        if cached_detail:
            # 使用缓存的完整结果
            logger.info(f"使用缓存的应用详情: App ID {app_id}")
            formatted_message = cached_detail.get(
                "formatted_message", "❌ 缓存数据格式错误"
            )
            await message.edit_text(
                formatted_message,
                parse_mode="MarkdownV2",
                disable_web_page_preview=True,
            )
            return

        # 直接使用 App ID 作为应用名称，先开始获取价格信息
        app_name = f"App ID {app_id}"

        # 获取多国价格信息
        await message.edit_text(
            foldable_text_v2(f"💰 正在获取 {app_name} 的多国价格信息..."),
            parse_mode="MarkdownV2",
        )

        # 获取多国价格信息
        price_results_raw = await bot.get_multi_country_prices(
            app_name=app_name,
            app_id=int(app_id),
            platform=platform,
            countries=countries_to_check,
        )

        # 格式化结果
        target_plan = find_common_plan(price_results_raw)
        successful_results = [res for res in price_results_raw if res["status"] == "ok"]

        # 如果没有找到任何有效结果，显示错误
        if not successful_results:
            countries_str = ", ".join(countries_to_check)
            error_message = f"❌ 在以下区域均未找到 App ID {app_id}：{countries_str}\n\n请检查 ID 是否正确或尝试其他区域"
            await message.edit_text(
                foldable_text_v2(error_message), parse_mode="MarkdownV2"
            )
            return

        # 从第一个成功的结果中获取真实的应用名称
        real_app_name = None
        for res in successful_results:
            if res.get("real_app_name"):
                real_app_name = res["real_app_name"]
                break

        # 如果获取到了真实的应用名称，使用它
        if real_app_name:
            app_name = real_app_name

        # 使用新的格式化器
        full_raw_message = format_app_details(
            app_name=app_name,
            app_id=app_id,
            platform=platform,
            price_results=price_results_raw,
            target_plan=target_plan,
        )

        formatted_message = foldable_text_with_markdown_v2(full_raw_message)

        # 保存格式化结果到缓存
        cache_data = {
            "app_id": app_id,
            "app_name": app_name,
            "platform": platform,
            "countries": countries_to_check,
            "formatted_message": formatted_message,
            "timestamp": time.time(),
        }
        await bot.cache_manager.save_cache(
            detail_cache_key, cache_data, subdirectory="app_store"
        )
        logger.info(
            f"缓存应用详情: App ID {app_id}, 国家: {', '.join(countries_to_check)}"
        )

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
            disable_web_page_preview=True,
        )

        # 删除用户命令消息
        if update.message:
            await delete_user_command(
                context,
                update.effective_chat.id,
                update.message.message_id,
                session_id=session_id,
            )

    except Exception as e:
        logger.error(f"App ID 查询过程出错: {e}")
        error_message = f"❌ 查询失败: {e!s}\n\n请稍后重试或联系管理员。"
        await message.edit_text(
            foldable_text_v2(error_message), parse_mode="MarkdownV2"
        )


async def handle_app_search_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """处理App搜索相关的回调查询"""
    # 从 context.bot_data 获取 AppStorePriceBot 实例
    bot = context.bot_data.get("app_store_price_bot")
    if not bot:
        query = update.callback_query
        if query:
            await query.answer("❌ 服务未初始化")
        return

    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    data = query.data

    # 检查用户是否有搜索会话
    if user_id not in user_search_sessions:
        logger.warning(
            f"❌ User {user_id} has no active search session for callback: {data}"
        )
        error_message = "❌ 搜索会话已过期，请重新搜索。"
        await query.message.delete()
        await send_error(
            context,
            query.message.chat_id,
            foldable_text_v2(error_message),
            parse_mode="MarkdownV2",
        )
        return

    session = user_search_sessions[user_id]
    logger.info(
        f"🔍 Processing callback for user {user_id}: {data}, session message: {session.get('message_id')}"
    )

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
                    await query.edit_message_text(
                        foldable_text_v2(loading_message), parse_mode="MarkdownV2"
                    )
                    await show_app_details(
                        query, app_id, selected_app, context, session
                    )
                else:
                    error_message = "❌ 无法获取应用ID，请重新选择。"
                    await query.edit_message_text(
                        foldable_text_v2(error_message), parse_mode="MarkdownV2"
                    )

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

            await query.edit_message_text(
                foldable_text_v2(result_text),
                reply_markup=keyboard,
                parse_mode="MarkdownV2",
            )

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
            keyboard = [
                region_buttons[i : i + 2] for i in range(0, len(region_buttons), 2)
            ]

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
            platform = session["search_data"]["platform"]

            loading_message = (
                f"🔍 正在在 {country_code.upper()} 区域重新搜索 '{final_query}'..."
            )
            await query.edit_message_text(
                foldable_text_v2(loading_message), parse_mode="MarkdownV2"
            )

            # 使用新的搜索缓存加载函数
            all_results = await bot.load_or_fetch_search_results(
                final_query, country_code.lower(), platform
            )

            # 使用新的分页数据构建函数
            search_data_for_session = build_search_session_data(
                final_query, country_code.lower(), platform, all_results
            )

            # 重建会话对象
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

            # 显示新结果
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

            await query.edit_message_text(
                foldable_text_v2(result_text),
                reply_markup=keyboard,
                parse_mode="MarkdownV2",
            )

        elif data == "app_new_search":
            # 开始新搜索
            new_search_message = "🔍 *开始新的搜索*\n\n请使用 `/app 应用名称` 命令开始新的搜索。\n\n例如: `/app 微信`"
            await query.edit_message_text(
                foldable_text_with_markdown_v2(new_search_message),
                parse_mode="MarkdownV2",
            )
            # 清除会话
            if user_id in user_search_sessions:
                del user_search_sessions[user_id]

        elif data == "app_close":
            # 关闭搜索
            close_message = "🔍 搜索已关闭。\n\n使用 `/app 应用名称` 开始新的搜索。"
            await query.message.delete()
            await send_info(
                context,
                query.message.chat_id,
                foldable_text_v2(close_message),
                parse_mode="MarkdownV2",
            )

            # 清除会话
            if user_id in user_search_sessions:
                del user_search_sessions[user_id]

    except Exception as e:
        logger.error(f"处理回调查询时发生错误: {e}")
        error_message = f"❌ 操作失败: {e!s}\n\n请重新搜索或联系管理员."
        await query.message.delete()
        await send_error(
            context,
            query.message.chat_id,
            foldable_text_v2(error_message),
            parse_mode="MarkdownV2",
        )


async def show_app_details(
    query,
    app_id: str,
    app_info: dict,
    context: ContextTypes.DEFAULT_TYPE,
    session: dict,
) -> None:
    """显示应用详情"""
    # 从 context.bot_data 获取 AppStorePriceBot 实例
    bot = context.bot_data.get("app_store_price_bot")
    if not bot:
        await query.edit_message_text(
            foldable_text_v2("❌ 错误：App Store 查询服务未初始化。"),
            parse_mode="MarkdownV2",
        )
        return

    try:
        user_specified_countries = session.get("user_specified_countries")
        countries_to_check = user_specified_countries or DEFAULT_COUNTRIES

        app_name = app_info.get("trackName", "未知应用")
        platform = session.get("search_data", {}).get("platform", "iphone")

        # 获取多国价格信息
        price_results_raw = await bot.get_multi_country_prices(
            app_name=app_name,
            app_id=int(app_id),
            platform=platform,
            countries=countries_to_check,
        )

        target_plan = find_common_plan(price_results_raw)

        # 使用新的格式化器
        full_raw_message = format_app_details(
            app_name=app_name,
            app_id=str(app_id),
            platform=platform,
            price_results=price_results_raw,
            target_plan=target_plan,
        )

        formatted_message = foldable_text_with_markdown_v2(full_raw_message)

        await query.edit_message_text(
            formatted_message, parse_mode="MarkdownV2", disable_web_page_preview=True
        )

    except Exception as e:
        logger.error(f"显示应用详情时发生错误: {e}", exc_info=True)
        error_message = f"❌ 获取应用详情失败: {e!s}"
        await query.edit_message_text(
            foldable_text_v2(error_message), parse_mode="MarkdownV2"
        )


async def app_store_clean_cache_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """清理App Store缓存"""
    # 从 context.bot_data 获取 AppStorePriceBot 实例
    bot = context.bot_data.get("app_store_price_bot")
    if not bot:
        if update.effective_chat:
            await send_error(
                context,
                update.effective_chat.id,
                "❌ 错误：App Store 查询服务未初始化。",
            )
        return

    if not update.effective_user or not update.effective_chat or not update.message:
        return

    user_id = update.effective_user.id

    # 删除用户命令消息
    await delete_user_command(
        context, update.message.chat_id, update.message.message_id
    )

    # 使用 MySQL 用户管理器进行权限检查
    user_manager = context.bot_data.get("user_cache_manager")
    if not user_manager:
        await send_error(context, update.effective_chat.id, "❌ 用户管理器未初始化。")
        return

    if not (
        await user_manager.is_super_admin(user_id)
        or await user_manager.is_admin(user_id)
    ):
        await send_error(context, update.effective_chat.id, "❌ 你没有缓存管理权限。")
        return

    try:
        cache_manager_obj = context.bot_data.get("cache_manager")
        if not cache_manager_obj:
            await send_error(
                context, update.effective_chat.id, "❌ 缓存管理器未初始化。"
            )
            return

        await cache_manager_obj.clear_cache(subdirectory="app_store")

        result_text = "✅ App Store 相关的所有缓存已清理完成。\n\n包括：搜索结果、应用详情和价格信息。"

        await send_success(
            context,
            update.effective_chat.id,
            foldable_text_v2(result_text),
            parse_mode="MarkdownV2",
        )

    except Exception as e:
        logger.error(f"App Store缓存清理失败: {e}")
        await send_error(context, update.effective_chat.id, f"❌ 缓存清理失败: {e!s}")


# Register commands
command_factory.register_command(
    "app",
    app_command,
    permission=Permission.USER,
    description="App Store应用搜索（支持iOS/iPadOS/macOS/tvOS/watchOS/visionOS）",
)
command_factory.register_command(
    "app_cleancache",
    app_store_clean_cache_command,
    permission=Permission.ADMIN,
    description="清理App Store缓存",
)


async def app_store_clear_item_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """清理指定 App ID 的所有缓存（Redis + MySQL），可选按国家限定。"""
    # 从 context.bot_data 获取组件
    cache_manager_obj = context.bot_data.get("cache_manager")
    db_manager = context.bot_data.get("price_history_manager")

    if not update.effective_chat or not update.effective_user or not update.message:
        return

    # 删除用户命令消息
    await delete_user_command(
        context, update.message.chat_id, update.message.message_id
    )

    # 管理员校验（与 /app_cleancache 一致）
    user_manager = context.bot_data.get("user_cache_manager")
    if not user_manager:
        await send_error(context, update.effective_chat.id, "❌ 用户管理器未初始化。")
        return

    user_id = update.effective_user.id
    if not (
        await user_manager.is_super_admin(user_id)
        or await user_manager.is_admin(user_id)
    ):
        await send_error(context, update.effective_chat.id, "❌ 你没有缓存管理权限。")
        return

    # 解析参数: /app_clearitem <id或idXXXX> [国家...]
    if not context.args:
        await send_error(context, update.effective_chat.id, "❌ 用法: /app_clearitem <AppID或idXXXX> [国家...]")
        return

    raw_id = context.args[0].strip().lower()
    app_id_str = raw_id[2:] if raw_id.startswith("id") else raw_id
    if not app_id_str.isdigit():
        await send_error(context, update.effective_chat.id, "❌ App ID 格式不正确。示例: 932747118 或 id932747118")
        return

    app_id = app_id_str

    # 解析可选国家参数
    extra_params = context.args[1:] if len(context.args) > 1 else []
    countries = parse_countries(extra_params) if extra_params else []

    # 清理 Redis: app 价格缓存键前缀
    cleared_redis = 0
    if cache_manager_obj:
        try:
            if countries:
                for c in countries:
                    # 匹配所有平台，目标国家
                    prefix = f"app_store:prices:*:{app_id}:{c.upper()}"
                    await cache_manager_obj.clear_cache(
                        key_prefix=prefix, subdirectory="app_store"
                    )
            else:
                # 所有平台、所有国家
                prefix = f"app_store:prices:*:{app_id}:"
                await cache_manager_obj.clear_cache(
                    key_prefix=prefix, subdirectory="app_store"
                )
        except Exception as e:
            await send_error(context, update.effective_chat.id, f"❌ 清理 Redis 失败: {e!s}")
            return

    # 清理 MySQL: price_history
    deleted_db = 0
    if db_manager:
        try:
            if countries:
                for c in countries:
                    deleted_db += await db_manager.delete_item(
                        service="app_store", item_id=str(app_id), country_code=c
                    )
            else:
                deleted_db += await db_manager.delete_item(
                    service="app_store", item_id=str(app_id)
                )
        except Exception as e:
            await send_error(context, update.effective_chat.id, f"❌ 清理 MySQL 失败: {e!s}")
            return

    # 成功反馈
    scope_text = (
        ", ".join([c.upper() for c in countries]) if countries else "所有国家"
    )
    result_text = (
        f"✅ 已清理 App Store 缓存\n"
        f"• App ID: {app_id}\n"
        f"• 范围: {scope_text}\n"
        f"• MySQL 删除记录: {deleted_db}"
    )
    await send_success(
        context,
        update.effective_chat.id,
        foldable_text_v2(result_text),
        parse_mode="MarkdownV2",
    )


command_factory.register_command(
    "app_clearitem",
    app_store_clear_item_command,
    permission=Permission.ADMIN,
    description="清理指定 App ID 的缓存（Redis+MySQL）",
)
command_factory.register_callback(
    "^app_",
    handle_app_search_callback,
    permission=Permission.USER,
    description="App搜索回调处理",
)
# =============================================================================
# Inline 执行入口
# =============================================================================

async def appstore_inline_execute(args: str) -> dict:
    """
    Inline Query 执行入口 - 通过 App ID 查询 App Store 价格

    Args:
        args: App ID + 可选国家代码，格式为 "id363590051 US CN JP" 或 "363590051"

    Returns:
        dict: {
            "success": bool,
            "title": str,
            "message": str,
            "description": str,
            "error": str | None
        }
    """
    if not args or not args.strip():
        return {
            "success": False,
            "title": "❌ 请输入 App ID",
            "message": "请提供 App ID\\n\\n*使用方法:*\\n• `appstore id363590051` \\\\- 默认地区\\n• `appstore id363590051 US CN JP` \\\\- 指定地区\\n• `appstore 363590051` \\\\- 也可省略 id 前缀\\n\\n💡 App ID 可在 App Store 链接中找到",
            "description": "请提供 App ID，如 id363590051",
            "error": "未提供 App ID"
        }

    # 解析参数
    parts = args.strip().split()
    app_id_param = parts[0]

    # 支持 "id363590051" 或 "363590051" 格式
    if app_id_param.lower().startswith("id"):
        app_id = app_id_param[2:]
    else:
        app_id = app_id_param

    if not app_id.isdigit():
        return {
            "success": False,
            "title": "❌ 无效的 App ID",
            "message": f"无效的 App ID: `{app_id_param}`\\n\\nApp ID 必须是数字，如 `id363590051`",
            "description": "App ID 格式错误",
            "error": "App ID 必须是数字"
        }

    try:
        # 解析国家参数
        if len(parts) > 1:
            countries_parsed = parse_countries(parts[1:])
            countries_to_check = countries_parsed if countries_parsed else DEFAULT_COUNTRIES
        else:
            countries_to_check = DEFAULT_COUNTRIES

        platform = "ios"  # 默认 iOS 平台

        # 获取多国价格信息
        price_results_raw = await get_multi_country_prices(
            app_name=f"App ID {app_id}",
            app_id=int(app_id),
            platform=platform,
            countries=countries_to_check,
        )

        # 过滤成功结果
        successful_results = [res for res in price_results_raw if res["status"] == "ok"]

        if not successful_results:
            return {
                "success": False,
                "title": f"❌ 未找到 App {app_id}",
                "message": f"在默认区域中未找到 App ID `{app_id}`\\n\\n请检查 ID 是否正确",
                "description": f"未找到 App ID {app_id}",
                "error": "App 不存在"
            }

        # 获取真实应用名称
        real_app_name = None
        for res in successful_results:
            if res.get("real_app_name"):
                real_app_name = res["real_app_name"]
                break

        app_name = real_app_name or f"App ID {app_id}"

        # 格式化结果
        target_plan = find_common_plan(price_results_raw)
        formatted_result = format_app_details(
            app_name=app_name,
            app_id=app_id,
            platform=platform,
            price_results=price_results_raw,
            target_plan=target_plan,
        )

        # 构建简短描述
        first_result = successful_results[0]
        first_price = first_result.get("app_price_str", "免费")
        short_desc = f"{app_name} | {first_price}"

        return {
            "success": True,
            "title": f"📱 {app_name}",
            "message": foldable_text_with_markdown_v2(formatted_result),
            "description": short_desc,
            "error": None
        }

    except Exception as e:
        logger.error(f"Inline App Store query failed: {e}")
        return {
            "success": False,
            "title": "❌ 查询失败",
            "message": f"查询 App Store 失败: {str(e)}",
            "description": "查询失败",
            "error": str(e)
        }


# =============================================================================
# Inline 搜索入口（返回多个结果）
# =============================================================================

async def handle_inline_appstore_search(
    keyword: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> list:
    """
    Inline 搜索 App Store 应用（参考 netease 的 handle_inline_music_search）
    返回多个搜索结果供用户选择

    Args:
        keyword: 搜索关键词，格式为 "应用名称" 或 "应用名称 -平台标志" 或 "应用名称 HK TW JP"
        context: Telegram context

    Returns:
        list: InlineQueryResult 列表
    """
    from telegram import InlineQueryResultArticle, InputTextMessageContent
    from uuid import uuid4

    if not keyword.strip():
        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="🔍 请输入搜索关键词",
                description="例如: appstore 微信$ 或 appstore 微信 hk tw jp$",
                input_message_content=InputTextMessageContent(
                    message_text="🔍 请输入应用名称搜索 App Store\n\n"
                    "支持格式:\n"
                    "• appstore 微信$\n"
                    "• appstore 微信 hk tw jp$\n"
                    "• appstore Photoshop -mac$"
                ),
            )
        ]

    try:
        # 解析平台参数
        platform, cleaned_keyword = extract_platform_flag(keyword)

        if not cleaned_keyword.strip():
            return [
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title="❌ 请输入应用名称",
                    description="搜索关键词不能为空",
                    input_message_content=InputTextMessageContent(
                        message_text="❌ 请输入应用名称"
                    ),
                )
            ]

        # 解析应用名称和国家参数
        try:
            all_params_list = parse_command_args(cleaned_keyword)
        except ValueError:
            all_params_list = cleaned_keyword.split()

        # 分离应用名称和国家代码
        app_name_parts = []
        countries_parsed = []
        for param in all_params_list:
            if is_valid_country(param):
                countries_parsed = parse_countries(all_params_list[all_params_list.index(param):])
                break
            app_name_parts.append(param)

        if not app_name_parts:
            return [
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title="❌ 请输入应用名称",
                    description="搜索关键词不能为空",
                    input_message_content=InputTextMessageContent(
                        message_text="❌ 请输入应用名称"
                    ),
                )
            ]

        app_name_to_search = " ".join(app_name_parts)

        # 确定要查询的国家列表
        countries_to_check = countries_parsed if countries_parsed else DEFAULT_COUNTRIES

        # 默认在美区搜索（搜索本身只在一个区域进行）
        country_code = "us"

        # 获取平台信息
        platform_info = PLATFORM_INFO.get(platform, {"icon": "📱", "name": "iOS"})

        # 执行搜索
        logger.info(f"Inline App Store 搜索: '{app_name_to_search}' in {country_code}, platform: {platform}, countries: {countries_to_check}")
        all_results = await load_or_fetch_search_results(
            app_name_to_search, country_code, platform
        )

        if not all_results:
            return [
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title="❌ 未找到结果",
                    description=f"关键词: {app_name_to_search} ({platform_info['name']})",
                    input_message_content=InputTextMessageContent(
                        message_text=f"❌ 未找到与 \"{app_name_to_search}\" 相关的 {platform_info['name']} 应用"
                    ),
                )
            ]

        # 构建搜索结果列表（最多10个）
        results = []
        for i, app in enumerate(all_results[:10]):
            app_name = app.get("trackName", "未知应用")
            app_id = app.get("trackId")
            artist_name = app.get("artistName", "")

            if not app_id:
                continue

            # 构建描述
            description_parts = []
            if artist_name:
                description_parts.append(artist_name)

            # 获取价格信息（如果有）
            price = app.get("formattedPrice", "")
            if price:
                description_parts.append(price)

            description = " | ".join(description_parts) if description_parts else "点击查看多国价格"

            # 获取多国价格信息（使用用户指定的国家列表或默认列表）
            try:
                price_results_raw = await get_multi_country_prices(
                    app_name=app_name,
                    app_id=int(app_id),
                    platform=platform,
                    countries=countries_to_check,
                )

                # 格式化价格信息
                target_plan = find_common_plan(price_results_raw)
                formatted_result = format_app_details(
                    app_name=app_name,
                    app_id=str(app_id),
                    platform=platform,
                    price_results=price_results_raw,
                    target_plan=target_plan,
                )

                # 使用 MarkdownV2 格式
                message_text = foldable_text_with_markdown_v2(formatted_result)
                parse_mode = "MarkdownV2"

            except Exception as e:
                logger.warning(f"获取应用 {app_id} 价格失败: {e}")
                message_text = f"📱 *{app_name}*\n\n❌ 获取价格信息失败\n\n💡 请使用 `/app id{app_id}` 重试"
                parse_mode = "Markdown"

            results.append(
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title=f"{platform_info['icon']} {app_name}",
                    description=description,
                    input_message_content=InputTextMessageContent(
                        message_text=message_text,
                        parse_mode=parse_mode,
                    ),
                )
            )

        return results

    except Exception as e:
        logger.error(f"Inline App Store 搜索失败: {e}", exc_info=True)
        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="❌ 搜索失败",
                description=str(e)[:100],
                input_message_content=InputTextMessageContent(
                    message_text=f"❌ 搜索失败: {str(e)}"
                ),
            )
        ]
