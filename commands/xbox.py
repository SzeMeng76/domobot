import logging

from telegram import Update
from telegram.ext import ContextTypes

from utils.cache_commands import delegate_to_service_handler
from utils.command_factory import command_factory
from utils.permissions import Permission

logger = logging.getLogger(__name__)


async def xbox_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /xbox command."""
    await delegate_to_service_handler(
        update,
        context,
        service_key="xbox_price_bot",
        service_display_name="Xbox Game Pass",
    )


command_factory.register_command("xbox", xbox_command, permission=Permission.NONE, description="Xbox Game Pass订阅价格查询")

logger.info("Xbox Game Pass 命令已注册")


async def xbox_inline_execute(args: str, bot_instance=None) -> dict:
    """
    Inline Query 执行入口 - 提供完整的 Xbox Game Pass 价格查询功能

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
    xbox_price_bot = bot_instance
    if not xbox_price_bot:
        return {
            "success": False,
            "title": "❌ 服务未初始化",
            "message": "Xbox Game Pass 查询服务未初始化，请联系管理员",
            "description": "服务未初始化",
            "error": "Xbox Game Pass 服务未初始化"
        }

    try:
        await xbox_price_bot.load_or_fetch_data(None)

        if not args or not args.strip():
            result = await xbox_price_bot.get_top_cheapest(plan="pc")
            return {
                "success": True,
                "title": "🎮 Xbox Game Pass 全球最低价排名 (PC Game Pass)",
                "message": result,
                "description": "PC Game Pass 套餐全球最低价 Top 10",
                "error": None
            }
        elif args.strip().lower() == "ultimate":
            result = await xbox_price_bot.get_top_cheapest(plan="ultimate")
            return {
                "success": True,
                "title": "🎮 Xbox Game Pass 全球最低价排名 (Ultimate)",
                "message": result,
                "description": "Game Pass Ultimate 套餐全球最低价 Top 10",
                "error": None
            }
        else:
            query_list = args.strip().split()
            result = await xbox_price_bot.query_prices(query_list)

            if len(query_list) == 1:
                short_desc = f"Xbox Game Pass {query_list[0]} 订阅价格"
            else:
                short_desc = f"Xbox Game Pass {', '.join(query_list[:3])} 等地区价格"

            return {
                "success": True,
                "title": "🎮 Xbox Game Pass 价格查询",
                "message": result,
                "description": short_desc,
                "error": None
            }

    except Exception as e:
        logger.error(f"Inline Xbox query failed: {e}")
        return {
            "success": False,
            "title": "❌ 查询失败",
            "message": f"查询 Xbox Game Pass 价格失败: {str(e)}",
            "description": "查询失败",
            "error": str(e)
        }
