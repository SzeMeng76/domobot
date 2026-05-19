"""
酷狗音乐 API 封装模块
依赖自部署的 KuGouMusicApi (https://github.com/MakcRe/KuGouMusicApi)
通过 HTTP 调用,加密 / 签名都由 Node 服务处理,Python 这边只负责拼请求和解析响应
"""

import base64
import logging
import re
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


# URL 解析正则
_REG_KG_HASH = re.compile(r"hash=([0-9A-Fa-f]{32})")
_REG_KG_ID = re.compile(r"album_audio_id[=/](\d+)")
_REG_KG_DOMAIN = re.compile(r"kugou\.com|t\.kugou\.com|m\.kugou\.com")


# 酷狗官方榜单 ID(从 /rank/list 抽取的常用 12 个)
KUGOU_RANKS = {
    "top500":    {"id": 8888,   "name": "TOP500",      "icon": "🏆"},
    "surge":     {"id": 6666,   "name": "飙升榜",      "icon": "🚀"},
    "new":       {"id": 74534,  "name": "新歌榜",      "icon": "🆕"},
    "douyin":    {"id": 52144,  "name": "抖音热歌",    "icon": "🎵"},
    "kuaishou":  {"id": 52767,  "name": "快手热歌",    "icon": "📱"},
    "network":   {"id": 82831,  "name": "网络热歌",    "icon": "🌐"},
    "yueyu":     {"id": 33165,  "name": "粤语金曲",    "icon": "🇭🇰"},
    "rock":      {"id": 59896,  "name": "摇滚榜",      "icon": "🤘"},
    "minyao":    {"id": 51341,  "name": "民谣榜",      "icon": "🪕"},
    "dj":        {"id": 24971,  "name": "DJ热歌",      "icon": "🎧"},
    "ouwei":     {"id": 31310,  "name": "欧美榜",      "icon": "🇺🇸"},
    "guofeng":   {"id": 85897,  "name": "国潮音乐",    "icon": "🐉"},
}


# 品质映射: 我们对外的 quality 字符串 → 酷狗 API quality 参数
QUALITY_MAP = {
    "128":  "128",
    "320":  "320",
    "flac": "flac",
    "high": "high",  # Hi-Res
}


class KugouAPI:
    """酷狗音乐 API 客户端"""

    def __init__(
        self,
        base_url: str,
        token: str = "",
        userid: str = "",
        dfid: str = "",
        mid: str = "",
        httpx_client: Optional[httpx.AsyncClient] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.userid = userid
        self.dfid = dfid or "-"
        self.mid = mid
        self._client = httpx_client

    def _auth_header(self) -> dict:
        """构建 Authorization 头(KuGou API 项目专有约定,见 server.js#357-363)"""
        parts = []
        if self.token:
            parts.append(f"token={self.token}")
        if self.userid:
            parts.append(f"userid={self.userid}")
        if self.dfid:
            parts.append(f"dfid={self.dfid}")
        if self.mid:
            parts.append(f"mid={self.mid}")
        return {"Authorization": ";".join(parts)} if parts else {}

    async def _get(self, path: str, params: Optional[dict] = None) -> Optional[dict]:
        client = self._client or httpx.AsyncClient(timeout=30)
        url = f"{self.base_url}{path}"
        try:
            resp = await client.get(url, params=params or {}, headers=self._auth_header())
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict):
                raise ValueError(f"Unexpected response type: {type(data)}")
            return data
        except Exception as e:
            logger.error(f"KuGou GET {path} 失败: {e}")
            return None
        finally:
            if not self._client:
                await client.aclose()

    # ============================================================
    # 搜索
    # ============================================================

    async def search_songs(self, keyword: str, limit: int = 10) -> list[dict]:
        """
        搜索歌曲 → /search
        返回: [{"hash", "album_audio_id", "name", "artists", "album", "duration", "filesize", "image"}, ...]
        """
        result = await self._get("/search", {"keywords": keyword, "pagesize": str(limit)})
        if not result:
            return []

        try:
            lists = (result.get("data") or {}).get("lists") or []
            songs = []
            for s in lists:
                # SQ/HQ/MP3 三档优先取 SQ(无损)的 hash
                sq = s.get("SQ") or {}
                hq = s.get("HQ") or {}
                hash_ = sq.get("Hash") or hq.get("Hash") or s.get("FileHash") or ""
                if not hash_:
                    continue
                # 拼歌手名
                artists = s.get("SingerName") or ""
                songs.append({
                    "hash": hash_,
                    "album_audio_id": int(s.get("Audioid") or 0),
                    "name": s.get("OriSongName") or s.get("FileName") or "",
                    "artists": artists,
                    "album": (s.get("AlbumName") or "").strip(),
                    "duration": int(s.get("Duration") or 0),  # 秒
                    "filesize": int(sq.get("FileSize") or s.get("FileSize") or 0),
                    "image": (s.get("Image") or "").replace("{size}", "480"),
                })
            return songs
        except (KeyError, TypeError, ValueError) as e:
            logger.error(f"解析酷狗搜索结果失败: {e}")
            return []

    # ============================================================
    # 歌曲 URL
    # ============================================================

    async def get_song_url(
        self,
        hash_: str,
        album_audio_id: int = 0,
        quality: str = "flac",
    ) -> Optional[dict]:
        """
        获取下载链接 → /song/url
        quality: 128 / 320 / flac / high
        返回: {"url", "size", "type", "br", "name", "duration"}
        """
        params: dict = {"hash": hash_, "quality": QUALITY_MAP.get(quality, quality)}
        if album_audio_id:
            params["album_audio_id"] = str(album_audio_id)

        result = await self._get("/song/url", params)
        if not result:
            return None

        try:
            # url 可能是 list 也可能是 string
            url_field = result.get("url")
            if isinstance(url_field, list):
                url = url_field[0] if url_field else ""
            else:
                url = url_field or ""
            if not url:
                backup = result.get("backupUrl") or []
                url = backup[0] if backup else ""
            if not url:
                logger.warning(f"KuGou 歌曲 {hash_} 无可用下载链接")
                return None

            ext = (result.get("extName") or "mp3").lower()
            if ext not in ("mp3", "flac"):
                ext = "mp3"

            return {
                "url": url,
                "size": int(result.get("fileSize") or 0),
                "type": ext,
                "br": int(result.get("bitRate") or 0),
                "name": result.get("fileName") or "",
                "duration": int(result.get("timeLength") or 0),
                "hash": hash_,
            }
        except (KeyError, TypeError, ValueError) as e:
            logger.error(f"解析酷狗歌曲 URL 失败: {e}")
            return None

    # ============================================================
    # 歌曲详情 (从 album_audio_id 反查)
    # ============================================================

    async def get_song_detail(self, hash_: str, album_audio_id: int = 0) -> Optional[dict]:
        """
        获取歌曲详情 → /audio (按 hash)
        /audio 返回里 audio_name 形如 "歌手 - 歌名",需要拆分
        返回: {"hash", "album_audio_id", "name", "artists", "album", "duration", "pic_url"}
        """
        result = await self._get("/audio", {"hash": hash_})
        if not result:
            return None

        try:
            data = result.get("data")
            if isinstance(data, list):
                data = data[0] if data else {}
            data = data or {}

            full_name = data.get("audio_name") or ""
            # "歌手 - 歌名" → 拆分
            if " - " in full_name:
                artists, name = full_name.split(" - ", 1)
            else:
                artists, name = "", full_name

            return {
                "hash": hash_,
                "album_audio_id": int(data.get("audio_id") or album_audio_id),
                "name": name,
                "artists": artists,
                "album": "",  # /audio 不返回 album
                "duration": int(data.get("timelength") or 0) // 1000,  # ms → s
                "pic_url": "",  # /audio 不返回 cover
            }
        except (KeyError, TypeError, ValueError) as e:
            logger.error(f"解析酷狗歌曲详情失败: {e}")
            return None

    # ============================================================
    # 歌词 (两步: /search/lyric → /lyric)
    # ============================================================

    async def get_song_lyric(self, hash_: str) -> Optional[str]:
        """获取歌词 LRC 文本"""
        # Step 1: 搜索歌词候选
        sr = await self._get("/search/lyric", {"hash": hash_})
        if not sr:
            return None
        candidates = sr.get("candidates") or []
        if not candidates:
            return None
        lid = candidates[0].get("id")
        accesskey = candidates[0].get("accesskey")
        if not lid or not accesskey:
            return None

        # Step 2: 下载歌词
        lr = await self._get("/lyric", {
            "id": lid,
            "accesskey": accesskey,
            "fmt": "lrc",
            "decode": "true",
        })
        if not lr:
            return None

        # decode=true 时优先用 decodeContent,没有就自己 base64 解 content
        content = lr.get("decodeContent")
        if content:
            return content
        raw = lr.get("content") or ""
        if not raw:
            return None
        try:
            return base64.b64decode(raw).decode("utf-8", errors="ignore")
        except Exception as e:
            logger.error(f"解析酷狗歌词 base64 失败: {e}")
            return None

    # ============================================================
    # 榜单
    # ============================================================

    async def get_rank_songs(self, rank_id: int, limit: int = 10) -> Optional[dict]:
        """
        获取榜单歌曲 → /rank/audio
        返回: {"name": str, "songs": [{"hash", "album_audio_id", "name", "artists", "duration"}, ...]}
        """
        result = await self._get("/rank/audio", {"rankid": str(rank_id), "pagesize": str(limit), "page": "1"})
        if not result:
            return None

        try:
            data = result.get("data") or {}
            songlist = data.get("songlist") or []
            songs = []
            for s in songlist[:limit]:
                # rank/audio 的 hash 藏在 audio_info 子对象里(hash_128 是默认音质)
                audio_info = s.get("audio_info") or {}
                hash_ = (
                    audio_info.get("hash_128")
                    or audio_info.get("hash_320")
                    or audio_info.get("hash_flac")
                    or s.get("hash")
                    or s.get("FileHash")
                    or ""
                )
                if not hash_:
                    continue
                # author 名字
                authors = s.get("authors") or []
                if authors and isinstance(authors, list):
                    artists = "/".join(a.get("author_name", "") for a in authors if a.get("author_name"))
                else:
                    artists = s.get("author_name") or s.get("singername") or ""
                # duration 在 audio_info.duration_128(ms)
                duration_ms = audio_info.get("duration_128") or audio_info.get("duration_320") or 0
                songs.append({
                    "hash": hash_,
                    "album_audio_id": int(s.get("album_audio_id") or s.get("audio_id") or 0),
                    "name": s.get("songname") or "",
                    "artists": artists,
                    "duration": int(duration_ms) // 1000,
                })
            return {
                "name": "",  # /rank/audio 不返回榜单名,由调用方填
                "songs": songs,
                "total": int(data.get("total") or len(songs)),
            }
        except (KeyError, TypeError, ValueError) as e:
            logger.error(f"解析酷狗榜单失败: {e}")
            return None


# ============================================================
# URL / 文本解析工具
# ============================================================

def parse_kugou_hash(text: str) -> Optional[tuple[str, int]]:
    """
    从文本中解析酷狗 hash + album_audio_id
    返回 (hash, album_audio_id) 或 None
    """
    text = text.replace("\n", "").replace(" ", "")
    hash_match = _REG_KG_HASH.search(text)
    id_match = _REG_KG_ID.search(text)
    if hash_match:
        hash_ = hash_match.group(1).upper()
        aid = int(id_match.group(1)) if id_match else 0
        return (hash_, aid)
    return None


def contains_kugou_link(text: str) -> bool:
    """检测文本是否包含酷狗音乐链接"""
    return bool(_REG_KG_DOMAIN.search(text))


async def resolve_kugou_short_url(url: str, httpx_client: Optional[httpx.AsyncClient] = None) -> str:
    """解析 t.kugou.com 短链接,返回重定向后的 URL"""
    if "t.kugou.com" not in url and "m.kugou.com" not in url:
        return url
    client = httpx_client or httpx.AsyncClient(timeout=10)
    try:
        resp = await client.get(url, follow_redirects=False)
        return resp.headers.get("location", url)
    except Exception as e:
        logger.error(f"解析酷狗短链接失败: {e}")
        return url
    finally:
        if not httpx_client:
            await client.aclose()
