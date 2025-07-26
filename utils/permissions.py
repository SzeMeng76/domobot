"""
权限管理装饰器和工具函数
"""

import functools
import logging
from enum import Enum

from telegram import Update
from telegram.ext import ContextTypes

from utils.config_manager import get_config


logger = logging.getLogger(__name__)

# 获取配置
config = get_config()


class Permission(Enum):
    """权限等级枚举"""

    USER = "user"
    ADMIN = "admin"
    SUPER_ADMIN = "super_admin"


def require_permission(permission: Permission):
    """
    权限检查装饰器

    Args:
        permission: 所需权限等级
    """

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            user_id = update.effective_user.id
            chat_type = update.effective_chat.type

            # 记录使用日志
            logger.info(f"User {user_id} attempting to use {func.__name__} in {chat_type}")

            # 获取用户管理器
            user_manager = context.bot_data.get("user_cache_manager")
            if not user_manager:
                logger.error("用户管理器未初始化")
                return

            # 检查权限
            has_permission = False

            try:
                if permission == Permission.SUPER_ADMIN:
                    has_permission = user_id == config.super_admin_id
                elif permission == Permission.ADMIN:
                    # 检查是否为超级管理员或普通管理员
                    has_permission = user_id == config.super_admin_id or await user_manager.is_admin(user_id)
                # 管理员在任何地方都有权限
                elif user_id == config.super_admin_id or await user_manager.is_admin(user_id):
                    has_permission = True
                elif chat_type in ["group", "supergroup"]:
                    chat_id = update.effective_chat.id
                    has_permission = await user_manager.is_group_whitelisted(chat_id)
                elif chat_type == "private":
                    has_permission = await user_manager.is_whitelisted(user_id)

                if not has_permission:
                    permission_msg = {
                        Permission.SUPER_ADMIN: "此命令仅限超级管理员使用。",
                        Permission.ADMIN: "此命令仅限管理员使用。",
                        Permission.USER: "你没有使用此机器人的权限。\n请联系管理员申请权限。",
                    }

                    # 使用自动删除功能发送权限错误消息
                    from utils.message_manager import send_and_auto_delete

                    if update.message:
                        await send_and_auto_delete(
                            context=context,
                            chat_id=update.effective_chat.id,
                            text=f"❌ **权限不足**\n\n{permission_msg[permission]}",
                            delay=config.auto_delete_delay,
                            command_message_id=update.message.message_id if config.delete_user_commands else None,
                            parse_mode="Markdown",
                        )
                    elif update.callback_query and update.callback_query.message:
                        await send_and_auto_delete(
                            context=context,
                            chat_id=update.effective_chat.id,
                            text=f"❌ **权限不足**\n\n{permission_msg[permission]}",
                            delay=config.auto_delete_delay,
                            parse_mode="Markdown",
                        )
                    return

            except Exception as e:
                logger.error(f"权限检查时出错: {e}", exc_info=True)
                # 权限检查失败时拒绝访问
                return

            # 执行原函数
            try:
                return await func(update, context)
            except Exception as e:
                logger.error(f"Error in {func.__name__}: {e}", exc_info=True)
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="❌ 处理请求时发生错误，请稍后重试。\n如果问题持续存在，请联系管理员。",
                )

        return wrapper

    return decorator


# 保留向后兼容性的装饰器
def permission_required(require_admin=False):
    """
    权限检查装饰器 (向后兼容)

    Args:
        require_admin: 是否需要管理员权限
    """

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            from utils.message_manager import send_and_auto_delete

            user_id = update.effective_user.id
            chat_type = update.effective_chat.type

            # 记录使用日志
            logger.info(f"User {user_id} attempting to use {func.__name__} in {chat_type}")

            # 获取用户管理器
            user_manager = context.bot_data.get("user_cache_manager")
            if not user_manager:
                logger.error("用户管理器未初始化")
                return

            try:
                # 检查管理员权限
                if require_admin:
                    is_admin = user_id == config.super_admin_id or await user_manager.is_admin(user_id)
                    if not is_admin:
                        await send_and_auto_delete(
                            context=context,
                            chat_id=update.effective_chat.id,
                            text="❌ **管理员权限不足**\n\n此命令仅限管理员使用。",
                            delay=config.auto_delete_delay,
                            command_message_id=update.message.message_id
                            if update.message and config.delete_user_commands
                            else None,
                            parse_mode="Markdown",
                        )
                        return
                else:
                    # 检查基本使用权限
                    has_permission = False

                    # 管理员在任何地方都有权限
                    if user_id == config.super_admin_id or await user_manager.is_admin(user_id):
                        has_permission = True
                    # 私聊检查用户白名单
                    elif chat_type == "private":
                        has_permission = await user_manager.is_whitelisted(user_id)
                    # 群聊检查群组白名单
                    elif chat_type in ["group", "supergroup"]:
                        chat_id = update.effective_chat.id
                        has_permission = await user_manager.is_group_whitelisted(chat_id)

                    if not has_permission:
                        await send_and_auto_delete(
                            context=context,
                            chat_id=update.effective_chat.id,
                            text="❌ **权限不足**\n\n你没有使用此机器人的权限。\n请联系管理员申请权限。",
                            delay=config.auto_delete_delay,
                            command_message_id=update.message.message_id
                            if update.message and config.delete_user_commands
                            else None,
                            parse_mode="Markdown",
                        )
                        return

            except Exception as e:
                logger.error(f"权限检查时出错: {e}", exc_info=True)
                # 权限检查失败时拒绝访问
                return

            # 执行原函数
            try:
                return await func(update, context)
            except Exception as e:
                logger.error(f"Error in {func.__name__}: {e}", exc_info=True)
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="❌ 处理请求时发生错误，请稍后重试。\n如果问题持续存在，请联系管理员。",
                )

        return wrapper

    return decorator


async def check_user_permissions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> dict:
    """
    检查用户权限并返回详细信息

    Returns:
        dict: 包含权限信息的字典
    """
    user_id = update.effective_user.id
    chat_type = update.effective_chat.type

    # 获取用户管理器
    user_manager = context.bot_data.get("user_cache_manager")

    result = {
        "user_id": user_id,
        "chat_type": chat_type,
        "is_super_admin": user_id == config.super_admin_id,
        "is_admin": False,
        "is_whitelisted": False,
        "group_whitelisted": False,
        "has_permission": False,
        "permissions": {},
    }

    if not user_manager:
        logger.error("用户管理器未初始化")
        return result

    try:
        # 检查管理员权限
        result["is_admin"] = await user_manager.is_admin(user_id)

        # 超级管理员或普通管理员都有管理权限
        if result["is_super_admin"] or result["is_admin"]:
            result["permissions"] = {"manage_users": True, "manage_groups": True, "clear_cache": True}
            result["has_permission"] = True
        # 检查普通用户权限
        elif chat_type == "private":
            result["is_whitelisted"] = await user_manager.is_whitelisted(user_id)
            result["has_permission"] = result["is_whitelisted"]
        elif chat_type in ["group", "supergroup"]:
            chat_id = update.effective_chat.id
            result["group_whitelisted"] = await user_manager.is_group_whitelisted(chat_id)
            result["has_permission"] = result["group_whitelisted"]

    except Exception as e:
        logger.error(f"检查用户权限时出错: {e}", exc_info=True)

    return result


async def get_user_permission(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Permission | None:
    """
    获取用户的权限等级

    Args:
        update: Telegram更新对象
        context: 上下文对象

    Returns:
        用户的权限等级，如果没有权限则返回None
    """
    user_id = update.effective_user.id
    chat_type = update.effective_chat.type

    # 获取用户管理器
    user_manager = context.bot_data.get("user_cache_manager")
    if not user_manager:
        logger.error("用户管理器未初始化")
        return None

    try:
        # 检查超级管理员
        if user_id == config.super_admin_id:
            return Permission.SUPER_ADMIN

        # 检查管理员
        if await user_manager.is_admin(user_id):
            return Permission.ADMIN

        # 检查普通用户权限
        if chat_type == "private":
            # 私聊中需要用户在白名单中
            if await user_manager.is_whitelisted(user_id):
                return Permission.USER
        elif chat_type in ["group", "supergroup"]:
            # 群组中需要群组在白名单中
            chat_id = update.effective_chat.id
            if await user_manager.is_group_whitelisted(chat_id):
                return Permission.USER

    except Exception as e:
        logger.error(f"获取用户权限时出错: {e}", exc_info=True)

    # 没有权限
    return None
