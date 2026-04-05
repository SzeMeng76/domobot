# commands/apple_services_modules/apple_music_parser.py
"""
Apple Music 价格解析器

从 Apple 网站解析 Apple Music 订阅价格
"""

import logging
import re
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup, Tag

from utils.price_parser import CURRENCY_SYMBOL_TO_CODE, extract_currency_and_price

if TYPE_CHECKING:
    from .service import AppleServicesService

logger = logging.getLogger(__name__)

# 从 price_parser 的货币映射表动态构建脚注价格提取正则
# 按长度降序排列，避免 "HK$" 被 "$" 先匹配
_sorted_symbols = sorted(CURRENCY_SYMBOL_TO_CODE.keys(), key=len, reverse=True)
_escaped_symbols = [re.escape(s) for s in _sorted_symbols]
_all_symbols_pattern = "|".join(_escaped_symbols)

_FOOTNOTE_PRICE_RE = re.compile(
    rf"(?:{_all_symbols_pattern})\s*[\d,]+(?:\.\d+)?|"
    rf"[\d,]+(?:\.\d+)?\s*(?:{_all_symbols_pattern})"
)

# 月费后缀清理正则
_PERIOD_SUFFIX_RE = re.compile(
    r"\s*/\s*(?:mo\.?|month|maand|mes|mois|Monat|月|년|年)\s*$"
    r"|per\s+(?:month|maand)\s*$"
    r"|/월\.?\s*$",
    re.IGNORECASE,
)


def _clean_price_text(text: str) -> str:
    """清理价格文本：去掉促销文案、月费后缀、'月額'前缀"""
    text = re.sub(r"[。].*$", "", text).strip()
    text = _PERIOD_SUFFIX_RE.sub("", text).strip()
    text = re.sub(r"^月額\s*", "", text).strip()
    return text


async def parse_apple_music_prices(
    content: str,
    country_code: str,
    service_instance: "AppleServicesService",
) -> list[str]:
    """解析 Apple Music 价格

    Args:
        content: Apple Music 页面 HTML 内容
        country_code: 国家/地区代码
        service_instance: AppleServicesService 实例（用于汇率转换）

    Returns:
        list[str]: 格式化的价格信息行列表
    """
    result_lines = []
    soup = BeautifulSoup(content, "html.parser")
    plans_section = soup.find("section", class_="section-plans")

    if not plans_section or not isinstance(plans_section, Tag):
        result_lines.append("Apple Music 服务在该国家/地区不可用。")
        return result_lines

    if country_code == "CN":
        result_lines = await _parse_apple_music_cn(
            plans_section, soup, service_instance
        )
    else:
        result_lines = await _parse_apple_music_standard(
            plans_section, country_code, service_instance
        )

    # 补充：某些方案的 gallery item 显示促销文案而非价格，从页面脚注中提取
    result_lines = await _supplement_from_footnotes(
        result_lines, soup, country_code, service_instance
    )

    return result_lines


async def _parse_apple_music_cn(
    plans_section: Tag,
    soup: BeautifulSoup,
    service_instance: "AppleServicesService",
) -> list[str]:
    """解析中国区 Apple Music 价格

    Args:
        plans_section: plans section Tag
        soup: 完整的 BeautifulSoup 对象
        service_instance: AppleServicesService 实例

    Returns:
        list[str]: 格式化的价格信息行列表
    """
    result_lines = []
    logger.info("Applying CN-specific parsing for Apple Music.")

    # Try new gallery-based structure first (2024+ layout)
    gallery_items = plans_section.select("li.gallery-item")
    parsed_any = False

    if gallery_items:
        logger.info(f"Found {len(gallery_items)} gallery items (new layout)")
        # Extract student price from FAQ if available
        faq_section = soup.find("section", class_="section-faq")
        if faq_section:
            faq_text = faq_section.get_text()
            student_match = re.search(r"学生.*?每月仅需\s*(RMB\s*\d+)", faq_text)
            if student_match:
                student_price = student_match.group(1)
                result_lines.append(f"• 学生计划: {student_price}/月")
                parsed_any = True

        # Parse gallery items for individual and family plans
        for item in gallery_items:
            plan_name_elem = item.select_one("h3.tile-eyebrow")
            price_elem = item.select_one("p.tile-headline")

            if plan_name_elem and price_elem:
                plan_name = plan_name_elem.get_text(strip=True)
                price_text = price_elem.get_text(strip=True)
                # Extract price from "仅需 RMB 11/月" format
                price_match = re.search(r"(RMB\s*\d+)/月", price_text)
                if price_match:
                    price_str = f"{price_match.group(1)}/月"
                    result_lines.append(f"• {plan_name}计划: {price_str}")
                    parsed_any = True

    # Fallback to old structure if new layout didn't work
    if not parsed_any:
        logger.info("Falling back to old plan-list-item structure")
        student_plan_item = plans_section.select_one("div.plan-list-item.student")
        if student_plan_item and isinstance(student_plan_item, Tag):
            plan_name_tag = student_plan_item.select_one("p.plan-type:not(.cost)")
            price_tag = student_plan_item.select_one("p.cost")
            if plan_name_tag and price_tag:
                price_str = price_tag.get_text(strip=True)
                result_lines.append(f"• 学生计划: {price_str}")

        individual_plan_item = plans_section.select_one("div.plan-list-item.individual")
        if individual_plan_item and isinstance(individual_plan_item, Tag):
            plan_name_tag = individual_plan_item.select_one("p.plan-type:not(.cost)")
            price_tag = individual_plan_item.select_one("p.cost")
            if plan_name_tag and price_tag:
                price_str = price_tag.get_text(strip=True)
                result_lines.append(f"• 个人计划: {price_str}")

        family_plan_item = plans_section.select_one("div.plan-list-item.family")
        if family_plan_item and isinstance(family_plan_item, Tag):
            plan_name_tag = family_plan_item.select_one("p.plan-type:not(.cost)")
            price_tag = family_plan_item.select_one("p.cost")
            if plan_name_tag and price_tag:
                price_str = price_tag.get_text(strip=True)
                result_lines.append(f"• 家庭计划: {price_str}")

    return result_lines


async def _parse_apple_music_standard(
    plans_section: Tag,
    country_code: str,
    service_instance: "AppleServicesService",
) -> list[str]:
    """解析非中国区 Apple Music 价格

    Args:
        plans_section: plans section Tag
        country_code: 国家/地区代码
        service_instance: AppleServicesService 实例

    Returns:
        list[str]: 格式化的价格信息行列表
    """
    result_lines = []
    logger.info(f"Applying standard parsing for Apple Music ({country_code}).")

    # Try new gallery-based structure first (2024+ layout)
    gallery_items = plans_section.select("li.gallery-item")
    parsed_any = False

    if gallery_items:
        logger.info(
            f"Found {len(gallery_items)} gallery items for {country_code} (new layout)"
        )

        # Map of plan IDs to Chinese names
        plan_name_map = {
            "student": "学生",
            "individual": "个人",
            "voice": "Voice",
            "family": "家庭",
        }

        for item in gallery_items:
            # Get plan ID from item's id attribute
            plan_id = item.get("id", "")
            plan_name_elem = item.select_one("h3.tile-eyebrow")
            price_elem = item.select_one("p.tile-headline")

            if plan_name_elem and price_elem:
                # Use mapped Chinese name if available, otherwise use extracted name
                plan_name = plan_name_map.get(
                    plan_id, plan_name_elem.get_text(strip=True)
                )
                price_text = price_elem.get_text(strip=True)

                # 清理价格文本，去掉促销后缀和月费标记
                cleaned = _clean_price_text(price_text)

                # 用动态正则提取价格 token（货币符号+数字），
                # 过滤掉 "Try it free for 1 month" 等促销文案
                price_match = _FOOTNOTE_PRICE_RE.search(cleaned)
                if not price_match:
                    continue

                price_str = price_match.group(0).strip()

                # 用通用价格解析器验证
                _, price_value = extract_currency_and_price(
                    price_str, country_code, service="apple_services"
                )

                if price_value is not None and price_value > 0:
                    line = f"• {plan_name}计划: {price_str}"
                    if country_code != "CN":
                        cny_price_str = await service_instance.convert_price_to_cny(
                            price_str, country_code
                        )
                        line += cny_price_str
                    result_lines.append(line)
                    parsed_any = True

    # Fallback to old plan-list-item structure
    if not parsed_any:
        logger.info(f"Falling back to old plan-list-item structure for {country_code}")
        plan_items = plans_section.select("div.plan-list-item")
        plan_order = ["student", "individual", "family"]
        processed_plans = set()

        for plan_type in plan_order:
            item = plans_section.select_one(f"div.plan-list-item.{plan_type}")
            if item and isinstance(item, Tag) and plan_type not in processed_plans:
                plan_name_tag = item.select_one(
                    "p.plan-type:not(.cost), h3, h4, .plan-title, .plan-name"
                )
                plan_name_extracted = (
                    plan_name_tag.get_text(strip=True).replace("プラン", "").strip()
                    if plan_name_tag
                    else plan_type.capitalize()
                )

                price_tag = item.select_one("p.cost span, p.cost, .price, .plan-price")
                if price_tag:
                    price_str = price_tag.get_text(strip=True)
                    price_str = re.sub(
                        r"\s*/\s*(月|month|mo\.?).*",
                        "",
                        price_str,
                        flags=re.IGNORECASE,
                    ).strip()

                    if plan_type == "student":
                        plan_name = "学生"
                    elif plan_type == "individual":
                        plan_name = "个人"
                    elif plan_type == "family":
                        plan_name = "家庭"
                    else:
                        plan_name = plan_name_extracted

                    line = f"• {plan_name}计划: {price_str}"
                    cny_price_str = await service_instance.convert_price_to_cny(
                        price_str, country_code
                    )
                    line += cny_price_str
                    result_lines.append(line)
                    processed_plans.add(plan_type)

        for item in plan_items:
            class_list = item.get("class", [])
            is_processed = False
            for p_plan in processed_plans:
                if p_plan in class_list:
                    is_processed = True
                    break
            if is_processed:
                continue

            plan_name_tag = item.select_one(
                "p.plan-type:not(.cost), h3, h4, .plan-title, .plan-name"
            )
            plan_name = (
                plan_name_tag.get_text(strip=True).replace("プラン", "").strip()
                if plan_name_tag
                else "未知计划"
            )

            price_tag = item.select_one("p.cost span, p.cost, .price, .plan-price")
            if price_tag:
                price_str = price_tag.get_text(strip=True)
                price_str = re.sub(
                    r"\s*/\s*(月|month|mo\.?).*",
                    "",
                    price_str,
                    flags=re.IGNORECASE,
                ).strip()

                line = f"• {plan_name}: {price_str}"
                cny_price_str = await service_instance.convert_price_to_cny(
                    price_str, country_code
                )
                line += cny_price_str
                result_lines.append(line)

    return result_lines


async def _supplement_from_footnotes(
    result_lines: list[str],
    soup: BeautifulSoup,
    country_code: str,
    service_instance: "AppleServicesService",
) -> list[str]:
    """从页面脚注中补充 gallery item 未包含价格的方案

    Apple 的某些方案（尤其是 individual）在 gallery item 中显示免费试用
    促销文案而非实际价格，实际价格出现在页面底部脚注中。
    """
    # 检查已解析到的方案
    found = set()
    joined = " ".join(result_lines)
    if "个人" in joined or "個人" in joined:
        found.add("individual")
    if "学生" in joined or "學生" in joined:
        found.add("student")
    if "家庭" in joined:
        found.add("family")

    if len(found) >= 3:
        return result_lines

    full_text = soup.get_text()

    # 方案关键词 → (搜索词列表, 显示名称)
    plans = [
        ("individual", ["个人", "個人", "Individual"], "个人"),
        ("student", ["学生", "學生", "Student"], "学生"),
        ("family", ["家庭", "Family"], "家庭"),
    ]

    for plan_id, keywords, display_name in plans:
        if plan_id in found:
            continue

        price_str = _find_price_in_footnotes(full_text, keywords)
        if not price_str:
            continue

        if country_code == "CN":
            line = f"• {display_name}计划: {price_str}/月"
        else:
            line = f"• {display_name}计划: {price_str}"
            cny_str = await service_instance.convert_price_to_cny(
                price_str, country_code
            )
            line += cny_str
        result_lines.append(line)
        logger.info(f"[footnote] {country_code} {display_name}: {price_str}")

    return result_lines


def _find_price_in_footnotes(text: str, keywords: list[str]) -> str | None:
    """在页面全文中搜索方案关键词附近的价格

    搜索策略: 方案关键词 → 80字符内 → "每月/月" → 后续30字符内 → 价格模式
    示例:
      CN: "个人订阅每月仅需 RMB 11"
      HK: "個人收費計劃每月只需 HK$68"
    """
    for kw in keywords:
        pattern = (
            rf"{kw}.{{0,80}}(?:每月|月费|月收费|月額|/月|monthly|per month|/month)"
        )
        for m in re.finditer(pattern, text, re.IGNORECASE):
            context = text[m.start() : m.end() + 30]
            price_match = _FOOTNOTE_PRICE_RE.search(context[len(kw) :])
            if price_match:
                return price_match.group(0).strip()
    return None
