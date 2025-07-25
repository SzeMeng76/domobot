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
    """Extracts iCloud prices from Apple Support HTML content."""
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

        if response.status_code == 404:
            logger.info(f"{service} not available in {country_code} (404).")
            return f"📍 国家/地区: {flag_emoji} {country_info['name']}\n{service_display_name} 服务在该国家/地区不可用。"

        response.raise_for_status()
        content = response.text
        logger.info(f"Successfully fetched URL: {url}")

    except httpx.HTTPStatusError as e:
        logger.error(f"Network error for {url}: {e}")
        if e.response.status_code == 404:
            return (
                f"📍 国家/地区: {flag_emoji} {country_info['name']}\n{service_display_name} 服务在该国家/地区不可用。"
            )
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
            prices = get_icloud_prices_from_html(content)
            country_name = country_info["name"]

            matched_country = None
            for name in prices.keys():
                if country_name in name or name in country_name:
                    matched_country = name
                    break

            if not matched_country:
                result_lines.append(f"{service_display_name} 服务在该国家/地区不可用。")
            else:
                size_order = ["50GB", "200GB", "2TB", "6TB", "12TB"]
                country_prices = prices[matched_country]["prices"]
                for size in size_order:
                    if size in country_prices:
                        price = country_prices[size]
                        line = f"{size}: {price}"
                        if country_code != "CN":
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
            return

    service = args[0].lower()
    if service not in ["icloud", "appleone", "applemusic"]:
        invalid_service_message = "无效的服务类型，请使用 iCloud, Apple One 或 AppleMusic"
        await message.delete()
        await send_error(context, update.effective_chat.id, foldable_text_v2(invalid_service_message), parse_mode="MarkdownV2")
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
                # iCloud has a universal URL for all regions
                url = "https://support.apple.com/zh-cn/108047"
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
command_factory.register_command(
    "aps_cleancache", apple_services_clean_cache_command, permission=Permission.ADMIN, description="清理Apple服务缓存"
)
