"""
YouTube Music API 封装模块
使用 ytmusicapi 调用 YouTube Music 接口（搜索、排行榜、歌词）
使用 pytubefix 下载音频（复用 parsehub_patch.py 的 OAuth/代理配置）
"""

import asyncio
import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# YouTube Music 链接正则
_REG_YTM_VIDEO_ID = re.compile(
    r"(?:youtube\.com/watch\?(?:.*&)?v=|youtu\.be/|music\.youtube\.com/watch\?(?:.*&)?v=)([\w-]{11})"
)
_REG_YTM_DOMAIN = re.compile(r"music\.youtube\.com|youtu\.be|youtube\.com")

# 各国/全球榜单配置
YTMUSIC_CHARTS = {
    "global": {"country": "ZZ", "name": "全球榜", "icon": "🌍"},
    "us":     {"country": "US", "name": "美国榜", "icon": "🇺🇸"},
    "jp":     {"country": "JP", "name": "日本榜", "icon": "🇯🇵"},
    "kr":     {"country": "KR", "name": "韩国榜", "icon": "🇰🇷"},
    "gb":     {"country": "GB", "name": "英国榜", "icon": "🇬🇧"},
    "hk":     {"country": "HK", "name": "香港榜", "icon": "🇭🇰"},
    "tw":     {"country": "TW", "name": "台湾榜", "icon": "🇹🇼"},
}


class YTMusicAPI:
    """YouTube Music API 客户端"""

    def __init__(self, oauth_token_path: Optional[str] = None):
        """
        初始化客户端

        Args:
            oauth_token_path: OAuth token 文件路径，不传则读环境变量 YOUTUBE_OAUTH_TOKEN，
                              再不行则匿名模式（搜索/榜单不需要登录）
        """
        self._token_path = oauth_token_path or os.getenv("YOUTUBE_OAUTH_TOKEN")
        self._ytmusic = None
        self._init_client()

    def _init_client(self):
        try:
            from ytmusicapi import YTMusic
            if self._token_path and os.path.exists(self._token_path):
                self._ytmusic = YTMusic(self._token_path)
                logger.info(f"✅ YTMusic 已使用 OAuth token 初始化: {self._token_path}")
            else:
                self._ytmusic = YTMusic()
                logger.info("✅ YTMusic 已使用匿名模式初始化（搜索/榜单可用）")
        except Exception as e:
            logger.error(f"YTMusic 初始化失败: {e}")
            self._ytmusic = None

    async def search_songs(self, keyword: str, limit: int = 10) -> list[dict]:
        """
        搜索歌曲

        Returns:
            [{videoId, name, artists, album, duration, duration_str, thumbnails}, ...]
        """
        if not self._ytmusic:
            return []
        try:
            results = await asyncio.to_thread(
                self._ytmusic.search, keyword, filter="songs", limit=limit
            )
            songs = []
            for r in results[:limit]:
                artists = ", ".join(a["name"] for a in r.get("artists") or [])
                album = r.get("album") or {}
                album_name = album.get("name", "") if isinstance(album, dict) else ""
                duration_str = r.get("duration") or ""
                duration_sec = r.get("duration_seconds") or _parse_duration(duration_str)
                songs.append({
                    "videoId": r.get("videoId", ""),
                    "name": r.get("title", ""),
                    "artists": artists,
                    "album": album_name,
                    "duration": duration_sec,
                    "duration_str": duration_str,
                    "thumbnails": r.get("thumbnails") or [],
                })
            return songs
        except Exception as e:
            logger.error(f"YTMusic 搜索失败: {e}")
            return []

    async def get_song_detail(self, video_id: str) -> Optional[dict]:
        """
        获取歌曲详情

        Returns:
            {videoId, name, artists, duration, thumbnails}
        """
        if not self._ytmusic:
            return None
        try:
            r = await asyncio.to_thread(self._ytmusic.get_song, video_id)
            details = r.get("videoDetails", {})
            thumbnails = details.get("thumbnail", {}).get("thumbnails", [])
            return {
                "videoId": video_id,
                "name": details.get("title", ""),
                "artists": details.get("author", ""),
                "album": "",
                "duration": int(details.get("lengthSeconds", 0)),
                "thumbnails": thumbnails,
            }
        except Exception as e:
            logger.error(f"YTMusic 获取歌曲详情失败 {video_id}: {e}")
            return None

    async def get_charts(self, country: str = "ZZ") -> list[dict]:
        """
        获取排行榜歌曲

        Args:
            country: 国家代码，"ZZ" 为全球榜

        Returns:
            [{rank, trend, videoId, playlistId, name, artists, album, thumbnails}, ...]
        """
        if not self._ytmusic:
            return []
        try:
            data = await asyncio.to_thread(self._ytmusic.get_charts, country=country)
            songs = []
            # get_charts 返回 data["songs"]["items"]
            items = []
            if "songs" in data and "items" in data.get("songs", {}):
                items = data["songs"]["items"]
            elif "videos" in data and "items" in data.get("videos", {}):
                items = data["videos"]["items"]

            for item in items:
                artists = ", ".join(a["name"] for a in item.get("artists") or [])
                album = item.get("album") or {}
                songs.append({
                    "rank": item.get("rank"),
                    "trend": item.get("trend"),  # "up" / "down" / "neutral"
                    "videoId": item.get("videoId", ""),
                    "playlistId": item.get("playlistId", ""),
                    "name": item.get("title", ""),
                    "artists": artists,
                    "album": album.get("name", "") if isinstance(album, dict) else "",
                    "thumbnails": item.get("thumbnails") or [],
                })
            return songs
        except Exception as e:
            logger.error(f"YTMusic 获取排行榜失败 ({country}): {e}")
            return []

    async def get_lyrics(self, video_id: str) -> Optional[str]:
        """获取歌词"""
        if not self._ytmusic:
            return None
        try:
            watch = await asyncio.to_thread(
                self._ytmusic.get_watch_playlist, videoId=video_id
            )
            lyrics_id = watch.get("lyrics")
            if not lyrics_id:
                return None
            lyrics_data = await asyncio.to_thread(self._ytmusic.get_lyrics, lyrics_id)
            return lyrics_data.get("lyrics")
        except Exception as e:
            logger.debug(f"YTMusic 获取歌词失败 {video_id}: {e}")
            return None


# ============================================================
# 下载工具函数
# ============================================================

async def download_audio(video_id: str, output_dir: Path) -> Optional[tuple[Path, str, int, str]]:
    """
    使用 pytubefix 下载 YouTube 音频

    复用 parsehub_patch.py 的配置：
      - YOUTUBE_PROXY 环境变量 → 代理
      - YOUTUBE_OAUTH_TOKEN 环境变量 → OAuth token 文件路径

    Args:
        video_id: YouTube video ID
        output_dir: 输出目录

    Returns:
        (file_path, title, duration_seconds, author) 或 None
    """
    video_url = f"https://www.youtube.com/watch?v={video_id}"

    def _download_sync():
        from pytubefix import YouTube

        # 代理配置（与 parsehub_patch.py 保持一致）
        youtube_proxy = os.getenv("YOUTUBE_PROXY")
        proxies = None
        if youtube_proxy:
            proxies = {"http": youtube_proxy, "https": youtube_proxy}
            logger.info(f"🌐 [YTMusic] 使用代理: {youtube_proxy[:30]}...")

        # OAuth token 配置（与 parsehub_patch.py 保持一致）
        token_path = os.getenv("YOUTUBE_OAUTH_TOKEN")
        use_oauth = bool(token_path and os.path.exists(token_path))
        if use_oauth:
            logger.info(f"🔐 [YTMusic] 使用 OAuth token: {token_path}")

        yt = YouTube(
            video_url,
            client="WEB",
            proxies=proxies,
            use_oauth=use_oauth,
            allow_oauth_cache=True,
            token_file=token_path if (use_oauth and token_path) else None,
        )

        # 优先 m4a（aac），更兼容 Telegram 音频播放
        stream = yt.streams.get_audio_only(subtype="mp4")
        if not stream:
            # fallback: 任意最高码率音频流
            stream = (
                yt.streams.filter(only_audio=True)
                .order_by("abr")
                .desc()
                .first()
            )
        if not stream:
            raise RuntimeError("找不到可用的音频流")

        filename = f"ytm_{video_id}_{time.time_ns()}.m4a"
        logger.info(f"🎵 [YTMusic] 开始下载: {yt.title} | {stream.abr}")
        out_path = stream.download(output_path=str(output_dir), filename=filename)

        return Path(out_path), yt.title or "", int(yt.length or 0), yt.author or ""

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        return await asyncio.to_thread(_download_sync)
    except Exception as e:
        logger.error(f"[YTMusic] 下载失败 {video_id}: {e}")
        return None


# ============================================================
# 工具函数
# ============================================================

def parse_video_id(text: str) -> Optional[str]:
    """从文本中提取 YouTube videoId（11位）"""
    match = _REG_YTM_VIDEO_ID.search(text)
    if match:
        return match.group(1)
    clean = text.strip()
    if re.match(r"^[\w-]{11}$", clean):
        return clean
    return None


def contains_ytmusic_link(text: str) -> bool:
    """检测文本是否包含 YouTube / YouTube Music 链接"""
    return bool(_REG_YTM_DOMAIN.search(text))


def get_thumbnail_url(thumbnails: list) -> Optional[str]:
    """从 thumbnails 列表取最大分辨率图片"""
    if not thumbnails:
        return None
    return max(thumbnails, key=lambda t: t.get("width", 0) * t.get("height", 0)).get("url")


def _parse_duration(duration_str: str) -> int:
    """'3:45' -> 225 秒"""
    if not duration_str:
        return 0
    parts = duration_str.strip().split(":")
    try:
        return sum(int(p) * m for p, m in zip(reversed(parts), [1, 60, 3600]))
    except ValueError:
        return 0
