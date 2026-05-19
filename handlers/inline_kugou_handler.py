"""
Inline 酷狗音乐处理器
- 酷狗链接 → 解析 hash → 后台下载上传(ChosenInlineResult)
- search 关键词 → 搜索结果列表 → 选中后后台下载上传
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

from utils.kugou_api import parse_kugou_hash, resolve_kugou_short_url

logger = logging.getLogger(__name__)

# 内存缓存:存待下载的歌曲信息
_pending_downloads: dict[str, dict] = {}
_pending_timestamps: dict[str, float] = {}
PENDING_TTL = 300  # 5 分钟


def _cleanup_pending():
    now = time.time()
    expired = [k for k, t in _pending_timestamps.items() if now - t > PENDING_TTL]
    for k in expired:
        _pending_downloads.pop(k, None)
        _pending_timestamps.pop(k, None)


async def handle_inline_kugou_link(
    query_text: str,
    inline_query,
    context: ContextTypes.DEFAULT_TYPE,
) -> list:
    """处理 inline 中的酷狗音乐链接"""
    _cleanup_pending()
    cache_manager = context.bot_data.get("cache_manager")
    httpx_client = context.bot_data.get("httpx_client")

    resolved = await resolve_kugou_short_url(query_text, httpx_client)
    parsed = parse_kugou_hash(resolved)

    if not parsed:
        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="❌ 无法解析酷狗音乐链接",
                description="未能从链接中提取 hash",
                input_message_content=InputTextMessageContent(
                    message_text=f"❌ 无法解析酷狗链接: {query_text}"
                ),
            )
        ]

    hash_, aid = parsed
    return await _build_song_result(
        {"hash": hash_, "album_audio_id": aid, "name": "", "artists": "", "album": "", "duration": 0},
        cache_manager,
        context,
    )


async def handle_inline_kugou_search(
    keyword: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> list:
    """Inline 酷狗搜索"""
    _cleanup_pending()

    if not keyword.strip():
        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="🎵 请输入搜索关键词",
                description="例如: kugou 海阔天空$",
                input_message_content=InputTextMessageContent(
                    message_text="🎵 请输入搜索关键词"
                ),
            )
        ]

    from commands.kugou import _kugou_api
    if not _kugou_api:
        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="❌ 酷狗音乐服务未配置",
                description="请联系管理员",
                input_message_content=InputTextMessageContent(
                    message_text="❌ 酷狗音乐服务未配置"
                ),
            )
        ]

    songs = await _kugou_api.search_songs(keyword, limit=10)
    if not songs:
        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="❌ 未找到结果",
                description=f"关键词: {keyword}",
                input_message_content=InputTextMessageContent(
                    message_text=f"❌ 酷狗未找到与 \"{keyword}\" 相关的歌曲"
                ),
            )
        ]

    cache_manager = context.bot_data.get("cache_manager")
    results = []
    for s in songs:
        result = await _build_song_result(s, cache_manager, context)
        results.extend(result)

    return results


async def _build_song_result(
    meta: dict,
    cache_manager,
    context: ContextTypes.DEFAULT_TYPE,
) -> list:
    """构建单首歌的 inline 结果"""
    hash_ = meta["hash"]
    name = meta.get("name", "")
    artists = meta.get("artists", "")
    album = meta.get("album", "")
    duration = meta.get("duration", 0)

    # 缓存命中?
    cache_key = f"kugou:file:{hash_}"
    cached = await cache_manager.get(cache_key) if cache_manager else None

    if cached and cached.get("file_id"):
        cname = cached.get("name", "")
        cartists = cached.get("artists", "")
        caption = cached.get("caption", f"🎵 {cname} - {cartists}")

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                text=f"{cname} - {cartists}",
                url=f"https://www.kugou.com/song/#hash={hash_}",
            )],
            [InlineKeyboardButton(
                text="Send me to...",
                switch_inline_query=f"kugou {cname} {cartists}",
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
            logger.warning(f"构建酷狗缓存音频结果失败: {e}")

    # 无缓存 → 注册 pending + Article 占位
    display = f"{name} - {artists}" if name else hash_[:8]
    dur_str = f" [{duration // 60}:{duration % 60:02d}]" if duration else ""

    result_id = f"kgmusic_dl_{hash_[:12].lower()}_{int(time.time() * 1000000)}"
    _pending_downloads[result_id] = {
        "hash": hash_,
        "album_audio_id": meta.get("album_audio_id", 0),
        "name": name,
        "artists": artists,
        "album": album,
        "duration": duration,
        "image": meta.get("image", ""),
    }
    _pending_timestamps[result_id] = time.time()

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            text=f"🎵 {name or hash_[:8]}",
            url=f"https://www.kugou.com/song/#hash={hash_}",
        )],
    ])

    return [
        InlineQueryResultArticle(
            id=result_id,
            title=f"🎵 {name or hash_[:8]}",
            description=f"{artists} | {album}{dur_str}" if artists else "点击下载 (酷狗)",
            input_message_content=InputTextMessageContent(
                message_text=f"🎵 <b>{html_escape(display)}</b>\n⏳ 下载中... (酷狗)",
                parse_mode="HTML",
            ),
            reply_markup=keyboard,
        )
    ]


async def handle_inline_kugou_chosen(
    update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """用户选择 inline 酷狗结果后的回调"""
    chosen_result = update.chosen_inline_result
    result_id = chosen_result.result_id
    inline_message_id = chosen_result.inline_message_id

    if not result_id.startswith("kgmusic_dl_"):
        return

    pending = _pending_downloads.pop(result_id, None)
    _pending_timestamps.pop(result_id, None)

    if not pending:
        try:
            await context.bot.edit_message_text(
                inline_message_id=inline_message_id,
                text="❌ 下载请求已过期,请重新搜索",
            )
        except Exception:
            pass
        return

    hash_ = pending["hash"]
    name = pending.get("name", "")
    artists = pending.get("artists", "")
    album = pending.get("album", "")
    duration = pending.get("duration", 0)
    pic_url = pending.get("image", "")
    display = f"{name} - {artists}" if name else hash_[:8]

    from commands.kugou import _kugou_api, _pyrogram_helper
    from commands.music import _download_file, _embed_metadata
    from utils.config_manager import get_config

    if not _kugou_api:
        try:
            await context.bot.edit_message_text(
                inline_message_id=inline_message_id,
                text="❌ 酷狗音乐服务未配置",
            )
        except Exception:
            pass
        return

    config = get_config()
    quality = config.kugou_default_quality or "flac"

    try:
        song_url = await _kugou_api.get_song_url(hash_, pending.get("album_audio_id", 0), quality=quality)
        if (not song_url or not song_url.get("url")) and quality != "320":
            song_url = await _kugou_api.get_song_url(hash_, pending.get("album_audio_id", 0), quality="320")
        if (not song_url or not song_url.get("url")) and quality != "128":
            song_url = await _kugou_api.get_song_url(hash_, pending.get("album_audio_id", 0), quality="128")

        if not song_url or not song_url.get("url"):
            await context.bot.edit_message_text(
                inline_message_id=inline_message_id,
                text=f"🎵 <b>{html_escape(display)}</b>\n❌ 暂无可用音源",
                parse_mode="HTML",
            )
            return

        size_mb = song_url["size"] / (1024 * 1024)
        try:
            await context.bot.edit_message_text(
                inline_message_id=inline_message_id,
                text=f"🎵 <b>{html_escape(display)}</b>\n⬇️ 下载中... ({size_mb:.1f}MB,酷狗)",
                parse_mode="HTML",
            )
        except Exception:
            pass

        tmp_dir = Path(tempfile.mkdtemp(prefix="kugou_inline_"))
        audio_path = tmp_dir / f"{hash_[:8]}.{song_url['type']}"
        thumb_path = tmp_dir / f"{hash_[:8]}_cover.jpg"

        try:
            download_ok = await _download_file(
                song_url["url"], audio_path, None, config.music_download_timeout,
            )
            if not download_ok:
                await context.bot.edit_message_text(
                    inline_message_id=inline_message_id,
                    text=f"🎵 <b>{html_escape(display)}</b>\n❌ 下载失败",
                    parse_mode="HTML",
                )
                return

            cover_downloaded = False
            if pic_url:
                try:
                    cover_downloaded = await _download_file(pic_url, thumb_path, timeout=15)
                except Exception:
                    pass

            detail = {"name": name, "artists": artists, "album": album}
            await _embed_metadata(audio_path, detail, thumb_path if cover_downloaded else None)

            try:
                await context.bot.edit_message_text(
                    inline_message_id=inline_message_id,
                    text=f"🎵 <b>{html_escape(display)}</b>\n📤 上传中...",
                    parse_mode="HTML",
                )
            except Exception:
                pass

            if _pyrogram_helper and _pyrogram_helper.is_started and _pyrogram_helper.client:
                from pyrogram.types import InputMediaAudio as PyrogramInputMediaAudio
                from pyrogram.enums import ParseMode as PyrogramParseMode

                file_ext = song_url.get("type", "mp3").upper()
                bitrate_kbps = song_url.get("br", 0) / 1000
                quality_tag = "FLAC 无损" if file_ext == "FLAC" else f"MP3 {bitrate_kbps:.0f}kbps"
                cap_parts = [f"🎵 <b>{html_escape(name)}</b>", f"👤 {html_escape(artists)}"]
                if album:
                    cap_parts.append(f"💿 {html_escape(album)}")
                cap_parts.append(f"🎧 {quality_tag} | {size_mb:.1f}MB | 酷狗")
                caption = "\n".join(cap_parts)

                await _pyrogram_helper.client.edit_inline_media(
                    inline_message_id=inline_message_id,
                    media=PyrogramInputMediaAudio(
                        media=str(audio_path),
                        caption=caption,
                        parse_mode=PyrogramParseMode.HTML,
                        duration=duration or song_url.get("duration", 0),
                        performer=artists,
                        title=name,
                        thumb=str(thumb_path) if cover_downloaded else None,
                    ),
                )
                logger.info(f"[Inline Kugou] edit_inline_media 成功: {display}")
            else:
                await context.bot.edit_message_text(
                    inline_message_id=inline_message_id,
                    text=(
                        f"🎵 <b>{html_escape(display)}</b>\n"
                        f"❌ Inline 上传不可用\n"
                        f"💡 请在对话中发送 /kugou {name} 下载"
                    ),
                    parse_mode="HTML",
                )

        finally:
            import shutil
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass

    except Exception as e:
        logger.error(f"[Inline Kugou] 处理失败: {e}", exc_info=True)
        try:
            await context.bot.edit_message_text(
                inline_message_id=inline_message_id,
                text=f"🎵 <b>{html_escape(display)}</b>\n❌ 处理失败: {html_escape(str(e))}",
                parse_mode="HTML",
            )
        except Exception:
            pass
