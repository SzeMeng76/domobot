# commands/apple_services_modules/apple_one_parser.py
"""
Apple One 价格解析器

从 Apple 网站解析 Apple One 套餐价格
"""

import logging
import re
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup, NavigableString, Tag

if TYPE_CHECKING:
    from .service import AppleServicesService

logger = logging.getLogger(__name__)

# data-tile-id → 中文名称映射（语言无关）
_PLAN_ID_TO_CN = {
    "plan-individual": "个人",
    "plan-family": "家庭",
    "plan-premier": "高级",
}

# 多语言 plan 名称 → 中文（兜底：当 data-tile-id 不可用时使用）
_PLAN_TEXT_TO_CN = {
    "individual": "个人",
    "family": "家庭",
    "premier": "高级",
    "個人": "个人",
    "個人方案": "个人",
    "ファミリー": "家庭",
    "家庭方案": "家庭",
    "プレミア": "高级",
}

# 月费周期清理正则（匹配各语言的 /月、/mo.、per month、月額 等后缀）
_MONTHLY_SUFFIX_RE = re.compile(
    r"\s*/\s*(?:mo\.?|month|maand|mes|mois|Monat|月)\s*$"
    r"|per\s+month\s*$"
    r"|月額\s*$",
    re.IGNORECASE,
)


def _normalize_plan_name(plan_element, name_text: str) -> str:
    """将各语言的 plan 名称统一为中文

    优先使用 data-tile-id 属性（语言无关），回退到文本匹配。
    """
    # 优先：从父级 div.plan-tile 的 data-tile-id 获取
    parent_tile = plan_element.find_parent("div", class_="plan-tile")
    if parent_tile:
        tile_id = parent_tile.get("data-tile-id", "")
        if tile_id in _PLAN_ID_TO_CN:
            return _PLAN_ID_TO_CN[tile_id]

    # 回退：文本匹配
    lookup = name_text.strip()
    if lookup.lower() in _PLAN_TEXT_TO_CN:
        return _PLAN_TEXT_TO_CN[lookup.lower()]
    if lookup in _PLAN_TEXT_TO_CN:
        return _PLAN_TEXT_TO_CN[lookup]

    return name_text


def _extract_visible_text(element) -> str:
    """提取元素的可见文本，跳过 visuallyhidden 无障碍冗余 span

    Apple 的价格 HTML 结构:
      ₩14,900<span aria-hidden="true">/월.</span><span class="visuallyhidden">/월</span>
    直接 get_text() 会得到 "₩14,900/월./월"（重复）。
    此函数跳过 visuallyhidden span，返回 "₩14,900/월."。
    """
    parts = []
    for child in element.children:
        if isinstance(child, NavigableString):
            parts.append(str(child))
        elif isinstance(child, Tag):
            classes = child.get("class", [])
            if "visuallyhidden" not in classes:
                parts.append(child.get_text())
    return "".join(parts).strip()


def _clean_price_text(price: str) -> str:
    """清理价格文本中的月费周期后缀"""
    cleaned = _MONTHLY_SUFFIX_RE.sub("", price).strip()
    cleaned = cleaned.replace("per month", "").replace("per maand", "").strip()
    # 清理尾部句号（日文促销文案截断后残留）
    cleaned = re.sub(r"[。.]\s*$", "", cleaned).strip()
    return cleaned


async def parse_apple_one_prices(
    content: str,
    country_code: str,
    service_instance: "AppleServicesService",
) -> list[str]:
    """解析 Apple One 价格

    Args:
        content: Apple One 页面 HTML 内容
        country_code: 国家/地区代码
        service_instance: AppleServicesService 实例（用于汇率转换）

    Returns:
        list[str]: 格式化的价格信息行列表
    """
    result_lines = []
    soup = BeautifulSoup(content, "html.parser")
    plans = soup.find_all("div", class_="plan-tile")
    logger.info(f"Found {len(plans)} Apple One plans for {country_code}")

    if not plans:
        result_lines.append("Apple One 服务在该国家/地区不可用。")
        return result_lines

    is_first_plan = True
    for plan in plans:
        if not is_first_plan:
            result_lines.append("")
        else:
            is_first_plan = False

        name = plan.find("h3", class_="typography-plan-headline")
        price_element = plan.find("p", class_="typography-plan-subhead")

        if name and price_element:
            name_text = _normalize_plan_name(name, name.get_text(strip=True))
            price = _clean_price_text(_extract_visible_text(price_element))

            line = f"• {name_text}: {price}"
            if country_code != "CN":
                cny_price_str = await service_instance.convert_price_to_cny(
                    price, country_code
                )
                line += cny_price_str
            result_lines.append(line)

            services = plan.find_all("li", class_="service-item")
            for service_item in services:
                service_name = service_item.find("span", class_="visuallyhidden")
                service_price = service_item.find("span", class_="cost")

                if service_name and service_price:
                    service_name_text = service_name.get_text(strip=True)
                    # iCloud+ 附带存储容量标记 (如 "50GB")
                    storage_badge = service_item.find(
                        "span", class_="typography-plan-violator"
                    )
                    if storage_badge:
                        service_name_text += f" {storage_badge.get_text(strip=True)}"
                    service_price_text = _clean_price_text(
                        _extract_visible_text(service_price)
                    )
                    service_line = f"  - {service_name_text}: {service_price_text}"
                    if country_code != "CN":
                        cny_price_str = await service_instance.convert_price_to_cny(
                            service_price_text, country_code
                        )
                        service_line += cny_price_str
                    result_lines.append(service_line)

    return result_lines
