"""
富文本卡片助手。

Telegram Bot API 没有表格、字号、颜色这些排版能力（全部消息实体只有
加粗/斜体/下划线/删除线/剧透/代码/代码块/引用块/链接/自定义 emoji/时间戳）。
那些「好看」的卡片 bot，靠的是把这些基础能力**组合排版**：

* ``<pre>`` 的等宽字体 + 精确空格对齐 -> 看起来像表格
* ``<blockquote>`` -> 左侧竖线引用块
* ``━━━━`` 等制表字符 -> 分隔线
* emoji 当图标
* 按钮 ``style`` 上色

本模块把这些封装成可直接调用的函数，返回可配 ``parse_mode="HTML"`` 发送的
字符串。所有文本都会自动做 HTML 转义，不用担心用户输入里带 ``<`` ``&``。
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Sequence

from .formatter import escape_html


# 常用分隔线
DIVIDER = "━━━━━━━━━━━━━━━━"
DIVIDER_THIN = "───────────────"


def display_width(text: str) -> int:
    """
    计算字符串的显示宽度。

    中文/全角字符占 2 列，ASCII 占 1 列。用于在等宽字体里对齐表格。
    """
    return sum(
        2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text
    )


def _pad(text: str, width: int, align: str) -> str:
    diff = width - display_width(text)
    if diff <= 0:
        return text
    return " " * diff + text if align == "right" else text + " " * diff


def _truncate_to_width(text: str, width: int) -> str:
    """按显示宽度截断（超宽时补 …）。"""
    if display_width(text) <= width:
        return text
    out, used = [], 0
    for ch in text:
        w = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if used + w > width - 1:
            break
        out.append(ch)
        used += w
    return "".join(out) + "…"


def pre_table(
    rows: Sequence[Sequence[str]],
    *,
    header: Sequence[str] | None = None,
    aligns: Sequence[str] | None = None,
    separator: str = " │ ",
) -> str:
    """
    用 ``<pre>`` 生成等宽对齐的表格。

    这是 Telegram 里唯一能做出「表格」观感的办法：``<pre>`` 会使用等宽
    字体并加灰底，中文按双宽计算后补齐空格即可对齐。

    Args:
        rows: 数据行，每行是若干单元格
        header: 表头行（可选，会加粗并加一条分隔线）
        aligns: 每列对齐方式（``"left"`` / ``"right"`` / ``"center"``）
        separator: 列之间的分隔符

    Returns:
        HTML 字符串（``<pre>`` 包裹）

    Examples:
        >>> pre_table([["金额", "US$39.95/月"], ["人数", "6 人车"]])
        '<pre>金额 │ US$39.95/月\\n人数 │ 6 人车   </pre>'
    """
    if not rows:
        return ""

    all_rows: list[list[str]] = []
    if header:
        all_rows.append([str(c) for c in header])
    all_rows.extend([str(c) for c in row] for row in rows)

    col_count = max(len(r) for r in all_rows)
    # 补齐短行
    for r in all_rows:
        r.extend([""] * (col_count - len(r)))

    widths = [
        max(display_width(r[i]) for r in all_rows) for i in range(col_count)
    ]
    aligns = list(aligns or ["left"] * col_count)
    while len(aligns) < col_count:
        aligns.append("left")

    lines: list[str] = []
    data_start = 0

    if header:
        head = ""
        for i, cell in enumerate(all_rows[0]):
            if i:
                head += separator
            head += _pad(cell, widths[i], aligns[i])
        lines.append(escape_html(head.rstrip()))
        # 表头下的分隔线
        total_w = sum(widths) + len(separator) * (col_count - 1)
        lines.append("─" * total_w)
        data_start = 1

    for row in all_rows[data_start:]:
        cells = [
            _pad(cell, widths[i], aligns[i]) for i, cell in enumerate(row)
        ]
        lines.append(escape_html(separator.join(cells).rstrip()))

    return "<pre>" + "\n".join(lines) + "</pre>"


def field_block(
    fields: Iterable[tuple[str, str]],
    *,
    icon_width: int = 4,
) -> str:
    """
    生成「标签: 值」的对齐字段块（不用等宽字体，普通 HTML）。

    Args:
        fields: (标签, 值) 序列
        icon_width: 标签补齐宽度，让冒号对齐

    Returns:
        HTML 字符串
    """
    lines = []
    for label, value in fields:
        pad = " " * max(0, icon_width - display_width(label))
        lines.append(f"{escape_html(label)}{pad}: {escape_html(value)}")
    return "\n".join(lines)


def quote(text: str, *, expandable: bool = False) -> str:
    """
    包成引用块（左侧竖线）。

    Args:
        text: 原文（支持已渲染的 HTML 片段，请自行确保安全）
        expandable: 是否可折叠（默认显示 3 行 + 展开按钮）

    Returns:
        HTML 字符串
    """
    attr = " expandable" if expandable else ""
    return f"<blockquote{attr}>{text}</blockquote>"


def card(
    *,
    title: str = "",
    subtitle: str | None = None,
    body: str | None = None,
    fields: Iterable[tuple[str, str]] | None = None,
    table: Sequence[Sequence[str]] | None = None,
    table_header: Sequence[str] | None = None,
    note: str | None = None,
    footer: str | None = None,
    divider: str = DIVIDER,
) -> str:
    """
    组装一张信息卡片。

    典型结构::

        标题（加粗）
        副标题
        ━━━━━━━━━━
        字段 / 表格 / 正文
        ━━━━━━━━━━
        📝 备注（引用块）
        页脚

    Args:
        title: 标题，会加粗
        subtitle: 副标题
        body: 正文段落
        fields: 字段列表（与 table 二选一，可同时用）
        table: 表格数据
        table_header: 表头
        note: 备注，渲染成引用块
        footer: 页脚小字
        divider: 分隔线字符

    Returns:
        HTML 字符串
    """
    parts: list[str] = []

    if title:
        parts.append(f"<b>{escape_html(title)}</b>")
    if subtitle:
        parts.append(escape_html(subtitle))

    body_parts: list[str] = []
    if fields:
        body_parts.append(field_block(fields))
    if table:
        body_parts.append(pre_table(table, header=table_header))
    if body:
        body_parts.append(body)

    if body_parts:
        if parts:
            parts.append(divider)
        parts.extend(body_parts)

    if note:
        if parts:
            parts.append("")
        parts.append(quote(f"📝 {escape_html(note)}"))

    if footer:
        if parts:
            parts.append("")
        parts.append(f"<i>{escape_html(footer)}</i>")

    return "\n".join(parts)
