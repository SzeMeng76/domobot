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

    NONE = "none"  # 新增：无权限要求，所有人都可以使用 
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
            # Inline 消息没有 effective_chat，直接执行（inline 消息已经发送，无法撤回）
            if update.callback_query and update.callback_query.inline_message_id:
                try:
                    return await func(update, context)
                except Exception as e:
                    logger.error(f"Error in {func.__name__} (inline): {e}", exc_info=True)
                    if update.callback_query:
                        await update.callback_query.answer("❌ 处理失败", show_alert=True)
                return

            # 如果权限要求是 NONE，直接执行函数，不进行权限检查
            if permission == Permission.NONE:
                try:
                    return await func(update, context)
                except Exception as e:
                    logger.error(f"Error in {func.__name__}: {e}", exc_info=True)
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text="❌ 处理请求时发生错误，请稍后重试。\n如果问题持续存在，请联系管理员。",
                    )
                return

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
                    has_permission = user_id in config.super_admin_ids
                elif permission == Permission.ADMIN:
                    # 检查是否为超级管理员或普通管理员
                    has_permission = user_id in config.super_admin_ids or await user_manager.is_admin(user_id)
                # 管理员在任何地方都有权限
                elif user_id in config.super_admin_ids or await user_manager.is_admin(user_id):
                    has_permission = True
                elif chat_type in ["group", "supergroup"]:
                    chat_id = update.effective_chat.id
                    has_permission = await user_manager.is_group_whitelisted(chat_id)
                elif chat_type == "private":
                    has_permission = await user_manager.is_whitelisted(user_id)


                if not has_permission:
                    # 🔧 在未授权群组中，对于普通文本消息（非命令），静默忽略，不发送错误提示
                    # 这样可以避免bot在未加白名单的群组中打扰正常聊天
                    if chat_type in ["group", "supergroup"]:
                        # 检查是否是普通文本消息（不是命令）
                        if update.message and update.message.text and not update.message.text.startswith('/'):
                            logger.debug(f"群组 {update.effective_chat.id} 未授权，静默忽略普通文本消息")
                            return  # 静默返回，不发送任何消息

                    # 🔧 根据权限级别给出不同的错误提示
                    if permission == Permission.SUPER_ADMIN:
                        error_message = "此命令仅限超级管理员使用。"
                    elif permission == Permission.ADMIN:
                        error_message = "此命令仅限管理员使用。"
                    elif permission == Permission.USER:
                        error_message = "🔒 此机器人暂时不对外公开使用。\n\n💡 这是一个私人价格查询机器人，目前仅限授权用户使用。\n\n📝 如果你需要类似功能，可以考虑使用其他公开的汇率查询机器人或访问相关官方网站查询价格信息。\n\n感谢你的理解！🙏"

                    # 使用自动删除功能发送权限错误消息
                    from utils.message_manager import send_error, delete_user_command

                    if update.message:
                        await send_error(
                            context=context,
                            chat_id=update.effective_chat.id,
                            text=f"**访问被拒绝**\n\n{error_message}",
                            parse_mode="Markdown",
                        )
                        # 删除用户的命令消息
                        if config.delete_user_commands:
                            await delete_user_command(context, update.effective_chat.id, update.message.message_id)
                    elif update.callback_query and update.callback_query.message:
                        await send_error(
                            context=context,
                            chat_id=update.effective_chat.id,
                            text=f"**访问被拒绝**\n\n{error_message}",
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
                # 使用 send_error 确保错误消息会被自动删除
                from utils.message_manager import send_error
                await send_error(
                    context=context,
                    chat_id=update.effective_chat.id,
                    text="处理请求时发生错误，请稍后重试。\n如果问题持续存在，请联系管理员。",
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
            # Inline 消息没有 effective_chat，直接执行（inline 消息已经发送，无法撤回）
            if update.callback_query and update.callback_query.inline_message_id:
                try:
                    return await func(update, context)
                except Exception as e:
                    logger.error(f"Error in {func.__name__} (inline): {e}", exc_info=True)
                    if update.callback_query:
                        await update.callback_query.answer("❌ 处理失败", show_alert=True)
                return

            from utils.message_manager import send_error, delete_user_command

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
                    is_admin = user_id in config.super_admin_ids or await user_manager.is_admin(user_id)
                    if not is_admin:
                        await send_error(
                            context=context,
                            chat_id=update.effective_chat.id,
                            text="**管理员权限不足**\n\n此命令仅限管理员使用。",
                            parse_mode="Markdown",
                        )
                        # 删除用户命令
                        if update.message:
                            await delete_user_command(
                                context=context,
                                chat_id=update.effective_chat.id,
                                message_id=update.message.message_id,
                            )
                        return
                else:
                    # 检查基本使用权限
                    has_permission = False

                    # 管理员在任何地方都有权限
                    if user_id in config.super_admin_ids or await user_manager.is_admin(user_id):
                        has_permission = True
                    # 私聊检查用户白名单
                    elif chat_type == "private":
                        has_permission = await user_manager.is_whitelisted(user_id)
                    # 群聊检查群组白名单
                    elif chat_type in ["group", "supergroup"]:
                        chat_id = update.effective_chat.id
                        has_permission = await user_manager.is_group_whitelisted(chat_id)

                    if not has_permission:
                        await send_error(
                            context=context,
                            chat_id=update.effective_chat.id,
                            text="**权限不足**\n\n你没有使用此机器人的权限。\n请联系管理员申请权限。",
                            parse_mode="Markdown",
                        )
                        # 删除用户命令
                        if update.message:
                            await delete_user_command(
                                context=context,
                                chat_id=update.effective_chat.id,
                                message_id=update.message.message_id,
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
                # 使用 send_error 确保错误消息会被自动删除
                from utils.message_manager import send_error
                await send_error(
                    context=context,
                    chat_id=update.effective_chat.id,
                    text="处理请求时发生错误，请稍后重试。\n如果问题持续存在，请联系管理员。",
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
        "is_super_admin": user_id in config.super_admin_ids,
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
        if user_id in config.super_admin_ids:
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
