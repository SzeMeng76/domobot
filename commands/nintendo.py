import logging

from telegram import Update
from telegram.ext import ContextTypes

from utils.cache_commands import delegate_to_service_handler
from utils.command_factory import command_factory
from utils.permissions import Permission

logger = logging.getLogger(__name__)


async def nintendo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /nt command."""
    await delegate_to_service_handler(
        update,
        context,
        service_key="nintendo_price_bot",
        service_display_name="Nintendo Switch Online",
    )


# Register commands
command_factory.register_command("nt", nintendo_command, permission=Permission.NONE, description="Nintendo Switch Online订阅价格查询")

logger.info("Nintendo Switch Online 命令已注册")


# =============================================================================
# Inline 执行入口
# =============================================================================

async def nintendo_inline_execute(args: str, bot_instance=None) -> dict:
    """
    Inline Query 执行入口 - 提供完整的 Nintendo Switch Online 价格查询功能

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
    nintendo_price_bot = bot_instance
    if not nintendo_price_bot:
        return {
            "success": False,
            "title": "❌ 服务未初始化",
            "message": "Nintendo Switch Online 查询服务未初始化，请联系管理员",
            "description": "服务未初始化",
            "error": "Nintendo Switch Online 服务未初始化"
        }

    try:
        # 加载数据
        await nintendo_price_bot.load_or_fetch_data(None)

        if not args or not args.strip():
            # 无参数：返回 Top 10 最便宜的国家（Individual 12个月）
            result = await nintendo_price_bot.get_top_cheapest()
            return {
                "success": True,
                "title": "🎮 Nintendo Switch Online 全球最低价排名",
                "message": result,
                "description": "Nintendo Switch Online Individual 12个月套餐全球最低价 Top 10",
                "error": None
            }
        else:
            # 有参数：检查是否查询家庭套餐排行榜
            args_lower = args.strip().lower()
            if args_lower in ["family", "家庭"]:
                # 返回家庭套餐排行榜
                result = await nintendo_price_bot.get_top_cheapest_family()
                return {
                    "success": True,
                    "title": "🎮 Nintendo Switch Online 家庭套餐全球最低价排名",
                    "message": result,
                    "description": "Nintendo Switch Online Family 12个月套餐全球最低价 Top 10",
                    "error": None
                }
            else:
                # 查询指定国家
                query_list = args.strip().split()
                result = await nintendo_price_bot.query_prices(query_list)

                # 构建简短描述
                if len(query_list) == 1:
                    short_desc = f"Nintendo Switch Online {query_list[0]} 订阅价格"
                else:
                    short_desc = f"Nintendo Switch Online {', '.join(query_list[:3])} 等地区价格"

                return {
                    "success": True,
                    "title": f"🎮 Nintendo Switch Online 价格查询",
                    "message": result,
                    "description": short_desc,
                    "error": None
                }

    except Exception as e:
        logger.error(f"Inline Nintendo Switch Online query failed: {e}")
        return {
            "success": False,
            "title": "❌ 查询失败",
            "message": f"查询 Nintendo Switch Online 价格失败: {str(e)}",
            "description": "查询失败",
            "error": str(e)
        }
