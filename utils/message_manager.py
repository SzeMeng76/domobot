"""
统一消息管理模块
提供简洁强大的消息发送和自动删除功能
"""

import logging
from enum import Enum
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown # ✨ 新增：导入“消毒”工具

logger = logging.getLogger(__name__)


class MessageType(Enum):
    """消息类型枚举"""
    ERROR = "❌"
    SUCCESS = "✅"
    INFO = "ℹ️"
    SEARCH_RESULT = "🔍"
    HELP = "❓"


async def send_message_with_auto_delete(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    text: str,
    msg_type: MessageType = MessageType.INFO,
    custom_delay: int | None = None,
    session_id: str | None = None,
    **kwargs
) -> object | None:
    """
    统一的消息发送+自动删除函数
    """
    try:
        sent_message = await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            **kwargs
        )

        if custom_delay is not None:
            delay = custom_delay
        elif msg_type == MessageType.ERROR:
            delay = 5
        else:
            from utils.config_manager import get_config
            config = get_config()
            delay = config.auto_delete_delay
        
        # 只有延迟时间大于0才调度删除
        if delay > 0:
            await _schedule_deletion(context, sent_message.chat_id, sent_message.message_id, delay, session_id, msg_type.name)

        logger.debug(f"消息已发送: chat_id={chat_id}, type={msg_type.name}, delay={delay}s, session={session_id}")
        return sent_message

    except Exception as e:
        logger.error(f"发送消息失败: {e}")
        return None


# --- 便捷函数 ---

async def send_error(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str, **kwargs
) -> object | None:
    """发送错误消息（5秒自动删除）"""
    if not text.startswith("❌"):
        text = f"❌ {text}"
    # ✨ 修复：在发送前对文本进行转义
    safe_text = escape_markdown(text, version=2)
    return await send_message_with_auto_delete(context, chat_id, safe_text, MessageType.ERROR, **kwargs)


async def send_success(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str, **kwargs
) -> object | None:
    """发送成功消息（使用配置延迟）"""
    if not text.startswith("✅"):
        text = f"✅ {text}"
    # ✨ 修复：在发送前对文本进行转义
    safe_text = escape_markdown(text, version=2)
    return await send_message_with_auto_delete(context, chat_id, safe_text, MessageType.SUCCESS, **kwargs)


async def send_info(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str, **kwargs
) -> object | None:
    """发送信息消息（使用配置延迟）"""
    # ✨ 修复：在发送前对文本进行转义
    safe_text = escape_markdown(text, version=2)
    return await send_message_with_auto_delete(context, chat_id, safe_text, MessageType.INFO, **kwargs)

async def send_help(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str, **kwargs
) -> object | None:
    """发送帮助消息（使用配置延迟）"""
    # 帮助消息通常是预设好的，并且已经处理好格式，所以不需要转义
    return await send_message_with_auto_delete(context, chat_id, text, MessageType.HELP, **kwargs)


async def delete_user_command(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, **kwargs
) -> bool:
    """
    统一的用户命令删除函数
    """
    from utils.config_manager import get_config
    config = get_config()

    if not config.delete_user_commands:
        return False

    delay = config.user_command_delete_delay
    
    # 修复：如果延迟为0或更小，立即删除
    if delay <= 0:
        try:
            return await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception as e:
            logger.warning(f"立即删除用户命令 {message_id} 失败: {e}")
            return False
    else:
        return await _schedule_deletion(context, chat_id, message_id, delay, task_type="user_command", **kwargs)


async def cancel_session_deletions(session_id: str, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    取消会话相关的所有删除任务
    """
    try:
        scheduler = context.bot_data.get("message_delete_scheduler")
        if scheduler:
            count = await scheduler.cancel_session_deletions(session_id)
            logger.info(f"已取消会话 {session_id} 的 {count} 个删除任务")
            return count
        logger.warning("无法获取消息删除调度器")
        return 0
    except Exception as e:
        logger.error(f"取消会话删除任务失败: {e}")
        return 0


async def _schedule_deletion(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    delay: int,
    session_id: str | None = None,
    task_type: str = "bot_message",
) -> bool:
    """
    内部函数：调度消息删除任务
    """
    try:
        scheduler = context.bot_data.get("message_delete_scheduler")
        if scheduler:
            await scheduler.schedule_deletion(chat_id, message_id, delay, session_id, task_type)
            return True
        logger.warning(f"消息删除调度器未正确初始化")
        return False
    except Exception as e:
        logger.error(f"调度消息删除失败: {e}")
        return False
