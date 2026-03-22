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
            # 只有包含 ytmusicapi OAuth 字段的 JSON 才传给 YTMusic()
            # pytubefix 的 token 文件格式不兼容，传进去会报错
            token_valid = False
            if self._token_path and os.path.exists(self._token_path):
                try:
                    import json
                    with open(self._token_path) as f:
                        token_data = json.load(f)
                    # ytmusicapi OAuth JSON 必须有 access_token + oauth_credentials
                    if "access_token" in token_data and "oauth_credentials" in token_data:
                        token_valid = True
                except Exception:
                    pass

            if token_valid:
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
        获取排行榜

        get_charts() 实际返回结构：
          - "videos"  → 播放列表条目（Top Music Videos playlist）
          - "artists" → 艺人排行
          - "daily"/"weekly" → Premium 账号才有

        这里取 "videos" 播放列表的第一个，再用 get_playlist 拿实际歌曲列表。

        Returns:
            [{rank, trend, videoId, playlistId, name, artists, album, thumbnails}, ...]
        """
        if not self._ytmusic:
            return []
        try:
            data = await asyncio.to_thread(self._ytmusic.get_charts, country=country)

            # 取第一个 PL 开头的 Top Music Videos 播放列表（跳过 OLAK 专辑列表）
            videos_list = data.get("videos") or data.get("daily") or data.get("weekly") or []
            playlist_id = next(
                (v.get("playlistId") for v in videos_list if (v.get("playlistId") or "").startswith("PL")),
                None,
            )
            if not playlist_id:
                return []

            # 用 playlist 拿实际歌曲列表（limit 20）
            playlist = await asyncio.to_thread(
                self._ytmusic.get_playlist, playlist_id, limit=20
            )
            tracks = playlist.get("tracks") or []
            songs = []
            for i, track in enumerate(tracks):
                artists = ", ".join(a["name"] for a in track.get("artists") or [])
                album = track.get("album") or {}
                songs.append({
                    "rank": str(i + 1),
                    "trend": None,
                    "videoId": track.get("videoId", ""),
                    "playlistId": playlist_id,
                    "name": track.get("title", ""),
                    "artists": artists,
                    "album": album.get("name", "") if isinstance(album, dict) else "",
                    "thumbnails": track.get("thumbnails") or [],
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
    下载 YouTube 音频：yt-dlp 优先，失败自动 fallback 到 pytubefix

    环境变量（与 parsehub_patch.py 保持一致）：
      YOUTUBE_PROXY       → 代理地址
      YOUTUBE_COOKIE      → yt-dlp cookie 文件路径（Netscape 格式）
      YOUTUBE_OAUTH_TOKEN → pytubefix OAuth token 文件路径（fallback 用）

    Returns:
        (file_path, title, duration_seconds, author) 或 None
    """
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- yt-dlp (主) ---
    def _ytdlp_download():
        from yt_dlp import YoutubeDL

        youtube_proxy = os.getenv("YOUTUBE_PROXY")
        cookie_file = os.getenv("YOUTUBE_COOKIE")
        output_template = str(output_dir / f"ytm_{video_id}_{time.time_ns()}.%(ext)s")

        ydl_params = {
            "format": "bestaudio[ext=m4a]/bestaudio/best",
            "outtmpl": {"default": output_template},
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "http_headers": {
                "Referer": "https://www.youtube.com/",
                "Origin": "https://www.youtube.com",
            },
        }
        if youtube_proxy:
            ydl_params["proxy"] = youtube_proxy
            logger.info(f"🌐 [YTMusic/yt-dlp] 代理: {youtube_proxy[:30]}...")
        if cookie_file and os.path.exists(cookie_file):
            ydl_params["cookiefile"] = cookie_file
            logger.info(f"🍪 [YTMusic/yt-dlp] cookie: {cookie_file}")

        with YoutubeDL(ydl_params) as ydl:  # type: ignore[arg-type]
            info = ydl.extract_info(video_url, download=True)

        downloads = (info or {}).get("requested_downloads") or []
        if downloads:
            out_path = Path(downloads[0]["filepath"])
        else:
            matches = list(output_dir.glob(f"ytm_{video_id}_*"))
            if not matches:
                raise RuntimeError("yt-dlp 下载后找不到输出文件")
            out_path = matches[0]

        title = (info or {}).get("title") or ""
        duration = int((info or {}).get("duration") or 0)
        author = (info or {}).get("uploader") or (info or {}).get("channel") or ""
        logger.info(f"✅ [YTMusic/yt-dlp] 下载完成: {title}")
        return out_path, title, duration, author

    try:
        return await asyncio.to_thread(_ytdlp_download)
    except Exception as e:
        logger.warning(f"[YTMusic] yt-dlp 失败，切换到 pytubefix: {e}")

    # --- pytubefix (fallback) ---
    def _pytubefix_download():
        from pytubefix import YouTube

        youtube_proxy = os.getenv("YOUTUBE_PROXY")
        proxies: Optional[dict] = (
            {"http": youtube_proxy, "https": youtube_proxy} if youtube_proxy else None
        )
        if proxies:
            logger.info(f"🌐 [YTMusic/pytubefix] 代理: {youtube_proxy[:30]}...")  # type: ignore[index]

        token_path = os.getenv("YOUTUBE_OAUTH_TOKEN")
        use_oauth = bool(token_path and os.path.exists(token_path))
        if use_oauth:
            logger.info(f"🔐 [YTMusic/pytubefix] OAuth token: {token_path}")

        yt = YouTube(
            video_url,
            client="WEB",
            proxies=proxies,
            use_oauth=use_oauth,
            allow_oauth_cache=True,
            token_file=token_path if use_oauth else None,  # type: ignore[arg-type]
        )

        stream = yt.streams.get_audio_only(subtype="mp4") or (
            yt.streams.filter(only_audio=True).order_by("abr").desc().first()
        )
        if not stream:
            raise RuntimeError("找不到可用的音频流")

        filename = f"ytm_{video_id}_{time.time_ns()}.m4a"
        logger.info(f"🎵 [YTMusic/pytubefix] {yt.title} | {stream.abr}")
        out_path = stream.download(output_path=str(output_dir), filename=filename) or ""
        return Path(out_path), yt.title or "", int(yt.length or 0), yt.author or ""

    try:
        return await asyncio.to_thread(_pytubefix_download)
    except Exception as e:
        logger.error(f"[YTMusic] pytubefix 也失败了: {e}")
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
