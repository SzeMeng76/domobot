import logging

from telegram import Update
from telegram.ext import ContextTypes

from utils.cache_commands import delegate_to_service_handler
from utils.command_factory import command_factory
from utils.permissions import Permission

logger = logging.getLogger(__name__)


async def spotify_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /spotify command."""
    await delegate_to_service_handler(
        update,
        context,
        service_key="spotify_price_bot",
        service_display_name="Spotify",
    )


async def spotify_prepaid_individual_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /spi command for individual 1-year prepaid plans."""
    from utils.formatter import foldable_text_v2
    from utils.message_manager import delete_user_command, send_error
    from utils.config_manager import get_config
    from utils.message_manager import _schedule_deletion

    if not update.message:
        return

    spotify_price_bot = context.bot_data.get("spotify_price_bot")
    if not spotify_price_bot:
        error_message = "❌ 错误：Spotify 查询服务未初始化。"
        await send_error(
            context,
            update.message.chat_id,
            foldable_text_v2(error_message),
            parse_mode="MarkdownV2",
        )
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        return

    loading_message = "🔍 正在查询 Spotify Premium 个人1年预付费全球最低价格排名... ⏳"
    message = await context.bot.send_message(
        chat_id=update.message.chat_id,
        text=foldable_text_v2(loading_message),
        parse_mode="MarkdownV2"
    )

    try:
        await spotify_price_bot.load_or_fetch_data(context)
        result = await spotify_price_bot.get_top_prepaid_individual()
        await message.edit_text(result, parse_mode="MarkdownV2", disable_web_page_preview=True)

        chat_id = update.message.chat_id
        user_command_id = update.message.message_id
        config = get_config()
        await _schedule_deletion(context, chat_id, message.message_id, config.auto_delete_delay)
        await delete_user_command(context, chat_id, user_command_id)

        logger.info(f"🔧 Scheduled deletion for Spotify prepaid individual messages - Bot: {message.message_id}, User: {user_command_id}")
    except Exception as e:
        logger.error(f"Error getting top prepaid individual Spotify prices: {e}", exc_info=True)
        error_message = f"❌ 查询时发生错误: {e}"
        await message.edit_text(foldable_text_v2(error_message), parse_mode="MarkdownV2")


async def spotify_prepaid_family_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /spf command for family 1-year prepaid plans."""
    from utils.formatter import foldable_text_v2
    from utils.message_manager import delete_user_command, send_error
    from utils.config_manager import get_config
    from utils.message_manager import _schedule_deletion

    if not update.message:
        return

    spotify_price_bot = context.bot_data.get("spotify_price_bot")
    if not spotify_price_bot:
        error_message = "❌ 错误：Spotify 查询服务未初始化。"
        await send_error(
            context,
            update.message.chat_id,
            foldable_text_v2(error_message),
            parse_mode="MarkdownV2",
        )
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        return

    loading_message = "🔍 正在查询 Spotify Premium 家庭1年预付费全球最低价格排名... ⏳"
    message = await context.bot.send_message(
        chat_id=update.message.chat_id,
        text=foldable_text_v2(loading_message),
        parse_mode="MarkdownV2"
    )

    try:
        await spotify_price_bot.load_or_fetch_data(context)
        result = await spotify_price_bot.get_top_prepaid_family()
        await message.edit_text(result, parse_mode="MarkdownV2", disable_web_page_preview=True)

        chat_id = update.message.chat_id
        user_command_id = update.message.message_id
        config = get_config()
        await _schedule_deletion(context, chat_id, message.message_id, config.auto_delete_delay)
        await delete_user_command(context, chat_id, user_command_id)

        logger.info(f"🔧 Scheduled deletion for Spotify prepaid family messages - Bot: {message.message_id}, User: {user_command_id}")
    except Exception as e:
        logger.error(f"Error getting top prepaid family Spotify prices: {e}", exc_info=True)
        error_message = f"❌ 查询时发生错误: {e}"
        await message.edit_text(foldable_text_v2(error_message), parse_mode="MarkdownV2")


# Register commands
command_factory.register_command(
    "sp", spotify_command, permission=Permission.NONE, description="Spotify订阅价格查询"
)
command_factory.register_command(
    "spi", spotify_prepaid_individual_command, permission=Permission.NONE, description="Spotify个人1年预付费排行榜"
)
command_factory.register_command(
    "spf", spotify_prepaid_family_command, permission=Permission.NONE, description="Spotify家庭1年预付费排行榜"
)

logger.info("Spotify 命令已注册")
async def spotify_inline_execute(args: str, bot_instance=None) -> dict:
    """
    Inline Query 执行入口 - 提供完整的 Spotify 价格查询功能

    Args:
        args: 用户输入的参数字符串，如 "US" 或 "美国"，为空则返回 Top 10

    Returns:
        dict: {
            "success": bool,
            "title": str,
            "message": str,
            "description": str,
            "error": str | None
        }
    """
    spotify_price_bot = bot_instance
    if not spotify_price_bot:
        return {
            "success": False,
            "title": "❌ 服务未初始化",
            "message": "Spotify 查询服务未初始化，请联系管理员",
            "description": "服务未初始化",
            "error": "Spotify 服务未初始化"
        }

    try:
        # 加载数据
        await spotify_price_bot.load_or_fetch_data(None)

        if not args or not args.strip():
            # 无参数：返回 Top 10 最便宜的国家（家庭版）
            result = await spotify_price_bot.get_top_cheapest()
            return {
                "success": True,
                "title": "🎵 Spotify 全球最低价排名",
                "message": result,
                "description": "Spotify 家庭版全球最低价 Top 10",
                "error": None
            }
        else:
            # 有参数：查询指定国家
            query_list = args.strip().split()
            result = await spotify_price_bot.query_prices(query_list)

            # 构建简短描述
            if len(query_list) == 1:
                short_desc = f"Spotify {query_list[0]} 订阅价格"
            else:
                short_desc = f"Spotify {', '.join(query_list[:3])} 等地区价格"

            return {
                "success": True,
                "title": f"🎵 Spotify 价格查询",
                "message": result,
                "description": short_desc,
                "error": None
            }

    except Exception as e:
        logger.error(f"Inline Spotify query failed: {e}")
        return {
            "success": False,
            "title": "❌ 查询失败",
            "message": f"查询 Spotify 价格失败: {str(e)}",
            "description": "查询失败",
            "error": str(e)
        }
