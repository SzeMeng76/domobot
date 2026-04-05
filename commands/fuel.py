# Description: Telegram bot command for fuel price lookup
# This module provides /fuel command to check fuel prices globally and in China

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

# GitHub raw URLs for fuel price data
CHINA_DATA_URL = "https://raw.githubusercontent.com/SzeMeng76/fuel-price-tracker/refs/heads/master/china_fuel_prices.json"
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
    "Qatar": "QA",
    "Kuwait": "KW",
    "Bahrain": "BH",
    "Oman": "OM",
    "Israel": "IL",
    "Pakistan": "PK",
    "Bangladesh": "BD",
    "Sri-Lanka": "LK",
    "Sri Lanka": "LK",
    "Algeria": "DZ",
    "Morocco": "MA",
    "Tunisia": "TN",
    "Libya": "LY",
    "Ghana": "GH",
    "Ethiopia": "ET",
    "Tanzania": "TZ",
    "Uganda": "UG",
    "Zambia": "ZM",
    "Zimbabwe": "ZW",
    "Botswana": "BW",
    "Namibia": "NA",
    "Angola": "AO",
    "Mozambique": "MZ",
    "Madagascar": "MG",
    "Mauritius": "MU",
    "Seychelles": "SC",
    "Iceland": "IS",
    "Luxembourg": "LU",
    "Malta": "MT",
    "Cyprus": "CY",
    "Albania": "AL",
    "Serbia": "RS",
    "Bosnia-and-Herzegovina": "BA",
    "Bosnia and Herzegovina": "BA",
    "North-Macedonia": "MK",
    "North Macedonia": "MK",
    "Montenegro": "ME",
    "Moldova": "MD",
    "Georgia": "GE",
    "Armenia": "AM",
    "Azerbaijan": "AZ",
    "Kazakhstan": "KZ",
    "Uzbekistan": "UZ",
    "Turkmenistan": "TM",
    "Kyrgyzstan": "KG",
    "Tajikistan": "TJ",
    "Mongolia": "MN",
    "Nepal": "NP",
    "Bhutan": "BT",
    "Myanmar": "MM",
    "Cambodia": "KH",
    "Laos": "LA",
    "Brunei": "BN",
    "Maldives": "MV",
    "Afghanistan": "AF",
    "Iraq": "IQ",
    "Iran": "IR",
    "Syria": "SY",
    "Lebanon": "LB",
    "Jordan": "JO",
    "Yemen": "YE",
    "Palestine": "PS",
    "Cuba": "CU",
    "Jamaica": "JM",
    "Dominican-Republic": "DO",
    "Dominican Republic": "DO",
    "Trinidad-and-Tobago": "TT",
    "Trinidad and Tobago": "TT",
    "Bahamas": "BS",
    "Barbados": "BB",
    "Guatemala": "GT",
    "Honduras": "HN",
    "El-Salvador": "SV",
    "El Salvador": "SV",
    "Nicaragua": "NI",
    "Costa-Rica": "CR",
    "Costa Rica": "CR",
    "Panama": "PA",
    "Bolivia": "BO",
    "Paraguay": "PY",
    "Uruguay": "UY",
    "Guyana": "GY",
    "Suriname": "SR",
    "Senegal": "SN",
    "Mali": "ML",
    "Burkina-Faso": "BF",
    "Burkina Faso": "BF",
    "Niger": "NE",
    "Chad": "TD",
    "Sudan": "SD",
    "South-Sudan": "SS",
    "South Sudan": "SS",
    "Eritrea": "ER",
    "Djibouti": "DJ",
    "Somalia": "SO",
    "Rwanda": "RW",
    "Burundi": "BI",
    "Malawi": "MW",
    "Cameroon": "CM",
    "Central-African-Republic": "CF",
    "Central African Republic": "CF",
    "Congo": "CG",
    "Democratic-Republic-of-the-Congo": "CD",
    "Democratic Republic of the Congo": "CD",
    "Gabon": "GA",
    "Equatorial-Guinea": "GQ",
    "Equatorial Guinea": "GQ",
    "Sao-Tome-and-Principe": "ST",
    "Sao Tome and Principe": "ST",
    "Guinea": "GN",
    "Guinea-Bissau": "GW",
    "Guinea Bissau": "GW",
    "Sierra-Leone": "SL",
    "Sierra Leone": "SL",
    "Liberia": "LR",
    "Ivory-Coast": "CI",
    "Ivory Coast": "CI",
    "Togo": "TG",
    "Benin": "BJ",
    "Mauritania": "MR",
    "Gambia": "GM",
    "Cape-Verde": "CV",
    "Cape Verde": "CV",
    "Comoros": "KM",
    "Lesotho": "LS",
    "Eswatini": "SZ",
    "Papua-New-Guinea": "PG",
    "Papua New Guinea": "PG",
    "Fiji": "FJ",
    "Solomon-Islands": "SB",
    "Solomon Islands": "SB",
    "Vanuatu": "VU",
    "Samoa": "WS",
    "Tonga": "TO",
    "Kiribati": "KI",
    "Micronesia": "FM",
    "Palau": "PW",
    "Marshall-Islands": "MH",
    "Marshall Islands": "MH",
    "Tuvalu": "TV",
    "Nauru": "NR",
    "North-Korea": "KP",
    "North Korea": "KP",
    "Macau": "MO",
}


async def fetch_fuel_data(url: str) -> dict | None:
    """Fetch fuel price data from GitHub with cache"""
    try:
        # Try cache first
        cache_key = f"fuel_data_{url.split('/')[-1]}"
        if cache_manager:
            cached_data = await cache_manager.load_cache(cache_key, subdirectory="fuel")
            if cached_data:
                logger.info(f"Using cached fuel data for {cache_key}")
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
                await cache_manager.save_cache(cache_key, data, subdirectory="fuel")

            return data
        else:
            logger.error(f"Failed to fetch data: HTTP {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Error fetching fuel data: {e}")
        return None


def format_china_province(province_data: dict, all_data: dict = None) -> str:
    """Format China province fuel price with ranking"""
    province = province_data.get('province', 'Unknown')
    gasoline_92 = province_data.get('92_gasoline', 0)
    gasoline_95 = province_data.get('95_gasoline', 0)
    gasoline_98 = province_data.get('98_gasoline', 0)
    diesel_0 = province_data.get('0_diesel', 0)

    text = f"📍 *{province}*\n\n"
    text += f"92\\# 汽油: `{gasoline_92:.2f}` 元\\/升\n"
    text += f"95\\# 汽油: `{gasoline_95:.2f}` 元\\/升\n"
    text += f"98\\# 汽油: `{gasoline_98:.2f}` 元\\/升\n"
    text += f"0\\# 柴油: `{diesel_0:.2f}` 元\\/升\n"

    # Add ranking if all_data is provided
    if all_data and gasoline_92 > 0:
        sorted_provinces = sorted(
            all_data.items(),
            key=lambda x: x[1].get('92_gasoline', 0)
        )
        prices = [info.get('92_gasoline', 0) for _, info in sorted_provinces]
        avg_price = sum(prices) / len(prices) if prices else 0

        # Find ranking
        rank = next((i + 1 for i, (code, info) in enumerate(sorted_provinces)
                    if info.get('province') == province), None)

        if rank:
            text += f"\n📊 *全国排名:* 第 {rank}\\/{len(sorted_provinces)} 位\n"
            text += f"📈 *全国平均:* `{avg_price:.2f}` 元\\/升\n"
            diff = gasoline_92 - avg_price
            if diff > 0:
                text += f"💸 比平均高 `{diff:.2f}` 元\\/升\n"
            elif diff < 0:
                text += f"💚 比平均低 `{abs(diff):.2f}` 元\\/升\n"

    # Add adjustment info if available
    adjustment = province_data.get('adjustment')
    if adjustment:
        next_date = adjustment.get('next_adjustment_date', '')
        trend = adjustment.get('expected_trend', '')
        amount = adjustment.get('expected_amount_liter', '')
        if next_date and trend:
            text += f"\n📅 *下次调价:* {next_date}\n"
            text += f"*预计:* {trend}"
            if amount:
                text += f" {amount}"
            text += "\n"

    return text


def format_global_country(country_data: dict, all_data: dict = None, country_code: str = None) -> str:
    """Format global country fuel price with ranking (gasoline and diesel)"""
    country = country_data.get('country', 'Unknown')
    gasoline = country_data.get('gasoline')
    diesel = country_data.get('diesel')

    # Map to ISO code if needed
    if country_code:
        iso_code = COUNTRY_CODE_MAPPING.get(country_code, country_code)
    else:
        iso_code = None

    # Get Chinese name and flag
    country_name_cn = None
    country_flag = ""
    if iso_code:
        country_info = SUPPORTED_COUNTRIES.get(iso_code.upper(), {})
        country_name_cn = country_info.get('name', '')
        country_flag = get_country_flag(iso_code)

    # Format title with Chinese name and flag
    if country_name_cn:
        text = f"🌍 *{country}* \\({country_name_cn}\\) {country_flag}\n\n"
    else:
        text = f"🌍 *{country}*\n\n"

    # Gasoline
    if gasoline:
        price = gasoline.get('price', 0)
        currency = gasoline.get('currency', 'USD')
        price_cny = gasoline.get('price_cny', 0)
        local_price = gasoline.get('local_price')
        local_currency = gasoline.get('local_currency')

        text += f"🚗 *汽油:*\n"

        # Show local price if available
        if local_price and local_currency:
            text += f"  本地价格: `{local_price:.2f}` {local_currency}\\/L\n"

        text += f"  USD价格: `{price:.2f}` {currency}\\/L\n"
        text += f"  折合CNY: `{price_cny:.2f}` CNY\\/L\n"

        # Add ranking for gasoline
        if all_data and price_cny > 0:
            gasoline_data = [(code, info) for code, info in all_data.items()
                           if info.get('gasoline') and info['gasoline'].get('price_cny', 0) > 0]
            sorted_countries = sorted(gasoline_data, key=lambda x: x[1]['gasoline']['price_cny'])
            prices = [info['gasoline']['price_cny'] for _, info in sorted_countries]
            avg_price = sum(prices) / len(prices) if prices else 0

            rank = next((i + 1 for i, (code, info) in enumerate(sorted_countries)
                        if info.get('country') == country), None)

            if rank:
                text += f"  📊 全球排名: 第 {rank}\\/{len(sorted_countries)} 位\n"
                diff = price_cny - avg_price
                if diff > 0:
                    text += f"  💸 比平均高 `{diff:.2f}` CNY\\/L\n"
                elif diff < 0:
                    text += f"  💚 比平均低 `{abs(diff):.2f}` CNY\\/L\n"

    # Diesel
    if diesel:
        price = diesel.get('price', 0)
        currency = diesel.get('currency', 'USD')
        price_cny = diesel.get('price_cny', 0)
        local_price = diesel.get('local_price')
        local_currency = diesel.get('local_currency')

        text += f"\n🚛 *柴油:*\n"

        # Show local price if available
        if local_price and local_currency:
            text += f"  本地价格: `{local_price:.2f}` {local_currency}\\/L\n"

        text += f"  USD价格: `{price:.2f}` {currency}\\/L\n"
        text += f"  折合CNY: `{price_cny:.2f}` CNY\\/L\n"

        # Add ranking for diesel
        if all_data and price_cny > 0:
            diesel_data = [(code, info) for code, info in all_data.items()
                         if info.get('diesel') and info['diesel'].get('price_cny', 0) > 0]
            sorted_countries = sorted(diesel_data, key=lambda x: x[1]['diesel']['price_cny'])
            prices = [info['diesel']['price_cny'] for _, info in sorted_countries]
            avg_price = sum(prices) / len(prices) if prices else 0

            rank = next((i + 1 for i, (code, info) in enumerate(sorted_countries)
                        if info.get('country') == country), None)

            if rank:
                text += f"  📊 全球排名: 第 {rank}\\/{len(sorted_countries)} 位\n"
                diff = price_cny - avg_price
                if diff > 0:
                    text += f"  💸 比平均高 `{diff:.2f}` CNY\\/L\n"
                elif diff < 0:
                    text += f"  💚 比平均低 `{abs(diff):.2f}` CNY\\/L\n"

    # LPG
    lpg = country_data.get('lpg')
    if lpg:
        price = lpg.get('price', 0)
        currency = lpg.get('currency', 'USD')
        price_cny = lpg.get('price_cny', 0)
        local_price = lpg.get('local_price')
        local_currency = lpg.get('local_currency')

        text += f"\n⛽ *LPG:*\n"

        # Show local price if available
        if local_price and local_currency:
            text += f"  本地价格: `{local_price:.2f}` {local_currency}\\/L\n"

        text += f"  USD价格: `{price:.2f}` {currency}\\/L\n"
        text += f"  折合CNY: `{price_cny:.2f}` CNY\\/L\n"

        # Add ranking for LPG
        if all_data and price_cny > 0:
            lpg_data = [(code, info) for code, info in all_data.items()
                       if info.get('lpg') and info['lpg'].get('price_cny', 0) > 0]
            sorted_countries = sorted(lpg_data, key=lambda x: x[1]['lpg']['price_cny'])
            prices = [info['lpg']['price_cny'] for _, info in sorted_countries]
            avg_price = sum(prices) / len(prices) if prices else 0

            rank = next((i + 1 for i, (code, info) in enumerate(sorted_countries)
                        if info.get('country') == country), None)

            if rank:
                text += f"  📊 全球排名: 第 {rank}\\/{len(sorted_countries)} 位\n"
                diff = price_cny - avg_price
                if diff > 0:
                    text += f"  💸 比平均高 `{diff:.2f}` CNY\\/L\n"
                elif diff < 0:
                    text += f"  💚 比平均低 `{abs(diff):.2f}` CNY\\/L\n"

    if not gasoline and not diesel and not lpg:
        text += "暂无数据\n"

    # Add data source and price date
    text += f"\n📅 *数据日期:* "
    price_date = None
    if gasoline and gasoline.get('price_date'):
        price_date = gasoline.get('price_date')
    elif diesel and diesel.get('price_date'):
        price_date = diesel.get('price_date')
    elif lpg and lpg.get('price_date'):
        price_date = lpg.get('price_date')

    if price_date:
        # Escape hyphens in date
        price_date_escaped = price_date.replace('-', '\\-')
        text += f"{price_date_escaped}\n"
    else:
        text += "未知\n"

    text += f"🔗 *数据来源:* [GlobalPetrolPrices\\.com](https://www\\.globalpetrolprices\\.com/)\n"

    return text


async def fuel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /fuel command"""
    if not update.message:
        return

    # Parse arguments
    args = context.args

    if not args:
        # No args - show global gasoline rankings (like netflix shows top 10)
        await show_rankings(update, context, "gasoline")
        return

    query = " ".join(args).lower()

    # Handle special commands
    if query.startswith("rankings") or query.startswith("rank") or query.startswith("排行") or query.startswith("top"):
        # Extract fuel type if specified
        parts = query.split()
        fuel_type = parts[1] if len(parts) > 1 else "gasoline"
        await show_rankings(update, context, fuel_type)
        return

    # Handle direct fuel type queries (diesel, gasoline, lpg, 柴油, 汽油, 液化石油气)
    if query in ["diesel", "柴油"]:
        await show_rankings(update, context, "diesel")
        return

    if query in ["gasoline", "gas", "汽油"]:
        await show_rankings(update, context, "gasoline")
        return

    if query in ["lpg", "液化石油气"]:
        await show_rankings(update, context, "lpg")
        return

    if query.startswith("china") or query.startswith("中国") or query == "cn":
        # Extract fuel type if specified
        parts = query.split()
        fuel_type = parts[1] if len(parts) > 1 else "92"
        await show_china_all(update, context, fuel_type)
        return

    # Search for specific location
    await search_fuel_price(update, context, args)


async def show_rankings(update: Update, context: ContextTypes.DEFAULT_TYPE, fuel_type: str = "gasoline"):
    """Show global fuel price rankings for specified fuel type"""
    if not update.message:
        return

    data = await fetch_fuel_data(GLOBAL_DATA_URL)

    if not data:
        await send_error(context, update.message.chat_id, "无法获取数据，请稍后重试", parse_mode="MarkdownV2")
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        return

    # Map fuel type
    fuel_map = {
        "gasoline": ("gasoline", "🚗 汽油"),
        "gas": ("gasoline", "🚗 汽油"),
        "汽油": ("gasoline", "🚗 汽油"),
        "diesel": ("diesel", "🚛 柴油"),
        "柴油": ("diesel", "🚛 柴油"),
        "lpg": ("lpg", "⛽ LPG"),
        "液化石油气": ("lpg", "⛽ LPG"),
    }

    fuel_key, fuel_name = fuel_map.get(fuel_type.lower(), ("gasoline", "🚗 汽油"))

    # Filter valid data and sort by CNY price
    valid_data = [(code, info) for code, info in data.items()
                  if info.get(fuel_key) and info[fuel_key].get('price_cny', 0) > 0]

    if not valid_data:
        await send_error(context, update.message.chat_id, f"暂无{fuel_name}数据", parse_mode="MarkdownV2")
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        return

    # Sort by price
    sorted_data = sorted(valid_data, key=lambda x: x[1][fuel_key]['price_cny'])

    # Get cheapest and most expensive
    cheapest_10 = sorted_data[:10]
    expensive_10 = sorted_data[-10:][::-1]

    # Calculate average
    prices = [info[fuel_key]['price_cny'] for _, info in valid_data]
    avg_price = sum(prices) / len(prices)

    # Format message
    text = f"🛢️ *全球{fuel_name}价格排行榜*\n\n"

    text += "💚 *最便宜 Top 10:*\n"
    for i, (code, info) in enumerate(cheapest_10, 1):
        country = info['country']
        fuel_info = info[fuel_key]
        price_cny = fuel_info['price_cny']
        price_orig = fuel_info['price']
        currency = fuel_info['currency']

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

        text += f"{i}\\. {country_display}: `{price_cny:.2f}` CNY\\/L \\(`{price_orig:.2f}` {currency}\\/L\\)\n"

    text += "\n💸 *最贵 Top 10:*\n"
    for i, (code, info) in enumerate(expensive_10, 1):
        country = info['country']
        fuel_info = info[fuel_key]
        price_cny = fuel_info['price_cny']
        price_orig = fuel_info['price']
        currency = fuel_info['currency']

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

        text += f"{i}\\. {country_display}: `{price_cny:.2f}` CNY\\/L \\(`{price_orig:.2f}` {currency}\\/L\\)\n"

    text += f"\n📊 *全球平均价格:* `{avg_price:.2f}` CNY\\/L\n"
    text += f"📈 *价格范围:* `{min(prices):.2f}` \\- `{max(prices):.2f}` CNY\\/L\n"
    text += f"🌍 *覆盖国家:* {len(valid_data)} 个\n"

    # Add usage hint
    if fuel_key == "gasoline":
        text += f"\n💡 *提示:* 使用 `/fuel rankings diesel` 查看柴油排行，`/fuel rankings lpg` 查看LPG排行\n"
    elif fuel_key == "diesel":
        text += f"\n💡 *提示:* 使用 `/fuel rankings gasoline` 查看汽油排行，`/fuel rankings lpg` 查看LPG排行\n"
    else:  # lpg
        text += f"\n💡 *提示:* 使用 `/fuel rankings gasoline` 查看汽油排行，`/fuel rankings diesel` 查看柴油排行\n"

    await send_search_result(context, update.message.chat_id, text, parse_mode="MarkdownV2")
    await delete_user_command(context, update.message.chat_id, update.message.message_id)


async def show_china_all(update: Update, context: ContextTypes.DEFAULT_TYPE, fuel_type: str = "92"):
    """Show all China provinces fuel prices with rankings for specified fuel type"""
    if not update.message:
        return

    data = await fetch_fuel_data(CHINA_DATA_URL)

    if not data:
        await send_error(context, update.message.chat_id, "无法获取数据，请稍后重试", parse_mode="MarkdownV2")
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        return

    # Map fuel type to data key
    fuel_map = {
        "92": ("92_gasoline", "92\\# 汽油"),
        "95": ("95_gasoline", "95\\# 汽油"),
        "98": ("98_gasoline", "98\\# 汽油"),
        "0": ("0_diesel", "0\\# 柴油"),
        "diesel": ("0_diesel", "0\\# 柴油"),
        "柴油": ("0_diesel", "0\\# 柴油"),
    }

    # Get fuel key and name
    fuel_key, fuel_name = fuel_map.get(fuel_type.lower(), ("92_gasoline", "92# 汽油"))

    # Sort by specified fuel type price
    sorted_provinces = sorted(
        data.items(),
        key=lambda x: x[1].get(fuel_key, 0)
    )

    # Calculate statistics
    prices = [info.get(fuel_key, 0) for _, info in sorted_provinces if info.get(fuel_key, 0) > 0]
    avg_price = sum(prices) / len(prices) if prices else 0

    # Get cheapest and most expensive
    cheapest_10 = sorted_provinces[:10]
    expensive_10 = sorted_provinces[-10:][::-1]

    text = f"🇨🇳 *中国油价排行榜 \\({fuel_name}\\)*\n\n"

    # Cheapest 10
    text += "💚 *最便宜 Top 10:*\n"
    for i, (code, info) in enumerate(cheapest_10, 1):
        province = info.get('province', 'Unknown')
        price = info.get(fuel_key, 0)
        text += f"{i}\\. {province}: `{price:.2f}` 元\\/升\n"

    # Most expensive 10
    text += "\n💸 *最贵 Top 10:*\n"
    for i, (code, info) in enumerate(expensive_10, 1):
        province = info.get('province', 'Unknown')
        price = info.get(fuel_key, 0)
        text += f"{i}\\. {province}: `{price:.2f}` 元\\/升\n"

    # Statistics
    text += f"\n📊 *全国平均:* `{avg_price:.2f}` 元\\/升\n"
    text += f"📈 *价格范围:* `{min(prices):.2f}` \\- `{max(prices):.2f}` 元\\/升\n"
    text += f"🏙️ *覆盖省市:* {len(sorted_provinces)} 个\n"

    # Add adjustment info from first province
    first_province = next(iter(data.values()))
    adjustment = first_province.get('adjustment')
    if adjustment:
        next_date = adjustment.get('next_adjustment_date', '')
        trend = adjustment.get('expected_trend', '')
        amount = adjustment.get('expected_amount_liter', '')
        if next_date and trend:
            text += f"\n📅 *下次调价:* {next_date}\n"
            text += f"*预计:* {trend}"
            if amount:
                text += f" {amount}"
            text += "\n"

    # Add usage hint
    text += f"\n💡 *提示:* 使用 `/fuel china 95` 或 `/fuel china 98` 或 `/fuel china diesel` 查看其他油品排行\n"

    await send_search_result(context, update.message.chat_id, text, parse_mode="MarkdownV2")
    await delete_user_command(context, update.message.chat_id, update.message.message_id)


async def search_fuel_price(update: Update, context: ContextTypes.DEFAULT_TYPE, args: list):
    """Search for specific location fuel price - supports multiple countries"""
    if not update.message:
        return

    # Parse queries
    queries = [q.lower() for q in args]

    # Collect results
    results = []
    not_found = []

    for query in queries:
        found = False

        # Try China first
        china_data = await fetch_fuel_data(CHINA_DATA_URL)
        if china_data:
            for code, info in china_data.items():
                province = info.get('province', '').lower()
                if query in province or query in code.lower():
                    results.append({
                        'type': 'china',
                        'data': info,
                        'all_data': china_data
                    })
                    found = True
                    break

        if found:
            continue

        # Try global - use SUPPORTED_COUNTRIES for matching
        global_data = await fetch_fuel_data(GLOBAL_DATA_URL)
        if global_data:
            # Try matching with SUPPORTED_COUNTRIES first
            for country_code, country_info in SUPPORTED_COUNTRIES.items():
                country_name_cn = country_info.get('name', '').lower()

                if query == country_code.lower() or query in country_name_cn:
                    # Find matching country in global data
                    for json_code, fuel_info in global_data.items():
                        iso_code = COUNTRY_CODE_MAPPING.get(json_code, json_code)
                        if iso_code.upper() == country_code:
                            results.append({
                                'type': 'global',
                                'data': fuel_info,
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
                            'type': 'global',
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
            f"未找到 '{', '.join(queries)}' 的油价数据\n\n"
            "提示: 使用 /fuel 查看全球排行榜",
            parse_mode="MarkdownV2"
        )
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        return

    # Build message
    message_parts = []

    for result in results:
        if result['type'] == 'china':
            text = format_china_province(result['data'], result['all_data'])
        else:
            text = format_global_country(result['data'], result['all_data'], result['code'])
        message_parts.append(text)

    # Add not found notice
    if not_found:
        message_parts.append(f"\n❌ 未找到: {', '.join(not_found)}")

    final_message = "\n\n".join(message_parts)
    await send_search_result(context, update.message.chat_id, final_message, parse_mode="MarkdownV2")
    await delete_user_command(context, update.message.chat_id, update.message.message_id)


# Register command
command_factory.register_command("fuel", fuel_command, permission=Permission.NONE, description="🛢️ 查询全球和中国油价（汽油+柴油）")


# =============================================================================
# Inline 执行入口
# =============================================================================

async def fuel_inline_execute(args: str) -> dict:
    """
    Inline Query 执行入口 - 提供完整的 fuel 价格查询功能

    Args:
        args: 用户输入的参数字符串，如 "my" 或 "马来西亚" 或 "china"，为空则返回全球汽油排行榜

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
            # 无参数：返回全球汽油排行榜
            data = await fetch_fuel_data(GLOBAL_DATA_URL)
            if not data:
                return {
                    "success": False,
                    "title": "❌ 查询失败",
                    "message": "无法获取数据，请稍后重试",
                    "description": "数据获取失败",
                    "error": "Failed to fetch data"
                }

            result = await _format_rankings_text(data, "gasoline")
            return {
                "success": True,
                "title": "🛢️ 全球汽油价格排行榜",
                "message": result,
                "description": "全球汽油价格 Top 10",
                "error": None
            }
        else:
            # 有参数：查询指定国家或地区
            query_list = args.strip().split()

            # Handle china rankings
            if query_list[0] in ["china", "中国"]:
                fuel_type = query_list[1] if len(query_list) > 1 else "92"
                data = await fetch_fuel_data(CHINA_DATA_URL)
                if not data:
                    return {
                        "success": False,
                        "title": "❌ 查询失败",
                        "message": "无法获取中国数据，请稍后重试",
                        "description": "数据获取失败",
                        "error": "Failed to fetch China data"
                    }

                result = await _format_china_rankings_text(data, fuel_type)
                return {
                    "success": True,
                    "title": f"🇨🇳 中国油价排行榜",
                    "message": result,
                    "description": f"中国油价排行榜",
                    "error": None
                }

            # Handle global rankings
            if query_list[0] in ["diesel", "柴油", "lpg", "液化石油气", "rankings"]:
                # Determine fuel type
                if query_list[0] in ["diesel", "柴油"]:
                    fuel_type = "diesel"
                elif query_list[0] in ["lpg", "液化石油气"]:
                    fuel_type = "lpg"
                elif query_list[0] == "rankings" and len(query_list) > 1:
                    fuel_type = query_list[1]
                else:
                    fuel_type = "gasoline"

                data = await fetch_fuel_data(GLOBAL_DATA_URL)
                if not data:
                    return {
                        "success": False,
                        "title": "❌ 查询失败",
                        "message": "无法获取数据，请稍后重试",
                        "description": "数据获取失败",
                        "error": "Failed to fetch data"
                    }

                result = await _format_rankings_text(data, fuel_type)
                fuel_name_map = {"diesel": "柴油", "gasoline": "汽油", "lpg": "LPG"}
                fuel_name = fuel_name_map.get(fuel_type, "汽油")
                return {
                    "success": True,
                    "title": f"🛢️ 全球{fuel_name}价格排行榜",
                    "message": result,
                    "description": f"全球{fuel_name}价格 Top 10",
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
                    desc = f"{query_list[0]} 油价"
                else:
                    desc = f"{', '.join(query_list[:3])} 等地区油价"

                return {
                    "success": True,
                    "title": f"🛢️ 油价查询",
                    "message": final_message,
                    "description": desc,
                    "error": None
                }
            else:
                return {
                    "success": False,
                    "title": "❌ 未找到",
                    "message": f"未找到 '{', '.join(query_list)}' 的油价数据",
                    "description": "未找到数据",
                    "error": "Countries not found"
                }

    except Exception as e:
        logger.error(f"Inline fuel query failed: {e}")
        return {
            "success": False,
            "title": "❌ 查询失败",
            "message": f"查询油价失败: {str(e)}",
            "description": "查询失败",
            "error": str(e)
        }


async def _format_rankings_text(data: dict, fuel_type: str) -> str:
    """Format rankings text for inline mode"""
    from utils.formatter import foldable_text_with_markdown_v2

    fuel_map = {
        "gasoline": ("gasoline", "🚗 汽油"),
        "diesel": ("diesel", "🚛 柴油"),
        "lpg": ("lpg", "⛽ LPG"),
    }

    fuel_key, fuel_name = fuel_map.get(fuel_type, ("gasoline", "🚗 汽油"))

    # Filter and sort
    valid_data = [(code, info) for code, info in data.items()
                  if info.get(fuel_key) and info[fuel_key].get('price_cny', 0) > 0]
    sorted_data = sorted(valid_data, key=lambda x: x[1][fuel_key]['price_cny'])
    cheapest_10 = sorted_data[:10]
    expensive_10 = sorted_data[-10:][::-1]

    # Format message
    raw_parts = [f"*🛢️ 全球{fuel_name}价格排行榜*", ""]

    raw_parts.append("💚 *最便宜 Top 10:*")
    for i, (code, info) in enumerate(cheapest_10, 1):
        country = info['country']
        fuel_info = info[fuel_key]
        price_cny = fuel_info['price_cny']

        # Map to ISO code
        iso_code = COUNTRY_CODE_MAPPING.get(code, code)
        country_info = SUPPORTED_COUNTRIES.get(iso_code.upper(), {})
        country_name_cn = country_info.get('name', '')
        country_flag = get_country_flag(iso_code)

        if country_name_cn:
            country_display = f"{country} ({country_name_cn}) {country_flag}"
        else:
            country_display = country

        raw_parts.append(f"{i}. {country_display}: ¥{price_cny:.2f}/L")

    raw_parts.append("")
    raw_parts.append("💸 *最贵 Top 10:*")
    for i, (code, info) in enumerate(expensive_10, 1):
        country = info['country']
        fuel_info = info[fuel_key]
        price_cny = fuel_info['price_cny']

        # Map to ISO code
        iso_code = COUNTRY_CODE_MAPPING.get(code, code)
        country_info = SUPPORTED_COUNTRIES.get(iso_code.upper(), {})
        country_name_cn = country_info.get('name', '')
        country_flag = get_country_flag(iso_code)

        if country_name_cn:
            country_display = f"{country} ({country_name_cn}) {country_flag}"
        else:
            country_display = country

        raw_parts.append(f"{i}. {country_display}: ¥{price_cny:.2f}/L")

    raw_message = "\n".join(raw_parts)
    return foldable_text_with_markdown_v2(raw_message)


async def _format_china_rankings_text(data: dict, fuel_type: str) -> str:
    """Format China rankings text for inline mode"""
    from utils.formatter import foldable_text_with_markdown_v2

    fuel_map = {
        "92": ("92_gasoline", "92# 汽油"),
        "95": ("95_gasoline", "95# 汽油"),
        "98": ("98_gasoline", "98# 汽油"),
        "diesel": ("0_diesel", "0# 柴油"),
    }

    fuel_key, fuel_name = fuel_map.get(fuel_type, ("92_gasoline", "92# 汽油"))

    # Sort
    sorted_provinces = sorted(data.items(), key=lambda x: x[1].get(fuel_key, 0))
    cheapest_10 = sorted_provinces[:10]
    expensive_10 = sorted_provinces[-10:][::-1]

    # Format message
    raw_parts = [f"*🇨🇳 中国油价排行榜 ({fuel_name})*", ""]

    raw_parts.append("💚 *最便宜 Top 10:*")
    for i, (code, info) in enumerate(cheapest_10, 1):
        province = info.get('province', 'Unknown')
        price = info.get(fuel_key, 0)
        raw_parts.append(f"{i}. {province}: ¥{price:.2f}/升")

    raw_parts.append("")
    raw_parts.append("💸 *最贵 Top 10:*")
    for i, (code, info) in enumerate(expensive_10, 1):
        province = info.get('province', 'Unknown')
        price = info.get(fuel_key, 0)
        raw_parts.append(f"{i}. {province}: ¥{price:.2f}/升")

    raw_message = "\n".join(raw_parts)
    return foldable_text_with_markdown_v2(raw_message)


async def _search_country_text(query: str) -> str | None:
    """Search for country and return formatted text for inline mode"""
    from utils.formatter import foldable_text_with_markdown_v2

    # Try China first
    china_data = await fetch_fuel_data(CHINA_DATA_URL)
    if china_data:
        for code, info in china_data.items():
            province = info.get('province', '').lower()
            if query in province or query in code.lower():
                # Format China province with full details
                province_name = info.get('province', 'Unknown')
                gasoline_92 = info.get('92_gasoline', 0)
                gasoline_95 = info.get('95_gasoline', 0)
                gasoline_98 = info.get('98_gasoline', 0)
                diesel_0 = info.get('0_diesel', 0)

                raw_parts = [
                    f"*📍 {province_name}*",
                    "",
                    f"92# 汽油: ¥{gasoline_92:.2f}/升",
                    f"95# 汽油: ¥{gasoline_95:.2f}/升",
                    f"98# 汽油: ¥{gasoline_98:.2f}/升",
                    f"0# 柴油: ¥{diesel_0:.2f}/升"
                ]

                # Add ranking if available
                if gasoline_92 > 0:
                    sorted_provinces = sorted(
                        china_data.items(),
                        key=lambda x: x[1].get('92_gasoline', 0)
                    )
                    prices = [info_item.get('92_gasoline', 0) for _, info_item in sorted_provinces]
                    avg_price = sum(prices) / len(prices) if prices else 0

                    rank = next((i + 1 for i, (c, info_item) in enumerate(sorted_provinces)
                                if info_item.get('province') == province_name), None)

                    if rank:
                        raw_parts.append("")
                        raw_parts.append(f"📊 *全国排名:* 第 {rank}/{len(sorted_provinces)} 位")
                        raw_parts.append(f"📈 *全国平均:* ¥{avg_price:.2f}/升")
                        diff = gasoline_92 - avg_price
                        if diff > 0:
                            raw_parts.append(f"💸 比平均高 ¥{diff:.2f}/升")
                        elif diff < 0:
                            raw_parts.append(f"💚 比平均低 ¥{abs(diff):.2f}/升")

                # Add adjustment info if available
                adjustment = info.get('adjustment')
                if adjustment:
                    next_date = adjustment.get('next_adjustment_date', '')
                    trend = adjustment.get('expected_trend', '')
                    amount = adjustment.get('expected_amount_liter', '')
                    if next_date and trend:
                        raw_parts.append("")
                        raw_parts.append(f"📅 *下次调价:* {next_date}")
                        raw_parts.append(f"*预计:* {trend}" + (f" {amount}" if amount else ""))

                raw_message = "\n".join(raw_parts)
                return foldable_text_with_markdown_v2(raw_message)

    # Try global
    global_data = await fetch_fuel_data(GLOBAL_DATA_URL)
    if global_data:
        # Try SUPPORTED_COUNTRIES matching
        for country_code, country_info in SUPPORTED_COUNTRIES.items():
            country_name_cn = country_info.get('name', '').lower()
            if query == country_code.lower() or query in country_name_cn:
                for json_code, fuel_info in global_data.items():
                    iso_code = COUNTRY_CODE_MAPPING.get(json_code, json_code)
                    if iso_code.upper() == country_code:
                        return _format_country_inline(fuel_info, json_code, global_data)

        # Fallback: direct search
        for code, info in global_data.items():
            country = info.get('country', '').lower()
            if query in country or query in code.lower():
                return _format_country_inline(info, code, global_data)

    return None


def _format_country_inline(country_data: dict, country_code: str, all_data: dict = None) -> str:
    """Format single country data for inline mode"""
    from utils.formatter import foldable_text_with_markdown_v2

    country = country_data.get('country', 'Unknown')
    gasoline = country_data.get('gasoline')
    diesel = country_data.get('diesel')

    # Map to ISO code
    iso_code = COUNTRY_CODE_MAPPING.get(country_code, country_code)
    country_info = SUPPORTED_COUNTRIES.get(iso_code.upper(), {})
    country_name_cn = country_info.get('name', '')
    country_flag = get_country_flag(iso_code)

    raw_parts = []

    # Title
    if country_name_cn:
        raw_parts.append(f"*🌍 {country} ({country_name_cn}) {country_flag}*")
    else:
        raw_parts.append(f"*🌍 {country}*")

    raw_parts.append("")

    # Gasoline
    if gasoline:
        local_price = gasoline.get('local_price')
        local_currency = gasoline.get('local_currency')
        price = gasoline.get('price', 0)
        price_cny = gasoline.get('price_cny', 0)

        raw_parts.append("🚗 *汽油:*")
        if local_price and local_currency:
            raw_parts.append(f"  本地: {local_currency} {local_price:.2f}/L")
        raw_parts.append(f"  USD: ${price:.2f}/L")
        raw_parts.append(f"  CNY: ¥{price_cny:.2f}/L")

        # Add ranking for gasoline
        if all_data and price_cny > 0:
            gasoline_data = [(code, info) for code, info in all_data.items()
                           if info.get('gasoline') and info['gasoline'].get('price_cny', 0) > 0]
            sorted_countries = sorted(gasoline_data, key=lambda x: x[1]['gasoline']['price_cny'])
            prices = [info['gasoline']['price_cny'] for _, info in sorted_countries]
            avg_price = sum(prices) / len(prices) if prices else 0

            rank = next((i + 1 for i, (code, info) in enumerate(sorted_countries)
                        if info.get('country') == country), None)

            if rank:
                raw_parts.append(f"  📊 全球排名: 第 {rank}/{len(sorted_countries)} 位")
                diff = price_cny - avg_price
                if diff > 0:
                    raw_parts.append(f"  💸 比平均高 ¥{diff:.2f}/L")
                elif diff < 0:
                    raw_parts.append(f"  💚 比平均低 ¥{abs(diff):.2f}/L")

    # Diesel
    if diesel:
        local_price = diesel.get('local_price')
        local_currency = diesel.get('local_currency')
        price = diesel.get('price', 0)
        price_cny = diesel.get('price_cny', 0)

        raw_parts.append("")
        raw_parts.append("🚛 *柴油:*")
        if local_price and local_currency:
            raw_parts.append(f"  本地: {local_currency} {local_price:.2f}/L")
        raw_parts.append(f"  USD: ${price:.2f}/L")
        raw_parts.append(f"  CNY: ¥{price_cny:.2f}/L")

        # Add ranking for diesel
        if all_data and price_cny > 0:
            diesel_data = [(code, info) for code, info in all_data.items()
                         if info.get('diesel') and info['diesel'].get('price_cny', 0) > 0]
            sorted_countries = sorted(diesel_data, key=lambda x: x[1]['diesel']['price_cny'])
            prices = [info['diesel']['price_cny'] for _, info in sorted_countries]
            avg_price = sum(prices) / len(prices) if prices else 0

            rank = next((i + 1 for i, (code, info) in enumerate(sorted_countries)
                        if info.get('country') == country), None)

            if rank:
                raw_parts.append(f"  📊 全球排名: 第 {rank}/{len(sorted_countries)} 位")
                diff = price_cny - avg_price
                if diff > 0:
                    raw_parts.append(f"  💸 比平均高 ¥{diff:.2f}/L")
                elif diff < 0:
                    raw_parts.append(f"  💚 比平均低 ¥{abs(diff):.2f}/L")

    # LPG
    lpg = country_data.get('lpg')
    if lpg:
        local_price = lpg.get('local_price')
        local_currency = lpg.get('local_currency')
        price = lpg.get('price', 0)
        price_cny = lpg.get('price_cny', 0)

        raw_parts.append("")
        raw_parts.append("⛽ *LPG:*")
        if local_price and local_currency:
            raw_parts.append(f"  本地: {local_currency} {local_price:.2f}/L")
        raw_parts.append(f"  USD: ${price:.2f}/L")
        raw_parts.append(f"  CNY: ¥{price_cny:.2f}/L")

        if all_data and price_cny > 0:
            lpg_data = [(code, info) for code, info in all_data.items()
                       if info.get('lpg') and info['lpg'].get('price_cny', 0) > 0]
            sorted_countries = sorted(lpg_data, key=lambda x: x[1]['lpg']['price_cny'])
            prices = [info['lpg']['price_cny'] for _, info in sorted_countries]
            avg_price = sum(prices) / len(prices) if prices else 0

            rank = next((i + 1 for i, (code, info) in enumerate(sorted_countries)
                        if info.get('country') == country), None)

            if rank:
                raw_parts.append(f"  📊 全球排名: 第 {rank}/{len(sorted_countries)} 位")
                diff = price_cny - avg_price
                if diff > 0:
                    raw_parts.append(f"  💸 比平均高 ¥{diff:.2f}/L")
                elif diff < 0:
                    raw_parts.append(f"  💚 比平均低 ¥{abs(diff):.2f}/L")

    # Price date
    price_date = None
    if gasoline and gasoline.get('price_date'):
        price_date = gasoline.get('price_date')
    elif diesel and diesel.get('price_date'):
        price_date = diesel.get('price_date')
    elif lpg and lpg.get('price_date'):
        price_date = lpg.get('price_date')

    if price_date:
        raw_parts.append("")
        raw_parts.append(f"📅 数据日期: {price_date}")

    raw_parts.append("🔗 数据来源: GlobalPetrolPrices.com")

    raw_message = "\n".join(raw_parts)
    return foldable_text_with_markdown_v2(raw_message)
