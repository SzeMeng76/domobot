"""
网易云音乐链接自动识别处理器
在群组中自动检测 music.163.com / 163cn.tv / 163cn.link 链接并下载发送
参考 Music163bot-Go-2 的 URL 检测逻辑（bot/bot.go 190行）
"""

import logging

from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters

from utils.netease_api import contains_music_link, parse_music_id, parse_program_id, resolve_short_url
from utils.message_manager import delete_user_command

logger = logging.getLogger(__name__)

# 全局依赖（由 main.py 注入）
_cache_manager = None
_httpx_client = None
_pyrogram_helper = None


def set_dependencies(cache_manager, httpx_client, pyrogram_helper=None):
    """设置依赖"""
    global _cache_manager, _httpx_client, _pyrogram_helper
    _cache_manager = cache_manager
    _httpx_client = httpx_client
    _pyrogram_helper = pyrogram_helper


async def auto_music_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """自动检测网易云音乐链接并下载发送"""
    message = update.message
    if not message:
        return

    text = message.text or message.caption
    if not text:
        return

    # 检测是否包含网易云链接
    if not contains_music_link(text):
        return

    # 解析短链接
    resolved = await resolve_short_url(text, _httpx_client)

    # 尝试提取歌曲 ID
    song_id = parse_music_id(resolved)

    # 尝试电台节目
    if not song_id:
        program_id = parse_program_id(resolved)
        if program_id:
            from commands.music import _netease_api
            if _netease_api:
                song_id = await _netease_api.get_program_song_id(program_id)

    if not song_id:
        return

    chat_id = message.chat_id
    logger.info(f"检测到网易云链接，歌曲ID: {song_id}, 群组: {chat_id}")

    # 删除用户的链接消息
    await delete_user_command(context, chat_id, message.message_id)

    status_msg = await context.bot.send_message(chat_id=chat_id, text="🎵 检测到网易云音乐链接，处理中...")

    # 复用 music.py 的下载逻辑
    from commands.music import _download_and_send_music
    await _download_and_send_music(
        song_id, chat_id, context,
        status_message=status_msg,
    )


def setup_auto_music_handler(application):
    """注册自动音乐链接识别处理器"""
    handler = MessageHandler(
        (filters.TEXT | filters.CAPTION) & ~filters.COMMAND,
        auto_music_handler,
    )
    # 优先级 98，略高于 auto_parse_handler(99) 但低于命令
    application.add_handler(handler, group=98)
    logger.info("✅ 网易云音乐自动识别处理器已注册")
