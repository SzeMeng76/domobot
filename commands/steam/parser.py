# Description: Steam 模块的辅助解析函数
# 从原 steam.py 拆分

import re


def escape_markdown(text: str) -> str:
    """转义 Markdown 特殊字符"""
    special_chars = [
        "\\",
        "`",
        "*",
        "_",
        "{",
        "}",
        "[",
        "]",
        "(",
        ")",
        "#",
        "+",
        "-",
        ".",
        "!",
    ]
    for char in special_chars:
        text = text.replace(char, f"\\{char}")
    return text


def get_country_code(country_input: str) -> str | None:
    """
    将国家输入（中文名、英文名或代码）转换为国家代码

    支持输入:
    - 国家代码: US, TR, CN, UK, JP
    - 中文名称: 美国, 土耳其, 中国
    - 英文全名: USA, Turkey, China, United Kingdom, Japan

    Args:
        country_input: 用户输入的国家标识

    Returns:
        str: 国家代码（大写），如 "US"
        None: 无效输入
    """
    from utils.country_mapper import get_country_code as unified_get_country_code

    return unified_get_country_code(country_input)


def parse_bundle_price(price_str: str) -> float | None:
    """解析捆绑包价格字符串"""
    if not price_str or price_str == "未知":
        return None
    # 移除货币符号和空格，提取数字
    match = re.search(r"[\d,]+\.?\d*", price_str.replace(",", ""))
    return float(match.group()) if match else None
