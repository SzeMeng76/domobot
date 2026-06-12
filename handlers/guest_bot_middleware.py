"""
Guest Bot Middleware - 自动处理Guest Bot消息的中间件
"""
import logging
from telegram.ext import BaseHandler, filters
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


class GuestBotMiddleware(BaseHandler):
    """
    Guest Bot中间件 - 自动注入guest context到message对象
    必须在所有命令handler之前注册
    """

    def __init__(self, guest_bot_handler):
        """
        Args:
            guest_bot_handler: GuestBotHandler实例
        """
        super().__init__(callback=self._process)
        self.guest_bot_handler = guest_bot_handler

    def check_update(self, update: object) -> bool:
        """检查是否应该处理此update"""
        return isinstance(update, Update) and update.guest_message is not None

    async def _process(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        处理update，如果是guest bot消息则注入context

        Returns:
            None表示继续处理，其他值表示终止
        """
        # 检查是否是guest bot消息
        if not self.guest_bot_handler.is_guest_bot_message(update):
            return None  # 不是guest bot消息，继续

        # 进行权限检查和context注入
        authorized = await self.guest_bot_handler.process_guest_message(update, context)

        if not authorized:
            # 未授权，已发送拒绝消息，停止处理
            return True  # 停止后续handler

        # 授权通过，注入guest context到message对象
        from utils.guest_bot_wrapper import inject_guest_context_to_message
        inject_guest_context_to_message(update.guest_message, context)

        # 关键修复：把guest_message复制到update.message
        # 让后续的CommandHandler、ConversationHandler等能识别
        update._unfreeze()
        update.message = update.guest_message
        update._freeze()

        # 继续到后续handler
        return None
