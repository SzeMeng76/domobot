#!/usr/bin/env python3
"""
酷狗音乐命令模块
依赖自部署的 KuGouMusicApi (https://github.com/MakcRe/KuGouMusicApi)
通过 HTTP 接口调用,Python 这边只负责拼请求和处理 Telegram 上传/缓存
"""

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Optional

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, InputFile
from telegram.ext import ContextTypes

from utils.command_factory import command_factory
from utils.config_manager import get_config
from utils.error_handling import with_error_handling
from utils.kugou_api import (
    KUGOU_RANKS,
    KugouAPI,
    contains_kugou_link,
    parse_kugou_hash,
    resolve_kugou_short_url,
)
from utils.message_manager import (
    _schedule_deletion,
    delete_user_command,
    send_error,
    send_message_with_auto_delete,
)
from utils.permissions import Permission

logger = logging.getLogger(__name__)

# 全局依赖
_cache_manager = None
_httpx_client = None
_pyrogram_helper = None
_kugou_api: Optional[KugouAPI] = None

# 并发控制
_download_semaphore = asyncio.Semaphore(4)

# 缓存键前缀
CACHE_FILE_PREFIX = "kugou:file"
CACHE_SEARCH_PREFIX = "kugou:search"
CACHE_RANK_PREFIX = "kugou:rank"
CACHE_LYRIC_PREFIX = "kugou:lyric"

# Pending 缓存(存搜索时拿到的元数据,callback 来下载时复用)
# key: short_id, value: {"hash", "album_audio_id", "name", "artists", "album", "duration"}
_song_meta_cache: dict[str, dict] = {}


def set_dependencies(cache_manager, httpx_client, pyrogram_helper=None):
    """注入依赖"""
    global _cache_manager, _httpx_client, _pyrogram_helper, _kugou_api
    _cache_manager = cache_manager
    _httpx_client = httpx_client
    _pyrogram_helper = pyrogram_helper

    config = get_config()
    if not config.kugou_api_url:
        logger.warning("KUGOU_API_URL 未配置,酷狗音乐功能不可用")
        _kugou_api = None
        return

    _kugou_api = KugouAPI(
        base_url=config.kugou_api_url,
        token=config.kugou_token,
        userid=config.kugou_userid,
        dfid=config.kugou_dfid,
        mid=config.kugou_mid,
        httpx_client=httpx_client,
    )
    logger.info(f"🎵 酷狗音乐 API 已初始化: {config.kugou_api_url}")


def is_enabled() -> bool:
    return _kugou_api is not None


# ============================================================
# 工具函数
# ============================================================

def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _short_meta_id(hash_: str) -> str:
    """从 hash 截前 12 位作为 callback_data 用的短 ID(callback_data 上限 64 字节)"""
    return hash_[:12].lower()


def _stash_meta(meta: dict) -> str:
    """把搜索元数据塞进内存缓存,返回 short_id"""
    sid = _short_meta_id(meta["hash"])
    _song_meta_cache[sid] = meta
    return sid


def _build_kugou_keyboard(hash_: str, name: str = "", artists: str = "") -> InlineKeyboardMarkup:
    """酷狗歌曲消息的 InlineKeyboard"""
    display = f"{name} - {artists}" if name else hash_[:8]
    if len(display) > 50:
        display = display[:47] + "..."
    sid = _short_meta_id(hash_)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            text=f"🎵 {display}",
            url=f"https://www.kugou.com/song/#hash={hash_}",
        )],
        [InlineKeyboardButton(
            text="📝 歌词",
            callback_data=f"kugou_lyric_{sid}",
        )],
    ])


async def _download_kugou_file(url: str, path: Path, timeout: int = 60) -> bool:
    """
    酷狗 CDN 文件下载 — 不强制 HTTPS(酷狗 CDN 不支持 HTTPS),
    可选走 KUGOU_DOWNLOAD_PROXY 代理(海外服务器必填)
    """
    config = get_config()
    proxy = (config.kugou_download_proxy or "").strip() or None

    # 构造 client(代理参数无法用全局 _httpx_client,所以单独建)
    if proxy:
        client = httpx.AsyncClient(timeout=timeout, proxy=proxy)
    else:
        client = _httpx_client or httpx.AsyncClient(timeout=timeout)

    try:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            with open(path, "wb") as f:
                async for chunk in resp.aiter_bytes(8192):
                    f.write(chunk)
        return True
    except Exception as e:
        logger.error(f"酷狗下载失败 {url}: {e}")
        return False
    finally:
        # 自建的(走代理或无全局)需要关闭
        if proxy or not _httpx_client:
            try:
                await client.aclose()
            except Exception:
                pass


# ============================================================
# 核心:下载并发送
# ============================================================

async def _download_and_send_kugou(
    meta: dict,
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    reply_to_message_id: Optional[int] = None,
    status_message=None,
) -> bool:
    """下载酷狗音乐并发送到 Telegram"""
    if not _kugou_api:
        return False

    config = get_config()
    hash_ = meta["hash"]
    album_audio_id = meta.get("album_audio_id", 0)

    # 1. 缓存命中?
    cache_key = f"{CACHE_FILE_PREFIX}:{hash_}"
    cached = await _cache_manager.get(cache_key) if _cache_manager else None
    if cached:
        try:
            file_id = cached["file_id"]
            caption = cached.get("caption", "")
            keyboard = _build_kugou_keyboard(hash_, cached.get("name", ""), cached.get("artists", ""))
            sent_cached = await context.bot.send_audio(
                chat_id=chat_id, audio=file_id, caption=caption, parse_mode="HTML",
                reply_markup=keyboard, reply_to_message_id=reply_to_message_id,
            )
            if config.auto_delete_delay > 0:
                await _schedule_deletion(context, chat_id, sent_cached.message_id, config.auto_delete_delay)
            if status_message:
                try:
                    await status_message.delete()
                except Exception:
                    pass
            return True
        except Exception as e:
            logger.warning(f"酷狗缓存发送失败,重新下载: {e}")

    # 2. 获取下载链接
    if status_message:
        try:
            await status_message.edit_text("🎵 获取酷狗歌曲信息...")
        except Exception:
            pass

    quality = config.kugou_default_quality or "flac"
    song_url = await _kugou_api.get_song_url(hash_, album_audio_id, quality=quality)
    # FLAC 拿不到就降级到 320,再不行 128
    if (not song_url or not song_url.get("url")) and quality != "320":
        song_url = await _kugou_api.get_song_url(hash_, album_audio_id, quality="320")
    if (not song_url or not song_url.get("url")) and quality != "128":
        song_url = await _kugou_api.get_song_url(hash_, album_audio_id, quality="128")

    if not song_url or not song_url.get("url"):
        if status_message:
            try:
                await status_message.edit_text("❌ 酷狗暂无可用音源(可能需要 VIP 或版权限制)")
                if config.auto_delete_delay > 0:
                    await _schedule_deletion(
                        context, status_message.chat_id, status_message.message_id,
                        min(config.auto_delete_delay, 30),
                    )
            except Exception:
                pass
        return False

    # 拼歌曲详情(从 meta 拿,不再调 /audio)
    name = meta.get("name") or song_url.get("name") or hash_[:8]
    artists = meta.get("artists", "")
    album = meta.get("album", "")
    duration = meta.get("duration") or song_url.get("duration", 0)
    pic_url = meta.get("image", "")  # 搜索结果里有 Image

    # 3. 下载
    if status_message:
        size_mb = song_url["size"] / (1024 * 1024)
        try:
            await status_message.edit_text(
                f"⬇️ 下载中... ({size_mb:.1f}MB)\n🎵 {name} - {artists}"
            )
        except Exception:
            pass

    async with _download_semaphore:
        tmp_dir = Path(tempfile.mkdtemp(prefix="kugou_"))
        audio_path = tmp_dir / f"{hash_[:8]}.{song_url['type']}"
        thumb_path = tmp_dir / f"{hash_[:8]}_cover.jpg"

        try:
            # 酷狗 CDN 不支持 HTTPS,且海外服务器可能需要代理,用专用下载函数
            from commands.music import _embed_metadata

            download_ok = await _download_kugou_file(
                song_url["url"], audio_path, config.music_download_timeout,
            )
            if not download_ok:
                if status_message:
                    try:
                        await status_message.edit_text("❌ 酷狗下载失败")
                        if config.auto_delete_delay > 0:
                            await _schedule_deletion(
                                context, status_message.chat_id, status_message.message_id,
                                min(config.auto_delete_delay, 30),
                            )
                    except Exception:
                        pass
                return False

            # 封面
            cover_downloaded = False
            if pic_url:
                try:
                    # 封面图通常是 HTTPS,走通用下载即可(不需要酷狗代理)
                    from commands.music import _download_file
                    cover_downloaded = await _download_file(pic_url, thumb_path, timeout=15)
                except Exception:
                    pass

            # 嵌入元数据
            detail = {"name": name, "artists": artists, "album": album}
            await _embed_metadata(audio_path, detail, thumb_path if cover_downloaded else None)

            # 4. 上传
            if status_message:
                try:
                    await status_message.edit_text(f"📤 上传中...\n🎵 {name} - {artists}")
                except Exception:
                    pass

            file_ext = song_url.get("type", "mp3").upper()
            bitrate_kbps = song_url.get("br", 0) / 1000
            size_mb = song_url.get("size", 0) / (1024 * 1024)
            quality_tag = "FLAC 无损" if file_ext == "FLAC" else f"MP3 {bitrate_kbps:.0f}kbps"
            caption_parts = [
                f"🎵 <b>{_escape_html(name)}</b>",
                f"👤 {_escape_html(artists)}",
            ]
            if album:
                caption_parts.append(f"💿 {_escape_html(album)}")
            caption_parts.append(f"🎧 {quality_tag} | {size_mb:.1f}MB | 酷狗")
            caption = "\n".join(caption_parts)

            keyboard = _build_kugou_keyboard(hash_, name, artists)
            file_size_mb = audio_path.stat().st_size / (1024 * 1024)
            sent_msg = None

            # Pyrogram 优先
            if _pyrogram_helper and _pyrogram_helper.is_started:
                try:
                    logger.info(f"🚀 Pyrogram 上传酷狗音频 {file_size_mb:.1f}MB")
                    sent_msg = await _pyrogram_helper.send_large_audio(
                        chat_id=chat_id, audio_path=str(audio_path), caption=caption,
                        duration=duration, performer=artists, title=name,
                        thumb=str(thumb_path) if cover_downloaded else None,
                        reply_markup=keyboard, parse_mode="HTML",
                    )
                except Exception as e:
                    logger.warning(f"⚠️ Pyrogram 上传酷狗失败,降级到 PTB: {e}")
                    sent_msg = None

            if not sent_msg:
                if file_size_mb > 50:
                    if status_message:
                        try:
                            await status_message.edit_text(f"❌ 文件过大 ({file_size_mb:.1f}MB)")
                        except Exception:
                            pass
                    return False
                with open(audio_path, "rb") as audio_file:
                    thumb_file = open(thumb_path, "rb") if cover_downloaded else None
                    try:
                        sent_msg = await context.bot.send_audio(
                            chat_id=chat_id, audio=audio_file, caption=caption,
                            parse_mode="HTML", duration=duration, performer=artists,
                            title=name, thumbnail=thumb_file, reply_markup=keyboard,
                            reply_to_message_id=reply_to_message_id,
                        )
                    finally:
                        if thumb_file:
                            thumb_file.close()

            # 5. 缓存 file_id
            if sent_msg and _cache_manager:
                file_id = None
                if hasattr(sent_msg, "audio") and sent_msg.audio:
                    file_id = sent_msg.audio.file_id
                elif hasattr(sent_msg, "document") and sent_msg.document:
                    file_id = sent_msg.document.file_id
                if file_id:
                    await _cache_manager.set(
                        cache_key,
                        {
                            "file_id": file_id, "name": name, "artists": artists,
                            "album": album, "duration": duration, "caption": caption,
                        },
                        ttl=config.music_cache_duration,
                    )

            # 6. 自动删除
            if sent_msg and config.auto_delete_delay > 0:
                msg_chat_id = getattr(sent_msg, "chat_id", None) or getattr(sent_msg.chat, "id", None)
                msg_id = getattr(sent_msg, "message_id", None) or getattr(sent_msg, "id", None)
                if msg_chat_id and msg_id:
                    await _schedule_deletion(context, msg_chat_id, msg_id, config.auto_delete_delay)

            if status_message:
                try:
                    await status_message.delete()
                except Exception:
                    pass
            return True

        except Exception as e:
            logger.error(f"酷狗处理 {hash_} 失败: {e}", exc_info=True)
            if status_message:
                try:
                    await status_message.edit_text(f"❌ 处理失败: {e}")
                except Exception:
                    pass
            return False
        finally:
            import shutil
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass


# ============================================================
# 命令: /kugou
# ============================================================

@with_error_handling
async def kugou_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/kugou <关键词|链接> — 搜索/下载酷狗音乐"""
    if not update.message:
        return
    await delete_user_command(context, update.message.chat_id, update.message.message_id)

    if not _kugou_api:
        await send_error(context, update.message.chat_id, "酷狗音乐服务未配置,请联系管理员")
        return

    args = (update.message.text or "").split(None, 1)
    if len(args) < 2:
        await send_message_with_auto_delete(
            context, update.message.chat_id,
            "🎵 <b>酷狗音乐</b>\n\n"
            "用法:\n"
            "<code>/kugou 关键词</code> — 搜索歌曲\n"
            "<code>/kugou 酷狗链接</code> — 解析链接\n"
            "<code>/kugou chart</code> — 查看榜单",
            parse_mode="HTML",
        )
        return

    query = args[1].strip()

    # 榜单
    if query.lower() in ("chart", "charts", "top", "榜单", "排行榜"):
        await _show_chart_menu(update.message.chat_id, context)
        return

    # 链接识别
    if contains_kugou_link(query):
        resolved = await resolve_kugou_short_url(query, _httpx_client)
        parsed = parse_kugou_hash(resolved)
        if parsed:
            hash_, aid = parsed
            status_msg = await context.bot.send_message(chat_id=update.message.chat_id, text="🎵 处理中...")
            meta = {"hash": hash_, "album_audio_id": aid, "name": "", "artists": "", "album": "", "duration": 0}
            _stash_meta(meta)
            await _download_and_send_kugou(meta, update.message.chat_id, context, status_message=status_msg)
            return

    # 关键词搜索
    status_msg = await context.bot.send_message(chat_id=update.message.chat_id, text="🔍 搜索酷狗...")

    cache_key_search = f"{CACHE_SEARCH_PREFIX}:{query}"
    songs = await _cache_manager.get(cache_key_search) if _cache_manager else None
    if not songs:
        songs = await _kugou_api.search_songs(query, limit=10)
        if songs and _cache_manager:
            config_s = get_config()
            await _cache_manager.set(cache_key_search, songs, ttl=config_s.kugou_search_cache_duration)

    if not songs:
        try:
            await status_msg.edit_text("❌ 酷狗未找到相关歌曲")
            cfg = get_config()
            if cfg.auto_delete_delay > 0:
                await _schedule_deletion(
                    context, update.message.chat_id, status_msg.message_id,
                    min(cfg.auto_delete_delay, 30),
                )
        except Exception:
            pass
        return

    # 渲染列表
    text_lines = ["🔍 <b>酷狗搜索结果</b>\n"]
    buttons = []
    for i, s in enumerate(songs):
        dur_min = s["duration"] // 60
        dur_sec = s["duration"] % 60
        text_lines.append(
            f"<b>{i + 1}.</b> {_escape_html(s['name'])} - {_escape_html(s['artists'])} "
            f"[{dur_min}:{dur_sec:02d}]"
        )
        sid = _stash_meta(s)
        buttons.append(InlineKeyboardButton(text=str(i + 1), callback_data=f"kugou_dl_{sid}"))

    keyboard = InlineKeyboardMarkup([buttons[:5], buttons[5:]] if len(buttons) > 5 else [buttons])

    try:
        await status_msg.edit_text("\n".join(text_lines), parse_mode="HTML", reply_markup=keyboard)
        cfg = get_config()
        if cfg.auto_delete_delay > 0:
            await _schedule_deletion(context, update.message.chat_id, status_msg.message_id, cfg.auto_delete_delay)
    except Exception as e:
        logger.error(f"更新酷狗搜索结果失败: {e}")


# ============================================================
# 回调
# ============================================================

@with_error_handling
async def kugou_download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """搜索结果按钮 -> 下载"""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    sid = (query.data or "").replace("kugou_dl_", "")
    meta = _song_meta_cache.get(sid)
    if not meta:
        try:
            await query.answer("⚠️ 搜索结果已过期,请重新搜索", show_alert=True)
        except Exception:
            pass
        return

    chat_id = (query.message.chat_id if query.message else None)
    status_msg = await context.bot.send_message(chat_id=chat_id, text="🎵 处理中...")
    await _download_and_send_kugou(meta, chat_id, context, status_message=status_msg)


@with_error_handling
async def kugou_lyric_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """歌词按钮"""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    sid = (query.data or "").replace("kugou_lyric_", "")
    meta = _song_meta_cache.get(sid)
    if not meta or not _kugou_api:
        try:
            await query.answer("⚠️ 信息已过期", show_alert=True)
        except Exception:
            pass
        return

    hash_ = meta["hash"]
    name = meta.get("name") or hash_[:8]
    artists = meta.get("artists", "")

    lyric_key = f"{CACHE_LYRIC_PREFIX}:{hash_}"
    lyric = await _cache_manager.get(lyric_key) if _cache_manager else None
    if not lyric:
        lyric = await _kugou_api.get_song_lyric(hash_)
        if lyric and _cache_manager:
            cfg = get_config()
            await _cache_manager.set(lyric_key, lyric, ttl=cfg.kugou_lyric_cache_duration)

    if not lyric:
        no_lyric = await context.bot.send_message(chat_id=(query.message.chat_id if query.message else None), text="❌ 酷狗暂无歌词")
        cfg = get_config()
        if cfg.auto_delete_delay > 0:
            await _schedule_deletion(
                context, (query.message.chat_id if query.message else None), no_lyric.message_id,
                min(cfg.auto_delete_delay, 30),
            )
        return

    filename = f"{name} - {artists}.lrc" if artists else f"{name}.lrc"
    filename = "".join(c for c in filename if c not in r'\/:*?"<>|')

    tmp_path = Path(tempfile.mktemp(suffix=".lrc", prefix="kugou_lyric_"))
    try:
        tmp_path.write_text(lyric, encoding="utf-8")
        with open(tmp_path, "rb") as f:
            sent = await context.bot.send_document(
                chat_id=(query.message.chat_id if query.message else None),
                document=InputFile(f, filename=filename),
                caption=f"📝 {_escape_html(name)} - {_escape_html(artists)} (酷狗)",
                parse_mode="HTML",
            )
        cfg = get_config()
        if cfg.auto_delete_delay > 0:
            await _schedule_deletion(context, (query.message.chat_id if query.message else None), sent.message_id, cfg.auto_delete_delay)
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


# ============================================================
# 榜单
# ============================================================

async def _show_chart_menu(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    buttons = []
    row = []
    for key, info in KUGOU_RANKS.items():
        row.append(InlineKeyboardButton(
            text=f"{info['icon']} {info['name']}",
            callback_data=f"kugou_chart_{key}",
        ))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    keyboard = InlineKeyboardMarkup(buttons)
    msg = await context.bot.send_message(
        chat_id=chat_id,
        text="🏆 <b>酷狗音乐榜单</b>\n\n选择一个榜单查看：",
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    cfg = get_config()
    if cfg.auto_delete_delay > 0:
        await _schedule_deletion(context, chat_id, msg.message_id, cfg.auto_delete_delay)


@with_error_handling
async def kugou_chart_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()

    chart_key = (query.data or "").replace("kugou_chart_", "")
    info = KUGOU_RANKS.get(chart_key)
    if not info or not _kugou_api:
        return

    try:
        await query.edit_message_text(
            f"{info['icon']} 加载 <b>{info['name']}</b> 中...",
            parse_mode="HTML",
        )
    except Exception:
        pass

    cache_key = f"{CACHE_RANK_PREFIX}:{chart_key}"
    playlist = await _cache_manager.get(cache_key) if _cache_manager else None
    if not playlist:
        playlist = await _kugou_api.get_rank_songs(info["id"], limit=10)
        if playlist and playlist["songs"] and _cache_manager:
            cfg = get_config()
            await _cache_manager.set(cache_key, playlist, ttl=cfg.kugou_rank_cache_duration)

    if not playlist or not playlist["songs"]:
        try:
            await query.edit_message_text(f"❌ 获取 {info['name']} 失败")
        except Exception:
            pass
        return

    text_lines = [f"{info['icon']} <b>酷狗 - {_escape_html(info['name'])}</b>\n"]
    buttons = []
    for i, s in enumerate(playlist["songs"]):
        dur_min = s["duration"] // 60
        dur_sec = s["duration"] % 60
        text_lines.append(
            f"<b>{i + 1}.</b> {_escape_html(s['name'])} - {_escape_html(s['artists'])} "
            f"[{dur_min}:{dur_sec:02d}]"
        )
        sid = _stash_meta(s)
        buttons.append(InlineKeyboardButton(text=str(i + 1), callback_data=f"kugou_dl_{sid}"))

    keyboard_rows = [buttons[:5], buttons[5:]]
    keyboard_rows.append([InlineKeyboardButton("🔙 返回榜单", callback_data="kugou_chart_menu")])
    keyboard = InlineKeyboardMarkup(keyboard_rows)

    try:
        await query.edit_message_text("\n".join(text_lines), parse_mode="HTML", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"更新酷狗榜单失败: {e}")


@with_error_handling
async def kugou_chart_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()

    buttons = []
    row = []
    for key, info in KUGOU_RANKS.items():
        row.append(InlineKeyboardButton(
            text=f"{info['icon']} {info['name']}",
            callback_data=f"kugou_chart_{key}",
        ))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    keyboard = InlineKeyboardMarkup(buttons)
    try:
        await query.edit_message_text(
            "🏆 <b>酷狗音乐榜单</b>\n\n选择一个榜单查看：",
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    except Exception:
        pass


# ============================================================
# 注册
# ============================================================

command_factory.register_command(
    "kugou",
    kugou_command,
    permission=Permission.USER,
    description="搜索/下载酷狗音乐",
)

command_factory.register_callback(
    r"^kugou_dl_[a-z0-9]+$",
    kugou_download_callback,
    permission=Permission.NONE,
    description="酷狗音乐下载回调",
)

command_factory.register_callback(
    r"^kugou_lyric_[a-z0-9]+$",
    kugou_lyric_callback,
    permission=Permission.NONE,
    description="酷狗歌词回调",
)

command_factory.register_callback(
    r"^kugou_chart_menu$",
    kugou_chart_menu_callback,
    permission=Permission.NONE,
    description="酷狗榜单菜单",
)

command_factory.register_callback(
    r"^kugou_chart_(?!menu$)[a-z0-9]+$",
    kugou_chart_callback,
    permission=Permission.NONE,
    description="酷狗榜单选择",
)

logger.info("🎵 酷狗音乐命令模块已加载")
