"""
Inline YouTube Music 处理器
参考 inline_music_handler.py（网易云实现）：
- YouTube 链接/videoId → 有缓存直接发音频，无缓存先占位再后台下载上传
- 搜索关键词 → 搜索结果列表，有缓存直接发音频，无缓存后台下载上传
- 使用 ChosenInlineResultHandler 实现后台下载+上传
"""

import logging
import shutil
import tempfile
import time
from html import escape as html_escape
from pathlib import Path
from uuid import uuid4

from typing import Optional

import httpx
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InlineQueryResultCachedAudio,
    InputTextMessageContent,
)
from telegram.ext import ContextTypes

from utils.ytmusic_api import download_audio, get_thumbnail_url, parse_video_id

logger = logging.getLogger(__name__)

# 内存缓存：存储待下载的歌曲信息
_pending_downloads: dict[str, dict] = {}
_pending_timestamps: dict[str, float] = {}
PENDING_TTL = 300  # 5 分钟


def _cleanup_pending():
    now = time.time()
    expired = [k for k, t in _pending_timestamps.items() if now - t > PENDING_TTL]
    for k in expired:
        _pending_downloads.pop(k, None)
        _pending_timestamps.pop(k, None)


async def handle_inline_ytmusic_link(
    query_text: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> list:
    """处理 inline 中的 YouTube 链接/videoId"""
    _cleanup_pending()
    video_id = parse_video_id(query_text)
    if not video_id:
        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="❌ 无法解析 YouTube 链接",
                description="未能从链接中提取 videoId",
                input_message_content=InputTextMessageContent(
                    message_text=f"❌ 无法解析 YouTube 链接: {query_text}"
                ),
            )
        ]
    cache_manager = context.bot_data.get("cache_manager")
    return await _build_video_result(video_id, cache_manager, context)


async def handle_inline_ytmusic_search(
    keyword: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> list:
    """Inline 搜索 YouTube Music 歌曲"""
    _cleanup_pending()

    if not keyword.strip():
        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="🎵 请输入搜索关键词",
                description="例如: yt 晴天$",
                input_message_content=InputTextMessageContent(
                    message_text="🎵 请输入搜索关键词"
                ),
            )
        ]

    from commands.ytmusic import _ytmusic_api
    if not _ytmusic_api:
        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="❌ YouTube Music 服务未初始化",
                description="请稍后重试",
                input_message_content=InputTextMessageContent(
                    message_text="❌ YouTube Music 服务未初始化"
                ),
            )
        ]

    songs = await _ytmusic_api.search_songs(keyword, limit=10)
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
        result = await _build_video_result(s["videoId"], cache_manager, context, song_info=s)
        results.extend(result)
    return results


async def _build_video_result(
    video_id: str,
    cache_manager,
    context: ContextTypes.DEFAULT_TYPE,
    song_info: Optional[dict] = None,
) -> list:
    """构建单首歌的 inline 结果：有缓存 → CachedAudio，无缓存 → Article 占位"""
    cache_key = f"ytmusic:file:{video_id}"
    cached = await cache_manager.get(cache_key) if cache_manager else None

    if cached and cached.get("file_id"):
        name = cached.get("name", "")
        artists = cached.get("artists", "")
        caption = cached.get("caption", f"🎵 {name} - {artists}")
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                text=f"{name} - {artists}",
                url=f"https://music.youtube.com/watch?v={video_id}",
            )
        ]])
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

    # 无缓存：从 song_info 或 API 获取详情
    name = ""
    artists = ""
    duration = 0

    if song_info:
        name = song_info.get("name", "")
        artists = song_info.get("artists", "")
        duration = song_info.get("duration", 0)
    else:
        from commands.ytmusic import _ytmusic_api
        if _ytmusic_api:
            detail = await _ytmusic_api.get_song_detail(video_id)
            if detail:
                name = detail["name"]
                artists = detail["artists"]
                duration = detail.get("duration", 0)

    display = f"{name} - {artists}" if name else video_id
    dur_str = f" [{duration // 60}:{duration % 60:02d}]" if duration else ""

    result_id = f"ytm_dl_{video_id}_{int(time.time() * 1000000)}"
    _pending_downloads[result_id] = {
        "video_id": video_id,
        "name": name,
        "artists": artists,
    }
    _pending_timestamps[result_id] = time.time()

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            text=f"🎵 {name or video_id}",
            url=f"https://music.youtube.com/watch?v={video_id}",
        )
    ]])

    return [
        InlineQueryResultArticle(
            id=result_id,
            title=f"🎵 {name or video_id}",
            description=f"{artists}{dur_str}" if artists else "点击下载",
            input_message_content=InputTextMessageContent(
                message_text=f"🎵 <b>{html_escape(display)}</b>\n⏳ 下载中...",
                parse_mode="HTML",
            ),
            reply_markup=keyboard,
        )
    ]


async def handle_inline_ytmusic_chosen(
    update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """用户选择 inline YouTube Music 结果后的回调，后台下载上传"""
    chosen_result = update.chosen_inline_result
    result_id = chosen_result.result_id
    inline_message_id = chosen_result.inline_message_id

    if not result_id.startswith("ytm_dl_"):
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

    video_id = pending["video_id"]
    name = pending.get("name", "")
    artists = pending.get("artists", "")
    display = f"{name} - {artists}" if name else video_id

    from commands.ytmusic import _ytmusic_api, _pyrogram_helper, _cache_manager, _httpx_client, CACHE_FILE_PREFIX

    if not _ytmusic_api:
        try:
            await context.bot.edit_message_text(
                inline_message_id=inline_message_id,
                text="❌ YouTube Music 服务未初始化"
            )
        except Exception:
            pass
        return

    try:
        # 1. 检查 Redis 缓存
        cache_key = f"{CACHE_FILE_PREFIX}:{video_id}"
        cached = await _cache_manager.get(cache_key) if _cache_manager else None
        if cached and cached.get("file_id"):
            if _pyrogram_helper and _pyrogram_helper.is_started and _pyrogram_helper.client:
                from pyrogram.types import InputMediaAudio as PyrogramInputMediaAudio
                from pyrogram.enums import ParseMode as PyrogramParseMode
                await _pyrogram_helper.client.edit_inline_media(
                    inline_message_id=inline_message_id,
                    media=PyrogramInputMediaAudio(
                        media=cached["file_id"],
                        caption=cached.get("caption", ""),
                        parse_mode=PyrogramParseMode.HTML,
                        performer=cached.get("artists", ""),
                        title=cached.get("name", ""),
                    )
                )
            return

        # 2. 获取详情（补全 name/artists）
        if not name:
            detail = await _ytmusic_api.get_song_detail(video_id)
            if detail:
                name = detail["name"]
                artists = detail["artists"]
                display = f"{name} - {artists}"

        try:
            await context.bot.edit_message_text(
                inline_message_id=inline_message_id,
                text=f"🎵 <b>{html_escape(display)}</b>\n⬇️ 下载中...",
                parse_mode="HTML",
            )
        except Exception:
            pass

        # 3. 下载音频
        tmp_dir = Path(tempfile.mkdtemp(prefix="ytm_inline_"))
        try:
            result = await download_audio(video_id, tmp_dir)
            if not result:
                await context.bot.edit_message_text(
                    inline_message_id=inline_message_id,
                    text=f"🎵 <b>{html_escape(display)}</b>\n❌ 下载失败",
                    parse_mode="HTML",
                )
                return

            audio_path, dl_title, duration, author = result
            name = name or dl_title
            artists = artists or author
            display = f"{name} - {artists}" if name else video_id

            # 4. 下载封面
            thumb_path = tmp_dir / f"{video_id}_cover.jpg"
            cover_downloaded = False
            detail = await _ytmusic_api.get_song_detail(video_id)
            if detail:
                thumb_url = get_thumbnail_url(detail.get("thumbnails", []))
                if thumb_url:
                    try:
                        client = _httpx_client or httpx.AsyncClient(timeout=15)
                        resp = await client.get(thumb_url)
                        if resp.status_code == 200:
                            thumb_path.write_bytes(resp.content)
                            cover_downloaded = True
                        if not _httpx_client:
                            await client.aclose()
                    except Exception:
                        pass

            # 5. 上传
            try:
                await context.bot.edit_message_text(
                    inline_message_id=inline_message_id,
                    text=f"🎵 <b>{html_escape(display)}</b>\n📤 上传中...",
                    parse_mode="HTML",
                )
            except Exception:
                pass

            file_size_mb = audio_path.stat().st_size / (1024 * 1024)
            caption = (
                f"🎵 <b>{html_escape(name)}</b>\n"
                f"👤 {html_escape(artists)}\n"
                f"🎧 YouTube Music | {file_size_mb:.1f}MB"
            )

            if _pyrogram_helper and _pyrogram_helper.is_started and _pyrogram_helper.client:
                from pyrogram.types import InputMediaAudio as PyrogramInputMediaAudio
                from pyrogram.enums import ParseMode as PyrogramParseMode

                await _pyrogram_helper.client.edit_inline_media(
                    inline_message_id=inline_message_id,
                    media=PyrogramInputMediaAudio(
                        media=str(audio_path),
                        caption=caption,
                        parse_mode=PyrogramParseMode.HTML,
                        duration=duration,
                        performer=artists,
                        title=name,
                        thumb=str(thumb_path) if cover_downloaded else None,
                    )
                )
                logger.info(f"[Inline YTMusic] edit_inline_media 成功: {display}")

                # 6. 缓存 file_id（无法从 edit_inline_media 获取，下次 /yt 命令会缓存）
            else:
                await context.bot.edit_message_text(
                    inline_message_id=inline_message_id,
                    text=(
                        f"🎵 <b>{html_escape(display)}</b>\n"
                        f"❌ Inline 上传不可用\n"
                        f"💡 请在对话中发送 /yt {video_id} 下载"
                    ),
                    parse_mode="HTML",
                )

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    except Exception as e:
        logger.error(f"[Inline YTMusic] 处理失败: {e}", exc_info=True)
        try:
            await context.bot.edit_message_text(
                inline_message_id=inline_message_id,
                text=f"🎵 <b>{html_escape(display)}</b>\n❌ 处理失败: {html_escape(str(e))}",
                parse_mode="HTML",
            )
        except Exception:
            pass
