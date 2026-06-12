"""
Guest Bot Wrapper - 拦截并重定向bot响应到guest query
通过monkey patch Message的reply方法和Bot的send方法来实现透明的guest bot支持

对于媒体消息（图片/视频/音频），使用私聊中转技术：
1. 先发送占位文本到guest query（获得inline_message_id）
2. 暂存媒体到用户私聊（获得file_id）
3. 用editMessageMedia替换占位文本为媒体
"""
import logging
from contextvars import ContextVar
from telegram import Message, Bot
from telegram.ext import ContextTypes, ExtBot
from telegram.error import TelegramError

logger = logging.getLogger(__name__)

# 用contextvars存储当前请求的guest_query_id，线程/协程安全
# 在middleware里设置，wrapper里读取，无需修改任何命令代码
_current_guest_query_id: ContextVar[str | None] = ContextVar('guest_query_id', default=None)
# 第一次answer_guest_query后存inline_message_id，后续用editMessageText
_current_inline_message_id: ContextVar[str | None] = ContextVar('inline_message_id', default=None)

# 保存原始方法
_original_reply_text = Message.reply_text
_original_reply_photo = Message.reply_photo
_original_reply_document = Message.reply_document
_original_reply_video = Message.reply_video
_original_reply_audio = Message.reply_audio
_original_bot_send_message = None


class GuestMessageProxy:
    """
    代理对象，模拟Message对象的edit_text/edit_caption等方法
    用于guest bot模式下，命令代码调用message.edit_text()时，
    实际上通过editMessageText编辑inline message
    """
    def __init__(self, bot, inline_message_id: str, chat_id=None, message_id=None):
        self._bot = bot
        self._inline_message_id = inline_message_id
        self.chat_id = chat_id
        self.message_id = message_id or 0

    async def edit_text(self, text: str, **kwargs):
        try:
            await self._bot.edit_message_text(
                inline_message_id=self._inline_message_id,
                text=text,
                parse_mode=kwargs.get('parse_mode'),
                reply_markup=kwargs.get('reply_markup'),
            )
            logger.debug(f"GuestMessageProxy.edit_text: edited inline message")
        except Exception as e:
            if 'not modified' in str(e).lower():
                pass  # 内容相同，忽略
            else:
                logger.error(f"GuestMessageProxy.edit_text failed: {e}")

    async def edit_caption(self, caption: str, **kwargs):
        await self.edit_text(caption, **kwargs)

    async def delete(self):
        pass  # guest模式下不能删除inline message，忽略

    async def reply_text(self, text: str, **kwargs):
        guest_query_id = _current_guest_query_id.get()
        if guest_query_id:
            return await _send_guest_response(guest_query_id, self._bot, text, **kwargs)


async def _guest_aware_reply_text(self, text: str, *args, **kwargs):
    """支持Guest Bot的reply_text"""
    if hasattr(self, '_guest_query_id') and self._guest_query_id:
        logger.info(f"Intercepted reply_text for guest query {self._guest_query_id}")
        return await _send_guest_response(self._guest_query_id, self.get_bot(), text=text, **kwargs)
    return await _original_reply_text(self, text, *args, **kwargs)


async def _guest_aware_reply_photo(self, photo, *args, **kwargs):
    """支持Guest Bot的reply_photo - 通过私聊中转"""
    if hasattr(self, '_guest_query_id') and self._guest_query_id:
        user_id = self.from_user.id if self.from_user else None
        if not user_id:
            logger.error("No user_id for guest photo reply")
            return await _original_reply_photo(self, photo, *args, **kwargs)

        caption = kwargs.get('caption', '')
        logger.info(f"Guest Bot reply_photo: staging to private chat {user_id}")

        # 尝试通过私聊中转
        success = await _send_guest_media(
            self.get_bot(),
            self._guest_query_id,
            user_id,
            'photo',
            photo,
            caption,
            **kwargs
        )

        if success:
            return None  # 已通过guest方式发送

        # 失败则降级为文本
        logger.warning("Guest Bot photo staging failed, falling back to text")
        fallback_text = f"📷 {caption}\n\n⚠️ 图片发送失败\n💡 请先私聊bot发送 /start 开启私聊，然后重试"
        return await _send_guest_response(self._guest_query_id, self.get_bot(), text=fallback_text)

    return await _original_reply_photo(self, photo, *args, **kwargs)


async def _guest_aware_reply_audio(self, audio, *args, **kwargs):
    """支持Guest Bot的reply_audio - 通过私聊中转"""
    if hasattr(self, '_guest_query_id') and self._guest_query_id:
        user_id = self.from_user.id if self.from_user else None
        if not user_id:
            return await _original_reply_audio(self, audio, *args, **kwargs)

        caption = kwargs.get('caption', '')
        logger.info(f"Guest Bot reply_audio: staging to private chat {user_id}")

        success = await _send_guest_media(
            self.get_bot(),
            self._guest_query_id,
            user_id,
            'audio',
            audio,
            caption,
            **kwargs
        )

        if success:
            return None

        fallback_text = f"🎵 {caption}\n\n⚠️ 音频发送失败\n💡 请先私聊bot发送 /start 开启私聊，然后重试"
        return await _send_guest_response(self._guest_query_id, self.get_bot(), text=fallback_text)

    return await _original_reply_audio(self, audio, *args, **kwargs)


async def _guest_aware_reply_document(self, document, *args, **kwargs):
    """支持Guest Bot的reply_document - 通过私聊中转"""
    if hasattr(self, '_guest_query_id') and self._guest_query_id:
        user_id = self.from_user.id if self.from_user else None
        if not user_id:
            return await _original_reply_document(self, document, *args, **kwargs)

        caption = kwargs.get('caption', '')
        logger.info(f"Guest Bot reply_document: staging to private chat {user_id}")

        success = await _send_guest_media(
            self.get_bot(),
            self._guest_query_id,
            user_id,
            'document',
            document,
            caption,
            **kwargs
        )

        if success:
            return None

        fallback_text = f"📄 {caption}\n\n⚠️ 文档发送失败\n💡 请先私聊bot发送 /start 开启私聊，然后重试"
        return await _send_guest_response(self._guest_query_id, self.get_bot(), text=fallback_text)

    return await _original_reply_document(self, document, *args, **kwargs)


async def _guest_aware_reply_video(self, video, *args, **kwargs):
    """支持Guest Bot的reply_video - 通过私聊中转"""
    if hasattr(self, '_guest_query_id') and self._guest_query_id:
        user_id = self.from_user.id if self.from_user else None
        if not user_id:
            return await _original_reply_video(self, video, *args, **kwargs)

        caption = kwargs.get('caption', '')
        logger.info(f"Guest Bot reply_video: staging to private chat {user_id}")

        success = await _send_guest_media(
            self.get_bot(),
            self._guest_query_id,
            user_id,
            'video',
            video,
            caption,
            **kwargs
        )

        if success:
            return None

        fallback_text = f"🎥 {caption}\n\n⚠️ 视频发送失败\n💡 请先私聊bot发送 /start 开启私聊，然后重试"
        return await _send_guest_response(self._guest_query_id, self.get_bot(), text=fallback_text)

    return await _original_reply_video(self, video, *args, **kwargs)


async def _send_guest_response(guest_query_id: str, bot, text: str, **kwargs):
    """统一的Guest Bot文本响应发送函数

    第一次调用：answer_guest_query发送消息，存储inline_message_id
    后续调用：editMessageText编辑消息（同一个guest_query只能answer一次）
    """
    from telegram import InlineQueryResultArticle, InputTextMessageContent

    parse_mode = kwargs.get('parse_mode')
    disable_web_page_preview = kwargs.get('disable_web_page_preview', False)
    reply_markup = kwargs.get('reply_markup')

    # 检查是否已经有inline_message_id（说明已经answer过了）
    inline_message_id = _current_inline_message_id.get()
    if inline_message_id:
        # 后续调用：用editMessageText编辑消息
        try:
            await bot.edit_message_text(
                inline_message_id=inline_message_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
            )
            logger.info(f"Edited guest query message via inline_message_id")
            return GuestMessageProxy(bot, inline_message_id)
        except Exception as e:
            if 'not modified' in str(e).lower():
                return GuestMessageProxy(bot, inline_message_id)
            logger.error(f"Failed to edit guest query message: {e}")
            raise

    # 第一次调用：answer_guest_query
    input_content = InputTextMessageContent(
        message_text=text,
        parse_mode=parse_mode,
        disable_web_page_preview=disable_web_page_preview
    )
    result = InlineQueryResultArticle(
        id=guest_query_id[:64],
        title="Response",
        input_message_content=input_content,
        reply_markup=reply_markup
    )

    try:
        sent_msg = await bot.answer_guest_query(
            guest_query_id=guest_query_id,
            result=result
        )
        # 存储inline_message_id供后续编辑使用
        inline_msg_id = None
        if sent_msg and hasattr(sent_msg, 'inline_message_id') and sent_msg.inline_message_id:
            inline_msg_id = sent_msg.inline_message_id
            _current_inline_message_id.set(inline_msg_id)
            logger.info(f"Stored inline_message_id for future edits: {inline_msg_id}")
        logger.info(f"Successfully sent guest query text response")
        # 返回GuestMessageProxy，让命令代码可以调用edit_text等方法
        if inline_msg_id:
            return GuestMessageProxy(bot, inline_msg_id)
        return sent_msg
    except Exception as e:
        logger.error(f"Failed to send guest query response: {e}")
        raise


async def _send_guest_media(bot: Bot, guest_query_id: str, user_id: int, media_type: str, media, caption: str, **kwargs):
    """
    通过私聊中转发送媒体到Guest Bot（在群组中显示）

    正确流程：
    1. 先发送占位文本到guest query（获得inline_message_id）
    2. 暂存媒体到用户私聊（获得file_id）
    3. 用editMessageMedia替换占位文本为媒体（在群组中显示）
    4. 删除私聊中的暂存消息

    Returns:
        True=成功，False=失败
    """
    from telegram import InlineQueryResultArticle, InputTextMessageContent, InputMediaPhoto, InputMediaDocument, InputMediaVideo, InputMediaAudio

    try:
        # 检查是否已经有inline_message_id（loading消息已经answer过了）
        inline_message_id = _current_inline_message_id.get()

        if not inline_message_id:
            # 步骤1：发送占位文本，获得inline_message_id
            placeholder = InputTextMessageContent(
                message_text=f"🔄 正在加载{_media_type_cn(media_type)}..."
            )
            result = InlineQueryResultArticle(
                id=guest_query_id[:64],
                title="Loading...",
                input_message_content=placeholder
            )
            logger.info(f"Sending placeholder for guest query {guest_query_id}")
            sent_msg = await bot.answer_guest_query(guest_query_id, result)
            inline_message_id = sent_msg.inline_message_id if hasattr(sent_msg, 'inline_message_id') else None
            if inline_message_id:
                _current_inline_message_id.set(inline_message_id)
                logger.info(f"Got inline_message_id: {inline_message_id}")

        if not inline_message_id:
            logger.error("Failed to get inline_message_id")
            return False

        # 步骤2：暂存到私聊获取file_id
        logger.info(f"Staging {media_type} to private chat {user_id}")
        file_id = await _stage_media_to_private(bot, user_id, media_type, media)

        if not file_id:
            logger.error("Failed to get file_id from staging")
            # 更新占位文本为错误提示
            await bot.edit_message_text(
                inline_message_id=inline_message_id,
                text=f"⚠️ {_media_type_cn(media_type)}发送失败\n💡 请先私聊bot发送 /start 开启私聊"
            )
            return False

        # 步骤3：用editMessageMedia替换占位文本为媒体
        logger.info(f"Editing message with media file_id={file_id}")

        # 构建InputMedia对象
        input_media = None
        if media_type == 'photo':
            input_media = InputMediaPhoto(media=file_id, caption=caption)
        elif media_type == 'audio':
            input_media = InputMediaAudio(media=file_id, caption=caption)
        elif media_type == 'document':
            input_media = InputMediaDocument(media=file_id, caption=caption)
        elif media_type == 'video':
            input_media = InputMediaVideo(media=file_id, caption=caption)

        # 编辑消息，替换为媒体（在群组中显示！）
        await bot.edit_message_media(
            inline_message_id=inline_message_id,
            media=input_media
        )

        logger.info(f"Successfully sent {media_type} via guest bot (displayed in group)")
        return True

    except Exception as e:
        logger.error(f"Failed to send guest media: {e}")
        return False


async def _stage_media_to_private(bot: Bot, user_id: int, media_type: str, media) -> str | None:
    """
    暂存媒体到用户私聊，获取file_id，然后删除消息

    Returns:
        file_id或None
    """
    try:
        staging_caption = f"🔄 正在准备{_media_type_cn(media_type)}..."

        # 根据类型发送
        msg = None
        if media_type == 'photo':
            msg = await bot.send_photo(chat_id=user_id, photo=media, caption=staging_caption)
            file_id = msg.photo[-1].file_id if msg.photo else None
        elif media_type == 'audio':
            msg = await bot.send_audio(chat_id=user_id, audio=media, caption=staging_caption)
            file_id = msg.audio.file_id if msg.audio else None
        elif media_type == 'document':
            msg = await bot.send_document(chat_id=user_id, document=media, caption=staging_caption)
            file_id = msg.document.file_id if msg.document else None
        elif media_type == 'video':
            msg = await bot.send_video(chat_id=user_id, video=media, caption=staging_caption)
            file_id = msg.video.file_id if msg.video else None
        else:
            return None

        if not file_id or not msg:
            return None

        logger.info(f"Staged {media_type} to private, file_id={file_id}")

        # 立即删除暂存消息
        try:
            await bot.delete_message(chat_id=user_id, message_id=msg.message_id)
            logger.debug(f"Deleted staging message {msg.message_id}")
        except Exception as e:
            logger.warning(f"Failed to delete staging message: {e}")

        return file_id

    except TelegramError as e:
        if "Forbidden" in str(e) or "403" in str(e):
            logger.warning(f"User {user_id} has not started private chat with bot")
        else:
            logger.error(f"Failed to stage {media_type}: {e}")
        return None


def _media_type_cn(media_type: str) -> str:
    """媒体类型中文名"""
    mapping = {
        'photo': '图片',
        'audio': '音频',
        'document': '文档',
        'video': '视频',
    }
    return mapping.get(media_type, '媒体')


def _wrap_bot_send_message(original_func):
    """包装bot.send_message以支持guest_query_id参数"""
    async def wrapper(*args, **kwargs):
        # 优先使用显式传入的_guest_query_id，其次用contextvars里的
        guest_query_id = kwargs.pop('_guest_query_id', None) or _current_guest_query_id.get()
        if guest_query_id:
            text = kwargs.pop('text', None)
            bot = args[0] if args and isinstance(args[0], (Bot, ExtBot)) else None
            if bot and text:
                logger.info(f"Redirecting bot.send_message to guest query {guest_query_id}")
                return await _send_guest_response(guest_query_id, bot, text, **kwargs)
        return await original_func(*args, **kwargs)
    return wrapper


def install_guest_bot_patches():
    """安装Guest Bot补丁，使reply方法支持guest query（包含媒体中转）"""
    global _original_bot_send_message
    from telegram.ext import ExtBot

    # Patch Message类的方法
    Message.reply_text = _guest_aware_reply_text
    Message.reply_photo = _guest_aware_reply_photo
    Message.reply_audio = _guest_aware_reply_audio
    Message.reply_document = _guest_aware_reply_document
    Message.reply_video = _guest_aware_reply_video

    # Patch Bot类和ExtBot类的send方法（都要patch，因为实例可能用ExtBot）
    _original_bot_send_message = Bot.send_message
    wrapped = _wrap_bot_send_message(_original_bot_send_message)
    Bot.send_message = wrapped
    ExtBot.send_message = wrapped

    logger.info("✅ Guest Bot patches installed (with media staging support)")


def inject_guest_context_to_message(message: Message, context: ContextTypes.DEFAULT_TYPE):
    """
    将guest context信息注入到Message对象

    Note: Message对象是frozen的，不能动态添加属性。
    guest_query_id已经存储在context.user_data中，无需注入到message对象。

    Args:
        message: Message对象
        context: Context对象（包含user_data）
    """
    # No-op: context.user_data已经包含guest_query_id，无需注入到message
    if context.user_data.get('is_guest_bot_call'):
        logger.debug(f"Guest context available in context.user_data for message {message.message_id}")
    pass


def inject_guest_context_to_kwargs(kwargs: dict, context: ContextTypes.DEFAULT_TYPE):
    """
    将guest_query_id注入到kwargs中，用于bot.send_message等直接调用

    Usage in commands:
        kwargs = {'text': 'hello'}
        inject_guest_context_to_kwargs(kwargs, context)
        await context.bot.send_message(chat_id=..., **kwargs)
    """
    if context.user_data.get('is_guest_bot_call'):
        kwargs['_guest_query_id'] = context.user_data.get('guest_query_id')



