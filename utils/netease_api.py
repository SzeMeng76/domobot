"""
网易云音乐 API 封装模块
参考 Music163Api-Go (github.com/XiaoMengXinX/Music163Api-Go) 实现
使用 EAPI 加密方式调用网易云音乐接口（AES-ECB，与 Go 源码一致）
"""

import hashlib
import json
import logging
import os
import re
import secrets
import string
import time
from typing import Optional

import httpx
from Crypto.Cipher import AES

logger = logging.getLogger(__name__)

# EAPI 加密密钥（来自 Music163Api-Go/utils/crypto.go）
_EAPI_KEY = b"e82ckenh8dichen8"


def _generate_key(key: bytes) -> bytes:
    """generateKey — 与 Go 源码一致"""
    gen_key = bytearray(key[:16].ljust(16, b"\x00"))
    i = 16
    while i < len(key):
        for j in range(16):
            if i >= len(key):
                break
            gen_key[j] ^= key[i]
            i += 1
    return bytes(gen_key)


def _pkcs7_pad(data: bytes, block_size: int = 16) -> bytes:
    pad_len = block_size - (len(data) % block_size)
    return data + bytes([pad_len] * pad_len)


def _eapi_encrypt(text: str) -> bytes:
    """AES-ECB 加密 — 对应 Go 的 encryptECB / EapiEncrypt"""
    key = _generate_key(_EAPI_KEY)
    cipher = AES.new(key, AES.MODE_ECB)
    padded = _pkcs7_pad(text.encode())
    return cipher.encrypt(padded)


def _splice_str(path: str, data: str) -> str:
    """SpliceStr — 拼接签名字符串（来自 Go utils/request.go）"""
    nobody = "36cd479b6b5"
    text = f"nobody{path}use{data}md5forencrypt"
    md5_hex = hashlib.md5(text.encode()).hexdigest()
    return f"{path}-{nobody}-{data}-{nobody}-{md5_hex}"


def _format_params(spliced: str) -> str:
    """Format2Params — 加密后转大写十六进制"""
    encrypted = _eapi_encrypt(spliced)
    return f"params={encrypted.hex().upper()}"


def _generate_device_id() -> str:
    charset = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(charset) for _ in range(32))


# 随机 User-Agent 列表（来自 Go utils/request.go）
_USER_AGENTS = [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 9_1 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Version/9.0 Mobile/13B143 Safari/601.1",
    "Mozilla/5.0 (Linux; Android 5.0; SM-G900P Build/LRX21T) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/59.0.3071.115 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/59.0.3071.115 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 10_0 like Mac OS X) AppleWebKit/602.1.38 (KHTML, like Gecko) Version/10.0 Mobile/14A300 Safari/602.1",
    "NeteaseMusic/9.3.40.1753206443(164);Dalvik/2.1.0 (Linux; U; Android 9; MIX 2 MIUI/V12.0.1.0.PDECNXM)",
]

# URL 解析正则
_REG_SONG_ID = re.compile(r"song[/?].*?(?:id=)?(\d+)")
_REG_PROGRAM_ID = re.compile(r"(?:program|dj)[/?].*?(?:id=)?(\d+)")
_REG_URL = re.compile(r"https?://[^\s]+")
_REG_MUSIC_DOMAIN = re.compile(r"music\.163\.com|163cn\.tv|163cn\.link")


class NeteaseAPI:
    """网易云音乐 API 客户端（EAPI 加密，与 Music163Api-Go 一致）"""

    BASE_URL = "https://music.163.com"

    def __init__(self, music_u: str = "", httpx_client: Optional[httpx.AsyncClient] = None):
        self.music_u = music_u
        self._client = httpx_client
        self._device_id = _generate_device_id()

    def _build_cookie_str(self) -> str:
        """构建 Cookie 字符串（对应 Go CreateNewRequest 中的 cookie 拼接）"""
        cookie = {
            "deviceId": self._device_id,
            "appver": "9.3.40",
            "buildver": str(int(time.time()))[:10],
            "resolution": "1920x1080",
            "os": "Android",
        }
        if self.music_u:
            cookie["MUSIC_U"] = self.music_u
        else:
            # 无登录时使用匿名 token（来自 Go 源码）
            cookie["MUSIC_A"] = (
                "4ee5f776c9ed1e4d5f031b09e084c6cb333e43ee4a841afeebbef9bbf4b7e4152b51ff20ecb9e8ee"
                "9e89ab23044cf50d1609e4781e805e73a138419e5583bc7fd1e5933c52368d9127ba9ce4e2f233bf"
                "5a77ba40ea6045ae1fc612ead95d7b0e0edf70a74334194e1a190979f5fc12e9968c3666a981495b"
                "33a649814e309366"
            )
        parts = [f"{k}={v}" for k, v in cookie.items()]
        return "; ".join(parts)

    async def _request(self, api_path: str, payload_json: str) -> dict:
        """
        发送 EAPI 请求（ApiRequest — 响应未加密）
        api_path: 如 /api/v1/search/song/get
        payload_json: JSON 字符串
        """
        spliced = _splice_str(api_path, payload_json)
        body = _format_params(spliced)
        url = f"{self.BASE_URL}/eapi{api_path.removeprefix('/api')}"

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": secrets.choice(_USER_AGENTS),
            "Cookie": self._build_cookie_str(),
        }

        client = self._client or httpx.AsyncClient(timeout=30)
        try:
            resp = await client.post(url, content=body, headers=headers)
            logger.debug(f"NetEase EAPI {api_path} status={resp.status_code} body={resp.text[:200]}")
            resp.raise_for_status()
            result = resp.json()
            if not isinstance(result, dict):
                raise ValueError(f"Unexpected response type: {type(result)}")
            return result
        finally:
            if not self._client:
                await client.aclose()

    async def search_songs(self, keyword: str, limit: int = 10) -> list[dict]:
        """
        搜索歌曲（对应 Go SearchSong / SearchSongAPI = /api/v1/search/song/get）
        返回: [{"id": int, "name": str, "artists": str, "album": str, "duration": int}, ...]
        """
        payload = json.dumps({"s": keyword, "offset": 0, "limit": limit})
        result = await self._request("/api/v1/search/song/get", payload)

        songs = []
        try:
            for s in result.get("result", {}).get("songs", []):
                artists = "/".join(ar.get("name", "") for ar in s.get("artists", []))
                songs.append({
                    "id": s["id"],
                    "name": s.get("name", ""),
                    "artists": artists,
                    "album": s.get("album", {}).get("name", ""),
                    "duration": s.get("duration", 0) // 1000,
                })
        except (KeyError, TypeError) as e:
            logger.error(f"解析搜索结果失败: {e}")
        return songs

    async def get_song_detail(self, song_id: int) -> Optional[dict]:
        """
        获取歌曲详情（对应 Go GetSongDetail / SongDetailAPI = /api/v3/song/detail）
        """
        c_json = json.dumps([{"id": song_id}])
        payload = json.dumps({"c": c_json})
        result = await self._request("/api/v3/song/detail", payload)

        try:
            s = result["songs"][0]
            artists = "/".join(ar.get("name", "") for ar in s.get("ar", []))
            return {
                "id": s["id"],
                "name": s.get("name", ""),
                "artists": artists,
                "album": s.get("al", {}).get("name", ""),
                "pic_url": s.get("al", {}).get("picUrl", ""),
                "duration": s.get("dt", 0) // 1000,
            }
        except (KeyError, IndexError, TypeError) as e:
            logger.error(f"获取歌曲详情失败: {e}")
            return None

    async def get_song_url(self, song_id: int, level: str = "hires") -> Optional[dict]:
        """
        获取歌曲下载链接（对应 Go GetSongURL / SongUrlAPI = /api/song/enhance/player/url/v1）
        level: standard, higher, exhigh, lossless, hires
        注意：Go 源码中 ids 是 JSON string array（如 ["12345"]），encodeType 默认 mp3
        """
        ids_json = json.dumps([str(song_id)])
        payload = json.dumps({
            "ids": ids_json,
            "level": level,
            "encodeType": "mp3",
        })
        result = await self._request("/api/song/enhance/player/url/v1", payload)

        try:
            d = result["data"][0]
            url = d.get("url")
            if not url:
                logger.warning(f"歌曲 {song_id} 无可用下载链接")
                return None
            base_url = url.split("?")[0]
            ext = os.path.splitext(base_url)[1].lstrip(".")
            if ext not in ("mp3", "flac"):
                ext = "mp3"
            return {
                "url": url,
                "size": d.get("size", 0),
                "md5": d.get("md5", ""),
                "type": ext,
                "br": d.get("br", 0),
            }
        except (KeyError, IndexError, TypeError) as e:
            logger.error(f"获取下载链接失败: {e}")
            return None

    async def get_song_lyric(self, song_id: int) -> Optional[str]:
        """获取歌词（对应 Go GetSongLyric / SongLyricAPI = /api/song/lyric）"""
        payload = json.dumps({
            "id": song_id,
            "lv": -1,
            "kv": -1,
            "tv": -1,
            "yv": -1,
        })
        result = await self._request("/api/song/lyric", payload)
        try:
            lyric = result.get("lrc", {}).get("lyric", "")
            return lyric if lyric else None
        except (KeyError, TypeError):
            return None

    async def get_program_song_id(self, program_id: int) -> Optional[int]:
        """获取电台节目的真实歌曲 ID（对应 Go GetProgramDetail）"""
        payload = json.dumps({"id": str(program_id)})
        result = await self._request("/api/dj/program/detail", payload)
        try:
            return result["program"]["mainSong"]["id"]
        except (KeyError, TypeError):
            return None

    async def get_playlist_detail(self, playlist_id: int, limit: int = 10) -> Optional[dict]:
        """
        获取歌单/榜单详情（对应 Go GetPlaylistDetail / PlaylistDetailAPI = /api/v6/playlist/detail）
        榜单就是特殊歌单，用固定的 playlist ID 即可获取
        返回: {"name": str, "description": str, "track_count": int, "songs": [{"id", "name", "artists", "duration"}, ...]}
        """
        payload = json.dumps({
            "id": str(playlist_id),
            "t": "0",
            "n": str(limit),
            "s": "0",
        })
        result = await self._request("/api/v6/playlist/detail", payload)
        try:
            p = result["playlist"]
            songs = []
            for s in (p.get("tracks") or [])[:limit]:
                artists = "/".join(ar.get("name", "") for ar in s.get("ar", []))
                songs.append({
                    "id": s["id"],
                    "name": s.get("name", ""),
                    "artists": artists,
                    "album": s.get("al", {}).get("name", ""),
                    "duration": s.get("dt", 0) // 1000,
                })
            return {
                "name": p.get("name", ""),
                "description": p.get("description", ""),
                "track_count": p.get("trackCount", 0),
                "songs": songs,
            }
        except (KeyError, TypeError) as e:
            logger.error(f"获取歌单详情失败: {e}")
            return None


# 网易云音乐官方榜单 ID（榜单本质是特殊歌单）
CHART_PLAYLISTS = {
    "hot":        {"id": 3778678,    "name": "热歌榜",    "icon": "🔥"},
    "new":        {"id": 3779629,    "name": "新歌榜",    "icon": "🆕"},
    "surge":      {"id": 19723756,   "name": "飙升榜",    "icon": "🚀"},
    "original":   {"id": 2884035,    "name": "原创榜",    "icon": "✨"},
    "rap":        {"id": 991319590,  "name": "说唱榜",    "icon": "🎤"},
    "acg":        {"id": 71385702,   "name": "ACG榜",     "icon": "🎮"},
    "electronic": {"id": 745956260,  "name": "电音榜",    "icon": "🎧"},
    "billboard":  {"id": 60198,      "name": "Billboard", "icon": "🇺🇸"},
    "uk":         {"id": 180106,     "name": "UK排行榜",  "icon": "🇬🇧"},
    "japan":      {"id": 60131,      "name": "日本Oricon", "icon": "🇯🇵"},
}


# ============================================================
# URL 解析工具函数（参考 bot/tools.go）
# ============================================================

def parse_music_id(text: str) -> Optional[int]:
    """从文本中解析网易云歌曲 ID"""
    text = text.replace("\n", "").replace(" ", "")
    match = _REG_SONG_ID.search(text)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass
    nums = re.findall(r"\d+", text)
    if nums:
        try:
            return int(nums[0])
        except ValueError:
            pass
    return None


def parse_program_id(text: str) -> Optional[int]:
    """从文本中解析电台节目 ID"""
    text = text.replace("\n", "").replace(" ", "")
    match = _REG_PROGRAM_ID.search(text)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass
    return None


def contains_music_link(text: str) -> bool:
    """检测文本是否包含网易云音乐链接"""
    return bool(_REG_MUSIC_DOMAIN.search(text))


async def resolve_short_url(url: str, httpx_client: Optional[httpx.AsyncClient] = None) -> str:
    """解析 163cn.tv / 163cn.link 短链接，返回重定向后的 URL"""
    if "163cn.tv" not in url and "163cn.link" not in url:
        return url
    client = httpx_client or httpx.AsyncClient(timeout=10)
    try:
        resp = await client.get(url, follow_redirects=False)
        location = resp.headers.get("location", url)
        return location
    except Exception as e:
        logger.error(f"解析短链接失败: {e}")
        return url
    finally:
        if not httpx_client:
            await client.aclose()
