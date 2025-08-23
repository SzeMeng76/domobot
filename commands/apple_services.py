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
    
    # Remove duplicate period indicators (e.g., "/monthper month")
    normalized_text = re.sub(r'/month\s*per month', '/month', normalized_text)
    normalized_text = re.sub(r'per month\s*/month', 'per month', normalized_text)
    
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

    price_value = extract_price_value_from_country_info(price, country_info)
    if price_value <= 0:
        return ""

    cny_price = await rate_converter.convert(price_value, country_info["currency"], "CNY")
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
    """Extracts iCloud prices from Apple Support HTML content (legacy Chinese support page)."""
    soup = BeautifulSoup(content, "html.parser")
    prices = {}

    paragraphs = soup.find_all("p", class_="gb-paragraph")
    current_country = None
    size_price_dict = {}
    currency = ""

    for p in paragraphs:
        text = p.get_text(strip=True)

        # Check if it's a country line
        if ("（" in text and "）" in text) or text.endswith("（港元）"):
            if current_country:
                prices[current_country] = {"currency": currency, "prices": size_price_dict}

            # Process country info
            if text.endswith("（港元）"):
                current_country = "香港"
                currency = "港元"
                size_price_dict = {}
            elif "（" in text and "）" in text:
                country_match = re.match(r"^(.*?)（(.*?)）", text)
                if country_match:
                    current_country = country_match.group(1)
                    currency = country_match.group(2)
                    size_price_dict = {}

        # Check if it's a price line
        else:
            # Find size and price
            size = p.find("b")
            if size:
                # Get full size text
                size_text = size.get_text(strip=True)
                # Remove colons (full-width and half-width)
                size_text = size_text.replace("：", "").replace(":", "").strip()

                # Get full price text
                price_text = text
                if "：" in price_text:
                    price = price_text.split("：")[-1].strip()
                elif ":" in price_text:
                    price = price_text.split(":")[-1].strip()
                else:
                    # If no colon, extract number part
                    match = re.search(r"HK\$\s*(\d+)", price_text)
                    if match:
                        price = f"HK$ {match.group(1)}"
                    else:
                        continue

                size_price_dict[size_text] = price

    # Save data for the last country
    if current_country:
        prices[current_country] = {"currency": currency, "prices": size_price_dict}

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
                    "ayda" in price_text.lower() or "月" in price_text
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
                            "ayda" in span_text.lower() or "月" in span_text
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
                if country_name in name or name in country_name or name == country_name:
                    matched_country = name
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
                                    if country_name in name or name in country_name or name == country_name:
                                        matched_country = name
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
