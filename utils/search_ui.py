"""
通用搜索UI组件

提供可复用的搜索结果格式化、分页键盘生成等功能。
供 Steam、App Store、Google Play 等服务使用。
"""

import logging
from dataclasses import dataclass

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from utils.country_data import SUPPORTED_COUNTRIES, get_country_flag

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """搜索结果数据类"""

    id: str
    name: str
    type: str = "item"
    extra_info: str = ""


@dataclass
class PaginationInfo:
    """分页信息数据类"""

    current_page: int = 1
    total_pages: int = 1
    total_results: int = 0
    page_size: int = 5


class SearchUIBuilder:
    """
    通用搜索UI构建器

    使用示例:
        builder = SearchUIBuilder(
            service_name="Steam",
            service_icon="🎮",
            callback_prefix="steam"
        )
        message = builder.format_search_header(...)
        keyboard = builder.create_search_keyboard(...)
    """

    # 默认类型图标映射
    DEFAULT_TYPE_ICONS = {
        "game": "🎮",
        "app": "📱",
        "bundle": "🛍",
        "dlc": "📦",
        "music": "🎵",
        "video": "🎬",
        "book": "📚",
        "subscription": "💳",
        "default": "📄",
    }

    def __init__(
        self,
        service_name: str,
        service_icon: str = "🔍",
        callback_prefix: str = "search",
        type_icons: dict[str, str] | None = None,
        page_size: int = 5,
        max_name_length: int = 37,
    ):
        """
        初始化搜索UI构建器

        Args:
            service_name: 服务名称 (如 "Steam", "App Store")
            service_icon: 服务图标
            callback_prefix: 回调数据前缀
            type_icons: 自定义类型图标映射
            page_size: 每页显示数量
            max_name_length: 名称最大长度
        """
        self.service_name = service_name
        self.service_icon = service_icon
        self.callback_prefix = callback_prefix
        self.type_icons = type_icons or self.DEFAULT_TYPE_ICONS
        self.page_size = page_size
        self.max_name_length = max_name_length

    def get_type_icon(self, item_type: str) -> str:
        """获取类型对应的图标"""
        return self.type_icons.get(item_type, self.type_icons.get("default", "📄"))

    def truncate_name(self, name: str, max_length: int | None = None) -> str:
        """截断过长的名称"""
        max_len = max_length or self.max_name_length
        if len(name) > max_len:
            return name[: max_len - 3] + "..."
        return name

    def format_search_header(
        self,
        query: str,
        country_code: str,
        pagination: PaginationInfo,
        custom_title: str | None = None,
    ) -> str:
        """
        格式化搜索结果头部信息

        Args:
            query: 搜索关键词
            country_code: 国家代码
            pagination: 分页信息
            custom_title: 自定义标题

        Returns:
            格式化后的消息文本
        """
        country_flag = get_country_flag(country_code)
        country_info = SUPPORTED_COUNTRIES.get(
            country_code.upper(), {"name": country_code}
        )
        country_name = country_info.get("name", country_code)

        title = custom_title or f"{self.service_icon} {self.service_name}搜索结果"

        header_parts = [
            title,
            f"🔍 关键词: {query}",
            f"🌍 搜索地区: {country_flag} {country_name} ({country_code.upper()})",
            f"📊 找到 {pagination.total_results} 个结果 "
            f"(第 {pagination.current_page}/{pagination.total_pages} 页)",
            "",
            "请从下方选择您要查询的内容：",
        ]

        return "\n".join(header_parts)

    def format_no_results(self, query: str, country_code: str) -> str:
        """格式化无结果消息"""
        return (
            f"🔍 在 {country_code.upper()} 区域没有找到" f"关键词 '{query}' 的相关内容"
        )

    def format_error(self, error_message: str) -> str:
        """格式化错误消息"""
        return f"❌ 搜索失败: {error_message}"

    def create_search_keyboard(
        self,
        results: list[dict],
        pagination: PaginationInfo,
        item_name_key: str = "name",
        item_type_key: str = "type",
        show_region_button: bool = True,
        show_close_button: bool = True,
        extra_buttons: list[list[InlineKeyboardButton]] | None = None,
    ) -> InlineKeyboardMarkup:
        """
        创建搜索结果键盘

        Args:
            results: 搜索结果列表
            pagination: 分页信息
            item_name_key: 结果中名称字段的键
            item_type_key: 结果中类型字段的键
            show_region_button: 是否显示更改地区按钮
            show_close_button: 是否显示关闭按钮
            extra_buttons: 额外的按钮行

        Returns:
            InlineKeyboardMarkup 对象
        """
        keyboard = []
        prefix = self.callback_prefix

        # 结果选择按钮
        for i, item in enumerate(results[: self.page_size]):
            name = item.get(item_name_key, "未知")
            item_type = item.get(item_type_key, "default")
            icon = self.get_type_icon(item_type)

            display_name = self.truncate_name(name)
            callback_data = f"{prefix}_select_{i}_{pagination.current_page}"

            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"{i + 1}. {icon} {display_name}",
                        callback_data=callback_data,
                    )
                ]
            )

        # 分页导航
        nav_row = self._create_navigation_row(pagination)
        if nav_row:
            keyboard.append(nav_row)

        # 操作按钮
        action_row = []
        if show_region_button:
            action_row.append(
                InlineKeyboardButton(
                    "🌍 更改搜索地区",
                    callback_data=f"{prefix}_change_region",
                )
            )
        if show_close_button:
            action_row.append(
                InlineKeyboardButton("❌ 关闭", callback_data=f"{prefix}_close")
            )
        if action_row:
            keyboard.append(action_row)

        # 额外按钮
        if extra_buttons:
            keyboard.extend(extra_buttons)

        return InlineKeyboardMarkup(keyboard)

    def _create_navigation_row(
        self, pagination: PaginationInfo
    ) -> list[InlineKeyboardButton]:
        """创建分页导航行"""
        nav_row = []
        prefix = self.callback_prefix
        current = pagination.current_page
        total = pagination.total_pages

        if current > 1:
            nav_row.append(
                InlineKeyboardButton(
                    "⬅️ 上一页", callback_data=f"{prefix}_page_{current - 1}"
                )
            )

        nav_row.append(
            InlineKeyboardButton(
                f"📄 {current}/{total}", callback_data=f"{prefix}_page_info"
            )
        )

        if current < total:
            nav_row.append(
                InlineKeyboardButton(
                    "下一页 ➡️", callback_data=f"{prefix}_page_{current + 1}"
                )
            )

        return nav_row

    def create_region_keyboard(
        self,
        regions: list[str],
        current_region: str | None = None,
        columns: int = 3,
    ) -> InlineKeyboardMarkup:
        """
        创建地区选择键盘

        Args:
            regions: 地区代码列表
            current_region: 当前选中的地区
            columns: 每行显示的列数

        Returns:
            InlineKeyboardMarkup 对象
        """
        keyboard = []
        prefix = self.callback_prefix
        row = []

        for region in regions:
            flag = get_country_flag(region)
            is_current = region.upper() == (current_region or "").upper()
            label = f"{'✓ ' if is_current else ''}{flag} {region.upper()}"

            row.append(
                InlineKeyboardButton(
                    label, callback_data=f"{prefix}_region_{region.lower()}"
                )
            )

            if len(row) >= columns:
                keyboard.append(row)
                row = []

        if row:
            keyboard.append(row)

        # 返回按钮
        keyboard.append(
            [InlineKeyboardButton("🔙 返回", callback_data=f"{prefix}_back")]
        )

        return InlineKeyboardMarkup(keyboard)


class CallbackParser:
    """
    回调数据解析器

    使用示例:
        parser = CallbackParser("steam")
        result = parser.parse("steam_select_0_1")
        # result = {"action": "select", "params": ["0", "1"]}
    """

    def __init__(self, prefix: str):
        self.prefix = prefix

    def parse(self, callback_data: str) -> dict | None:
        """
        解析回调数据

        Args:
            callback_data: 回调数据字符串

        Returns:
            解析结果字典，包含 action 和 params
        """
        if not callback_data.startswith(f"{self.prefix}_"):
            return None

        parts = callback_data[len(self.prefix) + 1 :].split("_")
        if not parts:
            return None

        return {"action": parts[0], "params": parts[1:] if len(parts) > 1 else []}

    def is_action(self, callback_data: str, action: str) -> bool:
        """检查是否为指定动作"""
        result = self.parse(callback_data)
        return result is not None and result["action"] == action

    def get_page(self, callback_data: str) -> int | None:
        """从分页回调中获取页码"""
        result = self.parse(callback_data)
        if result and result["action"] == "page" and result["params"]:
            try:
                return int(result["params"][0])
            except ValueError:
                return None
        return None

    def get_selection(self, callback_data: str) -> tuple[int, int] | None:
        """从选择回调中获取索引和页码"""
        result = self.parse(callback_data)
        if result and result["action"] == "select" and len(result["params"]) >= 2:
            try:
                return int(result["params"][0]), int(result["params"][1])
            except ValueError:
                return None
        return None
