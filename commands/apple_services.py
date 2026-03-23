import asyncio
import logging
import re
from datetime import timedelta

import httpx
from bs4 import BeautifulSoup, Tag
from telegram import Update
from telegram.ext import ContextTypes

from utils.command_factory import command_factory
from utils.config_manager import get_config
from utils.country_data import COUNTRY_NAME_TO_CODE, SUPPORTED_COUNTRIES, get_country_flag
from utils.formatter import foldable_text_v2, foldable_text_with_markdown_v2
from utils.message_manager import delete_user_command, send_error, send_success, send_help
from utils.permissions import Permission
from utils.price_parser import extract_price_value_from_country_info


def normalize_pricing_text(price_text: str) -> str:
    """Normalize pricing text to Chinese for consistent display."""
    # First check for free pricing terms in different languages
    free_terms = [
        "ücretsiz",    # Turkish
        "free",        # English
        "gratis",      # Spanish/Portuguese
        "gratuit",     # French
        "kostenlos",   # German
        "無料",        # Japanese
        "무료",        # Korean
        "免费",        # Chinese Simplified
        "免費",        # Chinese Traditional
        "مجاني",       # Arabic
        "gratuito",    # Italian
        "бесплатно",   # Russian
    ]

    price_lower = price_text.lower().strip()
    for term in free_terms:
        if term.lower() in price_lower:
            return "免费"

    # Normalize subscription periods to Chinese
    normalized_text = price_text

    # Remove duplicate period indicators (e.g., "/monthper month", "/maandper maand")
    normalized_text = re.sub(r'/month\s*per month', '/month', normalized_text, flags=re.IGNORECASE)
    normalized_text = re.sub(r'per month\s*/month', 'per month', normalized_text, flags=re.IGNORECASE)
    normalized_text = re.sub(r'/maand\s*per maand', '/maand', normalized_text, flags=re.IGNORECASE)
    normalized_text = re.sub(r'per maand\s*/maand', 'per maand', normalized_text, flags=re.IGNORECASE)
    normalized_text = re.sub(r'/jaar\s*per jaar', '/jaar', normalized_text, flags=re.IGNORECASE)
    normalized_text = re.sub(r'per jaar\s*/jaar', 'per jaar', normalized_text, flags=re.IGNORECASE)
    
    # Replace various period indicators with Chinese equivalents
    period_replacements = [
        # Monthly patterns
        (r'/month', '每月'),
        (r'per month', '每月'),
        (r'\bmonth\b', '每月'),
        (r'\bayda\b', '每月'),  # Turkish
        (r'月額', '每月'),      # Japanese
        (r'월', '每월'),        # Korean
        (r'/mes', '每月'),      # Spanish
        (r'par mois', '每月'),  # French
        (r'pro Monat', '每月'), # German
        (r'/maand', '每月'),    # Dutch
        (r'per maand', '每月'), # Dutch

        # Yearly patterns
        (r'/year', '每年'),
        (r'per year', '每年'),
        (r'\byear\b', '每年'),
        (r'yıllık', '每年'),   # Turkish
        (r'年額', '每年'),      # Japanese
        (r'연', '每年'),        # Korean
        (r'/año', '每年'),      # Spanish
        (r'par an', '每年'),    # French
        (r'pro Jahr', '每年'),  # German
        (r'/jaar', '每年'),     # Dutch
        (r'per jaar', '每年'),  # Dutch
    ]
    
    for pattern, replacement in period_replacements:
        normalized_text = re.sub(pattern, replacement, normalized_text, flags=re.IGNORECASE)
    
    # Clean up extra whitespace
    normalized_text = re.sub(r'\s+', ' ', normalized_text).strip()
    
    return normalized_text


# Configure logging
logger = logging.getLogger(__name__)

# Default search countries if none are specified by the user
DEFAULT_COUNTRIES = ["CN", "NG", "TR", "JP", "IN", "MY"]

# Global rate_converter (will be set by main.py)
rate_converter = None


def set_rate_converter(converter):
    global rate_converter
    rate_converter = converter


async def convert_price_to_cny(price: str, country_code: str, context: ContextTypes.DEFAULT_TYPE) -> str:
    """Converts a price string from a given country's currency to CNY."""
    rate_converter = context.bot_data["rate_converter"]

    if not rate_converter:
        return " (汇率转换器未初始化)"

    country_info = SUPPORTED_COUNTRIES.get(country_code)
    if not country_info:
        return " (不支持的国家)"

    # 使用 extract_currency_and_price 来检测实际货币
    from utils.price_parser import extract_currency_and_price
    detected_currency, price_value = extract_currency_and_price(price, country_code)

    if price_value is None or price_value <= 0:
        return ""

    # 使用统一的降级转换函数，使用检测到的货币而不是国家默认货币
    from commands.rate_command import convert_currency_with_fallback
    cny_price = await convert_currency_with_fallback(price_value, detected_currency, "CNY")
    if cny_price is not None:
        return f" ≈ ¥{cny_price:.2f} CNY"
    else:
        return " (汇率获取失败)"


def parse_countries_from_args(args: list[str]) -> list[str]:
    """Parses country arguments, supporting codes and Chinese names."""
    countries = []
    for arg in args:
        country = arg.upper()
        if arg in COUNTRY_NAME_TO_CODE:
            countries.append(COUNTRY_NAME_TO_CODE[arg])
        elif country in SUPPORTED_COUNTRIES:
            countries.append(country)
    return countries if countries else DEFAULT_COUNTRIES


def get_icloud_prices_from_html(content: str) -> dict:
    """Extracts iCloud prices from Apple Support HTML content.

    New HTML structure (as of 2025):
    <h4 class="gb-header">Nigeria<sup>3</sup> (NGN)</h4>
    <ul class="list gb-list">
      <li class="gb-list_item">
        <p class="gb-paragraph"><b>50 GB</b>: ₦900</p>
      </li>
    </ul>
    """
    soup = BeautifulSoup(content, "html.parser")
    prices = {}

    # Find all country headers (h4 with class gb-header)
    country_headers = soup.find_all("h4", class_="gb-header")

    for header in country_headers:
        header_text = header.get_text(strip=True)

        # Extract country name and currency from format like:
        # English: "Nigeria<sup>3</sup> (NGN)"
        # Chinese: "尼日利亚<sup>3</sup>（尼日利亚奈拉）"
        # Remove superscript footnotes
        clean_text = re.sub(r'<sup>.*?</sup>', '', str(header))
        clean_text = BeautifulSoup(clean_text, "html.parser").get_text(strip=True)

        # Try English format first: "Country Name (CURRENCY_CODE)"
        country_match = re.match(r"^(.*?)\s*\(([A-Z]{3})\)$", clean_text)
        if country_match:
            country_name = country_match.group(1).strip()
            currency_code = country_match.group(2).strip()
        else:
            # Try Chinese format: "国家名（货币名称）"
            country_match = re.match(r"^(.*?)（(.+?)）$", clean_text)
            if not country_match:
                logger.debug(f"Skipping header with unrecognized format: {clean_text}")
                continue
            country_name = country_match.group(1).strip()
            currency_name = country_match.group(2).strip()
            # For Chinese format, use currency name as code (will be displayed as-is)
            currency_code = currency_name

        # Find the next <ul> sibling that contains the prices
        price_list = header.find_next_sibling("ul", class_="gb-list")
        if not price_list:
            # Try finding within next few siblings
            next_elem = header.find_next_sibling()
            while next_elem and next_elem.name != "h4":
                if next_elem.name == "ul" and "gb-list" in next_elem.get("class", []):
                    price_list = next_elem
                    break
                next_elem = next_elem.find_next_sibling()

        if not price_list:
            logger.warning(f"No price list found for country: {country_name}")
            continue

        # Extract prices from list items
        size_price_dict = {}
        list_items = price_list.find_all("li", class_="gb-list_item")

        for item in list_items:
            p = item.find("p", class_="gb-paragraph")
            if not p:
                continue

            text = p.get_text(strip=True)
            size_elem = p.find("b")

            if size_elem:
                # Get storage size and normalize by removing spaces (e.g., "50 GB" -> "50GB")
                size_text = size_elem.get_text(strip=True).replace(" ", "")

                # Extract price after colon
                if ":" in text:
                    price = text.split(":", 1)[1].strip()
                elif "：" in text:
                    price = text.split("：", 1)[1].strip()
                else:
                    # Fallback: extract everything after bold part
                    full_text = p.get_text(strip=True)
                    bold_text = size_elem.get_text(strip=True)
                    if bold_text in full_text:
                        price = full_text.replace(bold_text, "").strip()
                        price = re.sub(r"^[：:]\s*", "", price).strip()
                    else:
                        continue

                if price and size_text:
                    size_price_dict[size_text] = price
                    logger.debug(f"Added price for {country_name}: {size_text} = {price}")

        if size_price_dict:
            prices[country_name] = {"currency": currency_code, "prices": size_price_dict}
            logger.info(f"Parsed {country_name} ({currency_code}) with {len(size_price_dict)} storage tiers")

    logger.info(f"Total countries parsed from Apple Support HTML: {len(prices)}")
    return prices


def get_icloud_prices_from_apple_website(content: str, country_code: str) -> dict:
    """Extracts iCloud prices from Apple website HTML content (e.g., apple.com/tr/icloud/)."""
    soup = BeautifulSoup(content, "html.parser")
    country_info = SUPPORTED_COUNTRIES.get(country_code, {})
    country_name = country_info.get("name", country_code)
    currency = country_info.get("currency", "")
    
    logger.info(f"Parsing iCloud prices for {country_name} ({country_code}), currency: {currency}")
    
    size_price_dict = {}
    
    # Method 1: Comparison table pricing (most comprehensive - includes all plans)
    plan_items = soup.find_all("div", class_="plan-list-item")
    logger.info(f"Found {len(plan_items)} plan items in comparison table")
    
    for item in plan_items:
        cost_elem = item.find("p", class_="typography-compare-body plan-type cost")
        if cost_elem:
            aria_label = cost_elem.get("aria-label", "")
            price_text = cost_elem.get_text(strip=True)
            
            logger.debug(f"Processing item: aria-label='{aria_label}', price_text='{price_text}'")
            
            # Extract capacity from aria-label
            capacity_match = re.search(r"(\d+\s*(?:GB|TB))", aria_label)
            if capacity_match:
                capacity = capacity_match.group(1).replace(" ", "")
                # Handle both paid plans (with currency) and free plans
                # Check for common currency patterns or free terms
                is_valid_price = (
                    # Free terms in various languages
                    "ücretsiz" in price_text.lower() or "free" in price_text.lower() or
                    "gratis" in price_text.lower() or "gratuit" in price_text.lower() or
                    "kostenlos" in price_text.lower() or "免费" in price_text or
                    # Currency patterns
                    re.search(r'[\d.,]+\s*(?:TL|RM|USD|\$|EUR|€|£|¥|₹|₩|₦|R\$|C\$|A\$|NZ\$|HK\$|S\$|₱|₪|₨|kr|₽|zł|Kč|Ft)', price_text) or
                    # Month/year patterns (subscription pricing)
                    "/month" in price_text or "per month" in price_text or
                    "/year" in price_text or "per year" in price_text or
                    "ayda" in price_text.lower() or "月" in price_text or
                    "/maand" in price_text.lower() or "per maand" in price_text.lower() or  # Dutch
                    "/jaar" in price_text.lower() or "per jaar" in price_text.lower()  # Dutch
                )
                
                if is_valid_price:
                    size_price_dict[capacity] = price_text
                    logger.info(f"Added plan: {capacity} = {price_text}")
                else:
                    logger.debug(f"Skipped plan {capacity}: price '{price_text}' doesn't match pricing criteria")
            else:
                logger.debug(f"No capacity match in aria-label: '{aria_label}'")
    
    # Method 2: Accordion structure (fallback)
    if not size_price_dict:
        accordion_buttons = soup.find_all("button")
        for button in accordion_buttons:
            if "data-accordion-item" in button.attrs or "accordion" in " ".join(button.get("class", [])):
                capacity_elem = button.find("span", class_="plan-capacity")
                price_span = None
                
                # Find price span (role="text")
                for span in button.find_all("span"):
                    span_text = span.get_text(strip=True)
                    if span.get("role") == "text":
                        # Check for valid pricing patterns
                        is_valid_price = (
                            "ücretsiz" in span_text.lower() or "free" in span_text.lower() or
                            "gratis" in span_text.lower() or "gratuit" in span_text.lower() or
                            "kostenlos" in span_text.lower() or "免费" in span_text or
                            re.search(r'[\d.,]+\s*(?:TL|RM|USD|\$|EUR|€|£|¥|₹|₩|₦|R\$|C\$|A\$|NZ\$|HK\$|S\$|₱|₪|₨|kr|₽|zł|Kč|Ft)', span_text) or
                            "/month" in span_text or "per month" in span_text or
                            "/year" in span_text or "per year" in span_text or
                            "ayda" in span_text.lower() or "月" in span_text or
                            "/maand" in span_text.lower() or "per maand" in span_text.lower() or  # Dutch
                            "/jaar" in span_text.lower() or "per jaar" in span_text.lower()  # Dutch
                        )
                        if is_valid_price:
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
        
        if price_elements and plan_elements and len(price_elements) == len(plan_elements):
            for price_elem, plan_elem in zip(price_elements, plan_elements):
                price_text = price_elem.get_text(strip=True)
                plan_text = plan_elem.get_text(strip=True).replace(" ", "")
                
                if price_text and plan_text:
                    size_price_dict[plan_text] = price_text
    
    if size_price_dict:
        logger.info(f"Successfully parsed {len(size_price_dict)} iCloud plans for {country_name}")
        return {country_name: {"currency": currency, "prices": size_price_dict}}
    else:
        logger.warning(f"No iCloud pricing data found for {country_name} using Apple website parser")
        return {}


async def get_service_info(url: str, country_code: str, service: str, context: ContextTypes.DEFAULT_TYPE) -> str:
    """Fetches and parses Apple service price information with caching."""
    cache_manager = context.bot_data["cache_manager"]

    cache_key = f"apple_service_prices_{service}_{country_code}"
    cached_result = await cache_manager.load_cache(
        cache_key, max_age_seconds=timedelta(days=1).total_seconds(), subdirectory="apple_services"
    )
    if cached_result:
        return cached_result

    country_info = SUPPORTED_COUNTRIES.get(country_code)
    if not country_info:
        return "不支持的国家/地区"

    flag_emoji = get_country_flag(country_code)
    service_display_name = {"icloud": "iCloud", "appleone": "Apple One", "applemusic": "Apple Music"}.get(
        service, service
    )

    logger.info(f"Processing request for {country_info['name']} ({country_code}), URL: {url}, Service: {service})")

    try:
        from utils.http_client import get_http_client

        client = get_http_client()
        response = await client.get(url, timeout=15)
        content = None

        if response.status_code == 404:
            logger.info(f"{service} not available in {country_code} (404).")
            # For iCloud, try fallback to Apple Support page
            if service == "icloud":
                logger.info(f"Attempting iCloud fallback to Apple Support page for {country_code}")
                support_url = "https://support.apple.com/zh-cn/108047"
                try:
                    fallback_response = await client.get(support_url, timeout=15)
                    if fallback_response.status_code == 200:
                        content = fallback_response.text
                        url = support_url  # Update URL to reflect we're using support page
                        logger.info(f"Successfully fetched fallback URL: {support_url}")
                        # Continue with parsing using the support page content
                    else:
                        return f"📍 国家/地区: {flag_emoji} {country_info['name']}\n{service_display_name} 服务在该国家/地区不可用。"
                except Exception as fallback_error:
                    logger.error(f"Fallback request failed: {fallback_error}")
                    return f"📍 国家/地区: {flag_emoji} {country_info['name']}\n{service_display_name} 服务在该国家/地区不可用。"
            else:
                return f"📍 国家/地区: {flag_emoji} {country_info['name']}\n{service_display_name} 服务在该国家/地区不可用。"
        else:
            response.raise_for_status()
            content = response.text
            logger.info(f"Successfully fetched URL: {url}")
        
        if content is None:
            return f"📍 国家/地区: {flag_emoji} {country_info['name']}\n{service_display_name} 服务在该国家/地区不可用。"

    except httpx.HTTPStatusError as e:
        logger.error(f"Network error for {url}: {e}")
        if e.response.status_code == 404:
            # For iCloud, try fallback to Apple Support page
            if service == "icloud":
                logger.info(f"Attempting iCloud fallback to Apple Support page for {country_code} (HTTPStatusError)")
                support_url = "https://support.apple.com/zh-cn/108047"
                try:
                    fallback_response = await client.get(support_url, timeout=15)
                    if fallback_response.status_code == 200:
                        content = fallback_response.text
                        url = support_url  # Update URL to reflect we're using support page
                        logger.info(f"Successfully fetched fallback URL: {support_url}")
                        # Continue with parsing using the support page content
                    else:
                        return f"📍 国家/地区: {flag_emoji} {country_info['name']}\n{service_display_name} 服务在该国家/地区不可用。"
                except Exception as fallback_error:
                    logger.error(f"Fallback request failed: {fallback_error}")
                    return f"📍 国家/地区: {flag_emoji} {country_info['name']}\n{service_display_name} 服务在该国家/地区不可用。"
            else:
                return f"📍 国家/地区: {flag_emoji} {country_info['name']}\n{service_display_name} 服务在该国家/地区不可用。"
        return f"📍 国家/地区: {flag_emoji} {country_info['name']}\n获取价格信息失败: 网络错误或请求超时 (HTTP {e.response.status_code})。"
    except httpx.RequestError as e:
        logger.error(f"Unexpected error fetching {url}: {e}")
        return f"📍 国家/地区: {flag_emoji} {country_info['name']}\n获取价格信息失败: 网络错误或请求超时。"
    except Exception as e:
        logger.error(f"Fatal error for {country_code}, service {service}: {e}")
        return f"📍 国家/地区: {flag_emoji} {country_info['name']}\n获取价格信息失败: {e!s}."

    try:
        result_lines = [f"📍 国家/地区: {flag_emoji} {country_info['name']}"]
        service_display_name = {"icloud": "iCloud", "appleone": "Apple One", "applemusic": "Apple Music"}.get(
            service, service
        )

        if service == "icloud":
            # Try to parse as Apple website first (for country-specific URLs)
            prices = get_icloud_prices_from_apple_website(content, country_code)
            
            # Fallback to legacy Apple Support page format if no prices found
            if not prices:
                prices = get_icloud_prices_from_html(content)
            
            # If still no prices and we're not already using Apple Support, try fallback
            if not prices and "support.apple.com" not in url:
                logger.info(f"No prices found, attempting Apple Support fallback for {country_code}")
                try:
                    support_url = "https://support.apple.com/zh-cn/108047"
                    support_response = await client.get(support_url, timeout=15)
                    if support_response.status_code == 200:
                        support_content = support_response.text
                        logger.info(f"Successfully fetched Apple Support fallback page")
                        prices = get_icloud_prices_from_html(support_content)
                        if prices:
                            logger.info(f"Successfully parsed {len(prices)} countries from Apple Support page")
                except Exception as support_error:
                    logger.error(f"Apple Support fallback failed: {support_error}")
            
            country_name = country_info["name"]
            
            # Find matching country data
            matched_country = None
            for name in prices.keys():
                # Remove footnote numbers and superscript for better matching
                clean_name = re.sub(r'[0-9,\s]+$', '', name).strip()
                # Use exact matching first, then fallback to substring matching
                if (country_name == clean_name or 
                    clean_name == country_name):
                    matched_country = name
                    logger.info(f"Exact matched country: '{country_name}' -> '{name}'")
                    break
                elif (country_name in name and 
                      len(country_name) > 2 and  # Avoid short matches like "美" matching "美国" 
                      not any(other_clean for other_clean in [re.sub(r'[0-9,\s]+$', '', other_name).strip() 
                                                              for other_name in prices.keys() 
                                                              if other_name != name] 
                             if country_name in other_clean and other_clean != clean_name)):
                    matched_country = name
                    logger.info(f"Substring matched country: '{country_name}' -> '{name}'")
                    break
            
            if not matched_country:
                # Final fallback: try Apple Support page if we haven't already
                if "support.apple.com" not in url:
                    logger.info(f"Final fallback attempt: fetching Apple Support page for {country_code}")
                    try:
                        support_url = "https://support.apple.com/zh-cn/108047"
                        support_response = await client.get(support_url, timeout=15)
                        if support_response.status_code == 200:
                            support_content = support_response.text
                            support_prices = get_icloud_prices_from_html(support_content)
                            if support_prices:
                                logger.info(f"Successfully got fallback data from Apple Support page")
                                prices = support_prices
                                # Re-check for matching country
                                for name in prices.keys():
                                    clean_name = re.sub(r'[0-9,\s]+$', '', name).strip()
                                    # Use exact matching first
                                    if (country_name == clean_name or 
                                        clean_name == country_name):
                                        matched_country = name
                                        logger.info(f"Fallback exact matched country: '{country_name}' -> '{name}'")
                                        break
                                    elif (country_name in name and 
                                          len(country_name) > 2 and
                                          not any(other_clean for other_clean in [re.sub(r'[0-9,\s]+$', '', other_name).strip() 
                                                                                  for other_name in prices.keys() 
                                                                                  if other_name != name] 
                                                 if country_name in other_clean and other_clean != clean_name)):
                                        matched_country = name
                                        logger.info(f"Fallback substring matched country: '{country_name}' -> '{name}'")
                                        break
                    except Exception as support_error:
                        logger.error(f"Final fallback failed: {support_error}")
                
                if not matched_country:
                    result_lines.append(f"{service_display_name} 服务在该国家/地区不可用。")
            else:
                size_order = ["5GB", "50GB", "200GB", "2TB", "6TB", "12TB"]
                country_prices = prices[matched_country]["prices"]
                for size in size_order:
                    if size in country_prices:
                        price = country_prices[size]
                        # Normalize pricing text to Chinese for consistent display
                        normalized_price = normalize_pricing_text(price)
                        line = f"{size}: {normalized_price}"
                        
                        # Don't convert free plans or CNY prices
                        if country_code != "CN" and normalized_price != "免费":
                            cny_price_str = await convert_price_to_cny(price, country_code, context)
                            line += cny_price_str
                        result_lines.append(line)
                    else:
                        logger.warning(f"{size} plan not found for {country_name}")

        elif service == "appleone":
            soup = BeautifulSoup(content, "html.parser")
            plans = soup.find_all("div", class_="plan-tile")
            logger.info(f"Found {len(plans)} Apple One plans for {country_code}")

            if not plans:
                result_lines.append(f"{service_display_name} 服务在该国家/地区不可用。")
            else:
                is_first_plan = True
                for plan in plans:
                    if not is_first_plan:
                        result_lines.append("")
                    else:
                        is_first_plan = False

                    name = plan.find("h3", class_="typography-plan-headline")
                    price_element = plan.find("p", class_="typography-plan-subhead")

                    if name and price_element:
                        name_text = name.get_text(strip=True)
                        price = price_element.get_text(strip=True)
                        price = price.replace("per month", "").replace("/month", "").replace("/mo.", "").strip()
                        line = f"• {name_text}: {price}"
                        if country_code != "CN":
                            cny_price_str = await convert_price_to_cny(price, country_code, context)
                            line += cny_price_str
                        result_lines.append(line)

                        services = plan.find_all("li", class_="service-item")
                        for service_item in services:
                            service_name = service_item.find("span", class_="visuallyhidden")
                            service_price = service_item.find("span", class_="cost")

                            if service_name and service_price:
                                service_name_text = service_name.get_text(strip=True)
                                service_price_text = service_price.get_text(strip=True)
                                service_price_text = (
                                    service_price_text.replace("per month", "")
                                    .replace("/month", "")
                                    .replace("/mo.", "")
                                    .strip()
                                )
                                service_line = f"  - {service_name_text}: {service_price_text}"
                                if country_code != "CN":
                                    cny_price_str = await convert_price_to_cny(
                                        service_price_text, country_code, context
                                    )
                                    service_line += cny_price_str
                                result_lines.append(service_line)

        elif service == "applemusic":
            soup = BeautifulSoup(content, "html.parser")
            plans_section = soup.find("section", class_="section-plans")

            if not plans_section or not isinstance(plans_section, Tag):
                result_lines.append(f"{service_display_name} 服务在该国家/地区不可用。")
            elif country_code == "CN":
                logger.info("Applying CN-specific parsing for Apple Music.")

                # Try new gallery-based structure first (2024+ layout)
                gallery_items = plans_section.select("li.gallery-item")
                parsed_any = False

                if gallery_items:
                    logger.info(f"Found {len(gallery_items)} gallery items (new layout)")
                    # Extract student price from FAQ if available
                    student_price = None
                    faq_section = soup.find("section", class_="section-faq")
                    if faq_section:
                        faq_text = faq_section.get_text()
                        student_match = re.search(r'学生.*?每月仅需\s*(RMB\s*\d+)', faq_text)
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
                            price_match = re.search(r'(RMB\s*\d+)/月', price_text)
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
                            plan_name = plan_name_tag.get_text(strip=True).replace("4", "").strip()
                            price_str = price_tag.get_text(strip=True)
                            result_lines.append(f"• 学生计划: {price_str}")

                    individual_plan_item = plans_section.select_one("div.plan-list-item.individual")
                    if individual_plan_item and isinstance(individual_plan_item, Tag):
                        plan_name_tag = individual_plan_item.select_one("p.plan-type:not(.cost)")
                        price_tag = individual_plan_item.select_one("p.cost")
                        if plan_name_tag and price_tag:
                            plan_name = plan_name_tag.get_text(strip=True)
                            price_str = price_tag.get_text(strip=True)
                            result_lines.append(f"• 个人计划: {price_str}")

                    family_plan_item = plans_section.select_one("div.plan-list-item.family")
                    if family_plan_item and isinstance(family_plan_item, Tag):
                        plan_name_tag = family_plan_item.select_one("p.plan-type:not(.cost)")
                        price_tag = family_plan_item.select_one("p.cost")
                        if plan_name_tag and price_tag:
                            plan_name = plan_name_tag.get_text(strip=True).replace("5", "").strip()
                            price_str = price_tag.get_text(strip=True)
                            result_lines.append(f"• 家庭计划: {price_str}")
            else:
                logger.info(f"Applying standard parsing for Apple Music ({country_code}).")

                # Try new gallery-based structure first (2024+ layout)
                gallery_items = plans_section.select("li.gallery-item")
                parsed_any = False

                if gallery_items:
                    logger.info(f"Found {len(gallery_items)} gallery items for {country_code} (new layout)")

                    # Map of plan IDs to Chinese names
                    plan_name_map = {
                        "student": "学生",
                        "individual": "个人",
                        "voice": "Voice",
                        "family": "家庭"
                    }

                    for item in gallery_items:
                        # Get plan ID from item's id attribute
                        plan_id = item.get("id", "")
                        plan_name_elem = item.select_one("h3.tile-eyebrow")
                        price_elem = item.select_one("p.tile-headline")

                        if plan_name_elem and price_elem:
                            # Use mapped Chinese name if available, otherwise use extracted name
                            plan_name = plan_name_map.get(plan_id, plan_name_elem.get_text(strip=True))
                            price_text = price_elem.get_text(strip=True)

                            # Extract the main price, handling various formats
                            # Examples: "₹119/month", "月額1,080円。新規登録すると、最初の1か月間無料。", "RM 16.90/month"
                            price_match = re.search(r'(RM\s*[\d,]+(?:\.\d+)?(?:/month|/mo)?|[¥₹$€£₩₦]\s*[\d,]+(?:\.\d+)?(?:/month|/年|/月)?|月額\s*[\d,]+円|[\d,]+(?:\.\d+)?\s*(?:TL|USD|EUR|GBP|JPY|INR|KRW|NGN|BRL|CAD|AUD|NZD|HKD|SGD|PHP|ILS|PKR|kr|RUB|PLN|CZK|HUF)(?:/month|/mo)?)', price_text)

                            if price_match:
                                price_str = price_match.group(1).strip()
                                # Clean up common suffixes
                                price_str = re.sub(r'/month|/mo\.?|。.*$', '', price_str, flags=re.IGNORECASE).strip()

                                line = f"• {plan_name}计划: {price_str}"
                                if country_code != "CN":
                                    cny_price_str = await convert_price_to_cny(price_str, country_code, context)
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
                            plan_name_tag = item.select_one("p.plan-type:not(.cost), h3, h4, .plan-title, .plan-name")
                            plan_name_extracted = (
                                plan_name_tag.get_text(strip=True).replace("プラン", "").strip()
                                if plan_name_tag
                                else plan_type.capitalize()
                            )

                            price_tag = item.select_one("p.cost span, p.cost, .price, .plan-price")
                            if price_tag:
                                price_str = price_tag.get_text(strip=True)
                                price_str = re.sub(
                                    r"\s*/\s*(月|month|mo\\.?).*", "", price_str, flags=re.IGNORECASE
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
                                cny_price_str = await convert_price_to_cny(price_str, country_code, context)
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

                        plan_name_tag = item.select_one("p.plan-type:not(.cost), h3, h4, .plan-title, .plan-name")
                        plan_name = (
                            plan_name_tag.get_text(strip=True).replace("プラン", "").strip()
                            if plan_name_tag
                            else "未知计划"
                        )

                        price_tag = item.select_one("p.cost span, p.cost, .price, .plan-price")
                        if price_tag:
                            price_str = price_tag.get_text(strip=True)
                            price_str = re.sub(r"\s*/\s*(月|month).*", "", price_str, flags=re.IGNORECASE).strip()

                            line = f"• {plan_name}: {price_str}"
                            cny_price_str = await convert_price_to_cny(price_str, country_code, context)
                            line += cny_price_str
                            result_lines.append(line)

        # Only join if there are actual price details beyond the header
        if len(result_lines) > 1:
            final_result_str = "\n".join(result_lines)
            await cache_manager.save_cache(cache_key, final_result_str, subdirectory="apple_services")
            return final_result_str
        else:
            # Return the single line message (e.g., "Not Available") without caching
            return result_lines[0]

    except Exception as e:
        logger.error(f"Error parsing content for {country_code}, service {service}: {e}")
        return f"📍 国家/地区: {flag_emoji} {country_info['name']}\n获取价格信息失败: {e!s}."


async def apple_services_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /aps command to query Apple service prices."""
    if not update.message or not update.effective_chat:
        return

    args = context.args
    if not args:
        help_message = (
            "🍎 *Apple 服务价格查询*\n\n"
            "**使用方法:**\n"
            "`/aps <服务类型> [国家/地区...]`\n\n"
            "**支持的服务类型:**\n"
            "• `icloud` - iCloud 存储价格\n"
            "• `appleone` - Apple One 套餐价格\n"
            "• `applemusic` - Apple Music 订阅价格\n\n"
            "**使用示例:**\n"
            "`/aps icloud` - 查询默认地区 iCloud 价格\n"
            "`/aps applemusic US JP CN` - 查询美国、日本、中国的 Apple Music 价格\n"
            "`/aps appleone 中国 美国` - 支持中文国家名称\n\n"
            "💡 不指定国家时使用默认地区：中国、尼日利亚、土耳其、日本、印度、马来西亚"
        )
        await send_help(context, update.effective_chat.id, foldable_text_with_markdown_v2(help_message), parse_mode="MarkdownV2")
        await delete_user_command(context, update.effective_chat.id, update.message.message_id)
        return

    loading_message = "🔍 正在查询中... ⏳"
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id, text=foldable_text_v2(loading_message), parse_mode="MarkdownV2"
    )

    # Handle cache clearing
    if args[0].lower() == "clean":
        try:
            context.bot_data["cache_manager"].clear_cache(subdirectory="apple_services")
            cache_message = "Apple 服务价格缓存已清理。"
            await message.delete()
            await send_success(context, update.effective_chat.id, foldable_text_v2(cache_message), parse_mode="MarkdownV2")
            return
        except Exception as e:
            logger.error(f"Error clearing Apple Services cache: {e}")
            error_message = f"清理缓存时发生错误: {e!s}"
            await message.delete()
            await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
            await delete_user_command(context, update.effective_chat.id, update.message.message_id)
            return

    service = args[0].lower()
    if service not in ["icloud", "appleone", "applemusic"]:
        invalid_service_message = "无效的服务类型，请使用 iCloud, Apple One 或 AppleMusic"
        await message.delete()
        await send_error(context, update.effective_chat.id, foldable_text_v2(invalid_service_message), parse_mode="MarkdownV2")
        await delete_user_command(context, update.effective_chat.id, update.message.message_id)
        return

    try:
        countries = parse_countries_from_args(args[1:])

        display_name = ""
        if service == "icloud":
            display_name = "iCloud"
        elif service == "appleone":
            display_name = "Apple One"
        else:  # service == "applemusic"
            display_name = "Apple Music"

        tasks = []
        for country in countries:
            url = ""
            if service == "icloud":
                if country == "US":
                    # For US, use the base URL without country code
                    url = "https://www.apple.com/icloud/"
                elif country == "CN":
                    # For China, use .cn domain
                    url = "https://www.apple.com.cn/icloud/"
                else:
                    # For other countries, use country code format like Apple One
                    url = f"https://www.apple.com/{country.lower()}/icloud/"
            elif country == "US":
                # For US, use the base URL without country code
                url = f"https://www.apple.com/{service}/"
            elif country == "CN" and service == "appleone":
                url = "https://www.apple.com.cn/apple-one/"
            elif country == "CN" and service == "applemusic":
                url = "https://www.apple.com.cn/apple-music/"
            else:
                url = f"https://www.apple.com/{country.lower()}/{service}/"
            tasks.append(get_service_info(url, country, service, context))

        country_results = await asyncio.gather(*tasks)

        # 组装原始文本消息 (使用新的格式化模式)
        raw_message_parts = []
        raw_message_parts.append(f"*📱 {display_name} 价格信息*")
        raw_message_parts.append("")  # Empty line after header

        # 过滤有效结果并添加国家之间的空行分隔
        valid_results = [result for result in country_results if result]
        if valid_results:
            for i, result in enumerate(valid_results):
                raw_message_parts.append(result)
                # Add blank line between countries (except for the last one)
                if i < len(valid_results) - 1:
                    raw_message_parts.append("")
        else:
            raw_message_parts.append("所有查询地区均无此服务。")

        # Join and apply formatting using foldable_text_with_markdown_v2
        raw_final_message = "\n".join(raw_message_parts).strip()

        await message.edit_text(
            foldable_text_with_markdown_v2(raw_final_message), parse_mode="MarkdownV2", disable_web_page_preview=True
        )

        # 调度删除机器人回复消息，使用配置的延迟时间
        from utils.message_manager import _schedule_deletion
        config = get_config()
        await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)
        
        # 删除用户命令
        await delete_user_command(context, update.effective_chat.id, update.message.message_id)

    except Exception as e:
        logger.error(f"Error in apple_services_command: {e}")
        error_message = f"查询失败: {e!s}"
        await message.delete()
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        await delete_user_command(context, update.effective_chat.id, update.message.message_id)


async def apple_services_clean_cache_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /aps_cleancache command to clear Apple Services related caches."""
    if not update.message or not update.effective_chat:
        return
    try:
        context.bot_data["cache_manager"].clear_cache(subdirectory="apple_services")
        success_message = "✅ Apple 服务价格缓存已清理。"
        await send_success(context, update.effective_chat.id, foldable_text_v2(success_message), parse_mode="MarkdownV2")
        await delete_user_command(context, update.effective_chat.id, update.message.message_id)
        return
    except Exception as e:
        logger.error(f"Error clearing Apple Services cache: {e}")
        error_message = f"❌ 清理Apple Services缓存时发生错误: {e!s}"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        await delete_user_command(context, update.effective_chat.id, update.message.message_id)
        return


# Register the commands
command_factory.register_command(
    "aps",
    apple_services_command,
    permission=Permission.USER,
    description="查询Apple服务价格 (iCloud, Apple One, Apple Music)",
)
# 已迁移到统一缓存管理命令 /cleancache
# command_factory.register_command(
#     "aps_cleancache", apple_services_clean_cache_command, permission=Permission.ADMIN, description="清理Apple服务缓存"
# )


# =============================================================================
# Inline 执行入口
# =============================================================================

async def _get_service_info_inline(url: str, country_code: str, service: str) -> str:
    """
    Inline 专用的服务信息获取函数（不依赖 context，不使用缓存）
    支持 iCloud fallback 到 Apple Support 页面
    """
    country_info = SUPPORTED_COUNTRIES.get(country_code)
    if not country_info:
        return "不支持的国家/地区"

    flag_emoji = get_country_flag(country_code)
    service_display_name = {"icloud": "iCloud", "appleone": "Apple One", "applemusic": "Apple Music"}.get(
        service, service
    )

    try:
        from utils.http_client import get_http_client

        client = get_http_client()
        response = await client.get(url, timeout=15)
        content = None

        if response.status_code == 404:
            # For iCloud, try fallback to Apple Support page
            if service == "icloud":
                logger.info(f"[Inline] Attempting iCloud fallback to Apple Support page for {country_code}")
                support_url = "https://support.apple.com/zh-cn/108047"
                try:
                    fallback_response = await client.get(support_url, timeout=15)
                    if fallback_response.status_code == 200:
                        content = fallback_response.text
                        url = support_url
                        logger.info(f"[Inline] Successfully fetched fallback URL: {support_url}")
                    else:
                        return f"📍 国家/地区: {flag_emoji} {country_info['name']}\n{service_display_name} 服务在该国家/地区不可用。"
                except Exception as fallback_error:
                    logger.error(f"[Inline] Fallback request failed: {fallback_error}")
                    return f"📍 国家/地区: {flag_emoji} {country_info['name']}\n{service_display_name} 服务在该国家/地区不可用。"
            else:
                return f"📍 国家/地区: {flag_emoji} {country_info['name']}\n{service_display_name} 服务在该国家/地区不可用。"
        else:
            response.raise_for_status()
            content = response.text

        if content is None:
            return f"📍 国家/地区: {flag_emoji} {country_info['name']}\n{service_display_name} 服务在该国家/地区不可用。"

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404 and service == "icloud":
            # Try fallback
            try:
                from utils.http_client import get_http_client
                client = get_http_client()
                support_url = "https://support.apple.com/zh-cn/108047"
                fallback_response = await client.get(support_url, timeout=15)
                if fallback_response.status_code == 200:
                    content = fallback_response.text
                    url = support_url
                else:
                    return f"📍 国家/地区: {flag_emoji} {country_info['name']}\n{service_display_name} 服务在该国家/地区不可用。"
            except:
                return f"📍 国家/地区: {flag_emoji} {country_info['name']}\n{service_display_name} 服务在该国家/地区不可用。"
        else:
            return f"📍 国家/地区: {flag_emoji} {country_info['name']}\n获取价格信息失败: 网络错误 (HTTP {e.response.status_code})。"
    except Exception as e:
        logger.error(f"[Inline] Error for {country_code}, service {service}: {e}")
        return f"📍 国家/地区: {flag_emoji} {country_info['name']}\n获取价格信息失败: {e!s}."

    # 解析价格信息
    try:
        result_lines = [f"📍 国家/地区: {flag_emoji} {country_info['name']}"]
        country_name = country_info["name"]

        if service == "icloud":
            # Try to parse as Apple website first (for country-specific URLs)
            prices = get_icloud_prices_from_apple_website(content, country_code)

            # Fallback to legacy Apple Support page format if no prices found
            if not prices:
                prices = get_icloud_prices_from_html(content)

            # If still no prices and we're not already using Apple Support, try fallback
            if not prices and "support.apple.com" not in url:
                logger.info(f"[Inline] No prices found, attempting Apple Support fallback for {country_code}")
                try:
                    support_url = "https://support.apple.com/zh-cn/108047"
                    support_response = await client.get(support_url, timeout=15)
                    if support_response.status_code == 200:
                        support_content = support_response.text
                        logger.info(f"[Inline] Successfully fetched Apple Support fallback page")
                        prices = get_icloud_prices_from_html(support_content)
                        if prices:
                            logger.info(f"[Inline] Successfully parsed {len(prices)} countries from Apple Support page")
                except Exception as support_error:
                    logger.error(f"[Inline] Apple Support fallback failed: {support_error}")

            # Find matching country data (key is country NAME, not code!)
            matched_country = None
            for name in prices.keys():
                # Remove footnote numbers and superscript for better matching
                clean_name = re.sub(r'[0-9,\s]+$', '', name).strip()
                # Use exact matching first, then fallback to substring matching
                if (country_name == clean_name or
                    clean_name == country_name):
                    matched_country = name
                    logger.info(f"[Inline] Exact matched country: '{country_name}' -> '{name}'")
                    break
                elif (country_name in name and
                      len(country_name) > 2 and  # Avoid short matches like "美" matching "美国"
                      not any(other_clean for other_clean in [re.sub(r'[0-9,\s]+$', '', other_name).strip()
                                                              for other_name in prices.keys()
                                                              if other_name != name]
                             if country_name in other_clean and other_clean != clean_name)):
                    matched_country = name
                    logger.info(f"[Inline] Substring matched country: '{country_name}' -> '{name}'")
                    break

            if not matched_country:
                # Final fallback: try Apple Support page if we haven't already
                if "support.apple.com" not in url:
                    logger.info(f"[Inline] Final fallback attempt: fetching Apple Support page for {country_code}")
                    try:
                        support_url = "https://support.apple.com/zh-cn/108047"
                        support_response = await client.get(support_url, timeout=15)
                        if support_response.status_code == 200:
                            support_content = support_response.text
                            support_prices = get_icloud_prices_from_html(support_content)
                            if support_prices:
                                logger.info(f"[Inline] Successfully got fallback data from Apple Support page")
                                prices = support_prices
                                # Re-check for matching country
                                for name in prices.keys():
                                    clean_name = re.sub(r'[0-9,\s]+$', '', name).strip()
                                    # Use exact matching first
                                    if (country_name == clean_name or
                                        clean_name == country_name):
                                        matched_country = name
                                        logger.info(f"[Inline] Fallback exact matched country: '{country_name}' -> '{name}'")
                                        break
                                    elif (country_name in name and
                                          len(country_name) > 2 and
                                          not any(other_clean for other_clean in [re.sub(r'[0-9,\s]+$', '', other_name).strip()
                                                                                  for other_name in prices.keys()
                                                                                  if other_name != name]
                                                 if country_name in other_clean and other_clean != clean_name)):
                                        matched_country = name
                                        logger.info(f"[Inline] Fallback substring matched country: '{country_name}' -> '{name}'")
                                        break
                    except Exception as support_error:
                        logger.error(f"[Inline] Final fallback failed: {support_error}")

                if not matched_country:
                    result_lines.append(f"{service_display_name} 服务在该国家/地区不可用。")
            else:
                size_order = ["5GB", "50GB", "200GB", "2TB", "6TB", "12TB"]
                country_prices = prices[matched_country]["prices"]
                for size in size_order:
                    if size in country_prices:
                        price = country_prices[size]
                        # Normalize pricing text to Chinese for consistent display
                        normalized_price = normalize_pricing_text(price)
                        line = f"{size}: {normalized_price}"

                        # Convert to CNY (inline version without context)
                        if country_code != "CN" and normalized_price != "免费":
                            cny_price_str = await _convert_price_to_cny_inline(price, country_code)
                            line += cny_price_str
                        result_lines.append(line)

        elif service == "appleone":
            soup = BeautifulSoup(content, "html.parser")
            plans = soup.find_all("div", class_="plan-tile")
            logger.info(f"[Inline] Found {len(plans)} Apple One plans for {country_code}")

            if not plans:
                result_lines.append(f"{service_display_name} 服务在该国家/地区不可用。")
            else:
                is_first_plan = True
                for plan in plans:
                    if not is_first_plan:
                        result_lines.append("")
                    else:
                        is_first_plan = False

                    name = plan.find("h3", class_="typography-plan-headline")
                    price_element = plan.find("p", class_="typography-plan-subhead")

                    if name and price_element:
                        name_text = name.get_text(strip=True)
                        price = price_element.get_text(strip=True)
                        price = price.replace("per month", "").replace("/month", "").replace("/mo.", "").strip()
                        line = f"• {name_text}: {price}"
                        if country_code != "CN":
                            cny_price_str = await _convert_price_to_cny_inline(price, country_code)
                            line += cny_price_str
                        result_lines.append(line)

                        # 子服务列表
                        services = plan.find_all("li", class_="service-item")
                        for service_item in services:
                            service_name = service_item.find("span", class_="visuallyhidden")
                            service_price = service_item.find("span", class_="cost")

                            if service_name and service_price:
                                service_name_text = service_name.get_text(strip=True)
                                service_price_text = service_price.get_text(strip=True)
                                service_price_text = (
                                    service_price_text.replace("per month", "")
                                    .replace("/month", "")
                                    .replace("/mo.", "")
                                    .strip()
                                )
                                service_line = f"  - {service_name_text}: {service_price_text}"
                                if country_code != "CN":
                                    cny_price_str = await _convert_price_to_cny_inline(
                                        service_price_text, country_code
                                    )
                                    service_line += cny_price_str
                                result_lines.append(service_line)

        elif service == "applemusic":
            soup = BeautifulSoup(content, "html.parser")
            plans_section = soup.find("section", class_="section-plans")

            if not plans_section or not isinstance(plans_section, Tag):
                result_lines.append(f"{service_display_name} 服务在该国家/地区不可用。")
            else:
                # Try new gallery-based structure first (2024+ layout)
                gallery_items = plans_section.select("li.gallery-item")
                parsed_any = False

                if gallery_items:
                    logger.info(f"[Inline] Found {len(gallery_items)} gallery items for {country_code}")
                    plan_name_map = {"student": "学生", "individual": "个人", "voice": "Voice", "family": "家庭"}

                    for item in gallery_items:
                        plan_id = item.get("id", "")
                        plan_name_elem = item.select_one("h3.tile-eyebrow")
                        price_elem = item.select_one("p.tile-headline")

                        if plan_name_elem and price_elem:
                            plan_name = plan_name_map.get(plan_id, plan_name_elem.get_text(strip=True))
                            price_text = price_elem.get_text(strip=True)

                            price_match = re.search(r'([¥₹$€£₩₦]\s*[\d,]+(?:\.\d+)?(?:/month|/年|/月)?|月額\s*[\d,]+円|[\d,]+(?:\.\d+)?\s*(?:TL|RM|USD|EUR|GBP|JPY|INR|KRW|NGN|BRL|CAD|AUD|NZD|HKD|SGD|PHP|ILS|PKR|kr|RUB|PLN|CZK|HUF)(?:/month|/mo)?|RMB\s*\d+)', price_text)

                            if price_match:
                                price_str = price_match.group(1).strip()
                                price_str = re.sub(r'/month|/mo\.?|。.*$', '', price_str, flags=re.IGNORECASE).strip()

                                line = f"• {plan_name}计划: {price_str}"
                                if country_code != "CN":
                                    cny_price_str = await _convert_price_to_cny_inline(price_str, country_code)
                                    line += cny_price_str
                                result_lines.append(line)
                                parsed_any = True

                # Fallback to old plan-list-item structure
                if not parsed_any:
                    logger.info(f"[Inline] Falling back to old plan-list-item structure for {country_code}")
                    plan_order = ["student", "individual", "family"]
                    processed_plans = set()

                    for plan_type in plan_order:
                        item = plans_section.select_one(f"div.plan-list-item.{plan_type}")
                        if item and isinstance(item, Tag) and plan_type not in processed_plans:
                            price_tag = item.select_one("p.cost span, p.cost, .price, .plan-price")
                            if price_tag:
                                price_str = price_tag.get_text(strip=True)
                                price_str = re.sub(r"\s*/\s*(月|month|mo\\.?).*", "", price_str, flags=re.IGNORECASE).strip()

                                if plan_type == "student":
                                    plan_name = "学生"
                                elif plan_type == "individual":
                                    plan_name = "个人"
                                elif plan_type == "family":
                                    plan_name = "家庭"
                                else:
                                    plan_name = plan_type.capitalize()

                                line = f"• {plan_name}计划: {price_str}"
                                if country_code != "CN":
                                    cny_price_str = await _convert_price_to_cny_inline(price_str, country_code)
                                    line += cny_price_str
                                result_lines.append(line)
                                processed_plans.add(plan_type)

        return "\n".join(result_lines)

    except Exception as e:
        logger.error(f"[Inline] Error parsing prices for {country_code}: {e}")
        return f"📍 国家/地区: {flag_emoji} {country_info['name']}\n解析价格信息失败: {e!s}."


async def _convert_price_to_cny_inline(price: str, country_code: str) -> str:
    """Inline 专用的价格转换函数（不依赖 context）"""
    country_info = SUPPORTED_COUNTRIES.get(country_code)
    if not country_info:
        return ""

    # 使用 extract_currency_and_price 来检测实际货币
    from utils.price_parser import extract_currency_and_price
    detected_currency, price_value = extract_currency_and_price(price, country_code)

    if price_value is None or price_value <= 0:
        return ""

    from commands.rate_command import convert_currency_with_fallback
    cny_price = await convert_currency_with_fallback(price_value, detected_currency, "CNY")
    if cny_price is not None:
        return f" ≈ ¥{cny_price:.2f} CNY"
    else:
        return ""


async def appleservices_inline_execute(args: str) -> dict:
    """
    Inline Query 执行入口 - 提供完整的 Apple 服务价格查询功能

    Args:
        args: 用户输入的参数字符串，如 "icloud" 或 "appleone US"

    Returns:
        dict: {
            "success": bool,
            "title": str,
            "message": str,
            "description": str,
            "error": str | None
        }
    """
    import asyncio

    if not args or not args.strip():
        # 无参数：显示帮助信息
        return {
            "success": False,
            "title": "❌ 请指定服务类型",
            "message": "请提供服务类型\\n\\n*可用服务:*\\n• `appleservices icloud` \\\\- iCloud 价格\\n• `appleservices appleone` \\\\- Apple One 套餐\\n• `appleservices applemusic` \\\\- Apple Music 价格\\n\\n*可选国家:*\\n添加国家代码查询特定地区，如: `appleservices icloud US CN JP`",
            "description": "请指定服务类型: icloud, appleone, applemusic",
            "error": "未提供服务类型"
        }

    try:
        parts = args.strip().split()
        service = parts[0].lower()

        if service not in ["icloud", "appleone", "applemusic"]:
            return {
                "success": False,
                "title": "❌ 无效的服务类型",
                "message": f"无效的服务类型: `{service}`\\n\\n*可用服务:*\\n• `icloud` \\\\- iCloud 存储\\n• `appleone` \\\\- Apple One 套餐\\n• `applemusic` \\\\- Apple Music",
                "description": "无效的服务类型",
                "error": "无效的服务类型"
            }

        # 解析国家参数
        countries = parse_countries_from_args(parts[1:]) if len(parts) > 1 else DEFAULT_COUNTRIES

        display_name = {"icloud": "iCloud", "appleone": "Apple One", "applemusic": "Apple Music"}.get(service, service)

        # 构建URL并获取数据（使用 inline 专用函数）
        tasks = []
        for country in countries:
            url = ""
            if service == "icloud":
                if country == "US":
                    url = "https://www.apple.com/icloud/"
                elif country == "CN":
                    url = "https://www.apple.com.cn/icloud/"
                else:
                    url = f"https://www.apple.com/{country.lower()}/icloud/"
            elif country == "US":
                url = f"https://www.apple.com/{service}/"
            elif country == "CN" and service == "appleone":
                url = "https://www.apple.com.cn/apple-one/"
            elif country == "CN" and service == "applemusic":
                url = "https://www.apple.com.cn/apple-music/"
            else:
                url = f"https://www.apple.com/{country.lower()}/{service}/"
            tasks.append(_get_service_info_inline(url, country, service))

        country_results = await asyncio.gather(*tasks)

        # 组装消息
        raw_message_parts = [f"*📱 {display_name} 价格信息*", ""]

        valid_results = [result for result in country_results if result]
        if valid_results:
            for i, result in enumerate(valid_results):
                raw_message_parts.append(result)
                if i < len(valid_results) - 1:
                    raw_message_parts.append("")
        else:
            raw_message_parts.append("所有查询地区均无此服务。")

        raw_final_message = "\n".join(raw_message_parts).strip()

        # 构建简短描述
        country_str = ", ".join(countries[:3])
        if len(countries) > 3:
            country_str += f" 等{len(countries)}个地区"

        return {
            "success": True,
            "title": f"📱 {display_name} 价格",
            "message": foldable_text_with_markdown_v2(raw_final_message),
            "description": f"{display_name} {country_str} 价格",
            "error": None
        }

    except Exception as e:
        logger.error(f"Inline Apple Services query failed: {e}")
        return {
            "success": False,
            "title": "❌ 查询失败",
            "message": f"查询 Apple 服务价格失败: {str(e)}",
            "description": "查询失败",
            "error": str(e)
        }
