"""
Telegram Boost 查询命令
支持查询频道/群组的 boost 状态和个人 boost 列表
"""

import logging
from datetime import datetime
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from utils.command_factory import command_factory, Permission
from utils.error_handling import with_error_handling

logger = logging.getLogger(__name__)


def _escape_markdown(text: str) -> str:
    """转义 MarkdownV2 特殊字符"""
    if not text:
        return text
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text


@with_error_handling
async def boost_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    查询频道/群组的 boost 状态

    用法:
        /boost @channel - 查询指定频道的 boost 状态
        /boost - 在频道/群组中使用，查询当前频道的 boost 状态
    """
    # 获取目标 chat_id
    target_chat = None

    if context.args and len(context.args) > 0:
        # 用户指定了频道
        target_chat = context.args[0]
    elif update.effective_chat.type in ['channel', 'supergroup']:
        # 在频道/群组中使用
        target_chat = update.effective_chat.id
    else:
        await update.message.reply_text(
            "❌ 请指定频道用户名或在频道/群组中使用此命令\n\n"
            "用法: `/boost @channel`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # 获取 Pyrogram 客户端
    from commands.social_parser import _adapter
    pyrogram_helper = getattr(_adapter, 'pyrogram_helper', None)

    if not pyrogram_helper or not pyrogram_helper.is_started:
        await update.message.reply_text(
            "❌ Pyrogram 客户端未启动\n\n"
            "Boost 功能需要 Pyrogram 客户端支持"
        )
        return

    try:
        # 查询 boost 状态
        boost_status = await pyrogram_helper.client.get_boosts_status(target_chat)

        # 构建消息
        level_text = _escape_markdown(str(boost_status.level))
        boosts_text = _escape_markdown(str(boost_status.boosts))
        current_text = _escape_markdown(str(boost_status.current_level_boosts))

        message = f"📊 *Boost 状态*\n\n"
        message += f"🎯 当前等级: *{level_text}*\n"
        message += f"⚡ Boost 数量: *{boosts_text}* / {current_text}\n"

        if boost_status.next_level_boosts:
            next_text = _escape_markdown(str(boost_status.next_level_boosts))
            remaining = boost_status.next_level_boosts - boost_status.boosts
            remaining_text = _escape_markdown(str(remaining))
            message += f"📈 下一等级: {next_text} \\(还需 *{remaining_text}*\\)\n"

        if boost_status.my_boost:
            message += f"✅ 你已 boost 此频道\n"

        if boost_status.gift_boosts is not None:
            gift_text = _escape_markdown(str(boost_status.gift_boosts))
            message += f"🎁 礼物 Boost: {gift_text}\n"

        # 添加 boost 链接按钮
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 Boost 此频道", url=boost_status.boost_url)]
        ])

        await update.message.reply_text(
            message,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=keyboard
        )

    except Exception as e:
        logger.error(f"查询 boost 状态失败: {e}", exc_info=True)
        error_msg = str(e)
        if "CHANNEL_PRIVATE" in error_msg or "CHAT_ADMIN_REQUIRED" in error_msg:
            await update.message.reply_text(
                "❌ 无法访问该频道\n\n"
                "可能原因:\n"
                "• 频道是私有的\n"
                "• Bot 不是频道成员\n"
                "• 需要管理员权限"
            )
        else:
            await update.message.reply_text(
                f"❌ 查询失败\n\n错误: {_escape_markdown(error_msg)}",
                parse_mode=ParseMode.MARKDOWN_V2
            )


@with_error_handling
async def myboosts_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    查询你的 boost 列表

    用法:
        /myboosts - 查看你给哪些频道 boost 了
    """
    # 获取 Pyrogram 客户端
    from commands.social_parser import _adapter
    pyrogram_helper = getattr(_adapter, 'pyrogram_helper', None)

    if not pyrogram_helper or not pyrogram_helper.is_started:
        await update.message.reply_text(
            "❌ Pyrogram 客户端未启动\n\n"
            "Boost 功能需要 Pyrogram 客户端支持"
        )
        return

    try:
        # 查询我的 boost 列表
        my_boosts = await pyrogram_helper.client.get_boosts()

        if not my_boosts:
            await update.message.reply_text(
                "📭 你还没有 boost 任何频道\n\n"
                "💡 Telegram Premium 用户每月有 4 个免费 boost slots"
            )
            return

        # 构建消息
        message = f"🚀 *你的 Boost 列表* \\({_escape_markdown(str(len(my_boosts)))} 个\\)\n\n"

        for i, boost in enumerate(my_boosts, 1):
            chat_title = _escape_markdown(boost.chat.title or boost.chat.username or "未知频道")
            slot_text = _escape_markdown(str(boost.slot))

            # 格式化日期
            expire_date = boost.expire_date.strftime("%Y-%m-%d")
            expire_text = _escape_markdown(expire_date)

            message += f"{i}\\. *{chat_title}*\n"
            message += f"   • Slot: {slot_text}\n"
            message += f"   • 过期: {expire_text}\n"

            # 检查是否快过期（7天内）
            days_left = (boost.expire_date - datetime.now()).days
            if days_left <= 7:
                days_text = _escape_markdown(str(days_left))
                message += f"   ⚠️ 还剩 {days_text} 天\n"

            message += "\n"

        # 添加 cooldown 信息（如果有）
        if my_boosts and my_boosts[0].cooldown_until_date > datetime.now():
            cooldown_date = my_boosts[0].cooldown_until_date.strftime("%Y-%m-%d %H:%M")
            cooldown_text = _escape_markdown(cooldown_date)
            message += f"⏰ 下次可 boost: {cooldown_text}\n"

        await update.message.reply_text(
            message,
            parse_mode=ParseMode.MARKDOWN_V2
        )

    except Exception as e:
        logger.error(f"查询 boost 列表失败: {e}", exc_info=True)
        await update.message.reply_text(
            f"❌ 查询失败\n\n错误: {_escape_markdown(str(e))}",
            parse_mode=ParseMode.MARKDOWN_V2
        )


# 注册命令（无需权限）
command_factory.register_command("boost", boost_command, permission=Permission.NONE, description="查询频道Boost状态")
command_factory.register_command("myboosts", myboosts_command, permission=Permission.NONE, description="查看我的Boost列表")
