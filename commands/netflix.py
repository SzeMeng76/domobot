import logging

from telegram import Update
from telegram.ext import ContextTypes

from utils.cache_commands import delegate_to_cache_cleaner, delegate_to_service_handler
from utils.command_factory import command_factory
from utils.permissions import Permission

logger = logging.getLogger(__name__)


async def netflix_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /netflix command."""
    await delegate_to_service_handler(
        update,
        context,
        service_key="netflix_price_bot",
        service_display_name="Netflix",
    )


async def netflix_clean_cache_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """Handles the /netflix_cleancache command."""
    await delegate_to_cache_cleaner(
        update,
        context,
        service_key="netflix_price_bot",
        service_display_name="Netflix",
    )


# Register commands
command_factory.register_command(
    "nf", netflix_command, permission=Permission.USER, description="Netflix订阅价格查询"
)
command_factory.register_command(
    "nf_cleancache",
    netflix_clean_cache_command,
    permission=Permission.ADMIN,
    description="清理Netflix缓存",
)

logger.info("Netflix 命令已注册")


# =============================================================================
# Inline 执行入口
# =============================================================================

async def netflix_inline_execute(args: str, bot_instance=None) -> dict:
    """
    Inline Query 执行入口 - 提供完整的 Netflix 价格查询功能

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
    netflix_price_bot = bot_instance
    if not netflix_price_bot:
        return {
            "success": False,
            "title": "❌ 服务未初始化",
            "message": "Netflix 查询服务未初始化，请联系管理员",
            "description": "服务未初始化",
            "error": "Netflix 服务未初始化"
        }

    try:
        # 加载数据
        await netflix_price_bot.load_or_fetch_data(None)

        if not args or not args.strip():
            # 无参数：返回 Top 10 最便宜的国家
            result = await netflix_price_bot.get_top_cheapest()
            return {
                "success": True,
                "title": "🎬 Netflix 全球最低价排名",
                "message": result,
                "description": "Netflix Premium 套餐全球最低价 Top 10",
                "error": None
            }
        else:
            # 有参数：查询指定国家
            query_list = args.strip().split()
            result = await netflix_price_bot.query_prices(query_list)

            # 构建简短描述
            if len(query_list) == 1:
                short_desc = f"Netflix {query_list[0]} 订阅价格"
            else:
                short_desc = f"Netflix {', '.join(query_list[:3])} 等地区价格"

            return {
                "success": True,
                "title": f"🎬 Netflix 价格查询",
                "message": result,
                "description": short_desc,
                "error": None
            }

    except Exception as e:
        logger.error(f"Inline Netflix query failed: {e}")
        return {
            "success": False,
            "title": "❌ 查询失败",
            "message": f"查询 Netflix 价格失败: {str(e)}",
            "description": "查询失败",
            "error": str(e)
        }
