"""
文本格式化工具。

本模块同时提供两套互不干扰的格式化出口：

* ``MarkdownV2`` 系（``escape_v2`` / ``format_with_markdown_v2`` /
  ``foldable_text_v2`` / ``foldable_text_with_markdown_v2``）
  历史实现，仍被大量调用点使用，行为保持不变。

* ``HTML`` 系（``escape_html`` / ``md_to_html`` / ``foldable_text_html`` /
  ``foldable_text_with_markdown_html``）
  新实现，用 ``<blockquote expandable>`` 做原生折叠，取代早期用
  ``**> `` 前缀 + 结尾 ``||`` 拼出来的 MarkdownV2 伪折叠。

两套函数都只是"生成字符串"，不绑定发送方式；调用点自行决定
``parse_mode``。要把某个模块迁到 HTML 系，只需把函数名和
``parse_mode="MarkdownV2"`` 一起改掉，不要只改其中一个。
"""

import html as _html
import logging
import re
from datetime import UTC, datetime

from telegram.helpers import escape_markdown

from .config_manager import get_config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MarkdownV2 系（历史实现，保留不动）
# ---------------------------------------------------------------------------


def escape_v2(text: str) -> str:
    """Escapes text for Telegram MarkdownV2."""
    if not text:
        return ""
    return escape_markdown(text, version=2)


def format_with_markdown_v2(text: str) -> str:
    """
    智能处理带有MarkdownV2格式的文本，保持格式化效果的同时进行转义。

    最终版本：完全避免递归，使用更简单的一次性处理方法。

    Args:
        text (str): 包含MarkdownV2格式标记的文本

    Returns:
        str: 正确转义的MarkdownV2格式文本
    """
    if not text:
        return ""

    try:
        result_text = text

        # 第一步：保护代码块（它们的内容不应该被转义）
        code_blocks = []
        code_pattern = r"`([^`]+)`"
        matches = list(re.finditer(code_pattern, result_text))

        for i, match in enumerate(reversed(matches)):
            placeholder = f"__CODE_BLOCK_{i}__"
            code_blocks.append((placeholder, match.group(0)))  # 保存整个代码块
            result_text = result_text[: match.start()] + placeholder + result_text[match.end() :]

        # 第二步：保护链接格式
        link_blocks = []
        link_pattern = r"\[([^\]]+)\]\(([^)]+)\)"
        matches = list(re.finditer(link_pattern, result_text))

        for i, match in enumerate(reversed(matches)):
            placeholder = f"__LINK_BLOCK_{i}__"
            link_text = escape_v2(match.group(1))
            link_url = escape_v2(match.group(2))
            link_blocks.append((placeholder, f"[{link_text}]({link_url})"))
            result_text = result_text[: match.start()] + placeholder + result_text[match.end() :]

        # 第三步：处理其他格式标记（粗体、斜体、删除线、spoiler）
        formats = [
            (r"\*([^*]+)\*", lambda m: f"*{escape_v2(m.group(1))}*"),
            (r"(?<!\w)_([^_\s][^_]*[^_\s]|[^_\s])_(?!\w)", lambda m: f"_{escape_v2(m.group(1))}_"),
            (r"~([^~]+)~", lambda m: f"~{escape_v2(m.group(1))}~"),
            (r"\|\|([^|]+)\|\|", lambda m: f"||{escape_v2(m.group(1))}||"),
        ]

        format_blocks = []
        for i, (pattern, formatter) in enumerate(formats):
            matches = list(re.finditer(pattern, result_text))
            for j, match in enumerate(reversed(matches)):
                placeholder = f"__FORMAT_{i}_{j}__"
                formatted_content = formatter(match)
                format_blocks.append((placeholder, formatted_content))
                result_text = result_text[: match.start()] + placeholder + result_text[match.end() :]

        # 第四步：转义剩余的普通文本
        escaped_result = escape_v2(result_text)

        # 第五步：恢复所有保护的内容
        # 注意：要用转义后的占位符来替换，并且要先恢复内层的内容

        # 首先恢复代码块和链接（它们可能在格式块内容中）
        for placeholder, content in code_blocks:
            escaped_placeholder = escape_v2(placeholder)
            # 在主文本中替换
            escaped_result = escaped_result.replace(escaped_placeholder, content)
            # 在格式块内容中也替换
            for i, (fmt_placeholder, fmt_content) in enumerate(format_blocks):
                if escaped_placeholder in fmt_content:
                    format_blocks[i] = (fmt_placeholder, fmt_content.replace(escaped_placeholder, content))

        for placeholder, content in link_blocks:
            escaped_placeholder = escape_v2(placeholder)
            # 在主文本中替换
            escaped_result = escaped_result.replace(escaped_placeholder, content)
            # 在格式块内容中也替换
            for i, (fmt_placeholder, fmt_content) in enumerate(format_blocks):
                if escaped_placeholder in fmt_content:
                    format_blocks[i] = (fmt_placeholder, fmt_content.replace(escaped_placeholder, content))

        # 最后恢复格式块
        for placeholder, content in format_blocks:
            escaped_placeholder = escape_v2(placeholder)
            escaped_result = escaped_result.replace(escaped_placeholder, content)

        return escaped_result

    except Exception as e:
        logger.error(f"Error during markdown formatting: {e}", exc_info=True)
        return escape_v2(text)  # 降级到安全转义


def foldable_text_v2(body: str) -> str:
    """
    Formats text for MarkdownV2, applying folding if it exceeds the configured line threshold.

    这是 foldable_text_with_markdown_v2 的简化版本，用于纯文本内容。

    Args:
        body (str): The text to format (plain text, no markdown).

    Returns:
        str: A MarkdownV2 formatted string, potentially folded.
    """
    try:
        config = get_config()
        folding_threshold = config.folding_threshold

        body_lines = body.split("\n")

        if len(body_lines) > folding_threshold:
            if not body_lines:
                return ""

            escaped_lines = [escape_v2(line) for line in body_lines]

            first_line = f"**> {escaped_lines[0]}"
            following_lines = [f"> {line}" for line in escaped_lines[1:]]
            all_lines = [first_line, *following_lines]

            if all_lines:
                all_lines[-1] += "||"

            return "\n".join(all_lines)
        else:
            return escape_v2(body)

    except Exception as e:
        logger.error(f"Error during foldable text formatting: {e}", exc_info=True)
        return escape_v2(body)  # Fallback to safe escaped text


def foldable_text_with_markdown_v2(body: str) -> str:
    """
    格式化包含MarkdownV2格式的文本，支持基于行数的折叠功能。

    Args:
        body (str): 包含MarkdownV2格式标记的文本

    Returns:
        str: 正确格式化和可能折叠的MarkdownV2文本
    """
    try:
        config = get_config()
        folding_threshold = config.folding_threshold

        body_lines = body.split("\n")

        if len(body_lines) > folding_threshold:
            if not body_lines:
                return ""

            # 对每行进行智能格式化
            formatted_lines = [format_with_markdown_v2(line) for line in body_lines]

            first_line = f"**> {formatted_lines[0]}"
            following_lines = [f"> {line}" for line in formatted_lines[1:]]
            all_lines = [first_line, *following_lines]

            if all_lines:
                # 检查最后一行是否以spoiler结尾，避免冲突
                last_line = all_lines[-1]
                if last_line.endswith("||"):
                    # 如果最后一行已经以 || 结尾（spoiler格式），添加空格分隔
                    all_lines[-1] += " ||"
                else:
                    # 正常情况，直接添加折叠结束标记
                    all_lines[-1] += "||"

            return "\n".join(all_lines)
        else:
            return format_with_markdown_v2(body)

    except Exception as e:
        logger.error(f"Error during foldable markdown formatting: {e}", exc_info=True)
        return escape_v2(body)  # 降级到安全转义


# ---------------------------------------------------------------------------
# HTML 系（新实现）
# ---------------------------------------------------------------------------


def escape_html(text: str, quote: bool = False) -> str:
    """转义 HTML 特殊字符，供 ParseMode.HTML 使用。"""
    if not text:
        return ""
    return _html.escape(text, quote=quote)


# ---------------------------------------------------------------------------
# 富文本标签
# ---------------------------------------------------------------------------

# Telegram 支持的 date-time 格式串（见 Bot API date-time entity formatting）
VALID_TIME_FORMATS = frozenset(
    {
        "r", "w", "d", "D", "t", "T",
        "wd", "wD", "wt", "wT",
        "wdt", "wdT", "wDt", "wDT",
        "dt", "dT", "Dt", "DT",
    }
)


def tg_time(
    value: datetime | float,
    fmt: str = "wDT",
    fallback: str | None = None,
) -> str:
    """
    生成客户端按用户本地时区渲染的时间戳。

    支持 ``<tg-time>`` 的客户端会按用户所在时区显示；不支持的客户端
    显示 ``fallback``（默认是 UTC 时间字符串）。

    Args:
        value: ``datetime`` 或 Unix 时间戳（秒）
        fmt: 格式串，取值见 :data:`VALID_TIME_FORMATS`，默认 ``"wDT"``
            （星期 + 长日期 + 长时间）
        fallback: 降级显示文本

    Returns:
        HTML 片段

    Raises:
        ValueError: fmt 不在允许范围内

    Examples:
        >>> tg_time(1735689600, "wDT")
        '<tg-time unix="1735689600" format="wDT">2024-12-31 00:00 UTC</tg-time>'
    """
    if fmt not in VALID_TIME_FORMATS:
        raise ValueError(
            f"不支持的 tg-time 格式 {fmt!r}，可选：{sorted(VALID_TIME_FORMATS)}"
        )

    if isinstance(value, datetime):
        # naive datetime 按本地时区解释
        ts = int(value.timestamp())
    elif isinstance(value, (int, float)):
        ts = int(value)
    else:
        raise TypeError(f"tg_time 需要 datetime 或数字时间戳，收到 {type(value)!r}")

    if fallback is None:

        fallback = datetime.fromtimestamp(ts, tz=UTC).strftime(
            "%Y-%m-%d %H:%M UTC"
        )

    return (
        f'<tg-time unix="{ts}" format="{escape_html(fmt, quote=True)}">'
        f"{escape_html(fallback)}</tg-time>"
    )


def tg_emoji(emoji_id: str, fallback: str = "⭐") -> str:
    """
    生成自定义 emoji 标签。

    注意：仅当 bot 购买了 Fragment 用户名，或 bot 所有者账号有 Telegram
    Premium 时客户端才会实际渲染为自定义 emoji，否则显示 ``fallback``。
    发消息时若权限不足，Telegram 服务端可能直接返回错误，上线前先用
    真实 bot 发一条验证。

    Args:
        emoji_id: 自定义 emoji 的唯一 ID
        fallback: 降级显示的标准 emoji

    Returns:
        HTML 片段
    """
    if not emoji_id:
        return escape_html(fallback)
    return (
        f'<tg-emoji emoji-id="{escape_html(str(emoji_id), quote=True)}">'
        f"{escape_html(fallback)}</tg-emoji>"
    )


# 输入里已存在的 tg-time / tg-emoji 标签：解析后按白名单属性重建，
# 避免它们被当成普通文本转义掉，同时不允许夹带任意属性。
_ATTR_RE = re.compile(r'([\w-]+)\s*=\s*"([^"]*)"')
_TG_TAG_RE = re.compile(r"<tg-(time|emoji)\b([^>]*)>(.*?)</tg-\1>", re.DOTALL)
_TG_TIME_ATTRS = frozenset({"unix", "format"})
_TG_EMOJI_ATTRS = frozenset({"emoji-id"})


def _rebuild_tg_tag(kind: str, raw_attrs: str, inner: str) -> str:
    """按白名单重建 tg-* 标签，丢弃未识别属性。"""
    allowed = _TG_TIME_ATTRS if kind == "time" else _TG_EMOJI_ATTRS
    attrs = [
        (name, val)
        for name, val in _ATTR_RE.findall(raw_attrs)
        if name in allowed
    ]
    attr_str = "".join(
        f' {name}="{escape_html(val, quote=True)}"' for name, val in attrs
    )
    return f"<tg-{kind}{attr_str}>{escape_html(inner)}</tg-{kind}>"


# ---------------------------------------------------------------------------
# Markdown 子集 -> HTML
# ---------------------------------------------------------------------------

# 成对分隔符。顺序有意义：长的排前面，避免 ** 被当成两个 *。
# 语义与 Telegram MarkdownV2 一致：
#   **bold** / *bold*  -> <b>
#   __underline__      -> <u>
#   _italic_           -> <i>
_EMPHASIS: tuple[tuple[str, str], ...] = (
    ("**", "b"),
    ("__", "u"),
    ("~~", "s"),
    ("||", "spoiler"),
    ("*", "b"),
    ("_", "i"),
)

# Markdown v1 只认 * _ ` [ 这几个标记，~ 和 | 是字面量。
# 若复用 v2 的表，价格里的 ~ 或 a || b 会被误判成删除线/剧透。
# 项目里的 v1 文本大量使用 **粗体**（v1 规范里其实是单星号），
# 因此这里保留 ** 并映射为 <b>，符合实际书写意图。
_EMPHASIS_V1: tuple[tuple[str, str], ...] = (
    ("**", "b"),
    ("*", "b"),
    ("_", "i"),
)

_OPEN_TAG = {
    "b": "<b>",
    "u": "<u>",
    "s": "<s>",
    "i": "<i>",
    "spoiler": '<span class="tg-spoiler">',
}
_CLOSE_TAG = {
    "b": "</b>",
    "u": "</u>",
    "s": "</s>",
    "i": "</i>",
    "spoiler": "</span>",
}


def _find_delimiter(text: str, delim: str, start: int) -> int:
    """
    从 ``start`` 起找能与 ``delim`` 配对的结束位置，找不到返回 -1。

    单字符分隔符会跳过由它组成的双字符对，避免 ``*a **b** c*`` 里
    外层 ``*`` 提前闭合。
    """
    i = start
    n = len(text)
    while True:
        j = text.find(delim, i)
        if j == -1:
            return -1
        # 反斜杠转义
        if j > 0 and text[j - 1] == "\\":
            i = j + 1
            continue
        # 单字符分隔符要避开 ** / __ 组合
        if delim in ("*", "_") and (
            (j + 1 < n and text[j + 1] == delim)
            or (j > 0 and text[j - 1] == delim)
        ):
            i = j + 1
            continue
        # 结束分隔符后面不能紧跟字母数字（避免 snake_case 误伤）
        if delim == "_" and j + 1 < n and text[j + 1].isalnum():
            i = j + 1
            continue
        return j


def _is_word_boundary(text: str, i: int) -> bool:
    """``_`` / ``*`` 开头前若紧跟字母数字，则当作普通字符。"""
    return i == 0 or not text[i - 1].isalnum()


def _render_inline(text: str, version: int = 2) -> str:
    """
    把 markdown 子集渲染成 Telegram HTML。

    递归处理嵌套：外层格式在找到匹配的结束分隔符后，对内部内容再次
    调用本函数，因此 ``**粗体里套 _斜体_**`` 能正确产出嵌套标签，
    代码块内部的内容则原样转义、不再解析。

    Args:
        text: 待渲染文本
        version: 1 或 2。v1 只识别 ``*`` / ``_``（``~`` 和 ``|`` 视为
            字面量），v2 额外支持 ``__``/``~~``/``||``。
    """
    emphasis = _EMPHASIS_V1 if version == 1 else _EMPHASIS
    out: list[str] = []
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]

        # --- 已存在的 tg-time / tg-emoji：白名单重建后透传 ---
        if ch == "<":
            m = _TG_TAG_RE.match(text, i)
            if m:
                out.append(_rebuild_tg_tag(m.group(1), m.group(2), m.group(3)))
                i = m.end()
                continue

        # --- 代码围栏 ```lang\n...\n``` ---
        if text.startswith("```", i):
            fence_end = text.find("```", i + 3)
            if fence_end != -1:
                raw = text[i + 3 : fence_end]
                lang = ""
                if "\n" in raw:
                    first, rest = raw.split("\n", 1)
                    if first.strip() and not first.strip().startswith(" "):
                        lang = first.strip()
                        raw = rest
                if lang:
                    out.append(
                        f'<pre><code class="language-'
                        f'{escape_html(lang, quote=True)}">{escape_html(rstrip_lines(raw))}'
                        f"</code></pre>"
                    )
                else:
                    out.append(f"<pre>{escape_html(rstrip_lines(raw))}</pre>")
                i = fence_end + 3
                continue

        # --- 行内代码 ---
        if ch == "`":
            code_end = text.find("`", i + 1)
            if code_end != -1:
                out.append(f"<code>{escape_html(text[i + 1 : code_end])}</code>")
                i = code_end + 1
                continue

        # --- 链接 [text](url) ---
        if ch == "[":
            m = re.match(r"\[([^\]\n]+)\]\(([^)\s]+)\)", text[i:])
            if m:
                label = _render_inline(m.group(1), version)
                url = escape_html(m.group(2), quote=True)
                out.append(f'<a href="{url}">{label}</a>')
                i += m.end()
                continue

        # --- 反斜杠转义 ---
        if ch == "\\" and i + 1 < n and text[i + 1] in "*_~|`[]()\\<>":
            out.append(escape_html(text[i + 1]))
            i += 2
            continue

        # --- 成对强调分隔符 ---
        matched = False
        delim_chars = "*_" if version == 1 else "*_~|"
        if ch in delim_chars and _is_word_boundary(text, i):
            for delim, kind in emphasis:
                if not text.startswith(delim, i):
                    continue
                close = _find_delimiter(text, delim, i + len(delim))
                if close == -1:
                    continue
                inner = text[i + len(delim) : close]
                if not inner:
                    continue
                out.append(
                    _OPEN_TAG[kind]
                    + _render_inline(inner, version)
                    + _CLOSE_TAG[kind]
                )
                i = close + len(delim)
                matched = True
                break
        if matched:
            continue

        # --- 普通字符 ---
        out.append(escape_html(ch))
        i += 1

    return "".join(out)


def rstrip_lines(text: str) -> str:
    """去掉代码块首尾多余的空行，保留内部缩进。"""
    return text.strip("\n")


def _escape_and_convert_lines(text: str) -> str:
    """兼容旧名字：把 markdown 子集转成 HTML。"""
    return _render_inline(text)


def md_to_html(text: str) -> str:
    """
    把 markdown 片段转成 Telegram HTML。

    覆盖的语法（与 Telegram MarkdownV2 语义一致）：

    ==================  ================================
    输入                输出
    ==================  ================================
    ``**粗体**``        ``<b>``
    ``*粗体*``          ``<b>``
    ``__下划线__``      ``<u>``
    ``_斜体_``          ``<i>``
    ``~~删除线~~``      ``<s>``
    ``||剧透||``        ``<span class="tg-spoiler">``
    ``` `代码` ```      ``<code>``
    ``` ```lang ...``` ```  ``<pre><code class="language-lang">``
    ``[文字](url)``     ``<a href="url">``
    ==================  ================================

    支持任意嵌套；未闭合的分隔符按普通字符处理，不会抛错。
    需要 ``<tg-time>`` / ``<tg-emoji>`` 时用 :func:`tg_time` /
    :func:`tg_emoji` 生成片段后直接拼进文本，本函数会原样保留。

    Args:
        text: markdown 片段

    Returns:
        HTML 字符串，可直接配合 ``parse_mode="HTML"`` 发送
    """
    if not text:
        return ""
    try:
        return _render_inline(text)
    except Exception as e:  # pragma: no cover - 防御性
        logger.error(f"Error during md_to_html conversion: {e}", exc_info=True)
        return escape_html(text)


def _fold(body: str, rendered: str) -> str:
    """超过折叠阈值时包一层可展开引用块。"""
    threshold = get_config().folding_threshold
    if len(body.split("\n")) <= threshold:
        return rendered
    return f"<blockquote expandable>{rendered}</blockquote>"


# MarkdownV2 里需要反斜杠转义的字符（与 telegram.helpers.escape_markdown 一致）
_V2_ESCAPE_CHARS = "_*[]()~`>#+-=|{}.!"
_V2_UNESCAPE_RE = re.compile(rf"\\([{re.escape(_V2_ESCAPE_CHARS)}])")

# 渲染前只还原"没有语法意义"的字符。格式字符（* _ ~ | ` [ ] ( ) >）保留
# 反斜杠，交给 _render_inline 的转义分支处理，否则 r"\*不是粗体\*" 会被
# 还原成 **...** 从而误判为加粗。
_V2_SAFE_UNESCAPE = r"#+\-={}.!"
_V2_SAFE_UNESCAPE_RE = re.compile(rf"\\([{re.escape(_V2_SAFE_UNESCAPE)}])")

# 旧 foldable_text_with_markdown_v2 的缺陷产物：它的单星号正则会把
# **标题** 拆坏，产生 \**标题** 或 \**标题*\* 两种变形，界面上会多出
# 字面星号。这里在转换时修复回 **标题**。
_LEGACY_BOLD_PATTERNS = (
    (re.compile(r"\\\*\*([^*\n]+)\*\\\*"), r"**\1**"),
    (re.compile(r"\\\*\*([^*\n]+)\*\*"), r"**\1**"),
)


def _repair_legacy_fold(text: str) -> str:
    """修复旧折叠函数把 **粗体** 拆坏的问题。"""
    for pattern, replacement in _LEGACY_BOLD_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def unescape_v2(text: str) -> str:
    """
    还原 MarkdownV2 的反斜杠转义。

    项目里大量代码先调用 ``escape_markdown(..., version=2)`` 再格式化，
    这些反斜杠在 HTML 模式下会原样显示成 ``\\.`` ``\\-``，所以切到 HTML
    前必须先还原。对未转义的文本是幂等操作。

    Args:
        text: 可能含 MarkdownV2 转义的文本

    Returns:
        还原后的文本
    """
    if not text:
        return ""

    # 项目里常见"先 escape_markdown 一次、foldable_* 内部再 escape 一次"
    # 的双重转义，因此循环还原直到稳定。转义层数有上限，避免病态输入死循环。
    for _ in range(8):
        restored = _V2_UNESCAPE_RE.sub(r"\1", text)
        if restored == text:
            break
        text = restored

    return text


def _unescape_for_render(text: str) -> str:
    """
    渲染前的转义处理。

    只还原 ``. - # + = { } !`` 这类无语法意义的字符；格式字符保留反斜杠，
    由 :func:`_render_inline` 输出为字面量字符。同时修复旧折叠函数的
    ``**粗体**`` 拆坏问题。
    """
    if not text:
        return ""

    text = _repair_legacy_fold(text)

    # 双重转义：\\* -> \*，最终仍保留一层给渲染器
    for _ in range(8):
        restored = _V2_SAFE_UNESCAPE_RE.sub(r"\1", text)
        if restored == text:
            break
        text = restored

    return text

    return text


def foldable_text_from_v2_escaped_html(body: str) -> str:
    """
    接受"已经过 MarkdownV2 转义"的文本，产出 HTML 折叠结果。

    供那些保留 ``escape_markdown(version=2)`` 调用、只想把发送端切到 HTML
    的模块使用。内部顺序是：先还原转义 -> 再按 markdown 子集渲染 -> 折叠。

    Args:
        body: 含 MarkdownV2 转义的文本

    Returns:
        HTML 字符串
    """
    try:
        if not body:
            return ""
        return _fold(body, _render_inline(_unescape_for_render(body)))
    except Exception as e:
        logger.error(f"Error during v2-escaped html formatting: {e}", exc_info=True)
        return escape_html(unescape_v2(body))


def foldable_plain_from_v2_escaped_html(body: str) -> str:
    """纯文本版本：只还原转义并折叠，不解析 markdown。"""
    try:
        if not body:
            return ""
        plain = unescape_v2(body)
        return _fold(body, escape_html(plain))
    except Exception as e:
        logger.error(f"Error during plain v2-escaped html: {e}", exc_info=True)
        return escape_html(unescape_v2(body))

# 旧折叠实现产生的前缀：**> 第一行  +  > 后续行  +  结尾 ||
_FOLD_OPEN_RE = re.compile(r"^\*\*>\s?")
_QUOTE_PREFIX_RE = re.compile(r"^>\s?")


def mdv2_to_html(text: str) -> str:
    """
    把 MarkdownV2 文本整体转换成 Telegram HTML。

    覆盖 MarkdownV2 的行级与行内语法：

    * 行首 ``> `` 引用块 -> ``<blockquote>``
    * 旧折叠格式 ``**> 首行`` + ``> 续行`` + 结尾 ``||``
      -> ``<blockquote expandable>``
    * 行内加粗/斜体/下划线/删除线/剧透/代码/代码围栏/链接
      （见 :func:`md_to_html`）
    * 反斜杠转义还原

    这是给"整体切换 parse_mode"用的兼容层：输入按 MarkdownV2 语义书写
    （含预先 escape 过的内容），输出可直接配 ``parse_mode="HTML"`` 发送。

    Args:
        text: MarkdownV2 文本

    Returns:
        HTML 字符串
    """
    if not text:
        return ""

    rendered = _mdv2_to_html_inner(text)

    # 已经是引用块（含旧折叠格式）就不再二次包裹，避免嵌套折叠
    if rendered.lstrip().startswith("<blockquote"):
        return rendered

    return _fold(text, rendered)


def _mdv2_to_html_inner(text: str, version: int = 2) -> str:
    """mdv2_to_html 的实现体（不含折叠包裹）。"""
    try:
        plain = _unescape_for_render(text)
        lines = plain.split("\n")

        # --- 旧折叠格式：**> 首行 + > 续行 + 结尾 || ---
        # v1 没有 spoiler，结尾的 || 属于字面量，不去除。
        if _FOLD_OPEN_RE.match(lines[0]):
            inner_lines = []
            for idx, line in enumerate(lines):
                if idx == 0:
                    inner_lines.append(_FOLD_OPEN_RE.sub("", line))
                else:
                    inner_lines.append(_QUOTE_PREFIX_RE.sub("", line))
            inner = "\n".join(inner_lines)
            if version != 1 and inner.rstrip().endswith("||"):
                inner = inner.rstrip()[:-2]
            return (
                f"<blockquote expandable>"
                f"{_render_inline(inner, version)}</blockquote>"
            )

        # --- 逐行处理：连续以 > 开头的行归为一个引用块 ---
        # 代码围栏必须先在整段上手处理，否则按行切开后会失效。
        out: list[str] = []
        buffer: list[str] = []
        i = 0
        n = len(lines)

        def flush_quote() -> None:
            if buffer:
                inner = "\n".join(_QUOTE_PREFIX_RE.sub("", ln) for ln in buffer)
                out.append(
                    f"<blockquote>{_render_inline(inner, version)}</blockquote>"
                )
                buffer.clear()

        while i < n:
            line = lines[i]

            # 代码围栏：收集到闭合为止
            if line.lstrip().startswith("```"):
                flush_quote()
                fence: list[str] = [line]
                i += 1
                while i < n:
                    fence.append(lines[i])
                    if lines[i].lstrip().startswith("```"):
                        i += 1
                        break
                    i += 1
                out.append(_render_inline("\n".join(fence), version))
                continue

            if _QUOTE_PREFIX_RE.match(line):
                buffer.append(line)
            else:
                flush_quote()
                out.append(_render_inline(line, version))
            i += 1

        flush_quote()
        return "\n".join(out)

    except Exception as e:
        logger.error(f"Error during mdv2_to_html: {e}", exc_info=True)
        return escape_html(unescape_v2(text))


def md1_to_html(text: str) -> str:
    """
    把 Markdown v1 文本转换成 Telegram HTML。

    v1 是 Telegram 保留的遗留模式，只有 ``*粗体*``、``_斜体_``、行内代码、
    代码块和链接；``~`` 与 ``|`` 是字面量，不会解析成删除线或剧透——这正是
    不能直接复用 :func:`mdv2_to_html` 的原因。

    项目里的 v1 文本实际大量书写 ``**粗体**``（v1 规范里应为单星号），
    因此这里把 ``**`` 也识别为加粗，符合原意。

    Args:
        text: Markdown v1 文本

    Returns:
        HTML 字符串
    """
    if not text:
        return ""

    rendered = _mdv2_to_html_inner(text, version=1)

    if rendered.lstrip().startswith("<blockquote"):
        return rendered

    return _fold(text, rendered)


def foldable_text_html(body: str) -> str:
    """
    纯文本版本的 HTML 折叠格式化。

    超过折叠阈值时用 ``<blockquote expandable>`` 包裹，客户端默认只显示
    前几行并给出展开按钮；未超过阈值则只做 HTML 转义。

    Args:
        body: 纯文本（不含 markdown 标记）

    Returns:
        HTML 字符串
    """
    try:
        if not body:
            return ""
        return _fold(body, escape_html(body))
    except Exception as e:
        logger.error(f"Error during html folding: {e}", exc_info=True)
        return escape_html(body)


def foldable_text_with_markdown_html(body: str) -> str:
    """
    markdown 版本的 HTML 折叠格式化。

    对应旧实现 ``foldable_text_with_markdown_v2``，区别在于：

    * 折叠改用原生 ``<blockquote expandable>``，不再用 ``**> `` 前缀 +
      结尾 ``||`` 拼伪折叠（旧写法依赖未闭合的 spoiler 标记，长文本
      容易把后续内容一并染成剧透）；
    * 支持嵌套格式与代码围栏。

    折叠判定基于原始行数，渲染在整段上一次性完成，因此代码围栏不会被
    行拆分破坏。

    Args:
        body: 含 markdown 标记的文本

    Returns:
        HTML 字符串
    """
    try:
        if not body:
            return ""
        return _fold(body, _render_inline(body))
    except Exception as e:
        logger.error(f"Error during html foldable formatting: {e}", exc_info=True)
        return escape_html(body)


def foldable_text(
    body: str, parse_mode: str = "MarkdownV2"
) -> str:
    """
    按 parse_mode 选择对应的折叠实现。

    Args:
        body: 文本
        parse_mode: 支持 ``"HTML"``、``"MarkdownV2"``/``"Markdown"``

    Returns:
        已格式化并（必要时）折叠的字符串

    Raises:
        ValueError: parse_mode 不受支持
    """
    mode = (parse_mode or "").strip().upper()
    if mode == "HTML":
        return foldable_text_with_markdown_html(body)
    if mode in ("MARKDOWNV2", "MARKDOWN", "MARKDOWN_V2"):
        return foldable_text_with_markdown_v2(body)
    raise ValueError(f"Unsupported parse_mode: {parse_mode!r}")


def foldable_plain_text(
    body: str, parse_mode: str = "MarkdownV2"
) -> str:
    """
    按 parse_mode 选择对应的纯文本折叠实现。

    ``MarkdownV2`` 走 :func:`foldable_text_v2`（只转义、不解析标记），
    ``HTML`` 走 :func:`foldable_text_html`。
    """
    mode = (parse_mode or "").strip().upper()
    if mode == "HTML":
        return foldable_text_html(body)
    if mode in ("MARKDOWNV2", "MARKDOWN", "MARKDOWN_V2"):
        return foldable_text_v2(body)
    raise ValueError(f"Unsupported parse_mode: {parse_mode!r}")
