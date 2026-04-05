# commands/apple_services_modules/icloud_parser.py
"""
iCloud 价格解析器

从 Apple 网站和 Apple Support 页面解析 iCloud 存储价格
"""

import logging
import re

from bs4 import BeautifulSoup

from utils.country_data import SUPPORTED_COUNTRIES
from utils.price_parser import CURRENCY_SYMBOL_TO_CODE

logger = logging.getLogger(__name__)

# Apple Support 页面中文货币名 → ISO 4217 代码映射
# 用于从解析的标题（如 "苏里南（美元）"）中提取实际计价货币
CHINESE_CURRENCY_TO_CODE: dict[str, str] = {
    "美元": "USD",
    "欧元": "EUR",
    "英镑": "GBP",
    "日元": "JPY",
    "韩元": "KRW",
    "人民币": "CNY",
    "加元": "CAD",
    "澳元": "AUD",
    "新西兰元": "NZD",
    "港元": "HKD",
    "新台币": "TWD",
    "新加坡元": "SGD",
    "瑞士法郎": "CHF",
    "瑞典克朗": "SEK",
    "挪威克朗": "NOK",
    "丹麦克朗": "DKK",
    "印度卢比": "INR",
    "印尼盾": "IDR",
    "马来西亚林吉特": "MYR",
    "菲律宾比索": "PHP",
    "泰铢": "THB",
    "越南盾": "VND",
    "巴西雷亚尔": "BRL",
    "墨西哥比索": "MXN",
    "哥伦比亚比索": "COP",
    "智利比索": "CLP",
    "秘鲁新索尔": "PEN",
    "新土耳其里拉": "TRY",
    "南非兰特": "ZAR",
    "尼日利亚奈拉": "NGN",
    "埃及镑": "EGP",
    "以色列新谢克尔": "ILS",
    "沙特里亚尔": "SAR",
    "阿联酋迪拉姆": "AED",
    "卡塔尔里亚尔": "QAR",
    "俄罗斯卢布": "RUB",
    "波兰兹罗提": "PLN",
    "匈牙利福林": "HUF",
    "捷克克朗": "CZK",
    "罗马尼亚列伊": "RON",
    "巴基斯坦卢比": "PKR",
    "坦桑尼亚先令": "TZS",
    "哈萨克斯坦坚戈": "KZT",
    "保加利亚列弗": "BGN",
}


def resolve_icloud_currency(
    currency_hint: str,
    detected_currency: str | None,
    country_code: str,
) -> str:
    """根据多层优先级确定 iCloud 价格的实际计价货币

    优先级：
    1. 页面标题中的中文货币名（如 "苏里南（美元）" → USD）
    2. 符号检测结果中明确的非 USD 货币
    3. 符号检测为 USD 且本地货币符号不是 "$" → 确认 USD
    4. 回退到 SUPPORTED_COUNTRIES 中的默认货币

    Args:
        currency_hint: 解析器从页面标题提取的中文货币名（如 "美元"、"欧元"）
        detected_currency: extract_currency_and_price 检测到的货币代码（如 "SRD"、"USD"）
        country_code: ISO 国家代码（如 "SR"）

    Returns:
        ISO 4217 货币代码
    """
    # 优先级 1：页面标题明确标注的货币
    override = CHINESE_CURRENCY_TO_CODE.get(currency_hint)
    if override:
        return override

    country_info = SUPPORTED_COUNTRIES.get(country_code, {})

    # 优先级 2/3：符号检测
    if detected_currency and detected_currency != "USD":
        return detected_currency
    if detected_currency == "USD":
        local_symbol = country_info.get("symbol", "")
        if local_symbol != "$":
            return "USD"

    # 优先级 4：默认
    return country_info.get("currency", "USD")


# 从 price_parser 的货币映射表动态构建验证正则（双向匹配前缀/后缀货币符号）
_sorted_symbols = sorted(CURRENCY_SYMBOL_TO_CODE.keys(), key=len, reverse=True)
_escaped_symbols = [re.escape(s) for s in _sorted_symbols]
_all_symbols_pattern = "|".join(_escaped_symbols)

_CURRENCY_PATTERN = re.compile(
    rf"(?:{_all_symbols_pattern})\s*[\d,]+(?:\.\d+)?|"
    rf"[\d,]+(?:\.\d+)?\s*(?:{_all_symbols_pattern})"
)

# 免费词汇（多语言）
_FREE_TERMS = frozenset(
    [
        "ücretsiz",  # Turkish
        "free",  # English
        "gratis",  # Spanish/Portuguese
        "gratuit",  # French
        "kostenlos",  # German
        "免费",  # Chinese
    ]
)


def _is_valid_price_format(price_text: str) -> bool:
    """验证价格文本是否为有效的价格格式

    Args:
        price_text: 待验证的价格文本

    Returns:
        bool: 如果是有效价格格式返回 True
    """
    price_lower = price_text.lower()

    # 检查免费词汇
    for term in _FREE_TERMS:
        if term in price_lower:
            return True

    # 检查货币符号
    if _CURRENCY_PATTERN.search(price_text):
        return True

    # 检查订阅周期模式（多语言）
    subscription_patterns = [
        "/month",
        "per month",
        "/year",
        "per year",
        "ayda",  # Turkish
        "月",  # Chinese/Japanese
        "월",  # Korean
        "mes",  # Spanish/Portuguese
        "mois",  # French
        "monat",  # German
        "/maand",
        "per maand",  # Dutch monthly
        "/jaar",
        "per jaar",  # Dutch yearly
    ]

    for pattern in subscription_patterns:
        if pattern in price_lower:
            return True

    return False


def get_icloud_prices_from_html(content: str) -> dict:
    """从 Apple Support HTML 内容提取 iCloud 价格

    支持两种页面结构:
    - 新版: h4.gb-header(国家+货币) + ul.gb-list > li(容量：价格)
    - 旧版: p.gb-paragraph(国家+货币) + p.gb-paragraph > b(容量) + 价格

    Args:
        content: Apple Support 页面 HTML 内容

    Returns:
        dict: 国家名称 -> {"currency": 货币名, "prices": {容量: 价格}}
    """
    soup = BeautifulSoup(content, "html.parser")
    prices = {}

    # 尝试新版结构: h4.gb-header + ul(list gb-list)
    prices = _parse_h4_ul_structure(soup)

    # 如果新版结构无结果，回退到旧版 p.gb-paragraph 结构
    if not prices:
        prices = _parse_paragraph_structure(soup)

    logger.info(f"Total countries parsed from Apple Support HTML: {len(prices)}")
    return prices


# 清理国家名中的脚注数字（如 "巴哈马2,3" → "巴哈马", "韩国5" → "韩国"）
_FOOTNOTE_PATTERN = re.compile(r"[\d,]+$")

# 容量提取正则
_TIER_PATTERN = re.compile(r"(\d+\s*(?:GB|TB))")


def _parse_h4_ul_structure(soup: BeautifulSoup) -> dict:
    """解析新版页面结构: h4 标题 + ul 列表

    结构:
      <h4 class="gb-header">巴西（巴西雷亚尔）</h4>
      <ul class="list gb-list">
        <li><p class="gb-paragraph"><b>50GB</b>：R$ 5.90</p></li>
        ...
      </ul>
    """
    prices = {}
    h4s = soup.find_all("h4", class_="gb-header")

    for h4 in h4s:
        text = h4.get_text(strip=True)
        if "（" not in text or "）" not in text:
            continue

        # 提取国家名和货币
        match = re.match(r"^(.*?)（(.*?)）", text)
        if not match:
            continue

        raw_country = match.group(1).strip()
        currency = match.group(2).strip()

        # 清理脚注数字
        country_name = _FOOTNOTE_PATTERN.sub("", raw_country).strip()
        if not country_name:
            continue

        # 找紧邻的 ul 兄弟
        next_ul = h4.find_next_sibling("ul")
        if not next_ul:
            continue

        size_price_dict = {}
        for li in next_ul.find_all("li"):
            li_text = li.get_text(strip=True)
            if not li_text:
                continue

            # 格式: "50GB：$0.99" 或 "50 GB：$0.99"
            tier_match = _TIER_PATTERN.search(li_text)
            if not tier_match:
                continue

            tier = tier_match.group(1).replace(" ", "")

            # 提取价格（冒号后面的部分）
            if "：" in li_text:
                price = li_text.split("：", 1)[1].strip()
            elif ":" in li_text:
                price = li_text.split(":", 1)[1].strip()
            else:
                continue

            if price:
                size_price_dict[tier] = price

        if size_price_dict:
            prices[country_name] = {"currency": currency, "prices": size_price_dict}
            logger.debug(f"[h4+ul] {country_name}: {len(size_price_dict)} tiers")

    return prices


def _parse_paragraph_structure(soup: BeautifulSoup) -> dict:
    """解析旧版页面结构: p.gb-paragraph 段落

    结构:
      <p class="gb-paragraph">俄罗斯（俄罗斯卢布）</p>    ← 国家行(无 <b>)
      <p class="gb-paragraph"><b>50GB</b>：₽59</p>        ← 价格行(有 <b>)
    """
    prices = {}
    paragraphs = soup.find_all("p", class_="gb-paragraph")
    current_country = None
    size_price_dict = {}
    currency = ""

    for p in paragraphs:
        text = p.get_text(strip=True)

        if "（" in text and "）" in text and not p.find("b"):
            # 保存前一个国家
            if current_country and size_price_dict:
                prices[current_country] = {
                    "currency": currency,
                    "prices": size_price_dict,
                }

            clean_text = re.sub(r"<[^>]+>", "", text)
            country_match = re.match(r"^(.*?)（(.*?)）", clean_text)
            if country_match:
                current_country = country_match.group(1).strip()
                currency = country_match.group(2).strip()
                size_price_dict = {}

        elif current_country:
            size_elem = p.find("b")
            if size_elem:
                size_text = size_elem.get_text(strip=True)

                if "：" in text:
                    price = text.split("：", 1)[1].strip()
                elif ":" in text:
                    price = text.split(":", 1)[1].strip()
                else:
                    full_text = p.get_text(strip=True)
                    bold_text = size_elem.get_text(strip=True)
                    if bold_text in full_text:
                        price = full_text.replace(bold_text, "").strip()
                        price = re.sub(r"^[：:]\s*", "", price).strip()
                    else:
                        continue

                if price and size_text:
                    # 清理 tier 名称中的冒号（部分 HTML 格式 <b>50GB：</b>）
                    clean_tier = _TIER_PATTERN.search(size_text)
                    tier_key = (
                        clean_tier.group(1).replace(" ", "")
                        if clean_tier
                        else size_text.rstrip("：:")
                    )
                    size_price_dict[tier_key] = price

    # 保存最后一个国家
    if current_country and size_price_dict:
        prices[current_country] = {"currency": currency, "prices": size_price_dict}

    return prices


def get_icloud_prices_from_apple_website(content: str, country_code: str) -> dict:
    """从 Apple 网站 HTML 内容提取 iCloud 价格（如 apple.com/tr/icloud/）

    Args:
        content: Apple 官网 iCloud 页面 HTML 内容
        country_code: 国家/地区代码

    Returns:
        dict: 国家名称 -> {"currency": 货币名, "prices": {容量: 价格}}
    """
    soup = BeautifulSoup(content, "html.parser")
    country_info = SUPPORTED_COUNTRIES.get(country_code, {})
    country_name = country_info.get("name", country_code)
    currency = country_info.get("currency", "")

    logger.info(
        f"Parsing iCloud prices for {country_name} ({country_code}), currency: {currency}"
    )

    size_price_dict = {}

    # Method 1: Comparison table pricing (most comprehensive - includes all plans)
    plan_items = soup.find_all("div", class_="plan-list-item")
    logger.info(f"Found {len(plan_items)} plan items in comparison table")

    for item in plan_items:
        cost_elem = item.find("p", class_="typography-compare-body plan-type cost")
        if cost_elem:
            aria_label = cost_elem.get("aria-label", "")
            price_text = cost_elem.get_text(strip=True)

            logger.debug(
                f"Processing item: aria-label='{aria_label}', price_text='{price_text}'"
            )

            # Extract capacity from aria-label
            capacity_match = re.search(r"(\d+\s*(?:GB|TB))", aria_label)
            if capacity_match:
                capacity = capacity_match.group(1).replace(" ", "")
                if _is_valid_price_format(price_text):
                    size_price_dict[capacity] = price_text
                    logger.info(f"Added plan: {capacity} = {price_text}")
                else:
                    logger.debug(
                        f"Skipped plan {capacity}: price '{price_text}' doesn't match pricing criteria"
                    )
            else:
                logger.debug(f"No capacity match in aria-label: '{aria_label}'")

    # Method 2: Accordion structure (fallback)
    if not size_price_dict:
        accordion_buttons = soup.find_all("button")
        for button in accordion_buttons:
            if "data-accordion-item" in button.attrs or "accordion" in " ".join(
                button.get("class", [])
            ):
                capacity_elem = button.find("span", class_="plan-capacity")
                price_span = None

                # Find price span (role="text")
                for span in button.find_all("span"):
                    span_text = span.get_text(strip=True)
                    if span.get("role") == "text" and _is_valid_price_format(span_text):
                        price_span = span
                        break

                if capacity_elem and price_span:
                    capacity = capacity_elem.get_text(strip=True).replace(" ", "")
                    price = price_span.get_text(strip=True)
                    size_price_dict[capacity] = price

    # Method 3: Hero section pricing (fallback for basic plans)
    if not size_price_dict:
        price_elements = soup.find_all("p", class_="typography-hero-compare-price")
        plan_elements = soup.find_all("h3", class_="typography-hero-compare-plan")

        if (
            price_elements
            and plan_elements
            and len(price_elements) == len(plan_elements)
        ):
            for price_elem, plan_elem in zip(price_elements, plan_elements):
                price_text = price_elem.get_text(strip=True)
                plan_text = plan_elem.get_text(strip=True).replace(" ", "")

                if price_text and plan_text:
                    size_price_dict[plan_text] = price_text

    if size_price_dict:
        logger.info(
            f"Successfully parsed {len(size_price_dict)} iCloud plans for {country_name}"
        )
        return {country_name: {"currency": currency, "prices": size_price_dict}}
    else:
        logger.warning(
            f"No iCloud pricing data found for {country_name} using Apple website parser"
        )
        return {}
