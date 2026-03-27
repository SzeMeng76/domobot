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

    # Get Chinese name and flag
    country_name_cn = None
    country_flag = ""
    if country_code:
        country_info = SUPPORTED_COUNTRIES.get(country_code.upper(), {})
        country_name_cn = country_info.get('name', '')
        country_flag = get_country_flag(country_code)

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
        text += f"🚗 *汽油:*\n"
        text += f"  价格: `{price:.2f}` {currency}\\/L\n"
        text += f"  折合: `{price_cny:.2f}` CNY\\/L\n"

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
        text += f"\n🚛 *柴油:*\n"
        text += f"  价格: `{price:.2f}` {currency}\\/L\n"
        text += f"  折合: `{price_cny:.2f}` CNY\\/L\n"

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

    if not gasoline and not diesel:
        text += "暂无数据\n"

    return text


async def fuel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /fuel command"""
    if not update.message:
        return

    # Parse arguments
    args = context.args

    if not args:
        # Show help
        help_text = (
            "🛢️ *燃油价格查询*\n\n"
            "*使用方法:*\n"
            "`/fuel [地区/国家]` \\- 查询指定地区油价\n"
            "`/fuel rankings [燃油]` \\- 全球价格排行榜\n"
            "`/fuel china [油品]` \\- 中国省份排行榜\n\n"
            "*全球燃油选项:*\n"
            "`/fuel rankings` \\- 汽油排行 \\(默认\\)\n"
            "`/fuel rankings diesel` \\- 柴油排行\n\n"
            "*中国油品选项:*\n"
            "`/fuel china` \\- 92\\#汽油排行 \\(默认\\)\n"
            "`/fuel china 95` \\- 95\\#汽油排行\n"
            "`/fuel china 98` \\- 98\\#汽油排行\n"
            "`/fuel china diesel` \\- 0\\#柴油排行\n\n"
            "*示例:*\n"
            "`/fuel 北京` \\- 查北京油价\n"
            "`/fuel usa` \\- 查美国油价\n"
            "`/fuel 日本` \\- 查日本油价\n"
        )
        await send_help(context, update.message.chat_id, help_text, parse_mode="MarkdownV2")
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        return

    query = " ".join(args).lower()

    # Handle special commands
    if query.startswith("rankings") or query.startswith("rank") or query.startswith("排行") or query.startswith("top10"):
        # Extract fuel type if specified
        parts = query.split()
        fuel_type = parts[1] if len(parts) > 1 else "gasoline"
        await show_rankings(update, context, fuel_type)
        return

    if query.startswith("china") or query.startswith("中国") or query == "cn":
        # Extract fuel type if specified
        parts = query.split()
        fuel_type = parts[1] if len(parts) > 1 else "92"
        await show_china_all(update, context, fuel_type)
        return

    # Search for specific location
    await search_fuel_price(update, context, query)


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
        text += f"{i}\\. {country}: `{price_cny:.2f}` CNY\\/L \\(`{price_orig:.2f}` {currency}\\/L\\)\n"

    text += "\n💸 *最贵 Top 10:*\n"
    for i, (code, info) in enumerate(expensive_10, 1):
        country = info['country']
        fuel_info = info[fuel_key]
        price_cny = fuel_info['price_cny']
        price_orig = fuel_info['price']
        currency = fuel_info['currency']
        text += f"{i}\\. {country}: `{price_cny:.2f}` CNY\\/L \\(`{price_orig:.2f}` {currency}\\/L\\)\n"

    text += f"\n📊 *全球平均价格:* `{avg_price:.2f}` CNY\\/L\n"
    text += f"📈 *价格范围:* `{min(prices):.2f}` \\- `{max(prices):.2f}` CNY\\/L\n"
    text += f"🌍 *覆盖国家:* {len(valid_data)} 个\n"

    # Add usage hint
    other_fuel = "diesel" if fuel_key == "gasoline" else "gasoline"
    other_name = "柴油" if fuel_key == "gasoline" else "汽油"
    text += f"\n💡 *提示:* 使用 `/fuel rankings {other_fuel}` 查看{other_name}排行\n"

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
        "92": ("92_gasoline", "92# 汽油"),
        "95": ("95_gasoline", "95# 汽油"),
        "98": ("98_gasoline", "98# 汽油"),
        "0": ("0_diesel", "0# 柴油"),
        "diesel": ("0_diesel", "0# 柴油"),
        "柴油": ("0_diesel", "0# 柴油"),
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
    text += f"\n💡 *提示:* 使用 `/fuel china 95` 查看95\\#汽油排行\n"

    await send_search_result(context, update.message.chat_id, text, parse_mode="MarkdownV2")
    await delete_user_command(context, update.message.chat_id, update.message.message_id)


async def search_fuel_price(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str):
    """Search for specific location fuel price"""
    if not update.message:
        return

    # Try China first
    china_data = await fetch_fuel_data(CHINA_DATA_URL)
    if china_data:
        for code, info in china_data.items():
            province = info.get('province', '').lower()
            if query in province or query in code:
                text = format_china_province(info, china_data)  # Pass all_data for ranking
                await send_search_result(context, update.message.chat_id, text, parse_mode="MarkdownV2")
                await delete_user_command(context, update.message.chat_id, update.message.message_id)
                return

    # Try global - use SUPPORTED_COUNTRIES for better matching
    global_data = await fetch_fuel_data(GLOBAL_DATA_URL)
    if global_data:
        # First try exact code match
        query_upper = query.upper()
        if query_upper in global_data:
            text = format_global_country(global_data[query_upper], global_data, query_upper)
            await send_search_result(context, update.message.chat_id, text, parse_mode="MarkdownV2")
            await delete_user_command(context, update.message.chat_id, update.message.message_id)
            return

        # Try matching with SUPPORTED_COUNTRIES
        for country_code, country_info in SUPPORTED_COUNTRIES.items():
            country_name_cn = country_info.get('name', '').lower()
            # Check if query matches country code or Chinese name
            if query in country_code.lower() or query in country_name_cn:
                # Find in global data
                for code, fuel_info in global_data.items():
                    if code.upper() == country_code or country_code in code.upper():
                        text = format_global_country(fuel_info, global_data, country_code)
                        await send_search_result(context, update.message.chat_id, text, parse_mode="MarkdownV2")
                        await delete_user_command(context, update.message.chat_id, update.message.message_id)
                        return

        # Fallback: search by country name in global data
        for code, info in global_data.items():
            country = info.get('country', '').lower()
            if query in country or query in code.lower():
                text = format_global_country(info, global_data, code)
                await send_search_result(context, update.message.chat_id, text, parse_mode="MarkdownV2")
                await delete_user_command(context, update.message.chat_id, update.message.message_id)
                return

    # Not found
    await send_error(
        context,
        update.message.chat_id,
        f"未找到 '{query}' 的油价数据\n\n"
        "提示: 使用 /fuel rankings 查看所有国家",
        parse_mode="MarkdownV2"
    )
    await delete_user_command(context, update.message.chat_id, update.message.message_id)


# Register command
command_factory.register_command("fuel", fuel_command, permission=Permission.NONE, description="🛢️ 查询全球和中国油价（汽油+柴油）")
