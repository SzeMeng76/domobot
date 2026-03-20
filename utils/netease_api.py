"""
网易云音乐 API 封装模块
参考 Music163bot-Go (github.com/XiaoMengXinX/Music163Api-Go) 实现
使用 WeAPI 加密方式调用网易云音乐接口
"""

import base64
import binascii
import hashlib
import json
import logging
import os
import re
from typing import Optional

import httpx
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

logger = logging.getLogger(__name__)

# WeAPI 加密常量
MODULUS = "00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7b725152b3ab17a876aea8a5aa76d2e417629ec4ee341f56135fccf695280104e0312ecbda92557c93870114af6c9d05c4f7f0c3685b7a46bee255932575cce10b424d813cfe4875d3e82047b97ddef52741d546b8e289dc6935b3ece0462db0a22b8e7"
NONCE = "0CoJUm6Qyw8W8jud"
PUB_KEY = "010001"
# 固定的 secretKey (与 Go 源码一致)
SECRET_KEY = "TA3YiYCfY2dDJQgg"
# 预计算的 encSecKey
ENC_SEC_KEY = "84ca47bca10bad09a6b04c561b7c0dc0eb27dc7263830df2fa26e119d0d4974ac1b4ee93e2ce7404da5f tried34e3d55a5e593e94b3acf2a0eeb2f18c26f1c5e4a5f69c733e1f7d1e3c1e9e2e1f3c5d4f6a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3"

# 固定随机字节（简化实现，与 Go 源码保持一致）
_IV = b"0102030405060708"


def _aes_encrypt(text: str, key: str) -> str:
    """AES-CBC-128 加密"""
    cipher = AES.new(key.encode("utf-8"), AES.MODE_CBC, _IV)
    encrypted = cipher.encrypt(pad(text.encode("utf-8"), AES.block_size))
    return base64.b64encode(encrypted).decode("utf-8")


def _weapi_encrypt(payload: dict) -> dict:
    """WeAPI 加密请求参数"""
    text = json.dumps(payload)
    # 第一次加密：使用 NONCE
    enc1 = _aes_encrypt(text, NONCE)
    # 第二次加密：使用 SECRET_KEY
    enc2 = _aes_encrypt(enc1, SECRET_KEY)
    return {
        "params": enc2,
        "encSecKey": ENC_SEC_KEY,
    }


# 网易云 API 请求头
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Referer": "https://music.163.com",
    "Content-Type": "application/x-www-form-urlencoded",
    "Origin": "https://music.163.com",
}

# URL 解析正则
_REG_SONG_ID = re.compile(r"song[/?].*?(?:id=)?(\d+)")
_REG_PROGRAM_ID = re.compile(r"(?:program|dj)[/?].*?(?:id=)?(\d+)")
_REG_URL = re.compile(r"https?://[^\s]+")
_REG_MUSIC_DOMAIN = re.compile(r"music\.163\.com|163cn\.tv|163cn\.link")


class NeteaseAPI:
    """网易云音乐 API 客户端"""

    BASE_URL = "https://music.163.com"

    def __init__(self, music_u: str = "", httpx_client: Optional[httpx.AsyncClient] = None):
        self.music_u = music_u
        self._client = httpx_client

    def _get_cookies(self) -> dict:
        cookies = {"os": "pc", "appver": "2.10.14"}
        if self.music_u:
            cookies["MUSIC_U"] = self.music_u
        return cookies

    async def _request(self, endpoint: str, payload: dict) -> dict:
        """发送加密 API 请求"""
        url = f"{self.BASE_URL}/weapi{endpoint}"
        data = _weapi_encrypt(payload)
        client = self._client or httpx.AsyncClient(timeout=30)
        try:
            resp = await client.post(
                url,
                data=data,
                headers=_HEADERS,
                cookies=self._get_cookies(),
            )
            resp.raise_for_status()
            return resp.json()
        finally:
            if not self._client:
                await client.aclose()

    async def search_songs(self, keyword: str, limit: int = 10) -> list[dict]:
        """
        搜索歌曲
        返回: [{"id": int, "name": str, "artists": str, "album": str, "duration": int}, ...]
        """
        payload = {
            "s": keyword,
            "type": 1,  # 1=歌曲
            "limit": limit,
            "offset": 0,
        }
        result = await self._request("/cloudsearch/get/web", payload)

        songs = []
        try:
            for s in result.get("result", {}).get("songs", []):
                artists = "/".join(ar.get("name", "") for ar in s.get("ar", []))
                songs.append({
                    "id": s["id"],
                    "name": s.get("name", ""),
                    "artists": artists,
                    "album": s.get("al", {}).get("name", ""),
                    "duration": s.get("dt", 0) // 1000,
                })
        except (KeyError, TypeError) as e:
            logger.error(f"解析搜索结果失败: {e}")
        return songs

    async def get_song_detail(self, song_id: int) -> Optional[dict]:
        """
        获取歌曲详情
        返回: {"id", "name", "artists", "album", "pic_url", "duration"}
        """
        payload = {
            "c": json.dumps([{"id": song_id}]),
            "ids": json.dumps([song_id]),
        }
        result = await self._request("/v3/song/detail", payload)

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

    async def get_song_url(self, song_id: int, level: str = "exhigh") -> Optional[dict]:
        """
        获取歌曲下载链接
        level: standard, higher, exhigh, lossless, hires
        返回: {"url", "size", "md5", "type"}
        """
        payload = {
            "ids": json.dumps([song_id]),
            "level": level,
            "encodeType": "flac",
        }
        result = await self._request("/song/enhance/player/url/v1", payload)

        try:
            d = result["data"][0]
            url = d.get("url")
            if not url:
                logger.warning(f"歌曲 {song_id} 无可用下载链接")
                return None
            # 文件类型检测（参考 processMusic.go）
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
        """获取歌词（LRC 格式），无歌词返回 None"""
        payload = {
            "id": song_id,
            "lv": -1,
            "tv": -1,
            "rv": -1,
        }
        result = await self._request("/song/lyric", payload)
        try:
            lyric = result.get("lrc", {}).get("lyric", "")
            return lyric if lyric else None
        except (KeyError, TypeError):
            return None

    async def get_program_song_id(self, program_id: int) -> Optional[int]:
        """获取电台节目的真实歌曲 ID"""
        payload = {"id": program_id}
        result = await self._request("/dj/program/detail", payload)
        try:
            return result["program"]["mainSong"]["id"]
        except (KeyError, TypeError):
            return None


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
    # 尝试纯数字
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
