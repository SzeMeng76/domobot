import logging

from telegram import Update
from telegram.ext import ContextTypes

from utils.cache_commands import delegate_to_cache_cleaner, delegate_to_service_handler
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


async def spotify_clean_cache_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """Handles the /spotify_cleancache command."""
    await delegate_to_cache_cleaner(
        update,
        context,
        service_key="spotify_price_bot",
        service_display_name="Spotify",
    )


# Register commands
command_factory.register_command(
    "sp", spotify_command, permission=Permission.USER, description="Spotify订阅价格查询"
)
command_factory.register_command(
    "sp_cleancache",
    spotify_clean_cache_command,
    permission=Permission.ADMIN,
    description="清理Spotify缓存",
)

logger.info("Spotify 命令已注册")
async def spotify_inline_execute(args: str) -> dict:
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
