"""
通用缓存清理命令辅助函数

提供统一的缓存清理命令处理模式，消除重复代码。
"""

import logging
from typing import Callable, Any

from telegram import Update
from telegram.ext import ContextTypes

from utils.formatter import foldable_text_v2
from utils.message_manager import delete_user_command, send_error

logger = logging.getLogger(__name__)


async def generic_service_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    service_key: str,
    service_display_name: str,
    handler_method: str | Callable,
) -> Any:
    """
    通用的服务命令处理器，消除重复的服务获取和错误处理代码。

    Args:
        update: Telegram Update 对象
        context: Telegram Context 对象
        service_key: 服务在 bot_data 中的键名（例如 "netflix_price_bot"）
        service_display_name: 服务显示名称（例如 "Netflix"）
        handler_method: 要调用的方法名（字符串）或可调用对象

    Returns:
        服务方法的返回值，如果服务未初始化则返回 None

    Example:
        ```python
        async def netflix_clean_cache_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
            return await generic_service_command(
                update, context,
                service_key="netflix_price_bot",
                service_display_name="Netflix",
                handler_method="clean_cache_command"
            )
        ```
    """
    if not update.message:
        return None

    # 从 context.bot_data 获取服务实例
    service = context.bot_data.get(service_key)
    if not service:
        error_message = f"❌ 错误：{service_display_name} 查询服务未初始化。"
        await send_error(
            context,
            update.message.chat_id,
            foldable_text_v2(error_message),
            parse_mode="MarkdownV2",
        )
        await delete_user_command(
            context, update.message.chat_id, update.message.message_id
        )
        return None

    # 调用服务方法
    if isinstance(handler_method, str):
        # 如果是方法名字符串，从服务对象获取方法
        method = getattr(service, handler_method, None)
        if not method:
            logger.error(f"Service {service_key} does not have method {handler_method}")
            error_message = f"❌ 服务方法 {handler_method} 不存在。"
            await send_error(
                context,
                update.message.chat_id,
                foldable_text_v2(error_message),
                parse_mode="MarkdownV2",
            )
            return None
        return await method(update, context)
    else:
        # 如果是可调用对象，直接调用
        return await handler_method(service, update, context)


async def delegate_to_service_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    service_key: str,
    service_display_name: str,
    handler_method: str = "command_handler",
) -> Any:
    """
    委托命令处理给服务的 command_handler 方法。

    这是 generic_service_command 的便捷包装，专门用于主命令处理。

    Args:
        update: Telegram Update 对象
        context: Telegram Context 对象
        service_key: 服务在 bot_data 中的键名
        service_display_name: 服务显示名称
        handler_method: 处理方法名，默认为 "command_handler"

    Returns:
        服务方法的返回值

    Example:
        ```python
        async def netflix_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
            await delegate_to_service_handler(
                update, context,
                service_key="netflix_price_bot",
                service_display_name="Netflix"
            )
        ```
    """
    return await generic_service_command(
        update,
        context,
        service_key=service_key,
        service_display_name=service_display_name,
        handler_method=handler_method,
    )


async def delegate_to_cache_cleaner(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    service_key: str,
    service_display_name: str,
) -> Any:
    """
    委托缓存清理命令给服务的 clean_cache_command 方法。

    这是 generic_service_command 的便捷包装，专门用于缓存清理命令。

    Args:
        update: Telegram Update 对象
        context: Telegram Context 对象
        service_key: 服务在 bot_data 中的键名
        service_display_name: 服务显示名称

    Returns:
        服务方法的返回值

    Example:
        ```python
        async def netflix_clean_cache_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
            await delegate_to_cache_cleaner(
                update, context,
                service_key="netflix_price_bot",
                service_display_name="Netflix"
            )
        ```
    """
    return await generic_service_command(
        update,
        context,
        service_key=service_key,
        service_display_name=service_display_name,
        handler_method="clean_cache_command",
    )
