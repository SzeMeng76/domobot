import asyncio
import logging
import re

# 使用 HTML 解析器版本（更准确可靠）
from utils.google_play_html_scraper import app as gp_app
from utils.google_play_html_scraper import search
# 保留异常类的导入
try:
    from google_play_scraper import exceptions as gp_exceptions
except:
    # 如果导入失败，定义一个简单的异常类
    class NotFoundError(Exception):
        pass
    class gp_exceptions:
        NotFoundError = NotFoundError

from telegram import Update
from telegram.ext import ContextTypes

from utils.command_factory import command_factory
from utils.config_manager import config_manager
from utils.country_data import SUPPORTED_COUNTRIES, get_country_flag
from utils.formatter import foldable_text_v2, foldable_text_with_markdown_v2
from utils.message_manager import delete_user_command, send_error, send_help, send_search_result, send_success
from utils.permissions import Permission
from utils.rate_converter import RateConverter


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Default search countries if none are specified by the user
DEFAULT_SEARCH_COUNTRIES = ["US", "NG", "TR"]

# Global cache_manager (will be set by main.py)
cache_manager = None


def set_cache_manager(manager):
    global cache_manager
    cache_manager = manager


# Global rate_converter (will be set by main.py)
rate_converter = None


def set_rate_converter(converter: RateConverter):
    global rate_converter
    rate_converter = converter


# Standard Emojis (no custom tg://emoji?id=...)
EMOJI_APP = "📱"
EMOJI_DEV = "👨‍💻"
EMOJI_RATING = "⭐️"
EMOJI_INSTALLS = "⬇️"
EMOJI_PRICE = "💰"
EMOJI_IAP = "🛒"
EMOJI_LINK = "🔗"
EMOJI_COUNTRY = "📍"
EMOJI_FLAG_PLACEHOLDER = "🏳️"  # Fallback if no custom emoji found


async def parse_and_convert_iap_price(price_str: str, rate_converter) -> tuple[str, str | None]:
    """
    Parse Google Play IAP price string and convert to CNY.
    Returns (original_price, cny_converted_info)
    
    Examples:
    - "每件NGN 150.00-NGN 99,900.00" -> ("每件NGN 150.00-NGN 99,900.00", "约 ¥10.50-¥700.00")
    - "$0.99 - $99.99 per item" -> ("$0.99 - $99.99 per item", "约 ¥7.00-¥710.00")
    """
    if not price_str or not rate_converter or not rate_converter.rates:
        return price_str, None
    
    # Extended pattern to match more currency formats
    # Matches: NGN 150.00, $0.99, USD 10.50, ₹100, etc.
    price_pattern = r'([A-Z]{3}|[¥€£$₹₦₩₽₪₸₴₦₵₡₲₪₫₨₩₭₯₰₱₲₳₴₵₶₷₸₹₺₻₼₽₾₿＄￠￡￢￣￤￥￦])[\s]*([\d,]+\.?\d*)'
    matches = re.findall(price_pattern, price_str)
    
    if not matches:
        return price_str, None
    
    # Common currency symbol mappings
    symbol_to_code = {
        '$': 'USD', '€': 'EUR', '£': 'GBP', '¥': 'JPY', '￥': 'CNY',
        '₹': 'INR', '₦': 'NGN', '₩': 'KRW', '₽': 'RUB', '₪': 'ILS',
        '₸': 'KZT', '₴': 'UAH', '₵': 'GHS', '₡': 'CRC', '₲': 'PYG',
        '₫': 'VND', '₨': 'PKR', '₭': 'LAK', '₯': 'GRD', '₱': 'PHP',
        '₳': 'ARA', '₶': 'LVL', '₷': 'SPL', '₺': 'TRY', '₻': 'TMT',
        '₼': 'AZN', '₾': 'GEL', '₿': 'BTC', '＄': 'USD', '￠': 'USD',
        '￡': 'GBP', '￢': 'GBP', '￤': 'ITL', '￦': 'KRW'
    }
    
    try:
        converted_prices = []
        
        for currency_symbol, price_value in matches:
            # Clean price value
            clean_price = price_value.replace(',', '')
            price_float = float(clean_price)
            
            # Convert currency symbol to standard code
            if len(currency_symbol) == 3 and currency_symbol.isalpha():
                # Already a 3-letter code
                currency_code = currency_symbol.upper()
            else:
                # Map symbol to code
                currency_code = symbol_to_code.get(currency_symbol, 'USD')
            
            # Convert currency to CNY using fallback function
            from commands.rate_command import convert_currency_with_fallback
            cny_price = await convert_currency_with_fallback(price_float, currency_code, "CNY")
            if cny_price is not None:
                converted_prices.append(f"¥{cny_price:.2f}")
            else:
                logger.warning(f"Currency {currency_code} conversion failed (no source supports it)")
        
        if converted_prices:
            if len(converted_prices) == 1:
                cny_info = f"约 {converted_prices[0]}"
            elif len(converted_prices) == 2:
                cny_info = f"约 {converted_prices[0]}-{converted_prices[1]}"
            else:
                # More than 2 prices, show range
                cny_info = f"约 {converted_prices[0]}-{converted_prices[-1]}"
            
            return price_str, cny_info
            
    except (ValueError, TypeError) as e:
        logger.warning(f"Failed to parse/convert IAP price '{price_str}': {e}")
    
    return price_str, None


async def get_app_details_for_country(app_id: str, country: str, lang_code: str) -> tuple[str, dict | None, str | None]:
    """Asynchronously fetches app details for a specific country/region with caching."""
    cache_key = f"gp_app_{app_id}_{country}_{lang_code}"

    # Check cache first (cache for 6 hours)
    cached_data = await cache_manager.load_cache(
        cache_key, max_age_seconds=config_manager.config.google_play_app_cache_duration, subdirectory="google_play"
    )
    if cached_data:
        return country, cached_data, None

    try:
        # google_play_scraper is not async, so run in executor
        app_details = await asyncio.to_thread(gp_app, app_id, lang=lang_code, country=country)

        # Save to cache
        await cache_manager.save_cache(cache_key, app_details, subdirectory="google_play")

        return country, app_details, None
    except gp_exceptions.NotFoundError:
        return country, None, f"在该区域 ({country}) 未找到应用"
    except Exception as e:
        logger.warning(f"Failed to get app details for {country}: {e}")
        return country, None, f"查询 {country} 区出错: {type(e).__name__}"


async def googleplay_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /gp command to query Google Play app information."""
    if not update.message:
        return

    args_list = context.args

    if not args_list:
        help_message = """❓ 请输入应用名称或包名。

用法: /gp <应用名或包名> [国家代码1] [国家代码2] ...

示例:
/gp Youtube
/gp Google Maps us
/gp ChatGPT in ng (查询印度和尼日利亚)
/gp "Red Dead Redemption" us cn jp
/gp TikTok (查 US, NG, TR 默认区域)

注: 多词应用名会自动识别，国家代码为2字母代码，支持查询多个国家"""
        from utils.config_manager import get_config

        await send_help(context, update.message.chat_id, foldable_text_v2(help_message), parse_mode="MarkdownV2")
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        return

    # Parse arguments - support multiple country codes
    user_countries = []
    lang_code = "zh-cn"  # Fixed default language
    
    # Find all 2-letter country codes from the end of arguments
    query_args = args_list[:]
    
    # Start from the end and find valid country codes
    while len(query_args) > 1:  # Keep at least one arg for app name
        last_arg = query_args[-1]
        if (len(last_arg) == 2 and 
            last_arg.isalpha() and 
            last_arg.upper() in SUPPORTED_COUNTRIES):
            user_countries.insert(0, last_arg.upper())  # Insert at beginning to maintain order
            query_args.pop()  # Remove from query args
        else:
            break  # Stop if we find a non-country code
    
    # The remaining args form the app name query
    query = " ".join(query_args)

    countries_to_search = []
    if user_countries:
        countries_to_search = user_countries
        initial_search_country = user_countries[0]
        search_info = f"区域: {', '.join(user_countries)}"
    else:
        countries_to_search = DEFAULT_SEARCH_COUNTRIES
        initial_search_country = DEFAULT_SEARCH_COUNTRIES[0]
        search_info = f"区域: {', '.join(countries_to_search)}"

    # Initial search message - use plain text, will be replaced
    search_message = f"🔍 正在搜索 Google Play 应用: {query} ({search_info})..."
    message = await context.bot.send_message(
        chat_id=update.message.chat_id, text=foldable_text_v2(search_message), parse_mode="MarkdownV2"
    )

    app_id = None
    app_title_short = query
    icon_url = None

    # Search for App ID with caching
    search_cache_key = f"gp_search_{query}_{initial_search_country}_{lang_code}"
    cached_search = await cache_manager.load_cache(
        search_cache_key,
        max_age_seconds=config_manager.config.google_play_search_cache_duration,
        subdirectory="google_play",
    )

    try:
        if cached_search:
            app_info_short = cached_search.get("results", [{}])[0] if cached_search.get("results") else None
        else:
            # HTML 解析器版本返回准确的搜索结果
            search_results = await asyncio.to_thread(
                search, query, n_hits=1, lang=lang_code, country=initial_search_country
            )
            if search_results:
                # Cache the search results as a dictionary
                cache_data = {"results": search_results, "query": query}
                await cache_manager.save_cache(search_cache_key, cache_data, subdirectory="google_play")
                app_info_short = search_results[0]
            else:
                app_info_short = None

        if app_info_short:
            # HTML 解析器保证 appId 总是存在
            app_id = app_info_short["appId"]
            # HTML 解析器的 title 可能是 None，使用 or 确保有值
            app_title_short = app_info_short.get("title") or query
            icon_url = app_info_short.get("icon")
        else:
            error_message = f"😕 在区域 {initial_search_country} 未找到应用: {query}"
            await message.delete()
            await send_error(context, message.chat_id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
            await delete_user_command(context, message.chat_id, update.message.message_id)
            return

    except Exception as e:
        logger.exception(f"Error searching for app ID (country: {initial_search_country}): {e}")
        error_message = f"❌ 搜索应用 ID 时出错 ({initial_search_country}): {type(e).__name__}"
        await message.delete()
        await send_error(context, message.chat_id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        await delete_user_command(context, message.chat_id, update.message.message_id)
        return

    # Update with progress message
    progress_message = f"""✅ 找到应用: {app_title_short} ({app_id})
⏳ 正在获取以下区域的详细信息: {", ".join(countries_to_search)}..."""
    await message.edit_text(foldable_text_v2(progress_message), parse_mode="MarkdownV2")

    # Concurrently fetch details for all countries
    tasks = [get_app_details_for_country(app_id, c, lang_code) for c in countries_to_search]
    results = await asyncio.gather(*tasks)

    # Build the raw text message (no escaping, no markdown formatting)
    raw_message_parts = []
    preview_trigger_link = ""

    # Get basic app info from first valid result
    first_valid_details = next((details for _, details, _ in results if details), None)
    if first_valid_details:
        app_title_short = first_valid_details.get("title", app_title_short)
        developer = first_valid_details.get("developer", "N/A")
        icon_url = first_valid_details.get("icon", icon_url)

        if icon_url:
            preview_trigger_link = f"[\u200b]({icon_url})"

        raw_message_parts.append(f"{EMOJI_APP} *应用名称: {app_title_short}*")
        raw_message_parts.append(f"{EMOJI_DEV} 开发者: {developer}")
    else:
        raw_message_parts.append(f"{EMOJI_APP} {app_title_short}")

    if preview_trigger_link:
        raw_message_parts.insert(0, preview_trigger_link)

    raw_message_parts.append("")

    # Process results for each country
    for i, (country_code, details, error_msg) in enumerate(results):
        country_info = SUPPORTED_COUNTRIES.get(country_code, {})
        flag = get_country_flag(country_code) or EMOJI_FLAG_PLACEHOLDER
        country_name = country_info.get("name", country_code)

        raw_message_parts.append(f"{EMOJI_COUNTRY} {flag} {country_name} ({country_code})")

        if details:
            score = details.get("score")
            installs = details.get("installs", "N/A")
            app_url_country = details.get("url", "")

            score_str = f"{score:.1f}/5.0" if score is not None else "暂无评分"
            rating_stars = ""
            if score is not None:
                rounded_score = round(score)
                rating_stars = "⭐" * rounded_score + "☆" * (5 - rounded_score)
            else:
                rating_stars = "☆☆☆☆☆"

            is_free = details.get("free", False)
            price = details.get("price", 0)
            currency = details.get("currency", "")
            price_str = "免费"
            
            if not is_free and price > 0 and currency:
                price_str = f"{price} {currency}"
                # Add CNY conversion for app price
                if rate_converter and rate_converter.rates and currency.upper() in rate_converter.rates:
                    try:
                        cny_price = await rate_converter.convert(float(price), currency.upper(), "CNY")
                        if cny_price is not None:
                            price_str += f" (约 ¥{cny_price:.2f})"
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Failed to convert app price {price} {currency} to CNY: {e}")
            elif not is_free and price == 0 and currency:
                price_str = f"0 {currency} (可能免费)"
            elif is_free and price > 0:
                price_str = f"免费 (原价 {price} {currency}"
                # Add CNY conversion for original price
                if rate_converter and rate_converter.rates and currency.upper() in rate_converter.rates:
                    try:
                        cny_price = await rate_converter.convert(float(price), currency.upper(), "CNY")
                        if cny_price is not None:
                            price_str += f", 约 ¥{cny_price:.2f}"
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Failed to convert original price {price} {currency} to CNY: {e}")
                price_str += ")"
            elif not is_free and price == 0 and not currency:
                price_str = "价格未知"

            offers_iap = details.get("offersIAP", False)
            iap_range_raw = details.get("IAPRange")
            iap_price_raw = details.get("inAppProductPrice")
            iap_str = "无"
            
            if offers_iap:
                if iap_range_raw:
                    original_price, cny_info = await parse_and_convert_iap_price(iap_range_raw, rate_converter)
                    iap_str = original_price
                    if cny_info:
                        iap_str += f" ({cny_info})"
                elif iap_price_raw:
                    original_price, cny_info = await parse_and_convert_iap_price(iap_price_raw, rate_converter)
                    iap_str = original_price
                    if cny_info:
                        iap_str += f" ({cny_info})"
                else:
                    iap_str = "有 (价格范围未知)"
            else:
                # 即使offersIAP为False，也检查是否有价格信息（可能是检测bug）
                if iap_price_raw:
                    original_price, cny_info = await parse_and_convert_iap_price(iap_price_raw, rate_converter)
                    iap_str = f"{original_price} (检测到IAP)"
                    if cny_info:
                        iap_str = f"{original_price} ({cny_info}, 检测到IAP)"
                elif iap_range_raw:
                    original_price, cny_info = await parse_and_convert_iap_price(iap_range_raw, rate_converter)
                    iap_str = f"{original_price} (检测到IAP)"
                    if cny_info:
                        iap_str = f"{original_price} ({cny_info}, 检测到IAP)"

            raw_message_parts.append(f"  {EMOJI_RATING} 评分: {rating_stars} ({score_str})")
            raw_message_parts.append(f"  {EMOJI_INSTALLS} 安装量: {installs}")
            raw_message_parts.append(f"  {EMOJI_PRICE} 价格: {price_str}")
            raw_message_parts.append(f"  {EMOJI_IAP} 内购: {iap_str}")
            if app_url_country:
                raw_message_parts.append(f"  {EMOJI_LINK} [Google Play 链接]({app_url_country})")

        else:
            raw_message_parts.append(f"  😕 {error_msg}")

        # Add a blank line between countries (except for the last one)
        if i < len(results) - 1:
            raw_message_parts.append("")

    # Join the raw message
    raw_final_message = "\n".join(raw_message_parts).strip()

    # 删除搜索进度消息，然后发送结果
    try:
        await message.delete()
        
        # 使用统一API发送搜索结果
        from utils.message_manager import send_search_result
        await send_search_result(
            context,
            update.message.chat_id,
            foldable_text_with_markdown_v2(raw_final_message),
            parse_mode="MarkdownV2",
            disable_web_page_preview=False
        )
        
        # 删除用户命令消息
        await delete_user_command(context, update.message.chat_id, update.message.message_id)

    except Exception as e:
        logger.exception(f"Error editing final result: {e}")
        error_message = f"❌ 发送结果时出错。错误类型: {type(e).__name__}"
        await message.delete()
        await send_error(context, message.chat_id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        await delete_user_command(context, message.chat_id, update.message.message_id)


async def google_play_clean_cache_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /gp_cleancache command to clear Google Play related caches."""
    if not update.message:
        return

    try:
        # 从 context 获取缓存管理器
        cache_mgr = context.bot_data.get("cache_manager")
        if cache_mgr:
            await cache_mgr.clear_cache(subdirectory="google_play")
            success_message = "✅ Google Play 缓存已清理。"
        else:
            success_message = "⚠️ 缓存管理器未初始化。"
        await send_success(context, update.message.chat_id, foldable_text_v2(success_message), parse_mode="MarkdownV2")
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
    except Exception as e:
        logger.error(f"Error clearing Google Play cache: {e}")
        error_message = f"❌ 清理 Google Play 缓存时发生错误: {e!s}"
        await send_error(context, update.message.chat_id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        await delete_user_command(context, update.message.chat_id, update.message.message_id)


# Alias for the command
gp_command = googleplay_command
gp_clean_cache_command = google_play_clean_cache_command

# Register commands
command_factory.register_command("gp", gp_command, permission=Permission.USER, description="Google Play应用价格查询")
# 已迁移到统一缓存管理命令 /cleancache
# command_factory.register_command(
#     "gp_cleancache", gp_clean_cache_command, permission=Permission.ADMIN, description="清理Google Play缓存"
# )


# =============================================================================
# Inline 搜索入口（返回多个结果）
# =============================================================================

async def handle_inline_googleplay_search(
    keyword: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> list:
    """
    Inline 搜索 Google Play 应用（参考 appstore 的 handle_inline_appstore_search）
    返回多个搜索结果供用户选择

    Args:
        keyword: 搜索关键词，格式为 "应用名称" 或 "应用名称 US NG TR"
        context: Telegram context

    Returns:
        list: InlineQueryResult 列表
    """
    from telegram import InlineQueryResultArticle, InputTextMessageContent
    from uuid import uuid4

    if not keyword.strip():
        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="🔍 请输入搜索关键词",
                description="例如: gp youtube$ 或 gp chatgpt us ng tr$",
                input_message_content=InputTextMessageContent(
                    message_text="🔍 请输入应用名称搜索 Google Play\n\n"
                    "支持格式:\n"
                    "• gp youtube$\n"
                    "• gp chatgpt$\n"
                    "• gp tiktok us ng tr$ (多国价格)"
                ),
            )
        ]

    try:
        # 解析应用名称和国家参数
        args_list = keyword.strip().split()

        # 从末尾查找国家代码
        user_countries = []
        query_args = args_list[:]

        while len(query_args) > 1:  # 至少保留一个参数作为应用名
            last_arg = query_args[-1]
            if (len(last_arg) == 2 and
                last_arg.isalpha() and
                last_arg.upper() in SUPPORTED_COUNTRIES):
                user_countries.insert(0, last_arg.upper())
                query_args.pop()
            else:
                break

        # 剩余参数组成应用名称
        query = " ".join(query_args)

        if not query:
            return [
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title="❌ 请输入应用名称",
                    description="搜索关键词不能为空",
                    input_message_content=InputTextMessageContent(
                        message_text="❌ 请输入应用名称"
                    ),
                )
            ]

        # 确定要查询的国家列表
        countries_to_check = user_countries if user_countries else DEFAULT_SEARCH_COUNTRIES
        initial_search_country = countries_to_check[0]

        lang_code = "zh-cn"

        # 执行搜索
        logger.info(f"Inline Google Play 搜索: '{query}' in {initial_search_country}, countries: {countries_to_check}")

        # 搜索应用（最多10个结果）
        search_cache_key = f"gp_search_{query}_{initial_search_country}_{lang_code}"
        cached_search = await cache_manager.load_cache(
            search_cache_key,
            max_age_seconds=config_manager.config.google_play_search_cache_duration,
            subdirectory="google_play",
        )

        if cached_search:
            search_results = cached_search.get("results", [])
        else:
            search_results = await asyncio.to_thread(
                search, query, n_hits=10, lang=lang_code, country=initial_search_country
            )
            if search_results:
                cache_data = {"results": search_results, "query": query}
                await cache_manager.save_cache(search_cache_key, cache_data, subdirectory="google_play")

        if not search_results:
            return [
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title="❌ 未找到结果",
                    description=f"关键词: {query}",
                    input_message_content=InputTextMessageContent(
                        message_text=f"❌ 未找到与 \"{query}\" 相关的应用"
                    ),
                )
            ]

        # 构建搜索结果列表（最多10个）
        results = []
        for app_info in search_results[:10]:
            app_id = app_info.get("appId")
            app_title = app_info.get("title", "未知应用")
            developer = app_info.get("developer", "")

            if not app_id:
                continue

            # 构建描述
            description_parts = []
            if developer:
                description_parts.append(developer)

            # 获取价格信息（如果有）
            price = app_info.get("price")
            if price:
                description_parts.append(price)

            description = " | ".join(description_parts) if description_parts else "点击查看多国价格"

            # 获取多国详细信息
            try:
                # 并发获取所有国家的详细信息
                tasks = [get_app_details_for_country(app_id, c, lang_code) for c in countries_to_check]
                country_results = await asyncio.gather(*tasks)

                # 构建消息
                raw_message_parts = []

                # 获取基本信息
                first_valid_details = next((details for _, details, _ in country_results if details), None)
                if first_valid_details:
                    app_title = first_valid_details.get("title", app_title)
                    developer = first_valid_details.get("developer", "N/A")
                    icon_url = first_valid_details.get("icon")

                    if icon_url:
                        raw_message_parts.append(f"[\u200b]({icon_url})")

                    raw_message_parts.append(f"{EMOJI_APP} *应用名称: {app_title}*")
                    raw_message_parts.append(f"{EMOJI_DEV} 开发者: {developer}")
                    raw_message_parts.append("")

                    # 添加各国信息
                    for i, (country, details, error_msg) in enumerate(country_results):
                        country_info = SUPPORTED_COUNTRIES.get(country, {})
                        country_name = country_info.get("name", country)
                        flag_emoji = get_country_flag(country)

                        raw_message_parts.append(f"{EMOJI_COUNTRY} *{flag_emoji} {country_name} ({country})*")

                        if details:
                            score = details.get("score", 0)
                            score_str = f"{score:.1f}" if score else "N/A"
                            rating_stars = "⭐" * int(round(score)) if score else "N/A"
                            installs = details.get("installs", "N/A")

                            # 价格信息
                            is_free = details.get("free", True)
                            price_raw = details.get("price")
                            if is_free:
                                price_str = "免费"
                            elif price_raw:
                                price_str = str(price_raw)
                            else:
                                price_str = "价格未知"

                            # 内购信息
                            offers_iap = details.get("offersIAP", False)
                            iap_range_raw = details.get("IAPRange")
                            iap_price_raw = details.get("inAppProductPrice")
                            iap_str = "无"

                            if offers_iap:
                                if iap_range_raw:
                                    original_price, cny_info = await parse_and_convert_iap_price(iap_range_raw, rate_converter)
                                    iap_str = original_price
                                    if cny_info:
                                        iap_str += f" ({cny_info})"
                                elif iap_price_raw:
                                    original_price, cny_info = await parse_and_convert_iap_price(iap_price_raw, rate_converter)
                                    iap_str = original_price
                                    if cny_info:
                                        iap_str += f" ({cny_info})"
                                else:
                                    iap_str = "有 (价格范围未知)"

                            raw_message_parts.append(f"  {EMOJI_RATING} 评分: {rating_stars} ({score_str})")
                            raw_message_parts.append(f"  {EMOJI_INSTALLS} 安装量: {installs}")
                            raw_message_parts.append(f"  {EMOJI_PRICE} 价格: {price_str}")
                            raw_message_parts.append(f"  {EMOJI_IAP} 内购: {iap_str}")
                        else:
                            raw_message_parts.append(f"  😕 {error_msg}")

                        # 国家之间添加空行
                        if i < len(country_results) - 1:
                            raw_message_parts.append("")

                    raw_final_message = "\n".join(raw_message_parts).strip()
                    message_text = foldable_text_with_markdown_v2(raw_final_message)
                    parse_mode = "MarkdownV2"

                    # 更新描述，显示查询的国家
                    if len(countries_to_check) > 1:
                        countries_str = ", ".join([c.upper() for c in countries_to_check[:3]])
                        if len(countries_to_check) > 3:
                            countries_str += f" +{len(countries_to_check) - 3}"
                        description = f"多国价格: {countries_str}"
                    elif first_valid_details:
                        # 单国查询，显示价格
                        is_free = first_valid_details.get("free", True)
                        if is_free:
                            description = "免费"
                        else:
                            price_raw = first_valid_details.get("price")
                            if price_raw:
                                description = str(price_raw)

                else:
                    # 没有获取到任何详细信息
                    message_text = f"📱 *{app_title}*\n\n❌ 获取详细信息失败\n\n💡 请使用 `/gp {query}` 重试"
                    parse_mode = "Markdown"

            except Exception as e:
                logger.warning(f"获取应用 {app_id} 详情失败: {e}")
                message_text = f"📱 *{app_title}*\n\n❌ 获取详细信息失败\n\n💡 请使用 `/gp {query}` 重试"
                parse_mode = "Markdown"

            results.append(
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title=f"📱 {app_title}",
                    description=description,
                    input_message_content=InputTextMessageContent(
                        message_text=message_text,
                        parse_mode=parse_mode,
                    ),
                )
            )

        return results

    except Exception as e:
        logger.error(f"Inline Google Play 搜索失败: {e}", exc_info=True)
        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="❌ 搜索失败",
                description=str(e)[:100],
                input_message_content=InputTextMessageContent(
                    message_text=f"❌ 搜索失败: {str(e)}"
                ),
            )
        ]
