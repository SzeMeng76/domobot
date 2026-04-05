# Description: Steam 模块的 UI 组件和搜索结果格式化
# 从原 steam.py 拆分

from telegram import InlineKeyboardMarkup

from utils.search_ui import PaginationInfo, SearchUIBuilder

# Steam 搜索 UI 构建器
steam_search_ui = SearchUIBuilder(
    service_name="Steam",
    service_icon="🎮",
    callback_prefix="steam",
    type_icons={
        "game": "🎮",
        "bundle": "🛍",
        "dlc": "📦",
        "default": "🎮",
    },
    page_size=5,
    max_name_length=37,
)


def format_steam_search_results(search_data: dict) -> str:
    """使用 SearchUIBuilder 格式化 Steam 搜索结果"""
    if search_data.get("error"):
        return steam_search_ui.format_error(search_data["error"])

    results = search_data.get("results", [])
    query = search_data["query"]
    country_inputs = search_data.get("country_inputs", ["CN"])
    current_country = country_inputs[0] if country_inputs else "CN"

    if not results:
        return steam_search_ui.format_no_results(query, current_country)

    # 创建分页信息
    pagination = PaginationInfo(
        current_page=search_data.get("current_page", 1),
        total_pages=search_data.get("total_pages", 1),
        total_results=search_data.get("total_results", len(results)),
        page_size=5,
    )

    return steam_search_ui.format_search_header(query, current_country, pagination)


def create_steam_search_keyboard(search_data: dict) -> InlineKeyboardMarkup:
    """使用 SearchUIBuilder 创建 Steam 搜索键盘"""
    results = search_data.get("results", [])
    pagination = PaginationInfo(
        current_page=search_data.get("current_page", 1),
        total_pages=search_data.get("total_pages", 1),
        total_results=search_data.get("total_results", len(results)),
        page_size=5,
    )

    return steam_search_ui.create_search_keyboard(
        results,
        pagination,
        item_name_key="name",
        item_type_key="type",
    )
