import logging
import json
import asyncio
import base64
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown

# JustWatch API
try:
    from simplejustwatchapi.justwatch import search as justwatch_search
    from simplejustwatchapi.justwatch import details as justwatch_details
    from simplejustwatchapi.justwatch import offers_for_countries as justwatch_offers
    JUSTWATCH_AVAILABLE = True
except ImportError:
    JUSTWATCH_AVAILABLE = False
    logger.warning("JustWatch API 不可用，将仅使用 TMDB 观影平台数据")

from utils.command_factory import command_factory
from utils.config_manager import config_manager
from utils.country_data import SUPPORTED_COUNTRIES, get_country_flag
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
        """获取评价数据的方法，整合TMDB和Trakt的评价数据"""
        all_reviews = []
        
        # 获取TMDB评价（先中文后英文）
        chinese_reviews = await self._make_tmdb_request(f"{content_type}/{content_id}/reviews", language="zh-CN")
        if chinese_reviews and chinese_reviews.get("results"):
            all_reviews.extend(chinese_reviews["results"])
        
        # 获取英文评价
        english_reviews = await self._make_tmdb_request(f"{content_type}/{content_id}/reviews", language="en-US")
        if english_reviews and english_reviews.get("results"):
            existing_ids = {review.get("id") for review in all_reviews}
            for review in english_reviews["results"]:
                if review.get("id") not in existing_ids:
                    all_reviews.append(review)
        
        # 总是尝试获取Trakt评论数据
        try:
            # 查找对应的Trakt ID
            trakt_id = None
            if content_type == "movie":
                trakt_id = await self._find_trakt_movie_id(content_id)
            elif content_type == "tv":
                trakt_id = await self._find_trakt_tv_id(content_id)
            
            if trakt_id:
                # 获取Trakt评论
                trakt_comments = None
                if content_type == "movie":
                    trakt_comments = await self._get_trakt_movie_comments(trakt_id)
                elif content_type == "tv":
                    trakt_comments = await self._get_trakt_tv_comments(trakt_id)
                
                if trakt_comments and isinstance(trakt_comments, list):
                    # 转换Trakt评论格式为TMDB格式
                    for comment in trakt_comments:  # 获取所有Trakt评论
                        # 转换格式
                        trakt_review = {
                            "id": f"trakt_{comment.get('id', '')}",
                            "author": comment.get("user", {}).get("username", "Trakt用户"),
                            "content": comment.get("comment", ""),
                            "created_at": comment.get("created_at", ""),
                            "author_details": {
                                "rating": None  # Trakt评论不包含评分
                            },
                            "source": "trakt"  # 标记来源
                        }
                        all_reviews.append(trakt_review)
                        
        except Exception as e:
            logger.warning(f"获取Trakt评论时出错: {e}")
        
        # 构造返回数据
        if all_reviews:
            return {"results": all_reviews, "total_results": len(all_reviews)}
        return None
    
    async def _get_trakt_movie_stats(self, movie_id: int) -> Optional[Dict]:
        """获取电影在Trakt上的统计数据"""
        endpoint = f"movies/{movie_id}/stats"
        return await self._make_trakt_request(endpoint)
    
    async def _get_trakt_tv_stats(self, tv_id: int) -> Optional[Dict]:
        """获取电视剧在Trakt上的统计数据"""
        endpoint = f"shows/{tv_id}/stats"
        return await self._make_trakt_request(endpoint)
    
    async def _get_trakt_movie_comments(self, movie_id: int, sort: str = "newest", limit: int = 50) -> Optional[List]:
        """获取电影在Trakt上的评论"""
        endpoint = f"movies/{movie_id}/comments/{sort}"
        params = {"limit": limit}
        return await self._make_trakt_request(endpoint, params)
    
    async def _get_trakt_tv_comments(self, tv_id: int, sort: str = "newest", limit: int = 50) -> Optional[List]:
        """获取电视剧在Trakt上的评论"""
        endpoint = f"shows/{tv_id}/comments/{sort}"
        params = {"limit": limit}
        return await self._make_trakt_request(endpoint, params)
    
    async def _get_trakt_trending_movies(self, limit: int = 10) -> Optional[List]:
        """获取Trakt热门电影"""
        endpoint = f"movies/trending"
        params = {"limit": limit}
        return await self._make_trakt_request(endpoint, params)
    
    async def _get_trakt_trending_tv(self, limit: int = 10) -> Optional[List]:
        """获取Trakt热门电视剧"""
        endpoint = f"shows/trending"
        params = {"limit": limit}
        return await self._make_trakt_request(endpoint, params)
    
    async def _get_trakt_movie_related(self, movie_id: int, limit: int = 10) -> Optional[List]:
        """获取Trakt相关电影推荐"""
        endpoint = f"movies/{movie_id}/related"
        params = {"limit": limit}
        return await self._make_trakt_request(endpoint, params)
    
    async def _get_trakt_tv_related(self, tv_id: int, limit: int = 10) -> Optional[List]:
        """获取Trakt相关电视剧推荐"""
        endpoint = f"shows/{tv_id}/related"
        params = {"limit": limit}
        return await self._make_trakt_request(endpoint, params)
    
    async def _find_trakt_movie_id(self, tmdb_id: int) -> Optional[int]:
        """通过TMDB ID查找对应的Trakt ID"""
        endpoint = f"search/tmdb/{tmdb_id}"
        params = {"type": "movie"}
        result = await self._make_trakt_request(endpoint, params)
        if result and len(result) > 0:
            return result[0].get("movie", {}).get("ids", {}).get("trakt")
        return None
    
    async def _find_trakt_tv_id(self, tmdb_id: int) -> Optional[int]:
        """通过TMDB ID查找对应的Trakt ID"""
        endpoint = f"search/tmdb/{tmdb_id}"
        params = {"type": "show"}
        result = await self._make_trakt_request(endpoint, params)
        if result and len(result) > 0:
            return result[0].get("show", {}).get("ids", {}).get("trakt")
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
            
            # 获取Trakt统计数据
            try:
                trakt_id = await self._find_trakt_movie_id(movie_id)
                if trakt_id:
                    trakt_stats = await self._get_trakt_movie_stats(trakt_id)
                    if trakt_stats:
                        data["trakt_stats"] = trakt_stats
            except Exception as e:
                logger.warning(f"获取电影Trakt统计数据时出错: {e}")
            
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
            
            # 获取Trakt统计数据
            try:
                trakt_id = await self._find_trakt_tv_id(tv_id)
                if trakt_id:
                    trakt_stats = await self._get_trakt_tv_stats(trakt_id)
                    if trakt_stats:
                        data["trakt_stats"] = trakt_stats
            except Exception as e:
                logger.warning(f"获取电视剧Trakt统计数据时出错: {e}")
            
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
    # 流媒体平台排行榜相关方法
    # ========================================
    
    async def get_platform_trending(self, platform: str, limit: int = 15, country: str = "US") -> Optional[List]:
        """获取指定平台的热门内容排行榜 - 改进版
        Args:
            platform: 平台技术名称 (netflix, amazon, disney, hulu, max等)
            limit: 返回数量限制
            country: 国家代码
        """
        if not JUSTWATCH_AVAILABLE:
            logger.warning("JustWatch API不可用，无法获取平台排行榜")
            return None
            
        cache_key = f"platform_trending_{platform}_{country}_{limit}"
        cached_data = await cache_manager.load_cache(cache_key, subdirectory="movie")
        if cached_data:
            return cached_data
            
        try:
            search_results = []
            
            # 定义平台technical_name的所有变体（基于调试发现）
            platform_variants = {
                # Netflix 系列 (143个内容)
                "netflix": ["netflix", "netflixbasicwithads"],
                
                # Amazon 系列 (121个内容)
                "amazon": ["amazon", "amazonprime", "amazonprimevideowithads", "amazonimdbtv"],
                
                # Disney+ (2个内容 - 确实很少)
                "disneyplus": ["disneyplus"],
                
                # HBO Max/Max
                "max": ["max"],
                
                # Apple TV 系列 (70个内容)
                "itunes": ["itunes"],
                
                # Hulu
                "hulu": ["hulu"],
                
                # Paramount+ 系列 (12个内容)
                "paramountplusshowtime": ["paramountplusshowtime", "amazonparamountplus", "appletvparamountplus", "rokuchannelparamountplus"],
                
                # Peacock 系列
                "peacocktvpremium": ["peacocktvpremium"],
                
                # Roku Channel
                "rokuchannel": ["rokuchannel"],
                
                # Pluto TV (3个内容)
                "plutotv": ["plutotv"],
                
                # Tubi TV (11个内容)
                "tubitv": ["tubitv"],
                
                # Vudu/Fandango (47+6=53个内容)
                "vudu": ["vudu", "vudufree"],
                
                # Google Play Movies (31个内容)
                "play": ["play"],
                
                # YouTube 系列 (29+1=30个内容) 
                "youtube": ["youtube", "youtubefree"],
                
                # Plex 系列 (18个内容)
                "plex": ["plex", "plexplayer", "justwatchplexchannel", "plexfast"],
                
                # Starz 系列 (10个内容)
                "starz": ["starz", "amazonstarz", "appletvstarz", "rokuchannelstarz"],
                
                # AMC+ 系列 (6个内容)
                "amcplus": ["amcplus", "amazonamcplus", "appletvamcplus"],
                
                # 免费平台
                "fawesometv": ["fawesometv"],  # 16个内容
                "hoopla": ["hoopla"],  # 11个内容
                "kanopy": ["kanopy"],  # 8个内容
                "philo": ["philo"],  # 8个内容
                "fubotv": ["fubotv"],  # 8个内容
                "spectrumondemand": ["spectrumondemand"],  # 6个内容
                "ondemandkorea": ["ondemandkorea"],  # 4个内容
                "justwatchtv": ["justwatchtv"],  # 4个内容
                "viki": ["viki"],  # 3个内容
                "sundancenow": ["sundancenow"],  # 2个内容
                "mubi": ["mubi", "amazonmubi"],  # 2+2=4个内容
                "kocowa": ["kocowa", "amazonkcpglobal"],  # 2+2=4个内容
                "thecw": ["thecw"],  # 2个内容
                "cineverse": ["cineverse"],  # 2个内容
                "darkroom": ["darkroom"],  # 2个内容
                "kinofilmcollection": ["kinofilmcollection"],  # 2个内容
                "distrotv": ["distrotv"],  # 2个内容
                "mometu": ["mometu"],  # 2个内容
                "discoveryplusus": ["discoveryplusus", "amazondiscoveryplus"],  # 2+2=4个内容
                "filmzie": ["filmzie"]  # 2个内容
            }
            
            # 1. 优先使用 "new releases" 查询（显示最新上架内容）
            try:
                new_releases_results = justwatch_search("new releases", country, "en", 100, True)
                target_platforms = platform_variants.get(platform.lower(), [platform])
                
                for entry in new_releases_results:
                    has_platform = any(
                        offer.package.technical_name.lower() in [tp.lower() for tp in target_platforms]
                        for offer in entry.offers
                    )
                    
                    if has_platform:
                        search_results.append(entry)
                        
                    if len(search_results) >= limit:
                        break
                        
            except Exception as e:
                logger.warning(f"New releases查询失败: {e}")
            
            # 2. 如果新上架内容不够，使用平台名称查询作为补充
            if len(search_results) < limit:
                platform_query_names = {
                    # 主要平台
                    "netflix": ["netflix"],
                    "amazon": ["amazon prime", "prime video"],
                    "disneyplus": ["disney+", "disney plus"],
                    "max": ["hbo max", "max"],
                    "itunes": ["apple tv"],
                    "hulu": ["hulu"],
                    "paramountplusshowtime": ["paramount+", "paramount plus"],
                    "peacocktvpremium": ["peacock"],
                    "rokuchannel": ["roku channel"],
                    "plutotv": ["pluto tv"],
                    "tubitv": ["tubi"],
                    "vudu": ["vudu", "fandango at home"],
                    
                    # 新增平台
                    "play": ["google play", "google play movies"],
                    "youtube": ["youtube"],
                    "plex": ["plex"],
                    "starz": ["starz"],
                    "amcplus": ["amc+", "amc plus"],
                    "fawesometv": ["fawesome"],
                    "hoopla": ["hoopla"],
                    "kanopy": ["kanopy"],
                    "philo": ["philo"],
                    "fubotv": ["fubotv", "fubo tv"],
                    "spectrumondemand": ["spectrum on demand"],
                    "ondemandkorea": ["ondemandkorea"],
                    "viki": ["viki", "rakuten viki"],
                    "sundancenow": ["sundance now"],
                    "mubi": ["mubi"],
                    "kocowa": ["kocowa"],
                    "thecw": ["the cw", "cw"],
                    "cineverse": ["cineverse"],
                    "discoveryplusus": ["discovery+", "discovery plus"]
                }
                
                query_names = platform_query_names.get(platform.lower(), [platform])
                
                for query_name in query_names:
                    try:
                        results = justwatch_search(query_name, country, "en", 100, True)
                        target_platforms = platform_variants.get(platform.lower(), [platform])
                        
                        for entry in results:
                            has_platform = any(
                                offer.package.technical_name.lower() in [tp.lower() for tp in target_platforms]
                                for offer in entry.offers
                            )
                            
                            if has_platform:
                                # 避免重复添加
                                if not any(existing.tmdb_id == entry.tmdb_id for existing in search_results if hasattr(existing, 'tmdb_id') and hasattr(entry, 'tmdb_id')):
                                    search_results.append(entry)
                                    
                                if len(search_results) >= limit:
                                    break
                                    
                        if len(search_results) >= limit:
                            break
                            
                    except Exception as e:
                        logger.warning(f"平台查询 '{query_name}' 失败: {e}")
                        continue
            
            # 3. 如果还是不够，使用传统的"popular"方法作为最后备选
            if len(search_results) < limit:
                for media_type in ["movie", "tv"]:
                    try:
                        popular_query = f"popular {media_type}s"
                        results = justwatch_search(popular_query, country, "en", 50, True)
                        target_platforms = platform_variants.get(platform.lower(), [platform])
                        
                        for entry in results:
                            has_platform = any(
                                offer.package.technical_name.lower() in [tp.lower() for tp in target_platforms]
                                for offer in entry.offers
                            )
                            
                            if has_platform:
                                # 避免重复添加
                                if not any(existing.tmdb_id == entry.tmdb_id for existing in search_results if hasattr(existing, 'tmdb_id') and hasattr(entry, 'tmdb_id')):
                                    search_results.append(entry)
                                    
                                if len(search_results) >= limit:
                                    break
                                    
                        if len(search_results) >= limit:
                            break
                            
                    except Exception as e:
                        logger.warning(f"Popular {media_type}s查询失败: {e}")
                        continue
            
            # 按流媒体热度排序
            search_results.sort(key=lambda x: (
                x.streaming_charts.rank if x.streaming_charts else 99999,
                -(x.scoring.tmdb_popularity if x.scoring and x.scoring.tmdb_popularity else 0)
            ))
            
            final_results = search_results[:limit]
            
            if final_results:
                await cache_manager.save_cache(cache_key, final_results, subdirectory="movie")
                logger.info(f"获取 {platform} 平台内容成功: {len(final_results)} 个结果")
            else:
                logger.warning(f"未找到 {platform} 平台的内容")
            
            return final_results
            
        except Exception as e:
            logger.error(f"获取平台排行榜失败: {e}")
            return None
    
    async def get_cross_platform_charts(self, title: str, country: str = "US") -> Optional[Dict]:
        """获取内容在各平台的排名对比
        Args:
            title: 内容标题
            country: 国家代码
        """
        if not JUSTWATCH_AVAILABLE:
            return None
            
        cache_key = f"cross_platform_{title}_{country}"
        cached_data = await cache_manager.load_cache(cache_key, subdirectory="movie")
        if cached_data:
            return cached_data
            
        try:
            results = justwatch_search(title, country, "en", 5, True)
            
            if not results:
                return None
                
            # 选择第一个匹配结果
            entry = results[0]
            
            # 按平台分组统计
            platform_data = {}
            for offer in entry.offers:
                platform_name = offer.package.name
                platform_tech = offer.package.technical_name
                
                if platform_tech not in platform_data:
                    platform_data[platform_tech] = {
                        'name': platform_name,
                        'offers': [],
                        'monetization_types': set()
                    }
                
                platform_data[platform_tech]['offers'].append(offer)
                platform_data[platform_tech]['monetization_types'].add(offer.monetization_type)
            
            result = {
                'entry': entry,
                'platforms': platform_data
            }
            
            await cache_manager.save_cache(cache_key, result, subdirectory="movie")
            return result
            
        except Exception as e:
            logger.error(f"获取跨平台数据失败: {e}")
            return None

    async def get_popular_for_cross_platform(self, limit: int = 6, country: str = "US") -> Optional[List]:
        """获取适合跨平台对比的热门内容
        Args:
            limit: 返回数量限制
            country: 国家代码
        """
        if not JUSTWATCH_AVAILABLE:
            logger.warning("JustWatch API不可用，无法获取热门内容")
            return None
            
        # 暂时禁用缓存，因为JustWatch对象序列化后会丢失属性
        # cache_key = f"popular_cross_platform_{country}_{limit}"
        # cached_data = await cache_manager.load_cache(cache_key, subdirectory="movie")
        # if cached_data:
        #     return cached_data
            
        try:
            search_results = []
            
            # 搜索真正的热门内容，使用通用查询策略
            search_queries = [
                "new releases",  # 新上架内容
                "trending movies",  # 热门电影
                "trending tv shows",  # 热门剧集
                "top rated movies",  # 高评分电影
                "top rated tv",  # 高评分剧集
                "action movies",  # 流行类型
                "comedy movies",
                "drama series",
                "blockbuster movies",  # 大片
                "award winning"  # 获奖内容
            ]
            
            for query in search_queries:
                try:
                    results = justwatch_search(query, country, "en", 20, True)
                    
                    for entry in results:
                        # 只选择有多个平台支持的内容（便于跨平台对比）
                        platform_count = len(set(offer.package.technical_name for offer in entry.offers))
                        
                        # 提高质量标准：至少4个平台，且有一定评分
                        if (platform_count >= 4 and 
                            entry.scoring and 
                            ((entry.scoring.imdb_score and entry.scoring.imdb_score >= 6.0) or
                             (entry.scoring.tmdb_score and entry.scoring.tmdb_score >= 6.0))):
                            
                            # 避免重复添加
                            if not any(existing.tmdb_id == entry.tmdb_id for existing in search_results if hasattr(existing, 'tmdb_id') and hasattr(entry, 'tmdb_id')):
                                search_results.append(entry)
                                
                            if len(search_results) >= limit * 2:  # 获取更多候选
                                break
                                
                except Exception as e:
                    logger.warning(f"查询 '{query}' 失败: {e}")
                    continue
            
            # 按平台数量和评分排序，选择最适合对比的内容
            search_results.sort(key=lambda x: (
                -len(set(offer.package.technical_name for offer in x.offers)),  # 平台数量降序
                -(x.scoring.imdb_score if x.scoring and x.scoring.imdb_score else 0),  # 评分降序
                -(x.scoring.tmdb_popularity if x.scoring and x.scoring.tmdb_popularity else 0)  # 热度降序
            ))
            
            final_results = search_results[:limit]
            
            if final_results:
                # 不缓存复杂的JustWatch对象，因为序列化会丢失对象属性
                # await cache_manager.save_cache(cache_key, final_results, subdirectory="movie")
                logger.info(f"获取跨平台对比热门内容成功: {len(final_results)} 个结果")
            
            return final_results
            
        except Exception as e:
            logger.error(f"获取跨平台对比热门内容失败: {e}")
            return None

    async def get_country_trending(self, country: str, limit: int = 15) -> Optional[List]:
        """获取指定国家的热门内容排行榜
        Args:
            country: 国家代码 (US, GB, JP, KR等)
            limit: 返回数量限制
        """
        if not JUSTWATCH_AVAILABLE:
            logger.warning("JustWatch API不可用，无法获取国家排行榜")
            return None
            
        cache_key = f"country_trending_{country}_{limit}"
        cached_data = await cache_manager.load_cache(cache_key, subdirectory="movie")
        if cached_data:
            return cached_data
            
        try:
            # 使用JustWatch搜索该国家的热门内容
            search_results = []
            
            # 搜索热门关键词来获取该国家的热门内容
            popular_queries = [
                "popular", "trending", "top rated", "most watched", 
                "blockbuster", "hit movies", "best series"
            ]
            
            for query in popular_queries:
                try:
                    results = justwatch_search(query, country, "en", 20, True)
                    
                    for entry in results:
                        # 避免重复添加
                        if entry not in search_results:
                            search_results.append(entry)
                        
                        if len(search_results) >= limit * 2:  # 获取更多数据用于筛选
                            break
                            
                    if len(search_results) >= limit * 2:
                        break
                        
                except Exception as e:
                    logger.warning(f"搜索查询 '{query}' 失败: {e}")
                    continue
            
            # 按流媒体热度和评分排序
            search_results.sort(key=lambda x: (
                x.streaming_charts.rank if x.streaming_charts else 99999,
                -(x.scoring.tmdb_popularity if x.scoring and x.scoring.tmdb_popularity else 0),
                -(x.scoring.imdb_score if x.scoring and x.scoring.imdb_score else 0)
            ))
            
            # 去重 - 按标题去重
            seen_titles = set()
            unique_results = []
            for entry in search_results:
                title_key = f"{entry.title}_{entry.release_year}"
                if title_key not in seen_titles:
                    seen_titles.add(title_key)
                    unique_results.append(entry)
                    
                    if len(unique_results) >= limit:
                        break
            
            if unique_results:
                await cache_manager.save_cache(cache_key, unique_results, subdirectory="movie")
            
            return unique_results
            
        except Exception as e:
            logger.error(f"获取国家排行榜失败: {e}")
            return None

    async def get_new_releases(self, limit: int = 15, country: str = "US") -> Optional[List]:
        """获取最新上架内容"""
        if not JUSTWATCH_AVAILABLE:
            return None
            
        cache_key = f"new_releases_{country}_{limit}"
        cached_data = await cache_manager.load_cache(cache_key, subdirectory="movie")
        if cached_data:
            return cached_data
            
        try:
            # 搜索最新内容关键词
            new_queries = ["new releases", "recently added", "latest movies", "new shows"]
            search_results = []
            
            for query in new_queries:
                try:
                    results = justwatch_search(query, country, "en", 20, True)
                    search_results.extend(results)
                    if len(search_results) >= limit * 2:
                        break
                except Exception:
                    continue
            
            # 按发行日期排序（越新越前）
            search_results.sort(key=lambda x: x.release_date, reverse=True)
            
            # 去重
            seen = set()
            unique_results = []
            for entry in search_results:
                key = f"{entry.title}_{entry.release_year}"
                if key not in seen:
                    seen.add(key)
                    unique_results.append(entry)
                    if len(unique_results) >= limit:
                        break
            
            if unique_results:
                await cache_manager.save_cache(cache_key, unique_results, subdirectory="movie")
            return unique_results
            
        except Exception as e:
            logger.error(f"获取最新上架内容失败: {e}")
            return None

    async def get_high_rated_content(self, limit: int = 15, country: str = "US") -> Optional[List]:
        """获取高分内容"""
        if not JUSTWATCH_AVAILABLE:
            return None
            
        cache_key = f"high_rated_{country}_{limit}"
        cached_data = await cache_manager.load_cache(cache_key, subdirectory="movie")
        if cached_data:
            return cached_data
            
        try:
            # 搜索高分内容关键词
            high_rated_queries = ["top rated", "best movies", "highest rated", "critically acclaimed"]
            search_results = []
            
            for query in high_rated_queries:
                try:
                    results = justwatch_search(query, country, "en", 30, True)
                    search_results.extend(results)
                    if len(search_results) >= limit * 3:
                        break
                except Exception:
                    continue
            
            # 按评分排序并筛选高分内容
            filtered_results = []
            for entry in search_results:
                if entry.scoring:
                    imdb_score = entry.scoring.imdb_score or 0
                    tmdb_score = entry.scoring.tmdb_score or 0
                    if imdb_score >= 7.0 or tmdb_score >= 7.0:
                        filtered_results.append(entry)
            
            # 按评分排序
            filtered_results.sort(key=lambda x: (
                -(x.scoring.imdb_score or 0),
                -(x.scoring.tmdb_score or 0)
            ))
            
            # 去重
            seen = set()
            unique_results = []
            for entry in filtered_results:
                key = f"{entry.title}_{entry.release_year}"
                if key not in seen:
                    seen.add(key)
                    unique_results.append(entry)
                    if len(unique_results) >= limit:
                        break
            
            if unique_results:
                await cache_manager.save_cache(cache_key, unique_results, subdirectory="movie")
            return unique_results
            
        except Exception as e:
            logger.error(f"获取高分内容失败: {e}")
            return None

    async def get_rank_filtered_content(self, rank_type: str, limit: int = 15, country: str = "US") -> Optional[List]:
        """根据排名类型获取内容"""
        if not JUSTWATCH_AVAILABLE:
            return None
            
        cache_key = f"rank_filtered_{rank_type}_{country}_{limit}"
        cached_data = await cache_manager.load_cache(cache_key, subdirectory="movie")
        if cached_data:
            return cached_data
            
        try:
            search_results = []
            queries = ["popular", "trending", "top movies", "best shows"]
            
            for query in queries:
                try:
                    results = justwatch_search(query, country, "en", 50, True)
                    search_results.extend(results)
                    if len(search_results) >= limit * 3:
                        break
                except Exception:
                    continue
            
            # 根据rank_type筛选
            filtered_results = []
            for entry in search_results:
                if entry.streaming_charts:
                    charts = entry.streaming_charts
                    
                    if rank_type == "top10" and charts.rank <= 10:
                        filtered_results.append(entry)
                    elif rank_type == "top100" and charts.rank <= 100:
                        filtered_results.append(entry)
                    elif rank_type == "rising" and charts.trend == "UP":
                        filtered_results.append(entry)
                    elif rank_type == "new_entries" and charts.days_in_top_100 <= 7:
                        filtered_results.append(entry)
                    elif rank_type == "long_term" and charts.days_in_top_100 >= 30:
                        filtered_results.append(entry)
                    elif rank_type == "weekly":
                        filtered_results.append(entry)
            
            # 排序
            if rank_type == "rising":
                filtered_results.sort(key=lambda x: x.streaming_charts.trend_difference, reverse=True)
            else:
                filtered_results.sort(key=lambda x: x.streaming_charts.rank)
            
            unique_results = filtered_results[:limit]
            
            if unique_results:
                await cache_manager.save_cache(cache_key, unique_results, subdirectory="movie")
            return unique_results
            
        except Exception as e:
            logger.error(f"获取排名筛选内容失败: {e}")
            return None

    async def get_genre_trending(self, genre: str, limit: int = 15, country: str = "US") -> Optional[List]:
        """根据类型获取热门内容"""
        if not JUSTWATCH_AVAILABLE:
            return None
            
        cache_key = f"genre_trending_{genre}_{country}_{limit}"
        cached_data = await cache_manager.load_cache(cache_key, subdirectory="movie")
        if cached_data:
            return cached_data
            
        try:
            # 类型关键词映射
            genre_queries = {
                "action": ["action movies", "action films", "thriller"],
                "comedy": ["comedy movies", "funny movies", "comedies"],
                "horror": ["horror movies", "scary movies", "horror films"],
                "romance": ["romantic movies", "love stories", "romance"],
                "scifi": ["sci-fi movies", "science fiction", "sci fi"],
                "thriller": ["thriller movies", "suspense", "mystery"],
                "documentary": ["documentaries", "documentary films"],
                "family": ["family movies", "kids movies", "family friendly"]
            }
            
            queries = genre_queries.get(genre, [f"{genre} movies"])
            search_results = []
            
            for query in queries:
                try:
                    results = justwatch_search(query, country, "en", 30, True)
                    search_results.extend(results)
                    if len(search_results) >= limit * 2:
                        break
                except Exception:
                    continue
            
            # 按热度排序
            search_results.sort(key=lambda x: (
                x.streaming_charts.rank if x.streaming_charts else 99999,
                -(x.scoring.tmdb_popularity if x.scoring and x.scoring.tmdb_popularity else 0)
            ))
            
            # 去重
            seen = set()
            unique_results = []
            for entry in search_results:
                key = f"{entry.title}_{entry.release_year}"
                if key not in seen:
                    seen.add(key)
                    unique_results.append(entry)
                    if len(unique_results) >= limit:
                        break
            
            if unique_results:
                await cache_manager.save_cache(cache_key, unique_results, subdirectory="movie")
            return unique_results
            
        except Exception as e:
            logger.error(f"获取类型热门内容失败: {e}")
            return None

    async def debug_available_platforms(self, country: str = "US", limit: int = 50) -> Optional[Dict]:
        """调试：获取JustWatch中实际可用的平台technical_name"""
        if not JUSTWATCH_AVAILABLE:
            return None
            
        try:
            # 搜索热门内容来获取平台信息
            search_results = []
            queries = ["popular", "trending", "netflix", "disney", "hulu"]
            
            for query in queries:
                try:
                    results = justwatch_search(query, country, "en", 30, False)  # False获取所有选项
                    search_results.extend(results)
                    if len(search_results) >= limit:
                        break
                except Exception:
                    continue
            
            # 统计所有出现的平台
            platforms_found = {}
            for entry in search_results:
                for offer in entry.offers:
                    tech_name = offer.package.technical_name
                    display_name = offer.package.name
                    
                    if tech_name not in platforms_found:
                        platforms_found[tech_name] = {
                            'display_name': display_name,
                            'count': 0,
                            'monetization_types': set()
                        }
                    
                    platforms_found[tech_name]['count'] += 1
                    platforms_found[tech_name]['monetization_types'].add(offer.monetization_type)
            
            # 按出现次数排序
            sorted_platforms = dict(sorted(
                platforms_found.items(), 
                key=lambda x: x[1]['count'], 
                reverse=True
            ))
            
            return sorted_platforms
            
        except Exception as e:
            logger.error(f"调试平台信息失败: {e}")
            return None

    def format_debug_platforms(self, platforms_data: Dict) -> str:
        """格式化调试平台信息"""
        if not platforms_data:
            return "❌ 未找到平台信息"
        
        lines = ["🔧 *JustWatch可用平台调试信息*\n"]
        lines.append("格式: `technical_name` - 显示名称 (出现次数) [观看方式]")
        lines.append("")
        
        for tech_name, info in platforms_data.items():
            display_name = info['display_name']
            count = info['count']
            monetization = ', '.join(sorted(info['monetization_types']))
            
            lines.append(f"`{tech_name}` - {display_name} ({count}) [{monetization}]")
        
        lines.append("")
        lines.append("💡 使用上述technical_name来修正平台映射")
        
        return "\n".join(lines)

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

    async def _search_justwatch_content(self, title: str, content_type: str = "movie", region: str = "CN") -> Optional[List]:
        """通过 JustWatch API 搜索内容"""
        if not JUSTWATCH_AVAILABLE:
            return None
            
        try:
            # JustWatch 支持的国家代码 - 中国可能不被直接支持，使用美国作为默认
            # 常见的支持国家：US, GB, DE, FR, JP, KR, AU, CA 等
            if region and region.upper() in ["US", "GB", "DE", "FR", "JP", "KR", "AU", "CA"]:
                country_code = region.upper()
                language_code = "en"  # 大多数国家使用英语
            else:
                # 默认使用美国，因为它有最全的数据
                country_code = "US"
                language_code = "en"
            
            cache_key = f"justwatch_search_{title}_{content_type}_{country_code}"
            # 暂时禁用JustWatch搜索缓存读取，因为MediaEntry对象序列化会有问题
            # cached_data = await cache_manager.load_cache(cache_key, subdirectory="movie")
            # if cached_data:
            #     logger.info(f"JustWatch: 使用缓存数据，类型={type(cached_data)}")
            #     if cached_data and len(cached_data) > 0:
            #         logger.info(f"JustWatch: 缓存第1项类型={type(cached_data[0])}")
            #     return cached_data
            
            # 搜索内容 - 添加超时保护
            try:
                # 使用 asyncio.wait_for 添加超时保护
                loop = asyncio.get_event_loop()
                # 根据文档，正确的参数顺序：title, country, language, count, best_only
                results = await asyncio.wait_for(
                    loop.run_in_executor(None, justwatch_search, title, country_code, language_code, 10, False),  # 改为 False 获取所有选项
                    timeout=15.0  # 15秒超时
                )
                
            except asyncio.TimeoutError:
                logger.warning(f"JustWatch 搜索超时: {title}")
                return None
            
            if results and isinstance(results, list) and len(results) > 0:
                # 过滤匹配的内容类型
                filtered_results = []
                for item in results:
                    if not item:
                        continue
                    
                    # JustWatch 返回的是 MediaEntry 对象，不是字典
                    if hasattr(item, 'object_type'):
                        item_object_type = getattr(item, 'object_type', '').upper()
                        
                        if content_type == "movie" and item_object_type == "MOVIE":
                            filtered_results.append(item)
                        elif content_type == "tv" and item_object_type == "SHOW":
                            filtered_results.append(item)
                    else:
                        logger.warning(f"JustWatch 项目无 object_type 属性: {type(item)}")
                
                logger.info(f"JustWatch: 过滤后 {len(filtered_results)} 个结果")
                
                if filtered_results:
                    # 暂时禁用JustWatch搜索缓存，因为MediaEntry对象序列化会有问题
                    # await cache_manager.save_cache(cache_key, filtered_results, subdirectory="movie")
                    return filtered_results
            
                
        except Exception as e:
            logger.warning(f"JustWatch 搜索失败 {title}: {e}")
        
        return None

    async def _get_justwatch_offers(self, node_id: str, regions: List[str] = None) -> Optional[Dict]:
        """获取 JustWatch 观影平台信息"""
        if not JUSTWATCH_AVAILABLE or not node_id:
            return None
            
        try:
            if not regions:
                regions = ["US", "GB", "DE"]  # 默认检查美国、英国、德国（JustWatch 支持的主要地区）
                
            cache_key = f"justwatch_offers_{node_id}_{'_'.join(regions)}"
            # 暂时禁用JustWatch offers缓存，可能也有序列化问题
            # cached_data = await cache_manager.load_cache(cache_key, subdirectory="movie")
            # if cached_data:
            #     return cached_data
            
            # 获取多地区观影平台信息 - 添加超时保护
            try:
                loop = asyncio.get_event_loop()
                offers_data = await asyncio.wait_for(
                    loop.run_in_executor(None, justwatch_offers, node_id, set(regions), "en", False),  # 改为 False 获取所有选项
                    timeout=10.0  # 10秒超时
                )
            except asyncio.TimeoutError:
                logger.warning(f"JustWatch 观影平台查询超时: {node_id}")
                return None
            except Exception as e:
                logger.error(f"JustWatch offers查询异常: {e}")
                return None
            
            if offers_data and isinstance(offers_data, dict):
                # 暂时禁用JustWatch offers缓存，可能也有序列化问题
                # await cache_manager.save_cache(cache_key, offers_data, subdirectory="movie")
                return offers_data
                
        except Exception as e:
            logger.warning(f"获取 JustWatch 观影平台失败 {node_id}: {e}")
        
        return None


    async def get_enhanced_watch_providers(self, content_id: int, content_type: str = "movie", title: str = "") -> Dict:
        """获取增强的观影平台信息，整合 TMDB 和 JustWatch 数据"""
        result = {
            "tmdb": None,
            "justwatch": None,
            "combined": {}
        }
        
        try:
            # 获取 TMDB 观影平台数据
            if content_type == "movie":
                tmdb_data = await self.get_movie_watch_providers(content_id)
            else:
                tmdb_data = await self.get_tv_watch_providers(content_id)
            
            result["tmdb"] = tmdb_data
            
            # 获取 JustWatch 数据作为补充
            if JUSTWATCH_AVAILABLE and title:
                logger.info(f"JustWatch: 开始搜索 {title}")
                # 由于我们只有基本信息，创建简化的数据结构用于搜索
                search_data = {}
                if content_type == "movie":
                    search_data["original_title"] = title
                    search_data["title"] = title
                else:
                    search_data["original_name"] = title
                    search_data["name"] = title
                
                justwatch_results = await self._enhanced_justwatch_search(search_data, title, content_type)
                
                if justwatch_results and len(justwatch_results) > 0:
                    logger.info(f"JustWatch: 找到 {len(justwatch_results)} 个有效搜索结果")
                    
                    # _enhanced_justwatch_search 已经返回经过验证的结果，直接使用第一个
                    best_match = justwatch_results[0]
                    
                    logger.info(f"JustWatch: best_match = {best_match}")
                    if best_match:
                        logger.info(f"JustWatch: best_match 有 entry_id: {hasattr(best_match, 'entry_id')}")
                    
                    if best_match and hasattr(best_match, 'entry_id'):
                        entry_id = best_match.entry_id
                        logger.info(f"JustWatch: 找到 entry_id = {entry_id}")
                        
                        # 保存完整的 MediaEntry 数据（包含评分、技术规格等）
                        result["justwatch_media_entry"] = best_match
                        
                        # 支持的国家列表
                        supported_countries = {"US", "GB", "DE", "FR", "JP", "KR", "AU", "CA"}
                        
                        # 使用 offers_for_countries API 获取多国家数据
                        justwatch_data = await self._get_justwatch_offers(entry_id, list(supported_countries))
                        
                        if justwatch_data:
                            country_count = len([c for c, offers in justwatch_data.items() if offers])
                            logger.info(f"JustWatch: 获取到 {country_count} 个国家的观看数据")
                            result["justwatch"] = justwatch_data
                        else:
                            logger.info(f"JustWatch: 未获取到观看数据")
                    else:
                        logger.warning(f"JustWatch: 没有找到有效的 best_match 或缺少 entry_id")
            
            # 合并数据，优先显示 TMDB 数据，JustWatch 作为补充
            result["combined"] = self._merge_watch_providers(tmdb_data, result.get("justwatch"))
            
        except Exception as e:
            logger.error(f"获取增强观影平台数据失败: {e}")
        
        
        return result
    
    def _calculate_title_similarity(self, search_title: str, result_title: str) -> float:
        """计算标题相似度"""
        if not search_title or not result_title:
            return 0.0
        
        # 导入difflib用于相似度计算
        from difflib import SequenceMatcher
        
        # 转换为小写进行比较
        search_lower = search_title.lower().strip()
        result_lower = result_title.lower().strip()
        
        # 基本相似度
        basic_similarity = SequenceMatcher(None, search_lower, result_lower).ratio()
        
        # 如果完全匹配，返回1.0
        if search_lower == result_lower:
            return 1.0
        
        # 检查是否包含关系（一个标题包含另一个）
        if search_lower in result_lower or result_lower in search_lower:
            return max(0.6, basic_similarity)
        
        return basic_similarity
    
    def _is_likely_english(self, text: str) -> bool:
        """检测文本是否可能是英文"""
        if not text:
            return False
        
        # 简单的英文检测：如果大部分字符是ASCII，认为是英文
        ascii_chars = sum(1 for char in text if ord(char) < 128)
        total_chars = len(text)
        
        # 如果80%以上是ASCII字符，认为是英文
        return (ascii_chars / total_chars) >= 0.8 if total_chars > 0 else False
    
    def _should_use_justwatch_result(self, search_title: str, result) -> bool:
        """判断是否应该使用JustWatch结果"""
        if not result or not hasattr(result, 'title'):
            return False
        
        result_title = getattr(result, 'title', '')
        if not result_title:
            return False
        
        similarity = self._calculate_title_similarity(search_title, result_title)
        
        # 相似度阈值：
        # - 0.5+ : 很可能是正确匹配
        # - 0.3-0.5 : 可能匹配，但需要谨慎
        # - <0.3 : 很可能是错误匹配
        if similarity < 0.3:
            logger.info(f"JustWatch匹配度过低，跳过: '{search_title}' vs '{result_title}' (相似度: {similarity:.2f})")
            return False
        elif similarity < 0.5:
            logger.info(f"JustWatch匹配度较低，但仍使用: '{search_title}' vs '{result_title}' (相似度: {similarity:.2f})")
        else:
            logger.info(f"JustWatch匹配度良好: '{search_title}' vs '{result_title}' (相似度: {similarity:.2f})")
        
        return True
    
    async def _enhanced_justwatch_search(self, tmdb_data: Dict, primary_title: str, content_type: str) -> Optional[List]:
        """增强的JustWatch搜索策略 - 尝试多个标题"""
        titles_to_try = []
        
        # 从TMDB数据中提取所有可能的标题
        if content_type == "movie":
            original_title = tmdb_data.get("original_title", "")
            local_title = tmdb_data.get("title", "")
        else:
            original_title = tmdb_data.get("original_name", "")
            local_title = tmdb_data.get("name", "")
        
        # 构建搜索标题列表，按优先级排序
        # 优先级：1. 英文原标题 2. 主要标题 3. 本地化标题
        if original_title and self._is_likely_english(original_title):
            titles_to_try.append(original_title)
            if local_title and local_title != original_title:
                titles_to_try.append(local_title)
        else:
            # 如果原标题不是英文（如中文），先尝试本地标题，再尝试原标题
            if primary_title and primary_title not in titles_to_try:
                titles_to_try.append(primary_title)
            if local_title and local_title != primary_title and local_title not in titles_to_try:
                titles_to_try.append(local_title)
            if original_title and original_title not in titles_to_try:
                titles_to_try.append(original_title)
        
        # 去重并过滤空标题
        titles_to_try = [title.strip() for title in titles_to_try if title and title.strip()]
        
        logger.info(f"JustWatch: 将尝试搜索标题: {titles_to_try}")
        
        # 依次尝试每个标题
        for i, title_to_search in enumerate(titles_to_try):
            logger.info(f"JustWatch: 尝试搜索标题 {i+1}/{len(titles_to_try)}: '{title_to_search}'")
            
            try:
                results = await self._search_justwatch_content(title_to_search, content_type)
                
                if results and isinstance(results, list) and len(results) > 0:
                    # 检查是否有有效匹配
                    valid_results = []
                    for result in results:
                        if hasattr(result, 'entry_id') and self._should_use_justwatch_result(title_to_search, result):
                            valid_results.append(result)
                    
                    if valid_results:
                        logger.info(f"JustWatch: 标题 '{title_to_search}' 找到 {len(valid_results)} 个有效结果")
                        return valid_results
                    else:
                        logger.info(f"JustWatch: 标题 '{title_to_search}' 无有效匹配结果")
                else:
                    logger.info(f"JustWatch: 标题 '{title_to_search}' 无搜索结果")
                    
            except Exception as e:
                logger.warning(f"JustWatch: 搜索标题 '{title_to_search}' 时出错: {e}")
                continue
        
        logger.info(f"JustWatch: 所有标题搜索完毕，未找到有效匹配")
        return None

    def _merge_watch_providers(self, tmdb_data: Optional[Dict], justwatch_data: Optional[Dict]) -> Dict:
        """合并 TMDB 和 JustWatch 观影平台数据 - 优化版"""
        merged = {}
        
        # 如果 TMDB 有数据，优先使用
        if tmdb_data and tmdb_data.get("results"):
            merged = tmdb_data.copy()
            
        # 如果 TMDB 没有数据，使用 JustWatch 优选数据
        elif justwatch_data:
            merged = self._convert_justwatch_preferred_types(justwatch_data)
            
        # 保存原始 JustWatch 数据供后续处理
        if justwatch_data:
            merged["justwatch_raw"] = justwatch_data
            
        return merged
    
    def _convert_justwatch_to_tmdb_format(self, justwatch_data: Dict) -> Dict:
        """将 JustWatch 数据转换为 TMDB 格式"""
        if not justwatch_data:
            return {}
            
        # 创建 TMDB 格式的结构
        tmdb_format = {
            "id": 0,  # JustWatch 没有对应的 TMDB ID
            "results": {}
        }
        
        # 国家代码映射
        country_mapping = {
            "US": "US",
            "GB": "GB", 
            "DE": "DE",
            "FR": "FR",
            "JP": "JP",
            "KR": "KR",
            "AU": "AU",
            "CA": "CA"
        }
        
        # 平台类型映射
        monetization_mapping = {
            "FLATRATE": "flatrate",      # 订阅流媒体
            "SUBSCRIPTION": "flatrate",  # 订阅（另一种表示）
            "RENT": "rent",              # 租赁
            "BUY": "buy",               # 购买
            "FREE": "free",             # 免费
            "ADS": "ads",               # 广告支持免费
            "FAST": "fast",             # 免费广告支持电视
            "CINEMA": "cinema"          # 影院
        }
        
        # 转换每个国家的数据
        for country, offers in justwatch_data.items():
            if not offers or country not in country_mapping:
                continue
                
            country_code = country_mapping[country]
            country_data = {}
            
            # 按类型分组
            type_groups = {}
            for offer in offers:
                monetization_type = getattr(offer, 'monetization_type', '')
                tmdb_type = monetization_mapping.get(monetization_type)
                
                if tmdb_type and hasattr(offer, 'package') and offer.package:
                    if tmdb_type not in type_groups:
                        type_groups[tmdb_type] = []
                    
                    # 构造平台信息
                    platform_info = {
                        "display_priority": len(type_groups[tmdb_type]) + 1,
                        "logo_path": f"/justwatch_{offer.package.technical_name}.png",
                        "provider_id": getattr(offer.package, 'package_id', 0),
                        "provider_name": getattr(offer.package, 'name', 'Unknown')
                    }
                    type_groups[tmdb_type].append(platform_info)
            
            # 添加到国家数据
            for tmdb_type, platforms in type_groups.items():
                country_data[tmdb_type] = platforms
                
            if country_data:
                country_data["link"] = f"https://www.justwatch.com/{country.lower()}"
                tmdb_format["results"][country_code] = country_data
        
        return tmdb_format
    
    def _convert_justwatch_preferred_types(self, justwatch_data: Dict) -> Dict:
        """转换JustWatch数据，只显示优选类型"""
        if not justwatch_data:
            return {}
        
        # 类型优先级：免费 > 订阅 > 租赁 > 购买 > 电影院
        type_priority = ['FREE', 'ADS', 'FLATRATE', 'SUBSCRIPTION', 'RENT', 'BUY', 'CINEMA']
        
        tmdb_format = {
            "id": 0,
            "results": {}
        }
        
        # 国家代码映射
        country_mapping = {
            "US": "US",
            "GB": "GB", 
            "DE": "DE",
            "FR": "FR",
            "JP": "JP",
            "KR": "KR",
            "AU": "AU",
            "CA": "CA"
        }
        
        for country_code in country_mapping.keys():
            if country_code not in justwatch_data:
                continue
                
            offers = justwatch_data[country_code]
            if not offers or not isinstance(offers, list):
                continue
                
            # 按类型分组
            type_groups = {}
            for offer in offers:
                monetization_type = getattr(offer, 'monetization_type', '')
                if monetization_type in type_priority:
                    if monetization_type not in type_groups:
                        type_groups[monetization_type] = []
                    type_groups[monetization_type].append(offer)
            
            # 选择优先级最高的类型
            selected_type = None
            for pref_type in type_priority:
                if pref_type in type_groups:
                    selected_type = pref_type
                    break
            
            # 只转换选中的类型
            if selected_type:
                country_data = self._convert_single_type_to_tmdb(
                    type_groups[selected_type], selected_type
                )
                if country_data:
                    country_data["link"] = f"https://www.justwatch.com/{country_code.lower()}"
                    tmdb_format["results"][country_code] = country_data
        
        return tmdb_format
    
    def _convert_single_type_to_tmdb(self, offers: list, monetization_type: str) -> Dict:
        """将单一类型的JustWatch数据转换为TMDB格式"""
        if not offers:
            return {}
        
        # 平台类型映射
        monetization_mapping = {
            "FLATRATE": "flatrate",
            "SUBSCRIPTION": "flatrate",
            "RENT": "rent",
            "BUY": "buy",
            "FREE": "free",
            "ADS": "ads",
            "CINEMA": "cinema"
        }
        
        tmdb_type = monetization_mapping.get(monetization_type, "flatrate")
        platforms = []
        
        for offer in offers:
            if hasattr(offer, 'package') and offer.package:
                platform_info = {
                    "display_priority": len(platforms) + 1,
                    "logo_path": f"/justwatch_{offer.package.technical_name}.png",
                    "provider_id": getattr(offer.package, 'package_id', 0),
                    "provider_name": getattr(offer.package, 'name', 'Unknown')
                }
                platforms.append(platform_info)
        
        return {tmdb_type: platforms} if platforms else {}
    
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
        
        reviews = reviews_data["results"]
        if not reviews:
            return ""
        
        # 分别筛选TMDB和Trakt评论
        tmdb_reviews = [r for r in reviews if r.get("source", "tmdb") == "tmdb"]
        trakt_reviews = [r for r in reviews if r.get("source") == "trakt"]
        
        # 选择显示的评论：1个TMDB + 1个Trakt
        selected_reviews = []
        if tmdb_reviews:
            selected_reviews.append(tmdb_reviews[0])
        if trakt_reviews:
            selected_reviews.append(trakt_reviews[0])
        
        # 如果没有足够的评论，补充其他评论
        if len(selected_reviews) < 2:
            for review in reviews:
                if review not in selected_reviews and len(selected_reviews) < 2:
                    selected_reviews.append(review)
        
        if not selected_reviews:
            return ""
        
        lines = ["", "📝 *用户评价*:"]
        
        for i, review in enumerate(selected_reviews, 1):
            author = review.get("author", "匿名用户")
            content = review.get("content", "")
            rating = review.get("author_details", {}).get("rating")
            source = review.get("source", "tmdb")  # 默认为TMDB
            
            if content:
                # 截取评价内容，最多200字符
                content_preview = content[:200] + "..." if len(content) > 200 else content
                # 替换换行符为空格
                content_preview = content_preview.replace('\n', ' ').replace('\r', ' ')
                
                # 简单检测语言（基于字符特征）
                chinese_chars = len([c for c in content if '\u4e00' <= c <= '\u9fff'])
                is_chinese = chinese_chars > len(content) * 0.3  # 如果中文字符超过30%认为是中文
                
                # 语言标识和来源标识
                lang_flag = "🇨🇳" if is_chinese else "🇺🇸"
                source_flag = "📺" if source == "trakt" else "🎬"
                source_text = "Trakt" if source == "trakt" else "TMDB"
                
                rating_text = f" ({rating}/10)" if rating else ""
                
                lines.append(f"")
                lines.append(f"👤 *{author}*{rating_text} {lang_flag}{source_flag} _({source_text})_:")
                lines.append(f"_{content_preview}_")
        
        return "\n".join(lines) if len(lines) > 2 else ""
    
    def _format_trakt_stats(self, trakt_stats: Dict) -> str:
        """格式化Trakt统计数据"""
        if not trakt_stats:
            return ""
        
        watchers = trakt_stats.get("watchers") or 0
        plays = trakt_stats.get("plays") or 0
        collectors = trakt_stats.get("collectors") or 0
        comments = trakt_stats.get("comments") or 0
        lists = trakt_stats.get("lists") or 0
        votes = trakt_stats.get("votes") or 0
        
        # 构建统计信息行
        stats_parts = []
        
        if watchers > 0:
            stats_parts.append(f"👥 {watchers:,}人观看")
        
        if collectors > 0:
            stats_parts.append(f"⭐ {collectors:,}人收藏")
        
        if plays > 0 and plays != watchers:  # 播放次数与观看人数不同时才显示
            stats_parts.append(f"▶️ {plays:,}次播放")
        
        if comments > 0:
            stats_parts.append(f"💬 {comments}条评论")
        
        if lists > 0:
            stats_parts.append(f"📋 {lists}个清单")
        
        if votes > 0:
            stats_parts.append(f"🗳️ {votes}票")
        
        if stats_parts:
            return f"📊 *Trakt数据*: {' | '.join(stats_parts)}"
        
        return ""
    
    def format_trakt_trending_movies(self, trending_data: List) -> str:
        """格式化Trakt热门电影数据"""
        if not trending_data:
            return "❌ 暂无热门电影数据"
        
        lines = ["🔥 *Trakt热门电影榜*\n"]
        
        for i, item in enumerate(trending_data[:10], 1):
            movie = item.get("movie", {})
            title = movie.get("title", "未知标题")
            year = movie.get("year", "")
            watchers = item.get("watchers") or 0
            
            # TMDB ID用于获取详情
            tmdb_id = movie.get("ids", {}).get("tmdb")
            
            year_text = f" ({year})" if year else ""
            watchers_text = f" - 👥{watchers:,}人观看" if watchers > 0 else ""
            
            if tmdb_id:
                lines.append(f"{i}. *{title}*{year_text}{watchers_text}")
                lines.append(f"   `/movie_detail {tmdb_id}`")
            else:
                lines.append(f"{i}. *{title}*{year_text}{watchers_text}")
            
            lines.append("")
        
        lines.extend([
            "💡 *使用说明*:",
            "点击命令链接查看详情，或使用 `/movie_detail <ID>` 获取完整信息"
        ])
        
        return "\n".join(lines)
    
    def format_trakt_trending_tv(self, trending_data: List) -> str:
        """格式化Trakt热门电视剧数据"""
        if not trending_data:
            return "❌ 暂无热门电视剧数据"
        
        lines = ["🔥 *Trakt热门电视剧榜*\n"]
        
        for i, item in enumerate(trending_data[:10], 1):
            show = item.get("show", {})
            title = show.get("title", "未知标题")
            year = show.get("year", "")
            watchers = item.get("watchers") or 0
            
            # TMDB ID用于获取详情
            tmdb_id = show.get("ids", {}).get("tmdb")
            
            year_text = f" ({year})" if year else ""
            watchers_text = f" - 👥{watchers:,}人观看" if watchers > 0 else ""
            
            if tmdb_id:
                lines.append(f"{i}. *{title}*{year_text}{watchers_text}")
                lines.append(f"   `/tv_detail {tmdb_id}`")
            else:
                lines.append(f"{i}. *{title}*{year_text}{watchers_text}")
            
            lines.append("")
        
        lines.extend([
            "💡 *使用说明*:",
            "点击命令链接查看详情，或使用 `/tv_detail <ID>` 获取完整信息"
        ])
        
        return "\n".join(lines)
    
    def format_trakt_related_movies(self, related_data: List, original_title: str) -> str:
        """格式化Trakt相关电影推荐数据"""
        if not related_data:
            return f"❌ 未找到与《{original_title}》相关的电影推荐"
        
        lines = [f"🔗 *与《{original_title}》相关的电影*\n"]
        
        for i, movie in enumerate(related_data[:8], 1):
            title = movie.get("title", "未知标题")
            year = movie.get("year", "")
            
            # TMDB ID用于获取详情
            tmdb_id = movie.get("ids", {}).get("tmdb")
            
            year_text = f" ({year})" if year else ""
            
            if tmdb_id:
                lines.append(f"{i}. *{title}*{year_text}")
                lines.append(f"   `/movie_detail {tmdb_id}`")
            else:
                lines.append(f"{i}. *{title}*{year_text}")
            
            lines.append("")
        
        lines.extend([
            "💡 *使用说明*:",
            "点击命令链接查看详情，或使用 `/movie_detail <ID>` 获取完整信息"
        ])
        
        return "\n".join(lines)
    
    def format_trakt_related_tv(self, related_data: List, original_title: str) -> str:
        """格式化Trakt相关电视剧推荐数据"""
        if not related_data:
            return f"❌ 未找到与《{original_title}》相关的电视剧推荐"
        
        lines = [f"🔗 *与《{original_title}》相关的电视剧*\n"]
        
        for i, show in enumerate(related_data[:8], 1):
            title = show.get("title", "未知标题")
            year = show.get("year", "")
            
            # TMDB ID用于获取详情
            tmdb_id = show.get("ids", {}).get("tmdb")
            
            year_text = f" ({year})" if year else ""
            
            if tmdb_id:
                lines.append(f"{i}. *{title}*{year_text}")
                lines.append(f"   `/tv_detail {tmdb_id}`")
            else:
                lines.append(f"{i}. *{title}*{year_text}")
            
            lines.append("")
        
        lines.extend([
            "💡 *使用说明*:",
            "点击命令链接查看详情，或使用 `/tv_detail <ID>` 获取完整信息"
        ])
        
        return "\n".join(lines)
    
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
            source = review.get("source", "tmdb")  # 获取来源信息
            
            # 简单检测语言
            chinese_chars = len([c for c in review_content if '\u4e00' <= c <= '\u9fff'])
            is_chinese = chinese_chars > len(review_content) * 0.3
            lang_flag = "🇨🇳" if is_chinese else "🇺🇸"
            
            # 来源标识
            source_flag = "📺" if source == "trakt" else "🎬"
            source_text = "Trakt" if source == "trakt" else "TMDB"
            
            rating_text = f" ({rating}/10)" if rating else ""
            date_text = f" - {created_at[:10]}" if created_at else ""
            
            content += f"=== 评价 {i} ({source_text}) ===\n"
            content += f"👤 {author}{rating_text} {lang_flag}{source_flag} 来源: {source_text}{date_text}\n\n"
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
            source = review.get("source", "tmdb")  # 获取来源信息
            
            # 简单检测语言
            chinese_chars = len([c for c in content if '\u4e00' <= c <= '\u9fff'])
            is_chinese = chinese_chars > len(content) * 0.3
            lang_flag = "🇨🇳" if is_chinese else "🇺🇸"
            
            # 来源标识
            source_flag = "📺" if source == "trakt" else "🎬"
            source_text = "Trakt" if source == "trakt" else "TMDB"
            
            # 动态截取评价内容
            if len(content) > max_chars_per_review:
                content_preview = content[:max_chars_per_review] + "..."
                has_truncated = True
            else:
                content_preview = content
            content_preview = content_preview.replace('\n', ' ').replace('\r', ' ')
            
            rating_text = f" ({rating}/10)" if rating else ""
            
            lines.append(f"{i}. *{author}*{rating_text} {lang_flag}{source_flag} _({source_text})_:")
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
            
            year_text = f" ({year})" if year else ""
            rating_text = f" - ⭐ {vote_average:.1f}/10" if vote_average > 0 else ""
            
            lines.append(f"{i}. *{name}*{year_text}{rating_text}")
            lines.append(f"   `/tv_detail {tv_id}`")
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
        ])
        
        # 添加增强评分信息（如果有JustWatch数据）
        justwatch_entry = detail_data.get("justwatch_media_entry")
        enhanced_ratings = self._format_enhanced_ratings(detail_data, justwatch_entry)
        if enhanced_ratings:
            lines.append(enhanced_ratings)
        else:
            # 如果没有JustWatch数据，显示基础TMDB评分
            lines.append(f"⭐ *评分*: {vote_average:.1f}/10 ({vote_count:,}人评价)")
        
        # 添加流媒体热度信息
        streaming_info = self._format_streaming_charts_info(justwatch_entry)
        if streaming_info:
            lines.append(streaming_info)
        
        # 添加Trakt统计数据
        trakt_stats = detail_data.get("trakt_stats")
        if trakt_stats:
            trakt_info = self._format_trakt_stats(trakt_stats)
            if trakt_info:
                lines.append(trakt_info)
        
        lines.extend([
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
        enhanced_providers = detail_data.get("enhanced_providers")
        
        if watch_providers:
            provider_info = self.format_watch_providers_compact(watch_providers, "tv")
            if provider_info:
                lines.append(provider_info)
        
        # 添加技术规格信息
        if enhanced_providers:
            tech_specs = self._format_technical_specs(enhanced_providers)
            if tech_specs:
                lines.append(tech_specs)
            
            # 添加价格信息
            price_info = self._format_price_info(enhanced_providers)
            if price_info:
                lines.append(price_info)
            
            # 添加语言支持信息
            language_support = self._format_language_support(enhanced_providers)
            if language_support:
                lines.append(language_support)
            
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
            f"💡 使用 `/tv_related {tv_id}` 获取Trakt相关推荐",
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
            
            year_text = f" ({year})" if year else ""
            rating_text = f" - ⭐ {vote_average:.1f}/10" if vote_average > 0 else ""
            
            lines.append(f"{i}. *{title}*{year_text}{rating_text}")
            lines.append(f"   `/movie_detail {movie_id}`")
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
        ])
        
        # 添加增强评分信息（如果有JustWatch数据）
        justwatch_entry = detail_data.get("justwatch_media_entry")
        enhanced_ratings = self._format_enhanced_ratings(detail_data, justwatch_entry)
        if enhanced_ratings:
            lines.append(enhanced_ratings)
        else:
            # 如果没有JustWatch数据，显示基础TMDB评分
            lines.append(f"⭐ *评分*: {vote_average:.1f}/10 ({vote_count:,}人评价)")
        
        # 添加流媒体热度信息
        streaming_info = self._format_streaming_charts_info(justwatch_entry)
        if streaming_info:
            lines.append(streaming_info)
        
        # 添加Trakt统计数据
        trakt_stats = detail_data.get("trakt_stats")
        if trakt_stats:
            trakt_info = self._format_trakt_stats(trakt_stats)
            if trakt_info:
                lines.append(trakt_info)
        
        lines.append(f"🏢 *制作公司*: {company_text}")
        
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
        enhanced_providers = detail_data.get("enhanced_providers")
        
        if watch_providers:
            provider_info = self.format_watch_providers_compact(watch_providers, "movie")
            if provider_info:
                lines.append(provider_info)
        
        # 添加技术规格信息
        if enhanced_providers:
            tech_specs = self._format_technical_specs(enhanced_providers)
            if tech_specs:
                lines.append(tech_specs)
            
            # 添加价格信息
            price_info = self._format_price_info(enhanced_providers)
            if price_info:
                lines.append(price_info)
            
            # 添加语言支持信息
            language_support = self._format_language_support(enhanced_providers)
            if language_support:
                lines.append(language_support)
            
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
            f"💡 使用 `/movie_related {movie_id}` 获取Trakt相关推荐",
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
    # 流媒体平台排行榜格式化方法
    # ========================================
    
    def format_platform_trending(self, platform_data: List, platform_name: str) -> str:
        """格式化平台最新上架内容"""
        if not platform_data:
            return f"❌ 暂无{platform_name}平台最新内容数据"
        
        # 平台表情映射
        platform_emojis = {
            "netflix": "🔴",
            "amazon": "📦", 
            "disney": "🏰",
            "hulu": "🟢",
            "max": "🔵",
            "apple": "🍎",
            "paramount": "⭐",
            "peacock": "🦚",
            "hbo": "🎭"
        }
        
        platform_emoji = platform_emojis.get(platform_name.lower(), "📱")
        lines = [f"{platform_emoji} *{platform_name} 最新上架*\n"]
        
        for i, entry in enumerate(platform_data, 1):
            title = entry.title
            year = entry.release_year
            media_emoji = "🎬" if entry.object_type == "MOVIE" else "📺"
            
            # 获取评分信息
            rating_text = ""
            if entry.scoring:
                if entry.scoring.imdb_score:
                    rating_text = f" - ⭐ {entry.scoring.imdb_score:.1f}/10"
                elif entry.scoring.tmdb_score:
                    rating_text = f" - ⭐ {entry.scoring.tmdb_score:.1f}/10"
            
            # 获取排名信息
            rank_text = ""
            if entry.streaming_charts:
                rank_info = entry.streaming_charts
                trend_emoji = {"UP": "📈", "DOWN": "📉", "STABLE": "➡️"}.get(rank_info.trend, "")
                rank_text = f" #{rank_info.rank} {trend_emoji}"
            
            lines.append(f"{i}. {media_emoji} *{title}* ({year}){rating_text}{rank_text}")
            
            # 添加详情链接
            if entry.tmdb_id:
                if entry.object_type == "MOVIE":
                    lines.append(f"   `/movie_detail {entry.tmdb_id}`")
                elif entry.object_type == "SHOW":
                    lines.append(f"   `/tv_detail {entry.tmdb_id}`")
            
            # 添加观看选项
            monetization_types = set(offer.monetization_type for offer in entry.offers)
            if "FLATRATE" in monetization_types:
                lines.append("   🎯 订阅观看")
            elif "RENT" in monetization_types:
                rent_offers = [offer for offer in entry.offers if offer.monetization_type == "RENT"]
                if rent_offers:
                    price = rent_offers[0].price_string or "价格待查"
                    lines.append(f"   💰 租赁: {price}")
            
            lines.append("")
        
        lines.extend([
            "💡 *使用说明*:",
            "   🎬 电影详情: `/movie_detail <ID>`",
            "   📺 电视剧详情: `/tv_detail <ID>`",
            "",
            "📊 数据来源: JustWatch"
        ])
        return "\n".join(lines)
    
    def format_cross_platform_charts(self, cross_data: Dict) -> str:
        """格式化跨平台排名对比"""
        if not cross_data:
            return "❌ 暂无跨平台数据"
            
        entry = cross_data['entry']
        platforms = cross_data['platforms']
        
        lines = [f"🔄 *{entry.title}* 跨平台对比\n"]
        
        # 基本信息
        lines.append(f"📅 发行年份: {entry.release_year}")
        if entry.scoring and entry.scoring.imdb_score:
            lines.append(f"⭐ IMDb评分: {entry.scoring.imdb_score:.1f}/10")
        
        # 流媒体排名
        if entry.streaming_charts:
            charts = entry.streaming_charts
            trend_emoji = {"UP": "📈", "DOWN": "📉", "STABLE": "➡️"}.get(charts.trend, "")
            lines.append(f"📊 JustWatch排名: #{charts.rank} {trend_emoji}")
        
        lines.append("\n🎯 *观看平台*:")
        
        # 按货币化类型分组
        flatrate_platforms = []
        rent_platforms = []
        buy_platforms = []
        
        for tech_name, platform_info in platforms.items():
            platform_name = platform_info['name']
            monetization_types = platform_info['monetization_types']
            offers = platform_info['offers']
            
            if 'FLATRATE' in monetization_types:
                flatrate_platforms.append(platform_name)
            if 'RENT' in monetization_types:
                rent_offer = next((o for o in offers if o.monetization_type == 'RENT'), None)
                price = rent_offer.price_string if rent_offer else "价格待查"
                rent_platforms.append(f"{platform_name} ({price})")
            if 'BUY' in monetization_types:
                buy_offer = next((o for o in offers if o.monetization_type == 'BUY'), None)
                price = buy_offer.price_string if buy_offer else "价格待查"
                buy_platforms.append(f"{platform_name} ({price})")
        
        if flatrate_platforms:
            lines.append(f"📺 订阅观看: {', '.join(flatrate_platforms)}")
        if rent_platforms:
            lines.append(f"💰 租赁观看: {', '.join(rent_platforms)}")
        if buy_platforms:
            lines.append(f"🛒 购买观看: {', '.join(buy_platforms)}")
        
        return "\n".join(lines)

    def format_country_trending(self, country_data: List, country_name: str) -> str:
        """格式化国家热门内容排行榜"""
        if not country_data:
            return f"❌ 暂无{country_name}热门内容数据"
        
        lines = [f"🌍 *{country_name} 热门内容*\n"]
        
        for i, entry in enumerate(country_data, 1):
            title = entry.title
            year = entry.release_year
            media_emoji = "🎬" if entry.object_type == "MOVIE" else "📺"
            
            # 获取评分信息
            rating_text = ""
            if entry.scoring:
                if entry.scoring.imdb_score:
                    rating_text = f" - ⭐ {entry.scoring.imdb_score:.1f}/10"
                elif entry.scoring.tmdb_score:
                    rating_text = f" - ⭐ {entry.scoring.tmdb_score:.1f}/10"
            
            # 获取排名信息
            rank_text = ""
            if entry.streaming_charts:
                rank_info = entry.streaming_charts
                trend_emoji = {"UP": "📈", "DOWN": "📉", "STABLE": "➡️"}.get(rank_info.trend, "")
                rank_text = f" #{rank_info.rank} {trend_emoji}"
            
            lines.append(f"{i}. {media_emoji} *{title}* ({year}){rating_text}{rank_text}")
            
            # 添加观看平台信息
            if entry.offers:
                platforms = []
                for offer in entry.offers[:3]:  # 只显示前3个平台
                    platform_name = offer.package.name
                    if offer.monetization_type == "FLATRATE":
                        platforms.append(f"{platform_name}")
                    elif offer.monetization_type == "RENT" and offer.price_string:
                        platforms.append(f"{platform_name}({offer.price_string})")
                
                if platforms:
                    lines.append(f"   🎯 可观看: {', '.join(platforms)}")
            
            # 添加详情链接
            if entry.tmdb_id:
                if entry.object_type == "MOVIE":
                    lines.append(f"   `/movie_detail {entry.tmdb_id}`")
                elif entry.object_type == "SHOW":
                    lines.append(f"   `/tv_detail {entry.tmdb_id}`")
            
            lines.append("")
        
        lines.extend([
            "💡 *使用说明*:",
            "   🎬 电影详情: `/movie_detail <ID>`", 
            "   📺 电视剧详情: `/tv_detail <ID>`",
            "",
            "📊 数据来源: JustWatch"
        ])
        return "\n".join(lines)

    def format_new_releases(self, new_data: List) -> str:
        """格式化最新上架内容"""
        if not new_data:
            return "❌ 暂无最新上架内容数据"
        
        lines = ["🆕 *最新上架内容*\n"]
        
        for i, entry in enumerate(new_data, 1):
            title = entry.title
            year = entry.release_year
            media_emoji = "🎬" if entry.object_type == "MOVIE" else "📺"
            
            # 获取评分信息
            rating_text = ""
            if entry.scoring:
                if entry.scoring.imdb_score:
                    rating_text = f" - ⭐ {entry.scoring.imdb_score:.1f}/10"
                elif entry.scoring.tmdb_score:
                    rating_text = f" - ⭐ {entry.scoring.tmdb_score:.1f}/10"
            
            lines.append(f"{i}. {media_emoji} *{title}* ({year}){rating_text}")
            
            # 添加发行日期
            if entry.release_date:
                lines.append(f"   📅 上映: {entry.release_date}")
            
            # 添加详情链接
            if entry.tmdb_id:
                if entry.object_type == "MOVIE":
                    lines.append(f"   `/movie_detail {entry.tmdb_id}`")
                elif entry.object_type == "SHOW":
                    lines.append(f"   `/tv_detail {entry.tmdb_id}`")
            
            lines.append("")
        
        lines.extend([
            "💡 *使用说明*:",
            "   🎬 电影详情: `/movie_detail <ID>`",
            "   📺 电视剧详情: `/tv_detail <ID>`",
            "",
            "📊 数据来源: JustWatch"
        ])
        return "\n".join(lines)

    def format_high_rated_content(self, high_rated_data: List) -> str:
        """格式化高分内容"""
        if not high_rated_data:
            return "❌ 暂无高分内容数据"
        
        lines = ["⭐ *高分精选内容*\n"]
        
        for i, entry in enumerate(high_rated_data, 1):
            title = entry.title
            year = entry.release_year
            media_emoji = "🎬" if entry.object_type == "MOVIE" else "📺"
            
            # 获取评分信息
            rating_text = ""
            if entry.scoring:
                scores = []
                if entry.scoring.imdb_score:
                    scores.append(f"IMDb {entry.scoring.imdb_score:.1f}")
                if entry.scoring.tmdb_score:
                    scores.append(f"TMDB {entry.scoring.tmdb_score:.1f}")
                if scores:
                    rating_text = f" - ⭐ {' | '.join(scores)}"
            
            lines.append(f"{i}. {media_emoji} *{title}* ({year}){rating_text}")
            
            # 添加详情链接
            if entry.tmdb_id:
                if entry.object_type == "MOVIE":
                    lines.append(f"   `/movie_detail {entry.tmdb_id}`")
                elif entry.object_type == "SHOW":
                    lines.append(f"   `/tv_detail {entry.tmdb_id}`")
            
            lines.append("")
        
        lines.extend([
            "💡 *使用说明*:",
            "   🎬 电影详情: `/movie_detail <ID>`",
            "   📺 电视剧详情: `/tv_detail <ID>`",
            "",
            "📊 数据来源: JustWatch (评分7.0+)"
        ])
        return "\n".join(lines)

    def format_rank_filtered_content(self, rank_data: List, rank_title: str) -> str:
        """格式化排名筛选内容"""
        if not rank_data:
            return f"❌ 暂无{rank_title}数据"
        
        lines = [f"🏆 *{rank_title}*\n"]
        
        for i, entry in enumerate(rank_data, 1):
            title = entry.title
            year = entry.release_year
            media_emoji = "🎬" if entry.object_type == "MOVIE" else "📺"
            
            # 获取排名信息
            rank_info = ""
            if entry.streaming_charts:
                charts = entry.streaming_charts
                rank_info = f" #{charts.rank}"
                
                # 添加趋势信息
                if charts.trend:
                    trend_emoji = {"UP": "📈", "DOWN": "📉", "STABLE": "➡️"}.get(charts.trend, "")
                    rank_info += f" {trend_emoji}"
                    
                # 添加趋势变化
                if charts.trend_difference:
                    if charts.trend == "UP":
                        rank_info += f"(+{charts.trend_difference})"
                    elif charts.trend == "DOWN":
                        rank_info += f"(-{charts.trend_difference})"
            
            # 获取评分信息
            rating_text = ""
            if entry.scoring and entry.scoring.imdb_score:
                rating_text = f" - ⭐ {entry.scoring.imdb_score:.1f}/10"
            
            lines.append(f"{i}. {media_emoji} *{title}* ({year}){rank_info}{rating_text}")
            
            # 添加详情链接
            if entry.tmdb_id:
                if entry.object_type == "MOVIE":
                    lines.append(f"   `/movie_detail {entry.tmdb_id}`")
                elif entry.object_type == "SHOW":
                    lines.append(f"   `/tv_detail {entry.tmdb_id}`")
            
            # 添加在榜天数信息（对长期霸榜类型）
            if entry.streaming_charts and "long_term" in rank_title.lower():
                days = entry.streaming_charts.days_in_top_100
                lines.append(f"   🕒 在榜: {days}天")
            
            lines.append("")
        
        lines.extend([
            "💡 *使用说明*:",
            "   🎬 电影详情: `/movie_detail <ID>`",
            "   📺 电视剧详情: `/tv_detail <ID>`",
            "",
            "📊 数据来源: JustWatch"
        ])
        return "\n".join(lines)

    def format_genre_trending(self, genre_data: List, genre_title: str) -> str:
        """格式化类型热门内容"""
        if not genre_data:
            return f"❌ 暂无{genre_title}数据"
        
        lines = [f"🎭 *{genre_title}*\n"]
        
        for i, entry in enumerate(genre_data, 1):
            title = entry.title
            year = entry.release_year
            media_emoji = "🎬" if entry.object_type == "MOVIE" else "📺"
            
            # 获取评分信息
            rating_text = ""
            if entry.scoring:
                if entry.scoring.imdb_score:
                    rating_text = f" - ⭐ {entry.scoring.imdb_score:.1f}/10"
                elif entry.scoring.tmdb_score:
                    rating_text = f" - ⭐ {entry.scoring.tmdb_score:.1f}/10"
            
            # 获取排名信息
            rank_text = ""
            if entry.streaming_charts:
                rank_text = f" #{entry.streaming_charts.rank}"
            
            lines.append(f"{i}. {media_emoji} *{title}* ({year}){rating_text}{rank_text}")
            
            # 添加详情链接
            if entry.tmdb_id:
                if entry.object_type == "MOVIE":
                    lines.append(f"   `/movie_detail {entry.tmdb_id}`")
                elif entry.object_type == "SHOW":
                    lines.append(f"   `/tv_detail {entry.tmdb_id}`")
            
            lines.append("")
        
        lines.extend([
            "💡 *使用说明*:",
            "   🎬 电影详情: `/movie_detail <ID>`",
            "   📺 电视剧详情: `/tv_detail <ID>`",
            "",
            "📊 数据来源: JustWatch"
        ])
        return "\n".join(lines)

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
            
            year_text = f" ({year})" if year else ""
            rating_text = f" - ⭐ {vote_average:.1f}/10" if vote_average > 0 and media_type != "person" else ""
            
            lines.append(f"{i}. {emoji} *{title}*{year_text}{rating_text}")
            
            if media_type == "movie":
                lines.append(f"   `/movie_detail {item_id}`")
            elif media_type == "tv":
                lines.append(f"   `/tv_detail {item_id}`")
            elif media_type == "person":
                lines.append(f"   `/person_detail {item_id}`")
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
            rating_text = f" - ⭐ {vote_average:.1f}/10" if vote_average > 0 else ""
            
            lines.append(f"{i}. *{title}*{year_text}{rating_text}")
            lines.append(f"   `/movie_detail {movie_id}`")
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
            rating_text = f" - ⭐ {vote_average:.1f}/10" if vote_average > 0 else ""
            
            lines.append(f"{i}. *{title}*{release_text}{rating_text}")
            lines.append(f"   `/movie_detail {movie_id}`")
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
            rating_text = f" - ⭐ {vote_average:.1f}/10" if vote_average > 0 else ""
            
            lines.append(f"{i}. *{name}*{year_text}{rating_text}")
            lines.append(f"   `/tv_detail {tv_id}`")
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
            rating_text = f" - ⭐ {vote_average:.1f}/10" if vote_average > 0 else ""
            
            lines.append(f"{i}. *{name}*{year_text}{rating_text}")
            lines.append(f"   `/tv_detail {tv_id}`")
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
    
    def format_justwatch_data(self, justwatch_data: Dict) -> str:
        """格式化 JustWatch 数据"""
        if not justwatch_data:
            return ""
        
        lines = []
        
        # 使用完整的国家数据映射
        def get_country_display_name(country_code):
            """获取国家的显示名称（包含国旗和中文名）"""
            if country_code in SUPPORTED_COUNTRIES:
                country_info = SUPPORTED_COUNTRIES[country_code]
                flag = get_country_flag(country_code)
                name = country_info.get('name', country_code)
                return f"{flag} {name}"
            else:
                flag = get_country_flag(country_code)
                return f"{flag} {country_code}"
        
        # 处理 JustWatch 提供的观影平台信息
        try:
            if isinstance(justwatch_data, dict) and justwatch_data:
                lines.append("")
                lines.append("🔍 *JustWatch 数据*:")
                
                # 按国家顺序显示（优先显示主要国家）
                country_order = ['US', 'GB', 'DE', 'FR', 'JP', 'KR', 'AU', 'CA']
                displayed_countries = []
                
                for country in country_order:
                    if country in justwatch_data:
                        offers = justwatch_data[country]
                        if offers and isinstance(offers, list) and len(offers) > 0:
                            displayed_countries.append(country)
                            country_display_name = get_country_display_name(country)
                            
                            # 按观看类型分组平台信息
                            offer_types = {}
                            for offer in offers:
                                # 获取平台名称
                                platform_name = None
                                if hasattr(offer, 'package') and hasattr(offer.package, 'name'):
                                    platform_name = offer.package.name
                                elif hasattr(offer, 'package') and hasattr(offer.package, 'technical_name'):
                                    platform_name = offer.package.technical_name
                                elif hasattr(offer, 'provider_id'):
                                    platform_name = str(offer.provider_id)
                                
                                # 获取观看类型
                                monetization_type = getattr(offer, 'monetization_type', 'UNKNOWN')
                                
                                if platform_name:
                                    if monetization_type not in offer_types:
                                        offer_types[monetization_type] = []
                                    if platform_name not in offer_types[monetization_type]:
                                        offer_types[monetization_type].append(platform_name)
                            
                            # 格式化输出
                            if offer_types:
                                type_display = {
                                    'FLATRATE': '🎬 订阅观看',
                                    'SUBSCRIPTION': '🎬 订阅观看',
                                    'FREE': '🆓 免费观看',
                                    'ADS': '📺 免费含广告',
                                    'RENT': '🏪 租赁',  
                                    'BUY': '💰 购买',
                                    'CINEMA': '🎭 影院'
                                }
                                
                                lines.append(f"• **{country_display_name}**:")
                                # 按类型优先级排序显示（优先显示免费和订阅选项）
                                type_order = ['FREE', 'ADS', 'FLATRATE', 'SUBSCRIPTION', 'RENT', 'BUY', 'CINEMA']
                                for offer_type in type_order:
                                    if offer_type in offer_types:
                                        platforms = offer_types[offer_type]
                                        display_name = type_display.get(offer_type, f'📱 {offer_type}')
                                        lines.append(f"  {display_name}: {', '.join(platforms)}")
                                
                                # 显示其他未知类型
                                for offer_type, platforms in offer_types.items():
                                    if offer_type not in type_order:
                                        display_name = type_display.get(offer_type, f'📱 {offer_type}')
                                        lines.append(f"  {display_name}: {', '.join(platforms)}")
                
                # 如果没有找到任何国家的数据
                if not displayed_countries:
                    lines.append("• 暂无支持地区的观看选项")
                        
        except Exception as e:
            logger.warning(f"格式化 JustWatch 数据失败: {e}")
            # 如果解析失败，至少显示有数据可用
            if justwatch_data:
                lines.append("\n🌟 *JustWatch 补充信息*:")
                lines.append("• 有额外观看选项可用")
        
        return "\n".join(lines)

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
        lines = [f"📺 *{content_name}观看平台*"]
        lines.append("") 
        lines.append("📊 *TMDB 数据*:")
        lines.append("")
        
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
        
        # 使用完整的国家数据映射（适用于TMDB区域）
        def get_region_display_name(region_code):
            """获取区域的显示名称（包含国旗和中文名）"""
            if region_code in SUPPORTED_COUNTRIES:
                country_info = SUPPORTED_COUNTRIES[region_code]
                flag = get_country_flag(region_code)
                name = country_info.get('name', region_code)
                return f"{flag} {name}"
            else:
                flag = get_country_flag(region_code)
                return f"{flag} {region_code}"
        
        found_any = False
        for region in sorted_regions[:5]:  # 最多显示5个地区
            region_data = results[region]
            region_name = get_region_display_name(region)
            
            # 检查是否有任何观看方式
            has_content = any([
                region_data.get("flatrate"),
                region_data.get("buy"), 
                region_data.get("rent"),
                region_data.get("free"),
                region_data.get("cinema")
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
            
            # 影院上映
            if region_data.get("cinema"):
                platforms = [p["provider_name"] for p in region_data["cinema"][:3]]
                lines.append(f"🎬 *影院上映*: {', '.join(platforms)}")
            
            lines.append("")
        
        if not found_any:
            lines = [f"📺 *{content_name}观看平台*"]
            lines.append("")
            lines.append("❌ 暂无 TMDB 观看平台信息")
        
        # 检查是否有 JustWatch 数据
        justwatch_raw = providers_data.get("justwatch_raw")
        if justwatch_raw:
            justwatch_info = self.format_justwatch_data(justwatch_raw)
            if justwatch_info:
                lines.append(justwatch_info)
        
        lines.append("⚠️ 平台可用性可能因时间而变化")
        
        return "\n".join(filter(None, lines))
    
    def format_watch_providers_compact(self, providers_data: Dict, content_type: str = "movie") -> str:
        """格式化观看平台信息（简化版，用于详情页面）"""
        if not providers_data or not providers_data.get("results"):
            return ""
        
        results = providers_data["results"]
        lines = []
        
        # 扩展地区检查，按优先级排序
        priority_regions = ["CN", "US", "GB", "FR", "DE", "JP", "KR", "AU", "CA", "ES", "IT", "BE", "LU", "NL"]
        region_names = {
            "CN": "🇨🇳中国", "US": "🇺🇸美国", "GB": "🇬🇧英国", 
            "FR": "🇫🇷法国", "DE": "🇩🇪德国", "JP": "🇯🇵日本",
            "KR": "🇰🇷韩国", "AU": "🇦🇺澳大利亚", "CA": "🇨🇦加拿大",
            "ES": "🇪🇸西班牙", "IT": "🇮🇹意大利", "BE": "🇧🇪比利时",
            "LU": "🇱🇺卢森堡", "NL": "🇳🇱荷兰"
        }
        found_any = False
        
        # 按优先级寻找平台：订阅 > 免费 > 租赁 > 购买 > 影院
        platform_types = [
            ("flatrate", "📺 *观看平台*", "订阅"),
            ("free", "🆓 *免费平台*", "免费"),
            ("ads", "📺 *免费含广告*", "含广告"),
            ("rent", "🏪 *租赁平台*", "租赁"),
            ("buy", "💰 *购买平台*", "购买"),
            ("cinema", "🎬 *影院上映*", "影院")
        ]
        
        for platform_type, prefix, type_name in platform_types:
            if found_any:
                break
                
            for region in priority_regions:
                if region not in results:
                    continue
                    
                region_data = results[region]
                if not region_data.get(platform_type):
                    continue
                    
                platforms = []
                for p in region_data[platform_type][:3]:  # 最多显示3个平台
                    platform_name = p["provider_name"]
                    platforms.append(platform_name)
                
                if platforms:
                    # 获取区域的显示名称（包含国旗和中文名）
                    if region in SUPPORTED_COUNTRIES:
                        country_info = SUPPORTED_COUNTRIES[region]
                        flag = get_country_flag(region)
                        name = country_info.get('name', region)
                        region_name = f"{flag} {name}"
                    else:
                        flag = get_country_flag(region)
                        region_name = f"{flag} {region}"
                    lines.append(f"{prefix}: {', '.join(platforms)} ({region_name})")
                    found_any = True
                    break  # 找到第一个有平台的地区就停止
        
        return "\n".join(lines) if lines else ""
    
    def _format_enhanced_ratings(self, tmdb_data: Dict, justwatch_entry: any = None) -> str:
        """格式化增强评分信息（整合TMDB和JustWatch评分）"""
        lines = []
        
        # 优先使用原始TMDB评分
        tmdb_rating = tmdb_data.get("vote_average", 0)
        tmdb_votes = tmdb_data.get("vote_count", 0)
        if tmdb_rating > 0:
            lines.append(f"   • TMDB: ⭐ {tmdb_rating:.1f}/10 ({tmdb_votes:,}人评价)")
        
        # JustWatch评分数据
        if justwatch_entry and hasattr(justwatch_entry, 'scoring') and justwatch_entry.scoring:
            scoring = justwatch_entry.scoring
            
            # IMDB评分
            if scoring.imdb_score and scoring.imdb_score > 0:
                votes_text = f" ({scoring.imdb_votes:,}票)" if scoring.imdb_votes else ""
                lines.append(f"   • IMDB: ⭐ {scoring.imdb_score:.1f}/10{votes_text}")
            
            # 烂番茄评分
            if scoring.tomatometer and scoring.tomatometer > 0:
                fresh_text = " 🍅认证新鲜" if scoring.certified_fresh else ""
                lines.append(f"   • 烂番茄: 🍅 {scoring.tomatometer}%{fresh_text}")
            
            # JustWatch评分
            if scoring.jw_rating and scoring.jw_rating > 0:
                jw_score = scoring.jw_rating * 10  # 转换为10分制
                lines.append(f"   • JustWatch: ⭐ {jw_score:.1f}/10")
        
        # JustWatch用户互动
        if justwatch_entry and hasattr(justwatch_entry, 'interactions') and justwatch_entry.interactions:
            interactions = justwatch_entry.interactions
            if interactions.likes and interactions.dislikes:
                total = interactions.likes + interactions.dislikes
                like_percent = (interactions.likes / total * 100) if total > 0 else 0
                lines.append(f"   • 用户反馈: 👍 {interactions.likes:,}  👎 {interactions.dislikes:,} ({like_percent:.1f}%好评)")
        
        if lines:
            return "📊 *综合评分*:\n" + "\n".join(lines)
        return ""
    
    def _format_streaming_charts_info(self, justwatch_entry: any = None) -> str:
        """格式化流媒体热度排名信息"""
        if not justwatch_entry or not hasattr(justwatch_entry, 'streaming_charts') or not justwatch_entry.streaming_charts:
            return ""
        
        charts = justwatch_entry.streaming_charts
        lines = []
        
        # 当前排名和趋势
        if charts.rank:
            trend_emoji = {"UP": "📈", "DOWN": "📉", "STABLE": "➡️"}.get(charts.trend, "")
            trend_text = ""
            if charts.trend_difference:
                if charts.trend == "UP":
                    trend_text = f" (上升{charts.trend_difference}位)"
                elif charts.trend == "DOWN":
                    trend_text = f" (下降{charts.trend_difference}位)"
            
            lines.append(f"   • 当前排名: #{charts.rank:,} {trend_emoji}{trend_text}")
        
        # 历史最高排名
        if charts.top_rank:
            lines.append(f"   • 历史最高: #{charts.top_rank}")
        
        # 榜单停留天数
        if charts.days_in_top_10 > 0:
            lines.append(f"   • 前10榜单: {charts.days_in_top_10}天")
        elif charts.days_in_top_100 > 0:
            lines.append(f"   • 前100榜单: {charts.days_in_top_100}天")
        
        if lines:
            return "📈 *流媒体热度*:\n" + "\n".join(lines)
        return ""
    
    def _format_technical_specs(self, enhanced_providers: Dict) -> str:
        """格式化技术规格信息"""
        if not enhanced_providers or not enhanced_providers.get("justwatch"):
            return ""
        
        justwatch_data = enhanced_providers["justwatch"]
        lines = []
        specs_found = set()
        
        # 收集所有技术规格
        for country, offers in justwatch_data.items():
            if not offers:
                continue
            for offer in offers:
                # 视频技术
                if hasattr(offer, 'video_technology') and offer.video_technology:
                    specs_found.update(offer.video_technology)
                # 音频技术
                if hasattr(offer, 'audio_technology') and offer.audio_technology:
                    specs_found.update(offer.audio_technology)
        
        if specs_found:
            tech_map = {
                "DOLBY_VISION": "🎭 杜比视界",
                "DOLBY_ATMOS": "🔊 杜比全景声",
                "_4K": "📱 4K超高清",
                "HDR": "🌈 HDR",
                "HDR10": "🌈 HDR10"
            }
            tech_list = [tech_map.get(spec, spec) for spec in specs_found if spec in tech_map]
            if tech_list:
                lines.append("🎬 *技术规格*: " + " | ".join(tech_list))
        
        return "\n".join(lines) if lines else ""
    
    def _format_price_info(self, enhanced_providers: Dict) -> str:
        """格式化价格信息"""
        if not enhanced_providers or not enhanced_providers.get("justwatch"):
            return ""
        
        justwatch_data = enhanced_providers["justwatch"]
        price_info = []
        
        # 收集价格信息
        for country, offers in justwatch_data.items():
            if not offers:
                continue
            for offer in offers:
                if hasattr(offer, 'price_string') and offer.price_string:
                    platform_name = offer.package.name if hasattr(offer, 'package') and offer.package else "未知平台"
                    price_text = offer.price_string
                    
                    # 价格变化提醒
                    if hasattr(offer, 'last_change_retail_price_value') and offer.last_change_retail_price_value:
                        if offer.price_value < offer.last_change_retail_price_value:
                            change = offer.last_change_retail_price_value - offer.price_value
                            price_text += f" ↓(降${change:.2f})"
                        elif offer.price_value > offer.last_change_retail_price_value:
                            change = offer.price_value - offer.last_change_retail_price_value
                            price_text += f" ↑(涨${change:.2f})"
                    
                    price_info.append(f"{platform_name}: {price_text}")
        
        if price_info:
            return "💰 *价格信息*: " + " | ".join(price_info[:3])  # 最多显示3个
        return ""
    
    def _format_language_support(self, enhanced_providers: Dict) -> str:
        """格式化语言支持信息"""
        if not enhanced_providers or not enhanced_providers.get("justwatch"):
            return ""
        
        justwatch_data = enhanced_providers["justwatch"]
        language_info = {}
        
        # 语言代码映射
        language_map = {
            "zh": "中文", "en": "英语", "ja": "日语", "ko": "韩语",
            "fr": "法语", "de": "德语", "es": "西班牙语", "pt": "葡萄牙语",
            "it": "意大利语", "ru": "俄语", "ar": "阿拉伯语", "hi": "印地语"
        }
        
        # 收集语言信息
        for country, offers in justwatch_data.items():
            if not offers:
                continue
            for offer in offers:
                platform_name = offer.package.name if hasattr(offer, 'package') and offer.package else "未知平台"
                
                # 音频语言
                audio_langs = []
                if hasattr(offer, 'audio_languages') and offer.audio_languages:
                    audio_langs = [language_map.get(lang, lang.upper()) for lang in offer.audio_languages[:3]]
                
                # 字幕语言  
                subtitle_langs = []
                if hasattr(offer, 'subtitle_languages') and offer.subtitle_languages:
                    subtitle_langs = [language_map.get(lang, lang.upper()) for lang in offer.subtitle_languages[:3]]
                
                if audio_langs or subtitle_langs:
                    if platform_name not in language_info:
                        language_info[platform_name] = {"audio": set(), "subtitle": set()}
                    
                    language_info[platform_name]["audio"].update(audio_langs)
                    language_info[platform_name]["subtitle"].update(subtitle_langs)
        
        # 格式化输出
        if language_info:
            lines = []
            for platform, langs in list(language_info.items())[:3]:  # 最多显示3个平台
                audio_text = "/".join(sorted(langs["audio"])) if langs["audio"] else "N/A"
                subtitle_text = "/".join(sorted(langs["subtitle"])) if langs["subtitle"] else "N/A"
                lines.append(f"   • {platform}: 🗣️ {audio_text} | 🎬 {subtitle_text}字幕")
            
            if lines:
                return "🌐 *语言支持*:\n" + "\n".join(lines)
        
        return ""

# 全局服务实例
movie_service: MovieService = None

# 用户搜索会话管理
movie_search_sessions = {}
person_search_sessions = {}
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

def create_person_search_keyboard(search_data: dict) -> InlineKeyboardMarkup:
    """创建人物搜索结果的内联键盘"""
    keyboard = []
    
    # 人物选择按钮 (每行显示一个人物)
    results = search_data["results"]
    for i in range(min(len(results), 10)):  # 显示前10个结果
        person = results[i]
        person_name = person.get("name", "未知人物")
        known_for = person.get("known_for_department", "")
        
        # 截断过长的人物名称
        if len(person_name) > 35:
            person_name = person_name[:32] + "..."
            
        callback_data = f"person_select_{i}_{search_data.get('current_page', 1)}"
        display_name = f"{i + 1}. 👤 {person_name}"
        if known_for:
            display_name += f" ({known_for})"
        keyboard.append([InlineKeyboardButton(display_name, callback_data=callback_data)])
    
    # 分页控制
    current_page = search_data.get("current_page", 1)
    total_pages = search_data.get("total_pages", 1)
    
    nav_row = []
    if current_page > 1:
        nav_row.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"person_page_{current_page - 1}"))
        
    nav_row.append(InlineKeyboardButton(f"📄 {current_page}/{total_pages}", callback_data="person_page_info"))
    
    if current_page < total_pages:
        nav_row.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"person_page_{current_page + 1}"))
        
    if nav_row:
        keyboard.append(nav_row)
    
    # 操作按钮
    action_row = [
        InlineKeyboardButton("❌ 关闭", callback_data="person_close")
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

def format_person_search_results_for_keyboard(search_data: dict) -> str:
    """格式化人物搜索结果消息用于内联键盘显示"""
    if search_data.get("error"):
        return f"❌ 搜索失败: {search_data['error']}"
        
    results = search_data["results"]
    query = search_data.get("query", "")
    total_results = search_data.get("total_results", len(results))
    current_page = search_data.get("current_page", 1)
    total_pages = search_data.get("total_pages", 1)
    
    header = f"👤 **人物搜索结果**\n"
    header += f"🔍 搜索词: *{escape_markdown(query, version=2)}*\n"
    header += f"📊 找到 {total_results} 位人物\n"
    if total_pages > 1:
        header += f"📄 第 {current_page}/{total_pages} 页\n"
    header += "\n请选择要查看详情的人物:"
    
    return header

def init_movie_service():
    """初始化电影服务"""
    global movie_service
    movie_service = MovieService()

async def movie_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /movie 命令 - 搜索电影"""
    if not update.message or not update.effective_chat:
        return
    
    # 获取用户ID用于会话管理
    user_id = update.effective_user.id
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    if not context.args:
        help_text = (
            "*🎬 电影信息查询帮助*\n\n"
            "**基础查询:**\n"
            "`/movie <电影名>` - 搜索电影（按钮选择）\n"
            "`/movies <电影名>` - 搜索电影（文本列表）\n"
            "`/movie_hot` - 获取热门电影\n"
            "`/movie_detail <电影ID>` - 获取电影详情\n"
            "`/movie_rec <电影ID>` - 获取相似推荐\n"
            "`/movie_videos <电影ID>` - 获取预告片和视频\n"
            "`/movie_reviews <电影ID>` - 获取电影用户评价\n"
            "`/movie_trending` - 获取Trakt热门电影\n"
            "`/movie_related <电影ID>` - 获取Trakt相关电影推荐\n"
            "`/movie_watch <电影ID>` - 获取观看平台\n\n"
            "**热门趋势:**\n"
            "`/trending` - 今日全球热门内容\n"
            "`/trending_week` - 本周全球热门内容\n"
            "`/now_playing` - 正在上映的电影\n"
            "`/upcoming` - 即将上映的电影\n\n"
            "**示例:**\n"
            "`/movie 复仇者联盟`\n"
            "`/movies 复仇者联盟`\n"
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
            
            # 如果用户已经有活跃的搜索会话，取消旧的删除任务
            if user_id in movie_search_sessions:
                old_session = movie_search_sessions[user_id]
                old_session_id = old_session.get("session_id")
                if old_session_id:
                    from utils.message_manager import cancel_session_deletions
                    cancelled_count = await cancel_session_deletions(old_session_id, context)
                    logger.info(f"🔄 用户 {user_id} 有现有电影搜索会话，已取消 {cancelled_count} 个旧的删除任务")
            
            # 存储用户搜索会话
            movie_search_sessions[user_id] = {
                "search_data": search_data,
                "timestamp": datetime.now()
            }
            
            # 格式化搜索结果消息
            result_text = format_movie_search_results_for_keyboard(search_data)
            keyboard = create_movie_search_keyboard(search_data)
            
            # 删除搜索进度消息
            await message.delete()
            
            # 生成会话ID用于消息管理
            import time
            session_id = f"movie_search_{user_id}_{int(time.time())}"
            
            # 使用统一的消息发送API发送搜索结果
            from utils.message_manager import send_message_with_auto_delete, MessageType
            new_message = await send_message_with_auto_delete(
                context,
                update.effective_chat.id,
                foldable_text_v2(result_text),
                MessageType.SEARCH_RESULT,
                session_id=session_id,
                reply_markup=keyboard,
                parse_mode="MarkdownV2"
            )
            
            # 更新会话中的消息ID
            if new_message:
                movie_search_sessions[user_id]["message_id"] = new_message.message_id
                movie_search_sessions[user_id]["session_id"] = session_id
            
            # 删除用户命令消息
            await delete_user_command(context, update.effective_chat.id, update.message.message_id, session_id=session_id)
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
            # 获取增强的观影平台数据
            movie_title = detail_data.get("original_title") or detail_data.get("title", "")
            logger.info(f"Movie title for JustWatch search: {movie_title}")
            enhanced_providers = await movie_service.get_enhanced_watch_providers(
                movie_id, "movie", movie_title
            )
            
            # 将增强的观影平台数据合并到详情数据中
            if enhanced_providers:
                combined_providers = enhanced_providers.get("combined") or enhanced_providers.get("tmdb")
                if combined_providers:
                    detail_data["watch/providers"] = combined_providers
                
                # 传递完整的增强数据
                detail_data["enhanced_providers"] = enhanced_providers
                
                # 传递JustWatch MediaEntry数据
                if enhanced_providers.get("justwatch_media_entry"):
                    detail_data["justwatch_media_entry"] = enhanced_providers["justwatch_media_entry"]
            
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
    
    user_id = update.effective_user.id if update.effective_user else None
    if user_id:
        # 检查并取消活跃的 movie 搜索会话的删除任务
        if user_id in movie_search_sessions:
            old_session = movie_search_sessions[user_id]
            old_session_id = old_session.get("session_id")
            if old_session_id:
                from utils.message_manager import cancel_session_deletions
                cancelled_count = await cancel_session_deletions(old_session_id, context)
                logger.info(f"🔄 用户 {user_id} 执行 movie_rec，已取消 {cancelled_count} 个movie搜索会话删除任务")
    
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
        # 清理所有电影和电视剧相关缓存
        prefixes = [
            "movie_search_", "movie_popular_", "movie_detail_", "movie_rec_",
            "movie_watch_providers_",
            "tv_search_", "tv_popular_", "tv_detail_", "tv_rec_", 
            "tv_season_", "tv_episode_", "tv_watch_providers_",
            "trending_",
            "person_search_", "person_detail_",
            "justwatch_search_", "justwatch_offers_",
            # 新增charts相关缓存
            "platform_trending_", "cross_platform_", "country_trending_",
            "new_releases_", "high_rated_", "rank_filtered_", "genre_trending_"
        ]
        for prefix in prefixes:
            await cache_manager.clear_cache(subdirectory="movie", key_prefix=prefix)
        
        success_message = "✅ 所有影视内容查询缓存已清理（包括电影、电视剧、人物、观看平台、JustWatch数据、排行榜数据）。"
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
    
    # 获取用户ID用于会话管理
    user_id = update.effective_user.id
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    if not context.args:
        help_text = (
            "*📺 电视剧信息查询帮助*\n\n"
            "**基础查询:**\n"
            "`/tv <电视剧名>` - 搜索电视剧（按钮选择）\n"
            "`/tvs <电视剧名>` - 搜索电视剧（文本列表）\n"
            "`/tv_hot` - 获取热门电视剧\n"
            "`/tv_detail <电视剧ID>` - 获取电视剧详情\n"
            "`/tv_rec <电视剧ID>` - 获取相似推荐\n"
            "`/tv_videos <电视剧ID>` - 获取预告片和视频\n"
            "`/tv_reviews <电视剧ID>` - 获取电视剧用户评价\n"
            "`/tv_trending` - 获取Trakt热门电视剧\n"
            "`/tv_related <电视剧ID>` - 获取Trakt相关电视剧推荐\n"
            "`/tv_watch <电视剧ID>` - 获取观看平台\n"
            "`/tv_season <电视剧ID> <季数>` - 获取季详情\n"
            "`/tv_episode <电视剧ID> <季数> <集数>` - 获取集详情\n\n"
            "**播出信息:**\n"
            "`/tv_airing` - 今日播出的电视剧\n"
            "`/tv_on_air` - 正在播出的电视剧\n\n"
            "**示例:**\n"
            "`/tv 权力的游戏`\n"
            "`/tvs 权力的游戏`\n"
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
            
            # 如果用户已经有活跃的搜索会话，取消旧的删除任务
            if user_id in tv_search_sessions:
                old_session = tv_search_sessions[user_id]
                old_session_id = old_session.get("session_id")
                if old_session_id:
                    from utils.message_manager import cancel_session_deletions
                    cancelled_count = await cancel_session_deletions(old_session_id, context)
                    logger.info(f"🔄 用户 {user_id} 有现有电视剧搜索会话，已取消 {cancelled_count} 个旧的删除任务")
            
            # 存储用户搜索会话
            tv_search_sessions[user_id] = {
                "search_data": search_data,
                "timestamp": datetime.now()
            }
            
            # 格式化搜索结果消息
            result_text = format_tv_search_results_for_keyboard(search_data)
            keyboard = create_tv_search_keyboard(search_data)
            
            # 删除搜索进度消息
            await message.delete()
            
            # 生成会话ID用于消息管理
            import time
            session_id = f"tv_search_{user_id}_{int(time.time())}"
            
            # 使用统一的消息发送API发送搜索结果
            from utils.message_manager import send_message_with_auto_delete, MessageType
            new_message = await send_message_with_auto_delete(
                context,
                update.effective_chat.id,
                foldable_text_v2(result_text),
                MessageType.SEARCH_RESULT,
                session_id=session_id,
                reply_markup=keyboard,
                parse_mode="MarkdownV2"
            )
            
            # 更新会话中的消息ID
            if new_message:
                tv_search_sessions[user_id]["message_id"] = new_message.message_id
                tv_search_sessions[user_id]["session_id"] = session_id
            
            # 删除用户命令消息
            await delete_user_command(context, update.effective_chat.id, update.message.message_id, session_id=session_id)
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
            # 获取增强的观影平台数据
            tv_title = detail_data.get("original_name") or detail_data.get("name", "")
            logger.info(f"TV title for JustWatch search: {tv_title}")
            enhanced_providers = await movie_service.get_enhanced_watch_providers(
                tv_id, "tv", tv_title
            )
            
            # 将增强的观影平台数据合并到详情数据中
            if enhanced_providers:
                combined_providers = enhanced_providers.get("combined") or enhanced_providers.get("tmdb")
                if combined_providers:
                    detail_data["watch/providers"] = combined_providers
                
                # 传递完整的增强数据
                detail_data["enhanced_providers"] = enhanced_providers
                
                # 传递JustWatch MediaEntry数据
                if enhanced_providers.get("justwatch_media_entry"):
                    detail_data["justwatch_media_entry"] = enhanced_providers["justwatch_media_entry"]
            
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
    
    user_id = update.effective_user.id if update.effective_user else None
    if user_id:
        # 检查并取消活跃的 tv 搜索会话的删除任务
        if user_id in tv_search_sessions:
            old_session = tv_search_sessions[user_id]
            old_session_id = old_session.get("session_id")
            if old_session_id:
                from utils.message_manager import cancel_session_deletions
                cancelled_count = await cancel_session_deletions(old_session_id, context)
                logger.info(f"🔄 用户 {user_id} 执行 tv_rec，已取消 {cancelled_count} 个tv搜索会话删除任务")
    
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
    
    user_id = update.effective_user.id if update.effective_user else None
    if user_id:
        # 检查并取消活跃的 movie 搜索会话的删除任务
        if user_id in movie_search_sessions:
            old_session = movie_search_sessions[user_id]
            old_session_id = old_session.get("session_id")
            if old_session_id:
                from utils.message_manager import cancel_session_deletions
                cancelled_count = await cancel_session_deletions(old_session_id, context)
                logger.info(f"🔄 用户 {user_id} 执行 movie_videos，已取消 {cancelled_count} 个movie搜索会话删除任务")
    
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

async def movie_trending_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /movie_trending 命令 - 获取Trakt热门电影"""
    if not update.message or not update.effective_chat:
        return
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    if not movie_service:
        error_message = "❌ 电影查询服务未初始化"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        return
    
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="🔥 正在获取Trakt热门电影\.\.\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    try:
        # 获取Trakt热门电影
        trending_data = await movie_service._get_trakt_trending_movies(10)
        if trending_data:
            result_text = movie_service.format_trakt_trending_movies(trending_data)
            await message.edit_text(
                foldable_text_with_markdown_v2(result_text),
                parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            await message.edit_text("❌ 无法获取Trakt热门电影数据")
    except Exception as e:
        logger.error(f"获取Trakt热门电影失败: {e}")
        await message.edit_text("❌ 获取热门电影时发生错误")
    
    # 调度删除机器人回复消息
    from utils.message_manager import _schedule_deletion
    from utils.config_manager import get_config
    config = get_config()
    await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)

async def tv_trending_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /tv_trending 命令 - 获取Trakt热门电视剧"""
    if not update.message or not update.effective_chat:
        return
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    if not movie_service:
        error_message = "❌ 电视剧查询服务未初始化"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        return
    
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="🔥 正在获取Trakt热门电视剧\.\.\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    try:
        # 获取Trakt热门电视剧
        trending_data = await movie_service._get_trakt_trending_tv(10)
        if trending_data:
            result_text = movie_service.format_trakt_trending_tv(trending_data)
            await message.edit_text(
                foldable_text_with_markdown_v2(result_text),
                parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            await message.edit_text("❌ 无法获取Trakt热门电视剧数据")
    except Exception as e:
        logger.error(f"获取Trakt热门电视剧失败: {e}")
        await message.edit_text("❌ 获取热门电视剧时发生错误")
    
    # 调度删除机器人回复消息
    from utils.message_manager import _schedule_deletion
    from utils.config_manager import get_config
    config = get_config()
    await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)

async def movie_related_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /movie_related 命令 - 获取Trakt相关电影推荐"""
    if not update.message or not update.effective_chat:
        return
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    # 检查参数
    if not context.args or len(context.args) == 0:
        await send_error(
            context, 
            update.effective_chat.id, 
            foldable_text_v2("❌ 请提供电影ID\n\n用法: `/movie_related <电影ID>`"), 
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
        text=f"🔍 正在获取相关电影推荐 \(ID: {movie_id}\)\.\.\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    try:
        # 先获取电影基本信息用于显示标题
        movie_detail = await movie_service.get_movie_details(movie_id)
        movie_title = movie_detail.get("title", f"ID {movie_id}") if movie_detail else f"ID {movie_id}"
        
        # 获取Trakt相关推荐
        trakt_id = await movie_service._find_trakt_movie_id(movie_id)
        if trakt_id:
            related_data = await movie_service._get_trakt_movie_related(trakt_id)
            if related_data:
                result_text = movie_service.format_trakt_related_movies(related_data, movie_title)
                await message.edit_text(
                    foldable_text_with_markdown_v2(result_text),
                    parse_mode=ParseMode.MARKDOWN_V2
                )
            else:
                await message.edit_text(f"❌ 未找到电影《{movie_title}》的相关推荐")
        else:
            await message.edit_text(f"❌ 在Trakt上未找到电影《{movie_title}》")
    except Exception as e:
        logger.error(f"获取电影相关推荐失败: {e}")
        await message.edit_text("❌ 获取相关推荐时发生错误")
    
    # 调度删除机器人回复消息
    from utils.message_manager import _schedule_deletion
    from utils.config_manager import get_config
    config = get_config()
    await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)

async def tv_related_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /tv_related 命令 - 获取Trakt相关电视剧推荐"""
    if not update.message or not update.effective_chat:
        return
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    # 检查参数
    if not context.args or len(context.args) == 0:
        await send_error(
            context, 
            update.effective_chat.id, 
            foldable_text_v2("❌ 请提供电视剧ID\n\n用法: `/tv_related <电视剧ID>`"), 
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
        text=f"🔍 正在获取相关电视剧推荐 \(ID: {tv_id}\)\.\.\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    try:
        # 先获取电视剧基本信息用于显示标题
        tv_detail = await movie_service.get_tv_details(tv_id)
        tv_title = tv_detail.get("name", f"ID {tv_id}") if tv_detail else f"ID {tv_id}"
        
        # 获取Trakt相关推荐
        trakt_id = await movie_service._find_trakt_tv_id(tv_id)
        if trakt_id:
            related_data = await movie_service._get_trakt_tv_related(trakt_id)
            if related_data:
                result_text = movie_service.format_trakt_related_tv(related_data, tv_title)
                await message.edit_text(
                    foldable_text_with_markdown_v2(result_text),
                    parse_mode=ParseMode.MARKDOWN_V2
                )
            else:
                await message.edit_text(f"❌ 未找到电视剧《{tv_title}》的相关推荐")
        else:
            await message.edit_text(f"❌ 在Trakt上未找到电视剧《{tv_title}》")
    except Exception as e:
        logger.error(f"获取电视剧相关推荐失败: {e}")
        await message.edit_text("❌ 获取相关推荐时发生错误")
    
    # 调度删除机器人回复消息
    from utils.message_manager import _schedule_deletion
    from utils.config_manager import get_config
    config = get_config()
    await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)

async def movie_reviews_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /movie_reviews 命令 - 获取电影评价"""
    if not update.message or not update.effective_chat:
        return
    
    user_id = update.effective_user.id if update.effective_user else None
    if user_id:
        # 检查并取消活跃的 movie 搜索会话的删除任务
        if user_id in movie_search_sessions:
            old_session = movie_search_sessions[user_id]
            old_session_id = old_session.get("session_id")
            if old_session_id:
                from utils.message_manager import cancel_session_deletions
                cancelled_count = await cancel_session_deletions(old_session_id, context)
                logger.info(f"🔄 用户 {user_id} 执行 movie_reviews，已取消 {cancelled_count} 个movie搜索会话删除任务")
    
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
                    source = review.get("source", "tmdb")  # 获取来源信息
                    
                    # 语言检测
                    chinese_chars = len([c for c in content if '\u4e00' <= c <= '\u9fff'])
                    is_chinese = chinese_chars > len(content) * 0.3
                    lang_flag = "🇨🇳" if is_chinese else "🇺🇸"
                    
                    # 来源标识
                    source_flag = "📺" if source == "trakt" else "🎬"
                    source_text = "Trakt" if source == "trakt" else "TMDB"
                    
                    # 短预览，最多100字符
                    content_preview = content[:100] + "..." if len(content) > 100 else content
                    content_preview = content_preview.replace('\n', ' ').replace('\r', ' ')
                    
                    rating_text = f" ({rating}/10)" if rating else ""
                    preview_lines.extend([
                        f"{i}. *{author}*{rating_text} {lang_flag}{source_flag} _({source_text})_:",
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
    
    user_id = update.effective_user.id if update.effective_user else None
    if user_id:
        # 检查并取消活跃的 TV 搜索会话的删除任务
        if user_id in tv_search_sessions:
            old_session = tv_search_sessions[user_id]
            old_session_id = old_session.get("session_id")
            if old_session_id:
                from utils.message_manager import cancel_session_deletions
                cancelled_count = await cancel_session_deletions(old_session_id, context)
                logger.info(f"🔄 用户 {user_id} 执行 tv_videos，已取消 {cancelled_count} 个tv搜索会话删除任务")
    
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
    
    user_id = update.effective_user.id if update.effective_user else None
    if user_id:
        # 检查并取消活跃的 TV 搜索会话的删除任务
        if user_id in tv_search_sessions:
            old_session = tv_search_sessions[user_id]
            old_session_id = old_session.get("session_id")
            if old_session_id:
                from utils.message_manager import cancel_session_deletions
                cancelled_count = await cancel_session_deletions(old_session_id, context)
                logger.info(f"🔄 用户 {user_id} 执行 tv_reviews，已取消 {cancelled_count} 个tv搜索会话删除任务")
    
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
                    source = review.get("source", "tmdb")  # 获取来源信息
                    
                    # 语言检测
                    chinese_chars = len([c for c in content if '\u4e00' <= c <= '\u9fff'])
                    is_chinese = chinese_chars > len(content) * 0.3
                    lang_flag = "🇨🇳" if is_chinese else "🇺🇸"
                    
                    # 来源标识
                    source_flag = "📺" if source == "trakt" else "🎬"
                    source_text = "Trakt" if source == "trakt" else "TMDB"
                    
                    # 短预览，最多100字符
                    content_preview = content[:100] + "..." if len(content) > 100 else content
                    content_preview = content_preview.replace('\n', ' ').replace('\r', ' ')
                    
                    rating_text = f" ({rating}/10)" if rating else ""
                    preview_lines.extend([
                        f"{i}. *{author}*{rating_text} {lang_flag}{source_flag} _({source_text})_:",
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

async def charts_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /charts 命令 - 显示排行榜选择菜单"""
    if not update.message or not update.effective_chat:
        return
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    # 创建inline keyboard
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔥 全球热门", callback_data="chart_global_trending"),
            InlineKeyboardButton("📺 电视剧榜", callback_data="chart_tv_trending"),
            InlineKeyboardButton("🎬 电影榜", callback_data="chart_movie_trending")
        ],
        # 🎯 最热门平台 (按数据量排序)
        [
            InlineKeyboardButton("🔴 Netflix", callback_data="chart_platform_netflix"),
            InlineKeyboardButton("📦 Amazon", callback_data="chart_platform_amazon"),
            InlineKeyboardButton("🍎 Apple TV", callback_data="chart_platform_itunes")
        ],
        [
            InlineKeyboardButton("🎬 Vudu", callback_data="chart_platform_vudu"),
            InlineKeyboardButton("▶️ YouTube", callback_data="chart_platform_youtube"),
            InlineKeyboardButton("🏰 Disney+", callback_data="chart_platform_disney")
        ],
        [
            InlineKeyboardButton("🔵 HBO Max", callback_data="chart_platform_max"),
            InlineKeyboardButton("⭐ Paramount+", callback_data="chart_platform_paramount"),
            InlineKeyboardButton("🟢 Hulu", callback_data="chart_platform_hulu")
        ],
        [
            InlineKeyboardButton("🎵 更多订阅平台", callback_data="chart_subscription_platforms"),
            InlineKeyboardButton("🆓 免费平台", callback_data="chart_free_platforms"),
            InlineKeyboardButton("🛒 租赁平台", callback_data="chart_rental_platforms")
        ],
        [
            InlineKeyboardButton("🏆 排名专区", callback_data="chart_rank_zone"),
            InlineKeyboardButton("🎭 类型专区", callback_data="chart_genre_zone")
        ],
        [
            InlineKeyboardButton("🆕 最新上架", callback_data="chart_new_releases"),
            InlineKeyboardButton("⭐ 高分内容", callback_data="chart_high_rated")
        ],
        [
            InlineKeyboardButton("🌍 按国家查看", callback_data="chart_by_country"),
            InlineKeyboardButton("🔄 跨平台对比", callback_data="chart_cross_platform")
        ],
        [
            InlineKeyboardButton("❌ 关闭", callback_data="chart_close"),
            InlineKeyboardButton("🔧 调试平台", callback_data="chart_debug_platforms")
        ]
    ])
    
    message_text = (
        "🏆 *流媒体排行榜中心*\n\n"
        "选择你想查看的排行榜类型：\n\n"
        "📊 **热门榜单**：全球热门内容\n"
        "🎯 **平台专属**：各流媒体平台最新上架内容\n"
        "🌐 **地区排行**：不同国家地区的热门内容\n"
        "🔍 **跨平台对比**：查看内容在各平台的情况"
    )
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=foldable_text_with_markdown_v2(message_text),
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN_V2
    )

async def charts_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理排行榜选择回调"""
    query = update.callback_query
    if not query or not query.data:
        return
        
    await query.answer()
    callback_data = query.data
    
    if not movie_service:
        await query.edit_message_text("❌ 电影查询服务未初始化")
        return
    
    async def schedule_chart_deletion():
        """为charts消息调度删除"""
        try:
            from utils.message_manager import _schedule_deletion
            from utils.config_manager import get_config
            config = get_config()
            await _schedule_deletion(context, query.message.chat_id, query.message.message_id, config.auto_delete_delay)
        except Exception as e:
            logger.warning(f"调度删除charts消息失败: {e}")
    
    try:
        if callback_data == "chart_global_trending":
            # 全球热门内容
            await query.edit_message_text("🔍 正在获取全球热门内容...")
            trending_data = await movie_service.get_trending_content("all", "day")
            if trending_data:
                result_text = movie_service.format_trending_content(trending_data, "day")
                await query.edit_message_text(
                    foldable_text_with_markdown_v2(result_text),
                    parse_mode=ParseMode.MARKDOWN_V2
                )
                await schedule_chart_deletion()
            else:
                await query.edit_message_text("❌ 获取全球热门内容失败")
                
        elif callback_data == "chart_tv_trending":
            # 热门电视剧
            await query.edit_message_text("🔍 正在获取热门电视剧...")
            trending_data = await movie_service._get_trakt_trending_tv(15)
            if trending_data:
                result_text = movie_service.format_trakt_trending_tv(trending_data)
                await query.edit_message_text(
                    foldable_text_with_markdown_v2(result_text),
                    parse_mode=ParseMode.MARKDOWN_V2
                )
                await schedule_chart_deletion()
            else:
                await query.edit_message_text("❌ 获取热门电视剧失败")
                
        elif callback_data == "chart_movie_trending":
            # 热门电影
            await query.edit_message_text("🔍 正在获取热门电影...")
            trending_data = await movie_service._get_trakt_trending_movies(15)
            if trending_data:
                result_text = movie_service.format_trakt_trending_movies(trending_data)
                await query.edit_message_text(
                    foldable_text_with_markdown_v2(result_text),
                    parse_mode=ParseMode.MARKDOWN_V2
                )
                await schedule_chart_deletion()
            else:
                await query.edit_message_text("❌ 获取热门电影失败")
                
        elif callback_data.startswith("chart_platform_"):
            # 平台专属排行榜
            platform = callback_data.replace("chart_platform_", "")
            platform_names = {
                "netflix": "Netflix",
                "amazon": "Amazon Prime", 
                "disneyplus": "Disney+",  # 修正：Disney+的正确technical_name
                "max": "HBO Max",
                "itunes": "Apple TV",
                "hulu": "Hulu",
                "paramountplusshowtime": "Paramount+",  # 修正：Paramount+的主要technical_name
                "peacocktvpremium": "Peacock",  # 修正：Peacock的正确technical_name
                "rokuchannel": "Roku Channel",
                "plutotv": "Pluto TV",
                "tubitv": "Tubi TV",  # 修正：Tubi的正确technical_name
                "vudu": "Vudu"
            }
            
            # 修正platform映射
            platform_mapping = {
                "apple": "itunes",  # Apple TV按钮映射到itunes
                "disney": "disneyplus",  # Disney+映射到正确的technical_name
                "paramount": "paramountplusshowtime",  # Paramount+映射到主要版本
                "peacock": "peacocktvpremium",  # Peacock映射到正确的technical_name
                "tubi": "tubitv",  # Tubi映射到正确的technical_name
            }
            
            actual_platform = platform_mapping.get(platform, platform)
            platform_display = platform_names.get(actual_platform, actual_platform.title())
            await query.edit_message_text(f"🔍 正在获取{platform_display}排行榜...")
            
            platform_data = await movie_service.get_platform_trending(actual_platform, limit=15)
            if platform_data:
                result_text = movie_service.format_platform_trending(platform_data, platform_display)
                await query.edit_message_text(
                    foldable_text_with_markdown_v2(result_text),
                    parse_mode=ParseMode.MARKDOWN_V2
                )
                await schedule_chart_deletion()
            else:
                # 如果失败，尝试其他可能的technical_name
                alternative_names = {
                    "disneyplus": ["disney"],  # Disney+的备用名称
                    "paramountplusshowtime": ["amazonparamountplus", "appletvparamountplus", "rokuchannelparamountplus"],  # Paramount+的其他渠道
                    "peacocktvpremium": ["peacock"],  # Peacock的可能备用名称
                    "hulu": ["hulupluspremium", "hulu"]  # Hulu可能的名称（虽然没在结果中看到）
                }
                
                tried_alternatives = False
                if actual_platform in alternative_names:
                    for alt_name in alternative_names[actual_platform]:
                        if alt_name != actual_platform:  # 避免重复尝试
                            alt_data = await movie_service.get_platform_trending(alt_name, limit=15)
                            if alt_data:
                                result_text = movie_service.format_platform_trending(alt_data, platform_display)
                                await query.edit_message_text(
                                    foldable_text_with_markdown_v2(result_text),
                                    parse_mode=ParseMode.MARKDOWN_V2
                                )
                                await schedule_chart_deletion()
                                tried_alternatives = True
                                break
                
                if not tried_alternatives:
                    await query.edit_message_text(
                        f"❌ 获取{platform_display}排行榜失败\n\n"
                        f"可能的原因：\n"
                        f"• 该平台在当前地区没有足够的热门内容\n"
                        f"• 平台名称映射需要调整 (当前尝试: `{actual_platform}`)\n"
                        f"• JustWatch API中该平台的technical_name可能不同\n\n"
                        f"💡 请尝试其他平台或稍后再试"
                    )
                
        elif callback_data == "chart_cross_platform":
            # 跨平台对比 - 动态获取热门内容
            await query.edit_message_text("🔍 正在获取热门内容...")
            
            try:
                popular_content = await movie_service.get_popular_for_cross_platform(6)
                
                if popular_content and len(popular_content) >= 4:
                    # 动态创建按钮
                    buttons = []
                    for i, entry in enumerate(popular_content[:6]):  # 最多6个
                        media_emoji = "🎬" if entry.object_type == "MOVIE" else "📺"
                        title = entry.title
                        # 限制标题长度，避免按钮过长
                        display_title = title if len(title) <= 12 else title[:12] + "..."
                        # 将标题编码到callback_data中，避免TMDB ID混淆
                        # 使用base64编码标题以避免特殊字符问题
                        encoded_title = base64.b64encode(title.encode('utf-8')).decode('ascii')
                        callback_data = f"chart_compare_title_{encoded_title}"
                        
                        button = InlineKeyboardButton(
                            f"{media_emoji} {display_title}", 
                            callback_data=callback_data
                        )
                        
                        # 每行放2个按钮
                        if i % 2 == 0:
                            buttons.append([button])
                        else:
                            buttons[-1].append(button)
                    
                    # 添加自定义搜索和返回按钮
                    buttons.append([
                        InlineKeyboardButton("🎨 自定义搜索", callback_data="chart_compare_custom")
                    ])
                    buttons.append([
                        InlineKeyboardButton("🔙 返回主菜单", callback_data="chart_main_menu")
                    ])
                    
                    cross_platform_keyboard = InlineKeyboardMarkup(buttons)
                    
                    await query.edit_message_text(
                        "🔍 *跨平台对比*\n\n"
                        "选择当前热门内容快速查看跨平台情况：\n\n"
                        "💡 这些是有多个平台支持的热门内容",
                        reply_markup=cross_platform_keyboard,
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
                else:
                    # 如果动态获取失败，使用备用的静态选项
                    fallback_keyboard = InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("🎬 Avatar", callback_data="chart_compare_Avatar"),
                            InlineKeyboardButton("🎭 Inception", callback_data="chart_compare_Inception")
                        ],
                        [
                            InlineKeyboardButton("📺 Breaking Bad", callback_data="chart_compare_Breaking Bad"),
                            InlineKeyboardButton("🦸 Avengers", callback_data="chart_compare_Avengers")
                        ],
                        [
                            InlineKeyboardButton("🎨 自定义搜索", callback_data="chart_compare_custom")
                        ],
                        [
                            InlineKeyboardButton("🔙 返回主菜单", callback_data="chart_main_menu")
                        ]
                    ])
                    
                    await query.edit_message_text(
                        "🔍 *跨平台对比*\n\n"
                        "选择内容快速查看跨平台情况：",
                        reply_markup=fallback_keyboard,
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
                    
            except Exception as e:
                logger.error(f"获取动态热门内容失败: {e}")
                await query.edit_message_text("❌ 获取热门内容失败，请稍后重试")
            
        elif callback_data == "chart_rank_zone":
            # 排名专区选择
            rank_keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🥇 Top 10", callback_data="chart_rank_top10"),
                    InlineKeyboardButton("🏅 Top 100", callback_data="chart_rank_top100")
                ],
                [
                    InlineKeyboardButton("📈 上升最快", callback_data="chart_rank_rising"),
                    InlineKeyboardButton("🔥 新入榜", callback_data="chart_rank_new_entries")
                ],
                [
                    InlineKeyboardButton("👑 长期霸榜", callback_data="chart_rank_long_term"),
                    InlineKeyboardButton("🎯 本周热门", callback_data="chart_rank_weekly")
                ],
                [
                    InlineKeyboardButton("🔙 返回主菜单", callback_data="chart_main_menu")
                ]
            ])
            
            await query.edit_message_text(
                "🏆 *排名专区*\n\n选择你想查看的排名类型：",
                reply_markup=rank_keyboard,
                parse_mode=ParseMode.MARKDOWN_V2
            )
            
        elif callback_data == "chart_genre_zone":
            # 类型专区选择
            genre_keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🎬 动作片", callback_data="chart_genre_action"),
                    InlineKeyboardButton("😂 喜剧片", callback_data="chart_genre_comedy"),
                    InlineKeyboardButton("😱 恐怖片", callback_data="chart_genre_horror")
                ],
                [
                    InlineKeyboardButton("💝 爱情片", callback_data="chart_genre_romance"),
                    InlineKeyboardButton("🚀 科幻片", callback_data="chart_genre_scifi"),
                    InlineKeyboardButton("🕵️ 悬疑片", callback_data="chart_genre_thriller")
                ],
                [
                    InlineKeyboardButton("📚 纪录片", callback_data="chart_genre_documentary"),
                    InlineKeyboardButton("👨‍👩‍👧‍👦 家庭片", callback_data="chart_genre_family")
                ],
                [
                    InlineKeyboardButton("🔙 返回主菜单", callback_data="chart_main_menu")
                ]
            ])
            
            await query.edit_message_text(
                "🎭 *类型专区*\n\n选择你想查看的内容类型：",
                reply_markup=genre_keyboard,
                parse_mode=ParseMode.MARKDOWN_V2
            )
            
        elif callback_data == "chart_new_releases":
            # 最新上架内容
            await query.edit_message_text("🔍 正在获取最新上架内容...")
            
            new_releases = await movie_service.get_new_releases(limit=15)
            if new_releases:
                result_text = movie_service.format_new_releases(new_releases)
                await query.edit_message_text(
                    foldable_text_with_markdown_v2(result_text),
                    parse_mode=ParseMode.MARKDOWN_V2
                )
                await schedule_chart_deletion()
            else:
                await query.edit_message_text("❌ 获取最新上架内容失败")
                
        elif callback_data == "chart_high_rated":
            # 高分内容
            await query.edit_message_text("🔍 正在获取高分内容...")
            
            high_rated = await movie_service.get_high_rated_content(limit=15)
            if high_rated:
                result_text = movie_service.format_high_rated_content(high_rated)
                await query.edit_message_text(
                    foldable_text_with_markdown_v2(result_text),
                    parse_mode=ParseMode.MARKDOWN_V2
                )
                await schedule_chart_deletion()
            else:
                await query.edit_message_text("❌ 获取高分内容失败")
                
        elif callback_data.startswith("chart_rank_"):
            # 排名专区处理
            rank_type = callback_data.replace("chart_rank_", "")
            rank_titles = {
                "top10": "🥇 JustWatch Top 10",
                "top100": "🏅 JustWatch Top 100", 
                "rising": "📈 上升最快内容",
                "new_entries": "🔥 新入榜内容",
                "long_term": "👑 长期霸榜内容",
                "weekly": "🎯 本周热门内容"
            }
            
            rank_title = rank_titles.get(rank_type, "排行榜")
            await query.edit_message_text(f"🔍 正在获取{rank_title}...")
            
            rank_data = await movie_service.get_rank_filtered_content(rank_type, limit=15)
            if rank_data:
                result_text = movie_service.format_rank_filtered_content(rank_data, rank_title)
                await query.edit_message_text(
                    foldable_text_with_markdown_v2(result_text),
                    parse_mode=ParseMode.MARKDOWN_V2
                )
                await schedule_chart_deletion()
            else:
                await query.edit_message_text(f"❌ 获取{rank_title}失败")
                
        elif callback_data.startswith("chart_genre_"):
            # 类型专区处理
            genre = callback_data.replace("chart_genre_", "")
            genre_titles = {
                "action": "🎬 动作片热门",
                "comedy": "😂 喜剧片热门",
                "horror": "😱 恐怖片热门",
                "romance": "💝 爱情片热门", 
                "scifi": "🚀 科幻片热门",
                "thriller": "🕵️ 悬疑片热门",
                "documentary": "📚 纪录片热门",
                "family": "👨‍👩‍👧‍👦 家庭片热门"
            }
            
            genre_title = genre_titles.get(genre, f"{genre.title()}热门")
            await query.edit_message_text(f"🔍 正在获取{genre_title}...")
            
            genre_data = await movie_service.get_genre_trending(genre, limit=15)
            if genre_data:
                result_text = movie_service.format_genre_trending(genre_data, genre_title)
                await query.edit_message_text(
                    foldable_text_with_markdown_v2(result_text),
                    parse_mode=ParseMode.MARKDOWN_V2
                )
                await schedule_chart_deletion()
            else:
                await query.edit_message_text(f"❌ 获取{genre_title}失败")
                
        elif callback_data == "chart_by_country":
            # 按国家查看 - 显示国家选择
            country_keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🇺🇸 美国", callback_data="chart_country_US"),
                    InlineKeyboardButton("🇬🇧 英国", callback_data="chart_country_GB"),
                    InlineKeyboardButton("🇯🇵 日本", callback_data="chart_country_JP")
                ],
                [
                    InlineKeyboardButton("🇰🇷 韩国", callback_data="chart_country_KR"),
                    InlineKeyboardButton("🇫🇷 法国", callback_data="chart_country_FR"),
                    InlineKeyboardButton("🇩🇪 德国", callback_data="chart_country_DE")
                ],
                [
                    InlineKeyboardButton("🇨🇦 加拿大", callback_data="chart_country_CA"),
                    InlineKeyboardButton("🇦🇺 澳大利亚", callback_data="chart_country_AU"),
                    InlineKeyboardButton("🇧🇷 巴西", callback_data="chart_country_BR")
                ],
                [
                    InlineKeyboardButton("🔙 返回主菜单", callback_data="chart_main_menu")
                ]
            ])
            
            await query.edit_message_text(
                "🌍 *选择国家/地区*\n\n选择你想查看的国家或地区的热门内容：",
                reply_markup=country_keyboard,
                parse_mode=ParseMode.MARKDOWN_V2
            )
            
        elif callback_data.startswith("chart_country_"):
            # 国家/地区热门内容 - 使用JustWatch按国家查看
            country = callback_data.replace("chart_country_", "")
            country_names = {
                "US": "🇺🇸 美国", "GB": "🇬🇧 英国", "JP": "🇯🇵 日本",
                "KR": "🇰🇷 韩国", "FR": "🇫🇷 法国", "DE": "🇩🇪 德国",
                "CA": "🇨🇦 加拿大", "AU": "🇦🇺 澳大利亚", "BR": "🇧🇷 巴西"
            }
            
            country_display = country_names.get(country, country)
            await query.edit_message_text(f"🔍 正在获取{country_display}热门内容...")
            
            # 使用JustWatch获取该国家的热门内容
            country_trending = await movie_service.get_country_trending(country, limit=15)
            if country_trending:
                result_text = movie_service.format_country_trending(country_trending, country_display)
                await query.edit_message_text(
                    foldable_text_with_markdown_v2(result_text),
                    parse_mode=ParseMode.MARKDOWN_V2
                )
                await schedule_chart_deletion()
            else:
                await query.edit_message_text(f"❌ 获取{country_display}热门内容失败")
                
        elif callback_data == "chart_main_menu":
            # 返回主菜单 - 直接编辑消息显示主菜单
            # 创建主菜单keyboard
            main_keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🔥 全球热门", callback_data="chart_global_trending"),
                    InlineKeyboardButton("📺 电视剧榜", callback_data="chart_tv_trending"),
                    InlineKeyboardButton("🎬 电影榜", callback_data="chart_movie_trending")
                ],
                # 🎯 最热门平台 (按数据量排序)
                [
                    InlineKeyboardButton("🔴 Netflix", callback_data="chart_platform_netflix"),
                    InlineKeyboardButton("📦 Amazon", callback_data="chart_platform_amazon"),
                    InlineKeyboardButton("🍎 Apple TV", callback_data="chart_platform_itunes")
                ],
                [
                    InlineKeyboardButton("🎬 Vudu", callback_data="chart_platform_vudu"),
                    InlineKeyboardButton("▶️ YouTube", callback_data="chart_platform_youtube"),
                    InlineKeyboardButton("🏰 Disney+", callback_data="chart_platform_disney")
                ],
                [
                    InlineKeyboardButton("🔵 HBO Max", callback_data="chart_platform_max"),
                    InlineKeyboardButton("⭐ Paramount+", callback_data="chart_platform_paramount"),
                    InlineKeyboardButton("🟢 Hulu", callback_data="chart_platform_hulu")
                ],
                [
                    InlineKeyboardButton("🎵 更多订阅平台", callback_data="chart_subscription_platforms"),
                    InlineKeyboardButton("🆓 免费平台", callback_data="chart_free_platforms"),
                    InlineKeyboardButton("🛒 租赁平台", callback_data="chart_rental_platforms")
                ],
                [
                    InlineKeyboardButton("🏆 排名专区", callback_data="chart_rank_zone"),
                    InlineKeyboardButton("🎭 类型专区", callback_data="chart_genre_zone")
                ],
                [
                    InlineKeyboardButton("🆕 最新上架", callback_data="chart_new_releases"),
                    InlineKeyboardButton("⭐ 高分内容", callback_data="chart_high_rated")
                ],
                [
                    InlineKeyboardButton("🌍 按国家查看", callback_data="chart_by_country"),
                    InlineKeyboardButton("🔄 跨平台对比", callback_data="chart_cross_platform")
                ],
                [
                    InlineKeyboardButton("❌ 关闭", callback_data="chart_close"),
                    InlineKeyboardButton("🔧 调试平台", callback_data="chart_debug_platforms")
                ]
            ])
            
            main_message_text = (
                "🏆 *流媒体排行榜中心*\n\n"
                "选择你想查看的排行榜类型：\n\n"
                "📊 **热门榜单**：全球热门内容\n"
                "🎯 **平台专属**：各流媒体平台独家排行\n"
                "🌐 **地区排行**：不同国家地区的热门内容\n"
                "🔍 **跨平台对比**：查看内容在各平台的情况"
            )
            
            await query.edit_message_text(
                text=foldable_text_with_markdown_v2(main_message_text),
                reply_markup=main_keyboard,
                parse_mode=ParseMode.MARKDOWN_V2
            )
            return
            
        elif callback_data == "chart_close":
            # 关闭菜单
            await query.delete_message()
            return
            
        elif callback_data == "chart_subscription_platforms":
            # 显示订阅平台
            subscription_keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🦚 Peacock", callback_data="chart_platform_peacocktvpremium"),
                    InlineKeyboardButton("🎭 Starz", callback_data="chart_platform_starz"),
                    InlineKeyboardButton("🎬 AMC+", callback_data="chart_platform_amcplus")
                ],
                [
                    InlineKeyboardButton("🎥 MUBI", callback_data="chart_platform_mubi"),
                    InlineKeyboardButton("📺 Philo", callback_data="chart_platform_philo"),
                    InlineKeyboardButton("⚽ fuboTV", callback_data="chart_platform_fubotv")
                ],
                [
                    InlineKeyboardButton("🔍 Discovery+", callback_data="chart_platform_discoveryplusus"),
                    InlineKeyboardButton("🎞️ Sundance Now", callback_data="chart_platform_sundancenow"),
                    InlineKeyboardButton("🌐 Spectrum", callback_data="chart_platform_spectrumondemand")
                ],
                [
                    InlineKeyboardButton("🔙 返回主菜单", callback_data="chart_main_menu")
                ]
            ])
            
            await query.edit_message_text(
                "🎵 *订阅制流媒体平台*\n\n选择你想查看的平台：",
                reply_markup=subscription_keyboard,
                parse_mode=ParseMode.MARKDOWN_V2
            )
            
        elif callback_data == "chart_free_platforms":
            # 显示免费平台
            free_keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🎮 Plex", callback_data="chart_platform_plex"),
                    InlineKeyboardButton("📺 Roku Channel", callback_data="chart_platform_rokuchannel"),
                    InlineKeyboardButton("🎪 Pluto TV", callback_data="chart_platform_plutotv")
                ],
                [
                    InlineKeyboardButton("📱 Tubi", callback_data="chart_platform_tubitv"),
                    InlineKeyboardButton("⭐ Fawesome", callback_data="chart_platform_fawesometv"),
                    InlineKeyboardButton("📚 Hoopla", callback_data="chart_platform_hoopla")
                ],
                [
                    InlineKeyboardButton("🎓 Kanopy", callback_data="chart_platform_kanopy"),
                    InlineKeyboardButton("🎬 JustWatch TV", callback_data="chart_platform_justwatchtv"),
                    InlineKeyboardButton("📺 The CW", callback_data="chart_platform_thecw")
                ],
                [
                    InlineKeyboardButton("🌸 Viki", callback_data="chart_platform_viki"),
                    InlineKeyboardButton("🇰🇷 OnDemandKorea", callback_data="chart_platform_ondemandkorea"),
                    InlineKeyboardButton("🎥 Cineverse", callback_data="chart_platform_cineverse")
                ],
                [
                    InlineKeyboardButton("🔙 返回主菜单", callback_data="chart_main_menu")
                ]
            ])
            
            await query.edit_message_text(
                "🆓 *免费流媒体平台*\n\n选择你想查看的平台：",
                reply_markup=free_keyboard,
                parse_mode=ParseMode.MARKDOWN_V2
            )
            
        elif callback_data == "chart_rental_platforms":
            # 显示租赁平台
            rental_keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🎬 Google Play", callback_data="chart_platform_play"),
                    InlineKeyboardButton("🎵 YouTube", callback_data="chart_platform_youtube"),
                    InlineKeyboardButton("🎪 Microsoft Store", callback_data="chart_platform_microsoft")
                ],
                [
                    InlineKeyboardButton("🎭 Darkroom", callback_data="chart_platform_darkroom"),
                    InlineKeyboardButton("🎬 Kino Film", callback_data="chart_platform_kinofilmcollection"),
                    InlineKeyboardButton("📺 DistroTV", callback_data="chart_platform_distrotv")
                ],
                [
                    InlineKeyboardButton("🎮 Filmzie", callback_data="chart_platform_filmzie"),
                    InlineKeyboardButton("🇰🇷 Kocowa", callback_data="chart_platform_kocowa"),
                    InlineKeyboardButton("📱 Mometu", callback_data="chart_platform_mometu")
                ],
                [
                    InlineKeyboardButton("🔙 返回主菜单", callback_data="chart_main_menu")
                ]
            ])
            
            await query.edit_message_text(
                "🛒 *租赁/购买平台*\n\n选择你想查看的平台：",
                reply_markup=rental_keyboard,
                parse_mode=ParseMode.MARKDOWN_V2
            )
            
        elif callback_data.startswith("chart_compare_"):
            # 处理跨平台对比请求
            if callback_data == "chart_compare_custom":
                # 自定义搜索提示
                await query.edit_message_text(
                    "🔍 *自定义跨平台对比*\n\n"
                    "请使用以下格式查看内容的跨平台情况：\n"
                    "`/chart_compare <电影或电视剧名称>`\n\n"
                    "例如：\n"
                    "• `/chart_compare Avatar`\n"
                    "• `/chart_compare Breaking Bad`\n"
                    "• `/chart_compare Avengers`",
                    parse_mode=ParseMode.MARKDOWN_V2
                )
            elif callback_data.startswith("chart_compare_dynamic_"):
                # 处理动态获取的热门内容（通过TMDB ID） - 向后兼容
                tmdb_id = callback_data.replace("chart_compare_dynamic_", "")
                await query.edit_message_text("🔍 正在获取跨平台对比数据...")
                
                try:
                    # 先通过TMDB ID获取详细信息
                    movie_details = await movie_service.get_movie_details(int(tmdb_id))
                    tv_details = await movie_service.get_tv_details(int(tmdb_id))
                    
                    # 确定是电影还是电视剧，获取标题
                    if movie_details and movie_details.get("title"):
                        title = movie_details["title"]
                    elif tv_details and tv_details.get("name"):
                        title = tv_details["name"]
                    else:
                        await query.edit_message_text("❌ 获取内容信息失败")
                        return
                    
                    # 使用标题进行跨平台对比搜索
                    cross_data = await movie_service.get_cross_platform_charts(title)
                    if cross_data:
                        result_text = movie_service.format_cross_platform_charts(cross_data)
                        
                        # 添加返回按钮
                        back_keyboard = InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔙 返回跨平台菜单", callback_data="chart_cross_platform")]
                        ])
                        
                        await query.edit_message_text(
                            result_text, 
                            parse_mode="MarkdownV2", 
                            reply_markup=back_keyboard, 
                            disable_web_page_preview=True
                        )
                    else:
                        await query.edit_message_text("❌ 获取跨平台对比数据失败")
                        
                except Exception as e:
                    logger.error(f"动态跨平台对比失败: {e}")
                    await query.edit_message_text("❌ 获取跨平台对比数据时发生错误")
            
            elif callback_data.startswith("chart_compare_title_"):
                # 处理通过标题编码的跨平台对比
                encoded_title = callback_data.replace("chart_compare_title_", "")
                await query.edit_message_text("🔍 正在获取跨平台对比数据...")
                
                try:
                    # 解码标题
                    title = base64.b64decode(encoded_title.encode('ascii')).decode('utf-8')
                    
                    # 使用标题进行跨平台对比搜索
                    cross_data = await movie_service.get_cross_platform_charts(title)
                    if cross_data:
                        result_text = movie_service.format_cross_platform_charts(cross_data)
                        
                        # 添加返回按钮
                        back_keyboard = InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔙 返回跨平台菜单", callback_data="chart_cross_platform")]
                        ])
                        
                        await query.edit_message_text(
                            foldable_text_with_markdown_v2(result_text),
                            reply_markup=back_keyboard,
                            parse_mode=ParseMode.MARKDOWN_V2
                        )
                    else:
                        await query.edit_message_text(f"❌ 未找到 '{title}' 的跨平台数据")
                        
                except Exception as e:
                    logger.error(f"获取动态跨平台对比数据失败: {e}")
                    await query.edit_message_text("❌ 获取跨平台对比数据时发生错误")
                    
            else:
                # 处理静态的热门内容（通过标题）
                title = callback_data.replace("chart_compare_", "").replace("_", " ")
                await query.edit_message_text(f"🔍 正在获取 *{title}* 的跨平台对比数据...")
                
                try:
                    cross_data = await movie_service.get_cross_platform_charts(title)
                    if cross_data:
                        result_text = movie_service.format_cross_platform_charts(cross_data)
                        
                        # 添加返回按钮
                        back_keyboard = InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔙 返回跨平台菜单", callback_data="chart_cross_platform")]
                        ])
                        
                        await query.edit_message_text(
                            foldable_text_with_markdown_v2(result_text),
                            reply_markup=back_keyboard,
                            parse_mode=ParseMode.MARKDOWN_V2
                        )
                    else:
                        await query.edit_message_text(f"❌ 未找到 '{title}' 的跨平台数据")
                except Exception as e:
                    logger.error(f"获取跨平台对比数据失败: {e}")
                    await query.edit_message_text("❌ 获取跨平台对比数据时发生错误")
        
        elif callback_data == "chart_debug_platforms":
            # 调试平台信息
            await query.edit_message_text("🔍 正在获取JustWatch平台信息...")
            
            debug_data = await movie_service.debug_available_platforms()
            if debug_data:
                result_text = movie_service.format_debug_platforms(debug_data)
                await query.edit_message_text(
                    foldable_text_with_markdown_v2(result_text),
                    parse_mode=ParseMode.MARKDOWN_V2
                )
                await schedule_chart_deletion()
            else:
                await query.edit_message_text("❌ 获取平台调试信息失败")
            
    except Exception as e:
        logger.error(f"处理排行榜回调失败: {e}")
        await query.edit_message_text("❌ 处理请求时发生错误，请稍后重试")

async def chart_compare_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /chart_compare 命令 - 跨平台对比"""
    if not update.message or not update.effective_chat:
        return
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    if not context.args:
        error_message = "❌ 请提供要对比的内容标题\n\n使用方法: `/chart_compare <标题>`\n例如: `/chart_compare The Matrix`"
        await send_error(context, update.effective_chat.id, foldable_text_with_markdown_v2(error_message), parse_mode="MarkdownV2")
        return
    
    if not movie_service:
        error_message = "❌ 电影查询服务未初始化"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        return
    
    title = " ".join(context.args)
    
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🔍 正在获取 *{escape_markdown(title, version=2)}* 的跨平台对比数据\.\.\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    try:
        cross_data = await movie_service.get_cross_platform_charts(title)
        if cross_data:
            result_text = movie_service.format_cross_platform_charts(cross_data)
            await message.edit_text(
                foldable_text_with_markdown_v2(result_text),
                parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            await message.edit_text(f"❌ 未找到 '{title}' 的跨平台数据")
    except Exception as e:
        logger.error(f"获取跨平台对比数据失败: {e}")
        await message.edit_text("❌ 获取跨平台对比数据时发生错误")
    
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
    
    # 获取用户ID用于会话管理
    user_id = update.effective_user.id
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    if not context.args:
        help_text = (
            "*👤 人物信息查询帮助*\n\n"
            "`/person <人物名>` - 搜索人物（按钮选择）\n"
            "`/persons <人物名>` - 搜索人物（文本列表）\n"
            "`/person_detail <人物ID>` - 获取人物详情\n\n"
            "**示例:**\n"
            "`/person 汤姆·汉克斯`\n"
            "`/persons 汤姆·汉克斯`\n"
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
            # 添加查询词到搜索数据中
            search_data["query"] = query
            
            # 如果用户已经有活跃的搜索会话，取消旧的删除任务
            if user_id in person_search_sessions:
                old_session = person_search_sessions[user_id]
                old_session_id = old_session.get("session_id")
                if old_session_id:
                    from utils.message_manager import cancel_session_deletions
                    cancelled_count = await cancel_session_deletions(old_session_id, context)
                    logger.info(f"🔄 用户 {user_id} 有现有人物搜索会话，已取消 {cancelled_count} 个旧的删除任务")
            
            # 存储用户搜索会话
            person_search_sessions[user_id] = {
                "search_data": search_data,
                "timestamp": datetime.now()
            }
            
            # 格式化搜索结果消息
            result_text = format_person_search_results_for_keyboard(search_data)
            keyboard = create_person_search_keyboard(search_data)
            
            # 删除搜索进度消息
            await message.delete()
            
            # 生成会话ID用于消息管理
            import time
            session_id = f"person_search_{user_id}_{int(time.time())}"
            
            # 使用统一的消息发送API发送搜索结果
            from utils.message_manager import send_message_with_auto_delete, MessageType
            new_message = await send_message_with_auto_delete(
                context,
                update.effective_chat.id,
                foldable_text_v2(result_text),
                MessageType.SEARCH_RESULT,
                session_id=session_id,
                reply_markup=keyboard,
                parse_mode="MarkdownV2"
            )
            
            # 更新会话中的消息ID
            if new_message:
                person_search_sessions[user_id]["message_id"] = new_message.message_id
                person_search_sessions[user_id]["session_id"] = session_id
            
            # 删除用户命令消息
            await delete_user_command(context, update.effective_chat.id, update.message.message_id, session_id=session_id)
        else:
            await message.edit_text("❌ 搜索人物失败，请稍后重试")
            # 调度删除机器人回复消息
            from utils.message_manager import _schedule_deletion
            from utils.config_manager import get_config
            config = get_config()
            await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)
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
    
    user_id = update.effective_user.id if update.effective_user else None
    if user_id:
        # 检查并取消活跃的 movie 搜索会话的删除任务
        if user_id in movie_search_sessions:
            old_session = movie_search_sessions[user_id]
            old_session_id = old_session.get("session_id")
            if old_session_id:
                from utils.message_manager import cancel_session_deletions
                cancelled_count = await cancel_session_deletions(old_session_id, context)
                logger.info(f"🔄 用户 {user_id} 执行 movie_watch，已取消 {cancelled_count} 个movie搜索会话删除任务")
    
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
        # 先获取电影基本信息以便获取标题
        movie_info = await movie_service.get_movie_details(movie_id)
        movie_title = ""
        if movie_info:
            # 优先使用英文原标题，如果没有再使用本地化标题
            movie_title = movie_info.get("original_title") or movie_info.get("title", "")
            logger.info(f"Movie title for JustWatch search: {movie_title}")
        
        # 使用增强的观影平台功能
        enhanced_providers = await movie_service.get_enhanced_watch_providers(
            movie_id, "movie", movie_title
        )
        
        # 优先使用合并后的数据，如果没有则回退到 TMDB 数据
        providers_data = enhanced_providers.get("combined") or enhanced_providers.get("tmdb")
        
        if providers_data:
            result_text = movie_service.format_watch_providers(providers_data, "movie")
            
            # 如果有 JustWatch 数据，添加数据源说明
            if enhanced_providers.get("justwatch"):
                result_text += "\n\n💡 数据来源: TMDB + JustWatch"
            else:
                result_text += "\n\n💡 数据来源: TMDB"
            
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
    
    user_id = update.effective_user.id if update.effective_user else None
    if user_id:
        # 检查并取消活跃的 tv 搜索会话的删除任务
        if user_id in tv_search_sessions:
            old_session = tv_search_sessions[user_id]
            old_session_id = old_session.get("session_id")
            if old_session_id:
                from utils.message_manager import cancel_session_deletions
                cancelled_count = await cancel_session_deletions(old_session_id, context)
                logger.info(f"🔄 用户 {user_id} 执行 tv_watch，已取消 {cancelled_count} 个tv搜索会话删除任务")
    
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
        # 先获取电视剧基本信息以便获取标题
        tv_info = await movie_service.get_tv_details(tv_id)
        tv_title = ""
        if tv_info:
            tv_title = tv_info.get("original_name") or tv_info.get("name", "")
            logger.info(f"TV title for JustWatch search: {tv_title}")
        
        # 使用增强的观影平台功能
        enhanced_providers = await movie_service.get_enhanced_watch_providers(
            tv_id, "tv", tv_title
        )
        
        # 优先使用合并后的数据，如果没有则回退到 TMDB 数据
        providers_data = enhanced_providers.get("combined") or enhanced_providers.get("tmdb")
        
        if providers_data:
            result_text = movie_service.format_watch_providers(providers_data, "tv")
            
            # 如果有 JustWatch 数据，添加数据源说明
            if enhanced_providers.get("justwatch"):
                result_text += "\n\n💡 数据来源: TMDB + JustWatch"
            else:
                result_text += "\n\n💡 数据来源: TMDB"
            
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

async def persons_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /persons 命令 - 搜索人物（纯文本结果）"""
    if not update.message or not update.effective_chat:
        return
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    if not context.args:
        help_text = (
            "*👤 人物文本搜索帮助*\n\n"
            "`/persons <人物名>` - 搜索人物（文本列表）\n"
            "`/person <人物名>` - 搜索人物（按钮选择）\n\n"
            "**示例:**\n"
            "`/persons 汤姆·汉克斯`"
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
            # 使用原来的文本格式化函数
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
                            detail_message = await context.bot.send_photo(
                                chat_id=query.message.chat_id,
                                photo=poster_url,
                                caption=foldable_text_with_markdown_v2(result_text),
                                parse_mode=ParseMode.MARKDOWN_V2
                            )
                            # 删除原来的搜索结果消息
                            await query.delete_message()
                            
                            # 为详情消息添加自动删除
                            from utils.message_manager import _schedule_deletion
                            from utils.config_manager import get_config
                            config = get_config()
                            await _schedule_deletion(context, query.message.chat_id, detail_message.message_id, config.auto_delete_delay)
                        except Exception as photo_error:
                            logger.warning(f"发送海报失败: {photo_error}，改用文本消息")
                            await query.edit_message_text(
                                foldable_text_with_markdown_v2(result_text),
                                parse_mode=ParseMode.MARKDOWN_V2
                            )
                            
                            # 为编辑后的消息添加自动删除
                            from utils.message_manager import _schedule_deletion
                            from utils.config_manager import get_config
                            config = get_config()
                            await _schedule_deletion(context, query.message.chat_id, query.message.message_id, config.auto_delete_delay)
                    else:
                        await query.edit_message_text(
                            foldable_text_with_markdown_v2(result_text),
                            parse_mode=ParseMode.MARKDOWN_V2
                        )
                        
                        # 为编辑后的消息添加自动删除
                        from utils.message_manager import _schedule_deletion
                        from utils.config_manager import get_config
                        config = get_config()
                        await _schedule_deletion(context, query.message.chat_id, query.message.message_id, config.auto_delete_delay)
                    
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
                            detail_message = await context.bot.send_photo(
                                chat_id=query.message.chat_id,
                                photo=poster_url,
                                caption=foldable_text_with_markdown_v2(result_text),
                                parse_mode=ParseMode.MARKDOWN_V2
                            )
                            # 删除原来的搜索结果消息
                            await query.delete_message()
                            
                            # 为详情消息添加自动删除
                            from utils.message_manager import _schedule_deletion
                            from utils.config_manager import get_config
                            config = get_config()
                            await _schedule_deletion(context, query.message.chat_id, detail_message.message_id, config.auto_delete_delay)
                        except Exception as photo_error:
                            logger.warning(f"发送海报失败: {photo_error}，改用文本消息")
                            await query.edit_message_text(
                                foldable_text_with_markdown_v2(result_text),
                                parse_mode=ParseMode.MARKDOWN_V2
                            )
                            
                            # 为编辑后的消息添加自动删除
                            from utils.message_manager import _schedule_deletion
                            from utils.config_manager import get_config
                            config = get_config()
                            await _schedule_deletion(context, query.message.chat_id, query.message.message_id, config.auto_delete_delay)
                    else:
                        await query.edit_message_text(
                            foldable_text_with_markdown_v2(result_text),
                            parse_mode=ParseMode.MARKDOWN_V2
                        )
                        
                        # 为编辑后的消息添加自动删除
                        from utils.message_manager import _schedule_deletion
                        from utils.config_manager import get_config
                        config = get_config()
                        await _schedule_deletion(context, query.message.chat_id, query.message.message_id, config.auto_delete_delay)
                    
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

async def person_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理人物搜索结果的内联键盘回调"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    callback_data = query.data
    
    # 检查用户是否有有效的搜索会话
    if user_id not in person_search_sessions:
        await query.edit_message_text("❌ 搜索会话已过期，请重新搜索")
        return
    
    session = person_search_sessions[user_id]
    search_data = session["search_data"]
    
    try:
        if callback_data.startswith("person_select_"):
            # 用户选择了一个人物
            parts = callback_data.split("_")
            person_index = int(parts[2])
            page = int(parts[3])
            
            # 获取当前页的搜索结果
            if page != search_data.get("current_page", 1):
                # 需要获取指定页面的数据
                new_search_data = await movie_service.search_person(
                    search_data["query"], page=page
                )
                if new_search_data:
                    search_data = new_search_data
                    person_search_sessions[user_id]["search_data"] = search_data
            
            results = search_data["results"]
            if person_index < len(results):
                selected_person = results[person_index]
                person_id = selected_person["id"]
                
                # 获取人物详情
                detail_data = await movie_service.get_person_details(person_id)
                if detail_data:
                    result_text, profile_url = movie_service.format_person_details(detail_data)
                    
                    # 如果有头像URL，发送图片消息
                    if profile_url:
                        try:
                            detail_message = await context.bot.send_photo(
                                chat_id=query.message.chat_id,
                                photo=profile_url,
                                caption=foldable_text_with_markdown_v2(result_text),
                                parse_mode=ParseMode.MARKDOWN_V2
                            )
                            # 删除原来的搜索结果消息
                            await query.delete_message()
                            
                            # 为详情消息添加自动删除
                            from utils.message_manager import _schedule_deletion
                            from utils.config_manager import get_config
                            config = get_config()
                            await _schedule_deletion(context, query.message.chat_id, detail_message.message_id, config.auto_delete_delay)
                        except Exception as photo_error:
                            logger.warning(f"发送头像失败: {photo_error}，改用文本消息")
                            await query.edit_message_text(
                                foldable_text_with_markdown_v2(result_text),
                                parse_mode=ParseMode.MARKDOWN_V2
                            )
                            
                            # 为编辑后的消息添加自动删除
                            from utils.message_manager import _schedule_deletion
                            from utils.config_manager import get_config
                            config = get_config()
                            await _schedule_deletion(context, query.message.chat_id, query.message.message_id, config.auto_delete_delay)
                    else:
                        await query.edit_message_text(
                            foldable_text_with_markdown_v2(result_text),
                            parse_mode=ParseMode.MARKDOWN_V2
                        )
                        
                        # 为编辑后的消息添加自动删除
                        from utils.message_manager import _schedule_deletion
                        from utils.config_manager import get_config
                        config = get_config()
                        await _schedule_deletion(context, query.message.chat_id, query.message.message_id, config.auto_delete_delay)
                    
                    # 清除用户会话
                    del person_search_sessions[user_id]
                else:
                    await query.edit_message_text("❌ 获取人物详情失败")
            else:
                await query.edit_message_text("❌ 选择的人物索引无效")
                
        elif callback_data.startswith("person_page_"):
            # 处理分页
            if callback_data == "person_page_info":
                return  # 只是显示页面信息，不做任何操作
            
            page_num = int(callback_data.split("_")[2])
            new_search_data = await movie_service.search_person(
                search_data["query"], page=page_num
            )
            
            if new_search_data:
                new_search_data["query"] = search_data["query"]  # 保持原查询词
                person_search_sessions[user_id]["search_data"] = new_search_data
                
                result_text = format_person_search_results_for_keyboard(new_search_data)
                keyboard = create_person_search_keyboard(new_search_data)
                
                await query.edit_message_text(
                    foldable_text_with_markdown_v2(result_text),
                    reply_markup=keyboard,
                    parse_mode=ParseMode.MARKDOWN_V2
                )
            else:
                await query.edit_message_text("❌ 获取页面数据失败")
                
        elif callback_data == "person_close":
            # 关闭搜索结果
            await query.delete_message()
            if user_id in person_search_sessions:
                del person_search_sessions[user_id]
                
    except Exception as e:
        logger.error(f"处理人物搜索回调失败: {e}")
        await query.edit_message_text("❌ 处理选择时发生错误")

# 注册命令
command_factory.register_command("movie", movie_command, permission=Permission.USER, description="搜索电影信息（按钮选择）")
command_factory.register_command("movies", movies_command, permission=Permission.USER, description="搜索电影信息（文本列表）")
command_factory.register_command("movie_hot", movie_hot_command, permission=Permission.USER, description="获取热门电影")
command_factory.register_command("movie_detail", movie_detail_command, permission=Permission.USER, description="获取电影详情")
command_factory.register_command("movie_rec", movie_rec_command, permission=Permission.USER, description="获取电影推荐")
command_factory.register_command("movie_videos", movie_videos_command, permission=Permission.USER, description="获取电影预告片")
command_factory.register_command("movie_reviews", movie_reviews_command, permission=Permission.USER, description="获取电影用户评价")
command_factory.register_command("movie_trending", movie_trending_command, permission=Permission.USER, description="获取Trakt热门电影")
command_factory.register_command("movie_related", movie_related_command, permission=Permission.USER, description="获取Trakt相关电影推荐")
command_factory.register_command("movie_cleancache", movie_clean_cache_command, permission=Permission.ADMIN, description="清理电影和电视剧查询缓存")

# 注册电视剧命令
command_factory.register_command("tv", tv_command, permission=Permission.USER, description="搜索电视剧信息（按钮选择）")
command_factory.register_command("tvs", tvs_command, permission=Permission.USER, description="搜索电视剧信息（文本列表）")
command_factory.register_command("tv_hot", tv_hot_command, permission=Permission.USER, description="获取热门电视剧")
command_factory.register_command("tv_detail", tv_detail_command, permission=Permission.USER, description="获取电视剧详情")
command_factory.register_command("tv_rec", tv_rec_command, permission=Permission.USER, description="获取电视剧推荐")
command_factory.register_command("tv_videos", tv_videos_command, permission=Permission.USER, description="获取电视剧预告片")
command_factory.register_command("tv_reviews", tv_reviews_command, permission=Permission.USER, description="获取电视剧用户评价")
command_factory.register_command("tv_trending", tv_trending_command, permission=Permission.USER, description="获取Trakt热门电视剧")
command_factory.register_command("tv_related", tv_related_command, permission=Permission.USER, description="获取Trakt相关电视剧推荐")
command_factory.register_command("tv_season", tv_season_command, permission=Permission.USER, description="获取电视剧季详情")
command_factory.register_command("tv_episode", tv_episode_command, permission=Permission.USER, description="获取电视剧集详情")

# 注册趋势和上映相关命令
command_factory.register_command("trending", trending_command, permission=Permission.USER, description="获取今日热门内容")
command_factory.register_command("trending_week", trending_week_command, permission=Permission.USER, description="获取本周热门内容")
command_factory.register_command("now_playing", now_playing_command, permission=Permission.USER, description="获取正在上映的电影")
command_factory.register_command("upcoming", upcoming_command, permission=Permission.USER, description="获取即将上映的电影")
command_factory.register_command("tv_airing", tv_airing_command, permission=Permission.USER, description="获取今日播出的电视剧")
command_factory.register_command("tv_on_air", tv_on_air_command, permission=Permission.USER, description="获取正在播出的电视剧")

# 注册排行榜相关命令
command_factory.register_command("charts", charts_command, permission=Permission.USER, description="流媒体排行榜中心")
command_factory.register_command("chart_compare", chart_compare_command, permission=Permission.USER, description="跨平台对比")

# 注册人物搜索命令
command_factory.register_command("person", person_command, permission=Permission.USER, description="搜索人物信息（按钮选择）")
command_factory.register_command("persons", persons_command, permission=Permission.USER, description="搜索人物信息（文本列表）")
command_factory.register_command("person_detail", person_detail_command, permission=Permission.USER, description="获取人物详情")

# 注册观看平台命令
command_factory.register_command("movie_watch", movie_watch_command, permission=Permission.USER, description="获取电影观看平台")
command_factory.register_command("tv_watch", tv_watch_command, permission=Permission.USER, description="获取电视剧观看平台")

# 注册回调处理器
command_factory.register_callback(r"^movie_", movie_callback_handler, permission=Permission.USER, description="电影搜索结果选择")
command_factory.register_callback(r"^tv_", tv_callback_handler, permission=Permission.USER, description="电视剧搜索结果选择")
command_factory.register_callback(r"^person_", person_callback_handler, permission=Permission.USER, description="人物搜索结果选择")
command_factory.register_callback(r"^chart_", charts_callback_handler, permission=Permission.USER, description="排行榜选择处理")