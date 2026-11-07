"""
Telegram 按钮 UI 原语

集中管理按钮颜色、分页导航、返回/关闭行，避免各模块各自手搓
``InlineKeyboardButton`` 导致样式不一致。

颜色来自 Bot API 10.0 的 ``style`` 参数（PTB 22.7+）::

    btn("确认", "ok", style=SUCCESS)   # 绿色
    btn("返回", "back", style=PRIMARY) # 蓝色
    btn("删除", "del", style=DANGER)   # 红色

取值只有 primary / success / danger（blue / green / red 为别名）。
未指定时由客户端主题决定；旧版客户端会忽略颜色、只显示文字，
因此属于安全的渐进增强，不需要做版本判断。
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Iterable, Sequence
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)

PRIMARY = "primary"
SUCCESS = "success"
DANGER = "danger"

# 未命中任何语义规则时使用的默认色，让所有可点击按钮都有统一观感。
# 可通过环境变量 UI_BUTTON_FALLBACK_STYLE 调整：
#   primary/success/danger -> 指定颜色
#   none/off/0             -> 未识别就不上色（旧行为）
FALLBACK_STYLE: str | None = PRIMARY


def _resolve_fallback_style() -> str | None:
    """读取 UI_BUTTON_FALLBACK_STYLE，未设置时用模块默认值。"""
    raw = os.getenv("UI_BUTTON_FALLBACK_STYLE")
    if raw is None:
        return FALLBACK_STYLE
    value = raw.strip().lower()
    if value in ("none", "off", "0", "false", "no", ""):
        return None
    if value in (PRIMARY, SUCCESS, DANGER):
        return value
    if value in ("blue", "green", "red"):
        return {"blue": PRIMARY, "green": SUCCESS, "red": DANGER}[value]
    logger.warning("未知的 UI_BUTTON_FALLBACK_STYLE=%r，按默认处理", raw)
    return FALLBACK_STYLE

# 颜色别名，读代码时更直观
BLUE = PRIMARY
GREEN = SUCCESS
RED = DANGER

# 通用文案
PREV_TEXT = "⬅️ 上一页"
NEXT_TEXT = "下一页 ➡️"
BACK_TEXT = "🔙 返回"
CLOSE_TEXT = "❌ 关闭"


def btn(
    text: str,
    data: str | None = None,
    *,
    url: str | None = None,
    style: str | None = None,
    icon: str | None = None,
) -> InlineKeyboardButton:
    """
    创建按钮。

    Args:
        text: 按钮文字
        data: callback_data（与 url 二选一）
        url: 跳转链接（与 data 二选一）
        style: 颜色，PRIMARY / SUCCESS / DANGER 之一
        icon: 按钮前自定义 emoji 的 ID。仅在 bot 购买了 Fragment 用户名、
            或 bot 所有者的账号有 Telegram Premium 时可用，否则 API 会报错。

    Returns:
        InlineKeyboardButton
    """
    if data is not None and url is not None:
        raise ValueError("按钮不能同时指定 callback_data 和 url")
    if data is None and url is None:
        raise ValueError("按钮必须指定 callback_data 或 url 之一")

    if data is not None:
        return InlineKeyboardButton(
            text, callback_data=data, style=style, icon_custom_emoji_id=icon
        )
    return InlineKeyboardButton(
        text, url=url, style=style, icon_custom_emoji_id=icon
    )


def page_nav_row(
    prefix: str,
    current: int,
    total: int,
    *,
    prev_text: str = PREV_TEXT,
    next_text: str = NEXT_TEXT,
    info_text: str | None = None,
) -> list[InlineKeyboardButton]:
    """
    创建分页导航行（上一页 / 页码 / 下一页）。

    页码按钮只是展示用，不着色，避免和真正的操作按钮抢视觉焦点。

    Args:
        prefix: 回调前缀，生成 ``{prefix}_page_{n}`` / ``{prefix}_page_info``
        current: 当前页（1-based）
        total: 总页数

    Returns:
        一行按钮；页码按钮始终存在
    """
    row: list[InlineKeyboardButton] = []

    if current > 1:
        row.append(btn(prev_text, f"{prefix}_page_{current - 1}", style=PRIMARY))

    row.append(btn(info_text or f"📄 {current}/{total}", f"{prefix}_page_info"))

    if current < total:
        row.append(btn(next_text, f"{prefix}_page_{current + 1}", style=PRIMARY))

    return row


def back_row(data: str, text: str = BACK_TEXT) -> list[InlineKeyboardButton]:
    """创建返回按钮行（蓝色）。"""
    return [btn(text, data, style=PRIMARY)]


def close_row(data: str, text: str = CLOSE_TEXT) -> list[InlineKeyboardButton]:
    """创建关闭按钮行（红色）。"""
    return [btn(text, data, style=DANGER)]


def chunk(
    items: Sequence[InlineKeyboardButton], columns: int
) -> list[list[InlineKeyboardButton]]:
    """
    把按钮切成每行 ``columns`` 个。

    Args:
        items: 按钮序列
        columns: 每行列数（至少 1）

    Returns:
        二维按钮列表，可直接喂给 InlineKeyboardMarkup
    """
    if columns < 1:
        raise ValueError("columns 必须 >= 1")
    return [list(items[i : i + columns]) for i in range(0, len(items), columns)]


def rows(*items: Iterable[InlineKeyboardButton]) -> list[list[InlineKeyboardButton]]:
    """把若干按钮行拼成键盘布局，过滤掉空行。"""
    return [list(row) for row in items if row]


# ---------------------------------------------------------------------------
# 全局样式注入
# ---------------------------------------------------------------------------

# 按文案关键字推断按钮语义。顺序有意义：先匹配更具体的规则。
# 目标是让绝大多数按钮都有颜色，同时避免整屏一色。
_DANGER_WORDS = (
    "关闭", "删除", "取消", "清除", "清理", "清空", "退出", "移除", "重置",
    "禁用", "解绑", "撤销", "停止", "拒绝", "标记满员", "销毁", "注销",
)
_SUCCESS_WORDS = (
    "确认", "确定", "已选", "启用", "解禁", "加入", "上车", "订阅",
    "保存", "提交", "生成", "开始", "开启", "✅", "✓",
)
_PRIMARY_WORDS = (
    "返回", "🔙", "上一页", "下一页", "上页", "下页", "⬅️", "➡️", "◀️", "▶️",
    "刷新", "🔄", "重新", "重试", "切换", "加载更多", "查看", "详情",
    "更多", "显示", "展开", "获取", "下载", "打开",
)
# 纯展示类、不该染色的（页码、统计、标题栏）
_NEUTRAL_PATTERNS = (
    "📄", "ℹ️", "📊", "━━", "第 ", "页", "/",
)


def infer_style(text: str) -> str | None:
    """
    按按钮文案推断语义颜色。

    规则按优先级匹配：危险操作 > 确认类 > 导航类 > 默认。

    Args:
        text: 按钮文字

    Returns:
        PRIMARY / SUCCESS / DANGER，无法判断时返回 None（跟随客户端主题）
    """
    if not text:
        return None

    t = text.strip()

    # 页码、进度、纯统计这类不染色
    if t in ("📄", "ℹ️", "❌", "📊"):
        return None
    if re.fullmatch(r"[📄ℹ️]?\s*\d+\s*/\s*\d+", t):
        return None

    if t.startswith("❌") or any(w in t for w in _DANGER_WORDS):
        return DANGER
    if any(w in t for w in _SUCCESS_WORDS):
        return SUCCESS
    if any(w in t for w in _PRIMARY_WORDS):
        return PRIMARY
    return None


# 带国旗/图标的地区选择按钮优先用 PRIMARY，避免满屏彩色
def infer_style_with_context(
    text: str, callback_data: str | None = None
) -> str | None:
    """
    结合 callback_data 推断颜色，比纯文案更准。

    项目里的 callback_data 有稳定后缀规律（``news_close``、``news_back``），
    用它判断可以覆盖文案里看不出来的语义。

    最后回退到 :data:`FALLBACK_STYLE`，使所有可点击按钮都有颜色；
    页码、分隔标题等纯展示行保持中性（见 :func:`is_neutral_button`）。

    Args:
        text: 按钮文字
        callback_data: 按钮的回调数据

    Returns:
        PRIMARY / SUCCESS / DANGER，纯展示行返回 None
    """
    if is_neutral_button(text, callback_data):
        return None

    if callback_data:
        data = str(callback_data).lower()
        # 末尾是动作名（可能带序号），取最后一个字母片段
        action = re.sub(r"[\d_]+$", "", data).rsplit("_", 1)[-1]
        if action in ("close", "cancel", "delete", "remove", "del", "clear"):
            return DANGER
        if action in ("back", "main", "menu", "prev", "next", "page", "refresh"):
            return PRIMARY
        if action in ("ok", "confirm", "select", "add", "enable", "submit"):
            return SUCCESS

    explicit = infer_style(text)
    if explicit:
        return explicit

    return _resolve_fallback_style()


def is_neutral_button(text: str, callback_data: str | None = None) -> bool:
    """
    判断按钮是否属于"纯展示行"，不应上色。

    包括页码（``📄 1/5``）、统计数字、以及只作标题分隔的分组行
    （``📂 科技类``），给它们上色会造成整屏同色的观感噪音。

    Args:
        text: 按钮文字
        callback_data: 按钮的回调数据

    Returns:
        True 表示保持中性（不上色）
    """
    t = (text or "").strip()
    if not t:
        return True

    # 页码 / 进度
    if re.fullmatch(r"[📄ℹ️]?\s*\d+\s*/\s*\d+", t):
        return True

    # 回调里能看出是信息行
    if callback_data:
        data = str(callback_data).lower()
        action = re.sub(r"[\d_]+$", "", data).rsplit("_", 1)[-1]
        if action in ("page_info", "info", "noop", "none"):
            return True

    # 不带具体动作的分组标题（只有分类名 + 图标）
    if t.startswith("📂"):
        return True

    return False


# InlineKeyboardButton 的全部字段（PTB 对象不可变，改样式必须重建）。
# 漏掉任何一个都会导致按钮行为丢失，所以这里显式列全。
_BUTTON_FIELDS = (
    "text",
    "url",
    "callback_data",
    "switch_inline_query",
    "switch_inline_query_current_chat",
    "callback_game",
    "pay",
    "login_url",
    "web_app",
    "switch_inline_query_chosen_chat",
    "copy_text",
    "style",
    "icon_custom_emoji_id",
)


def _clone_button_with_style(
    button: InlineKeyboardButton, style: str
) -> InlineKeyboardButton:
    """复制按钮并改成指定样式，其余字段原样保留。"""
    params = {
        name: getattr(button, name)
        for name in _BUTTON_FIELDS
        if getattr(button, name, None) is not None
    }
    params["style"] = style
    return InlineKeyboardButton(**params)


def style_markup(markup: Any) -> Any:
    """
    给 ``InlineKeyboardMarkup`` 里未指定颜色的按钮补上推断出的颜色。

    PTB 的 ``InlineKeyboardButton`` 是只读对象，因此这里重建键盘与按钮，
    并保留所有原有字段（url / web_app / copy_text / pay 等）。已有显式
    ``style`` 的按钮原样保留。非 ``InlineKeyboardMarkup`` 的 reply_markup
    直接透传。

    Args:
        markup: 任意 reply_markup 对象

    Returns:
        新的 ``InlineKeyboardMarkup``（若无变化则返回原对象）
    """
    if not isinstance(markup, InlineKeyboardMarkup):
        return markup

    changed = False
    new_keyboard: list[list[InlineKeyboardButton]] = []

    for row in markup.inline_keyboard:
        new_row: list[InlineKeyboardButton] = []
        for button in row:
            if getattr(button, "style", None):
                new_row.append(button)
                continue

            style = infer_style_with_context(
                button.text or "", getattr(button, "callback_data", None)
            )
            if style:
                new_row.append(_clone_button_with_style(button, style))
                changed = True
            else:
                new_row.append(button)
        new_keyboard.append(new_row)

    if not changed:
        return markup

    kwargs: dict[str, Any] = {"inline_keyboard": new_keyboard}
    if getattr(markup, "is_persistent", None) is not None:
        kwargs["is_persistent"] = markup.is_persistent
    if getattr(markup, "resize_keyboard", None) is not None:
        kwargs["resize_keyboard"] = markup.resize_keyboard
    if getattr(markup, "one_time_keyboard", None) is not None:
        kwargs["one_time_keyboard"] = markup.one_time_keyboard
    if getattr(markup, "input_field_placeholder", None) is not None:
        kwargs["input_field_placeholder"] = markup.input_field_placeholder
    if getattr(markup, "selective", None) is not None:
        kwargs["selective"] = markup.selective

    return InlineKeyboardMarkup(**kwargs)


def make_styled_bot_class() -> type:
    """
    构造一个 ``ExtBot`` 子类，在发送前统一处理两件事：

    1. 给未指定颜色的按钮补语义颜色（见 :func:`style_markup`）；
    2. 把以 ``MarkdownV2`` 发送的文本自动转成 ``HTML``，从而获得
       原生 ``<blockquote expandable>`` 折叠等富文本能力。

    所有发送/编辑方法最终都走 ``Bot._send_message``，在这一个方法上覆盖
    即可覆盖全项目，无需改动调用点。

    自动转换由环境变量 ``RICH_TEXT_AUTO_HTML`` 控制（默认开启），设为
    ``0``/``false`` 即可退回原生的 MarkdownV2 发送。

    Returns:
        ExtBot 的子类，供 ``ApplicationBuilder.bot()`` 使用
    """
    import os

    from telegram.ext import ExtBot

    from utils.formatter import md1_to_html, mdv2_to_html

    auto_html = os.getenv("RICH_TEXT_AUTO_HTML", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )

    class StyledBot(ExtBot):  # type: ignore[misc]
        async def _send_message(self, endpoint: str, data: dict, **kwargs: Any) -> Any:
            kwargs["reply_markup"] = style_markup(kwargs.get("reply_markup"))

            parse_mode = kwargs.get("parse_mode")
            converter = _pick_converter(auto_html, parse_mode)

            # entities 与 parse_mode 互斥，带 entities 的请求保持原样
            if converter is not None and not kwargs.get("caption_entities"):
                for key in ("text", "caption"):
                    value = kwargs.get(key, data.get(key))
                    if not (isinstance(value, str) and value):
                        continue
                    try:
                        converted = converter(value)
                    except Exception as e:  # pragma: no cover - 兜底
                        logger.warning("富文本转换失败，保持原文: %s", e)
                        continue
                    if key in kwargs:
                        kwargs[key] = converted
                    else:
                        data[key] = converted
                kwargs["parse_mode"] = "HTML"
                data.pop("parse_mode", None)

            return await super()._send_message(endpoint, data, **kwargs)

    return StyledBot


def _is_markdown_v2(parse_mode: Any) -> bool:
    """判断 parse_mode 是否为 MarkdownV2（含字符串与枚举写法）。"""
    if parse_mode is None:
        return False
    value = str(getattr(parse_mode, "value", parse_mode)).strip().upper()
    return value in ("MARKDOWNV2", "MARKDOWN_V2")


def _is_markdown_v1(parse_mode: Any) -> bool:
    """判断 parse_mode 是否为 Markdown v1（注意不能匹配到 MarkdownV2）。"""
    if parse_mode is None:
        return False
    value = str(getattr(parse_mode, "value", parse_mode)).strip().upper()
    # "MARKDOWNV2" 也以 "MARKDOWN" 开头，必须先排除
    return value in ("MARKDOWN", "MARKDOWN_V1")


def _pick_converter(auto_html: bool, parse_mode: Any) -> Any:
    """
    根据 parse_mode 选择转换函数，不需要转换时返回 None。

    MarkdownV2 与 v1 的语法不同（v1 不解析 ``~`` 和 ``|``），必须分别处理。
    HTML 或无 parse_mode 的请求保持原样。
    """
    if not auto_html:
        return None

    from utils.formatter import md1_to_html, mdv2_to_html

    if _is_markdown_v2(parse_mode):
        return mdv2_to_html
    if _is_markdown_v1(parse_mode):
        return md1_to_html
    return None


def build_styled_bot(
    token: str,
    *,
    read_timeout: float | None = None,
    write_timeout: float | None = None,
    media_write_timeout: float | None = None,
    connect_timeout: float | None = None,
    pool_timeout: float | None = None,
) -> Any:
    """
    构造带样式注入的 bot 实例。

    ``ApplicationBuilder`` 的 ``token`` 与 ``bot`` 参数互斥，超时参数也只能
    在没有传入 bot 实例时设置，因此这里手工组装 ``HTTPXRequest``，行为与
    ``ApplicationBuilder`` 内部一致。

    Args:
        token: bot token
        read_timeout: 读取超时（秒）
        write_timeout: 写入超时（秒）
        media_write_timeout: 媒体上传写入超时（秒）
        connect_timeout: 连接超时（秒）
        pool_timeout: 连接池超时（秒）

    Returns:
        ``StyledBot`` 实例，可直接传给 ``ApplicationBuilder.bot()``
    """
    from telegram.request import HTTPXRequest

    timeouts = {
        "connect_timeout": connect_timeout,
        "read_timeout": read_timeout,
        "write_timeout": write_timeout,
        "pool_timeout": pool_timeout,
        "media_write_timeout": media_write_timeout,
    }
    effective = {k: v for k, v in timeouts.items() if v is not None}

    return make_styled_bot_class()(token, request=HTTPXRequest(**effective))


