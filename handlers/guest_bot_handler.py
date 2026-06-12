"""
Guest Bot Handler - 允许bot在未加入的群组中响应@mention
支持所有现有命令功能，无需重新实现
使用现有的用户权限系统进行权限控制
"""
import logging
from telegram import Update, Message
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


class GuestBotHandler:
    """Guest Bot处理器 - 拦截并转发到现有命令处理器"""

    def __init__(self, user_manager, config):
        """
        初始化Guest Bot处理器

        Args:
            user_manager: MySQLUserManager实例（用于检查权限）
            config: BotConfig实例（获取super_admin_ids）
        """
        self.user_manager = user_manager
        self.config = config
        self._guest_context_storage = {}  # 存储 message_id -> (guest_query_id, caller_chat)
        logger.info("GuestBotHandler initialized with existing permission system")

    def is_user_allowed(self, user_id: int) -> bool:
        """检查用户是否有权限使用Guest Bot功能"""
        # 这里返回False，实际检查在async方法中
        return False

    async def is_user_allowed_async(self, user_id: int) -> bool:
        """异步检查用户权限（使用现有权限系统）"""
        # 1. 检查是否是super admin
        if user_id in self.config.super_admin_ids:
            return True

        # 2. 检查是否是admin
        try:
            is_admin = await self.user_manager.is_admin(user_id)
            if is_admin:
                return True
        except Exception as e:
            logger.error(f"Failed to check admin status for user {user_id}: {e}")

        # 3. 检查是否在白名单中
        try:
            is_whitelisted = await self.user_manager.is_whitelisted(user_id)
            return is_whitelisted
        except Exception as e:
            logger.error(f"Failed to check whitelist for user {user_id}: {e}")
            return False

    def is_guest_bot_message(self, update: Update) -> bool:
        """检查是否是Guest Bot消息"""
        return (
            update.guest_message is not None and
            update.guest_message.guest_query_id is not None
        )

    async def process_guest_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """
        预处理Guest Bot消息，进行权限检查

        Returns:
            True 表示是guest bot消息且已处理授权检查，后续handler可以继续
            False 表示不是guest bot消息或权限不足已拦截
        """
        message = update.guest_message
        if not message or not message.guest_query_id:
            return False

        guest_query_id = message.guest_query_id
        caller_user = message.guest_bot_caller_user
        caller_chat = message.guest_bot_caller_chat

        if not caller_user:
            logger.warning("Guest bot message without caller_user, ignoring")
            return False

        user_id = caller_user.id
        username = caller_user.username or caller_user.first_name
        chat_title = caller_chat.title if caller_chat else "Unknown"

        logger.info(
            f"Guest bot query from user {user_id} (@{username}) "
            f"in external group '{chat_title}' (ID: {caller_chat.id if caller_chat else 'N/A'})"
        )

        # 权限检查
        if not await self.is_user_allowed_async(user_id):
            logger.info(f"User {user_id} not authorized for guest bot access")
            await self._send_unauthorized_response(context.bot, guest_query_id, username)
            return False

        # 存储guest context信息，供后续reply使用
        context.user_data['guest_query_id'] = guest_query_id
        context.user_data['guest_caller_chat'] = caller_chat
        context.user_data['is_guest_bot_call'] = True

        logger.info(f"Guest bot message authorized, continuing to command handlers")
        return True

    async def _send_unauthorized_response(self, bot, guest_query_id: str, username: str):
        """发送未授权响应"""
        from telegram import InlineQueryResultArticle, InputTextMessageContent

        text = (
            f"❌ 抱歉 @{username}\n\n"
            f"你暂时没有权限在外部群组使用此Bot。\n\n"
            f"如需申请权限，请联系Bot管理员。"
        )

        input_content = InputTextMessageContent(message_text=text)
        result = InlineQueryResultArticle(
            id=guest_query_id[:64],
            title="Unauthorized",
            input_message_content=input_content
        )

        try:
            await bot.answer_guest_query(guest_query_id=guest_query_id, result=result)
            logger.info(f"Sent unauthorized response for guest query {guest_query_id}")
        except Exception as e:
            logger.error(f"Failed to send unauthorized response: {e}")



async def guest_bot_reply_interceptor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    拦截reply方法，如果是guest bot调用，使用answer_guest_query发送
    这个函数需要在所有命令处理完成后调用
    """
    if not context.user_data.get('is_guest_bot_call'):
        return

    # 命令已处理，但需要拦截reply
    # 注意：这个方法目前不工作，因为reply_text等方法是同步调用的
    # 需要在application级别hook send_message方法
    pass

