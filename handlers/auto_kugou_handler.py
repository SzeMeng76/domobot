"""
酷狗音乐链接自动识别处理器
在群组中检测 kugou.com / t.kugou.com 链接并自动下载发送
"""

import logging

from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters

from utils.kugou_api import contains_kugou_link, parse_kugou_hash, resolve_kugou_short_url
from utils.message_manager import delete_user_command

logger = logging.getLogger(__name__)

_cache_manager = None
_httpx_client = None
_pyrogram_helper = None


def set_dependencies(cache_manager, httpx_client, pyrogram_helper=None):
    global _cache_manager, _httpx_client, _pyrogram_helper
    _cache_manager = cache_manager
    _httpx_client = httpx_client
    _pyrogram_helper = pyrogram_helper


async def auto_kugou_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """自动检测酷狗链接并下载"""
    message = update.message
    if not message:
        return
    text = message.text or message.caption
    if not text:
        return
    if not contains_kugou_link(text):
        return

    # 解析短链(t.kugou.com)
    resolved = await resolve_kugou_short_url(text, _httpx_client)
    parsed = parse_kugou_hash(resolved)
    if not parsed:
        return

    hash_, aid = parsed
    chat_id = message.chat_id
    logger.info(f"检测到酷狗链接,hash={hash_}, 群组: {chat_id}")

    await delete_user_command(context, chat_id, message.message_id)

    from commands.kugou import _download_and_send_kugou, _stash_meta, is_enabled
    if not is_enabled():
        return

    status_msg = await context.bot.send_message(chat_id=chat_id, text="🎵 检测到酷狗链接,处理中...")
    meta = {"hash": hash_, "album_audio_id": aid, "name": "", "artists": "", "album": "", "duration": 0}
    _stash_meta(meta)
    await _download_and_send_kugou(meta, chat_id, context, status_message=status_msg)


def setup_auto_kugou_handler(application):
    """注册酷狗自动识别处理器"""
    handler = MessageHandler(
        (filters.TEXT | filters.CAPTION) & ~filters.COMMAND,
        auto_kugou_handler,
    )
    application.add_handler(handler, group=97)  # 比 auto_music_handler(98) 略高
    logger.info("✅ 酷狗音乐自动识别处理器已注册")
