"""
统一消息管理模块
提供简洁强大的消息发送和自动删除功能
"""

import logging
from enum import Enum

from telegram.ext import ContextTypes


logger = logging.getLogger(__name__)


class MessageType(Enum):
    """消息类型枚举"""
    ERROR = "❌"           # 错误消息
    SUCCESS = "✅"         # 成功消息
    INFO = "ℹ️"            # 信息消息
    SEARCH_RESULT = "🔍"   # 搜索结果
    HELP = "❓"            # 帮助消息

    def __init__(self, icon: str):
        self.icon = icon


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
    自动支持Guest Bot模式

    Args:
        context: Bot 上下文
        chat_id: 聊天ID
        text: 消息文本
        msg_type: 消息类型
        custom_delay: 自定义删除延迟（秒），None则使用配置值
        session_id: 会话ID，用于批量管理
        **kwargs: 传递给send_message的其他参数

    Returns:
        发送的消息对象，如果发送失败则返回None
    """
    try:
        # Guest Bot支持：注入guest_query_id
        from utils.guest_bot_wrapper import inject_guest_context_to_kwargs
        inject_guest_context_to_kwargs(kwargs, context)

        # 发送消息
        sent_message = await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            **kwargs
        )

        # Guest Bot模式下，answer_guest_query不支持自动删除，直接返回
        if context.user_data.get('is_guest_bot_call'):
            logger.debug(f"Guest Bot消息已发送（无自动删除）")
            return sent_message

        # 确定删除延迟
        if custom_delay is not None:
            delay = custom_delay
        elif msg_type == MessageType.ERROR:
            delay = 5  # 错误消息快速删除
        else:
            from utils.config_manager import get_config
            config = get_config()
            delay = config.auto_delete_delay

        # 调度删除
        await _schedule_deletion(context, sent_message.chat_id, sent_message.message_id, delay, session_id)

        logger.debug(f"消息已发送并调度删除: chat_id={chat_id}, type={msg_type.name}, delay={delay}s, session={session_id}")
        return sent_message

    except Exception as e:
        logger.error(f"发送消息失败: {e}")
        return None


# 便捷函数 - 使用统一的发送接口
async def send_error(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    text: str,
    session_id: str | None = None,
    **kwargs
) -> object | None:
    """发送错误消息（5秒自动删除）"""
    if not text.startswith("❌"):
        text = f"❌ {text}"
    return await send_message_with_auto_delete(context, chat_id, text, MessageType.ERROR, session_id=session_id, **kwargs)


async def send_success(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    text: str,
    session_id: str | None = None,
    **kwargs
) -> object | None:
    """发送成功消息（使用配置延迟）"""
    if not text.startswith("✅"):
        text = f"✅ {text}"
    return await send_message_with_auto_delete(context, chat_id, text, MessageType.SUCCESS, session_id=session_id, **kwargs)


async def send_info(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    text: str,
    session_id: str | None = None,
    **kwargs
) -> object | None:
    """发送信息消息（使用配置延迟）"""
    return await send_message_with_auto_delete(context, chat_id, text, MessageType.INFO, session_id=session_id, **kwargs)


async def send_search_result(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    text: str,
    custom_delay: int | None = None,
    session_id: str | None = None,
    **kwargs
) -> object | None:
    """发送搜索结果消息（使用配置延迟或自定义延迟）"""
    return await send_message_with_auto_delete(context, chat_id, text, MessageType.SEARCH_RESULT, custom_delay=custom_delay, session_id=session_id, **kwargs)


async def send_help(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    text: str,
    session_id: str | None = None,
    **kwargs
) -> object | None:
    """发送帮助消息（使用配置延迟）"""
    return await send_message_with_auto_delete(context, chat_id, text, MessageType.HELP, session_id=session_id, **kwargs)


async def delete_user_command(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    custom_delay: int | None = None,
    session_id: str | None = None
) -> bool:
    """
    统一的用户命令删除函数

    Args:
        context: Bot 上下文
        chat_id: 聊天ID
        message_id: 消息ID
        custom_delay: 自定义删除延迟（秒），None则使用配置值
        session_id: 会话ID，用于批量管理

    Returns:
        是否成功调度删除
    """
    from utils.config_manager import get_config

    config = get_config()
    if config.delete_user_commands:
        delay = custom_delay if custom_delay is not None else config.user_command_delete_delay
        return await _schedule_deletion(context, chat_id, message_id, delay, session_id)
    return False


async def cancel_session_deletions(session_id: str, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    取消会话相关的所有删除任务

    Args:
        session_id: 会话ID
        context: Bot 上下文

    Returns:
        是否成功取消
    """
    try:
        if context and hasattr(context, "bot_data"):
            scheduler = context.bot_data.get("message_delete_scheduler")
            if scheduler:
                count = await scheduler.cancel_session_deletions(session_id)
                logger.info(f"已取消会话 {session_id} 的 {count} 个删除任务")
                return count > 0

        logger.warning("无法获取消息删除调度器")
        return False

    except Exception as e:
        logger.error(f"取消会话删除任务失败: {e}")
        return False


# 注意：schedule_message_deletion 函数已被删除
# 请使用统一的 send_message_with_auto_delete() 或 delete_user_command() 函数


async def _schedule_deletion(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int | None,
    message_id: int | None,
    delay: int,
    session_id: str | None = None
) -> bool:
    """
    内部函数：调度消息删除任务

    Args:
        context: Bot 上下文
        chat_id: 聊天ID（None时跳过，用于inline message）
        message_id: 消息ID（None时跳过）
        delay: 延迟秒数
        session_id: 会话ID（可选）

    Returns:
        是否成功调度
    """
    if chat_id is None or message_id is None:
        return False
    try:
        if context and hasattr(context, "bot_data"):
            scheduler = context.bot_data.get("message_delete_scheduler")
            if scheduler and hasattr(scheduler, "schedule_deletion"):
                await scheduler.schedule_deletion(chat_id, message_id, delay, session_id)
                return True
            else:
                logger.warning(f"消息删除调度器未正确初始化: scheduler={scheduler}")
        else:
            logger.warning("无法获取 bot_data 或 context 为空")

        return False

    except Exception as e:
        logger.error(f"调度消息删除失败: {e}")
        return False


# 装饰器已移除 - 推荐直接使用统一的消息函数
