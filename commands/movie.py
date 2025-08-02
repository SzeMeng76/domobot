import logging
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
    
    async def _make_tmdb_request(self, endpoint: str, params: Dict[str, Any] = None) -> Optional[Dict]:
        """发起TMDB API请求"""
        api_key = await self._get_tmdb_api_key()
        if not api_key:
            logger.error("TMDB API密钥未配置")
            return None
            
        try:
            url = f"{self.tmdb_base_url}/{endpoint}"
            request_params = {"api_key": api_key, "language": "zh-CN"}
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
            
        data = await self._make_tmdb_request(f"movie/{movie_id}", {
            "append_to_response": "credits,videos,recommendations"
        })
        if data:
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
            
        data = await self._make_tmdb_request(f"tv/{tv_id}", {
            "append_to_response": "credits,videos,recommendations"
        })
        if data:
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
        """获取电视剧季详情"""
        cache_key = f"tv_season_{tv_id}_{season_number}"
        cached_data = await cache_manager.load_cache(cache_key, subdirectory="movie")
        if cached_data:
            return cached_data
            
        data = await self._make_tmdb_request(f"tv/{tv_id}/season/{season_number}")
        if data:
            await cache_manager.save_cache(cache_key, data, subdirectory="movie")
        return data
    
    async def get_tv_episode_details(self, tv_id: int, season_number: int, episode_number: int) -> Optional[Dict]:
        """获取电视剧集详情"""
        cache_key = f"tv_episode_{tv_id}_{season_number}_{episode_number}"
        cached_data = await cache_manager.load_cache(cache_key, subdirectory="movie")
        if cached_data:
            return cached_data
            
        data = await self._make_tmdb_request(f"tv/{tv_id}/season/{season_number}/episode/{episode_number}")
        if data:
            await cache_manager.save_cache(cache_key, data, subdirectory="movie")
        return data
    
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
            
        lines.extend([
            creator_info,
            cast_info,
            f"",
            f"📖 *剧情简介*:",
            f"{overview[:500]}{'...' if len(overview) > 500 else ''}",
        ])
        
        # 添加操作提示
        tv_id = detail_data.get("id")
        lines.extend([
            f"",
            f"💡 使用 `/tv_rec {tv_id}` 获取相似推荐",
            f"💡 使用 `/tv_season {tv_id} <季数>` 查看季详情"
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
        """格式化电视剧季详情"""
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
        
        # 显示前5集信息
        episodes = season_data.get("episodes", [])
        if episodes:
            lines.extend([
                f"",
                f"📋 *剧集列表* (显示前5集):",
                f""
            ])
            
            for ep in episodes[:5]:
                ep_num = ep.get("episode_number", 0)
                ep_name = ep.get("name", f"第{ep_num}集")
                ep_date = ep.get("air_date", "")
                ep_runtime = ep.get("runtime", 0)
                
                lines.append(f"{ep_num}. *{ep_name}*")
                if ep_date:
                    lines.append(f"   📅 {ep_date}")
                if ep_runtime:
                    lines.append(f"   ⏱️ {ep_runtime}分钟")
                lines.append("")
            
            if len(episodes) > 5:
                lines.append(f"... 还有 {len(episodes) - 5} 集")
        
        lines.extend([
            f"",
            f"💡 使用 `/tv_episode {tv_id} {season_number} <集数>` 查看集详情"
        ])
        
        return "\n".join(filter(None, lines))
    
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
            
        lines.extend([
            director_info,
            cast_info,
            f"",
            f"📖 *剧情简介*:",
            f"{overview[:500]}{'...' if len(overview) > 500 else ''}",
        ])
        
        # 添加操作提示
        movie_id = detail_data.get("id")
        lines.extend([
            f"",
            f"💡 使用 `/movie_rec {movie_id}` 获取相似推荐"
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

# 全局服务实例
movie_service: MovieService = None

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
            "`/movie <电影名>` - 搜索电影\n"
            "`/movie_hot` - 获取热门电影\n"
            "`/movie_detail <电影ID>` - 获取电影详情\n"
            "`/movie_rec <电影ID>` - 获取相似推荐\n\n"
            "**示例:**\n"
            "`/movie 复仇者联盟`\n"
            "`/movie_detail 299536`"
        )
        message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=foldable_text_with_markdown_v2(help_text),
            parse_mode=ParseMode.MARKDOWN_V2
        )
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
            result_text, poster_url = movie_service.format_movie_search_results(search_data)
            
            # 如果有海报URL，先发送图片再发送文本
            if poster_url:
                try:
                    # 发送海报图片
                    await context.bot.send_photo(
                        chat_id=update.effective_chat.id,
                        photo=poster_url,
                        caption=foldable_text_with_markdown_v2(result_text),
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
                    # 删除原来的加载消息
                    await message.delete()
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
                    await context.bot.send_photo(
                        chat_id=update.effective_chat.id,
                        photo=poster_url,
                        caption=foldable_text_with_markdown_v2(result_text),
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
                    # 删除原来的加载消息
                    await message.delete()
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
            "`/tv <电视剧名>` - 搜索电视剧\n"
            "`/tv_hot` - 获取热门电视剧\n"
            "`/tv_detail <电视剧ID>` - 获取电视剧详情\n"
            "`/tv_rec <电视剧ID>` - 获取相似推荐\n"
            "`/tv_season <电视剧ID> <季数>` - 获取季详情\n"
            "`/tv_episode <电视剧ID> <季数> <集数>` - 获取集详情\n\n"
            "**示例:**\n"
            "`/tv 权力的游戏`\n"
            "`/tv_detail 1399`\n"
            "`/tv_season 1399 1`"
        )
        message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=foldable_text_with_markdown_v2(help_text),
            parse_mode=ParseMode.MARKDOWN_V2
        )
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
            result_text, poster_url = movie_service.format_tv_search_results(search_data)
            
            # 如果有海报URL，先发送图片再发送文本
            if poster_url:
                try:
                    # 发送海报图片
                    await context.bot.send_photo(
                        chat_id=update.effective_chat.id,
                        photo=poster_url,
                        caption=foldable_text_with_markdown_v2(result_text),
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
                    # 删除原来的加载消息
                    await message.delete()
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
                    await context.bot.send_photo(
                        chat_id=update.effective_chat.id,
                        photo=poster_url,
                        caption=foldable_text_with_markdown_v2(result_text),
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
                    # 删除原来的加载消息
                    await message.delete()
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
    """处理 /tv_season 命令 - 获取电视剧季详情"""
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
        text=f"🔍 正在获取第{season_number}季详情 \(电视剧ID: {tv_id}\)\.\.\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    try:
        season_data = await movie_service.get_tv_season_details(tv_id, season_number)
        if season_data:
            result_text = movie_service.format_tv_season_details(season_data, tv_id)
            await message.edit_text(
                foldable_text_with_markdown_v2(result_text),
                parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            await message.edit_text(f"❌ 未找到电视剧ID {tv_id} 的第{season_number}季")
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

# 注册命令
command_factory.register_command("movie", movie_command, permission=Permission.USER, description="搜索电影信息")
command_factory.register_command("movie_hot", movie_hot_command, permission=Permission.USER, description="获取热门电影")
command_factory.register_command("movie_detail", movie_detail_command, permission=Permission.USER, description="获取电影详情")
command_factory.register_command("movie_rec", movie_rec_command, permission=Permission.USER, description="获取电影推荐")
command_factory.register_command("movie_cleancache", movie_clean_cache_command, permission=Permission.ADMIN, description="清理电影和电视剧查询缓存")

# 注册电视剧命令
command_factory.register_command("tv", tv_command, permission=Permission.USER, description="搜索电视剧信息")
command_factory.register_command("tv_hot", tv_hot_command, permission=Permission.USER, description="获取热门电视剧")
command_factory.register_command("tv_detail", tv_detail_command, permission=Permission.USER, description="获取电视剧详情")
command_factory.register_command("tv_rec", tv_rec_command, permission=Permission.USER, description="获取电视剧推荐")
command_factory.register_command("tv_season", tv_season_command, permission=Permission.USER, description="获取电视剧季详情")
command_factory.register_command("tv_episode", tv_episode_command, permission=Permission.USER, description="获取电视剧集详情")