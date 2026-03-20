"""
Inline 音乐处理器
参考 Music163bot-Go processInline.go + DomoBot inline_parse_handler.py 实现：
- 音乐链接/ID → 有缓存直接发音频，无缓存先占位再后台下载上传
- search 关键词 → 搜索结果列表，有缓存直接发音频，无缓存后台下载上传
- 使用 ChosenInlineResultHandler 实现后台下载+上传（参考 inline_parse_handler）
"""

import logging
import tempfile
import time
from html import escape as html_escape
from pathlib import Path
from uuid import uuid4

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InlineQueryResultCachedAudio,
    InputTextMessageContent,
)
from telegram.ext import ContextTypes

from utils.netease_api import parse_music_id, parse_program_id, resolve_short_url

logger = logging.getLogger(__name__)

# 内存缓存：存储待下载的歌曲信息（用户选择 inline 结果后后台下载）
_pending_downloads: dict[str, dict] = {}
_pending_timestamps: dict[str, float] = {}
PENDING_TTL = 300  # 5 分钟


def _cleanup_pending():
    """清理过期的 pending 缓存"""
    now = time.time()
    expired = [k for k, t in _pending_timestamps.items() if now - t > PENDING_TTL]
    for k in expired:
        _pending_downloads.pop(k, None)
        _pending_timestamps.pop(k, None)


async def handle_inline_music_link(
    query_text: str,
    inline_query,
    context: ContextTypes.DEFAULT_TYPE,
) -> list:
    """
    处理 inline 中的网易云音乐链接/ID（参考 processInlineMusic）
    - 有缓存 → InlineQueryResultCachedAudio 直接发送音频
    - 无缓存 → Article 占位，后台通过 ChosenInlineResultHandler 下载上传
    """
    _cleanup_pending()
    cache_manager = context.bot_data.get("cache_manager")
    httpx_client = context.bot_data.get("httpx_client")

    # 解析短链接
    resolved = await resolve_short_url(query_text, httpx_client)
    song_id = parse_music_id(resolved)

    if not song_id:
        program_id = parse_program_id(resolved)
        if program_id:
            from commands.music import _netease_api
            if _netease_api:
                song_id = await _netease_api.get_program_song_id(program_id)

    if not song_id:
        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="❌ 无法解析音乐链接",
                description="未能从链接中提取歌曲ID",
                input_message_content=InputTextMessageContent(
                    message_text=f"❌ 无法解析音乐链接: {query_text}"
                ),
            )
        ]

    return await _build_song_result(song_id, cache_manager, context)


async def handle_inline_music_search(
    keyword: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> list:
    """
    Inline 搜索歌曲（参考 processInlineSearch）
    有缓存 → 直接发音频；无缓存 → 占位 Article，后台下载上传
    """
    _cleanup_pending()

    if not keyword.strip():
        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="🎵 请输入搜索关键词",
                description="例如: music 晴天$",
                input_message_content=InputTextMessageContent(
                    message_text="🎵 请输入搜索关键词"
                ),
            )
        ]

    from commands.music import _netease_api
    if not _netease_api:
        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="❌ 音乐服务未初始化",
                description="请稍后重试",
                input_message_content=InputTextMessageContent(
                    message_text="❌ 音乐服务未初始化"
                ),
            )
        ]

    songs = await _netease_api.search_songs(keyword, limit=10)
    if not songs:
        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="❌ 未找到结果",
                description=f"关键词: {keyword}",
                input_message_content=InputTextMessageContent(
                    message_text=f"❌ 未找到与 \"{keyword}\" 相关的歌曲"
                ),
            )
        ]

    cache_manager = context.bot_data.get("cache_manager")
    results = []
    for s in songs:
        result = await _build_song_result(s["id"], cache_manager, context, song_info=s)
        results.extend(result)

    return results


async def _build_song_result(
    song_id: int,
    cache_manager,
    context: ContextTypes.DEFAULT_TYPE,
    song_info: dict = None,
) -> list:
    """
    构建单首歌的 inline 结果：
    - 有缓存 → CachedAudio
    - 无缓存 → Article 占位 + 注册 pending download
    """
    # 检查缓存
    cache_key = f"music:file:{song_id}"
    cached = await cache_manager.get(cache_key) if cache_manager else None

    if cached and cached.get("file_id"):
        # 有缓存：直接返回音频
        name = cached.get("name", "")
        artists = cached.get("artists", "")
        caption = cached.get("caption", f"🎵 {name} - {artists}")

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                text=f"{name} - {artists}",
                url=f"https://music.163.com/song?id={song_id}",
            )],
            [InlineKeyboardButton(
                text="Send me to...",
                switch_inline_query=f"https://music.163.com/song?id={song_id}",
            )],
        ])

        try:
            return [
                InlineQueryResultCachedAudio(
                    id=str(uuid4()),
                    audio_file_id=cached["file_id"],
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=keyboard,
                )
            ]
        except Exception as e:
            logger.warning(f"构建缓存音频结果失败: {e}")

    # 无缓存：获取歌曲详情
    name = ""
    artists = ""
    album = ""
    duration = 0

    if song_info:
        name = song_info.get("name", "")
        artists = song_info.get("artists", "")
        album = song_info.get("album", "")
        duration = song_info.get("duration", 0)
    else:
        from commands.music import _netease_api
        if _netease_api:
            detail = await _netease_api.get_song_detail(song_id)
            if detail:
                name = detail["name"]
                artists = detail["artists"]
                album = detail.get("album", "")
                duration = detail.get("duration", 0)

    display = f"{name} - {artists}" if name else f"歌曲 ID: {song_id}"
    dur_str = f" [{duration // 60}:{duration % 60:02d}]" if duration else ""

    # 注册 pending download（ChosenInlineResultHandler 会用到）
    result_id = f"music_dl_{song_id}_{int(time.time() * 1000000)}"
    _pending_downloads[result_id] = {
        "song_id": song_id,
        "name": name,
        "artists": artists,
        "album": album,
    }
    _pending_timestamps[result_id] = time.time()

    return [
        InlineQueryResultArticle(
            id=result_id,
            title=f"🎵 {name or song_id}",
            description=f"{artists} | {album}{dur_str}" if artists else "点击下载",
            input_message_content=InputTextMessageContent(
                message_text=f"🎵 <b>{html_escape(display)}</b>\n⏳ 下载中...",
                parse_mode="HTML",
            ),
        )
    ]


async def handle_inline_music_chosen(
    update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    用户选择 inline 音乐结果后的回调（参考 inline_parse_handler 的 handle_inline_parse_chosen）
    后台下载音频 → 用 Pyrogram edit_inline_media 替换成音频文件
    """
    chosen_result = update.chosen_inline_result
    result_id = chosen_result.result_id
    inline_message_id = chosen_result.inline_message_id

    # 只处理音乐下载
    if not result_id.startswith("music_dl_"):
        return

    pending = _pending_downloads.pop(result_id, None)
    _pending_timestamps.pop(result_id, None)

    if not pending:
        try:
            await context.bot.edit_message_text(
                inline_message_id=inline_message_id,
                text="❌ 下载请求已过期，请重新搜索"
            )
        except Exception:
            pass
        return

    song_id = pending["song_id"]
    name = pending.get("name", "")
    artists = pending.get("artists", "")
    display = f"{name} - {artists}" if name else str(song_id)

    from commands.music import _netease_api, _download_file, _embed_metadata
    from utils.config_manager import get_config
    import asyncio
    import shutil

    if not _netease_api:
        try:
            await context.bot.edit_message_text(
                inline_message_id=inline_message_id,
                text="❌ 音乐服务未初始化"
            )
        except Exception:
            pass
        return

    config = get_config()

    try:
        # 1. 获取详情和下载链接
        detail, song_url = await asyncio.gather(
            _netease_api.get_song_detail(song_id),
            _netease_api.get_song_url(song_id),
        )

        if not detail:
            await context.bot.edit_message_text(
                inline_message_id=inline_message_id,
                text=f"❌ 未找到歌曲: {display}"
            )
            return

        if not song_url or not song_url.get("url"):
            await context.bot.edit_message_text(
                inline_message_id=inline_message_id,
                text=f"🎵 <b>{html_escape(display)}</b>\n❌ 暂无可用音源（可能需要 VIP）",
                parse_mode="HTML",
            )
            return

        # 2. 更新状态
        size_mb = song_url["size"] / (1024 * 1024)
        try:
            await context.bot.edit_message_text(
                inline_message_id=inline_message_id,
                text=f"🎵 <b>{html_escape(display)}</b>\n⬇️ 下载中... ({size_mb:.1f}MB)",
                parse_mode="HTML",
            )
        except Exception:
            pass

        # 3. 下载
        tmp_dir = Path(tempfile.mkdtemp(prefix="music_inline_"))
        audio_path = tmp_dir / f"{song_id}.{song_url['type']}"
        thumb_path = tmp_dir / f"{song_id}_cover.jpg"

        try:
            download_ok = await _download_file(
                song_url["url"], audio_path, song_url.get("md5"), config.music_download_timeout
            )
            if not download_ok:
                await context.bot.edit_message_text(
                    inline_message_id=inline_message_id,
                    text=f"🎵 <b>{html_escape(display)}</b>\n❌ 下载失败",
                    parse_mode="HTML",
                )
                return

            # 下载封面
            cover_downloaded = False
            if detail.get("pic_url"):
                try:
                    cover_downloaded = await _download_file(detail["pic_url"], thumb_path, timeout=15)
                except Exception:
                    pass

            # 4. 嵌入元数据
            await _embed_metadata(audio_path, detail, thumb_path if cover_downloaded else None)

            # 5. 上传状态
            try:
                await context.bot.edit_message_text(
                    inline_message_id=inline_message_id,
                    text=f"🎵 <b>{html_escape(display)}</b>\n📤 上传中...",
                    parse_mode="HTML",
                )
            except Exception:
                pass

            # 6. 用 Pyrogram edit_inline_media 替换成音频
            from commands.music import _pyrogram_helper

            if _pyrogram_helper and _pyrogram_helper.is_started and _pyrogram_helper.client:
                from pyrogram.types import InputMediaAudio as PyrogramInputMediaAudio
                from pyrogram.enums import ParseMode as PyrogramParseMode

                # 构建 caption
                file_ext = song_url.get("type", "mp3").upper()
                bitrate_kbps = song_url.get("br", 0) / 1000
                quality_tag = "FLAC 无损" if file_ext == "FLAC" else f"MP3 {bitrate_kbps:.0f}kbps"
                caption = (
                    f"🎵 <b>{html_escape(detail['name'])}</b>\n"
                    f"👤 {html_escape(detail['artists'])}\n"
                    f"💿 {html_escape(detail['album'])}\n"
                    f"🎧 {quality_tag} | {size_mb:.1f}MB"
                )

                await _pyrogram_helper.client.edit_inline_media(
                    inline_message_id=inline_message_id,
                    media=PyrogramInputMediaAudio(
                        media=str(audio_path),
                        caption=caption,
                        parse_mode=PyrogramParseMode.HTML,
                        duration=detail.get("duration", 0),
                        performer=detail.get("artists", ""),
                        title=detail.get("name", ""),
                        thumb=str(thumb_path) if cover_downloaded else None,
                    )
                )
                logger.info(f"[Inline Music] edit_inline_media 成功: {display}")

                # 7. 获取 file_id 缓存（从 Pyrogram 无法直接获取，但下次用户 /music 会缓存）

            else:
                # Pyrogram 不可用 → 告知用户用 /music 命令
                await context.bot.edit_message_text(
                    inline_message_id=inline_message_id,
                    text=(
                        f"🎵 <b>{html_escape(display)}</b>\n"
                        f"❌ Inline 上传不可用\n"
                        f"💡 请在对话中发送 /music {song_id} 下载"
                    ),
                    parse_mode="HTML",
                )

        finally:
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass

    except Exception as e:
        logger.error(f"[Inline Music] 处理失败: {e}", exc_info=True)
        try:
            await context.bot.edit_message_text(
                inline_message_id=inline_message_id,
                text=f"🎵 <b>{html_escape(display)}</b>\n❌ 处理失败: {html_escape(str(e))}",
                parse_mode="HTML",
            )
        except Exception:
            pass
