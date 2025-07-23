import logging
import asyncio

from google_play_scraper import search, app as gp_app, exceptions as gp_exceptions
from telegram import Update
from telegram.ext import ContextTypes
from utils.country_data import SUPPORTED_COUNTRIES, get_country_flag
from utils.cache_manager import CacheManager
from utils.rate_converter import RateConverter
from utils.command_factory import command_factory
from utils.permissions import Permission
from utils.formatter import foldable_text_v2, foldable_text_with_markdown_v2
from utils.config_manager import config_manager, get_config
from utils.message_manager import schedule_message_deletion

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Default search countries if none are specified by the user
DEFAULT_SEARCH_COUNTRIES = ["US", "NG", "TR"]

# Initialize CacheManager
cache_manager = CacheManager()

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
EMOJI_FLAG_PLACEHOLDER = "🏳️" # Fallback if no custom emoji found

async def get_app_details_for_country(app_id: str, country: str, lang_code: str) -> tuple[str, dict | None, str | None]:
    """Asynchronously fetches app details for a specific country/region with caching."""
    cache_key = f"gp_app_{app_id}_{country}_{lang_code}"
    
    # Check cache first (cache for 6 hours)
    cached_data = cache_manager.load_cache(cache_key, max_age_seconds=config_manager.config.google_play_app_cache_duration, subdirectory="google_play")
    if cached_data:
        return country, cached_data, None
    
    try:
        # google_play_scraper is not async, so run in executor
        app_details = await asyncio.to_thread(gp_app, app_id, lang=lang_code, country=country)
        
        # Save to cache
        cache_manager.save_cache(cache_key, app_details, subdirectory="google_play")
        
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

用法: /gp <应用名或包名> [国家代码] [语言代码]

示例: 
/gp Youtube us en
/gp Tiktok (查 US, NG, TR)"""
        from utils.config_manager import get_config
        config = get_config()
        sent_message = await context.bot.send_message(
            chat_id=update.message.chat_id,
            text=foldable_text_v2(help_message),
            parse_mode="MarkdownV2",
        )
        schedule_message_deletion(
            chat_id=sent_message.chat_id,
            message_id=sent_message.message_id,
            delay=config.auto_delete_delay,
            user_id=update.effective_user.id,
        )
        if config.delete_user_commands:
            schedule_message_deletion(
                chat_id=update.message.chat_id,
                message_id=update.message.message_id,
                delay=config.user_command_delete_delay,
                task_type="user_command",
                user_id=update.effective_user.id,
            )
        return

    # Parse arguments
    query = args_list[0]
    user_country = None
    lang_code = 'zh-cn'.lower()

    if len(args_list) > 1:
        if len(args_list[1]) == 2 and args_list[1].isalpha():
            user_country = args_list[1].upper()
            if len(args_list) > 2:
                lang_code = args_list[2].lower()
        else:
            lang_code = args_list[1].lower()

    countries_to_search = []
    if user_country:
        countries_to_search.append(user_country)
        initial_search_country = user_country
        search_info = f"区域: {user_country}, 语: {lang_code}"
    else:
        countries_to_search = DEFAULT_SEARCH_COUNTRIES
        initial_search_country = DEFAULT_SEARCH_COUNTRIES[0]
        search_info = f"区域: {', '.join(countries_to_search)}, 语言: {lang_code}"

    # Initial search message - use plain text, will be replaced
    search_message = f"🔍 正在搜索 Google Play 应用: {query} ({search_info})..."
    message = await context.bot.send_message(
        chat_id=update.message.chat_id,
        text=foldable_text_v2(search_message),
        parse_mode="MarkdownV2"
    )

    app_id = None
    app_title_short = query
    icon_url = None

    # Search for App ID with caching
    search_cache_key = f"gp_search_{query}_{initial_search_country}_{lang_code}"
    cached_search = cache_manager.load_cache(search_cache_key, max_age_seconds=config_manager.config.google_play_search_cache_duration, subdirectory="google_play")
    
    try:
        if cached_search:
            app_info_short = cached_search.get("results", [{}])[0] if cached_search.get("results") else None
        else:
            search_results = await asyncio.to_thread(search, query, n_hits=1, lang=lang_code, country=initial_search_country)
            if search_results:
                # Cache the search results as a dictionary
                cache_data = {"results": search_results, "query": query}
                cache_manager.save_cache(search_cache_key, cache_data, subdirectory="google_play")
                app_info_short = search_results[0]
            else:
                app_info_short = None
                
        if app_info_short:
            app_id = app_info_short['appId']
            app_title_short = app_info_short.get('title', query)
            icon_url = app_info_short.get('icon')
        else:
            error_message = f"😕 在区域 {initial_search_country} 未找到应用: {query}"
            await message.edit_text(
                foldable_text_v2(error_message),
                "MarkdownV2"
            )
            schedule_message_deletion(message.chat_id, message.message_id, delay=5)
            return

    except Exception as e:
        logger.exception(f"Error searching for app ID (country: {initial_search_country}): {e}")
        error_message = f"❌ 搜索应用 ID 时出错 ({initial_search_country}): {type(e).__name__}"
        await message.edit_text(
            foldable_text_v2(error_message),
            "MarkdownV2"
        )
        schedule_message_deletion(message.chat_id, message.message_id, delay=5)
        return

    # Update with progress message
    progress_message = f"""✅ 找到应用: {app_title_short} ({app_id})
⏳ 正在获取以下区域的详细信息: {', '.join(countries_to_search)} (语言: {lang_code})..."""
    await message.edit_text(
        foldable_text_v2(progress_message),
        parse_mode="MarkdownV2"
    )

    # Concurrently fetch details for all countries
    tasks = [get_app_details_for_country(app_id, c, lang_code) for c in countries_to_search]
    results = await asyncio.gather(*tasks)

    # Build the raw text message (no escaping, no markdown formatting)
    raw_message_parts = []
    preview_trigger_link = ""

    # Get basic app info from first valid result
    first_valid_details = next((details for _, details, _ in results if details), None)
    if first_valid_details:
        app_title_short = first_valid_details.get('title', app_title_short)
        developer = first_valid_details.get('developer', 'N/A')
        icon_url = first_valid_details.get('icon', icon_url)

        if icon_url:
            preview_trigger_link = f'[\u200b]({icon_url})'

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
            score = details.get('score')
            installs = details.get('installs', 'N/A')
            app_url_country = details.get('url', '')

            score_str = f"{score:.1f}/5.0" if score is not None else "暂无评分"
            rating_stars = ""
            if score is not None:
                rounded_score = int(round(score))
                rating_stars = "⭐" * rounded_score + "☆" * (5 - rounded_score)
            else:
                rating_stars = "☆☆☆☆☆"

            is_free = details.get('free', False)
            price = details.get('price', 0)
            currency = details.get('currency', '')
            price_str = "免费"
            if not is_free and price > 0 and currency:
                price_str = f"{price} {currency}"
            elif not is_free and price == 0 and currency:
                price_str = f"0 {currency} (可能免费)"
            elif is_free and price > 0:
                price_str = f"免费 (原价 {price} {currency})"
            elif not is_free and price == 0 and not currency:
                price_str = "价格未知"

            offers_iap = details.get('offersIAP', False)
            iap_range_raw = details.get('IAPRange')
            iap_str = "无"
            if offers_iap and iap_range_raw:
                iap_str = f"{iap_range_raw}"
            elif offers_iap and not iap_range_raw:
                iap_str = "有 (范围未知)"

            raw_message_parts.append(f"  {EMOJI_RATING} 评分: {rating_stars} ({score_str})")
            raw_message_parts.append(f"  {EMOJI_INSTALLS} 安装量: {installs}")
            raw_message_parts.append(f"  {EMOJI_PRICE} 价格: {price_str}")
            raw_message_parts.append(f"  {EMOJI_IAP} 内购: {iap_str}")
            if app_url_country:
                raw_message_parts.append(f'  {EMOJI_LINK} [Google Play 链接]({app_url_country})')

        else:
            raw_message_parts.append(f"  😕 {error_msg}")
        
        # Add a blank line between countries (except for the last one)
        if i < len(results) - 1:
            raw_message_parts.append("")

    # Join the raw message
    raw_final_message = "\n".join(raw_message_parts).strip()

    # Apply formatting and folding through foldable_text_with_markdown_v2 (for links)
    try:
        await message.edit_text(
            foldable_text_with_markdown_v2(raw_final_message),
            parse_mode="MarkdownV2",
            disable_web_page_preview=False
        )
        
        # 添加自动删除逻辑
        from utils.config_manager import get_config
        config = get_config()
        
        # 获取消息 ID 和相关信息
        bot_message_id = message.message_id
        chat_id = update.message.chat_id
        user_command_id = update.message.message_id
        user_id = update.effective_user.id if update.effective_user else None
        
        # 使用 schedule_message_deletion 调度删除任务
        schedule_message_deletion(
            chat_id=chat_id,
            message_id=bot_message_id,
            delay=config.auto_delete_delay,
            task_type="bot_message",
            user_id=user_id
        )
        
        if config.delete_user_commands and user_command_id:
            schedule_message_deletion(
                chat_id=chat_id,
                message_id=user_command_id,
                delay=config.user_command_delete_delay,
                task_type="user_command",
                user_id=user_id
            )
        
        logger.info(f"🔧 Scheduled deletion for Google Play messages - Bot: {bot_message_id} (after {config.auto_delete_delay}s), User: {user_command_id} (after {config.user_command_delete_delay}s)")
            
    except Exception as e:
        logger.exception(f"Error editing final result: {e}")
        error_message = f"❌ 发送结果时出错。错误类型: {type(e).__name__}"
        await message.edit_text(
            foldable_text_v2(error_message),
            "MarkdownV2"
        )
        schedule_message_deletion(message.chat_id, message.message_id, delay=5)

async def google_play_clean_cache_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /gp_cleancache command to clear Google Play related caches."""
    if not update.message:
        return
        
    try:
        cache_manager.clear_cache(subdirectory="google_play")
        success_message = "✅ Google Play 缓存已清理。"
        config = get_config()
        sent_message = await context.bot.send_message(
            chat_id=update.message.chat_id,
            text=foldable_text_v2(success_message),
            parse_mode="MarkdownV2",
        )
        schedule_message_deletion(
            chat_id=sent_message.chat_id,
            message_id=sent_message.message_id,
            delay=config.auto_delete_delay,
            user_id=update.effective_user.id,
        )
        if config.delete_user_commands:
            schedule_message_deletion(
                chat_id=update.message.chat_id,
                message_id=update.message.message_id,
                delay=config.user_command_delete_delay,
                task_type="user_command",
                user_id=update.effective_user.id,
            )
    except Exception as e:
        logger.error(f"Error clearing Google Play cache: {e}")
        error_message = f"❌ 清理 Google Play 缓存时发生错误: {str(e)}"
        config = get_config()
        sent_message = await context.bot.send_message(
            chat_id=update.message.chat_id,
            text=foldable_text_v2(error_message),
            parse_mode="MarkdownV2",
        )
        schedule_message_deletion(
            chat_id=sent_message.chat_id,
            message_id=sent_message.message_id,
            delay=config.auto_delete_delay,
            user_id=update.effective_user.id,
        )
        if config.delete_user_commands:
            schedule_message_deletion(
                chat_id=update.message.chat_id,
                message_id=update.message.message_id,
                delay=config.user_command_delete_delay,
                task_type="user_command",
                user_id=update.effective_user.id,
            )

# Alias for the command
gp_command = googleplay_command
gp_clean_cache_command = google_play_clean_cache_command

# Register commands
command_factory.register_command("gp", gp_command, permission=Permission.USER, description="Google Play应用价格查询")
command_factory.register_command("gp_cleancache", gp_clean_cache_command, permission=Permission.ADMIN, description="清理Google Play缓存")
