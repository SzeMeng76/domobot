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
        """检查是否应该处理此update - 所有update都需要处理以清除旧的guest标记"""
        return isinstance(update, Update)

    async def _process(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        处理update，如果是guest bot消息则注入context

        Returns:
            None表示继续处理，其他值表示终止
        """
        # 重要：先清除旧的guest标记，避免污染
        context.user_data.pop('is_guest_bot_call', None)
        context.user_data.pop('guest_query_id', None)
        context.user_data.pop('guest_caller_chat', None)

        # 清除contextvars里的guest_query_id
        from utils.guest_bot_wrapper import _current_guest_query_id, _current_inline_message_id, _current_guest_user_id
        _current_guest_query_id.set(None)
        _current_inline_message_id.set(None)
        _current_guest_user_id.set(None)

        # 检查是否是guest bot消息
        if not self.guest_bot_handler.is_guest_bot_message(update):
            return None  # 不是guest bot消息，继续

        # 进行权限检查和context注入
        authorized = await self.guest_bot_handler.process_guest_message(update, context)

        if not authorized:
            # 未授权，已发送拒绝消息，停止处理
            return True  # 停止后续handler

        # 授权通过，注入guest context到message对象
        from utils.guest_bot_wrapper import inject_guest_context_to_message, _current_guest_query_id, _current_guest_user_id
        inject_guest_context_to_message(update.guest_message, context)

        # 设置contextvars，让所有send_message调用都能拦截（包括没有注入_guest_query_id的）
        guest_query_id = context.user_data.get('guest_query_id')
        _current_guest_query_id.set(guest_query_id)
        # 设置user_id，用于媒体私聊中转
        _current_guest_user_id.set(update.guest_message.from_user.id if update.guest_message.from_user else None)

        # 关键修复：把guest_message复制到update.message
        # 让后续的CommandHandler、ConversationHandler等能识别
        update._unfreeze()
        update.message = update.guest_message

        # 修复命令文本：去掉 @botname 前缀，让CommandHandler能识别
        # Guest message格式: "@mengpricebot /help args" -> "/help args"
        # 同时修复entities的offset，filters.COMMAND要求bot_command entity offset=0
        if update.message.text and update.message.text.startswith('@'):
            parts = update.message.text.split(maxsplit=1)
            if len(parts) > 1:
                mention_len = len(parts[0]) + 1  # "@botname "的长度
                new_text = parts[1]
                object.__setattr__(update.message, 'text', new_text)

                # 修复entities：去掉mention entity，调整其他entity的offset
                if update.message.entities:
                    from telegram import MessageEntity
                    new_entities = []
                    for entity in update.message.entities:
                        if entity.type == 'mention':
                            continue  # 去掉mention entity
                        new_offset = entity.offset - mention_len
                        if new_offset >= 0:
                            new_entities.append(MessageEntity(
                                type=entity.type,
                                offset=new_offset,
                                length=entity.length,
                            ))
                    object.__setattr__(update.message, 'entities', tuple(new_entities))
                logger.debug(f"Stripped bot mention, new text: '{new_text}'")

        update._freeze()

        # 继续到后续handler
        return None
