import logging

from telegram import Update
from telegram.ext import ContextTypes

from commands.google_play_modules import GooglePlayService
from utils.command_factory import command_factory
from utils.constants import (
    DEFAULT_LANGUAGE_CODE,
    GOOGLE_PLAY_DEFAULT_COUNTRIES,
)
from utils.formatter import foldable_text_v2
from utils.message_manager import delete_user_command, send_help
from utils.permissions import Permission

# Configure logging
logger = logging.getLogger(__name__)

# 使用 constants.py 中定义的默认搜索国家
DEFAULT_SEARCH_COUNTRIES = GOOGLE_PLAY_DEFAULT_COUNTRIES


async def googleplay_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handles the /gp command to query Google Play app information."""
    if not update.message:
        return

    # 从 context.bot_data 获取服务实例
    service: GooglePlayService = context.bot_data.get("google_play_service")
    if not service:
        await send_help(
            context,
            update.message.chat_id,
            foldable_text_v2("❌ 错误：Google Play 查询服务未初始化。"),
            parse_mode="MarkdownV2",
        )
        return

    args_list = context.args

    if not args_list:
        help_message = """❓ 请输入应用名称或包名。

用法: /gp <应用名或包名> [国家代码] [语言代码]

示例:
/gp Youtube us en
/gp Tiktok (查 US, NG, TR)"""

        await send_help(
            context,
            update.message.chat_id,
            foldable_text_v2(help_message),
            parse_mode="MarkdownV2",
        )
        await delete_user_command(
            context, update.message.chat_id, update.message.message_id
        )
        return

    # Parse arguments
    query = args_list[0]
    user_country = None
    lang_code = DEFAULT_LANGUAGE_CODE.lower()

    if len(args_list) > 1:
        # 尝试使用统一国家映射工具解析（支持国家代码、中文名、英文名）
        from utils.country_mapper import get_country_code

        resolved_country = get_country_code(args_list[1])
        if resolved_country:
            user_country = resolved_country
            if len(args_list) > 2:
                lang_code = args_list[2].lower()
        else:
            # 如果不是国家参数，则视为语言代码
            lang_code = args_list[1].lower()

    countries_to_search = []
    if user_country:
        countries_to_search.append(user_country)
        search_info = f"区域: {user_country}, 语: {lang_code}"
    else:
        countries_to_search = DEFAULT_SEARCH_COUNTRIES
        search_info = f"区域: {', '.join(countries_to_search)}, 语言: {lang_code}"

    # Initial search message - use plain text, will be replaced
    search_message = f"🔍 正在搜索 Google Play 应用: {query} ({search_info})..."
    message = await context.bot.send_message(
        chat_id=update.message.chat_id,
        text=foldable_text_v2(search_message),
        parse_mode="MarkdownV2",
    )

    # 使用 Sensor Tower API 搜索应用（返回多个结果）
    try:
        search_results = await service.sensor_tower_api.search_apps(query, top_n=5)

        if not search_results:
            error_msg = f"😕 未找到应用: {query}"
            await service._handle_error(
                context,
                update.message.chat_id,
                update.message.message_id,
                error_msg,
                message,
            )
            return

        # 如果只有一个结果，直接查询详情
        if len(search_results) == 1:
            app_id = search_results[0]["appId"]
            app_title = search_results[0]["title"]
            await service._query_app_details(
                context,
                update.message.chat_id,
                update.message.message_id,
                app_id,
                app_title,
                countries_to_search,
                lang_code,
                message,
            )
            return

        # 多个结果：显示选择按钮
        await service._show_search_results(
            context,
            update.message.chat_id,
            update.message.message_id,
            query,
            search_results,
            countries_to_search,
            lang_code,
            message,
        )

    except Exception as e:
        logger.exception(f"搜索应用时出错: {e}")
        await service._handle_error(
            context,
            update.message.chat_id,
            update.message.message_id,
            f"❌ 搜索失败: {type(e).__name__}",
            message,
        )


async def googleplay_callback_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handles callback queries from search result buttons."""
    query = update.callback_query
    if not query:
        return

    await query.answer()

    # 从 context.bot_data 获取服务实例
    service: GooglePlayService = context.bot_data.get("google_play_service")
    if not service:
        await query.edit_message_text("❌ 错误：Google Play 查询服务未初始化。")
        return

    callback_data = query.data
    if not callback_data or not callback_data.startswith("gp_"):
        return

    # Parse callback data: gp_索引|国家列表|消息ID
    parts = callback_data[3:].split("|")
    if len(parts) < 2:
        await query.edit_message_text("❌ 无效的回调数据")
        return

    # 处理取消按钮
    if parts[0] == "cancel":
        try:
            await query.message.delete()
            user_message_id = int(parts[1])
            await delete_user_command(context, query.message.chat_id, user_message_id)
        except Exception as e:
            logger.error(f"取消操作失败: {e}")
        return

    # 解析选择的应用索引
    try:
        app_index = int(parts[0])
        countries = parts[1].split(",")
        user_message_id = int(parts[2])
    except (ValueError, IndexError) as e:
        logger.error(f"解析回调数据失败: {e}")
        await query.edit_message_text("❌ 数据解析错误")
        return

    # 从缓存中获取搜索结果
    cache_key = f"google_play:search:{query.message.chat_id}:{user_message_id}"
    search_data = await service.cache_manager.load_cache(
        cache_key, subdirectory="google_play"
    )

    if not search_data:
        await query.edit_message_text(
            "❌ 搜索结果已过期，请重新搜索",
            reply_markup=None,
        )
        await delete_user_command(context, query.message.chat_id, user_message_id)
        return

    search_results = search_data.get("results", [])
    lang_code = search_data.get("lang_code", DEFAULT_LANGUAGE_CODE)

    if app_index >= len(search_results):
        await query.edit_message_text("❌ 应用索引无效")
        return

    selected_app = search_results[app_index]
    app_id = selected_app["appId"]
    app_title = selected_app["title"]

    # 查询应用详情
    await service._query_app_details(
        context,
        query.message.chat_id,
        user_message_id,
        app_id,
        app_title,
        countries,
        lang_code,
        query.message,
    )


# Register commands
command_factory.register_command(
    "gp",
    googleplay_command,
    permission=Permission.USER,
    description="Google Play应用价格查询",
)


async def google_play_clear_item_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """清理指定 Google Play 应用（包名）的缓存（Redis+MySQL）。用法: /gp_clearitem <包名> [国家...] [语言]"""
    if not update.message:
        return

    service: GooglePlayService = context.bot_data.get("google_play_service")
    db_manager = context.bot_data.get("price_history_manager")

    # 管理员判定
    user_manager = context.bot_data.get("user_cache_manager")
    if not user_manager or not update.effective_user:
        return
    user_id = update.effective_user.id
    if not (
        await user_manager.is_super_admin(user_id) or await user_manager.is_admin(user_id)
    ):
        from utils.message_manager import send_error
        await send_error(context, update.message.chat_id, "❌ 你没有缓存管理权限。")
        return

    # 删除用户命令消息
    await delete_user_command(
        context, update.message.chat_id, update.message.message_id
    )

    if not service or not service.cache_manager:
        await send_help(
            context,
            update.message.chat_id,
            foldable_text_v2("❌ 错误：Google Play 查询服务未初始化。"),
            parse_mode="MarkdownV2",
        )
        return

    if not context.args:
        await send_help(
            context,
            update.message.chat_id,
            foldable_text_v2("❌ 用法: /gp_clearitem <包名> [国家...]"),
            parse_mode="MarkdownV2",
        )
        return

    package_name = context.args[0].strip()
    # 解析可选国家
    extra = context.args[1:] if len(context.args) > 1 else []
    from utils.country_mapper import get_country_code

    countries = []
    for p in extra:
        code = get_country_code(p)
        if code and code not in countries:
            countries.append(code)

    # 清理 Redis 缓存（所有语言）
    try:
        if countries:
            for c in countries:
                prefix = f"google_play:app:{package_name}:{c.upper()}:"
                await service.cache_manager.clear_cache(
                    key_prefix=prefix, subdirectory="google_play"
                )
        else:
            prefix = f"google_play:app:{package_name}:"
            await service.cache_manager.clear_cache(
                key_prefix=prefix, subdirectory="google_play"
            )
    except Exception as e:
        await send_help(
            context,
            update.message.chat_id,
            foldable_text_v2(f"❌ 清理 Redis 失败: {e!s}"),
            parse_mode="MarkdownV2",
        )
        return

    # 清理 MySQL 记录
    deleted_db = 0
    if db_manager:
        try:
            if countries:
                for c in countries:
                    deleted_db += await db_manager.delete_item(
                        service="google_play", item_id=package_name, country_code=c
                    )
            else:
                deleted_db += await db_manager.delete_item(
                    service="google_play", item_id=package_name
                )
        except Exception as e:
            await send_help(
                context,
                update.message.chat_id,
                foldable_text_v2(f"❌ 清理 MySQL 失败: {e!s}"),
                parse_mode="MarkdownV2",
            )
            return

    result_text = (
        f"✅ 已清理 Google Play 缓存\n"
        f"• 包名: {package_name}\n"
        f"• 范围: {', '.join([c.upper() for c in countries]) if countries else '所有国家'}\n"
        f"• MySQL 删除记录: {deleted_db}"
    )
    await send_help(
        context,
        update.message.chat_id,
        foldable_text_v2(result_text),
        parse_mode="MarkdownV2",
    )


command_factory.register_command(
    "gp_clearitem",
    google_play_clear_item_command,
    permission=Permission.ADMIN,
    description="清理Google Play指定包名缓存（Redis+MySQL）",
)


# =============================================================================
# 价格辅助函数（本地扩展）
# =============================================================================
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




# =============================================================================
# Inline 执行入口
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
