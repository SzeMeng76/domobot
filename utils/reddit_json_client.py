"""
Reddit JSON API 客户端（无需 OAuth）
使用 Reddit 公开的 JSON 端点，不需要 API key
"""

import asyncio
import hashlib
import logging
import urllib.request
import urllib.parse
import json
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


class RedditJsonClient:
    """Reddit JSON API 客户端（无需 OAuth）"""

    def __init__(self, user_agent: str = "linux:domo_app:v1.0.0 (by /u/SzeMeng76)"):
        self.user_agent = user_agent
        self.base_url = "https://www.reddit.com"

    def _make_request(self, url: str) -> Dict[str, Any]:
        """发送 HTTP 请求"""
        try:
            headers = {
                'User-Agent': self.user_agent
            }
            req = urllib.request.Request(url, headers=headers)
            response = urllib.request.urlopen(req, timeout=10)
            return json.loads(response.read().decode())
        except Exception as e:
            logger.error(f"Reddit JSON 请求失败 ({url}): {e}")
            raise

    async def _async_request(self, url: str) -> Dict[str, Any]:
        """异步发送请求"""
        return await asyncio.to_thread(self._make_request, url)

    def _parse_post(self, post_data: Dict[str, Any]) -> RedditPost:
        """解析帖子数据"""
        # 提取预览图片
        preview_image_url = ""
        if 'preview' in post_data and 'images' in post_data['preview']:
            images = post_data['preview']['images']
            if images:
                preview_image_url = images[0]['source']['url'].replace('&amp;', '&')

        # 提取视频 URL
        video_url = ""
        is_video = post_data.get('is_video', False)
        if is_video and 'media' in post_data and post_data['media']:
            reddit_video = post_data['media'].get('reddit_video', {})
            video_url = reddit_video.get('fallback_url', '')

        # 提取 gallery 图片
        gallery_items = []
        if 'gallery_data' in post_data:
            gallery_data = post_data['gallery_data']
            if 'items' in gallery_data:
                for item in gallery_data['items']:
                    media_id = item['media_id']
                    if 'media_metadata' in post_data and media_id in post_data['media_metadata']:
                        media = post_data['media_metadata'][media_id]
                        if 's' in media and 'u' in media['s']:
                            img_url = media['s']['u'].replace('&amp;', '&')
                            gallery_items.append(img_url)

        return RedditPost(
            id=post_data['id'],
            title=post_data['title'],
            author=post_data.get('author', '[deleted]'),
            subreddit=post_data['subreddit'],
            score=post_data['score'],
            num_comments=post_data['num_comments'],
            url=post_data['url'],
            permalink=f"https://www.reddit.com{post_data['permalink']}",
            created_utc=post_data['created_utc'],
            is_self=post_data['is_self'],
            selftext=post_data.get('selftext', ''),
            post_hint=post_data.get('post_hint', ''),
            is_video=is_video,
            preview_image_url=preview_image_url,
            video_url=video_url,
            gallery_items=gallery_items
        )

    async def get_post_by_url(self, url: str) -> Optional[RedditPost]:
        """通过 URL 获取帖子"""
        try:
            # 确保 URL 以 .json 结尾
            if not url.endswith('.json'):
                url = url.rstrip('/') + '.json'

            data = await self._async_request(url)

            # 帖子数据在第一个 listing 中
            if isinstance(data, list) and len(data) > 0:
                post_data = data[0]['data']['children'][0]['data']
                return self._parse_post(post_data)

            return None

        except Exception as e:
            logger.error(f"获取帖子失败 ({url}): {e}")
            return None

    async def get_hot_posts(self, subreddit: Optional[str] = None, limit: int = 10) -> List[RedditPost]:
        """获取热门帖子"""
        try:
            if subreddit:
                url = f"{self.base_url}/r/{subreddit}/hot.json?limit={limit}"
            else:
                url = f"{self.base_url}/hot.json?limit={limit}"

            data = await self._async_request(url)
            posts = []

            for item in data['data']['children']:
                post_data = item['data']
                posts.append(self._parse_post(post_data))

            logger.info(f"✅ 获取到 {len(posts)} 个热门帖子")
            return posts

        except Exception as e:
            logger.error(f"获取热门帖子失败: {e}")
            raise

    async def get_top_posts(self, subreddit: Optional[str] = None, time_filter: str = 'day', limit: int = 10) -> List[RedditPost]:
        """获取 Top 帖子"""
        try:
            if subreddit:
                url = f"{self.base_url}/r/{subreddit}/top.json?t={time_filter}&limit={limit}"
            else:
                url = f"{self.base_url}/top.json?t={time_filter}&limit={limit}"

            data = await self._async_request(url)
            posts = []

            for item in data['data']['children']:
                post_data = item['data']
                posts.append(self._parse_post(post_data))

            logger.info(f"✅ 获取到 {len(posts)} 个 Top 帖子")
            return posts

        except Exception as e:
            logger.error(f"获取 Top 帖子失败: {e}")
            raise

    async def get_new_posts(self, subreddit: Optional[str] = None, limit: int = 10) -> List[RedditPost]:
        """获取最新帖子"""
        try:
            if subreddit:
                url = f"{self.base_url}/r/{subreddit}/new.json?limit={limit}"
            else:
                url = f"{self.base_url}/new.json?limit={limit}"

            data = await self._async_request(url)
            posts = []

            for item in data['data']['children']:
                post_data = item['data']
                posts.append(self._parse_post(post_data))

            logger.info(f"✅ 获取到 {len(posts)} 个最新帖子")
            return posts

        except Exception as e:
            logger.error(f"获取最新帖子失败: {e}")
            raise

    async def get_comments(self, post_id: str, limit: int = 10, sort: str = 'top') -> List[RedditComment]:
        """获取评论"""
        try:
            # 构建评论 URL（需要完整的 permalink）
            # 由于我们只有 post_id，需要先获取帖子来得到 permalink
            # 或者使用通用格式（但不知道 subreddit）
            # 最简单的方法：在获取帖子时缓存 permalink

            # 这里使用一个技巧：通过 /comments/{post_id}.json 获取
            url = f"{self.base_url}/comments/{post_id}.json?sort={sort}&limit={limit}"

            data = await self._async_request(url)

            # 评论数据在第二个 listing 中
            if isinstance(data, list) and len(data) > 1:
                comments_listing = data[1]['data']['children']
                comments = []

                for item in comments_listing:
                    if item['kind'] == 't1':  # t1 是评论类型
                        comment_data = item['data']

                        # 跳过 "more" 类型的占位符
                        if comment_data.get('body'):
                            comments.append(RedditComment(
                                id=comment_data['id'],
                                author=comment_data.get('author', '[deleted]'),
                                body=comment_data['body'],
                                score=comment_data['score'],
                                created_utc=comment_data['created_utc']
                            ))

                        # 达到限制就停止
                        if len(comments) >= limit:
                            break

                logger.info(f"✅ 获取到 {len(comments)} 条评论")
                return comments

            return []

        except Exception as e:
            logger.error(f"获取评论失败: {e}")
            return []  # 评论获取失败不影响主功能，返回空列表

    @staticmethod
    def get_url_hash(url: str) -> str:
        """生成 URL 的哈希值"""
        return hashlib.md5(url.encode()).hexdigest()[:16]
