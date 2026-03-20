#!/usr/bin/env python3
"""
网易云音乐命令模块
参考 Music163bot-Go-2 实现：搜索、下载、歌词、链接识别
"""

import asyncio
import hashlib
import logging
import os
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
from utils.netease_api import (
    NeteaseAPI,
    parse_music_id,
    parse_program_id,
    contains_music_link,
    resolve_short_url,
)
from utils.permissions import Permission

logger = logging.getLogger(__name__)

# 全局依赖
_cache_manager = None
_httpx_client = None
_pyrogram_helper = None
_netease_api: Optional[NeteaseAPI] = None

# 并发控制（参考 Go 源码的 musicLimiter = make(chan bool, 4)）
_download_semaphore = asyncio.Semaphore(4)

# 缓存键前缀
CACHE_PREFIX = "music"
CACHE_FILE_PREFIX = "music:file"
CACHE_SEARCH_PREFIX = "music:search"


def set_dependencies(cache_manager, httpx_client, pyrogram_helper=None):
    """注入依赖"""
    global _cache_manager, _httpx_client, _pyrogram_helper, _netease_api
    _cache_manager = cache_manager
    _httpx_client = httpx_client
    _pyrogram_helper = pyrogram_helper
    config = get_config()
    _netease_api = NeteaseAPI(
        music_u=config.music_u_cookie,
        httpx_client=httpx_client,
    )


# ============================================================
# 核心功能：下载并发送音乐
# ============================================================

async def _download_and_send_music(
    song_id: int,
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    reply_to_message_id: Optional[int] = None,
    status_message=None,
) -> bool:
    """
    下载歌曲并发送到 Telegram（参考 processMusic.go 完整流程）
    返回是否成功
    """
    if not _netease_api:
        return False

    config = get_config()

    # 1. 检查 Redis 缓存（参考 Go 源码的 DB 查询）
    cache_key = f"{CACHE_FILE_PREFIX}:{song_id}"
    cached = await _cache_manager.get(cache_key) if _cache_manager else None
    if cached:
        try:
            file_id = cached["file_id"]
            caption = cached.get("caption", "")
            keyboard = _build_music_keyboard(song_id, cached.get("name", ""), cached.get("artists", ""))

            sent_cached = await context.bot.send_audio(
                chat_id=chat_id,
                audio=file_id,
                caption=caption,
                parse_mode="HTML",
                reply_markup=keyboard,
                reply_to_message_id=reply_to_message_id,
            )
            # 自动删除缓存命中的音频消息
            if config.auto_delete_delay > 0:
                await _schedule_deletion(context, chat_id, sent_cached.message_id, config.auto_delete_delay)
            if status_message:
                try:
                    await status_message.delete()
                except Exception:
                    pass
            return True
        except Exception as e:
            logger.warning(f"缓存发送失败，重新下载: {e}")

    # 2. 获取歌曲详情和下载链接（参考 Go 源码的 batch request）
    if status_message:
        try:
            await status_message.edit_text("🎵 获取歌曲信息中...")
        except Exception:
            pass

    detail, song_url = await asyncio.gather(
        _netease_api.get_song_detail(song_id),
        _netease_api.get_song_url(song_id),
    )

    if not detail:
        if status_message:
            try:
                await status_message.edit_text("❌ 未找到该歌曲")
                if config.auto_delete_delay > 0:
                    await _schedule_deletion(context, status_message.chat_id, status_message.message_id, min(config.auto_delete_delay, 30))
            except Exception:
                pass
        return False

    if not song_url or not song_url.get("url"):
        if status_message:
            try:
                await status_message.edit_text("❌ 该歌曲暂无可用音源（可能需要 VIP 或版权限制）")
                if config.auto_delete_delay > 0:
                    await _schedule_deletion(context, status_message.chat_id, status_message.message_id, min(config.auto_delete_delay, 30))
            except Exception:
                pass
        return False

    # 3. 下载音频文件
    if status_message:
        size_mb = song_url["size"] / (1024 * 1024)
        try:
            await status_message.edit_text(
                f"⬇️ 下载中... ({size_mb:.1f}MB)\n"
                f"🎵 {detail['name']} - {detail['artists']}"
            )
        except Exception:
            pass

    async with _download_semaphore:
        tmp_dir = Path(tempfile.mkdtemp(prefix="music_"))
        audio_path = tmp_dir / f"{song_id}.{song_url['type']}"
        thumb_path = tmp_dir / f"{song_id}_cover.jpg"

        try:
            # 下载音频
            download_ok = await _download_file(
                song_url["url"], audio_path, song_url.get("md5"), config.music_download_timeout
            )
            if not download_ok:
                if status_message:
                    try:
                        await status_message.edit_text("❌ 下载失败，请稍后重试")
                        if config.auto_delete_delay > 0:
                            await _schedule_deletion(context, status_message.chat_id, status_message.message_id, min(config.auto_delete_delay, 30))
                    except Exception:
                        pass
                return False

            # 下载封面图
            cover_downloaded = False
            if detail.get("pic_url"):
                try:
                    cover_downloaded = await _download_file(
                        detail["pic_url"], thumb_path, timeout=15
                    )
                except Exception:
                    pass

            # 4. 嵌入 ID3 元数据（参考 Go 的 163KeyMarker）
            await _embed_metadata(
                audio_path, detail, thumb_path if cover_downloaded else None
            )

            # 5. 发送音频到 Telegram
            if status_message:
                try:
                    await status_message.edit_text(
                        f"📤 上传中...\n🎵 {detail['name']} - {detail['artists']}"
                    )
                except Exception:
                    pass

            file_ext = song_url.get("type", "mp3").upper()
            bitrate_kbps = song_url.get("br", 0) / 1000
            size_mb = song_url.get("size", 0) / (1024 * 1024)
            quality_tag = "FLAC 无损" if file_ext == "FLAC" else f"MP3 {bitrate_kbps:.0f}kbps"
            caption = (
                f"🎵 <b>{_escape_html(detail['name'])}</b>\n"
                f"👤 {_escape_html(detail['artists'])}\n"
                f"💿 {_escape_html(detail['album'])}\n"
                f"🎧 {quality_tag} | {size_mb:.1f}MB"
            )
            keyboard = _build_music_keyboard(song_id, detail["name"], detail["artists"])

            file_size_mb = audio_path.stat().st_size / (1024 * 1024)

            sent_msg = None
            # 优先使用 Pyrogram 上传（更稳定，支持大文件）
            # 参考 social_parser 的瀑布流：Pyrogram → python-telegram-bot fallback
            if _pyrogram_helper and _pyrogram_helper.is_started:
                try:
                    logger.info(f"🚀 使用 Pyrogram 上传 {file_size_mb:.1f}MB 音频")
                    sent_msg = await _pyrogram_helper.send_large_audio(
                        chat_id=chat_id,
                        audio_path=str(audio_path),
                        caption=caption,
                        duration=detail.get("duration", 0),
                        performer=detail.get("artists", ""),
                        title=detail.get("name", ""),
                        thumb=str(thumb_path) if cover_downloaded else None,
                        reply_markup=keyboard,
                        parse_mode="HTML",
                    )
                except Exception as e:
                    logger.warning(f"⚠️ Pyrogram 上传失败，降级到 python-telegram-bot: {e}")
                    sent_msg = None

            # Fallback: python-telegram-bot（仅 <= 50MB）
            if not sent_msg:
                if file_size_mb > 50:
                    logger.error(f"❌ 文件 {file_size_mb:.1f}MB 超过50MB且Pyrogram不可用")
                    if status_message:
                        try:
                            await status_message.edit_text(f"❌ 文件过大 ({file_size_mb:.1f}MB)，上传失败")
                            if config.auto_delete_delay > 0:
                                await _schedule_deletion(context, status_message.chat_id, status_message.message_id, min(config.auto_delete_delay, 30))
                        except Exception:
                            pass
                    return False
                with open(audio_path, "rb") as audio_file:
                    thumb_file = open(thumb_path, "rb") if cover_downloaded else None
                    try:
                        sent_msg = await context.bot.send_audio(
                            chat_id=chat_id,
                            audio=audio_file,
                            caption=caption,
                            parse_mode="HTML",
                            duration=detail.get("duration", 0),
                            performer=detail.get("artists", ""),
                            title=detail.get("name", ""),
                            thumbnail=thumb_file,
                            reply_markup=keyboard,
                            reply_to_message_id=reply_to_message_id,
                        )
                    finally:
                        if thumb_file:
                            thumb_file.close()

            # 6. 缓存 file_id 到 Redis
            if sent_msg and _cache_manager:
                file_id = None
                if hasattr(sent_msg, "audio") and sent_msg.audio:
                    file_id = sent_msg.audio.file_id
                elif hasattr(sent_msg, "document") and sent_msg.document:
                    file_id = sent_msg.document.file_id

                if file_id:
                    cache_data = {
                        "file_id": file_id,
                        "name": detail["name"],
                        "artists": detail["artists"],
                        "album": detail["album"],
                        "duration": detail.get("duration", 0),
                        "caption": caption,
                    }
                    await _cache_manager.set(
                        cache_key, cache_data, ttl=config.music_cache_duration
                    )

            # 7. 自动删除 bot 发送的音频消息
            # 兼容 python-telegram-bot (.chat_id/.message_id) 和 Pyrogram (.chat.id/.id)
            if sent_msg and config.auto_delete_delay > 0:
                msg_chat_id = getattr(sent_msg, 'chat_id', None) or getattr(sent_msg.chat, 'id', None)
                msg_id = getattr(sent_msg, 'message_id', None) or getattr(sent_msg, 'id', None)
                if msg_chat_id and msg_id:
                    await _schedule_deletion(context, msg_chat_id, msg_id, config.auto_delete_delay)

            if status_message:
                try:
                    await status_message.delete()
                except Exception:
                    pass
            return True

        except Exception as e:
            logger.error(f"处理音乐 {song_id} 失败: {e}", exc_info=True)
            if status_message:
                try:
                    await status_message.edit_text(f"❌ 处理失败: {e}")
                    if config.auto_delete_delay > 0:
                        await _schedule_deletion(context, status_message.chat_id, status_message.message_id, min(config.auto_delete_delay, 30))
                except Exception:
                    pass
            return False
        finally:
            # 清理临时文件
            import shutil
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass


async def _download_file(
    url: str, path: Path, expected_md5: Optional[str] = None, timeout: int = 60
) -> bool:
    """下载文件，支持 MD5 校验（参考 processMusic.go 的下载+校验流程）"""
    client = _httpx_client or httpx.AsyncClient(timeout=timeout)
    try:
        # CDN 主机替换（参考 Go 源码的 hostReplacer）
        download_url = url.replace("m8.", "m7.").replace("m801.", "m701.").replace("m804.", "m701.")
        # 强制 HTTPS
        if download_url.startswith("http://"):
            download_url = "https://" + download_url[7:]

        async with client.stream("GET", download_url) as resp:
            resp.raise_for_status()
            with open(path, "wb") as f:
                async for chunk in resp.aiter_bytes(8192):
                    f.write(chunk)

        # MD5 校验
        if expected_md5:
            md5 = hashlib.md5()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    md5.update(chunk)
            if md5.hexdigest().lower() != expected_md5.lower():
                logger.warning(f"MD5 校验失败: 期望 {expected_md5}, 实际 {md5.hexdigest()}")
                # 不删除文件，仍然尝试发送（参考 Go 源码行为）

        return True
    except Exception as e:
        logger.error(f"下载失败 {url}: {e}")
        return False
    finally:
        if not _httpx_client:
            await client.aclose()


async def _embed_metadata(audio_path: Path, detail: dict, cover_path: Optional[Path] = None):
    """嵌入 ID3/FLAC 元数据（使用 mutagen-rs，参考 Go 的 163KeyMarker）"""
    try:
        import mutagen_rs
        from mutagen_rs.id3 import APIC
        from mutagen_rs.flac import Picture
    except ImportError:
        logger.warning("mutagen-rs 未安装，跳过元数据嵌入")
        return

    ext = audio_path.suffix.lower()
    try:
        if ext == ".mp3":
            audio = mutagen_rs.MP3(str(audio_path))
            audio['TIT2'] = [detail.get("name", "")]
            audio['TPE1'] = [detail.get("artists", "")]
            audio['TALB'] = [detail.get("album", "")]

            if cover_path and cover_path.exists():
                with open(cover_path, "rb") as f:
                    audio.add(APIC(
                        encoding=3, mime="image/jpeg", type=3,
                        desc="Cover", data=f.read()
                    ))
            audio.save()

        elif ext == ".flac":
            audio = mutagen_rs.FLAC(str(audio_path))
            audio["title"] = detail.get("name", "")
            audio["artist"] = detail.get("artists", "")
            audio["album"] = detail.get("album", "")

            if cover_path and cover_path.exists():
                pic = Picture()
                pic.type = 3
                pic.mime = "image/jpeg"
                pic.desc = "Cover"
                with open(cover_path, "rb") as f:
                    pic.data = f.read()
                audio.add_picture(pic)
            audio.save()

    except Exception as e:
        logger.warning(f"嵌入元数据失败: {e}")


def _build_music_keyboard(song_id: int, name: str = "", artists: str = "") -> InlineKeyboardMarkup:
    """构建音乐消息的 InlineKeyboard（参考 processMusic.go 的 numericKeyboard）"""
    display = f"{name} - {artists}" if name else str(song_id)
    if len(display) > 50:
        display = display[:47] + "..."
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            text=f"🎵 {display}",
            url=f"https://music.163.com/song?id={song_id}",
        )],
        [InlineKeyboardButton(
            text="📝 歌词",
            callback_data=f"music_lyric_{song_id}",
        )],
    ])


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ============================================================
# 命令处理函数
# ============================================================

@with_error_handling
async def music_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /music <关键词|ID|链接> — 搜索或下载网易云音乐
    参考 Go 源码的 processAnyMusic + processSearch
    """
    if not update.message:
        return
    await delete_user_command(context, update.message.chat_id, update.message.message_id)

    if not _netease_api:
        await send_error(context, update.message.chat_id, "音乐服务未初始化")
        return

    args = (update.message.text or "").split(None, 1)
    if len(args) < 2:
        await send_message_with_auto_delete(
            context, update.message.chat_id,
            "🎵 <b>网易云音乐</b>\n\n"
            "用法:\n"
            "<code>/music 关键词</code> — 搜索歌曲\n"
            "<code>/music 歌曲ID</code> — 直接获取\n"
            "<code>/music 网易云链接</code> — 解析链接",
            parse_mode="HTML",
        )
        return

    query = args[1].strip()

    # 尝试解析为歌曲 ID（数字或链接）
    song_id = parse_music_id(query)

    # 检查是否为短链接
    if not song_id and contains_music_link(query):
        resolved = await resolve_short_url(query, _httpx_client)
        song_id = parse_music_id(resolved)

    # 检查是否为电台节目链接
    if not song_id:
        program_id = parse_program_id(query)
        if program_id:
            song_id = await _netease_api.get_program_song_id(program_id)

    if song_id:
        # 直接下载
        status_msg = await context.bot.send_message(
            chat_id=update.message.chat_id, text="🎵 处理中..."
        )
        await _download_and_send_music(
            song_id, update.message.chat_id, context,
            status_message=status_msg,
        )
        return

    # 关键词搜索（参考 processSearch.go）
    status_msg = await context.bot.send_message(
        chat_id=update.message.chat_id, text="🔍 搜索中..."
    )

    songs = await _netease_api.search_songs(query, limit=8)
    if not songs:
        try:
            await status_msg.edit_text("❌ 未找到相关歌曲")
            # 自动删除错误消息
            config = get_config()
            if config.auto_delete_delay > 0:
                await _schedule_deletion(context, update.message.chat_id, status_msg.message_id, min(config.auto_delete_delay, 30))
        except Exception:
            pass
        return

    # 构建搜索结果（参考 processSearch.go 的 InlineKeyboard）
    text_lines = ["🔍 <b>搜索结果</b>\n"]
    buttons = []
    for i, s in enumerate(songs):
        dur_min = s["duration"] // 60
        dur_sec = s["duration"] % 60
        text_lines.append(
            f"<b>{i + 1}.</b> {_escape_html(s['name'])} - {_escape_html(s['artists'])} "
            f"[{dur_min}:{dur_sec:02d}]"
        )
        buttons.append(
            InlineKeyboardButton(
                text=str(i + 1),
                callback_data=f"music_dl_{s['id']}",
            )
        )

    keyboard = InlineKeyboardMarkup([buttons])

    try:
        await status_msg.edit_text(
            "\n".join(text_lines),
            parse_mode="HTML",
            reply_markup=keyboard,
        )
        # 自动删除搜索结果
        config = get_config()
        if config.auto_delete_delay > 0:
            await _schedule_deletion(context, update.message.chat_id, status_msg.message_id, config.auto_delete_delay)
    except Exception as e:
        logger.error(f"更新搜索结果失败: {e}")


@with_error_handling
async def lyric_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /lyric <关键词|ID> — 获取歌词
    参考 processLyric.go
    """
    if not update.message:
        return
    await delete_user_command(context, update.message.chat_id, update.message.message_id)

    if not _netease_api:
        await send_error(context, update.message.chat_id, "音乐服务未初始化")
        return

    args = (update.message.text or "").split(None, 1)
    if len(args) < 2:
        await send_message_with_auto_delete(
            context, update.message.chat_id,
            "📝 <b>获取歌词</b>\n\n用法: <code>/lyric 关键词或ID</code>",
            parse_mode="HTML",
        )
        return

    query = args[1].strip()
    song_id = parse_music_id(query)

    # 如果不是 ID，先搜索
    if not song_id:
        songs = await _netease_api.search_songs(query, limit=1)
        if songs:
            song_id = songs[0]["id"]
        else:
            await send_error(context, update.message.chat_id, "未找到相关歌曲")
            return

    status_msg = await context.bot.send_message(
        chat_id=update.message.chat_id, text="📝 获取歌词中..."
    )

    detail, lyric = await asyncio.gather(
        _netease_api.get_song_detail(song_id),
        _netease_api.get_song_lyric(song_id),
    )

    if not lyric:
        try:
            await status_msg.edit_text("❌ 该歌曲暂无歌词")
            config = get_config()
            if config.auto_delete_delay > 0:
                await _schedule_deletion(context, update.message.chat_id, status_msg.message_id, min(config.auto_delete_delay, 30))
        except Exception:
            pass
        return

    # 保存为 .lrc 文件并发送（参考 processLyric.go）
    name = detail["name"] if detail else str(song_id)
    artists = detail.get("artists", "") if detail else ""
    filename = f"{name} - {artists}.lrc" if artists else f"{name}.lrc"
    # 清理文件名中的特殊字符
    filename = "".join(c for c in filename if c not in r'\/:*?"<>|')

    config = get_config()
    tmp_path = Path(tempfile.mktemp(suffix=".lrc", prefix="lyric_"))
    try:
        tmp_path.write_text(lyric, encoding="utf-8")
        with open(tmp_path, "rb") as f:
            sent_lyric = await context.bot.send_document(
                chat_id=update.message.chat_id,
                document=InputFile(f, filename=filename),
                caption=f"📝 {_escape_html(name)} - {_escape_html(artists)}",
                parse_mode="HTML",
            )
        # 自动删除歌词文件消息
        if config.auto_delete_delay > 0:
            await _schedule_deletion(context, update.message.chat_id, sent_lyric.message_id, config.auto_delete_delay)
        try:
            await status_msg.delete()
        except Exception:
            pass
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


# ============================================================
# 回调处理
# ============================================================

@with_error_handling
async def music_download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """搜索结果按钮回调 — 下载选中的歌曲（参考 Go 的 processCallbackMusic）"""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    data = query.data or ""
    # 格式: music_dl_{song_id}
    try:
        song_id = int(data.split("_")[-1])
    except (ValueError, IndexError):
        return

    chat_id = query.message.chat_id

    status_msg = await context.bot.send_message(chat_id=chat_id, text="🎵 处理中...")

    await _download_and_send_music(
        song_id, chat_id, context,
        status_message=status_msg,
    )


@with_error_handling
async def music_lyric_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """歌词按钮回调"""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    data = query.data or ""
    try:
        song_id = int(data.split("_")[-1])
    except (ValueError, IndexError):
        return

    if not _netease_api:
        return

    detail, lyric = await asyncio.gather(
        _netease_api.get_song_detail(song_id),
        _netease_api.get_song_lyric(song_id),
    )

    if not lyric:
        no_lyric_msg = await context.bot.send_message(
            chat_id=query.message.chat_id, text="❌ 该歌曲暂无歌词"
        )
        config = get_config()
        if config.auto_delete_delay > 0:
            await _schedule_deletion(context, query.message.chat_id, no_lyric_msg.message_id, min(config.auto_delete_delay, 30))
        return

    name = detail["name"] if detail else str(song_id)
    artists = detail.get("artists", "") if detail else ""
    filename = f"{name} - {artists}.lrc" if artists else f"{name}.lrc"
    filename = "".join(c for c in filename if c not in r'\/:*?"<>|')

    tmp_path = Path(tempfile.mktemp(suffix=".lrc", prefix="lyric_"))
    try:
        tmp_path.write_text(lyric, encoding="utf-8")
        with open(tmp_path, "rb") as f:
            sent_cb_lyric = await context.bot.send_document(
                chat_id=query.message.chat_id,
                document=InputFile(f, filename=filename),
                caption=f"📝 {_escape_html(name)} - {_escape_html(artists)}",
                parse_mode="HTML",
            )
        config = get_config()
        if config.auto_delete_delay > 0:
            await _schedule_deletion(context, query.message.chat_id, sent_cb_lyric.message_id, config.auto_delete_delay)
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


# ============================================================
# 注册命令和回调
# ============================================================

command_factory.register_command(
    "music",
    music_command,
    permission=Permission.USER,
    description="搜索/下载网易云音乐",
)

command_factory.register_command(
    "netease",
    music_command,
    permission=Permission.USER,
    description="搜索/下载网易云音乐 (别名)",
)

command_factory.register_command(
    "lyric",
    lyric_command,
    permission=Permission.USER,
    description="获取网易云歌词",
)

command_factory.register_callback(
    r"^music_dl_\d+$",
    music_download_callback,
    permission=Permission.NONE,
    description="音乐下载回调",
)

command_factory.register_callback(
    r"^music_lyric_\d+$",
    music_lyric_callback,
    permission=Permission.NONE,
    description="歌词获取回调",
)

logger.info("🎵 网易云音乐命令模块已加载")
