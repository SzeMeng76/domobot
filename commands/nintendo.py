"""
/nt command - Query Nintendo Switch Online subscription prices globally
参考 disney_plus.py 的架构实现
"""

import logging
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)


async def nintendo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /nt 命令"""
    if not update.message:
        return

    user_id = update.effective_user.id if update.effective_user else "Unknown"
    logger.info(f"User {user_id} triggered /nt with args: {context.args}")

    bot_instance = context.bot_data.get("nintendo_price_bot")
    if not bot_instance:
        await update.message.reply_text(
            "❌ Nintendo Switch Online 价格查询服务未初始化",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    args = context.args if context.args else []
    args_str = " ".join(args) if args else ""

    result = await nintendo_execute(args_str, bot_instance=bot_instance)

    await update.message.reply_text(
        result["message"],
        parse_mode=ParseMode.MARKDOWN_V2
    )


async def nintendo_inline_execute(args_str: str, bot_instance=None):
    """inline query 执行函数"""
    return await nintendo_execute(args_str, bot_instance=bot_instance)


async def nintendo_execute(args_str: str, bot_instance=None):
    """核心执行逻辑"""
    if not bot_instance:
        return {
            "success": False,
            "title": "服务未初始化",
            "message": "❌ Nintendo Switch Online 价格查询服务未初始化"
        }

    args = args_str.strip().split() if args_str.strip() else []

    try:
        if not args:
            # 无参数：显示 Individual + Family TOP 10
            message = await bot_instance.get_top_rankings()
        elif args[0].lower() in ["individual", "个人", "ind", "i"]:
            # Individual 12个月套餐 TOP 10
            message = await bot_instance.get_individual_ranking()
        elif args[0].lower() in ["family", "家庭", "fam", "f"]:
            # Family 12个月套餐 TOP 10
            message = await bot_instance.get_family_ranking()
        else:
            # 查询指定国家
            country_codes = [arg.upper() for arg in args]
            message = await bot_instance.query_countries(country_codes)

        return {
            "success": True,
            "title": "Nintendo Switch Online",
            "message": message
        }
    except Exception as e:
        logger.error(f"Nintendo execute error: {e}", exc_info=True)
        return {
            "success": False,
            "title": "查询失败",
            "message": f"❌ 查询失败：{str(e)}"
        }


def get_handlers():
    """返回命令处理器列表"""
    return [
        CommandHandler("nt", nintendo_command),
    ]
