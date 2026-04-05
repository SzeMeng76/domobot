"""
价格格式化工具模块

提供统一的价格格式化、排名 emoji、时间戳格式化等功能。
供所有价格查询命令（Netflix、Spotify、Disney+、Max、Steam、App Store 等）使用。
"""

from datetime import datetime
from typing import Optional

from utils.rate_converter import RateConverter


def get_rank_emoji(rank: int) -> str:
    """
    根据排名获取对应的 emoji

    Args:
        rank: 排名（1-based index）

    Returns:
        排名对应的 emoji 字符串

    Examples:
        >>> get_rank_emoji(1)
        '🥇'
        >>> get_rank_emoji(5)
        '5️⃣'
        >>> get_rank_emoji(15)
        '15.'
    """
    rank_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

    if rank == 1:
        return "🥇"
    elif rank == 2:
        return "🥈"
    elif rank == 3:
        return "🥉"
    elif 4 <= rank <= 10:
        return rank_emojis[rank - 1]
    else:
        return f"{rank}."


def format_cache_timestamp(timestamp: int, prefix: str = "⏱ 数据更新时间") -> str:
    """
    格式化缓存时间戳为可读字符串

    Args:
        timestamp: Unix 时间戳（秒）
        prefix: 时间戳前缀文本

    Returns:
        格式化后的时间字符串

    Examples:
        >>> format_cache_timestamp(1704067200)
        '⏱ 数据更新时间 (缓存)：2024-01-01 00:00:00'
    """
    update_time_str = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
    return f"{prefix} (缓存)：{update_time_str}"


async def format_price_with_cny(
    price: float | str,
    currency: str,
    rate_converter: RateConverter,
    show_original: bool = True,
) -> str:
    """
    格式化价格并转换为人民币显示

    Args:
        price: 原始价格（数值或字符串）
        currency: 货币代码（如 "USD", "EUR"）
        rate_converter: 汇率转换器实例
        show_original: 是否显示原始价格

    Returns:
        格式化后的价格字符串，如 "USD 9.99 ≈ ¥69.93" 或 "¥69.93"

    Examples:
        >>> await format_price_with_cny(9.99, "USD", rate_converter)
        'USD 9.99 ≈ ¥69.93'
        >>> await format_price_with_cny(9.99, "USD", rate_converter, show_original=False)
        '¥69.93'
    """
    # 提取数值
    if isinstance(price, str):
        # 尝试从字符串中提取数值
        import re

        match = re.search(r"[\d,]+\.?\d*", price.replace(",", ""))
        if match:
            price_num = float(match.group())
        else:
            return price  # 无法解析，返回原始字符串
    else:
        price_num = float(price)

    # 转换为人民币
    price_cny = await rate_converter.convert(price_num, currency, "CNY")

    if price_cny is None or price_cny <= 0:
        # 转换失败，返回原始价格
        return f"{currency} {price_num:.2f}" if show_original else "价格未知"

    # 格式化输出
    if show_original:
        return f"{currency} {price_num:.2f} ≈ ¥{price_cny:.2f}"
    else:
        return f"¥{price_cny:.2f}"


def normalize_period_text(text: str, target_lang: str = "zh") -> str:
    """
    标准化订阅周期文本（月/年）

    Args:
        text: 原始周期文本（如 "month", "year", "月", "年"）
        target_lang: 目标语言，"zh" 为中文，"en" 为英文

    Returns:
        标准化后的周期文本

    Examples:
        >>> normalize_period_text("month", "zh")
        '月'
        >>> normalize_period_text("yearly", "zh")
        '年'
        >>> normalize_period_text("月", "en")
        'month'
    """
    text_lower = text.lower().strip()

    # 月份映射
    month_keywords = ["month", "monthly", "mo", "月", "/mo"]
    # 年份映射
    year_keywords = ["year", "yearly", "annual", "annually", "yr", "年", "/yr"]

    if target_lang == "zh":
        if any(keyword in text_lower for keyword in month_keywords):
            return "月"
        elif any(keyword in text_lower for keyword in year_keywords):
            return "年"
        else:
            return text  # 无法识别，返回原文
    elif target_lang == "en":
        if any(keyword in text_lower for keyword in month_keywords):
            return "month"
        elif any(keyword in text_lower for keyword in year_keywords):
            return "year"
        else:
            return text
    else:
        return text


def format_price_range(
    min_price: float, max_price: float, currency: str = "CNY"
) -> str:
    """
    格式化价格区间

    Args:
        min_price: 最低价格
        max_price: 最高价格
        currency: 货币代码

    Returns:
        格式化后的价格区间字符串

    Examples:
        >>> format_price_range(10.0, 50.0, "CNY")
        '¥10.00 - ¥50.00'
        >>> format_price_range(9.99, 19.99, "USD")
        'USD 9.99 - USD 19.99'
    """
    if currency == "CNY":
        return f"¥{min_price:.2f} - ¥{max_price:.2f}"
    else:
        return f"{currency} {min_price:.2f} - {currency} {max_price:.2f}"


def format_subscription_plan(
    plan_name: str,
    price: float | str,
    currency: str,
    period: Optional[str] = None,
    price_cny: Optional[float] = None,
) -> str:
    """
    格式化订阅计划信息

    Args:
        plan_name: 计划名称（如 "家庭版", "Premium"）
        price: 价格
        currency: 货币代码
        period: 订阅周期（可选）
        price_cny: 人民币价格（可选）

    Returns:
        格式化后的订阅计划字符串

    Examples:
        >>> format_subscription_plan("家庭版", 99.0, "USD", "month", 693.0)
        '💰 家庭版: USD 99.00/月 ≈ ¥693.00'
        >>> format_subscription_plan("Premium", 9.99, "USD")
        '💰 Premium: USD 9.99'
    """
    # 格式化价格部分
    if isinstance(price, (int, float)):
        price_str = f"{currency} {price:.2f}"
    else:
        price_str = f"{currency} {price}"

    # 添加周期
    if period:
        period_zh = normalize_period_text(period, "zh")
        price_str = f"{price_str}/{period_zh}"

    # 添加人民币转换
    if price_cny and price_cny > 0:
        price_str = f"{price_str} ≈ ¥{price_cny:.2f}"

    return f"💰 {plan_name}: {price_str}"
