"""
file_id 缓存：同一 URL 解析过的媒体复用 Telegram file_id，避免重复上传触发 FloodWait。

参考 parse_hub_bot 的实现思路：
- 缓存 key = URL 的 MD5 hash
- 缓存 value = 媒体类型 + file_id 列表（支持多媒体）
- 命中后直接用 file_id 字符串调 send_video/send_photo/...，TG 后端复用文件，零上传
"""
import hashlib
import logging

logger = logging.getLogger(__name__)

CACHE_SUBDIR = "file_id"
DEFAULT_TTL = 7 * 24 * 3600  # 7 天


def _url_hash(url: str) -> str:
    return hashlib.md5(url.encode("utf-8")).hexdigest()


def _extract_from_message(msg) -> dict | None:
    """从 telegram.Message 提取媒体类型与 file_id。返回 None 表示无可缓存媒体。"""
    if getattr(msg, "video", None):
        v = msg.video
        return {"type": "video", "file_id": v.file_id,
                "width": getattr(v, "width", 0),
                "height": getattr(v, "height", 0),
                "duration": getattr(v, "duration", 0)}
    if getattr(msg, "animation", None):
        return {"type": "animation", "file_id": msg.animation.file_id}
    if getattr(msg, "audio", None):
        return {"type": "audio", "file_id": msg.audio.file_id}
    if getattr(msg, "photo", None) and msg.photo:
        # photo 是 PhotoSize 数组，取最大的
        return {"type": "photo", "file_id": msg.photo[-1].file_id}
    if getattr(msg, "document", None):
        return {"type": "document", "file_id": msg.document.file_id}
    return None


async def get_cached_media(cache_manager, url: str) -> dict | None:
    """
    查询 URL 对应的 file_id 缓存。
    返回 {"media": [{"type":..., "file_id":...}, ...]} 或 None。
    """
    if not cache_manager or not url:
        return None
    try:
        key = _url_hash(url)
        data = await cache_manager.get(key, subdirectory=CACHE_SUBDIR)
        if data and data.get("media"):
            logger.info(f"📦 file_id 缓存命中: {url[:60]}...")
            return data
        return None
    except Exception as e:
        logger.warning(f"file_id 缓存查询失败: {e}")
        return None


async def save_cached_media(cache_manager, url: str, sent_messages, ttl: int = DEFAULT_TTL) -> None:
    """
    从已发送的消息提取 file_id 并存入缓存。
    sent_messages: list[telegram.Message]
    """
    if not cache_manager or not url or not sent_messages:
        return
    try:
        media_list = []
        for m in sent_messages:
            info = _extract_from_message(m)
            if info:
                media_list.append(info)
        if not media_list:
            return
        key = _url_hash(url)
        await cache_manager.set(
            key,
            {"url": url, "media": media_list},
            ttl=ttl,
            subdirectory=CACHE_SUBDIR,
        )
        logger.info(f"💾 file_id 缓存写入: {url[:60]}... ({len(media_list)} 个媒体)")
    except Exception as e:
        logger.warning(f"file_id 缓存写入失败: {e}")


async def send_from_cache(context, chat_id: int, cached: dict, caption: str,
                          reply_parameters=None, reply_markup=None, parse_mode: str = "MarkdownV2") -> list:
    """
    根据缓存内容直接用 file_id 发送，完全跳过下载/上传。
    返回发送的 Message 列表。
    """
    sent = []
    media_list = cached.get("media", [])
    for i, m in enumerate(media_list):
        # 只在第一条消息附带 caption / reply_markup / reply
        cap = caption if i == 0 else None
        rp = reply_parameters if i == 0 else None
        rm = reply_markup if i == 0 else None
        pm = parse_mode if i == 0 else None

        t = m["type"]
        fid = m["file_id"]
        if t == "video":
            msg = await context.bot.send_video(
                chat_id=chat_id, video=fid, caption=cap, parse_mode=pm,
                reply_parameters=rp, reply_markup=rm, supports_streaming=True,
            )
        elif t == "photo":
            msg = await context.bot.send_photo(
                chat_id=chat_id, photo=fid, caption=cap, parse_mode=pm,
                reply_parameters=rp, reply_markup=rm,
            )
        elif t == "animation":
            msg = await context.bot.send_animation(
                chat_id=chat_id, animation=fid, caption=cap, parse_mode=pm,
                reply_parameters=rp, reply_markup=rm,
            )
        elif t == "audio":
            msg = await context.bot.send_audio(
                chat_id=chat_id, audio=fid, caption=cap, parse_mode=pm,
                reply_parameters=rp, reply_markup=rm,
            )
        elif t == "document":
            msg = await context.bot.send_document(
                chat_id=chat_id, document=fid, caption=cap, parse_mode=pm,
                reply_parameters=rp, reply_markup=rm,
            )
        else:
            continue
        sent.append(msg)
    return sent
