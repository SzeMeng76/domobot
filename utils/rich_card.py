"""
富文本卡片（Rich Message）高层封装。

Telegram MTProto 侧的 Rich Message 支持真正的表格、标题层级、列表等排版，
这是 PTB 22.8（Bot API）没有的能力，只能经 Kurigram 发送。

本模块把底层 block 组装封装成简单调用：

    await send_price_card(helper, chat_id, title="Netflix", rows=[("移动版", "MYR 19.90")])

同时提供 HTML 降级版本（:func:`render_plain`），在没有 Kurigram 或服务端
不支持富文本时使用，保证用户至少能读到内容。
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence

from .pyrogram_client import convert_reply_markup

logger = logging.getLogger(__name__)


def _build_table(
    header: Sequence[str] | None,
    rows: Iterable[Sequence[str]],
    *,
    bordered: bool = True,
    striped: bool = True,
    aligns: Sequence[str] | None = None,
):
    """
    构造 InputRichBlockTable。

    Args:
        header: 表头（会标记为 header 单元格）
        rows: 数据行
        bordered: 是否显示边框
        striped: 是否隔行变色
        aligns: 每列对齐（left/center/right）

    Returns:
        InputRichBlockTable 或 None（无数据时）
    """
    from pyrogram.types import InputRichBlockTable, RichBlockTableCell

    all_rows: list[list[str]] = []
    if header:
        all_rows.append([str(c) for c in header])
    all_rows.extend([str(c) for c in row] for row in rows)

    if not all_rows:
        return None

    col_count = max(len(r) for r in all_rows)
    for r in all_rows:
        r.extend([""] * (col_count - len(r)))

    align_list = list(aligns or ["left"] * col_count)
    while len(align_list) < col_count:
        align_list.append("left")

    cells = []
    for row_idx, row in enumerate(all_rows):
        cell_row = [
            RichBlockTableCell(
                text=value,
                is_header=row_idx == 0 if header else None,
                align=align_list[idx],
            )
            for idx, value in enumerate(row)
        ]
        cells.append(cell_row)

    return InputRichBlockTable(cells=cells, is_bordered=bordered, is_striped=striped)


def build_price_card(
    *,
    title: str,
    subtitle: str | None = None,
    rows: Iterable[Sequence[str]],
    header: Sequence[str] | None = None,
    note: str | None = None,
    footer: str | None = None,
) -> list:
    """
    组装价格类卡片的 block 列表。

    结构：标题 -> 副标题 -> 表格 -> 备注 -> 页脚。

    Args:
        title: 标题
        subtitle: 副标题
        rows: 表格数据行
        header: 表头
        note: 备注（引用块）
        footer: 页脚

    Returns:
        block 列表，可直接传给 send_rich_message(blocks=...)
    """
    from pyrogram.types import (
        InputRichBlockBlockQuotation,
        InputRichBlockFooter,
        InputRichBlockParagraph,
        InputRichBlockSectionHeading,
    )

    blocks: list = []

    if title:
        blocks.append(InputRichBlockSectionHeading(text=title, size=1))
    if subtitle:
        blocks.append(InputRichBlockParagraph(text=subtitle))

    table = _build_table(header, rows)
    if table:
        blocks.append(table)

    if note:
        blocks.append(
            InputRichBlockBlockQuotation(
                blocks=[InputRichBlockParagraph(text=note)]
            )
        )
    if footer:
        blocks.append(InputRichBlockFooter(text=footer))

    return blocks


def render_plain(
    *,
    title: str = "",
    subtitle: str | None = None,
    rows: Iterable[Sequence[str]] = (),
    header: Sequence[str] | None = None,
    note: str | None = None,
    footer: str | None = None,
) -> str:
    """
    生成降级用的 HTML 文本（``<pre>`` 等宽对齐模拟表格）。

    与 :func:`build_price_card` 接收相同参数，保证富文本失败时内容一致。

    Args:
        同 :func:`build_price_card`

    Returns:
        HTML 字符串，配 ``parse_mode="HTML"`` 发送
    """
    from .formatter import escape_html
    from .richtext_card import DIVIDER, display_width, pre_table

    parts: list[str] = []

    if title:
        parts.append(f"<b>{escape_html(title)}</b>")
    if subtitle:
        parts.append(escape_html(subtitle))

    table_rows = [list(r) for r in rows]
    if table_rows:
        if parts:
            parts.append(DIVIDER)
        if header:
            parts.append(pre_table(table_rows, header=header))
        else:
            # 无表头时统一按两列对齐，避免首行被当成标题样式
            width = max(display_width(str(r[0])) for r in table_rows if r)
            lines = [
                f"{str(r[0]).ljust(width)}{'  ' + str(r[1]) if len(r) > 1 else ''}"
                for r in table_rows
            ]
            parts.append("<pre>" + escape_html("\n".join(lines)) + "</pre>")

    if note:
        parts.append(f"<blockquote>📝 {escape_html(note)}</blockquote>")
    if footer:
        parts.append(f"<i>{escape_html(footer)}</i>")

    return "\n".join(parts)


async def send_price_card(
    helper,
    chat_id: int,
    *,
    title: str,
    rows: Iterable[Sequence[str]],
    subtitle: str | None = None,
    header: Sequence[str] | None = None,
    note: str | None = None,
    footer: str | None = None,
    reply_markup=None,
    reply_to_message_id: int | None = None,
    parse_mode: str = "HTML",
):
    """
    发送价格卡片：优先富文本表格，失败自动降级为普通消息。

    Args:
        helper: :class:`~utils.pyrogram_client.PyrogramHelper` 实例
        chat_id: 聊天ID
        title: 标题
        rows: 表格数据行
        subtitle: 副标题
        header: 表头
        note: 备注
        footer: 页脚
        reply_markup: PTB 的 InlineKeyboardMarkup
        reply_to_message_id: 回复的消息ID
        parse_mode: 降级消息使用的解析模式

    Returns:
        发送的消息对象，全部失败时返回 None
    """
    if not helper or not getattr(helper, "is_started", False):
        logger.debug("Pyrogram 未启动，跳过富文本发送")
        return None

    rows = list(rows)
    if not rows:
        return None

    fallback = render_plain(
        title=title,
        subtitle=subtitle,
        rows=rows,
        header=header,
        note=note,
        footer=footer,
    )

    try:
        blocks = build_price_card(
            title=title,
            subtitle=subtitle,
            rows=rows,
            header=header,
            note=note,
            footer=footer,
        )
        return await helper.send_rich_message(
            chat_id=chat_id,
            blocks=blocks,
            reply_markup=reply_markup,
            reply_to_message_id=reply_to_message_id,
        )
    except Exception as e:
        logger.warning("富文本表格发送失败，降级为等宽表格: %s", e)

    # 富文本已经失败过一次，这里直接走普通消息，不再重复尝试富文本
    try:
        return await helper.client.send_message(
            chat_id=chat_id,
            text=fallback,
            parse_mode=parse_mode,
            reply_markup=convert_reply_markup(reply_markup),
            reply_to_message_id=reply_to_message_id,
        )
    except Exception as e:
        logger.warning("等宽表格发送失败，降级为纯文本: %s", e)

    try:
        return await helper.client.send_message(
            chat_id=chat_id,
            text=_strip_tags(fallback),
            reply_markup=convert_reply_markup(reply_markup),
            reply_to_message_id=reply_to_message_id,
        )
    except Exception as e:
        logger.error("纯文本降级也失败: %s", e)
        return None


def _strip_tags(html: str) -> str:
    """去掉 HTML 标签，用于最终降级为纯文本。"""
    import re

    text = re.sub(r"<[^>]+>", "", html)
    return re.sub(r"\n{3,}", "\n\n", text).strip()
