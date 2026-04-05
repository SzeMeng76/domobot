# Description: Telegram bot command for electricity price lookup
# This module provides /electricity command to check electricity prices globally

import logging
from telegram import Update
from telegram.ext import ContextTypes

from utils.command_factory import command_factory
from utils.country_data import SUPPORTED_COUNTRIES, get_country_flag
from utils.formatter import foldable_text_v2, foldable_text_with_markdown_v2
from utils.message_manager import (
    delete_user_command,
    send_error,
    send_help,
    send_search_result,
)
from utils.permissions import Permission

logger = logging.getLogger(__name__)

# Dependencies
cache_manager = None
httpx_client = None


def set_dependencies(c_manager, h_client):
    """Set cache manager and httpx client dependencies"""
    global cache_manager, httpx_client
    cache_manager = c_manager
    httpx_client = h_client

# GitHub raw URL for electricity price data
GLOBAL_DATA_URL = "https://raw.githubusercontent.com/SzeMeng76/fuel-price-tracker/refs/heads/master/global_fuel_prices_processed.json"

# Mapping from GlobalPetrolPrices country codes to ISO 2-letter codes
COUNTRY_CODE_MAPPING = {
    "USA": "US",
    "Canada": "CA",
    "Mexico": "MX",
    "United-Kingdom": "GB",
    "United Kingdom": "GB",
    "Germany": "DE",
    "France": "FR",
    "Italy": "IT",
    "Spain": "ES",
    "Netherlands": "NL",
    "Belgium": "BE",
    "Switzerland": "CH",
    "Austria": "AT",
    "Sweden": "SE",
    "Norway": "NO",
    "Denmark": "DK",
    "Finland": "FI",
    "Poland": "PL",
    "Czech-Republic": "CZ",
    "Czech Republic": "CZ",
    "Hungary": "HU",
    "Romania": "RO",
    "Bulgaria": "BG",
    "Greece": "GR",
    "Portugal": "PT",
    "Ireland": "IE",
    "Croatia": "HR",
    "Slovenia": "SI",
    "Slovakia": "SK",
    "Estonia": "EE",
    "Latvia": "LV",
    "Lithuania": "LT",
    "Russia": "RU",
    "Ukraine": "UA",
    "Belarus": "BY",
    "Turkey": "TR",
    "China": "CN",
    "Japan": "JP",
    "South-Korea": "KR",
    "South Korea": "KR",
    "India": "IN",
    "Indonesia": "ID",
    "Thailand": "TH",
    "Vietnam": "VN",
    "Philippines": "PH",
    "Malaysia": "MY",
    "Singapore": "SG",
    "Hong-Kong": "HK",
    "Hong Kong": "HK",
    "Taiwan": "TW",
    "Australia": "AU",
    "New-Zealand": "NZ",
    "New Zealand": "NZ",
    "Brazil": "BR",
    "Argentina": "AR",
    "Chile": "CL",
    "Colombia": "CO",
    "Peru": "PE",
    "Venezuela": "VE",
    "Ecuador": "EC",
    "South-Africa": "ZA",
    "South Africa": "ZA",
    "Egypt": "EG",
    "Nigeria": "NG",
    "Kenya": "KE",
    "Saudi-Arabia": "SA",
    "Saudi Arabia": "SA",
    "United-Arab-Emirates": "AE",
    "United Arab Emirates": "AE",
    "Israel": "IL",
    "Pakistan": "PK",
    "Bangladesh": "BD",
    "Sri-Lanka": "LK",
    "Sri Lanka": "LK",
    "Cuba": "CU",
    "Ethiopia": "ET",
    "Bhutan": "BT",
    "Iraq": "IQ",
    "Angola": "AO",
    "Zambia": "ZM",
    "Laos": "LA",
    "Qatar": "QA",
    "Oman": "OM",
    "Cyprus": "CY",
    "Morocco": "MA",
    "Tunisia": "TN",
    "Algeria": "DZ",
    "Libya": "LY",
    "Sudan": "SD",
    "Ghana": "GH",
    "Tanzania": "TZ",
    "Uganda": "UG",
    "Zimbabwe": "ZW",
    "Mozambique": "MZ",
    "Madagascar": "MG",
    "Cameroon": "CM",
    "Senegal": "SN",
    "Bolivia": "BO",
    "Paraguay": "PY",
    "Uruguay": "UY",
    "Guatemala": "GT",
    "Costa-Rica": "CR",
    "Costa Rica": "CR",
    "Panama": "PA",
    "Honduras": "HN",
    "El-Salvador": "SV",
    "El Salvador": "SV",
    "Nicaragua": "NI",
    "Dominican-Republic": "DO",
    "Dominican Republic": "DO",
    "Jamaica": "JM",
    "Trinidad-and-Tobago": "TT",
    "Trinidad and Tobago": "TT",
    "Kuwait": "KW",
    "Bahrain": "BH",
    "Jordan": "JO",
    "Lebanon": "LB",
    "Syria": "SY",
    "Yemen": "YE",
    "Iran": "IR",
    "Kazakhstan": "KZ",
    "Uzbekistan": "UZ",
    "Azerbaijan": "AZ",
    "Georgia": "GE",
    "Armenia": "AM",
    "Mongolia": "MN",
    "Myanmar": "MM",
    "Cambodia": "KH",
    "Nepal": "NP",
    "Afghanistan": "AF",
    "Serbia": "RS",
    "Bosnia-and-Herzegovina": "BA",
    "Bosnia and Herzegovina": "BA",
    "Albania": "AL",
    "North-Macedonia": "MK",
    "North Macedonia": "MK",
    "Montenegro": "ME",
    "Moldova": "MD",
    "Luxembourg": "LU",
    "Malta": "MT",
    "Iceland": "IS",
}


async def fetch_electricity_data(url: str):
    """Fetch electricity price data from GitHub with cache"""
    try:
        # Try cache first
        cache_key = f"electricity_data_{url.split('/')[-1]}"
        if cache_manager:
            cached_data = await cache_manager.load_cache(cache_key, subdirectory="electricity")
            if cached_data:
                logger.info(f"Using cached electricity data for {cache_key}")
                return cached_data

        # Fetch from GitHub using httpx
        if not httpx_client:
            logger.error("httpx_client not initialized")
            return None

        response = await httpx_client.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()

            # Save to cache
            if cache_manager:
                await cache_manager.save_cache(cache_key, data, subdirectory="electricity")

            return data
        else:
            logger.error(f"Failed to fetch data: HTTP {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Error fetching electricity data: {e}")
        return None


def format_country_electricity(country: str, country_data: dict, all_data: dict = None) -> str:
    """Format electricity price information for a country"""
    text = f"⚡ *{country} 电价*\n\n"

    electricity = country_data.get('electricity')

    if not electricity:
        text += "暂无电价数据\n"
        return text

    # Households electricity
    households = electricity.get('households')
    if households:
        price = households.get('price', 0)
        currency = households.get('currency', 'USD')
        price_cny = households.get('price_cny', 0)
        local_price = households.get('local_price')
        local_currency = households.get('local_currency')

        text += f"🏠 *家庭用电:*\n"

        # Show local price if available
        if local_price and local_currency:
            text += f"  本地价格: `{local_price:.3f}` {local_currency}\\/kWh\n"

        text += f"  USD价格: `{price:.3f}` {currency}\\/kWh\n"
        text += f"  折合CNY: `{price_cny:.2f}` CNY\\/kWh\n"

        # Add ranking for households
        if all_data and price_cny > 0:
            households_data = [(code, info) for code, info in all_data.items()
                             if info.get('electricity') and info['electricity'].get('households')
                             and info['electricity']['households'].get('price_cny', 0) > 0]
            sorted_countries = sorted(households_data, key=lambda x: x[1]['electricity']['households']['price_cny'])
            prices = [info['electricity']['households']['price_cny'] for _, info in sorted_countries]
            avg_price = sum(prices) / len(prices) if prices else 0

            rank = next((i + 1 for i, (code, info) in enumerate(sorted_countries)
                        if info.get('country') == country), None)

            if rank:
                text += f"  📊 全球排名: 第 {rank}\\/{len(sorted_countries)} 位\n"
                diff = price_cny - avg_price
                if diff > 0:
                    text += f"  💸 比平均高 `{diff:.2f}` CNY\\/kWh\n"
                elif diff < 0:
                    text += f"  💚 比平均低 `{abs(diff):.2f}` CNY\\/kWh\n"

    # Business electricity
    business = electricity.get('business')
    if business:
        price = business.get('price', 0)
        currency = business.get('currency', 'USD')
        price_cny = business.get('price_cny', 0)
        local_price = business.get('local_price')
        local_currency = business.get('local_currency')

        text += f"\n🏢 *商业用电:*\n"

        # Show local price if available
        if local_price and local_currency:
            text += f"  本地价格: `{local_price:.3f}` {local_currency}\\/kWh\n"

        text += f"  USD价格: `{price:.3f}` {currency}\\/kWh\n"
        text += f"  折合CNY: `{price_cny:.2f}` CNY\\/kWh\n"

        # Add ranking for business
        if all_data and price_cny > 0:
            business_data = [(code, info) for code, info in all_data.items()
                           if info.get('electricity') and info['electricity'].get('business')
                           and info['electricity']['business'].get('price_cny', 0) > 0]
            sorted_countries = sorted(business_data, key=lambda x: x[1]['electricity']['business']['price_cny'])
            prices = [info['electricity']['business']['price_cny'] for _, info in sorted_countries]
            avg_price = sum(prices) / len(prices) if prices else 0

            rank = next((i + 1 for i, (code, info) in enumerate(sorted_countries)
                        if info.get('country') == country), None)

            if rank:
                text += f"  📊 全球排名: 第 {rank}\\/{len(sorted_countries)} 位\n"
                diff = price_cny - avg_price
                if diff > 0:
                    text += f"  💸 比平均高 `{diff:.2f}` CNY\\/kWh\n"
                elif diff < 0:
                    text += f"  💚 比平均低 `{abs(diff):.2f}` CNY\\/kWh\n"

    # Add data source and price date
    text += f"\n📅 *数据日期:* "
    price_date = None
    if households and households.get('price_date'):
        price_date = households.get('price_date')
    elif business and business.get('price_date'):
        price_date = business.get('price_date')

    if price_date:
        # Escape dots in date
        price_date_escaped = price_date.replace('.', '\\.')
        text += f"{price_date_escaped}\n"
    else:
        text += "未知\n"

    text += f"🔗 *数据来源:* [GlobalPetrolPrices\\.com](https://www\\.globalpetrolprices\\.com/)\n"

    return text


async def electricity_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /electricity command"""
    if not update.message:
        return

    # Parse arguments
    args = context.args

    if not args:
        # No args - show households electricity rankings
        await show_rankings(update, context, "households")
        return

    query = " ".join(args).lower()

    # Handle special commands
    if query.startswith("rankings") or query.startswith("rank") or query.startswith("排行") or query.startswith("top"):
        # Extract category if specified
        parts = query.split()
        category = parts[1] if len(parts) > 1 else "households"
        await show_rankings(update, context, category)
        return

    # Handle direct category queries
    if query in ["households", "家庭", "residential"]:
        await show_rankings(update, context, "households")
        return

    if query in ["business", "商业", "commercial"]:
        await show_rankings(update, context, "business")
        return

    # Search for specific country
    await search_electricity_price(update, context, args)


async def show_rankings(update: Update, context: ContextTypes.DEFAULT_TYPE, category: str = "households"):
    """Show global electricity price rankings for specified category"""
    if not update.message:
        return

    data = await fetch_electricity_data(GLOBAL_DATA_URL)

    if not data:
        await send_error(context, update.message.chat_id, "无法获取数据，请稍后重试", parse_mode="MarkdownV2")
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        return

    # Map category
    category_map = {
        "households": ("households", "🏠 家庭用电"),
        "家庭": ("households", "🏠 家庭用电"),
        "residential": ("households", "🏠 家庭用电"),
        "business": ("business", "🏢 商业用电"),
        "商业": ("business", "🏢 商业用电"),
        "commercial": ("business", "🏢 商业用电"),
    }

    category_key, category_name = category_map.get(category.lower(), ("households", "🏠 家庭用电"))

    # Filter valid data and sort by CNY price
    valid_data = [(code, info) for code, info in data.items()
                  if info.get('electricity') and info['electricity'].get(category_key)
                  and info['electricity'][category_key].get('price_cny', 0) > 0]

    if not valid_data:
        await send_error(context, update.message.chat_id, f"暂无{category_name}数据", parse_mode="MarkdownV2")
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        return

    # Sort by price
    sorted_data = sorted(valid_data, key=lambda x: x[1]['electricity'][category_key]['price_cny'])

    # Get cheapest and most expensive
    cheapest_10 = sorted_data[:10]
    expensive_10 = sorted_data[-10:][::-1]

    # Calculate average
    prices = [info['electricity'][category_key]['price_cny'] for _, info in valid_data]
    avg_price = sum(prices) / len(prices)

    # Format message
    text = f"⚡ *全球{category_name}价格排行榜*\n\n"

    text += "💚 *最便宜 Top 10:*\n"
    for i, (code, info) in enumerate(cheapest_10, 1):
        country = info['country']
        elec_info = info['electricity'][category_key]
        price_cny = elec_info['price_cny']
        price_orig = elec_info['price']
        currency = elec_info['currency']

        # Map to ISO code and get Chinese name and flag
        iso_code = COUNTRY_CODE_MAPPING.get(code, code)
        country_info = SUPPORTED_COUNTRIES.get(iso_code.upper(), {})
        country_name_cn = country_info.get('name', '')
        country_flag = get_country_flag(iso_code)

        # Format with Chinese name if available
        if country_name_cn:
            country_display = f"{country} \\({country_name_cn}\\) {country_flag}"
        else:
            country_display = country

        text += f"{i}\\. {country_display}: `{price_cny:.2f}` CNY\\/kWh \\(`{price_orig:.3f}` {currency}\\/kWh\\)\n"

    text += "\n💸 *最贵 Top 10:*\n"
    for i, (code, info) in enumerate(expensive_10, 1):
        country = info['country']
        elec_info = info['electricity'][category_key]
        price_cny = elec_info['price_cny']
        price_orig = elec_info['price']
        currency = elec_info['currency']

        # Map to ISO code and get Chinese name and flag
        iso_code = COUNTRY_CODE_MAPPING.get(code, code)
        country_info = SUPPORTED_COUNTRIES.get(iso_code.upper(), {})
        country_name_cn = country_info.get('name', '')
        country_flag = get_country_flag(iso_code)

        # Format with Chinese name if available
        if country_name_cn:
            country_display = f"{country} \\({country_name_cn}\\) {country_flag}"
        else:
            country_display = country

        text += f"{i}\\. {country_display}: `{price_cny:.2f}` CNY\\/kWh \\(`{price_orig:.3f}` {currency}\\/kWh\\)\n"

    text += f"\n📊 *全球平均价格:* `{avg_price:.2f}` CNY\\/kWh\n"
    text += f"📈 *价格范围:* `{min(prices):.2f}` \\- `{max(prices):.2f}` CNY\\/kWh\n"
    text += f"🌍 *覆盖国家:* {len(valid_data)} 个\n"

    # Add usage hint
    if category_key == "households":
        text += f"\n💡 *提示:* 使用 `/electricity rankings business` 查看商业用电排行\n"
    else:
        text += f"\n💡 *提示:* 使用 `/electricity rankings households` 查看家庭用电排行\n"

    text += f"🔍 *查询国家:* `/electricity <国家名>`\n"

    await send_search_result(context, update.message.chat_id, text, parse_mode="MarkdownV2")
    await delete_user_command(context, update.message.chat_id, update.message.message_id)


async def search_electricity_price(update: Update, context: ContextTypes.DEFAULT_TYPE, args: list):
    """Search for specific country electricity price - supports multiple countries"""
    if not update.message:
        return

    # Parse queries
    queries = [q.lower() for q in args]

    # Collect results
    results = []
    not_found = []

    global_data = await fetch_electricity_data(GLOBAL_DATA_URL)
    if not global_data:
        await send_error(context, update.message.chat_id, "无法获取数据，请稍后重试", parse_mode="MarkdownV2")
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        return

    for query in queries:
        found = False

        # Try matching with SUPPORTED_COUNTRIES first
        for country_code, country_info in SUPPORTED_COUNTRIES.items():
            country_name_cn = country_info.get('name', '').lower()

            if query == country_code.lower() or query in country_name_cn:
                # Find matching country in global data
                for json_code, elec_info in global_data.items():
                    iso_code = COUNTRY_CODE_MAPPING.get(json_code, json_code)
                    if iso_code.upper() == country_code:
                        results.append({
                            'data': elec_info,
                            'code': json_code,
                            'all_data': global_data
                        })
                        found = True
                        break
                if found:
                    break

        # Fallback: direct search
        if not found:
            for code, info in global_data.items():
                country = info.get('country', '').lower()
                if query in country or query in code.lower() or code.lower() == query:
                    results.append({
                        'data': info,
                        'code': code,
                        'all_data': global_data
                    })
                    found = True
                    break

        if not found:
            not_found.append(query)

    # Format results
    if not results:
        await send_error(
            context,
            update.message.chat_id,
            f"未找到 '{', '.join(queries)}' 的电价数据\n\n"
            "提示: 使用 /electricity 查看全球排行榜",
            parse_mode="MarkdownV2"
        )
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        return

    # Build message
    message_parts = []

    for result in results:
        country = result['data'].get('country', 'Unknown')
        text = format_country_electricity(country, result['data'], result['all_data'])
        message_parts.append(text)

    # Add not found notice
    if not_found:
        message_parts.append(f"\n❌ 未找到: {', '.join(not_found)}")

    final_message = "\n\n".join(message_parts)
    await send_search_result(context, update.message.chat_id, final_message, parse_mode="MarkdownV2")
    await delete_user_command(context, update.message.chat_id, update.message.message_id)


# Register command
command_factory.register_command("electricity", electricity_command, permission=Permission.NONE, description="⚡ 查询全球电价（家庭+商业）")
command_factory.register_command("elec", electricity_command, permission=Permission.NONE, description="⚡ 查询全球电价（简写）")


# =============================================================================
# Inline 执行入口
# =============================================================================

async def electricity_inline_execute(args: str) -> dict:
    """
    Inline Query 执行入口 - 提供完整的 electricity 价格查询功能

    Args:
        args: 用户输入的参数字符串，如 "au" 或 "澳大利亚" 或 "business"，为空则返回全球家庭电价排行榜

    Returns:
        dict: {
            "success": bool,
            "title": str,
            "message": str,
            "description": str,
            "error": str | None
        }
    """
    try:
        if not args or not args.strip():
            # 无参数：返回全球家庭电价排行榜
            data = await fetch_electricity_data(GLOBAL_DATA_URL)
            if not data:
                return {
                    "success": False,
                    "title": "❌ 查询失败",
                    "message": "无法获取数据，请稍后重试",
                    "description": "数据获取失败",
                    "error": "Failed to fetch data"
                }

            result = await _format_rankings_text(data, "households")
            return {
                "success": True,
                "title": "⚡ 全球家庭电价排行榜",
                "message": result,
                "description": "全球家庭电价 Top 10",
                "error": None
            }
        else:
            # 有参数：查询指定国家或排行榜
            query_list = args.strip().split()

            # Handle rankings
            if query_list[0] in ["business", "商业", "commercial", "households", "家庭", "residential", "rankings"]:
                # Determine category
                if query_list[0] in ["business", "商业", "commercial"]:
                    category = "business"
                elif query_list[0] in ["households", "家庭", "residential"]:
                    category = "households"
                elif query_list[0] == "rankings" and len(query_list) > 1:
                    category = query_list[1]
                else:
                    category = "households"

                data = await fetch_electricity_data(GLOBAL_DATA_URL)
                if not data:
                    return {
                        "success": False,
                        "title": "❌ 查询失败",
                        "message": "无法获取数据，请稍后重试",
                        "description": "数据获取失败",
                        "error": "Failed to fetch data"
                    }

                result = await _format_rankings_text(data, category)
                category_name_map = {"households": "家庭", "business": "商业"}
                category_name = category_name_map.get(category, "家庭")
                return {
                    "success": True,
                    "title": f"⚡ 全球{category_name}电价排行榜",
                    "message": result,
                    "description": f"全球{category_name}电价 Top 10",
                    "error": None
                }

            # Search for specific countries (support multiple)
            results = []
            not_found = []

            for query in query_list:
                result_text = await _search_country_text(query.lower())
                if result_text:
                    results.append(result_text)
                else:
                    not_found.append(query)

            if results:
                final_message = "\n\n".join(results)
                if not_found:
                    from utils.formatter import foldable_text_with_markdown_v2
                    final_message += f"\n\n❌ 未找到: {', '.join(not_found)}"
                    final_message = foldable_text_with_markdown_v2(final_message)

                # Build description
                if len(query_list) == 1:
                    desc = f"{query_list[0]} 电价"
                else:
                    desc = f"{', '.join(query_list[:3])} 等地区电价"

                return {
                    "success": True,
                    "title": f"⚡ 电价查询",
                    "message": final_message,
                    "description": desc,
                    "error": None
                }
            else:
                return {
                    "success": False,
                    "title": "❌ 未找到",
                    "message": f"未找到 '{', '.join(query_list)}' 的电价数据",
                    "description": "未找到数据",
                    "error": "Countries not found"
                }

    except Exception as e:
        logger.error(f"Inline electricity query failed: {e}")
        return {
            "success": False,
            "title": "❌ 查询失败",
            "message": f"查询电价失败: {str(e)}",
            "description": "查询失败",
            "error": str(e)
        }


async def _format_rankings_text(data: dict, category: str) -> str:
    """Format rankings text for inline mode"""
    from utils.formatter import foldable_text_with_markdown_v2

    category_map = {
        "households": ("households", "🏠 家庭用电"),
        "business": ("business", "🏢 商业用电"),
    }

    category_key, category_name = category_map.get(category, ("households", "🏠 家庭用电"))

    # Filter and sort
    valid_data = [(code, info) for code, info in data.items()
                  if info.get('electricity') and info['electricity'].get(category_key)
                  and info['electricity'][category_key].get('price_cny', 0) > 0]
    sorted_data = sorted(valid_data, key=lambda x: x[1]['electricity'][category_key]['price_cny'])
    cheapest_10 = sorted_data[:10]
    expensive_10 = sorted_data[-10:][::-1]

    # Format message
    raw_parts = [f"*⚡ 全球{category_name}价格排行榜*", ""]

    raw_parts.append("💚 *最便宜 Top 10:*")
    for i, (code, info) in enumerate(cheapest_10, 1):
        country = info['country']
        elec_info = info['electricity'][category_key]
        price_cny = elec_info['price_cny']

        # Map to ISO code
        iso_code = COUNTRY_CODE_MAPPING.get(code, code)
        country_info = SUPPORTED_COUNTRIES.get(iso_code.upper(), {})
        country_name_cn = country_info.get('name', '')
        country_flag = get_country_flag(iso_code)

        if country_name_cn:
            country_display = f"{country} ({country_name_cn}) {country_flag}"
        else:
            country_display = country

        raw_parts.append(f"{i}. {country_display}: `{price_cny:.2f}` CNY/kWh")

    raw_parts.append("")
    raw_parts.append("💸 *最贵 Top 10:*")
    for i, (code, info) in enumerate(expensive_10, 1):
        country = info['country']
        elec_info = info['electricity'][category_key]
        price_cny = elec_info['price_cny']

        # Map to ISO code
        iso_code = COUNTRY_CODE_MAPPING.get(code, code)
        country_info = SUPPORTED_COUNTRIES.get(iso_code.upper(), {})
        country_name_cn = country_info.get('name', '')
        country_flag = get_country_flag(iso_code)

        if country_name_cn:
            country_display = f"{country} ({country_name_cn}) {country_flag}"
        else:
            country_display = country

        raw_parts.append(f"{i}. {country_display}: `{price_cny:.2f}` CNY/kWh")

    # Add statistics
    prices = [info['electricity'][category_key]['price_cny'] for _, info in valid_data]
    avg_price = sum(prices) / len(prices)
    raw_parts.append("")
    raw_parts.append(f"📊 *全球平均价格:* `{avg_price:.2f}` CNY/kWh")
    raw_parts.append(f"🌍 *覆盖国家:* {len(valid_data)} 个")

    return foldable_text_with_markdown_v2("\n".join(raw_parts))


async def _search_country_text(query: str) -> str | None:
    """Search for a country and return formatted text"""
    from utils.formatter import foldable_text_with_markdown_v2

    data = await fetch_electricity_data(GLOBAL_DATA_URL)
    if not data:
        return None

    # Try matching with SUPPORTED_COUNTRIES first
    for country_code, country_info in SUPPORTED_COUNTRIES.items():
        country_name_cn = country_info.get('name', '').lower()

        if query == country_code.lower() or query in country_name_cn:
            # Find matching country in global data
            for json_code, elec_info in data.items():
                iso_code = COUNTRY_CODE_MAPPING.get(json_code, json_code)
                if iso_code.upper() == country_code:
                    country = elec_info.get('country', 'Unknown')
                    text = format_country_electricity(country, elec_info, data)
                    return foldable_text_with_markdown_v2(text)

    # Fallback: direct search
    for code, info in data.items():
        country = info.get('country', '').lower()
        if query in country or query in code.lower() or code.lower() == query:
            country_name = info.get('country', 'Unknown')
            text = format_country_electricity(country_name, info, data)
            return foldable_text_with_markdown_v2(text)

    return None
