#!/usr/bin/env python3
"""
YouTube Music 命令模块
功能：搜索歌曲、排行榜、下载上传音频、获取歌词
架构仿照 commands/music.py（网易云模块）
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
from utils.message_manager import (
    send_message_with_auto_delete,
    delete_user_command,
    _schedule_deletion,
    send_error,
)
from utils.ytmusic_api import (
    YTMusicAPI,
    YTMUSIC_CHARTS,
    parse_video_id,
    contains_ytmusic_link,
    get_thumbnail_url,
    download_audio,
)
from utils.permissions import Permission

logger = logging.getLogger(__name__)

# 全局依赖
_cache_manager = None
_httpx_client = None
_pyrogram_helper = None
_ytmusic_api: Optional[YTMusicAPI] = None

# 并发下载控制（与网易云模块保持一致）
_download_semaphore = asyncio.Semaphore(4)

# 缓存键前缀
CACHE_FILE_PREFIX = "ytmusic:file"
CACHE_SEARCH_PREFIX = "ytmusic:search"


def set_dependencies(cache_manager, httpx_client, pyrogram_helper=None):
    """注入依赖（在 main.py 中调用）"""
    global _cache_manager, _httpx_client, _pyrogram_helper, _ytmusic_api
    _cache_manager = cache_manager
    _httpx_client = httpx_client
    _pyrogram_helper = pyrogram_helper
    _ytmusic_api = YTMusicAPI()  # 自动读 YOUTUBE_OAUTH_TOKEN 环境变量


# ============================================================
# 核心功能：下载并发送音频
# ============================================================

async def _download_and_send(
    video_id: str,
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    reply_to_message_id: Optional[int] = None,
    status_message=None,
) -> bool:
    """
    下载 YouTube Music 歌曲并发送到 Telegram
    流程：Redis 缓存检查 → pytubefix 下载 → 嵌入封面 → Pyrogram/Bot API 上传 → 缓存 file_id
    """
    config = get_config()

    # 1. Redis 缓存检查
    cache_key = f"{CACHE_FILE_PREFIX}:{video_id}"
    cached = await _cache_manager.get(cache_key) if _cache_manager else None
    if cached:
        try:
            sent = await context.bot.send_audio(
                chat_id=chat_id,
                audio=cached["file_id"],
                caption=cached.get("caption", ""),
                parse_mode="HTML",
                reply_markup=_build_keyboard(video_id, cached.get("name", ""), cached.get("artists", "")),
                reply_to_message_id=reply_to_message_id,
            )
            if config.auto_delete_delay > 0:
                await _schedule_deletion(context, chat_id, sent.message_id, config.auto_delete_delay)
            if status_message:
                try:
                    await status_message.delete()
                except Exception:
                    pass
            return True
        except Exception as e:
            logger.warning(f"缓存发送失败，重新下载: {e}")

    # 2. 获取歌曲详情
    if status_message:
        try:
            await status_message.edit_text("🎵 获取歌曲信息中...")
        except Exception:
            pass

    if not _ytmusic_api:
        if status_message:
            try:
                await status_message.edit_text("❌ YouTube Music 服务未初始化")
            except Exception:
                pass
        return False

    detail = await _ytmusic_api.get_song_detail(video_id)
    if not detail:
        if status_message:
            try:
                await status_message.edit_text("❌ 未找到该歌曲")
                if config.auto_delete_delay > 0:
                    await _schedule_deletion(context, status_message.chat_id, status_message.message_id, min(config.auto_delete_delay, 30))
            except Exception:
                pass
        return False

    # 3. 下载音频
    if status_message:
        try:
            await status_message.edit_text(
                f"⬇️ 下载中...\n🎵 {detail['name']} - {detail['artists']}"
            )
        except Exception:
            pass

    async with _download_semaphore:
        tmp_dir = Path(tempfile.mkdtemp(prefix="ytmusic_"))
        try:
            result = await download_audio(video_id, tmp_dir)
            if not result:
                if status_message:
                    try:
                        await status_message.edit_text("❌ 下载失败，请稍后重试")
                        if config.auto_delete_delay > 0:
                            await _schedule_deletion(context, status_message.chat_id, status_message.message_id, min(config.auto_delete_delay, 30))
                    except Exception:
                        pass
                return False

            audio_path, dl_title, duration, author = result

            # 用 ytmusicapi 的详情覆盖（更准确的名字/艺人）
            name = detail["name"] or dl_title
            artists = detail["artists"] or author

            # 4. 下载封面图
            thumb_path = tmp_dir / f"{video_id}_cover.jpg"
            cover_downloaded = False
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
                except Exception as e:
                    logger.debug(f"封面下载失败: {e}")

            # 5. 上传到 Telegram
            if status_message:
                try:
                    await status_message.edit_text(
                        f"📤 上传中...\n🎵 {name} - {artists}"
                    )
                except Exception:
                    pass

            file_size_mb = audio_path.stat().st_size / (1024 * 1024)
            caption = (
                f"🎵 <b>{_esc(name)}</b>\n"
                f"👤 {_esc(artists)}\n"
                f"🎧 YouTube Music | {file_size_mb:.1f}MB"
            )
            keyboard = _build_keyboard(video_id, name, artists)

            sent_msg = None

            # 优先 Pyrogram（更稳定，支持大文件）
            if _pyrogram_helper and _pyrogram_helper.is_started:
                try:
                    logger.info(f"🚀 使用 Pyrogram 上传 {file_size_mb:.1f}MB 音频")
                    sent_msg = await _pyrogram_helper.send_large_audio(
                        chat_id=chat_id,
                        audio_path=str(audio_path),
                        caption=caption,
                        duration=duration or detail.get("duration", 0),
                        performer=artists,
                        title=name,
                        thumb=str(thumb_path) if cover_downloaded else None,
                        reply_markup=keyboard,
                        parse_mode="HTML",
                    )
                except Exception as e:
                    logger.warning(f"⚠️ Pyrogram 上传失败，降级: {e}")
                    sent_msg = None

            # Fallback: python-telegram-bot（≤50MB）
            if not sent_msg:
                if file_size_mb > 50:
                    logger.error(f"❌ 文件 {file_size_mb:.1f}MB 超过50MB 且 Pyrogram 不可用")
                    if status_message:
                        try:
                            await status_message.edit_text(f"❌ 文件过大 ({file_size_mb:.1f}MB)，上传失败")
                            if config.auto_delete_delay > 0:
                                await _schedule_deletion(context, status_message.chat_id, status_message.message_id, min(config.auto_delete_delay, 30))
                        except Exception:
                            pass
                    return False

                thumb_file = open(thumb_path, "rb") if cover_downloaded else None
                try:
                    with open(audio_path, "rb") as af:
                        sent_msg = await context.bot.send_audio(
                            chat_id=chat_id,
                            audio=af,
                            caption=caption,
                            parse_mode="HTML",
                            duration=duration or detail.get("duration", 0),
                            performer=artists,
                            title=name,
                            thumbnail=thumb_file,
                            reply_markup=keyboard,
                            reply_to_message_id=reply_to_message_id,
                        )
                finally:
                    if thumb_file:
                        thumb_file.close()

            # 6. 缓存 file_id
            if sent_msg and _cache_manager:
                file_id = None
                if hasattr(sent_msg, "audio") and sent_msg.audio:
                    file_id = sent_msg.audio.file_id
                elif hasattr(sent_msg, "document") and sent_msg.document:
                    file_id = sent_msg.document.file_id
                if file_id:
                    await _cache_manager.set(
                        cache_key,
                        {"file_id": file_id, "name": name, "artists": artists, "caption": caption},
                        ttl=config.music_cache_duration,
                    )

            # 7. 自动删除
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
            logger.error(f"处理 YouTube Music {video_id} 失败: {e}", exc_info=True)
            if status_message:
                try:
                    await status_message.edit_text(f"❌ 处理失败: {e}")
                    if config.auto_delete_delay > 0:
                        await _schedule_deletion(context, status_message.chat_id, status_message.message_id, min(config.auto_delete_delay, 30))
                except Exception:
                    pass
            return False
        finally:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)


# ============================================================
# 命令处理
# ============================================================

@with_error_handling
async def ytmusic_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /ytmusic <关键词|videoId|链接> — 搜索或下载 YouTube Music
    /ytmusic chart — 查看排行榜
    """
    if not update.message:
        return
    await delete_user_command(context, update.message.chat_id, update.message.message_id)

    args = (update.message.text or "").split(None, 1)
    if len(args) < 2:
        await send_message_with_auto_delete(
            context, update.message.chat_id,
            "🎵 <b>YouTube Music</b>\n\n"
            "用法：\n"
            "<code>/ytmusic 关键词</code> — 搜索歌曲\n"
            "<code>/ytmusic videoId或链接</code> — 直接下载\n"
            "<code>/ytmusic chart</code> — 查看排行榜",
            parse_mode="HTML",
        )
        return

    query = args[1].strip()

    # 榜单子命令
    if query.lower() in ("chart", "charts", "top", "榜单", "排行榜"):
        await _show_chart_menu(update.message.chat_id, context)
        return

    # 尝试解析 videoId（链接或纯 ID）
    video_id = parse_video_id(query)

    if video_id:
        status_msg = await context.bot.send_message(
            chat_id=update.message.chat_id, text="🎵 处理中..."
        )
        await _download_and_send(
            video_id, update.message.chat_id, context, status_message=status_msg
        )
        return

    # 关键词搜索
    status_msg = await context.bot.send_message(
        chat_id=update.message.chat_id, text="🔍 搜索中..."
    )

    if not _ytmusic_api:
        try:
            await status_msg.edit_text("❌ YouTube Music 服务未初始化")
        except Exception:
            pass
        return

    songs = await _ytmusic_api.search_songs(query, limit=10)
    if not songs:
        config = get_config()
        try:
            await status_msg.edit_text("❌ 未找到相关歌曲")
            if config.auto_delete_delay > 0:
                await _schedule_deletion(context, update.message.chat_id, status_msg.message_id, min(config.auto_delete_delay, 30))
        except Exception:
            pass
        return

    text_lines = ["🔍 <b>搜索结果</b>\n"]
    buttons = []
    for i, s in enumerate(songs):
        dur = s.get("duration_str") or _fmt_duration(s.get("duration", 0))
        text_lines.append(
            f"<b>{i + 1}.</b> {_esc(s['name'])} - {_esc(s['artists'])} [{dur}]"
        )
        buttons.append(InlineKeyboardButton(
            text=str(i + 1),
            callback_data=f"ytm_dl_{s['videoId']}",
        ))

    keyboard = InlineKeyboardMarkup([buttons[:5], buttons[5:]] if len(buttons) > 5 else [buttons])
    config = get_config()
    try:
        await status_msg.edit_text(
            "\n".join(text_lines), parse_mode="HTML", reply_markup=keyboard
        )
        if config.auto_delete_delay > 0:
            await _schedule_deletion(context, update.message.chat_id, status_msg.message_id, config.auto_delete_delay)
    except Exception as e:
        logger.error(f"更新搜索结果失败: {e}")


@with_error_handling
async def ytlyric_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/ytlyric <关键词|videoId> — 获取 YouTube Music 歌词"""
    if not update.message:
        return
    await delete_user_command(context, update.message.chat_id, update.message.message_id)

    args = (update.message.text or "").split(None, 1)
    if len(args) < 2:
        await send_message_with_auto_delete(
            context, update.message.chat_id,
            "📝 <b>获取歌词</b>\n\n用法: <code>/ytlyric 关键词或videoId</code>",
            parse_mode="HTML",
        )
        return

    query = args[1].strip()
    video_id = parse_video_id(query)

    if not video_id and _ytmusic_api:
        songs = await _ytmusic_api.search_songs(query, limit=1)
        if songs:
            video_id = songs[0]["videoId"]

    if not video_id:
        await send_error(context, update.message.chat_id, "未找到相关歌曲")
        return

    status_msg = await context.bot.send_message(
        chat_id=update.message.chat_id, text="📝 获取歌词中..."
    )

    if not _ytmusic_api:
        await send_error(context, update.message.chat_id, "YouTube Music 服务未初始化")
        return
    detail, lyrics = await asyncio.gather(
        _ytmusic_api.get_song_detail(video_id),
        _ytmusic_api.get_lyrics(video_id),
    )

    if not lyrics:
        config = get_config()
        try:
            await status_msg.edit_text("❌ 该歌曲暂无歌词")
            if config.auto_delete_delay > 0:
                await _schedule_deletion(context, update.message.chat_id, status_msg.message_id, min(config.auto_delete_delay, 30))
        except Exception:
            pass
        return

    name = detail["name"] if detail else video_id
    artists = detail.get("artists", "") if detail else ""
    filename = f"{name} - {artists}.txt" if artists else f"{name}.txt"
    filename = "".join(c for c in filename if c not in r'\/:*?"<>|')

    import tempfile
    tmp_path = Path(tempfile.mktemp(suffix=".txt", prefix="ytlyric_"))
    config = get_config()
    try:
        tmp_path.write_text(lyrics, encoding="utf-8")
        with open(tmp_path, "rb") as f:
            sent = await context.bot.send_document(
                chat_id=update.message.chat_id,
                document=InputFile(f, filename=filename),
                caption=f"📝 {_esc(name)} - {_esc(artists)}",
                parse_mode="HTML",
            )
        if config.auto_delete_delay > 0:
            await _schedule_deletion(context, update.message.chat_id, sent.message_id, config.auto_delete_delay)
        try:
            await status_msg.delete()
        except Exception:
            pass
    finally:
        tmp_path.unlink(missing_ok=True)


# ============================================================
# 排行榜
# ============================================================

async def _show_chart_menu(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """显示排行榜选择菜单"""
    buttons = []
    row = []
    for key, info in YTMUSIC_CHARTS.items():
        row.append(InlineKeyboardButton(
            text=f"{info['icon']} {info['name']}",
            callback_data=f"ytm_chart_{key}",
        ))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    keyboard = InlineKeyboardMarkup(buttons)
    config = get_config()
    msg = await context.bot.send_message(
        chat_id=chat_id,
        text="🏆 <b>YouTube Music 排行榜</b>\n\n选择一个榜单查看：",
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    if config.auto_delete_delay > 0:
        await _schedule_deletion(context, chat_id, msg.message_id, config.auto_delete_delay)


@with_error_handling
async def ytm_chart_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """排行榜按钮回调 — 显示榜单歌曲列表"""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    chart_key = (query.data or "").replace("ytm_chart_", "")
    chart_info = YTMUSIC_CHARTS.get(chart_key)
    if not chart_info or not _ytmusic_api:
        return

    try:
        await query.edit_message_text(
            f"{chart_info['icon']} 加载 <b>{chart_info['name']}</b> 中...",
            parse_mode="HTML",
        )
    except Exception:
        pass

    songs = await _ytmusic_api.get_charts(country=chart_info["country"])
    if not songs:
        try:
            await query.edit_message_text(f"❌ 获取 {chart_info['name']} 失败")
        except Exception:
            pass
        return

    # 趋势图标
    trend_icon = {"up": "📈", "down": "📉", "neutral": "➡️"}

    text_lines = [f"{chart_info['icon']} <b>{chart_info['name']}</b>\n"]
    buttons = []
    for i, s in enumerate(songs[:10]):
        rank = s.get("rank") or str(i + 1)
        trend = trend_icon.get(s.get("trend", ""), "")
        text_lines.append(
            f"<b>{rank}.</b>{trend} {_esc(s['name'])} - {_esc(s['artists'])}"
        )
        if s.get("videoId"):
            buttons.append(InlineKeyboardButton(
                text=str(rank),
                callback_data=f"ytm_dl_{s['videoId']}",
            ))

    keyboard_rows = [buttons[:5], buttons[5:]] if len(buttons) > 5 else [buttons]
    keyboard_rows.append([InlineKeyboardButton("🔙 返回榜单", callback_data="ytm_chart_menu")])
    keyboard = InlineKeyboardMarkup(keyboard_rows)

    try:
        await query.edit_message_text(
            "\n".join(text_lines), parse_mode="HTML", reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"更新榜单结果失败: {e}")


@with_error_handling
async def ytm_chart_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """返回榜单菜单"""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    buttons = []
    row = []
    for key, info in YTMUSIC_CHARTS.items():
        row.append(InlineKeyboardButton(
            text=f"{info['icon']} {info['name']}",
            callback_data=f"ytm_chart_{key}",
        ))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    try:
        await query.edit_message_text(
            "🏆 <b>YouTube Music 排行榜</b>\n\n选择一个榜单查看：",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
    except Exception:
        pass


@with_error_handling
async def ytm_download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """搜索结果/榜单下载按钮回调"""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    data = query.data or ""
    video_id = data.replace("ytm_dl_", "")
    if not video_id:
        return

    chat_id = query.message.chat_id
    status_msg = await context.bot.send_message(chat_id=chat_id, text="🎵 处理中...")
    await _download_and_send(video_id, chat_id, context, status_message=status_msg)


# ============================================================
# 辅助函数
# ============================================================

def _build_keyboard(video_id: str, name: str = "", artists: str = "") -> InlineKeyboardMarkup:
    """构建音乐消息按钮"""
    display = f"{name} - {artists}" if name else video_id
    if len(display) > 50:
        display = display[:47] + "..."
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            text=f"🎵 {display}",
            url=f"https://music.youtube.com/watch?v={video_id}",
        )],
        [InlineKeyboardButton(
            text="📝 歌词",
            callback_data=f"ytm_lyric_{video_id}",
        )],
    ])


@with_error_handling
async def ytm_lyric_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """歌词按钮回调"""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    video_id = (query.data or "").replace("ytm_lyric_", "")
    if not video_id or not _ytmusic_api:
        return

    detail, lyrics = await asyncio.gather(
        _ytmusic_api.get_song_detail(video_id),
        _ytmusic_api.get_lyrics(video_id),
    )

    if not lyrics:
        no_lyric = await context.bot.send_message(
            chat_id=query.message.chat_id, text="❌ 该歌曲暂无歌词"
        )
        config = get_config()
        if config.auto_delete_delay > 0:
            await _schedule_deletion(context, query.message.chat_id, no_lyric.message_id, min(config.auto_delete_delay, 30))
        return

    name = detail["name"] if detail else video_id
    artists = detail.get("artists", "") if detail else ""
    filename = f"{name} - {artists}.txt" if artists else f"{name}.txt"
    filename = "".join(c for c in filename if c not in r'\/:*?"<>|')

    import tempfile
    tmp_path = Path(tempfile.mktemp(suffix=".txt", prefix="ytlyric_"))
    config = get_config()
    try:
        tmp_path.write_text(lyrics, encoding="utf-8")
        with open(tmp_path, "rb") as f:
            sent = await context.bot.send_document(
                chat_id=query.message.chat_id,
                document=InputFile(f, filename=filename),
                caption=f"📝 {_esc(name)} - {_esc(artists)}",
                parse_mode="HTML",
            )
        if config.auto_delete_delay > 0:
            await _schedule_deletion(context, query.message.chat_id, sent.message_id, config.auto_delete_delay)
    finally:
        tmp_path.unlink(missing_ok=True)


def _esc(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fmt_duration(seconds: int) -> str:
    if not seconds:
        return "0:00"
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}"


# ============================================================
# 注册命令和回调
# ============================================================

command_factory.register_command(
    "ytmusic",
    ytmusic_command,
    permission=Permission.USER,
    description="搜索/下载 YouTube Music",
)

command_factory.register_command(
    "yt",
    ytmusic_command,
    permission=Permission.USER,
    description="搜索/下载 YouTube Music (别名)",
)

command_factory.register_command(
    "ytlyric",
    ytlyric_command,
    permission=Permission.USER,
    description="获取 YouTube Music 歌词",
)

command_factory.register_callback(
    r"^ytm_dl_[\w-]{11}$",
    ytm_download_callback,
    permission=Permission.NONE,
    description="YouTube Music 下载回调",
)

command_factory.register_callback(
    r"^ytm_lyric_[\w-]{11}$",
    ytm_lyric_callback,
    permission=Permission.NONE,
    description="YouTube Music 歌词回调",
)

command_factory.register_callback(
    r"^ytm_chart_menu$",
    ytm_chart_menu_callback,
    permission=Permission.NONE,
    description="返回榜单菜单回调",
)

command_factory.register_callback(
    r"^ytm_chart_(?!menu$)\w+$",
    ytm_chart_callback,
    permission=Permission.NONE,
    description="YouTube Music 榜单选择回调",
)

logger.info("🎵 YouTube Music 命令模块已加载")
