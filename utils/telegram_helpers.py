"""
Telegram 辅助函数
提供安全的消息操作包装，处理常见的 Telegram API 错误
"""

import logging
from typing import Optional

from telegram import CallbackQuery, Message
from telegram.error import BadRequest

logger = logging.getLogger(__name__)


async def safe_edit_message_text(
    query: CallbackQuery,
    text: str,
    **kwargs
) -> bool:
    """
    安全地编辑消息文本，处理消息不存在的情况

    Args:
        query: CallbackQuery 对象
        text: 新的消息文本
        **kwargs: 传递给 edit_message_text 的其他参数

    Returns:
        bool: 是否成功编辑消息
    """
    try:
        await query.edit_message_text(text=text, **kwargs)
        return True
    except BadRequest as e:
        error_msg = str(e)
        if "Message to edit not found" in error_msg or "Message is not modified" in error_msg:
            logger.warning(f"无法编辑消息: {error_msg}")
            return False
        raise


async def safe_delete_message(
    message: Message,
) -> bool:
    """
    安全地删除消息，处理消息不存在的情况

    Args:
        message: Message 对象

    Returns:
        bool: 是否成功删除消息
    """
    try:
        await message.delete()
        return True
    except BadRequest as e:
        error_msg = str(e)
        if "Message to delete not found" in error_msg or "Message can't be deleted" in error_msg:
            logger.warning(f"无法删除消息: {error_msg}")
            return False
        raise


async def safe_answer_callback_query(
    query: CallbackQuery,
    text: Optional[str] = None,
    show_alert: bool = False,
    **kwargs
) -> bool:
    """
    安全地回应回调查询，处理查询过期的情况

    Args:
        query: CallbackQuery 对象
        text: 提示文本
        show_alert: 是否显示为警告框
        **kwargs: 传递给 answer 的其他参数

    Returns:
        bool: 是否成功回应查询
    """
    try:
        await query.answer(text=text, show_alert=show_alert, **kwargs)
        return True
    except BadRequest as e:
        error_msg = str(e)
        if "Query is too old" in error_msg or "Query_id_invalid" in error_msg:
            logger.warning(f"回调查询已过期: {error_msg}")
            return False
        raise
