"""
Reddit API 客户端
封装 Reddit OAuth 认证和 API 请求
"""

import asyncio
import hashlib
import logging
import urllib.request
import urllib.parse
import json
from base64 import b64encode
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RedditPost:
    """Reddit 帖子数据类"""
    id: str
    title: str
    author: str
    subreddit: str
    score: int
    num_comments: int
    url: str
    permalink: str
    created_utc: float
    is_self: bool
    selftext: str = ""
    post_hint: str = ""
    is_video: bool = False
    preview_image_url: str = ""
    video_url: str = ""
    gallery_items: List[str] = None

    def __post_init__(self):
        if self.gallery_items is None:
            self.gallery_items = []


@dataclass
class RedditComment:
    """Reddit 评论数据类"""
    id: str
    author: str
    body: str
    score: int
    created_utc: float


class RedditClient:
    """Reddit API 客户端"""

    def __init__(self, client_id: str, client_secret: str, user_agent: str = "domobot:v1.0.0"):
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_agent = user_agent
        self.access_token: Optional[str] = None
        self.token_expiry: float = 0

    async def _get_access_token(self) -> str:
        """获取或刷新访问令牌"""
        import time
        now = time.time()

        # 如果令牌仍然有效，直接返回
        if self.access_token and self.token_expiry > now:
            return self.access_token

        try:
            auth = b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
            headers = {
                'Authorization': f'Basic {auth}',
                'User-Agent': self.user_agent,
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            data = urllib.parse.urlencode({'grant_type': 'client_credentials'}).encode()

            req = urllib.request.Request(
                'https://www.reddit.com/api/v1/access_token',
                data=data,
                headers=headers,
                method='POST'
            )

            response = await asyncio.to_thread(urllib.request.urlopen, req)
            token_data = json.loads(response.read().decode())

            self.access_token = token_data['access_token']
            self.token_expiry = now + (token_data['expires_in'] - 60)  # 提前60秒刷新

            logger.info(f"✅ Reddit 访问令牌已获取")
            return self.access_token

        except Exception as e:
            logger.error(f"获取 Reddit 访问令牌失败: {e}")
            raise

    async def _api_request(self, endpoint: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """发送 Reddit API 请求"""
        try:
            token = await self._get_access_token()
            url = f"https://oauth.reddit.com{endpoint}"

            if params:
                query_params = urllib.parse.urlencode(params)
                url += f"?{query_params}"

            headers = {
                'Authorization': f'Bearer {token}',
                'User-Agent': self.user_agent
            }

            req = urllib.request.Request(url, headers=headers)
            response = await asyncio.to_thread(urllib.request.urlopen, req)
            return json.loads(response.read().decode())

        except Exception as e:
            logger.error(f"Reddit API 请求失败 ({endpoint}): {e}")
            raise

    async def get_post_by_id(self, post_id: str) -> Optional[RedditPost]:
        """通过 ID 获取帖子"""
        try:
            # 清理 ID（移除 t3_ 前缀）
            clean_id = post_id.replace('t3_', '')

            data = await self._api_request(f"/comments/{clean_id}", {'limit': '1'})

            if not data or not data[0]['data']['children']:
                return None

            post_data = data[0]['data']['children'][0]['data']
            return self._parse_post(post_data)

        except Exception as e:
            logger.error(f"获取帖子失败 (ID: {post_id}): {e}")
            return None

    async def get_post_by_url(self, url: str) -> Optional[RedditPost]:
        """通过 URL 获取帖子"""
        try:
            # 从 URL 提取帖子 ID
            # 格式: https://www.reddit.com/r/subreddit/comments/post_id/title/
            import re
            match = re.search(r'/comments/([a-z0-9]+)', url)
            if not match:
                logger.error(f"无法从 URL 提取帖子 ID: {url}")
                return None

            post_id = match.group(1)
            return await self.get_post_by_id(post_id)

        except Exception as e:
            logger.error(f"通过 URL 获取帖子失败: {e}")
            return None

    async def get_comments(self, post_id: str, limit: int = 10, sort: str = 'top') -> List[RedditComment]:
        """获取帖子评论"""
        try:
            clean_id = post_id.replace('t3_', '')

            params = {
                'sort': sort,
                'limit': str(limit)
            }

            data = await self._api_request(f"/comments/{clean_id}", params)

            if len(data) < 2:
                return []

            comments = []
            for child in data[1]['data']['children']:
                if child['kind'] == 't1':  # t1 = comment
                    comment_data = child['data']
                    comments.append(RedditComment(
                        id=comment_data['id'],
                        author=comment_data['author'],
                        body=comment_data['body'],
                        score=comment_data['score'],
                        created_utc=comment_data['created_utc']
                    ))

            return comments

        except Exception as e:
            logger.error(f"获取评论失败: {e}")
            return []

    async def get_hot_posts(self, subreddit: str = None, limit: int = 10) -> List[RedditPost]:
        """获取热门帖子

        Args:
            subreddit: subreddit名称，None表示全站
            limit: 返回数量，默认10
        """
        try:
            endpoint = f"/r/{subreddit}/hot" if subreddit else "/hot"
            params = {'limit': str(limit)}

            data = await self._api_request(endpoint, params)

            posts = []
            for child in data['data']['children']:
                if child['kind'] == 't3':  # t3 = post
                    posts.append(self._parse_post(child['data']))

            return posts

        except Exception as e:
            logger.error(f"获取热门帖子失败: {e}")
            return []

    async def get_top_posts(self, subreddit: str = None, time_filter: str = 'day', limit: int = 10) -> List[RedditPost]:
        """获取Top帖子

        Args:
            subreddit: subreddit名称，None表示全站
            time_filter: 时间范围 (hour/day/week/month/year/all)
            limit: 返回数量，默认10
        """
        try:
            endpoint = f"/r/{subreddit}/top" if subreddit else "/top"
            params = {
                'limit': str(limit),
                't': time_filter
            }

            data = await self._api_request(endpoint, params)

            posts = []
            for child in data['data']['children']:
                if child['kind'] == 't3':  # t3 = post
                    posts.append(self._parse_post(child['data']))

            return posts

        except Exception as e:
            logger.error(f"获取Top帖子失败: {e}")
            return []

    async def get_new_posts(self, subreddit: str = None, limit: int = 10) -> List[RedditPost]:
        """获取最新帖子

        Args:
            subreddit: subreddit名称，None表示全站
            limit: 返回数量，默认10
        """
        try:
            endpoint = f"/r/{subreddit}/new" if subreddit else "/new"
            params = {'limit': str(limit)}

            data = await self._api_request(endpoint, params)

            posts = []
            for child in data['data']['children']:
                if child['kind'] == 't3':  # t3 = post
                    posts.append(self._parse_post(child['data']))

            return posts

        except Exception as e:
            logger.error(f"获取最新帖子失败: {e}")
            return []

    def _parse_post(self, post_data: Dict[str, Any]) -> RedditPost:
        """解析帖子数据"""
        post = RedditPost(
            id=post_data['id'],
            title=post_data['title'],
            author=post_data['author'],
            subreddit=post_data['subreddit'],
            score=post_data['score'],
            num_comments=post_data['num_comments'],
            url=post_data['url'],
            permalink=f"https://www.reddit.com{post_data['permalink']}",
            created_utc=post_data['created_utc'],
            is_self=post_data['is_self'],
            selftext=post_data.get('selftext', ''),
            post_hint=post_data.get('post_hint', ''),
            is_video=post_data.get('is_video', False)
        )

        # 提取图片 URL
        if 'preview' in post_data and 'images' in post_data['preview']:
            try:
                img = post_data['preview']['images'][0]['source']
                post.preview_image_url = img['url'].replace('&amp;', '&')
            except (KeyError, IndexError):
                pass

        # 提取视频 URL
        if post.is_video and 'media' in post_data and post_data['media']:
            try:
                video = post_data['media'].get('reddit_video', {})
                post.video_url = video.get('fallback_url', '')
            except (KeyError, TypeError):
                pass

        # 提取图集
        if 'gallery_data' in post_data:
            try:
                gallery_items = post_data['gallery_data']['items']
                media_metadata = post_data.get('media_metadata', {})

                for item in gallery_items:
                    media_id = item['media_id']
                    if media_id in media_metadata:
                        media = media_metadata[media_id]
                        if 's' in media and 'u' in media['s']:
                            img_url = media['s']['u'].replace('&amp;', '&')
                            post.gallery_items.append(img_url)

                # 如果没有 preview_image_url，使用 gallery 的第一张图片
                if not post.preview_image_url and post.gallery_items:
                    post.preview_image_url = post.gallery_items[0]
            except (KeyError, TypeError):
                pass

        return post

    @staticmethod
    def get_url_hash(url: str) -> str:
        """生成 URL 的 MD5 哈希值（用于 callback_data）"""
        md5 = hashlib.md5()
        md5.update(url.encode("utf-8"))
        return md5.hexdigest()
