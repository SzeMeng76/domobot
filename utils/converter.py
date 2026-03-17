"""
HTML 清理工具，用于 Telegraph 发布
FROM https://github.com/mercuree/html-telegraph-poster/blob/7212225e28a0206803c32e67d1185bbfbd1fc181/html_telegraph_poster/converter.py
"""
import re

from lxml.html.clean import Cleaner

allowed_tags = (
    "a",
    "aside",
    "b",
    "blockquote",
    "br",
    "code",
    "em",
    "figcaption",
    "figure",
    "h3",
    "h4",
    "hr",
    "i",
    "iframe",
    "img",
    "li",
    "ol",
    "p",
    "pre",
    "s",
    "strong",
    "u",
    "ul",
    "video",
)
telegram_embed_script_re = re.compile(
    r"""<script(?=[^>]+\sdata-telegram-post=['"]([^'"]+))[^<]+</script>""",
    re.IGNORECASE,
)
pre_content_re = re.compile(r"<(pre|code)(>|\s[^>]*>)[\s\S]*?</\1>")
line_breaks_inside_pre = re.compile(r"<br(/?>|\s[^<>]*>)")
line_breaks_and_empty_strings = re.compile(r"(\s{2,}|\s*\r?\n\s*)")
header_re = re.compile(r"<head[^a-z][\s\S]*</head>")


def clean_article_html(html_string):
    """
    清理 HTML 内容，使其符合 Telegraph 规范

    处理步骤：
    1. 标签标准化 (h1→h3, h2/h5/h6→h4, b→strong)
    2. Telegram embed 转换 (script→iframe)
    3. 移除 <head>
    4. lxml.Cleaner 清理 (只保留安全标签和属性)
    5. 清理换行符 (保留 <pre> 内的)
    6. 合并多个 <br> 为单个换行

    Args:
        html_string: 原始 HTML 字符串

    Returns:
        清理后的 HTML 字符串
    """
    html_string = html_string.replace("<h1", "<h3").replace("</h1>", "</h3>")
    # telegram will convert <b> anyway
    html_string = re.sub(r"<(/?)b(?=\s|>)", r"<\1strong", html_string)
    html_string = re.sub(r"<(/?)(h2|h5|h6)", r"<\1h4", html_string)
    # convert telegram embed posts before cleaner
    html_string = re.sub(
        telegram_embed_script_re,
        r'<iframe src="https://t.me/\1"></iframe>',
        html_string,
    )
    # remove <head> if present (can't do this with Cleaner)
    html_string = header_re.sub("", html_string)

    c = Cleaner(
        allow_tags=allowed_tags,
        style=True,
        remove_unknown_tags=False,
        embedded=False,
        safe_attrs_only=True,
        safe_attrs=("src", "href", "class"),
    )
    # wrap with div to be sure it is there
    # (otherwise lxml will add parent element in some cases
    html_string = f"<div>{html_string}</div>"
    cleaned = c.clean_html(html_string)
    # remove wrapped div
    cleaned = cleaned[5:-6]
    # remove all line breaks and empty strings
    html_string = replace_line_breaks_except_pre(cleaned)
    # but replace multiple br tags with one line break, telegraph will convert it to <br class="inline">
    html_string = re.sub(r"(<br(/?>|\s[^<>]*>)\s*)+", "\n", html_string)

    return html_string.strip(" \t")


def replace_line_breaks_except_pre(html_string, replace_by=" "):
    """
    移除所有换行符和空白字符，但保留 <pre> 标签内的

    Args:
        html_string: HTML 字符串
        replace_by: 用什么替换换行符（默认空格）

    Returns:
        处理后的 HTML 字符串
    """
    # Remove all line breaks and empty strings, except pre tag
    pre_ranges = [0]
    out = ""

    # replace non-breaking space with usual space
    html_string = html_string.replace("\u00a0", " ")

    # get <pre> start/end postion
    for x in pre_content_re.finditer(html_string):
        start, end = x.start(), x.end()
        pre_ranges.extend((start, end))
    pre_ranges.append(len(html_string))

    # all odd elements are <pre>, leave them untouched
    for k in range(1, len(pre_ranges)):
        part = html_string[pre_ranges[k - 1] : pre_ranges[k]]
        if k % 2 == 0:
            out += line_breaks_inside_pre.sub("\n", part)
        else:
            out += line_breaks_and_empty_strings.sub(replace_by, part)
    return out

