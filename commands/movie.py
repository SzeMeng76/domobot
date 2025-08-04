import logging
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown

from utils.command_factory import command_factory
from utils.config_manager import config_manager
from utils.formatter import foldable_text_v2, foldable_text_with_markdown_v2
from utils.message_manager import delete_user_command, send_error, send_success
from utils.permissions import Permission

logger = logging.getLogger(__name__)

# Telegraph 相关配置
TELEGRAPH_API_URL = "https://api.telegra.ph"
TELEGRAM_MESSAGE_LIMIT = 4096

# 全局变量
cache_manager = None
httpx_client = None

def set_dependencies(c_manager, h_client):
    global cache_manager, httpx_client
    cache_manager = c_manager
    httpx_client = h_client

class MovieService:
    """电影信息查询服务类"""
    
    def __init__(self):
        self.tmdb_base_url = "https://api.themoviedb.org/3"
        self.tmdb_image_base_url = "https://image.tmdb.org/t/p/w500"
        self.trakt_base_url = "https://api.trakt.tv"
        
    async def _get_tmdb_api_key(self) -> Optional[str]:
        """获取TMDB API密钥"""
        return config_manager.config.tmdb_api_key if hasattr(config_manager.config, 'tmdb_api_key') else None
    
    async def _get_trakt_api_key(self) -> Optional[str]:
        """获取Trakt API密钥"""
        return config_manager.config.trakt_api_key if hasattr(config_manager.config, 'trakt_api_key') else None
    
    async def _make_tmdb_request(self, endpoint: str, params: Dict[str, Any] = None, language: str = "zh-CN") -> Optional[Dict]:
        """发起TMDB API请求"""
        api_key = await self._get_tmdb_api_key()
        if not api_key:
            logger.error("TMDB API密钥未配置")
            return None
            
        try:
            url = f"{self.tmdb_base_url}/{endpoint}"
            request_params = {"api_key": api_key, "language": language}
            if params:
                request_params.update(params)
                
            response = await httpx_client.get(url, params=request_params, timeout=20.0)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            logger.error(f"TMDB API请求失败: {e}")
            return None
        except Exception as e:
            logger.error(f"TMDB API请求异常: {e}")
            return None
    
    async def _make_trakt_request(self, endpoint: str, params: Dict[str, Any] = None) -> Optional[Dict]:
        """发起Trakt API请求"""
        api_key = await self._get_trakt_api_key()
        if not api_key:
            logger.error("Trakt API密钥未配置")
            return None
            
        try:
            url = f"{self.trakt_base_url}/{endpoint}"
            headers = {
                "Content-Type": "application/json",
                "trakt-api-version": "2",
                "trakt-api-key": api_key
            }
            
            response = await httpx_client.get(url, params=params, headers=headers, timeout=20.0)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            logger.error(f"Trakt API请求失败: {e}")
            return None
        except Exception as e:
            logger.error(f"Trakt API请求异常: {e}")
            return None
    
    async def _get_videos_data(self, content_type: str, content_id: int) -> Optional[Dict]:
        """专门获取视频数据的方法，使用英文API以获取更多内容"""
        endpoint = f"{content_type}/{content_id}/videos"
        return await self._make_tmdb_request(endpoint, language="en-US")
    
    async def _get_reviews_data(self, content_type: str, content_id: int) -> Optional[Dict]:
        """获取评价数据的方法，优先中文评价，不足时补充英文评价"""
        # 先获取中文评价
        chinese_reviews = await self._make_tmdb_request(f"{content_type}/{content_id}/reviews", language="zh-CN")
        
        # 如果中文评价少于2个，再获取英文评价补充
        all_reviews = []
        if chinese_reviews and chinese_reviews.get("results"):
            all_reviews.extend(chinese_reviews["results"])
        
        # 如果需要更多评价，获取英文评价
        if len(all_reviews) < 2:
            english_reviews = await self._make_tmdb_request(f"{content_type}/{content_id}/reviews", language="en-US")
            if english_reviews and english_reviews.get("results"):
                # 添加英文评价，但避免重复
                existing_ids = {review.get("id") for review in all_reviews}
                for review in english_reviews["results"]:
                    if review.get("id") not in existing_ids and len(all_reviews) < 4:
                        all_reviews.append(review)
        
        # 构造返回数据
        if all_reviews:
            return {"results": all_reviews}
        return None
    
    async def search_movies(self, query: str, page: int = 1) -> Optional[Dict]:
        """搜索电影"""
        cache_key = f"movie_search_{query.lower()}_{page}"
        cached_data = await cache_manager.load_cache(cache_key, subdirectory="movie")
        if cached_data:
            return cached_data
            
        data = await self._make_tmdb_request("search/movie", {"query": query, "page": page})
        if data:
            await cache_manager.save_cache(cache_key, data, subdirectory="movie")
        return data
    
    async def get_popular_movies(self, page: int = 1) -> Optional[Dict]:
        """获取热门电影"""
        cache_key = f"movie_popular_{page}"
        cached_data = await cache_manager.load_cache(cache_key, subdirectory="movie")
        if cached_data:
            return cached_data
            
        data = await self._make_tmdb_request("movie/popular", {"page": page})
        if data:
            await cache_manager.save_cache(cache_key, data, subdirectory="movie")
        return data
    
    async def get_movie_details(self, movie_id: int) -> Optional[Dict]:
        """获取电影详情"""
        cache_key = f"movie_detail_{movie_id}"
        cached_data = await cache_manager.load_cache(cache_key, subdirectory="movie")
        if cached_data:
            return cached_data
            
        # 获取中文详情信息
        data = await self._make_tmdb_request(f"movie/{movie_id}", {
            "append_to_response": "credits,recommendations,watch/providers"
        })
        
        if data:
            # 如果关键字段为空，获取英文信息补充
            if not data.get("overview") or not data.get("tagline"):
                english_data = await self._make_tmdb_request(f"movie/{movie_id}", {
                    "append_to_response": "credits,recommendations,watch/providers"
                }, language="en-US")
                
                if english_data:
                    # 如果中文简介为空，使用英文简介
                    if not data.get("overview") and english_data.get("overview"):
                        data["overview"] = english_data["overview"]
                    
                    # 如果中文标语为空，使用英文标语
                    if not data.get("tagline") and english_data.get("tagline"):
                        data["tagline"] = english_data["tagline"]
            
            # 单独获取英文视频信息以获得更多内容
            videos_data = await self._get_videos_data("movie", movie_id)
            if videos_data:
                data["videos"] = videos_data
            
            # 获取评价信息
            reviews_data = await self._get_reviews_data("movie", movie_id)
            if reviews_data:
                data["reviews"] = reviews_data
            
            await cache_manager.save_cache(cache_key, data, subdirectory="movie")
        return data
    
    async def get_movie_recommendations(self, movie_id: int, page: int = 1) -> Optional[Dict]:
        """获取电影推荐"""
        cache_key = f"movie_rec_{movie_id}_{page}"
        cached_data = await cache_manager.load_cache(cache_key, subdirectory="movie")
        if cached_data:
            return cached_data
            
        data = await self._make_tmdb_request(f"movie/{movie_id}/recommendations", {"page": page})
        if data:
            await cache_manager.save_cache(cache_key, data, subdirectory="movie")
        return data
    
    # ========================================
    # 电视剧相关方法
    # ========================================
    
    async def search_tv_shows(self, query: str, page: int = 1) -> Optional[Dict]:
        """搜索电视剧"""
        cache_key = f"tv_search_{query.lower()}_{page}"
        cached_data = await cache_manager.load_cache(cache_key, subdirectory="movie")
        if cached_data:
            return cached_data
            
        data = await self._make_tmdb_request("search/tv", {"query": query, "page": page})
        if data:
            await cache_manager.save_cache(cache_key, data, subdirectory="movie")
        return data
    
    async def get_popular_tv_shows(self, page: int = 1) -> Optional[Dict]:
        """获取热门电视剧"""
        cache_key = f"tv_popular_{page}"
        cached_data = await cache_manager.load_cache(cache_key, subdirectory="movie")
        if cached_data:
            return cached_data
            
        data = await self._make_tmdb_request("tv/popular", {"page": page})
        if data:
            await cache_manager.save_cache(cache_key, data, subdirectory="movie")
        return data
    
    async def get_tv_details(self, tv_id: int) -> Optional[Dict]:
        """获取电视剧详情"""
        cache_key = f"tv_detail_{tv_id}"
        cached_data = await cache_manager.load_cache(cache_key, subdirectory="movie")
        if cached_data:
            return cached_data
            
        # 获取中文详情信息
        data = await self._make_tmdb_request(f"tv/{tv_id}", {
            "append_to_response": "credits,recommendations,watch/providers"
        })
        
        if data:
            # 如果关键字段为空，获取英文信息补充
            if not data.get("overview") or not data.get("tagline"):
                english_data = await self._make_tmdb_request(f"tv/{tv_id}", {
                    "append_to_response": "credits,recommendations,watch/providers"
                }, language="en-US")
                
                if english_data:
                    # 如果中文简介为空，使用英文简介
                    if not data.get("overview") and english_data.get("overview"):
                        data["overview"] = english_data["overview"]
                    
                    # 如果中文标语为空，使用英文标语
                    if not data.get("tagline") and english_data.get("tagline"):
                        data["tagline"] = english_data["tagline"]
            
            # 单独获取英文视频信息以获得更多内容
            videos_data = await self._get_videos_data("tv", tv_id)
            if videos_data:
                data["videos"] = videos_data
            
            # 获取评价信息
            reviews_data = await self._get_reviews_data("tv", tv_id)
            if reviews_data:
                data["reviews"] = reviews_data
            
            await cache_manager.save_cache(cache_key, data, subdirectory="movie")
        return data
    
    async def get_tv_recommendations(self, tv_id: int, page: int = 1) -> Optional[Dict]:
        """获取电视剧推荐"""
        cache_key = f"tv_rec_{tv_id}_{page}"
        cached_data = await cache_manager.load_cache(cache_key, subdirectory="movie")
        if cached_data:
            return cached_data
            
        data = await self._make_tmdb_request(f"tv/{tv_id}/recommendations", {"page": page})
        if data:
            await cache_manager.save_cache(cache_key, data, subdirectory="movie")
        return data
    
    async def get_tv_season_details(self, tv_id: int, season_number: int) -> Optional[Dict]:
        """获取电视剧季详情（支持中英文fallback）"""
        cache_key = f"tv_season_{tv_id}_{season_number}"
        cached_data = await cache_manager.load_cache(cache_key, subdirectory="movie")
        if cached_data:
            return cached_data
            
        # 获取中文季详情信息
        data = await self._make_tmdb_request(f"tv/{tv_id}/season/{season_number}")
        
        if data:
            # 检查剧集的简介是否需要英文补充
            episodes = data.get("episodes", [])
            episodes_need_fallback = []
            
            for episode in episodes:
                if not episode.get("overview"):  # 使用和tv_details相同的简单检查
                    episodes_need_fallback.append(episode.get("episode_number"))
            
            # 如果有剧集需要英文简介补充，或季简介为空，获取英文数据
            if episodes_need_fallback or not data.get("overview"):
                english_data = await self._make_tmdb_request(f"tv/{tv_id}/season/{season_number}", language="en-US")
                
                if english_data:
                    # 如果中文季简介为空，使用英文季简介（和tv_details相同逻辑）
                    if not data.get("overview") and english_data.get("overview"):
                        data["overview"] = english_data["overview"]
                    
                    # 为没有中文简介的剧集补充英文简介
                    english_episodes = english_data.get("episodes", [])
                    english_episodes_dict = {ep.get("episode_number"): ep for ep in english_episodes}
                    
                    for episode in episodes:
                        ep_num = episode.get("episode_number")
                        if ep_num in episodes_need_fallback and ep_num in english_episodes_dict:
                            english_ep = english_episodes_dict[ep_num]
                            # 使用和tv_details相同的逻辑
                            if not episode.get("overview") and english_ep.get("overview"):
                                episode["overview"] = english_ep["overview"]
                            # 也可以补充其他可能为空的字段
                            if not episode.get("name") and english_ep.get("name"):
                                episode["name"] = english_ep["name"]
            
            # 如果季简介仍然为空，尝试使用TV show的简介作为fallback
            if not data.get("overview"):
                tv_data = await self._make_tmdb_request(f"tv/{tv_id}")
                if tv_data and tv_data.get("overview"):
                    data["overview"] = tv_data["overview"]
                else:
                    # 如果中文TV show简介也为空，尝试英文TV show简介
                    tv_data_en = await self._make_tmdb_request(f"tv/{tv_id}", language="en-US")
                    if tv_data_en and tv_data_en.get("overview"):
                        data["overview"] = tv_data_en["overview"]
            
            await cache_manager.save_cache(cache_key, data, subdirectory="movie")
        return data
    
    async def get_tv_episode_details(self, tv_id: int, season_number: int, episode_number: int) -> Optional[Dict]:
        """获取电视剧集详情（支持中英文fallback）"""
        cache_key = f"tv_episode_{tv_id}_{season_number}_{episode_number}"
        cached_data = await cache_manager.load_cache(cache_key, subdirectory="movie")
        if cached_data:
            return cached_data
            
        # 获取中文集详情信息
        data = await self._make_tmdb_request(f"tv/{tv_id}/season/{season_number}/episode/{episode_number}")
        
        if data:
            # 如果关键字段为空，获取英文信息补充（和tv_details相同逻辑）
            if not data.get("overview") or not data.get("name"):
                english_data = await self._make_tmdb_request(f"tv/{tv_id}/season/{season_number}/episode/{episode_number}", language="en-US")
                
                if english_data:
                    # 如果中文简介为空，使用英文简介
                    if not data.get("overview") and english_data.get("overview"):
                        data["overview"] = english_data["overview"]
                    
                    # 如果中文标题为空，使用英文标题
                    if not data.get("name") and english_data.get("name"):
                        data["name"] = english_data["name"]
            
            await cache_manager.save_cache(cache_key, data, subdirectory="movie")
        return data
    
    # ========================================
    # 趋势内容相关方法
    # ========================================
    
    async def get_trending_content(self, media_type: str = "all", time_window: str = "day") -> Optional[Dict]:
        """获取趋势内容
        Args:
            media_type: "all", "movie", "tv", "person"
            time_window: "day", "week"
        """
        cache_key = f"trending_{media_type}_{time_window}"
        cached_data = await cache_manager.load_cache(cache_key, subdirectory="movie")
        if cached_data:
            return cached_data
            
        data = await self._make_tmdb_request(f"trending/{media_type}/{time_window}")
        if data:
            await cache_manager.save_cache(cache_key, data, subdirectory="movie")
        return data
    
    async def get_now_playing_movies(self) -> Optional[Dict]:
        """获取正在上映的电影"""
        cache_key = "now_playing_movies"
        cached_data = await cache_manager.load_cache(cache_key, subdirectory="movie")
        if cached_data:
            return cached_data
            
        data = await self._make_tmdb_request("movie/now_playing")
        if data:
            await cache_manager.save_cache(cache_key, data, subdirectory="movie")
        return data
    
    async def get_upcoming_movies(self) -> Optional[Dict]:
        """获取即将上映的电影"""
        cache_key = "upcoming_movies"
        cached_data = await cache_manager.load_cache(cache_key, subdirectory="movie")
        if cached_data:
            return cached_data
            
        data = await self._make_tmdb_request("movie/upcoming")
        if data:
            await cache_manager.save_cache(cache_key, data, subdirectory="movie")
        return data
    
    async def get_tv_airing_today(self) -> Optional[Dict]:
        """获取今日播出的电视剧"""
        cache_key = "tv_airing_today"
        cached_data = await cache_manager.load_cache(cache_key, subdirectory="movie")
        if cached_data:
            return cached_data
            
        data = await self._make_tmdb_request("tv/airing_today")
        if data:
            await cache_manager.save_cache(cache_key, data, subdirectory="movie")
        return data
    
    async def get_tv_on_the_air(self) -> Optional[Dict]:
        """获取正在播出的电视剧"""
        cache_key = "tv_on_the_air"
        cached_data = await cache_manager.load_cache(cache_key, subdirectory="movie")
        if cached_data:
            return cached_data
            
        data = await self._make_tmdb_request("tv/on_the_air")
        if data:
            await cache_manager.save_cache(cache_key, data, subdirectory="movie")
        return data
    
    # ========================================
    # 人物搜索相关方法
    # ========================================
    
    async def search_person(self, query: str, page: int = 1) -> Optional[Dict]:
        """搜索人物"""
        cache_key = f"person_search_{query.lower()}_{page}"
        cached_data = await cache_manager.load_cache(cache_key, subdirectory="movie")
        if cached_data:
            return cached_data
            
        data = await self._make_tmdb_request("search/person", {"query": query, "page": page})
        if data:
            await cache_manager.save_cache(cache_key, data, subdirectory="movie")
        return data
    
    async def get_person_details(self, person_id: int) -> Optional[Dict]:
        """获取人物详情"""
        cache_key = f"person_detail_{person_id}"
        cached_data = await cache_manager.load_cache(cache_key, subdirectory="movie")
        if cached_data:
            return cached_data
            
        data = await self._make_tmdb_request(f"person/{person_id}", {
            "append_to_response": "movie_credits,tv_credits,combined_credits"
        })
        if data:
            await cache_manager.save_cache(cache_key, data, subdirectory="movie")
        return data
    
    # ========================================
    # 观看平台相关方法
    # ========================================
    
    async def get_movie_watch_providers(self, movie_id: int, region: str = "CN") -> Optional[Dict]:
        """获取电影观看平台信息"""
        cache_key = f"movie_watch_providers_{movie_id}_{region}"
        cached_data = await cache_manager.load_cache(cache_key, subdirectory="movie")
        if cached_data:
            return cached_data
            
        data = await self._make_tmdb_request(f"movie/{movie_id}/watch/providers")
        if data:
            await cache_manager.save_cache(cache_key, data, subdirectory="movie")
        return data
    
    async def get_tv_watch_providers(self, tv_id: int, region: str = "CN") -> Optional[Dict]:
        """获取电视剧观看平台信息"""
        cache_key = f"tv_watch_providers_{tv_id}_{region}"
        cached_data = await cache_manager.load_cache(cache_key, subdirectory="movie")
        if cached_data:
            return cached_data
            
        data = await self._make_tmdb_request(f"tv/{tv_id}/watch/providers")
        if data:
            await cache_manager.save_cache(cache_key, data, subdirectory="movie")
        return data
    
    def _get_first_trailer_url(self, videos_data: Dict) -> Optional[str]:
        """获取第一个预告片的YouTube链接"""
        if not videos_data or not videos_data.get("results"):
            return None
            
        videos = videos_data["results"]
        if not videos:
            return None
            
        # 优先查找官方预告片
        for video in videos:
            if (video.get("type") == "Trailer" and 
                video.get("site") == "YouTube" and 
                video.get("official", True)):  # 优先官方视频
                key = video.get("key")
                if key:
                    return f"https://www.youtube.com/watch?v={key}"
        
        # 如果没有官方预告片，查找任何预告片
        for video in videos:
            if (video.get("type") == "Trailer" and 
                video.get("site") == "YouTube"):
                key = video.get("key")
                if key:
                    return f"https://www.youtube.com/watch?v={key}"
        
        # 如果没有预告片，查找任何视频
        for video in videos:
            if video.get("site") == "YouTube":
                key = video.get("key")
                if key:
                    return f"https://www.youtube.com/watch?v={key}"
        
        return None
    
    def _format_reviews_section(self, reviews_data: Dict) -> str:
        """格式化评价部分"""
        if not reviews_data or not reviews_data.get("results"):
            return ""
        
        reviews = reviews_data["results"][:2]  # 只显示前2个评价
        if not reviews:
            return ""
        
        lines = ["", "📝 *用户评价*:"]
        
        for i, review in enumerate(reviews, 1):
            author = review.get("author", "匿名用户")
            content = review.get("content", "")
            rating = review.get("author_details", {}).get("rating")
            
            if content:
                # 截取评价内容，最多200字符
                content_preview = content[:200] + "..." if len(content) > 200 else content
                # 替换换行符为空格
                content_preview = content_preview.replace('\n', ' ').replace('\r', ' ')
                
                # 简单检测语言（基于字符特征）
                chinese_chars = len([c for c in content if '\u4e00' <= c <= '\u9fff'])
                is_chinese = chinese_chars > len(content) * 0.3  # 如果中文字符超过30%认为是中文
                
                lang_flag = "🇨🇳" if is_chinese else "🇺🇸"
                rating_text = f" ({rating}/10)" if rating else ""
                
                lines.append(f"")
                lines.append(f"👤 *{author}*{rating_text} {lang_flag}:")
                lines.append(f"_{content_preview}_")
        
        return "\n".join(lines) if len(lines) > 2 else ""
    
    async def create_telegraph_page(self, title: str, content: str) -> Optional[str]:
        """创建Telegraph页面"""
        try:
            # 创建Telegraph账户
            account_data = {
                "short_name": "MengBot",
                "author_name": "MengBot Movie Reviews",
                "author_url": "https://t.me/mengpricebot"
            }
            
            response = await httpx_client.post(f"{TELEGRAPH_API_URL}/createAccount", data=account_data)
            if response.status_code != 200:
                return None
                
            account_info = response.json()
            if not account_info.get("ok"):
                return None
                
            access_token = account_info["result"]["access_token"]
            
            # 创建页面内容
            page_content = [
                {
                    "tag": "p",
                    "children": [content]
                }
            ]
            
            page_data = {
                "access_token": access_token,
                "title": title,
                "content": json.dumps(page_content),
                "return_content": "true"
            }
            
            response = await httpx_client.post(f"{TELEGRAPH_API_URL}/createPage", data=page_data)
            if response.status_code != 200:
                return None
                
            page_info = response.json()
            if not page_info.get("ok"):
                return None
                
            return page_info["result"]["url"]
        
        except Exception as e:
            logger.error(f"创建Telegraph页面失败: {e}")
            return None
    
    def format_reviews_for_telegraph(self, reviews_data: Dict, title: str) -> str:
        """将评价格式化为Telegraph友好的格式"""
        if not reviews_data or not reviews_data.get("results"):
            return "暂无评价内容"
        
        reviews = reviews_data["results"]
        content = f"{title} - 用户评价\n\n"
        content += f"共 {len(reviews)} 条评价\n\n"
        
        for i, review in enumerate(reviews, 1):
            author = review.get("author", "匿名用户")
            review_content = review.get("content", "")
            rating = review.get("author_details", {}).get("rating")
            created_at = review.get("created_at", "")
            
            # 简单检测语言
            chinese_chars = len([c for c in review_content if '\u4e00' <= c <= '\u9fff'])
            is_chinese = chinese_chars > len(review_content) * 0.3
            lang_flag = "🇨🇳" if is_chinese else "🇺🇸"
            
            rating_text = f" ({rating}/10)" if rating else ""
            date_text = f" - {created_at[:10]}" if created_at else ""
            
            content += f"=== 评价 {i} ===\n"
            content += f"👤 {author}{rating_text} {lang_flag}{date_text}\n\n"
            content += f"{review_content}\n\n"
            content += "=" * 50 + "\n\n"
        
        return content
    
    def format_reviews_list(self, reviews_data: Dict) -> str:
        """格式化评价列表（智能长度版本）"""
        if not reviews_data or not reviews_data.get("results"):
            return "❌ 暂无用户评价"
        
        reviews = reviews_data["results"][:5]  # 显示前5个评价
        lines = ["📝 *用户评价列表*\n"]
        
        # 计算基础内容长度（标题+评价作者信息等固定部分）
        base_length = len("📝 *用户评价列表*\n\n")
        for i, review in enumerate(reviews, 1):
            author = review.get("author", "匿名用户")
            rating = review.get("author_details", {}).get("rating")
            rating_text = f" ({rating}/10)" if rating else ""
            base_length += len(f"{i}. *{author}*{rating_text} 🇺🇸:\n   __\n\n")
        
        # 计算每条评价可用的平均字符数
        available_chars = 3200 - base_length  # 留800字符余量，为提示信息预留空间
        max_chars_per_review = max(200, available_chars // len(reviews)) if reviews else 200
        
        has_truncated = False  # 标记是否有内容被截断
        
        for i, review in enumerate(reviews, 1):
            author = review.get("author", "匿名用户")
            content = review.get("content", "")
            rating = review.get("author_details", {}).get("rating")
            
            # 简单检测语言
            chinese_chars = len([c for c in content if '\u4e00' <= c <= '\u9fff'])
            is_chinese = chinese_chars > len(content) * 0.3
            lang_flag = "🇨🇳" if is_chinese else "🇺🇸"
            
            # 动态截取评价内容
            if len(content) > max_chars_per_review:
                content_preview = content[:max_chars_per_review] + "..."
                has_truncated = True
            else:
                content_preview = content
            content_preview = content_preview.replace('\n', ' ').replace('\r', ' ')
            
            rating_text = f" ({rating}/10)" if rating else ""
            
            lines.append(f"{i}. *{author}*{rating_text} {lang_flag}:")
            lines.append(f"   _{content_preview}_")
            lines.append("")
        
        # 如果有内容被截断，添加提示信息
        if has_truncated:
            lines.append("📄 *部分评价内容已截断*")
            lines.append("💡 使用相应的 `/movie_reviews <ID>` 或 `/tv_reviews <ID>` 命令可能生成完整的Telegraph页面查看所有评价")
        
        return "\n".join(lines)
    
    def format_movie_search_results(self, search_data: Dict) -> tuple:
        """格式化电影搜索结果，返回(文本内容, 海报URL)"""
        if not search_data or not search_data.get("results"):
            return "❌ 未找到相关电影", None
        
        results = search_data["results"][:10]  # 显示前10个结果
        lines = ["🎬 *电影搜索结果*\n"]
        
        # 获取第一个有海报的电影的海报URL
        poster_url = None
        for movie in results:
            poster_path = movie.get("poster_path")
            if poster_path:
                poster_url = f"{self.tmdb_image_base_url}{poster_path}"
                break
        
        for i, movie in enumerate(results, 1):
            title = movie.get("title", "未知标题")
            original_title = movie.get("original_title", "")
            release_date = movie.get("release_date", "")
            year = release_date[:4] if release_date else "未知年份"
            vote_average = movie.get("vote_average", 0)
            movie_id = movie.get("id")
            poster_path = movie.get("poster_path")
            
            title_text = f"{title}"
            if original_title and original_title != title:
                title_text += f" ({original_title})"
                
            lines.append(f"{i}. *{title_text}* ({year})")
            lines.append(f"   ⭐ 评分: {vote_average:.1f}/10")
            lines.append(f"   🆔 ID: `{movie_id}`")
            if poster_path:
                lines.append(f"   🖼️ 海报: [查看]({self.tmdb_image_base_url}{poster_path})")
            lines.append("")
        
        lines.append("💡 使用 `/movie_detail <ID>` 查看详细信息")
        lines.append("💡 使用 `/movie_rec <ID>` 获取相似推荐")
        
        return "\n".join(lines), poster_url

    # ========================================
    # 电视剧格式化方法
    # ========================================
    
    def format_tv_search_results(self, search_data: Dict) -> tuple:
        """格式化电视剧搜索结果，返回(文本内容, 海报URL)"""
        if not search_data or not search_data.get("results"):
            return "❌ 未找到相关电视剧", None
        
        results = search_data["results"][:10]  # 显示前10个结果
        lines = ["📺 *电视剧搜索结果*\n"]
        
        # 获取第一个有海报的电视剧的海报URL
        poster_url = None
        for tv in results:
            poster_path = tv.get("poster_path")
            if poster_path:
                poster_url = f"{self.tmdb_image_base_url}{poster_path}"
                break
        
        for i, tv in enumerate(results, 1):
            name = tv.get("name", "未知标题")
            original_name = tv.get("original_name", "")
            first_air_date = tv.get("first_air_date", "")
            year = first_air_date[:4] if first_air_date else "未知年份"
            vote_average = tv.get("vote_average", 0)
            tv_id = tv.get("id")
            poster_path = tv.get("poster_path")
            
            title_text = f"{name}"
            if original_name and original_name != name:
                title_text += f" ({original_name})"
                
            lines.append(f"{i}. *{title_text}* ({year})")
            lines.append(f"   ⭐ 评分: {vote_average:.1f}/10")
            lines.append(f"   🆔 ID: `{tv_id}`")
            if poster_path:
                lines.append(f"   🖼️ 海报: [查看]({self.tmdb_image_base_url}{poster_path})")
            lines.append("")
        
        lines.append("💡 使用 `/tv_detail <ID>` 查看详细信息")
        lines.append("💡 使用 `/tv_rec <ID>` 获取相似推荐")
        
        return "\n".join(lines), poster_url
    
    def format_popular_tv_shows(self, popular_data: Dict) -> str:
        """格式化热门电视剧列表"""
        if not popular_data or not popular_data.get("results"):
            return "❌ 获取热门电视剧失败"
        
        results = popular_data["results"][:15]  # 显示前15个结果
        lines = ["🔥 *当前热门电视剧*\n"]
        
        for i, tv in enumerate(results, 1):
            name = tv.get("name", "未知标题")
            first_air_date = tv.get("first_air_date", "")
            year = first_air_date[:4] if first_air_date else ""
            vote_average = tv.get("vote_average", 0)
            tv_id = tv.get("id")
            
            # 排名图标
            if i <= 3:
                rank_icons = ["🥇", "🥈", "🥉"]
                rank = rank_icons[i-1]
            else:
                rank = f"{i}."
            
            year_text = f" ({year})" if year else ""
            lines.append(f"{rank} *{name}*{year_text}")
            lines.append(f"     ⭐ {vote_average:.1f}/10 | 🆔 `{tv_id}`")
            lines.append("")
        
        lines.append("💡 使用 `/tv_detail <ID>` 查看详细信息")
        lines.append("💡 使用 `/tv_rec <ID>` 获取相似推荐")
        lines.append("💡 使用 `/tv_videos <ID>` 查看预告片")
        
        return "\n".join(lines)
    
    def format_tv_details(self, detail_data: Dict) -> tuple:
        """格式化电视剧详情，返回(文本内容, 海报URL)"""
        if not detail_data:
            return "❌ 获取电视剧详情失败", None
        
        name = detail_data.get("name", "未知标题")
        original_name = detail_data.get("original_name", "")
        tagline = detail_data.get("tagline", "")
        overview = detail_data.get("overview", "暂无简介")
        first_air_date = detail_data.get("first_air_date", "")
        last_air_date = detail_data.get("last_air_date", "")
        number_of_seasons = detail_data.get("number_of_seasons", 0)
        number_of_episodes = detail_data.get("number_of_episodes", 0)
        episode_run_time = detail_data.get("episode_run_time", [])
        vote_average = detail_data.get("vote_average", 0)
        vote_count = detail_data.get("vote_count", 0)
        status = detail_data.get("status", "未知")
        poster_path = detail_data.get("poster_path")
        
        # 构建海报URL
        poster_url = f"{self.tmdb_image_base_url}{poster_path}" if poster_path else None
        
        # 状态翻译
        status_map = {
            "Returning Series": "更新中",
            "Ended": "已完结", 
            "Canceled": "已取消",
            "In Production": "制作中",
            "Pilot": "试播",
            "Planned": "计划中"
        }
        status_cn = status_map.get(status, status)
        
        # 类型
        genres = [g["name"] for g in detail_data.get("genres", [])]
        genre_text = " | ".join(genres) if genres else "未知"
        
        # 制作公司
        companies = [c["name"] for c in detail_data.get("production_companies", [])]
        company_text = ", ".join(companies[:3]) if companies else "未知"
        
        # 播放网络
        networks = [n["name"] for n in detail_data.get("networks", [])]
        network_text = ", ".join(networks[:3]) if networks else "未知"
        
        # 演员阵容
        cast_info = ""
        if detail_data.get("credits") and detail_data["credits"].get("cast"):
            main_cast = detail_data["credits"]["cast"][:5]
            cast_names = [actor["name"] for actor in main_cast]
            cast_info = f"\n🎭 *主要演员*: {', '.join(cast_names)}"
        
        # 创作者信息
        creator_info = ""
        if detail_data.get("created_by"):
            creators = [creator["name"] for creator in detail_data["created_by"]]
            if creators:
                creator_info = f"\n🎬 *创作者*: {', '.join(creators)}"
        
        # 单集时长
        runtime_text = ""
        if episode_run_time:
            if len(episode_run_time) == 1:
                runtime_text = f"{episode_run_time[0]}分钟"
            else:
                runtime_text = f"{min(episode_run_time)}-{max(episode_run_time)}分钟"
        else:
            runtime_text = "未知"
        
        lines = [
            f"📺 *{name}*",
        ]
        
        if original_name and original_name != name:
            lines.append(f"🏷️ *原名*: {original_name}")
            
        if tagline:
            lines.append(f"💭 *标语*: _{tagline}_")
            
        lines.extend([
            f"",
            f"📅 *首播日期*: {first_air_date or '未知'}",
            f"📅 *最后播出*: {last_air_date or '未知'}" if last_air_date else "",
            f"📊 *状态*: {status_cn}",
            f"📚 *季数*: {number_of_seasons}季 | *总集数*: {number_of_episodes}集",
            f"⏱️ *单集时长*: {runtime_text}",
            f"🎭 *类型*: {genre_text}",
            f"⭐ *评分*: {vote_average:.1f}/10 ({vote_count:,}人评价)",
            f"📺 *播出网络*: {network_text}",
            f"🏢 *制作公司*: {company_text}",
        ])
        
        if poster_url:
            lines.append(f"🖼️ *海报*: [查看]({poster_url})")
        
        # 添加预告片链接
        videos_data = detail_data.get("videos")
        if videos_data:
            trailer_url = self._get_first_trailer_url(videos_data)
            if trailer_url:
                lines.append(f"🎬 *预告片*: [观看]({trailer_url})")
        
        # 添加观看平台信息
        watch_providers = detail_data.get("watch/providers")
        if watch_providers:
            provider_info = self.format_watch_providers_compact(watch_providers, "tv")
            if provider_info:
                lines.append(provider_info)
            
        lines.extend([
            creator_info,
            cast_info,
            f"",
            f"📖 *剧情简介*:",
            f"{overview[:500]}{'...' if len(overview) > 500 else ''}",
        ])
        
        # 添加用户评价
        reviews_data = detail_data.get("reviews")
        if reviews_data:
            reviews_section = self._format_reviews_section(reviews_data)
            if reviews_section:
                lines.append(reviews_section)
        
        # 添加操作提示
        tv_id = detail_data.get("id")
        lines.extend([
            f"",
            f"💡 使用 `/tv_rec {tv_id}` 获取相似推荐",
            f"💡 使用 `/tv_videos {tv_id}` 查看预告片",
            f"💡 使用 `/tv_reviews {tv_id}` 查看用户评价",
            f"💡 使用 `/tv_season {tv_id} <季数>` 查看季详情",
            f"💡 使用 `/tv_watch {tv_id}` 查看完整观看平台"
        ])
        
        return "\n".join(filter(None, lines)), poster_url  # 过滤空行
    
    def format_tv_recommendations(self, rec_data: Dict, original_tv_id: int) -> str:
        """格式化电视剧推荐"""
        if not rec_data or not rec_data.get("results"):
            return "❌ 暂无相关推荐"
        
        results = rec_data["results"][:10]
        lines = [f"💡 *基于电视剧ID {original_tv_id} 的推荐*\n"]
        
        for i, tv in enumerate(results, 1):
            name = tv.get("name", "未知标题")
            first_air_date = tv.get("first_air_date", "")
            year = first_air_date[:4] if first_air_date else ""
            vote_average = tv.get("vote_average", 0)
            tv_id = tv.get("id")
            
            year_text = f" ({year})" if year else ""
            lines.append(f"{i}. *{name}*{year_text}")
            lines.append(f"   ⭐ {vote_average:.1f}/10 | 🆔 `{tv_id}`")
            lines.append("")
        
        lines.append("💡 使用 `/tv_detail <ID>` 查看详细信息")
        
        return "\n".join(lines)
    
    def format_tv_season_details(self, season_data: Dict, tv_id: int) -> str:
        """格式化电视剧季详情（智能长度版本）"""
        if not season_data:
            return "❌ 获取季详情失败"
        
        name = season_data.get("name", "未知季")
        season_number = season_data.get("season_number", 0)
        air_date = season_data.get("air_date", "")
        episode_count = season_data.get("episode_count", 0)
        overview = season_data.get("overview", "暂无简介")
        
        lines = [
            f"📺 *{name}* (第{season_number}季)",
            f"",
            f"📅 *播出日期*: {air_date or '未知'}",
            f"📚 *集数*: {episode_count}集",
            f"",
            f"📖 *简介*:",
            f"{overview[:300]}{'...' if len(overview) > 300 else ''}" if overview != "暂无简介" else "暂无简介",
        ]
        
        episodes = season_data.get("episodes", [])
        if episodes:
            lines.extend([
                f"",
                f"📋 *剧集列表*:",
                f""
            ])
            
            # 计算基础内容长度（标题+简介等固定部分）
            base_length = len("\n".join(lines))
            base_length += len(f"\n\n💡 使用 `/tv_episode {tv_id} {season_number} <集数>` 查看集详情")
            
            # 计算每集可用的平均字符数
            available_chars = 3200 - base_length  # 留800字符余量
            if len(episodes) > 0:
                max_chars_per_episode = max(100, available_chars // len(episodes))
            else:
                max_chars_per_episode = 200
            
            has_truncated = False
            episode_lines = []
            
            for ep in episodes:
                ep_num = ep.get("episode_number", 0)
                ep_name = ep.get("name", f"第{ep_num}集")
                ep_date = ep.get("air_date", "")
                ep_runtime = ep.get("runtime", 0)
                ep_overview = ep.get("overview", "")
                
                # 构建每集的信息
                episode_info = [f"{ep_num}. *{ep_name}*"]
                if ep_date:
                    episode_info.append(f"   📅 {ep_date}")
                if ep_runtime:
                    episode_info.append(f"   ⏱️ {ep_runtime}分钟")
                
                # 如果有剧情简介，动态截取
                if ep_overview:
                    if len(ep_overview) > max_chars_per_episode:
                        ep_overview_preview = ep_overview[:max_chars_per_episode] + "..."
                        has_truncated = True
                    else:
                        ep_overview_preview = ep_overview
                    ep_overview_preview = ep_overview_preview.replace('\n', ' ').replace('\r', ' ')
                    episode_info.append(f"   📝 _{ep_overview_preview}_")
                
                episode_info.append("")
                episode_lines.extend(episode_info)
            
            lines.extend(episode_lines)
            
            # 如果有内容被截断，添加提示信息
            if has_truncated:
                lines.extend([
                    "📄 *部分剧集简介已截断*",
                    f"💡 使用 `/tv_season_full {tv_id} {season_number}` 查看完整剧集列表"
                ])
        
        lines.extend([
            f"",
            f"💡 使用 `/tv_episode {tv_id} {season_number} <集数>` 查看集详情"
        ])
        
        return "\n".join(filter(None, lines))
    
    
    def format_season_episodes_for_telegraph(self, season_data: Dict, tv_id: int) -> str:
        """将剧集列表格式化为Telegraph友好的格式"""
        if not season_data:
            return "暂无剧集信息"
        
        name = season_data.get("name", "未知季")
        season_number = season_data.get("season_number", 0)
        episodes = season_data.get("episodes", [])
        
        content = f"{name} (第{season_number}季) - 完整剧集列表\n\n"
        content += f"共 {len(episodes)} 集\n\n"
        
        for ep in episodes:
            ep_num = ep.get("episode_number", 0)
            ep_name = ep.get("name", f"第{ep_num}集")
            ep_date = ep.get("air_date", "")
            ep_runtime = ep.get("runtime", 0)
            ep_overview = ep.get("overview", "")
            vote_average = ep.get("vote_average", 0)
            vote_count = ep.get("vote_count", 0)
            
            content += f"=== 第{ep_num}集：{ep_name} ===\n"
            if ep_date:
                content += f"📅 播出日期：{ep_date}\n"
            if ep_runtime:
                content += f"⏱️ 时长：{ep_runtime}分钟\n"
            if vote_count > 0:
                content += f"⭐ 评分：{vote_average:.1f}/10 ({vote_count}人评价)\n"
            
            if ep_overview:
                content += f"\n📝 剧情简介：\n{ep_overview}\n"
            
            content += "\n" + "=" * 50 + "\n\n"
        
        content += f"💡 使用 /tv_episode {tv_id} {season_number} <集数> 查看更多集详情"
        return content
    
    def format_tv_episode_details(self, episode_data: Dict, tv_id: int, season_number: int) -> str:
        """格式化电视剧集详情"""
        if not episode_data:
            return "❌ 获取集详情失败"
        
        name = episode_data.get("name", "未知集")
        episode_number = episode_data.get("episode_number", 0)
        air_date = episode_data.get("air_date", "")
        runtime = episode_data.get("runtime", 0)
        vote_average = episode_data.get("vote_average", 0)
        vote_count = episode_data.get("vote_count", 0)
        overview = episode_data.get("overview", "暂无简介")
        
        lines = [
            f"📺 *{name}*",
            f"🏷️ 第{season_number}季 第{episode_number}集",
            f"",
            f"📅 *播出日期*: {air_date or '未知'}",
            f"⏱️ *时长*: {runtime}分钟" if runtime else "⏱️ *时长*: 未知",
            f"⭐ *评分*: {vote_average:.1f}/10 ({vote_count}人评价)" if vote_count > 0 else "⭐ *评分*: 暂无评分",
            f"",
            f"📖 *剧情简介*:",
            f"{overview[:400]}{'...' if len(overview) > 400 else ''}" if overview != "暂无简介" else "暂无简介",
        ]
        
        # 演员信息
        if episode_data.get("guest_stars"):
            guest_stars = [star["name"] for star in episode_data["guest_stars"][:3]]
            if guest_stars:
                lines.extend([
                    f"",
                    f"🌟 *特邀演员*: {', '.join(guest_stars)}"
                ])
        
        lines.extend([
            f"",
            f"💡 使用 `/tv_season {tv_id} {season_number}` 查看整季信息"
        ])
        
        return "\n".join(filter(None, lines))
    
    def format_popular_movies(self, popular_data: Dict) -> str:
        """格式化热门电影列表"""
        if not popular_data or not popular_data.get("results"):
            return "❌ 获取热门电影失败"
        
        results = popular_data["results"][:15]  # 显示前15个结果
        lines = ["🔥 *当前热门电影*\n"]
        
        for i, movie in enumerate(results, 1):
            title = movie.get("title", "未知标题")
            release_date = movie.get("release_date", "")
            year = release_date[:4] if release_date else ""
            vote_average = movie.get("vote_average", 0)
            movie_id = movie.get("id")
            
            # 排名图标
            if i <= 3:
                rank_icons = ["🥇", "🥈", "🥉"]
                rank = rank_icons[i-1]
            else:
                rank = f"{i}."
            
            year_text = f" ({year})" if year else ""
            lines.append(f"{rank} *{title}*{year_text}")
            lines.append(f"     ⭐ {vote_average:.1f}/10 | 🆔 `{movie_id}`")
            lines.append("")
        
        lines.append("💡 使用 `/movie_detail <ID>` 查看详细信息")
        lines.append("💡 使用 `/movie_rec <ID>` 获取相似推荐")
        lines.append("💡 使用 `/movie_videos <ID>` 查看预告片")
        
        return "\n".join(lines)
    
    def format_movie_details(self, detail_data: Dict) -> tuple:
        """格式化电影详情，返回(文本内容, 海报URL)"""
        if not detail_data:
            return "❌ 获取电影详情失败", None
        
        title = detail_data.get("title", "未知标题")
        original_title = detail_data.get("original_title", "")
        tagline = detail_data.get("tagline", "")
        overview = detail_data.get("overview", "暂无简介")
        release_date = detail_data.get("release_date", "")
        runtime = detail_data.get("runtime", 0)
        vote_average = detail_data.get("vote_average", 0)
        vote_count = detail_data.get("vote_count", 0)
        budget = detail_data.get("budget", 0)
        revenue = detail_data.get("revenue", 0)
        poster_path = detail_data.get("poster_path")
        
        # 构建海报URL
        poster_url = f"{self.tmdb_image_base_url}{poster_path}" if poster_path else None
        
        # 类型
        genres = [g["name"] for g in detail_data.get("genres", [])]
        genre_text = " | ".join(genres) if genres else "未知"
        
        # 制作公司
        companies = [c["name"] for c in detail_data.get("production_companies", [])]
        company_text = ", ".join(companies[:3]) if companies else "未知"
        
        # 演员阵容
        cast_info = ""
        if detail_data.get("credits") and detail_data["credits"].get("cast"):
            main_cast = detail_data["credits"]["cast"][:5]
            cast_names = [actor["name"] for actor in main_cast]
            cast_info = f"\n🎭 *主要演员*: {', '.join(cast_names)}"
        
        # 导演信息
        director_info = ""
        if detail_data.get("credits") and detail_data["credits"].get("crew"):
            directors = [crew["name"] for crew in detail_data["credits"]["crew"] if crew["job"] == "Director"]
            if directors:
                director_info = f"\n🎬 *导演*: {', '.join(directors)}"
        
        lines = [
            f"🎬 *{title}*",
        ]
        
        if original_title and original_title != title:
            lines.append(f"🏷️ *原名*: {original_title}")
            
        if tagline:
            lines.append(f"💭 *标语*: _{tagline}_")
            
        lines.extend([
            f"",
            f"📅 *上映日期*: {release_date or '未知'}",
            f"⏱️ *片长*: {runtime}分钟" if runtime else "⏱️ *片长*: 未知",
            f"🎭 *类型*: {genre_text}",
            f"⭐ *评分*: {vote_average:.1f}/10 ({vote_count:,}人评价)",
            f"🏢 *制作公司*: {company_text}",
        ])
        
        if budget > 0:
            lines.append(f"💰 *制作成本*: ${budget:,}")
        if revenue > 0:
            lines.append(f"💵 *票房收入*: ${revenue:,}")
            
        if poster_url:
            lines.append(f"🖼️ *海报*: [查看]({poster_url})")
        
        # 添加预告片链接
        videos_data = detail_data.get("videos")
        if videos_data:
            trailer_url = self._get_first_trailer_url(videos_data)
            if trailer_url:
                lines.append(f"🎬 *预告片*: [观看]({trailer_url})")
        
        # 添加观看平台信息
        watch_providers = detail_data.get("watch/providers")
        if watch_providers:
            provider_info = self.format_watch_providers_compact(watch_providers, "movie")
            if provider_info:
                lines.append(provider_info)
            
        lines.extend([
            director_info,
            cast_info,
            f"",
            f"📖 *剧情简介*:",
            f"{overview[:500]}{'...' if len(overview) > 500 else ''}",
        ])
        
        # 添加用户评价
        reviews_data = detail_data.get("reviews")
        if reviews_data:
            reviews_section = self._format_reviews_section(reviews_data)
            if reviews_section:
                lines.append(reviews_section)
        
        # 添加操作提示
        movie_id = detail_data.get("id")
        lines.extend([
            f"",
            f"💡 使用 `/movie_rec {movie_id}` 获取相似推荐",
            f"💡 使用 `/movie_videos {movie_id}` 查看预告片",
            f"💡 使用 `/movie_reviews {movie_id}` 查看用户评价",
            f"💡 使用 `/movie_watch {movie_id}` 查看完整观看平台"
        ])
        
        return "\n".join(filter(None, lines)), poster_url  # 过滤空行
    
    def format_movie_recommendations(self, rec_data: Dict, original_movie_id: int) -> str:
        """格式化电影推荐"""
        if not rec_data or not rec_data.get("results"):
            return "❌ 暂无相关推荐"
        
        results = rec_data["results"][:10]
        lines = [f"💡 *基于电影ID {original_movie_id} 的推荐*\n"]
        
        for i, movie in enumerate(results, 1):
            title = movie.get("title", "未知标题")
            release_date = movie.get("release_date", "")
            year = release_date[:4] if release_date else ""
            vote_average = movie.get("vote_average", 0)
            movie_id = movie.get("id")
            
            year_text = f" ({year})" if year else ""
            lines.append(f"{i}. *{title}*{year_text}")
            lines.append(f"   ⭐ {vote_average:.1f}/10 | 🆔 `{movie_id}`")
            lines.append("")
        
        lines.append("💡 使用 `/movie_detail <ID>` 查看详细信息")
        
        return "\n".join(lines)
    
    def format_movie_videos(self, videos_data: Dict) -> str:
        """格式化电影视频信息"""
        if not videos_data or not videos_data.get("results"):
            return "❌ 暂无视频内容"
        
        videos = videos_data["results"]
        if not videos:
            return "❌ 暂无视频内容"
        
        lines = ["🎬 *相关视频*\n"]
        
        # 按类型分组显示
        trailers = [v for v in videos if v.get("type") == "Trailer"]
        teasers = [v for v in videos if v.get("type") == "Teaser"]
        clips = [v for v in videos if v.get("type") == "Clip"]
        featurettes = [v for v in videos if v.get("type") == "Featurette"]
        
        def add_videos(video_list, title, emoji):
            if video_list:
                lines.append(f"{emoji} *{title}*:")
                for video in video_list[:3]:  # 每类最多显示3个
                    name = video.get("name", "未知")
                    site = video.get("site", "")
                    key = video.get("key", "")
                    
                    if site == "YouTube" and key:
                        url = f"https://www.youtube.com/watch?v={key}"
                        # 将方括号替换为圆括号，避免Markdown冲突
                        safe_name = name.replace('[', '(').replace(']', ')')
                        lines.append(f"   🎥 [{safe_name}]({url})")
                    else:
                        lines.append(f"   🎥 {name} ({site})")
                lines.append("")
        
        add_videos(trailers, "预告片", "🎬")
        add_videos(teasers, "先导预告", "👀")
        add_videos(clips, "片段", "📹")
        add_videos(featurettes, "幕后花絮", "🎭")
        
        if not any([trailers, teasers, clips, featurettes]):
            return "❌ 暂无可用视频内容"
        
        return "\n".join(lines).rstrip()
    
    def format_tv_videos(self, videos_data: Dict) -> str:
        """格式化电视剧视频信息"""
        if not videos_data or not videos_data.get("results"):
            return "❌ 暂无视频内容"
        
        videos = videos_data["results"]
        if not videos:
            return "❌ 暂无视频内容"
        
        lines = ["📺 *相关视频*\n"]
        
        # 按类型分组显示
        trailers = [v for v in videos if v.get("type") == "Trailer"]
        teasers = [v for v in videos if v.get("type") == "Teaser"]
        clips = [v for v in videos if v.get("type") == "Clip"]
        behind_scenes = [v for v in videos if v.get("type") == "Behind the Scenes"]
        
        def add_videos(video_list, title, emoji):
            if video_list:
                lines.append(f"{emoji} *{title}*:")
                for video in video_list[:3]:  # 每类最多显示3个
                    name = video.get("name", "未知")
                    site = video.get("site", "")
                    key = video.get("key", "")
                    
                    if site == "YouTube" and key:
                        url = f"https://www.youtube.com/watch?v={key}"
                        # 将方括号替换为圆括号，避免Markdown冲突
                        safe_name = name.replace('[', '(').replace(']', ')')
                        lines.append(f"   📺 [{safe_name}]({url})")
                    else:
                        lines.append(f"   📺 {name} ({site})")
                lines.append("")
        
        add_videos(trailers, "预告片", "🎬")
        add_videos(teasers, "先导预告", "👀")
        add_videos(clips, "片段", "📹")
        add_videos(behind_scenes, "幕后花絮", "🎭")
        
        if not any([trailers, teasers, clips, behind_scenes]):
            return "❌ 暂无可用视频内容"
        
        return "\n".join(lines).rstrip()

    # ========================================
    # 趋势内容格式化方法
    # ========================================
    
    def format_trending_content(self, trending_data: Dict, time_window: str = "day") -> str:
        """格式化趋势内容"""
        if not trending_data or not trending_data.get("results"):
            return "❌ 获取趋势内容失败"
        
        results = trending_data["results"][:15]  # 显示前15个结果
        time_text = "今日" if time_window == "day" else "本周"
        lines = [f"🔥 *{time_text}热门内容*\n"]
        
        for i, item in enumerate(results, 1):
            # 判断是电影还是电视剧
            media_type = item.get("media_type", "unknown")
            
            if media_type == "movie":
                title = item.get("title", "未知标题")
                release_date = item.get("release_date", "")
                year = release_date[:4] if release_date else ""
                emoji = "🎬"
            elif media_type == "tv":
                title = item.get("name", "未知标题")
                first_air_date = item.get("first_air_date", "")
                year = first_air_date[:4] if first_air_date else ""
                emoji = "📺"
            elif media_type == "person":
                title = item.get("name", "未知人物")
                year = ""
                emoji = "👤"
            else:
                continue  # 跳过未知类型
            
            vote_average = item.get("vote_average", 0)
            item_id = item.get("id")
            
            # 排名图标
            if i <= 3:
                rank_icons = ["🥇", "🥈", "🥉"]
                rank = rank_icons[i-1]
            else:
                rank = f"{i}."
            
            year_text = f" ({year})" if year else ""
            lines.append(f"{rank} {emoji} *{title}*{year_text}")
            
            if media_type != "person":
                lines.append(f"     ⭐ {vote_average:.1f}/10 | 🆔 `{item_id}`")
            else:
                lines.append(f"     👤 人物 | 🆔 `{item_id}`")
            lines.append("")
        
        lines.append("💡 使用命令查看详细信息：")
        lines.append("   🎬 电影: `/movie_detail <ID>`")
        lines.append("   📺 电视剧: `/tv_detail <ID>`")
        lines.append("   👤 人物: `/person_detail <ID>`")
        
        return "\n".join(lines)
    
    def format_now_playing_movies(self, playing_data: Dict) -> str:
        """格式化正在上映的电影"""
        if not playing_data or not playing_data.get("results"):
            return "❌ 获取正在上映电影失败"
        
        results = playing_data["results"][:15]  # 显示前15个结果
        lines = ["🎭 *正在上映的电影*\n"]
        
        for i, movie in enumerate(results, 1):
            title = movie.get("title", "未知标题")
            release_date = movie.get("release_date", "")
            year = release_date[:4] if release_date else ""
            vote_average = movie.get("vote_average", 0)
            movie_id = movie.get("id")
            
            year_text = f" ({year})" if year else ""
            lines.append(f"{i}. *{title}*{year_text}")
            lines.append(f"   ⭐ {vote_average:.1f}/10 | 🆔 `{movie_id}`")
            lines.append("")
        
        lines.append("💡 使用 `/movie_detail <ID>` 查看详细信息")
        lines.append("💡 使用 `/movie_videos <ID>` 查看预告片")
        
        return "\n".join(lines)
    
    def format_upcoming_movies(self, upcoming_data: Dict) -> str:
        """格式化即将上映的电影"""
        if not upcoming_data or not upcoming_data.get("results"):
            return "❌ 获取即将上映电影失败"
        
        results = upcoming_data["results"][:15]  # 显示前15个结果
        lines = ["🗓️ *即将上映的电影*\n"]
        
        for i, movie in enumerate(results, 1):
            title = movie.get("title", "未知标题")
            release_date = movie.get("release_date", "")
            vote_average = movie.get("vote_average", 0)
            movie_id = movie.get("id")
            
            release_text = f" (上映: {release_date})" if release_date else ""
            lines.append(f"{i}. *{title}*{release_text}")
            
            if vote_average > 0:
                lines.append(f"   ⭐ {vote_average:.1f}/10 | 🆔 `{movie_id}`")
            else:
                lines.append(f"   🆔 `{movie_id}`")
            lines.append("")
        
        lines.append("💡 使用 `/movie_detail <ID>` 查看详细信息")
        lines.append("💡 使用 `/movie_videos <ID>` 查看预告片")
        
        return "\n".join(lines)
    
    def format_tv_airing_today(self, airing_data: Dict) -> str:
        """格式化今日播出的电视剧"""
        if not airing_data or not airing_data.get("results"):
            return "❌ 获取今日播出电视剧失败"
        
        results = airing_data["results"][:15]  # 显示前15个结果
        lines = ["📅 *今日播出的电视剧*\n"]
        
        for i, tv in enumerate(results, 1):
            name = tv.get("name", "未知标题")
            first_air_date = tv.get("first_air_date", "")
            year = first_air_date[:4] if first_air_date else ""
            vote_average = tv.get("vote_average", 0)
            tv_id = tv.get("id")
            
            year_text = f" ({year})" if year else ""
            lines.append(f"{i}. *{name}*{year_text}")
            lines.append(f"   ⭐ {vote_average:.1f}/10 | 🆔 `{tv_id}`")
            lines.append("")
        
        lines.append("💡 使用 `/tv_detail <ID>` 查看详细信息")
        lines.append("💡 使用 `/tv_videos <ID>` 查看预告片")
        
        return "\n".join(lines)
    
    def format_tv_on_the_air(self, on_air_data: Dict) -> str:
        """格式化正在播出的电视剧"""
        if not on_air_data or not on_air_data.get("results"):
            return "❌ 获取正在播出电视剧失败"
        
        results = on_air_data["results"][:15]  # 显示前15个结果
        lines = ["📺 *正在播出的电视剧*\n"]
        
        for i, tv in enumerate(results, 1):
            name = tv.get("name", "未知标题")
            first_air_date = tv.get("first_air_date", "")
            year = first_air_date[:4] if first_air_date else ""
            vote_average = tv.get("vote_average", 0)
            tv_id = tv.get("id")
            
            year_text = f" ({year})" if year else ""
            lines.append(f"{i}. *{name}*{year_text}")
            lines.append(f"   ⭐ {vote_average:.1f}/10 | 🆔 `{tv_id}`")
            lines.append("")
        
        lines.append("💡 使用 `/tv_detail <ID>` 查看详细信息")
        lines.append("💡 使用 `/tv_videos <ID>` 查看预告片")
        
        return "\n".join(lines)

    # ========================================
    # 人物搜索格式化方法
    # ========================================
    
    def format_person_search_results(self, search_data: Dict) -> tuple:
        """格式化人物搜索结果，返回(文本内容, 头像URL)"""
        if not search_data or not search_data.get("results"):
            return "❌ 未找到相关人物", None
        
        results = search_data["results"][:10]  # 显示前10个结果
        lines = ["👤 *人物搜索结果*\n"]
        
        # 获取第一个有头像的人物的头像URL
        profile_url = None
        for person in results:
            profile_path = person.get("profile_path")
            if profile_path:
                profile_url = f"{self.tmdb_image_base_url}{profile_path}"
                break
        
        for i, person in enumerate(results, 1):
            name = person.get("name", "未知姓名")
            known_for_department = person.get("known_for_department", "")
            person_id = person.get("id")
            profile_path = person.get("profile_path")
            
            # 职业映射
            department_map = {
                "Acting": "演员",
                "Directing": "导演", 
                "Writing": "编剧",
                "Production": "制片",
                "Camera": "摄影",
                "Editing": "剪辑",
                "Sound": "音效",
                "Art": "美术",
                "Costume & Make-Up": "化妆造型"
            }
            department_cn = department_map.get(known_for_department, known_for_department)
            
            lines.append(f"{i}. *{name}*")
            if department_cn:
                lines.append(f"   🎭 职业: {department_cn}")
            lines.append(f"   🆔 ID: `{person_id}`")
            
            if profile_path:
                lines.append(f"   📸 头像: [查看]({self.tmdb_image_base_url}{profile_path})")
            
            # 显示知名作品
            known_for = person.get("known_for", [])
            if known_for:
                known_titles = []
                for work in known_for[:3]:  # 最多显示3个作品
                    if work.get("media_type") == "movie":
                        known_titles.append(work.get("title", ""))
                    elif work.get("media_type") == "tv":
                        known_titles.append(work.get("name", ""))
                
                if known_titles:
                    lines.append(f"   🌟 知名作品: {', '.join(filter(None, known_titles))}")
            
            lines.append("")
        
        lines.append("💡 使用 `/person_detail <ID>` 查看详细信息")
        
        return "\n".join(lines), profile_url
    
    def format_person_details(self, detail_data: Dict) -> tuple:
        """格式化人物详情，返回(文本内容, 头像URL)"""
        if not detail_data:
            return "❌ 获取人物详情失败", None
        
        name = detail_data.get("name", "未知姓名")
        biography = detail_data.get("biography", "暂无简介")
        birthday = detail_data.get("birthday", "")
        deathday = detail_data.get("deathday", "")
        place_of_birth = detail_data.get("place_of_birth", "")
        known_for_department = detail_data.get("known_for_department", "")
        profile_path = detail_data.get("profile_path")
        popularity = detail_data.get("popularity", 0)
        
        # 构建头像URL
        profile_url = f"{self.tmdb_image_base_url}{profile_path}" if profile_path else None
        
        # 职业映射
        department_map = {
            "Acting": "演员",
            "Directing": "导演", 
            "Writing": "编剧",
            "Production": "制片",
            "Camera": "摄影",
            "Editing": "剪辑",
            "Sound": "音效",
            "Art": "美术",
            "Costume & Make-Up": "化妆造型"
        }
        department_cn = department_map.get(known_for_department, known_for_department)
        
        lines = [
            f"👤 *{name}*",
            f""
        ]
        
        if department_cn:
            lines.append(f"🎭 *主要职业*: {department_cn}")
            
        if birthday:
            lines.append(f"🎂 *出生日期*: {birthday}")
        if deathday:
            lines.append(f"💀 *去世日期*: {deathday}")
        if place_of_birth:
            lines.append(f"🌍 *出生地*: {place_of_birth}")
            
        lines.append(f"⭐ *人气指数*: {popularity:.1f}")
        
        if profile_url:
            lines.append(f"📸 *头像*: [查看]({profile_url})")
        
        # 电影作品
        movie_credits = detail_data.get("movie_credits", {})
        if movie_credits and movie_credits.get("cast"):
            movie_cast = movie_credits["cast"][:5]  # 显示前5部电影
            if movie_cast:
                lines.extend([
                    f"",
                    f"🎬 *主要电影作品*:"
                ])
                for movie in movie_cast:
                    title = movie.get("title", "未知")
                    release_date = movie.get("release_date", "")
                    year = release_date[:4] if release_date else ""
                    character = movie.get("character", "")
                    year_text = f" ({year})" if year else ""
                    character_text = f" 饰演 {character}" if character else ""
                    lines.append(f"   • {title}{year_text}{character_text}")
        
        # 电视剧作品
        tv_credits = detail_data.get("tv_credits", {})
        if tv_credits and tv_credits.get("cast"):
            tv_cast = tv_credits["cast"][:5]  # 显示前5部电视剧
            if tv_cast:
                lines.extend([
                    f"",
                    f"📺 *主要电视剧作品*:"
                ])
                for tv in tv_cast:
                    name_tv = tv.get("name", "未知")
                    first_air_date = tv.get("first_air_date", "")
                    year = first_air_date[:4] if first_air_date else ""
                    character = tv.get("character", "")
                    year_text = f" ({year})" if year else ""
                    character_text = f" 饰演 {character}" if character else ""
                    lines.append(f"   • {name_tv}{year_text}{character_text}")
        
        # 导演作品
        if movie_credits and movie_credits.get("crew"):
            director_works = [work for work in movie_credits["crew"] if work.get("job") == "Director"]
            if director_works:
                lines.extend([
                    f"",
                    f"🎬 *导演作品*:"
                ])
                for work in director_works[:5]:
                    title = work.get("title", "未知")
                    release_date = work.get("release_date", "")
                    year = release_date[:4] if release_date else ""
                    year_text = f" ({year})" if year else ""
                    lines.append(f"   • {title}{year_text}")
        
        if biography:
            lines.extend([
                f"",
                f"📖 *个人简介*:",
                f"{biography[:300]}{'...' if len(biography) > 300 else ''}"
            ])
        
        return "\n".join(filter(None, lines)), profile_url

    # ========================================
    # 观看平台格式化方法
    # ========================================
    
    def format_watch_providers(self, providers_data: Dict, content_type: str = "movie") -> str:
        """格式化观看平台信息
        Args:
            providers_data: 平台数据
            content_type: "movie" 或 "tv"
        """
        if not providers_data or not providers_data.get("results"):
            return "❌ 暂无观看平台信息"
        
        results = providers_data["results"]
        content_name = "电影" if content_type == "movie" else "电视剧"
        lines = [f"📺 *{content_name}观看平台*\n"]
        
        # 优先显示的地区
        priority_regions = ["CN", "US", "GB", "JP", "KR", "HK", "TW"]
        all_regions = list(results.keys())
        
        # 按优先级排序地区
        sorted_regions = []
        for region in priority_regions:
            if region in all_regions:
                sorted_regions.append(region)
        for region in all_regions:
            if region not in sorted_regions:
                sorted_regions.append(region)
        
        region_names = {
            "CN": "🇨🇳 中国大陆",
            "US": "🇺🇸 美国", 
            "GB": "🇬🇧 英国",
            "JP": "🇯🇵 日本",
            "KR": "🇰🇷 韩国",
            "HK": "🇭🇰 香港",
            "TW": "🇹🇼 台湾",
            "CA": "🇨🇦 加拿大",
            "AU": "🇦🇺 澳大利亚",
            "DE": "🇩🇪 德国",
            "FR": "🇫🇷 法国"
        }
        
        found_any = False
        for region in sorted_regions[:5]:  # 最多显示5个地区
            region_data = results[region]
            region_name = region_names.get(region, f"🌍 {region}")
            
            # 检查是否有任何观看方式
            has_content = any([
                region_data.get("flatrate"),
                region_data.get("buy"), 
                region_data.get("rent"),
                region_data.get("free")
            ])
            
            if not has_content:
                continue
                
            found_any = True
            lines.append(f"**{region_name}**")
            
            # 流媒体订阅
            if region_data.get("flatrate"):
                platforms = [p["provider_name"] for p in region_data["flatrate"][:5]]
                lines.append(f"🎬 *订阅观看*: {', '.join(platforms)}")
            
            # 购买
            if region_data.get("buy"):
                platforms = [p["provider_name"] for p in region_data["buy"][:3]]
                lines.append(f"💰 *购买*: {', '.join(platforms)}")
            
            # 租赁
            if region_data.get("rent"):
                platforms = [p["provider_name"] for p in region_data["rent"][:3]]
                lines.append(f"🏪 *租赁*: {', '.join(platforms)}")
            
            # 免费观看
            if region_data.get("free"):
                platforms = [p["provider_name"] for p in region_data["free"][:3]]
                lines.append(f"🆓 *免费*: {', '.join(platforms)}")
            
            lines.append("")
        
        if not found_any:
            return f"❌ 暂无该{content_name}的观看平台信息"
        
        lines.append("💡 数据来源: JustWatch")
        lines.append("⚠️ 平台可用性可能因时间而变化")
        
        return "\n".join(filter(None, lines))
    
    def format_watch_providers_compact(self, providers_data: Dict, content_type: str = "movie") -> str:
        """格式化观看平台信息（简化版，用于详情页面）"""
        if not providers_data or not providers_data.get("results"):
            return ""
        
        results = providers_data["results"]
        lines = []
        
        # 优先显示中国大陆和美国
        priority_regions = ["CN", "US", "GB"]
        region_names = {"CN": "🇨🇳中国", "US": "🇺🇸美国", "GB": "🇬🇧英国"}
        found_any = False
        
        for region in priority_regions:
            if region not in results:
                continue
                
            region_data = results[region]
            region_name = region_names.get(region, f"🌍{region}")
            
            # 只显示订阅平台（最常用）
            if region_data.get("flatrate"):
                platforms = []
                for p in region_data["flatrate"][:3]:
                    platform_name = p["provider_name"]
                    platforms.append(platform_name)
                
                if platforms:
                    found_any = True
                    lines.append(f"📺 *观看平台*: {', '.join(platforms)} ({region_name})")
                    break  # 只显示第一个有平台的地区
        
        if not found_any:
            # 如果没有订阅平台，尝试显示购买平台
            for region in priority_regions:
                if region not in results:
                    continue
                    
                region_data = results[region]
                region_name = region_names.get(region, f"🌍{region}")
                
                if region_data.get("buy"):
                    platforms = []
                    for p in region_data["buy"][:2]:
                        platform_name = p["provider_name"]
                        platforms.append(platform_name)
                    
                    if platforms:
                        lines.append(f"💰 *购买平台*: {', '.join(platforms)} ({region_name})")
                        break
        
        return "\n".join(lines) if lines else ""

# 全局服务实例
movie_service: MovieService = None

# 用户搜索会话管理
movie_search_sessions = {}
tv_search_sessions = {}

def create_movie_search_keyboard(search_data: dict) -> InlineKeyboardMarkup:
    """创建电影搜索结果的内联键盘"""
    keyboard = []
    
    # 电影选择按钮 (每行显示一个电影)
    results = search_data["results"]
    for i in range(min(len(results), 10)):  # 显示前10个结果
        movie = results[i]
        movie_title = movie.get("title", "未知电影")
        year = movie.get("release_date", "")[:4] if movie.get("release_date") else ""
        
        # 截断过长的电影名称
        if len(movie_title) > 35:
            movie_title = movie_title[:32] + "..."
            
        callback_data = f"movie_select_{i}_{search_data.get('current_page', 1)}"
        display_name = f"{i + 1}. 🎬 {movie_title}"
        if year:
            display_name += f" ({year})"
        keyboard.append([InlineKeyboardButton(display_name, callback_data=callback_data)])
    
    # 分页控制
    current_page = search_data.get("current_page", 1)
    total_pages = search_data.get("total_pages", 1)
    
    nav_row = []
    if current_page > 1:
        nav_row.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"movie_page_{current_page - 1}"))
        
    nav_row.append(InlineKeyboardButton(f"📄 {current_page}/{total_pages}", callback_data="movie_page_info"))
    
    if current_page < total_pages:
        nav_row.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"movie_page_{current_page + 1}"))
        
    if nav_row:
        keyboard.append(nav_row)
    
    # 操作按钮
    action_row = [
        InlineKeyboardButton("❌ 关闭", callback_data="movie_close")
    ]
    keyboard.append(action_row)
    
    return InlineKeyboardMarkup(keyboard)

def create_tv_search_keyboard(search_data: dict) -> InlineKeyboardMarkup:
    """创建电视剧搜索结果的内联键盘"""
    keyboard = []
    
    # 电视剧选择按钮 (每行显示一个电视剧)
    results = search_data["results"]
    for i in range(min(len(results), 10)):  # 显示前10个结果
        tv = results[i]
        tv_name = tv.get("name", "未知电视剧")
        year = tv.get("first_air_date", "")[:4] if tv.get("first_air_date") else ""
        
        # 截断过长的电视剧名称
        if len(tv_name) > 35:
            tv_name = tv_name[:32] + "..."
            
        callback_data = f"tv_select_{i}_{search_data.get('current_page', 1)}"
        display_name = f"{i + 1}. 📺 {tv_name}"
        if year:
            display_name += f" ({year})"
        keyboard.append([InlineKeyboardButton(display_name, callback_data=callback_data)])
    
    # 分页控制
    current_page = search_data.get("current_page", 1)
    total_pages = search_data.get("total_pages", 1)
    
    nav_row = []
    if current_page > 1:
        nav_row.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"tv_page_{current_page - 1}"))
        
    nav_row.append(InlineKeyboardButton(f"📄 {current_page}/{total_pages}", callback_data="tv_page_info"))
    
    if current_page < total_pages:
        nav_row.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"tv_page_{current_page + 1}"))
        
    if nav_row:
        keyboard.append(nav_row)
    
    # 操作按钮
    action_row = [
        InlineKeyboardButton("❌ 关闭", callback_data="tv_close")
    ]
    keyboard.append(action_row)
    
    return InlineKeyboardMarkup(keyboard)

def format_movie_search_results_for_keyboard(search_data: dict) -> str:
    """格式化电影搜索结果消息用于内联键盘显示"""
    if search_data.get("error"):
        return f"❌ 搜索失败: {search_data['error']}"
        
    results = search_data["results"]
    query = search_data.get("query", "")
    total_results = search_data.get("total_results", len(results))
    current_page = search_data.get("current_page", 1)
    total_pages = search_data.get("total_pages", 1)
    
    header = f"🎬 **电影搜索结果**\n"
    header += f"🔍 搜索词: *{escape_markdown(query, version=2)}*\n"
    header += f"📊 找到 {total_results} 部电影\n"
    if total_pages > 1:
        header += f"📄 第 {current_page}/{total_pages} 页\n"
    header += "\n请选择要查看详情的电影:"
    
    return header

def format_tv_search_results_for_keyboard(search_data: dict) -> str:
    """格式化电视剧搜索结果消息用于内联键盘显示"""
    if search_data.get("error"):
        return f"❌ 搜索失败: {search_data['error']}"
        
    results = search_data["results"]
    query = search_data.get("query", "")
    total_results = search_data.get("total_results", len(results))
    current_page = search_data.get("current_page", 1)
    total_pages = search_data.get("total_pages", 1)
    
    header = f"📺 **电视剧搜索结果**\n"
    header += f"🔍 搜索词: *{escape_markdown(query, version=2)}*\n"
    header += f"📊 找到 {total_results} 部电视剧\n"
    if total_pages > 1:
        header += f"📄 第 {current_page}/{total_pages} 页\n"
    header += "\n请选择要查看详情的电视剧:"
    
    return header

def init_movie_service():
    """初始化电影服务"""
    global movie_service
    movie_service = MovieService()

async def movie_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /movie 命令 - 搜索电影"""
    if not update.message or not update.effective_chat:
        return
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    if not context.args:
        help_text = (
            "*🎬 电影信息查询帮助*\n\n"
            "**基础查询:**\n"
            "`/movie <电影名>` - 搜索电影\n"
            "`/movie_hot` - 获取热门电影\n"
            "`/movie_detail <电影ID>` - 获取电影详情\n"
            "`/movie_rec <电影ID>` - 获取相似推荐\n"
            "`/movie_videos <电影ID>` - 获取预告片和视频\n"
            "`/movie_reviews <电影ID>` - 获取电影用户评价\n"
            "`/movie_watch <电影ID>` - 获取观看平台\n\n"
            "**热门趋势:**\n"
            "`/trending` - 今日全球热门内容\n"
            "`/trending_week` - 本周全球热门内容\n"
            "`/now_playing` - 正在上映的电影\n"
            "`/upcoming` - 即将上映的电影\n\n"
            "**示例:**\n"
            "`/movie 复仇者联盟`\n"
            "`/movie_detail 299536`\n"
            "`/movie_videos 299536`\n"
            "`/movie_reviews 299536`"
        )
        message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=foldable_text_with_markdown_v2(help_text),
            parse_mode=ParseMode.MARKDOWN_V2
        )
        # 调度删除机器人回复消息
        from utils.message_manager import _schedule_deletion
        from utils.config_manager import get_config
        config = get_config()
        await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)
        return
    
    query = " ".join(context.args)
    
    if not movie_service:
        error_message = "❌ 电影查询服务未初始化"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        return
    
    # 显示搜索进度
    escaped_query = escape_markdown(query, version=2)
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🔍 正在搜索电影: *{escaped_query}*\\.\\.\\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    try:
        search_data = await movie_service.search_movies(query)
        if search_data:
            # 添加查询词到搜索数据中
            search_data["query"] = query
            
            # 存储用户搜索会话
            user_id = update.effective_user.id
            movie_search_sessions[user_id] = {
                "search_data": search_data,
                "timestamp": datetime.now()
            }
            
            # 格式化搜索结果消息
            result_text = format_movie_search_results_for_keyboard(search_data)
            keyboard = create_movie_search_keyboard(search_data)
            
            # 更新消息显示搜索结果和选择按钮
            await message.edit_text(
                foldable_text_with_markdown_v2(result_text),
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            await message.edit_text("❌ 搜索电影失败，请稍后重试")
    except Exception as e:
        logger.error(f"电影搜索失败: {e}")
        await message.edit_text("❌ 搜索电影时发生错误")
    
    # 调度删除机器人回复消息
    from utils.message_manager import _schedule_deletion
    from utils.config_manager import get_config
    config = get_config()
    await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)

async def movie_hot_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /movie_hot 命令 - 获取热门电影"""
    if not update.message or not update.effective_chat:
        return
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    if not movie_service:
        error_message = "❌ 电影查询服务未初始化"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        return
    
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="🔍 正在获取热门电影\.\.\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    try:
        popular_data = await movie_service.get_popular_movies()
        if popular_data:
            result_text = movie_service.format_popular_movies(popular_data)
            await message.edit_text(
                foldable_text_with_markdown_v2(result_text),
                parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            await message.edit_text("❌ 获取热门电影失败，请稍后重试")
    except Exception as e:
        logger.error(f"获取热门电影失败: {e}")
        await message.edit_text("❌ 获取热门电影时发生错误")
    
    # 调度删除机器人回复消息
    from utils.message_manager import _schedule_deletion
    from utils.config_manager import get_config
    config = get_config()
    await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)

async def movie_detail_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /movie_detail 命令 - 获取电影详情"""
    if not update.message or not update.effective_chat:
        return
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    if not context.args:
        await send_error(
            context, 
            update.effective_chat.id, 
            foldable_text_v2("❌ 请提供电影ID\n\n用法: `/movie_detail <电影ID>`"), 
            parse_mode="MarkdownV2"
        )
        return
    
    try:
        movie_id = int(context.args[0])
    except ValueError:
        await send_error(
            context, 
            update.effective_chat.id, 
            foldable_text_v2("❌ 电影ID必须是数字"), 
            parse_mode="MarkdownV2"
        )
        return
    
    if not movie_service:
        error_message = "❌ 电影查询服务未初始化"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        return
    
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🔍 正在获取电影详情 \(ID: {movie_id}\)\.\.\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    try:
        detail_data = await movie_service.get_movie_details(movie_id)
        if detail_data:
            result_text, poster_url = movie_service.format_movie_details(detail_data)
            
            # 如果有海报URL，先发送图片再发送文本
            if poster_url:
                try:
                    # 发送海报图片
                    photo_message = await context.bot.send_photo(
                        chat_id=update.effective_chat.id,
                        photo=poster_url,
                        caption=foldable_text_with_markdown_v2(result_text),
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
                    # 删除原来的加载消息
                    await message.delete()
                    # 更新message为新发送的图片消息，用于后续删除调度
                    message = photo_message
                except Exception as photo_error:
                    logger.warning(f"发送海报失败: {photo_error}，改用文本消息")
                    # 如果图片发送失败，改用文本消息
                    await message.edit_text(
                        foldable_text_with_markdown_v2(result_text),
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
            else:
                # 没有海报，直接发送文本
                await message.edit_text(
                    foldable_text_with_markdown_v2(result_text),
                    parse_mode=ParseMode.MARKDOWN_V2
                )
        else:
            await message.edit_text(f"❌ 未找到ID为 {movie_id} 的电影")
    except Exception as e:
        logger.error(f"获取电影详情失败: {e}")
        await message.edit_text("❌ 获取电影详情时发生错误")
    
    # 调度删除机器人回复消息
    from utils.message_manager import _schedule_deletion
    from utils.config_manager import get_config
    config = get_config()
    await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)

async def movie_rec_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /movie_rec 命令 - 获取电影推荐"""
    if not update.message or not update.effective_chat:
        return
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    if not context.args:
        await send_error(
            context, 
            update.effective_chat.id, 
            foldable_text_v2("❌ 请提供电影ID\n\n用法: `/movie_rec <电影ID>`"), 
            parse_mode="MarkdownV2"
        )
        return
    
    try:
        movie_id = int(context.args[0])
    except ValueError:
        await send_error(
            context, 
            update.effective_chat.id, 
            foldable_text_v2("❌ 电影ID必须是数字"), 
            parse_mode="MarkdownV2"
        )
        return
    
    if not movie_service:
        error_message = "❌ 电影查询服务未初始化"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        return
    
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🔍 正在获取电影推荐 \(基于ID: {movie_id}\)\.\.\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    try:
        rec_data = await movie_service.get_movie_recommendations(movie_id)
        if rec_data:
            result_text = movie_service.format_movie_recommendations(rec_data, movie_id)
            await message.edit_text(
                foldable_text_with_markdown_v2(result_text),
                parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            await message.edit_text(f"❌ 未找到基于ID {movie_id} 的推荐")
    except Exception as e:
        logger.error(f"获取电影推荐失败: {e}")
        await message.edit_text("❌ 获取电影推荐时发生错误")
    
    # 调度删除机器人回复消息
    from utils.message_manager import _schedule_deletion
    from utils.config_manager import get_config
    config = get_config()
    await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)

async def movie_clean_cache_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /movie_cleancache 命令"""
    if not update.message:
        return
    
    try:
        # 清理电影和电视剧相关缓存
        prefixes = [
            "movie_search_", "movie_popular_", "movie_detail_", "movie_rec_",
            "tv_search_", "tv_popular_", "tv_detail_", "tv_rec_", 
            "tv_season_", "tv_episode_"
        ]
        for prefix in prefixes:
            await cache_manager.clear_cache(subdirectory="movie", key_prefix=prefix)
        
        success_message = "✅ 电影和电视剧查询缓存已清理。"
        await send_success(context, update.effective_chat.id, foldable_text_v2(success_message), parse_mode="MarkdownV2")
        await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    except Exception as e:
        logger.error(f"清理缓存失败: {e}")
        error_message = f"❌ 清理缓存时发生错误: {e!s}"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        await delete_user_command(context, update.effective_chat.id, update.message.message_id)

# ========================================
# 电视剧命令处理函数
# ========================================

async def tv_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /tv 命令 - 搜索电视剧"""
    if not update.message or not update.effective_chat:
        return
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    if not context.args:
        help_text = (
            "*📺 电视剧信息查询帮助*\n\n"
            "**基础查询:**\n"
            "`/tv <电视剧名>` - 搜索电视剧\n"
            "`/tv_hot` - 获取热门电视剧\n"
            "`/tv_detail <电视剧ID>` - 获取电视剧详情\n"
            "`/tv_rec <电视剧ID>` - 获取相似推荐\n"
            "`/tv_videos <电视剧ID>` - 获取预告片和视频\n"
            "`/tv_reviews <电视剧ID>` - 获取电视剧用户评价\n"
            "`/tv_watch <电视剧ID>` - 获取观看平台\n"
            "`/tv_season <电视剧ID> <季数>` - 获取季详情\n"
            "`/tv_episode <电视剧ID> <季数> <集数>` - 获取集详情\n\n"
            "**播出信息:**\n"
            "`/tv_airing` - 今日播出的电视剧\n"
            "`/tv_on_air` - 正在播出的电视剧\n\n"
            "**示例:**\n"
            "`/tv 权力的游戏`\n"
            "`/tv_detail 1399`\n"
            "`/tv_season 1399 1`\n"
            "`/tv_videos 1399`\n"
            "`/tv_reviews 1399`"
        )
        message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=foldable_text_with_markdown_v2(help_text),
            parse_mode=ParseMode.MARKDOWN_V2
        )
        # 调度删除机器人回复消息
        from utils.message_manager import _schedule_deletion
        from utils.config_manager import get_config
        config = get_config()
        await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)
        return
    
    query = " ".join(context.args)
    
    if not movie_service:
        error_message = "❌ 电视剧查询服务未初始化"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        return
    
    # 显示搜索进度
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🔍 正在搜索电视剧: *{escape_markdown(query, version=2)}*\.\.\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    try:
        search_data = await movie_service.search_tv_shows(query)
        if search_data:
            # 添加查询词到搜索数据中
            search_data["query"] = query
            
            # 存储用户搜索会话
            user_id = update.effective_user.id
            tv_search_sessions[user_id] = {
                "search_data": search_data,
                "timestamp": datetime.now()
            }
            
            # 格式化搜索结果消息
            result_text = format_tv_search_results_for_keyboard(search_data)
            keyboard = create_tv_search_keyboard(search_data)
            
            # 更新消息显示搜索结果和选择按钮
            await message.edit_text(
                foldable_text_with_markdown_v2(result_text),
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            await message.edit_text("❌ 搜索电视剧失败，请稍后重试")
    except Exception as e:
        logger.error(f"电视剧搜索失败: {e}")
        await message.edit_text("❌ 搜索电视剧时发生错误")
    
    # 调度删除机器人回复消息
    from utils.message_manager import _schedule_deletion
    from utils.config_manager import get_config
    config = get_config()
    await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)

async def tv_hot_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /tv_hot 命令 - 获取热门电视剧"""
    if not update.message or not update.effective_chat:
        return
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    if not movie_service:
        error_message = "❌ 电视剧查询服务未初始化"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        return
    
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="🔍 正在获取热门电视剧\.\.\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    try:
        popular_data = await movie_service.get_popular_tv_shows()
        if popular_data:
            result_text = movie_service.format_popular_tv_shows(popular_data)
            await message.edit_text(
                foldable_text_with_markdown_v2(result_text),
                parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            await message.edit_text("❌ 获取热门电视剧失败，请稍后重试")
    except Exception as e:
        logger.error(f"获取热门电视剧失败: {e}")
        await message.edit_text("❌ 获取热门电视剧时发生错误")
    
    # 调度删除机器人回复消息
    from utils.message_manager import _schedule_deletion
    from utils.config_manager import get_config
    config = get_config()
    await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)

async def tv_detail_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /tv_detail 命令 - 获取电视剧详情"""
    if not update.message or not update.effective_chat:
        return
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    if not context.args:
        await send_error(
            context, 
            update.effective_chat.id, 
            foldable_text_v2("❌ 请提供电视剧ID\n\n用法: `/tv_detail <电视剧ID>`"), 
            parse_mode="MarkdownV2"
        )
        return
    
    try:
        tv_id = int(context.args[0])
    except ValueError:
        await send_error(
            context, 
            update.effective_chat.id, 
            foldable_text_v2("❌ 电视剧ID必须是数字"), 
            parse_mode="MarkdownV2"
        )
        return
    
    if not movie_service:
        error_message = "❌ 电视剧查询服务未初始化"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        return
    
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🔍 正在获取电视剧详情 \(ID: {tv_id}\)\.\.\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    try:
        detail_data = await movie_service.get_tv_details(tv_id)
        if detail_data:
            result_text, poster_url = movie_service.format_tv_details(detail_data)
            
            # 如果有海报URL，先发送图片再发送文本
            if poster_url:
                try:
                    # 发送海报图片
                    photo_message = await context.bot.send_photo(
                        chat_id=update.effective_chat.id,
                        photo=poster_url,
                        caption=foldable_text_with_markdown_v2(result_text),
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
                    # 删除原来的加载消息
                    await message.delete()
                    # 更新message为新发送的图片消息，用于后续删除调度
                    message = photo_message
                except Exception as photo_error:
                    logger.warning(f"发送海报失败: {photo_error}，改用文本消息")
                    # 如果图片发送失败，改用文本消息
                    await message.edit_text(
                        foldable_text_with_markdown_v2(result_text),
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
            else:
                # 没有海报，直接发送文本
                await message.edit_text(
                    foldable_text_with_markdown_v2(result_text),
                    parse_mode=ParseMode.MARKDOWN_V2
                )
        else:
            await message.edit_text(f"❌ 未找到ID为 {tv_id} 的电视剧")
    except Exception as e:
        logger.error(f"获取电视剧详情失败: {e}")
        await message.edit_text("❌ 获取电视剧详情时发生错误")
    
    # 调度删除机器人回复消息
    from utils.message_manager import _schedule_deletion
    from utils.config_manager import get_config
    config = get_config()
    await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)

async def tv_rec_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /tv_rec 命令 - 获取电视剧推荐"""
    if not update.message or not update.effective_chat:
        return
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    if not context.args:
        await send_error(
            context, 
            update.effective_chat.id, 
            foldable_text_v2("❌ 请提供电视剧ID\n\n用法: `/tv_rec <电视剧ID>`"), 
            parse_mode="MarkdownV2"
        )
        return
    
    try:
        tv_id = int(context.args[0])
    except ValueError:
        await send_error(
            context, 
            update.effective_chat.id, 
            foldable_text_v2("❌ 电视剧ID必须是数字"), 
            parse_mode="MarkdownV2"
        )
        return
    
    if not movie_service:
        error_message = "❌ 电视剧查询服务未初始化"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        return
    
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🔍 正在获取电视剧推荐 \(基于ID: {tv_id}\)\.\.\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    try:
        rec_data = await movie_service.get_tv_recommendations(tv_id)
        if rec_data:
            result_text = movie_service.format_tv_recommendations(rec_data, tv_id)
            await message.edit_text(
                foldable_text_with_markdown_v2(result_text),
                parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            await message.edit_text(f"❌ 未找到基于ID {tv_id} 的推荐")
    except Exception as e:
        logger.error(f"获取电视剧推荐失败: {e}")
        await message.edit_text("❌ 获取电视剧推荐时发生错误")
    
    # 调度删除机器人回复消息
    from utils.message_manager import _schedule_deletion
    from utils.config_manager import get_config
    config = get_config()
    await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)

async def tv_season_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /tv_season 命令 - 获取电视剧季详情（智能长度版本）"""
    if not update.message or not update.effective_chat:
        return
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    if len(context.args) < 2:
        await send_error(
            context, 
            update.effective_chat.id, 
            foldable_text_v2("❌ 请提供电视剧ID和季数\n\n用法: `/tv_season <电视剧ID> <季数>`"), 
            parse_mode="MarkdownV2"
        )
        return
    
    try:
        tv_id = int(context.args[0])
        season_number = int(context.args[1])
    except ValueError:
        await send_error(
            context, 
            update.effective_chat.id, 
            foldable_text_v2("❌ 电视剧ID和季数必须是数字"), 
            parse_mode="MarkdownV2"
        )
        return
    
    if not movie_service:
        error_message = "❌ 电视剧查询服务未初始化"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        return
    
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🔍 正在获取第{season_number}季详情 \\(电视剧ID: {tv_id}\\)\\.\\.\\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    try:
        season_data = await movie_service.get_tv_season_details(tv_id, season_number)
        if not season_data:
            await message.edit_text(f"❌ 未找到电视剧ID {tv_id} 的第{season_number}季")
            return
        
        # 获取电视剧基本信息用于Telegraph标题
        tv_detail_data = await movie_service.get_tv_details(tv_id)
        tv_title = tv_detail_data.get("name", "未知电视剧") if tv_detail_data else "未知电视剧"
        
        # 格式化剧集列表
        result_text = movie_service.format_tv_season_details(season_data, tv_id)
        
        # 检查是否需要使用Telegraph（更积极的触发条件）
        episodes = season_data.get("episodes", [])
        episodes_count = len(episodes)
        
        # 计算所有剧集简介的总长度
        total_overview_length = sum(len(ep.get("overview", "")) for ep in episodes)
        avg_overview_length = total_overview_length / max(episodes_count, 1)
        
        # Telegraph触发条件：
        # 1. 消息长度超过2800字符
        # 2. 有5集以上且平均简介长度超过150字符
        # 3. 有任何单集简介超过400字符
        # 4. 总集数超过15集
        max_single_overview = max((len(ep.get("overview", "")) for ep in episodes), default=0)
        
        should_use_telegraph = (
            len(result_text) > 2800 or 
            (episodes_count > 5 and avg_overview_length > 150) or
            max_single_overview > 400 or
            episodes_count > 15
        )
        
        if should_use_telegraph:
            # 创建Telegraph页面
            telegraph_content = movie_service.format_season_episodes_for_telegraph(season_data, tv_id)
            season_name = season_data.get("name", f"第{season_number}季")
            telegraph_url = await movie_service.create_telegraph_page(f"{tv_title} {season_name} - 完整剧集列表", telegraph_content)
            
            if telegraph_url:
                # 发送包含Telegraph链接和简短预览的消息
                
                # 创建简短的预览版本（只显示前3集的基本信息）
                preview_lines = [
                    f"📺 *{season_data.get('name', f'第{season_number}季')}*",
                    f"",
                    f"📅 *播出日期*: {season_data.get('air_date', '') or '未知'}",
                    f"📚 *集数*: {episodes_count}集",
                    f"",
                    f"📖 *简介*:",
                    f"{season_data.get('overview', '暂无简介')[:200]}{'...' if len(season_data.get('overview', '')) > 200 else ''}",
                    f"",
                    f"📋 *剧集预览* (前3集):",
                    f""
                ]
                
                for ep in episodes[:3]:
                    ep_num = ep.get("episode_number", 0)
                    ep_name = ep.get("name", f"第{ep_num}集")
                    ep_date = ep.get("air_date", "")
                    
                    preview_lines.append(f"{ep_num}. *{ep_name}*")
                    if ep_date:
                        preview_lines.append(f"   📅 {ep_date}")
                    preview_lines.append("")
                
                if episodes_count > 3:
                    preview_lines.append(f"... 还有 {episodes_count - 3} 集")
                
                preview_lines.extend([
                    "",
                    f"📊 *总共 {episodes_count} 集剧集*",
                    f"📄 **完整剧集列表**: 由于内容较长，已生成Telegraph页面",
                    f"🔗 **查看完整列表**: {telegraph_url}",
                    "",
                    f"💡 使用 `/tv_episode {tv_id} {season_number} <集数>` 查看集详情"
                ])
                
                summary_text = "\n".join(preview_lines)
                await message.edit_text(
                    foldable_text_with_markdown_v2(summary_text),
                    parse_mode=ParseMode.MARKDOWN_V2
                )
            else:
                # Telegraph发布失败，发送截断的消息
                truncated_text = result_text[:TELEGRAM_MESSAGE_LIMIT - 200] + "\n\n⚠️ 内容过长已截断，完整剧集列表请查看详情页面"
                await message.edit_text(
                    foldable_text_with_markdown_v2(truncated_text),
                    parse_mode=ParseMode.MARKDOWN_V2
                )
        else:
            # 内容不长，直接发送
            await message.edit_text(
                foldable_text_with_markdown_v2(result_text),
                parse_mode=ParseMode.MARKDOWN_V2
            )
        
    except Exception as e:
        logger.error(f"获取电视剧季详情失败: {e}")
        await message.edit_text("❌ 获取电视剧季详情时发生错误")
    
    # 调度删除机器人回复消息
    from utils.message_manager import _schedule_deletion
    from utils.config_manager import get_config
    config = get_config()
    await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)

async def tv_episode_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /tv_episode 命令 - 获取电视剧集详情"""
    if not update.message or not update.effective_chat:
        return
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    if len(context.args) < 3:
        await send_error(
            context, 
            update.effective_chat.id, 
            foldable_text_v2("❌ 请提供电视剧ID、季数和集数\n\n用法: `/tv_episode <电视剧ID> <季数> <集数>`"), 
            parse_mode="MarkdownV2"
        )
        return
    
    try:
        tv_id = int(context.args[0])
        season_number = int(context.args[1])
        episode_number = int(context.args[2])
    except ValueError:
        await send_error(
            context, 
            update.effective_chat.id, 
            foldable_text_v2("❌ 电视剧ID、季数和集数必须是数字"), 
            parse_mode="MarkdownV2"
        )
        return
    
    if not movie_service:
        error_message = "❌ 电视剧查询服务未初始化"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        return
    
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🔍 正在获取第{season_number}季第{episode_number}集详情 \(电视剧ID: {tv_id}\)\.\.\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    try:
        episode_data = await movie_service.get_tv_episode_details(tv_id, season_number, episode_number)
        if episode_data:
            result_text = movie_service.format_tv_episode_details(episode_data, tv_id, season_number)
            await message.edit_text(
                foldable_text_with_markdown_v2(result_text),
                parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            await message.edit_text(f"❌ 未找到电视剧ID {tv_id} 第{season_number}季第{episode_number}集")
    except Exception as e:
        logger.error(f"获取电视剧集详情失败: {e}")
        await message.edit_text("❌ 获取电视剧集详情时发生错误")
    
    # 调度删除机器人回复消息
    from utils.message_manager import _schedule_deletion
    from utils.config_manager import get_config
    config = get_config()
    await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)

async def movie_videos_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /movie_videos 命令 - 获取电影视频"""
    if not update.message or not update.effective_chat:
        return
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    if not context.args:
        await send_error(
            context, 
            update.effective_chat.id, 
            foldable_text_v2("❌ 请提供电影ID\n\n用法: `/movie_videos <电影ID>`"), 
            parse_mode="MarkdownV2"
        )
        return
    
    try:
        movie_id = int(context.args[0])
    except ValueError:
        await send_error(
            context, 
            update.effective_chat.id, 
            foldable_text_v2("❌ 电影ID必须是数字"), 
            parse_mode="MarkdownV2"
        )
        return
    
    if not movie_service:
        error_message = "❌ 电影查询服务未初始化"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        return
    
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🔍 正在获取电影视频 \(ID: {movie_id}\)\.\.\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    try:
        # 直接获取视频数据
        videos_data = await movie_service._get_videos_data("movie", movie_id)
        if videos_data:
            result_text = movie_service.format_movie_videos(videos_data)
            await message.edit_text(
                foldable_text_with_markdown_v2(result_text),
                parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            await message.edit_text(f"❌ 未找到ID为 {movie_id} 的电影或无视频内容")
    except Exception as e:
        logger.error(f"获取电影视频失败: {e}")
        await message.edit_text("❌ 获取电影视频时发生错误")
    
    # 调度删除机器人回复消息
    from utils.message_manager import _schedule_deletion
    from utils.config_manager import get_config
    config = get_config()
    await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)

async def movie_reviews_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /movie_reviews 命令 - 获取电影评价"""
    if not update.message or not update.effective_chat:
        return
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    if not context.args:
        await send_error(
            context, 
            update.effective_chat.id, 
            foldable_text_v2("❌ 请提供电影ID\n\n用法: `/movie_reviews <电影ID>`"), 
            parse_mode="MarkdownV2"
        )
        return
    
    try:
        movie_id = int(context.args[0])
    except ValueError:
        await send_error(
            context, 
            update.effective_chat.id, 
            foldable_text_v2("❌ 电影ID必须是数字"), 
            parse_mode="MarkdownV2"
        )
        return
    
    if not movie_service:
        error_message = "❌ 电影查询服务未初始化"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        return
    
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🔍 正在获取电影评价 \(ID: {movie_id}\)\.\.\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    try:
        # 获取电影基本信息
        detail_data = await movie_service.get_movie_details(movie_id)
        if not detail_data:
            await message.edit_text(f"❌ 未找到ID为 {movie_id} 的电影")
            return
        
        movie_title = detail_data.get("title", "未知电影")
        
        # 获取评价数据
        reviews_data = await movie_service._get_reviews_data("movie", movie_id)
        if not reviews_data:
            await message.edit_text(f"❌ 未找到电影《{movie_title}》的评价信息")
            # 调度删除机器人回复消息
            from utils.message_manager import _schedule_deletion
            from utils.config_manager import get_config
            config = get_config()
            await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)
            return
        
        # 格式化评价列表
        result_text = movie_service.format_reviews_list(reviews_data)
        
        # 检查是否需要使用Telegraph（更积极的触发条件）
        reviews_count = len(reviews_data.get("results", []))
        avg_review_length = sum(len(r.get("content", "")) for r in reviews_data.get("results", [])) / max(reviews_count, 1)
        
        # 更积极的Telegraph触发条件：
        # 1. 消息长度超过2500字符
        # 2. 有2条以上评价且平均长度超过400字符
        # 3. 有任何单条评价超过800字符
        max_single_review = max((len(r.get("content", "")) for r in reviews_data.get("results", [])), default=0)
        
        should_use_telegraph = (
            len(result_text) > 2500 or 
            (reviews_count >= 2 and avg_review_length > 400) or
            max_single_review > 800
        )
        
        if should_use_telegraph:
            # 创建Telegraph页面
            telegraph_content = movie_service.format_reviews_for_telegraph(reviews_data, movie_title)
            telegraph_url = await movie_service.create_telegraph_page(f"{movie_title} - 用户评价", telegraph_content)
            
            if telegraph_url:
                # 发送包含Telegraph链接和简短预览的消息
                reviews_count = len(reviews_data.get("results", []))
                
                # 创建简短的预览版本（只显示前2条评价的更短预览）
                preview_lines = ["📝 *用户评价预览*\n"]
                for i, review in enumerate(reviews_data.get("results", [])[:2], 1):
                    author = review.get("author", "匿名用户")
                    content = review.get("content", "")
                    rating = review.get("author_details", {}).get("rating")
                    
                    # 语言检测
                    chinese_chars = len([c for c in content if '\u4e00' <= c <= '\u9fff'])
                    is_chinese = chinese_chars > len(content) * 0.3
                    lang_flag = "🇨🇳" if is_chinese else "🇺🇸"
                    
                    # 短预览，最多100字符
                    content_preview = content[:100] + "..." if len(content) > 100 else content
                    content_preview = content_preview.replace('\n', ' ').replace('\r', ' ')
                    
                    rating_text = f" ({rating}/10)" if rating else ""
                    preview_lines.extend([
                        f"{i}. *{author}*{rating_text} {lang_flag}:",
                        f"   _{content_preview}_",
                        ""
                    ])
                
                if reviews_count > 2:
                    preview_lines.append(f"... 还有 {reviews_count - 2} 条评价")
                
                preview_lines.extend([
                    "",
                    f"📊 *总共 {reviews_count} 条评价*",
                    f"📄 **完整评价内容**: 由于内容较长，已生成Telegraph页面",
                    f"🔗 **查看完整评价**: {telegraph_url}",
                    "",
                    f"💡 使用 `/movie_detail {movie_id}` 查看电影详情"
                ])
                
                summary_text = "\n".join(preview_lines)
                await message.edit_text(
                    foldable_text_with_markdown_v2(summary_text),
                    parse_mode=ParseMode.MARKDOWN_V2
                )
            else:
                # Telegraph发布失败，发送截断的消息
                truncated_text = result_text[:TELEGRAM_MESSAGE_LIMIT - 200] + "\n\n⚠️ 内容过长已截断，完整评价请查看详情页面"
                await message.edit_text(
                    foldable_text_with_markdown_v2(truncated_text),
                    parse_mode=ParseMode.MARKDOWN_V2
                )
        else:
            # 内容不长，直接发送
            await message.edit_text(
                foldable_text_with_markdown_v2(result_text),
                parse_mode=ParseMode.MARKDOWN_V2
            )
        
    except Exception as e:
        logger.error(f"获取电影评价失败: {e}")
        await message.edit_text("❌ 获取电影评价时发生错误")
    
    # 调度删除机器人回复消息
    from utils.message_manager import _schedule_deletion
    from utils.config_manager import get_config
    config = get_config()
    await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)

async def tv_videos_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /tv_videos 命令 - 获取电视剧视频"""
    if not update.message or not update.effective_chat:
        return
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    if not context.args:
        await send_error(
            context, 
            update.effective_chat.id, 
            foldable_text_v2("❌ 请提供电视剧ID\n\n用法: `/tv_videos <电视剧ID>`"), 
            parse_mode="MarkdownV2"
        )
        return
    
    try:
        tv_id = int(context.args[0])
    except ValueError:
        await send_error(
            context, 
            update.effective_chat.id, 
            foldable_text_v2("❌ 电视剧ID必须是数字"), 
            parse_mode="MarkdownV2"
        )
        return
    
    if not movie_service:
        error_message = "❌ 电视剧查询服务未初始化"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        return
    
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🔍 正在获取电视剧视频 \(ID: {tv_id}\)\.\.\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    try:
        # 直接获取视频数据
        videos_data = await movie_service._get_videos_data("tv", tv_id)
        if videos_data:
            result_text = movie_service.format_tv_videos(videos_data)
            await message.edit_text(
                foldable_text_with_markdown_v2(result_text),
                parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            await message.edit_text(f"❌ 未找到ID为 {tv_id} 的电视剧或无视频内容")
    except Exception as e:
        logger.error(f"获取电视剧视频失败: {e}")
        await message.edit_text("❌ 获取电视剧视频时发生错误")
    
    # 调度删除机器人回复消息
    from utils.message_manager import _schedule_deletion
    from utils.config_manager import get_config
    config = get_config()
    await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)

async def tv_reviews_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /tv_reviews 命令 - 获取电视剧评价"""
    if not update.message or not update.effective_chat:
        return
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    if not context.args:
        await send_error(
            context, 
            update.effective_chat.id, 
            foldable_text_v2("❌ 请提供电视剧ID\n\n用法: `/tv_reviews <电视剧ID>`"), 
            parse_mode="MarkdownV2"
        )
        return
    
    try:
        tv_id = int(context.args[0])
    except ValueError:
        await send_error(
            context, 
            update.effective_chat.id, 
            foldable_text_v2("❌ 电视剧ID必须是数字"), 
            parse_mode="MarkdownV2"
        )
        return
    
    if not movie_service:
        error_message = "❌ 电视剧查询服务未初始化"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        return
    
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🔍 正在获取电视剧评价 \(ID: {tv_id}\)\.\.\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    try:
        # 获取电视剧基本信息
        detail_data = await movie_service.get_tv_details(tv_id)
        if not detail_data:
            await message.edit_text(f"❌ 未找到ID为 {tv_id} 的电视剧")
            return
        
        tv_title = detail_data.get("name", "未知电视剧")
        
        # 获取评价数据
        reviews_data = await movie_service._get_reviews_data("tv", tv_id)
        if not reviews_data:
            await message.edit_text(f"❌ 未找到电视剧《{tv_title}》的评价信息")
            # 调度删除机器人回复消息
            from utils.message_manager import _schedule_deletion
            from utils.config_manager import get_config
            config = get_config()
            await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)
            return
        
        # 格式化评价列表
        result_text = movie_service.format_reviews_list(reviews_data)
        
        # 检查是否需要使用Telegraph（更积极的触发条件）
        reviews_count = len(reviews_data.get("results", []))
        avg_review_length = sum(len(r.get("content", "")) for r in reviews_data.get("results", [])) / max(reviews_count, 1)
        
        # 更积极的Telegraph触发条件：
        # 1. 消息长度超过2500字符
        # 2. 有2条以上评价且平均长度超过400字符
        # 3. 有任何单条评价超过800字符
        max_single_review = max((len(r.get("content", "")) for r in reviews_data.get("results", [])), default=0)
        
        should_use_telegraph = (
            len(result_text) > 2500 or 
            (reviews_count >= 2 and avg_review_length > 400) or
            max_single_review > 800
        )
        
        if should_use_telegraph:
            # 创建Telegraph页面
            telegraph_content = movie_service.format_reviews_for_telegraph(reviews_data, tv_title)
            telegraph_url = await movie_service.create_telegraph_page(f"{tv_title} - 用户评价", telegraph_content)
            
            if telegraph_url:
                # 发送包含Telegraph链接和简短预览的消息
                reviews_count = len(reviews_data.get("results", []))
                
                # 创建简短的预览版本（只显示前2条评价的更短预览）
                preview_lines = ["📝 *用户评价预览*\n"]
                for i, review in enumerate(reviews_data.get("results", [])[:2], 1):
                    author = review.get("author", "匿名用户")
                    content = review.get("content", "")
                    rating = review.get("author_details", {}).get("rating")
                    
                    # 语言检测
                    chinese_chars = len([c for c in content if '\u4e00' <= c <= '\u9fff'])
                    is_chinese = chinese_chars > len(content) * 0.3
                    lang_flag = "🇨🇳" if is_chinese else "🇺🇸"
                    
                    # 短预览，最多100字符
                    content_preview = content[:100] + "..." if len(content) > 100 else content
                    content_preview = content_preview.replace('\n', ' ').replace('\r', ' ')
                    
                    rating_text = f" ({rating}/10)" if rating else ""
                    preview_lines.extend([
                        f"{i}. *{author}*{rating_text} {lang_flag}:",
                        f"   _{content_preview}_",
                        ""
                    ])
                
                if reviews_count > 2:
                    preview_lines.append(f"... 还有 {reviews_count - 2} 条评价")
                
                preview_lines.extend([
                    "",
                    f"📊 *总共 {reviews_count} 条评价*",
                    f"📄 **完整评价内容**: 由于内容较长，已生成Telegraph页面",
                    f"🔗 **查看完整评价**: {telegraph_url}",
                    "",
                    f"💡 使用 `/tv_detail {tv_id}` 查看电视剧详情"
                ])
                
                summary_text = "\n".join(preview_lines)
                await message.edit_text(
                    foldable_text_with_markdown_v2(summary_text),
                    parse_mode=ParseMode.MARKDOWN_V2
                )
            else:
                # Telegraph发布失败，发送截断的消息
                truncated_text = result_text[:TELEGRAM_MESSAGE_LIMIT - 200] + "\n\n⚠️ 内容过长已截断，完整评价请查看详情页面"
                await message.edit_text(
                    foldable_text_with_markdown_v2(truncated_text),
                    parse_mode=ParseMode.MARKDOWN_V2
                )
        else:
            # 内容不长，直接发送
            await message.edit_text(
                foldable_text_with_markdown_v2(result_text),
                parse_mode=ParseMode.MARKDOWN_V2
            )
        
    except Exception as e:
        logger.error(f"获取电视剧评价失败: {e}")
        await message.edit_text("❌ 获取电视剧评价时发生错误")
    
    # 调度删除机器人回复消息
    from utils.message_manager import _schedule_deletion
    from utils.config_manager import get_config
    config = get_config()
    await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)

async def trending_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /trending 命令 - 获取今日热门内容"""
    if not update.message or not update.effective_chat:
        return
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    if not movie_service:
        error_message = "❌ 电影查询服务未初始化"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        return
    
    # 获取参数，默认为今日全部内容
    time_window = "day"
    media_type = "all"
    
    if context.args:
        if context.args[0].lower() in ["day", "week"]:
            time_window = context.args[0].lower()
        if len(context.args) > 1 and context.args[1].lower() in ["movie", "tv", "person"]:
            media_type = context.args[1].lower()
    
    time_text = "今日" if time_window == "day" else "本周"
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🔍 正在获取{time_text}热门内容\.\.\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    try:
        trending_data = await movie_service.get_trending_content(media_type, time_window)
        if trending_data:
            result_text = movie_service.format_trending_content(trending_data, time_window)
            await message.edit_text(
                foldable_text_with_markdown_v2(result_text),
                parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            await message.edit_text("❌ 获取热门内容失败，请稍后重试")
    except Exception as e:
        logger.error(f"获取热门内容失败: {e}")
        await message.edit_text("❌ 获取热门内容时发生错误")
    
    # 调度删除机器人回复消息
    from utils.message_manager import _schedule_deletion
    from utils.config_manager import get_config
    config = get_config()
    await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)

async def trending_week_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /trending_week 命令 - 获取本周热门内容"""
    if not update.message or not update.effective_chat:
        return
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    if not movie_service:
        error_message = "❌ 电影查询服务未初始化"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        return
    
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="🔍 正在获取本周热门内容\.\.\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    try:
        trending_data = await movie_service.get_trending_content("all", "week")
        if trending_data:
            result_text = movie_service.format_trending_content(trending_data, "week")
            await message.edit_text(
                foldable_text_with_markdown_v2(result_text),
                parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            await message.edit_text("❌ 获取本周热门内容失败，请稍后重试")
    except Exception as e:
        logger.error(f"获取本周热门内容失败: {e}")
        await message.edit_text("❌ 获取本周热门内容时发生错误")
    
    # 调度删除机器人回复消息
    from utils.message_manager import _schedule_deletion
    from utils.config_manager import get_config
    config = get_config()
    await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)

async def now_playing_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /now_playing 命令 - 获取正在上映的电影"""
    if not update.message or not update.effective_chat:
        return
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    if not movie_service:
        error_message = "❌ 电影查询服务未初始化"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        return
    
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="🔍 正在获取正在上映的电影\.\.\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    try:
        playing_data = await movie_service.get_now_playing_movies()
        if playing_data:
            result_text = movie_service.format_now_playing_movies(playing_data)
            await message.edit_text(
                foldable_text_with_markdown_v2(result_text),
                parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            await message.edit_text("❌ 获取正在上映电影失败，请稍后重试")
    except Exception as e:
        logger.error(f"获取正在上映电影失败: {e}")
        await message.edit_text("❌ 获取正在上映电影时发生错误")
    
    # 调度删除机器人回复消息
    from utils.message_manager import _schedule_deletion
    from utils.config_manager import get_config
    config = get_config()
    await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)

async def upcoming_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /upcoming 命令 - 获取即将上映的电影"""
    if not update.message or not update.effective_chat:
        return
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    if not movie_service:
        error_message = "❌ 电影查询服务未初始化"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        return
    
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="🔍 正在获取即将上映的电影\.\.\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    try:
        upcoming_data = await movie_service.get_upcoming_movies()
        if upcoming_data:
            result_text = movie_service.format_upcoming_movies(upcoming_data)
            await message.edit_text(
                foldable_text_with_markdown_v2(result_text),
                parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            await message.edit_text("❌ 获取即将上映电影失败，请稍后重试")
    except Exception as e:
        logger.error(f"获取即将上映电影失败: {e}")
        await message.edit_text("❌ 获取即将上映电影时发生错误")
    
    # 调度删除机器人回复消息
    from utils.message_manager import _schedule_deletion
    from utils.config_manager import get_config
    config = get_config()
    await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)

async def tv_airing_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /tv_airing 命令 - 获取今日播出的电视剧"""
    if not update.message or not update.effective_chat:
        return
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    if not movie_service:
        error_message = "❌ 电视剧查询服务未初始化"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        return
    
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="🔍 正在获取今日播出的电视剧\.\.\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    try:
        airing_data = await movie_service.get_tv_airing_today()
        if airing_data:
            result_text = movie_service.format_tv_airing_today(airing_data)
            await message.edit_text(
                foldable_text_with_markdown_v2(result_text),
                parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            await message.edit_text("❌ 获取今日播出电视剧失败，请稍后重试")
    except Exception as e:
        logger.error(f"获取今日播出电视剧失败: {e}")
        await message.edit_text("❌ 获取今日播出电视剧时发生错误")
    
    # 调度删除机器人回复消息
    from utils.message_manager import _schedule_deletion
    from utils.config_manager import get_config
    config = get_config()
    await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)

async def tv_on_air_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /tv_on_air 命令 - 获取正在播出的电视剧"""
    if not update.message or not update.effective_chat:
        return
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    if not movie_service:
        error_message = "❌ 电视剧查询服务未初始化"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        return
    
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="🔍 正在获取正在播出的电视剧\.\.\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    try:
        on_air_data = await movie_service.get_tv_on_the_air()
        if on_air_data:
            result_text = movie_service.format_tv_on_the_air(on_air_data)
            await message.edit_text(
                foldable_text_with_markdown_v2(result_text),
                parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            await message.edit_text("❌ 获取正在播出电视剧失败，请稍后重试")
    except Exception as e:
        logger.error(f"获取正在播出电视剧失败: {e}")
        await message.edit_text("❌ 获取正在播出电视剧时发生错误")
    
    # 调度删除机器人回复消息
    from utils.message_manager import _schedule_deletion
    from utils.config_manager import get_config
    config = get_config()
    await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)

async def person_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /person 命令 - 搜索人物"""
    if not update.message or not update.effective_chat:
        return
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    if not context.args:
        help_text = (
            "*👤 人物信息查询帮助*\n\n"
            "`/person <人物名>` - 搜索人物\n"
            "`/person_detail <人物ID>` - 获取人物详情\n\n"
            "**示例:**\n"
            "`/person 汤姆·汉克斯`\n"
            "`/person_detail 31`"
        )
        message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=foldable_text_with_markdown_v2(help_text),
            parse_mode=ParseMode.MARKDOWN_V2
        )
        # 调度删除机器人回复消息
        from utils.message_manager import _schedule_deletion
        from utils.config_manager import get_config
        config = get_config()
        await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)
        return
    
    query = " ".join(context.args)
    
    if not movie_service:
        error_message = "❌ 人物查询服务未初始化"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        return
    
    # 显示搜索进度
    escaped_query = escape_markdown(query, version=2)
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🔍 正在搜索人物: *{escaped_query}*\\.\\.\\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    try:
        search_data = await movie_service.search_person(query)
        if search_data:
            result_text, profile_url = movie_service.format_person_search_results(search_data)
            
            # 如果有头像URL，先发送图片再发送文本
            if profile_url:
                try:
                    # 发送头像图片
                    photo_message = await context.bot.send_photo(
                        chat_id=update.effective_chat.id,
                        photo=profile_url,
                        caption=foldable_text_with_markdown_v2(result_text),
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
                    # 删除原来的加载消息
                    await message.delete()
                    # 更新message为新发送的图片消息，用于后续删除调度
                    message = photo_message
                except Exception as photo_error:
                    logger.warning(f"发送头像失败: {photo_error}，改用文本消息")
                    # 如果图片发送失败，改用文本消息
                    await message.edit_text(
                        foldable_text_with_markdown_v2(result_text),
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
            else:
                # 没有头像，直接发送文本
                await message.edit_text(
                    foldable_text_with_markdown_v2(result_text),
                    parse_mode=ParseMode.MARKDOWN_V2
                )
        else:
            await message.edit_text("❌ 搜索人物失败，请稍后重试")
    except Exception as e:
        logger.error(f"人物搜索失败: {e}")
        await message.edit_text("❌ 搜索人物时发生错误")
    
    # 调度删除机器人回复消息
    from utils.message_manager import _schedule_deletion
    from utils.config_manager import get_config
    config = get_config()
    await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)

async def person_detail_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /person_detail 命令 - 获取人物详情"""
    if not update.message or not update.effective_chat:
        return
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    if not context.args:
        await send_error(
            context, 
            update.effective_chat.id, 
            foldable_text_v2("❌ 请提供人物ID\n\n用法: `/person_detail <人物ID>`"), 
            parse_mode="MarkdownV2"
        )
        return
    
    try:
        person_id = int(context.args[0])
    except ValueError:
        await send_error(
            context, 
            update.effective_chat.id, 
            foldable_text_v2("❌ 人物ID必须是数字"), 
            parse_mode="MarkdownV2"
        )
        return
    
    if not movie_service:
        error_message = "❌ 人物查询服务未初始化"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        return
    
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🔍 正在获取人物详情 \(ID: {person_id}\)\.\.\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    try:
        detail_data = await movie_service.get_person_details(person_id)
        if detail_data:
            result_text, profile_url = movie_service.format_person_details(detail_data)
            
            # 如果有头像URL，先发送图片再发送文本
            if profile_url:
                try:
                    # 发送头像图片
                    photo_message = await context.bot.send_photo(
                        chat_id=update.effective_chat.id,
                        photo=profile_url,
                        caption=foldable_text_with_markdown_v2(result_text),
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
                    # 删除原来的加载消息
                    await message.delete()
                    # 更新message为新发送的图片消息，用于后续删除调度
                    message = photo_message
                except Exception as photo_error:
                    logger.warning(f"发送头像失败: {photo_error}，改用文本消息")
                    # 如果图片发送失败，改用文本消息
                    await message.edit_text(
                        foldable_text_with_markdown_v2(result_text),
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
            else:
                # 没有头像，直接发送文本
                await message.edit_text(
                    foldable_text_with_markdown_v2(result_text),
                    parse_mode=ParseMode.MARKDOWN_V2
                )
        else:
            await message.edit_text(f"❌ 未找到ID为 {person_id} 的人物")
    except Exception as e:
        logger.error(f"获取人物详情失败: {e}")
        await message.edit_text("❌ 获取人物详情时发生错误")
    
    # 调度删除机器人回复消息
    from utils.message_manager import _schedule_deletion
    from utils.config_manager import get_config
    config = get_config()
    await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)

async def movie_watch_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /movie_watch 命令 - 获取电影观看平台"""
    if not update.message or not update.effective_chat:
        return
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    if not context.args:
        await send_error(
            context, 
            update.effective_chat.id, 
            foldable_text_v2("❌ 请提供电影ID\n\n用法: `/movie_watch <电影ID>`"), 
            parse_mode="MarkdownV2"
        )
        return
    
    try:
        movie_id = int(context.args[0])
    except ValueError:
        await send_error(
            context, 
            update.effective_chat.id, 
            foldable_text_v2("❌ 电影ID必须是数字"), 
            parse_mode="MarkdownV2"
        )
        return
    
    if not movie_service:
        error_message = "❌ 电影查询服务未初始化"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        return
    
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🔍 正在获取观看平台信息 \(ID: {movie_id}\)\.\.\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    try:
        providers_data = await movie_service.get_movie_watch_providers(movie_id)
        if providers_data:
            result_text = movie_service.format_watch_providers(providers_data, "movie")
            await message.edit_text(
                foldable_text_with_markdown_v2(result_text),
                parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            await message.edit_text(f"❌ 未找到ID为 {movie_id} 的电影观看平台信息")
    except Exception as e:
        logger.error(f"获取电影观看平台失败: {e}")
        await message.edit_text("❌ 获取观看平台信息时发生错误")
    
    # 调度删除机器人回复消息
    from utils.message_manager import _schedule_deletion
    from utils.config_manager import get_config
    config = get_config()
    await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)

async def tv_watch_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /tv_watch 命令 - 获取电视剧观看平台"""
    if not update.message or not update.effective_chat:
        return
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    if not context.args:
        await send_error(
            context, 
            update.effective_chat.id, 
            foldable_text_v2("❌ 请提供电视剧ID\n\n用法: `/tv_watch <电视剧ID>`"), 
            parse_mode="MarkdownV2"
        )
        return
    
    try:
        tv_id = int(context.args[0])
    except ValueError:
        await send_error(
            context, 
            update.effective_chat.id, 
            foldable_text_v2("❌ 电视剧ID必须是数字"), 
            parse_mode="MarkdownV2"
        )
        return
    
    if not movie_service:
        error_message = "❌ 电视剧查询服务未初始化"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        return
    
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🔍 正在获取观看平台信息 \(ID: {tv_id}\)\.\.\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    try:
        providers_data = await movie_service.get_tv_watch_providers(tv_id)
        if providers_data:
            result_text = movie_service.format_watch_providers(providers_data, "tv")
            await message.edit_text(
                foldable_text_with_markdown_v2(result_text),
                parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            await message.edit_text(f"❌ 未找到ID为 {tv_id} 的电视剧观看平台信息")
    except Exception as e:
        logger.error(f"获取电视剧观看平台失败: {e}")
        await message.edit_text("❌ 获取观看平台信息时发生错误")
    
    # 调度删除机器人回复消息
    from utils.message_manager import _schedule_deletion
    from utils.config_manager import get_config
    config = get_config()
    await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)

async def movies_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /movies 命令 - 搜索电影（纯文本结果）"""
    if not update.message or not update.effective_chat:
        return
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    if not context.args:
        help_text = (
            "*🎬 电影文本搜索帮助*\n\n"
            "`/movies <电影名>` - 搜索电影（文本列表）\n"
            "`/movie <电影名>` - 搜索电影（按钮选择）\n\n"
            "**示例:**\n"
            "`/movies 复仇者联盟`"
        )
        message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=foldable_text_with_markdown_v2(help_text),
            parse_mode=ParseMode.MARKDOWN_V2
        )
        from utils.message_manager import _schedule_deletion
        from utils.config_manager import get_config
        config = get_config()
        await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)
        return
    
    query = " ".join(context.args)
    
    if not movie_service:
        error_message = "❌ 电影查询服务未初始化"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        return
    
    # 显示搜索进度
    escaped_query = escape_markdown(query, version=2)
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🔍 正在搜索电影: *{escaped_query}*\\.\\.\\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    try:
        search_data = await movie_service.search_movies(query)
        if search_data:
            # 使用原来的文本格式化函数
            result_text, poster_url = movie_service.format_movie_search_results(search_data)
            
            # 如果有海报URL，先发送图片再发送文本
            if poster_url:
                try:
                    # 发送海报图片
                    photo_message = await context.bot.send_photo(
                        chat_id=update.effective_chat.id,
                        photo=poster_url,
                        caption=foldable_text_with_markdown_v2(result_text),
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
                    # 删除原来的加载消息
                    await message.delete()
                    # 更新message为新发送的图片消息，用于后续删除调度
                    message = photo_message
                except Exception as photo_error:
                    logger.warning(f"发送海报失败: {photo_error}，改用文本消息")
                    # 如果图片发送失败，改用文本消息
                    await message.edit_text(
                        foldable_text_with_markdown_v2(result_text),
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
            else:
                # 没有海报，直接发送文本
                await message.edit_text(
                    foldable_text_with_markdown_v2(result_text),
                    parse_mode=ParseMode.MARKDOWN_V2
                )
        else:
            await message.edit_text("❌ 搜索电影失败，请稍后重试")
    except Exception as e:
        logger.error(f"电影搜索失败: {e}")
        await message.edit_text("❌ 搜索电影时发生错误")
    
    # 调度删除机器人回复消息
    from utils.message_manager import _schedule_deletion
    from utils.config_manager import get_config
    config = get_config()
    await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)

async def tvs_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /tvs 命令 - 搜索电视剧（纯文本结果）"""
    if not update.message or not update.effective_chat:
        return
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    if not context.args:
        help_text = (
            "*📺 电视剧文本搜索帮助*\n\n"
            "`/tvs <电视剧名>` - 搜索电视剧（文本列表）\n"
            "`/tv <电视剧名>` - 搜索电视剧（按钮选择）\n\n"
            "**示例:**\n"
            "`/tvs 权力的游戏`"
        )
        message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=foldable_text_with_markdown_v2(help_text),
            parse_mode=ParseMode.MARKDOWN_V2
        )
        from utils.message_manager import _schedule_deletion
        from utils.config_manager import get_config
        config = get_config()
        await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)
        return
    
    query = " ".join(context.args)
    
    if not movie_service:
        error_message = "❌ 电视剧查询服务未初始化"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        return
    
    # 显示搜索进度
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🔍 正在搜索电视剧: *{escape_markdown(query, version=2)}*\.\.\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    try:
        search_data = await movie_service.search_tv_shows(query)
        if search_data:
            # 使用原来的文本格式化函数
            result_text, poster_url = movie_service.format_tv_search_results(search_data)
            
            # 如果有海报URL，先发送图片再发送文本
            if poster_url:
                try:
                    # 发送海报图片
                    photo_message = await context.bot.send_photo(
                        chat_id=update.effective_chat.id,
                        photo=poster_url,
                        caption=foldable_text_with_markdown_v2(result_text),
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
                    # 删除原来的加载消息
                    await message.delete()
                    # 更新message为新发送的图片消息，用于后续删除调度
                    message = photo_message
                except Exception as photo_error:
                    logger.warning(f"发送海报失败: {photo_error}，改用文本消息")
                    # 如果图片发送失败，改用文本消息
                    await message.edit_text(
                        foldable_text_with_markdown_v2(result_text),
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
            else:
                # 没有海报，直接发送文本
                await message.edit_text(
                    foldable_text_with_markdown_v2(result_text),
                    parse_mode=ParseMode.MARKDOWN_V2
                )
        else:
            await message.edit_text("❌ 搜索电视剧失败，请稍后重试")
    except Exception as e:
        logger.error(f"电视剧搜索失败: {e}")
        await message.edit_text("❌ 搜索电视剧时发生错误")
    
    # 调度删除机器人回复消息
    from utils.message_manager import _schedule_deletion
    from utils.config_manager import get_config
    config = get_config()
    await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)

async def movie_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理电影搜索结果的内联键盘回调"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    callback_data = query.data
    
    # 检查用户是否有有效的搜索会话
    if user_id not in movie_search_sessions:
        await query.edit_message_text("❌ 搜索会话已过期，请重新搜索")
        return
    
    session = movie_search_sessions[user_id]
    search_data = session["search_data"]
    
    try:
        if callback_data.startswith("movie_select_"):
            # 用户选择了一个电影
            parts = callback_data.split("_")
            movie_index = int(parts[2])
            page = int(parts[3])
            
            # 获取当前页的搜索结果
            if page != search_data.get("current_page", 1):
                # 需要获取指定页面的数据
                new_search_data = await movie_service.search_movies(
                    search_data["query"], page=page
                )
                if new_search_data:
                    search_data = new_search_data
                    movie_search_sessions[user_id]["search_data"] = search_data
            
            results = search_data["results"]
            if movie_index < len(results):
                selected_movie = results[movie_index]
                movie_id = selected_movie["id"]
                
                # 获取电影详情
                detail_data = await movie_service.get_movie_details(movie_id)
                if detail_data:
                    result_text, poster_url = movie_service.format_movie_details(detail_data)
                    
                    # 如果有海报URL，发送图片消息
                    if poster_url:
                        try:
                            await context.bot.send_photo(
                                chat_id=query.message.chat_id,
                                photo=poster_url,
                                caption=foldable_text_with_markdown_v2(result_text),
                                parse_mode=ParseMode.MARKDOWN_V2
                            )
                            # 删除原来的搜索结果消息
                            await query.delete_message()
                        except Exception as photo_error:
                            logger.warning(f"发送海报失败: {photo_error}，改用文本消息")
                            await query.edit_message_text(
                                foldable_text_with_markdown_v2(result_text),
                                parse_mode=ParseMode.MARKDOWN_V2
                            )
                    else:
                        await query.edit_message_text(
                            foldable_text_with_markdown_v2(result_text),
                            parse_mode=ParseMode.MARKDOWN_V2
                        )
                    
                    # 清除用户会话
                    del movie_search_sessions[user_id]
                else:
                    await query.edit_message_text("❌ 获取电影详情失败")
            else:
                await query.edit_message_text("❌ 选择的电影索引无效")
                
        elif callback_data.startswith("movie_page_"):
            # 处理分页
            if callback_data == "movie_page_info":
                return  # 只是显示页面信息，不做任何操作
            
            page_num = int(callback_data.split("_")[2])
            new_search_data = await movie_service.search_movies(
                search_data["query"], page=page_num
            )
            
            if new_search_data:
                new_search_data["query"] = search_data["query"]  # 保持原查询词
                movie_search_sessions[user_id]["search_data"] = new_search_data
                
                result_text = format_movie_search_results_for_keyboard(new_search_data)
                keyboard = create_movie_search_keyboard(new_search_data)
                
                await query.edit_message_text(
                    foldable_text_with_markdown_v2(result_text),
                    reply_markup=keyboard,
                    parse_mode=ParseMode.MARKDOWN_V2
                )
            else:
                await query.edit_message_text("❌ 获取页面数据失败")
                
        elif callback_data == "movie_close":
            # 关闭搜索结果
            await query.delete_message()
            if user_id in movie_search_sessions:
                del movie_search_sessions[user_id]
                
    except Exception as e:
        logger.error(f"处理电影搜索回调失败: {e}")
        await query.edit_message_text("❌ 处理选择时发生错误")

async def tv_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理电视剧搜索结果的内联键盘回调"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    callback_data = query.data
    
    # 检查用户是否有有效的搜索会话
    if user_id not in tv_search_sessions:
        await query.edit_message_text("❌ 搜索会话已过期，请重新搜索")
        return
    
    session = tv_search_sessions[user_id]
    search_data = session["search_data"]
    
    try:
        if callback_data.startswith("tv_select_"):
            # 用户选择了一个电视剧
            parts = callback_data.split("_")
            tv_index = int(parts[2])
            page = int(parts[3])
            
            # 获取当前页的搜索结果
            if page != search_data.get("current_page", 1):
                # 需要获取指定页面的数据
                new_search_data = await movie_service.search_tv_shows(
                    search_data["query"], page=page
                )
                if new_search_data:
                    search_data = new_search_data
                    tv_search_sessions[user_id]["search_data"] = search_data
            
            results = search_data["results"]
            if tv_index < len(results):
                selected_tv = results[tv_index]
                tv_id = selected_tv["id"]
                
                # 获取电视剧详情
                detail_data = await movie_service.get_tv_details(tv_id)
                if detail_data:
                    result_text, poster_url = movie_service.format_tv_details(detail_data)
                    
                    # 如果有海报URL，发送图片消息
                    if poster_url:
                        try:
                            await context.bot.send_photo(
                                chat_id=query.message.chat_id,
                                photo=poster_url,
                                caption=foldable_text_with_markdown_v2(result_text),
                                parse_mode=ParseMode.MARKDOWN_V2
                            )
                            # 删除原来的搜索结果消息
                            await query.delete_message()
                        except Exception as photo_error:
                            logger.warning(f"发送海报失败: {photo_error}，改用文本消息")
                            await query.edit_message_text(
                                foldable_text_with_markdown_v2(result_text),
                                parse_mode=ParseMode.MARKDOWN_V2
                            )
                    else:
                        await query.edit_message_text(
                            foldable_text_with_markdown_v2(result_text),
                            parse_mode=ParseMode.MARKDOWN_V2
                        )
                    
                    # 清除用户会话
                    del tv_search_sessions[user_id]
                else:
                    await query.edit_message_text("❌ 获取电视剧详情失败")
            else:
                await query.edit_message_text("❌ 选择的电视剧索引无效")
                
        elif callback_data.startswith("tv_page_"):
            # 处理分页
            if callback_data == "tv_page_info":
                return  # 只是显示页面信息，不做任何操作
            
            page_num = int(callback_data.split("_")[2])
            new_search_data = await movie_service.search_tv_shows(
                search_data["query"], page=page_num
            )
            
            if new_search_data:
                new_search_data["query"] = search_data["query"]  # 保持原查询词
                tv_search_sessions[user_id]["search_data"] = new_search_data
                
                result_text = format_tv_search_results_for_keyboard(new_search_data)
                keyboard = create_tv_search_keyboard(new_search_data)
                
                await query.edit_message_text(
                    foldable_text_with_markdown_v2(result_text),
                    reply_markup=keyboard,
                    parse_mode=ParseMode.MARKDOWN_V2
                )
            else:
                await query.edit_message_text("❌ 获取页面数据失败")
                
        elif callback_data == "tv_close":
            # 关闭搜索结果
            await query.delete_message()
            if user_id in tv_search_sessions:
                del tv_search_sessions[user_id]
                
    except Exception as e:
        logger.error(f"处理电视剧搜索回调失败: {e}")
        await query.edit_message_text("❌ 处理选择时发生错误")

# 注册命令
command_factory.register_command("movie", movie_command, permission=Permission.USER, description="搜索电影信息（按钮选择）")
command_factory.register_command("movies", movies_command, permission=Permission.USER, description="搜索电影信息（文本列表）")
command_factory.register_command("movie_hot", movie_hot_command, permission=Permission.USER, description="获取热门电影")
command_factory.register_command("movie_detail", movie_detail_command, permission=Permission.USER, description="获取电影详情")
command_factory.register_command("movie_rec", movie_rec_command, permission=Permission.USER, description="获取电影推荐")
command_factory.register_command("movie_videos", movie_videos_command, permission=Permission.USER, description="获取电影预告片")
command_factory.register_command("movie_reviews", movie_reviews_command, permission=Permission.USER, description="获取电影用户评价")
command_factory.register_command("movie_cleancache", movie_clean_cache_command, permission=Permission.ADMIN, description="清理电影和电视剧查询缓存")

# 注册电视剧命令
command_factory.register_command("tv", tv_command, permission=Permission.USER, description="搜索电视剧信息（按钮选择）")
command_factory.register_command("tvs", tvs_command, permission=Permission.USER, description="搜索电视剧信息（文本列表）")
command_factory.register_command("tv_hot", tv_hot_command, permission=Permission.USER, description="获取热门电视剧")
command_factory.register_command("tv_detail", tv_detail_command, permission=Permission.USER, description="获取电视剧详情")
command_factory.register_command("tv_rec", tv_rec_command, permission=Permission.USER, description="获取电视剧推荐")
command_factory.register_command("tv_videos", tv_videos_command, permission=Permission.USER, description="获取电视剧预告片")
command_factory.register_command("tv_reviews", tv_reviews_command, permission=Permission.USER, description="获取电视剧用户评价")
command_factory.register_command("tv_season", tv_season_command, permission=Permission.USER, description="获取电视剧季详情")
command_factory.register_command("tv_episode", tv_episode_command, permission=Permission.USER, description="获取电视剧集详情")

# 注册趋势和上映相关命令
command_factory.register_command("trending", trending_command, permission=Permission.USER, description="获取今日热门内容")
command_factory.register_command("trending_week", trending_week_command, permission=Permission.USER, description="获取本周热门内容")
command_factory.register_command("now_playing", now_playing_command, permission=Permission.USER, description="获取正在上映的电影")
command_factory.register_command("upcoming", upcoming_command, permission=Permission.USER, description="获取即将上映的电影")
command_factory.register_command("tv_airing", tv_airing_command, permission=Permission.USER, description="获取今日播出的电视剧")
command_factory.register_command("tv_on_air", tv_on_air_command, permission=Permission.USER, description="获取正在播出的电视剧")

# 注册人物搜索命令
command_factory.register_command("person", person_command, permission=Permission.USER, description="搜索人物信息")
command_factory.register_command("person_detail", person_detail_command, permission=Permission.USER, description="获取人物详情")

# 注册观看平台命令
command_factory.register_command("movie_watch", movie_watch_command, permission=Permission.USER, description="获取电影观看平台")
command_factory.register_command("tv_watch", tv_watch_command, permission=Permission.USER, description="获取电视剧观看平台")

# 注册回调处理器
command_factory.register_callback(r"^movie_", movie_callback_handler, permission=Permission.USER, description="电影搜索结果选择")
command_factory.register_callback(r"^tv_", tv_callback_handler, permission=Permission.USER, description="电视剧搜索结果选择")