import logging
import json
import asyncio
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
from utils.message_manager import delete_user_command, send_error, send_success, send_message_with_auto_delete
from utils.permissions import Permission
from utils.session_manager import SessionManager

logger = logging.getLogger(__name__)

# Telegraph 相关配置
TELEGRAPH_API_URL = "https://api.telegra.ph"
TELEGRAM_MESSAGE_LIMIT = 4096

# 全局变量
cache_manager = None
httpx_client = None

# 创建person会话管理器 - 与flight/hotel相同的配置
person_session_manager = SessionManager("PersonService", max_age=1800, max_sessions=200)  # 30分钟会话

async def _execute_person_search(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str) -> None:
    """执行人物搜索 - 与flight/hotel完全一致的模式"""
    if not movie_service:
        await send_error(context, update.message.chat_id, "❌ 人物查询服务未初始化")
        return
    
    loading_message = f"🔍 正在搜索人物: {query}... ⏳"
    
    # 使用与flight/hotel完全一致的消息发送方式
    message = await send_message_with_auto_delete(
        context=context,
        chat_id=update.message.chat_id,
        text=foldable_text_v2(loading_message),
        parse_mode="MarkdownV2"
    )
    
    try:
        search_data = await movie_service.search_person(query)
        if search_data and search_data.get('results'):
            # 添加查询词到搜索数据中
            search_data["query"] = query
            
            # 兼容旧系统：将搜索数据保存到旧的session中，以便旧的回调处理器能找到
            user_id = update.effective_user.id
            person_search_sessions[user_id] = {
                "search_data": search_data,
                "timestamp": datetime.now()
            }
            
            # 格式化搜索结果消息
            result_text = format_person_search_results_for_keyboard(search_data)
            keyboard = create_person_search_keyboard(search_data)
            
            # 更新消息内容，保持自动删除机制
            await message.edit_text(
                text=foldable_text_v2(result_text),
                parse_mode="MarkdownV2",
                reply_markup=keyboard
            )
        else:
            await message.edit_text(f"❌ 未找到人物: {query}")
            
    except Exception as e:
        logger.error(f"人物搜索失败: {e}")
        await message.edit_text(f"❌ 搜索失败: {str(e)}")

async def person_text_handler_core(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """人物功能文本处理的核心逻辑 - 与flight/hotel相同的模式"""
    if not update.message or not update.message.text:
        return
    
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # 获取用户会话
    session_data = person_session_manager.get_session(user_id)
    if not session_data:
        logger.debug(f"PersonService: 用户 {user_id} 没有活动会话")
        return
    
    logger.info(f"PersonService: 用户 {user_id} 活动会话 - action: {session_data.get('action')}, waiting_for: {session_data.get('waiting_for')}, 输入: {text[:50]}")
    
    action = session_data.get("action")
    waiting_for = session_data.get("waiting_for")
    
    try:
        # 删除用户输入的命令 - 与flight/hotel完全一致
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        
        if action == "person_search" and waiting_for == "person_name":
            # 处理人物搜索
            await _execute_person_search(update, context, text)
            person_session_manager.remove_session(user_id)
            
        elif action == "person_details" and waiting_for == "person_id":
            # 处理人物详情查询
            try:
                person_id = int(text)
                await _execute_person_details(update, context, person_id)
            except ValueError:
                await send_error(context, update.message.chat_id, "❌ 人物ID必须是数字")
            person_session_manager.remove_session(user_id)
            
    except Exception as e:
        logger.error(f"处理人物文本输入失败: {e}")
        await send_error(context, update.message.chat_id, f"处理失败: {str(e)}")
        person_session_manager.remove_session(user_id)
    
    # 消息已处理完成
    return

async def _execute_person_details(update: Update, context: ContextTypes.DEFAULT_TYPE, person_id: int) -> None:
    """执行人物详情查询 - 参考_handle_legacy_person_search_callback的正确做法"""
    if not movie_service:
        await send_error(context, update.message.chat_id, "❌ 人物查询服务未初始化")
        return
    
    loading_message = f"🔍 正在获取人物详情 (ID: {person_id})... ⏳"
    
    message = await send_message_with_auto_delete(
        context=context,
        chat_id=update.message.chat_id,
        text=foldable_text_v2(loading_message),
        parse_mode="MarkdownV2"
    )
    
    try:
        detail_data = await movie_service.get_person_details(person_id)
        if detail_data:
            result_text, profile_url = movie_service.format_person_details(detail_data)
            
            # 参考原来的逻辑：如果有头像，发送图片并删除loading消息
            if profile_url:
                try:
                    detail_message = await context.bot.send_photo(
                        chat_id=update.message.chat_id,
                        photo=profile_url,
                        caption=foldable_text_with_markdown_v2(result_text),
                        parse_mode="MarkdownV2"
                    )
                    # 删除loading消息
                    await message.delete()
                    # 调度自动删除图片消息
                    from utils.message_manager import _schedule_deletion
                    from utils.config_manager import get_config
                    config = get_config()
                    await _schedule_deletion(context, detail_message.chat_id, detail_message.message_id, config.auto_delete_delay)
                    return
                    
                except Exception as photo_error:
                    logger.warning(f"发送头像失败: {photo_error}，改用文本消息")
                    # 图片发送失败，更新为文本消息
                    await message.edit_text(
                        text=foldable_text_with_markdown_v2(result_text),
                        parse_mode="MarkdownV2"
                    )
                    return
            else:
                # 没有头像，更新为文本消息
                await message.edit_text(
                    text=foldable_text_with_markdown_v2(result_text),
                    parse_mode="MarkdownV2"
                )
        else:
            await message.edit_text(f"❌ 未找到ID为 {person_id} 的人物")
            
    except Exception as e:
        logger.error(f"获取人物详情失败: {e}")
        await message.edit_text(f"❌ 获取详情失败: {str(e)}")

async def _handle_legacy_person_search_callback(query, context, callback_data):
    """处理原有的人物搜索回调逻辑 - 保持向后兼容"""
    user_id = query.from_user.id
    
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
                            
                        except Exception as photo_error:
                            logger.warning(f"发送头像失败: {photo_error}，改用文本消息")
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
                
    except Exception as e:
        logger.error(f"处理旧人物搜索回调失败: {e}")
        await query.edit_message_text("❌ 处理选择时发生错误")

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
    
    async def get_justwatch_popular_content(self, country: str = "US", content_type: str = "all", count: int = 20) -> Optional[List]:
        """使用JustWatch API获取热门内容
        
        Args:
            country: 国家代码，默认US
            content_type: 内容类型 (movie, show, all)，默认all
            count: 返回数量，默认20
            
        Returns:
            List of MediaEntry with streaming charts data, or None if failed
        """
        if not JUSTWATCH_AVAILABLE:
            logger.warning("JustWatch API不可用")
            return None
            
        try:
            # JustWatch API只能通过搜索获取热门内容
            # 使用空字符串搜索获取最热门的内容
            popular_results = justwatch_search("", country=country, count=count)
            
            if not popular_results:
                logger.warning("JustWatch搜索返回空结果")
                return None
            
            filtered_results = []
            for entry in popular_results:
                # 根据content_type过滤
                if content_type == "movie" and entry.object_type != "MOVIE":
                    continue
                elif content_type == "show" and entry.object_type != "SHOW": 
                    continue
                
                # 只返回有StreamingCharts数据的内容，或者至少有offers的内容
                if (entry.streaming_charts and entry.streaming_charts.rank) or entry.offers:
                    filtered_results.append(entry)
            
            # 按照排名排序（如果有排名数据的话）
            def sort_key(entry):
                if entry.streaming_charts and entry.streaming_charts.rank:
                    return entry.streaming_charts.rank
                return 9999  # 没有排名的放在后面
            
            filtered_results.sort(key=sort_key)
            
            return filtered_results
            
        except Exception as e:
            logger.error(f"JustWatch热门内容获取失败: {e}")
            return None

    async def _get_justwatch_trending_movies(self, country: str = "US", limit: int = 15) -> Optional[List]:
        """获取JustWatch热门电影排行榜"""
        return await self.get_justwatch_popular_content(country=country, content_type="movie", count=limit)

    async def _get_justwatch_trending_tv(self, country: str = "US", limit: int = 15) -> Optional[List]:
        """获取JustWatch热门电视剧排行榜"""  
        return await self.get_justwatch_popular_content(country=country, content_type="show", count=limit)

    def _calculate_streaming_score(self, entry) -> float:
        """计算综合流媒体热度分数"""
        score = 0.0
        
        # 1. JustWatch streaming charts权重 (40%)
        if hasattr(entry, 'streaming_charts') and entry.streaming_charts:
            charts = entry.streaming_charts
            
            # 排名分数 (越小越好，转换为分数)
            if charts.rank:
                rank_score = max(0, 1000 - charts.rank) / 1000 * 100
                score += rank_score * 0.25
            
            # 趋势分数
            trend_bonus = {'UP': 20, 'STABLE': 10, 'DOWN': 0}.get(charts.trend, 0)
            score += trend_bonus * 0.05
            
            # 榜单停留时间分数
            if charts.days_in_top_100:
                days_score = min(charts.days_in_top_100, 100) / 100 * 50
                score += days_score * 0.10
        
        # 2. JustWatch评分权重 (20%)
        if hasattr(entry, 'scoring') and entry.scoring and entry.scoring.jw_rating:
            jw_score = entry.scoring.jw_rating * 100  # 转换为百分制
            score += jw_score * 0.20
        
        # 3. TMDB热度权重 (25%)
        if hasattr(entry, 'scoring') and entry.scoring and entry.scoring.tmdb_popularity:
            # TMDB热度通常0-200，标准化到100
            tmdb_score = min(entry.scoring.tmdb_popularity, 200) / 200 * 100
            score += tmdb_score * 0.25
        
        # 4. 用户互动权重 (15%)
        if hasattr(entry, 'interactions') and entry.interactions:
            interactions = entry.interactions
            if interactions.likes and interactions.dislikes:
                total = interactions.likes + interactions.dislikes
                if total > 0:
                    like_ratio = interactions.likes / total
                    # 考虑互动总量和喜欢比例
                    interaction_score = (like_ratio * 50) + (min(total, 10000) / 10000 * 50)
                    score += interaction_score * 0.15
        
        return score

    async def get_comprehensive_streaming_ranking(self, content_type: str = "movie", country: str = "US", limit: int = 20) -> Optional[List]:
        """获取综合流媒体热度排行榜
        
        Args:
            content_type: "movie" 或 "show"
            country: 国家代码
            limit: 返回数量
        """
        try:
            # 获取多个数据源
            justwatch_data = await self.get_justwatch_popular_content(
                country=country, content_type=content_type, count=50  # 获取更多数据用于排序
            )
            
            if not justwatch_data:
                return None
            
            # 为每个条目计算综合热度分数
            scored_items = []
            for entry in justwatch_data:
                score = self._calculate_streaming_score(entry)
                scored_items.append({
                    'entry': entry,
                    'score': score
                })
            
            # 按分数排序
            scored_items.sort(key=lambda x: x['score'], reverse=True)
            
            # 返回排序后的entry列表
            return [item['entry'] for item in scored_items[:limit]]
            
        except Exception as e:
            logger.error(f"获取综合流媒体排行榜失败: {e}")
            return None
    
    async def get_multi_country_streaming_ranking(self, content_type: str = "movie", countries: List[str] = None, limit: int = 20) -> Optional[List]:
        """获取多国综合流媒体热度排行榜
        
        Args:
            content_type: "movie" 或 "show"
            countries: 国家代码列表，默认为主要国家
            limit: 返回数量
        """
        if countries is None:
            countries = ["US", "JP", "KR", "TH", "SG", "MY", "TW", "HK"]
        
        try:
            logger.info(f"开始获取多国综合排行榜: {countries}")
            all_entries = {}  # 使用字典去重，key为title+year
            country_scores = {}  # 记录每个内容在各国的排名
            
            # 从每个国家获取数据
            for country in countries:
                try:
                    logger.info(f"获取 {country} 的数据...")
                    country_data = await self.get_justwatch_popular_content(
                        country=country, content_type=content_type, count=30
                    )
                    
                    if country_data:
                        for rank, entry in enumerate(country_data, 1):
                            # 创建唯一标识符
                            title = entry.title
                            year = getattr(entry, 'release_date', '')[:4] if hasattr(entry, 'release_date') and entry.release_date else ''
                            if not year and hasattr(entry, 'original_release_year'):
                                year = str(entry.original_release_year)
                            
                            unique_id = f"{title}_{year}".lower().replace(" ", "_")
                            
                            # 如果是新内容，添加到字典
                            if unique_id not in all_entries:
                                all_entries[unique_id] = entry
                                country_scores[unique_id] = {}
                            
                            # 记录在该国家的排名（排名越高分数越高）
                            rank_score = max(0, 100 - rank * 2)  # 第1名=98分，第2名=96分，依此类推
                            country_scores[unique_id][country] = rank_score
                            
                            logger.debug(f"  {country}: #{rank} {title} -> {rank_score}分")
                            
                except Exception as e:
                    logger.warning(f"获取 {country} 数据失败: {e}")
                    continue
            
            # 计算综合分数并排序
            scored_items = []
            for unique_id, entry in all_entries.items():
                country_data = country_scores[unique_id]
                
                # 基础分数：各国排名分数的平均值
                base_score = sum(country_data.values()) / len(country_data) if country_data else 0
                
                # 覆盖度加权：在更多国家有排名的内容获得额外分数
                coverage_bonus = len(country_data) * 5  # 每个国家额外5分
                
                # 流媒体热度分数（如果有的话）
                streaming_score = self._calculate_streaming_score(entry) * 0.3
                
                final_score = base_score + coverage_bonus + streaming_score
                
                scored_items.append({
                    'entry': entry,
                    'score': final_score,
                    'countries': list(country_data.keys()),
                    'country_ranks': country_data
                })
                
                logger.debug(f"综合评分: {entry.title} -> {final_score:.1f} (基础:{base_score:.1f} 覆盖:{coverage_bonus} 流媒体:{streaming_score:.1f})")
            
            # 按分数排序
            scored_items.sort(key=lambda x: x['score'], reverse=True)
            
            # 返回结果，包含额外的多国排名信息
            results = []
            for item in scored_items[:limit]:
                entry = item['entry']
                # 创建包含多国数据的包装对象
                wrapper = {
                    'entry': entry,
                    'multi_country_data': {
                        'score': item['score'],
                        'countries': item['countries'],
                        'country_ranks': item['country_ranks']
                    }
                }
                results.append(wrapper)
            
            logger.info(f"多国综合排行榜完成，共 {len(results)} 个结果")
            return results
            
        except Exception as e:
            logger.error(f"获取多国综合排行榜失败: {e}")
            return None
    
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
                # 创建包含TMDB ID的搜索数据结构
                search_data = {
                    "id": content_id  # 关键：直接传递TMDB ID
                }
                if content_type == "movie":
                    search_data["original_title"] = title
                    search_data["title"] = title
                else:
                    search_data["original_name"] = title
                    search_data["name"] = title
                
                # 当用户已经选择了具体内容时，不使用智能匹配
                justwatch_results = await self._enhanced_justwatch_search(search_data, title, content_type, use_smart_matching=False)
                
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
        
        # 相似度阈值：只接受高度匹配的结果，避免匹配到错误的内容
        # - 1.0: 完全匹配（理想）
        # - 0.85+: 高匹配度（可接受）
        # - <0.85: 可能是错误匹配，不使用
        if similarity < 0.85:
            logger.info(f"JustWatch匹配度不足，跳过: '{search_title}' vs '{result_title}' (相似度: {similarity:.2f}，需要≥0.85)")
            return False
        else:
            logger.info(f"JustWatch匹配度极高，使用: '{search_title}' vs '{result_title}' (相似度: {similarity:.2f})")
        
        return True
    
    async def _get_english_titles(self, tmdb_id: int, content_type: str) -> List[str]:
        """从TMDB API获取英文标题，优先从alternative_titles获取真正的英文标题"""
        english_titles = []
        
        try:
            logger.info(f"开始获取TMDB ID {tmdb_id} ({content_type})的英文标题")
            
            # 优先：获取alternative_titles中的英文标题（最准确）
            alt_titles_endpoint = f"{'movie' if content_type == 'movie' else 'tv'}/{tmdb_id}/alternative_titles"
            logger.info(f"优先获取alternative_titles: {alt_titles_endpoint}")
            alt_titles_data = await self._make_tmdb_request(alt_titles_endpoint)
            
            # 详细记录alternative_titles的响应
            logger.info(f"alternative_titles API完整响应: {alt_titles_data}")
            
            # 验证返回的ID是否匹配
            if alt_titles_data and alt_titles_data.get('id') != tmdb_id:
                logger.warning(f"⚠️ API返回的ID {alt_titles_data.get('id')} 与请求的ID {tmdb_id} 不匹配！")
                logger.warning(f"这可能是TMDB数据错误，跳过alternative_titles")
                alt_titles_data = None  # 忽略错误的数据
            
            if alt_titles_data and 'results' in alt_titles_data:
                logger.info(f"获取到{len(alt_titles_data['results'])}个alternative titles")
                for title_info in alt_titles_data['results']:
                    country = title_info.get('iso_3166_1')
                    title = title_info.get('title')
                    title_type = title_info.get('type', '')
                    logger.info(f"  alternative title: {title} (国家: {country}, 类型: {title_type})")
                    
                    # 优先获取英语国家的标题，不再依赖_is_likely_english判断
                    if country in ['US', 'GB', 'CA', 'AU'] and title and title not in english_titles:
                        english_titles.append(title)
                        logger.info(f"  ✓ 添加英语国家标题: {title}")
                    
                    # 如果是任何标题包含常见的英文词汇，也添加进去
                    elif title and any(word.lower() in title.lower() for word in ['flower', 'sea', 'the', 'and', 'of', 'in', 'to']) and title not in english_titles:
                        english_titles.append(title)
                        logger.info(f"  ✓ 添加可能的英文标题: {title} (包含英文词汇)")
            else:
                logger.info("没有获取到alternative_titles数据或results字段为空")
            
            # 补充：无论是否找到alternative titles，都获取英文API的标题作为对比
            logger.info(f"处理完alternative_titles后的english_titles: {english_titles}")
            if not english_titles:
                logger.info("没有找到alternative titles，获取英文API标题作为补充...")
                english_data = await self._make_tmdb_request(f"{'movie' if content_type == 'movie' else 'tv'}/{tmdb_id}", language="en-US")
                if english_data:
                    title_field = 'title' if content_type == 'movie' else 'name'
                    title = english_data.get(title_field)
                    original_title = english_data.get('original_title' if content_type == 'movie' else 'original_name')
                    
                    # 详细记录所有可能包含标题的字段
                    logger.info(f"  英文API完整响应的标题相关字段:")
                    logger.info(f"    name: {english_data.get('name')}")
                    logger.info(f"    title: {english_data.get('title')}")
                    logger.info(f"    original_name: {english_data.get('original_name')}")
                    logger.info(f"    original_title: {english_data.get('original_title')}")
                    logger.info(f"    tagline: {english_data.get('tagline')}")
                    
                    logger.info(f"  使用的title_field: {title_field}")
                    logger.info(f"  提取的标题: {title}")
                    logger.info(f"  提取的原始标题: {original_title}")
                    
                    # 直接添加英文API的标题，不再检查是否为英文
                    if title:
                        english_titles.append(title)
                        logger.info(f"  ✓ 添加英文API标题: {title}")
                    
                    # 添加原始标题（如果不重复）
                    if original_title and original_title not in english_titles:
                        english_titles.append(original_title)
                        logger.info(f"  ✓ 添加原始标题: {original_title}")
                        
        except Exception as e:
            logger.warning(f"获取英文标题时出错: {e}")
        
        logger.info(f"最终获取到的英文标题: {english_titles}")
        return english_titles

    async def _search_tmdb_for_id(self, title: str, content_type: str) -> List[Dict]:
        """通过标题搜索TMDB获取ID和基本信息"""
        try:
            endpoint = f"search/{'movie' if content_type == 'movie' else 'tv'}"
            params = {
                "query": title,
                "language": "zh-CN",
                "include_adult": False
            }
            
            logger.info(f"搜索TMDB: {endpoint} with query '{title}'")
            data = await self._make_tmdb_request(endpoint, params)
            
            if data and data.get('results'):
                logger.info(f"TMDB搜索到 {len(data['results'])} 个结果")
                return data['results']
            else:
                logger.info(f"TMDB搜索无结果")
                return []
                
        except Exception as e:
            logger.warning(f"TMDB搜索失败: {e}")
            return []
    
    def _find_best_match_from_search(self, search_results: List[Dict], query: str) -> Optional[Dict]:
        """从搜索结果中找到最匹配查询词的结果"""
        if not search_results or not query:
            return None
        
        query_lower = query.lower().strip()
        best_match = None
        best_score = 0
        
        for result in search_results:
            # 获取节目名称
            name = result.get('name') or result.get('title', '')
            original_name = result.get('original_name') or result.get('original_title', '')
            
            # 计算匹配度
            name_score = self._calculate_title_similarity(query_lower, name.lower())
            original_score = self._calculate_title_similarity(query_lower, original_name.lower())
            
            # 取最高分
            max_score = max(name_score, original_score)
            
            logger.info(f"  搜索结果匹配度: '{name}' / '{original_name}' -> {max_score:.2f}")
            
            # 如果完全匹配，直接返回
            if max_score >= 0.85:
                logger.info(f"  ✓ 找到完全匹配: {name}")
                return result
            
            # 记录最佳匹配
            if max_score > best_score:
                best_score = max_score
                best_match = result
        
        if best_match and best_score >= 0.6:  # 至少60%相似度
            name = best_match.get('name') or best_match.get('title', '')
            logger.info(f"  ✓ 最佳匹配 (相似度: {best_score:.2f}): {name}")
            return best_match
        
        logger.info(f"  未找到足够匹配的结果 (最高相似度: {best_score:.2f})")
        return search_results[0] if search_results else None  # 如果没有好的匹配，返回第一个

    async def _enhanced_justwatch_search(self, tmdb_data: Dict, primary_title: str, content_type: str, use_smart_matching: bool = True) -> Optional[List]:
        """增强的JustWatch搜索策略 - 尝试多个标题"""
        titles_to_try = []
        
        # 从TMDB数据中提取所有可能的标题
        if content_type == "movie":
            original_title = tmdb_data.get("original_title", "")
            local_title = tmdb_data.get("title", "")
            tmdb_id = tmdb_data.get("id")
        else:
            original_title = tmdb_data.get("original_name", "")
            local_title = tmdb_data.get("name", "")
            tmdb_id = tmdb_data.get("id")
        
        # 如果原标题不是英文，尝试获取英文标题
        english_titles = []
        logger.info(f"JustWatch: 检查原标题是否为英文: '{original_title}' -> {self._is_likely_english(original_title)}")
        logger.info(f"JustWatch: TMDB ID: {tmdb_id}")
        
        if not self._is_likely_english(original_title):
            if tmdb_id:
                logger.info(f"JustWatch: 使用已有TMDB ID获取英文标题...")
                english_titles = await self._get_english_titles(tmdb_id, content_type)
                logger.info(f"JustWatch: 获取到的英文标题: {english_titles}")
            else:
                # 如果没有TMDB ID，尝试通过搜索获取
                logger.info(f"JustWatch: 没有TMDB ID，尝试通过标题搜索获取...")
                search_results = await self._search_tmdb_for_id(original_title or primary_title, content_type)
                if search_results:
                    logger.info(f"JustWatch: TMDB搜索到可能匹配: {search_results}")
                    
                    # 根据use_smart_matching决定是否使用智能匹配
                    if use_smart_matching:
                        # 寻找最匹配的搜索结果，而不是简单使用第一个
                        best_match = self._find_best_match_from_search(search_results, original_title or primary_title)
                        logger.info(f"JustWatch: 智能匹配模式 - 使用最佳匹配结果")
                    else:
                        # 直接使用第一个搜索结果（用户已经通过其他方式指定了具体内容）
                        best_match = search_results[0]
                        logger.info(f"JustWatch: 直接模式 - 使用第一个搜索结果")
                    
                    if best_match:
                        result_tmdb_id = best_match.get('id')
                        if result_tmdb_id:
                            logger.info(f"JustWatch: 使用匹配结果 (ID: {result_tmdb_id})获取英文标题...")
                            result_english_titles = await self._get_english_titles(result_tmdb_id, content_type)
                            english_titles.extend(result_english_titles)
                            
                            # 同时添加搜索结果中的英文标题
                            if content_type == "movie":
                                result_title = best_match.get('title')
                                result_original = best_match.get('original_title')
                            else:
                                result_title = best_match.get('name')
                                result_original = best_match.get('original_name')
                            
                            if result_title and self._is_likely_english(result_title) and result_title not in english_titles:
                                english_titles.append(result_title)
                            if result_original and self._is_likely_english(result_original) and result_original not in english_titles:
                                english_titles.append(result_original)
                    
                    logger.info(f"JustWatch: 通过TMDB搜索获取到的英文标题: {english_titles}")
        else:
            if self._is_likely_english(original_title):
                logger.info(f"JustWatch: 原标题已是英文，跳过英文标题获取")
            if not tmdb_id:
                logger.info(f"JustWatch: 缺少TMDB ID，但原标题是英文")
        
        # 构建搜索标题列表，按优先级排序
        # 优先级：1. TMDB英文标题 2. 英文原标题 3. 主要标题 4. 本地化标题
        if english_titles:
            # 有英文标题时，优先使用英文标题
            titles_to_try.extend(english_titles)
            if original_title and original_title not in titles_to_try:
                titles_to_try.append(original_title)
            if local_title and local_title not in titles_to_try:
                titles_to_try.append(local_title)
            if primary_title and primary_title not in titles_to_try:
                titles_to_try.append(primary_title)
        elif original_title and self._is_likely_english(original_title):
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
    
    def format_justwatch_popular_content(self, content_list: List, content_type: str = "all", country: str = "US") -> str:
        """格式化JustWatch热门内容"""
        if not content_list:
            return "❌ 没有找到JustWatch热门内容"
        
        # 获取当前时间用于更新时间显示
        from datetime import datetime
        current_time = datetime.now().strftime("%Y-%m-%d")
        
        # 根据内容类型设置标题
        type_name = {
            "movie": "电影",
            "show": "电视剧", 
            "all": "影视内容"
        }.get(content_type, "内容")
        
        country_flag = get_country_flag(country)
        lines = [f"📺 **JustWatch {country_flag} {type_name}流媒体热门排行榜** (更新: {current_time})\n"]
        
        for i, entry in enumerate(content_list[:10], 1):
            title = entry.title
            year = entry.release_year
            content_type_icon = "🎬" if entry.object_type == "MOVIE" else "📺"
            tmdb_id = entry.tmdb_id
            
            # 排名和趋势信息
            rank_info = ""
            if entry.streaming_charts and entry.streaming_charts.rank:
                rank = entry.streaming_charts.rank
                trend = entry.streaming_charts.trend
                trend_diff = entry.streaming_charts.trend_difference
                
                # 趋势符号
                trend_symbol = {
                    "UP": "📈", 
                    "DOWN": "📉", 
                    "STABLE": "➡️"
                }.get(trend, "➡️")
                
                # 趋势变化文本
                if trend_diff and trend_diff != 0:
                    if trend == "UP":
                        rank_info = f" #{rank} (↑{abs(trend_diff)})"
                    elif trend == "DOWN":
                        rank_info = f" #{rank} (↓{abs(trend_diff)})"
                    else:
                        rank_info = f" #{rank} (持平)"
                else:
                    rank_info = f" #{rank}"
                
                lines.append(f"{i}. {content_type_icon} **{title}** ({year}) {trend_symbol}{rank_info}")
            else:
                lines.append(f"{i}. {content_type_icon} **{title}** ({year})")
            
            # 可用平台信息
            platforms = []
            for offer in entry.offers[:3]:  # 只显示前3个平台
                platform_name = offer.package.name
                if platform_name not in platforms:
                    platforms.append(platform_name)
            
            if platforms:
                lines.append(f"   🎬 平台: {' | '.join(platforms)}")
            
            # 显示排行榜统计（如果有的话）
            if entry.streaming_charts:
                chart_stats = []
                if hasattr(entry.streaming_charts, 'days_in_top_10') and entry.streaming_charts.days_in_top_10:
                    chart_stats.append(f"前10榜单{entry.streaming_charts.days_in_top_10}天")
                if hasattr(entry.streaming_charts, 'top_rank') and entry.streaming_charts.top_rank:
                    chart_stats.append(f"历史最高#{entry.streaming_charts.top_rank}")
                
                if chart_stats:
                    lines.append(f"   📊 {' | '.join(chart_stats)}")
            
            # JustWatch评分（如果有的话）
            if hasattr(entry, 'scoring') and entry.scoring and entry.scoring.jw_rating:
                lines.append(f"   ⭐ JW评分: {entry.scoring.jw_rating:.1f}/10")
            
            # 添加复制命令
            if tmdb_id:
                detail_cmd = "/movie_detail" if entry.object_type == "MOVIE" else "/tv_detail"
                lines.append(f"   `{detail_cmd} {tmdb_id}`")
            else:
                # 如果没有TMDB ID，使用搜索命令
                search_cmd = "/movie" if entry.object_type == "MOVIE" else "/tv"
                lines.append(f"   `{search_cmd} {title}`")
            
            lines.append("")
        
        # 添加说明和使用提示
        lines.extend([
            "─────────────────────────",
            "💡 **数据源说明**:",
            "• 📺 JustWatch - 流媒体平台排名数据",
            "• 📈📉➡️ 排名趋势: 上升/下降/稳定", 
            "• 🎬 平台数据基于用户观看行为统计",
            "",
            f"💡 使用 `/movie_detail <标题>` 或 `/tv_detail <标题>` 查看详情"
        ])
        
        return "\n".join(lines)
    
    def format_multi_country_streaming_ranking(self, content_list: List, content_type: str = "movie", countries: List[str] = None) -> str:
        """格式化多国综合流媒体热度排行榜"""
        if not content_list:
            return "❌ 没有找到多国流媒体热度排行榜数据"
        
        from datetime import datetime
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        type_name = "电影" if content_type == "movie" else "电视剧"
        countries_str = " | ".join([get_country_flag(c) for c in (countries or ["US", "JP", "KR", "TH", "SG", "MY", "TW", "HK"])])
        
        lines = [f"🌍 **多国综合流媒体{type_name}热度排行榜** (更新: {current_time})", 
                f"📊 数据来源: {countries_str}\n"]
        
        for i, item in enumerate(content_list[:15], 1):
            # 处理新的数据结构
            if isinstance(item, dict) and 'entry' in item:
                entry = item['entry']
                multi_data = item.get('multi_country_data', {})
            else:
                # 向后兼容旧格式
                entry = item
                multi_data = getattr(entry, 'multi_country_data', {})
            
            title = entry.title
            year = getattr(entry, 'original_release_year', '') or getattr(entry, 'release_date', '')[:4] if hasattr(entry, 'release_date') and entry.release_date else ''
            content_icon = "🎬" if entry.object_type == "MOVIE" else "📺"
            
            # 获取多国数据
            score = multi_data.get('score', 0)
            countries_with_rank = multi_data.get('countries', [])
            country_ranks = multi_data.get('country_ranks', {})
            
            # 基本信息行
            coverage_info = f"({len(countries_with_rank)}国上榜)" if countries_with_rank else ""
            lines.append(f"**#{i}** {content_icon} **{title}** ({year}) `综合热度: {score:.1f}` {coverage_info}")
            
            # 各国排名详情
            rank_details = []
            for country in sorted(countries_with_rank):
                flag = get_country_flag(country)
                rank_score = country_ranks.get(country, 0)
                # 根据分数反推大致排名
                approx_rank = max(1, int((100 - rank_score) / 2 + 1))
                rank_details.append(f"{flag}#{approx_rank}")
            
            if rank_details:
                # 每行最多显示6个国家，避免过长
                for chunk_start in range(0, len(rank_details), 6):
                    chunk = rank_details[chunk_start:chunk_start + 6]
                    lines.append(f"   📊 {' | '.join(chunk)}")
            
            # 流媒体热度信息（如果有的话）
            if hasattr(entry, 'streaming_charts') and entry.streaming_charts:
                charts = entry.streaming_charts
                if charts.rank:
                    trend_symbol = {'UP': '📈', 'DOWN': '📉', 'STABLE': '➡️'}.get(charts.trend, '➡️')
                    lines.append(f"   🎯 主要市场排名: {trend_symbol}#{charts.rank}")
            
            # 评分信息
            ratings = []
            if hasattr(entry, 'scoring') and entry.scoring:
                if entry.scoring.tmdb_popularity:
                    ratings.append(f"TMDB热度: {entry.scoring.tmdb_popularity:.1f}")
                if entry.scoring.jw_rating:
                    jw_score = entry.scoring.jw_rating * 10
                    ratings.append(f"JW评分: {jw_score:.1f}")
            
            if ratings:
                lines.append(f"   ⭐ {' | '.join(ratings)}")
            
            # 显示可用平台（取第一个国家的数据作为示例）
            if hasattr(entry, 'offers') and entry.offers:
                platforms = []
                for offer in entry.offers[:3]:  # 只显示前3个平台
                    if hasattr(offer, 'package') and offer.package and offer.package.name:
                        platforms.append(offer.package.name)
                
                if platforms:
                    lines.append(f"   🎬 主要平台: {' | '.join(platforms)}")
            
            # 添加详情命令
            tmdb_id = entry.tmdb_id
            if tmdb_id:
                detail_cmd = "/movie_detail" if entry.object_type == "MOVIE" else "/tv_detail"
                lines.append(f"   `{detail_cmd} {tmdb_id}`")
            
            lines.append("")  # 空行分隔
        
        # 添加说明
        lines.extend([
            "💡 **排行榜说明**:",
            "• 综合热度 = 各国排名平均分 + 覆盖度加成 + 流媒体热度",
            "• 在更多国家上榜的内容会获得额外加分",
            "• 数据来源于各国JustWatch流媒体平台排行榜",
            f"• 🌍 覆盖国家: {countries_str}"
        ])
        
        return "\n".join(lines)

    def format_comprehensive_streaming_ranking(self, content_list: List, content_type: str = "movie", country: str = "US") -> str:
        """格式化综合流媒体热度排行榜"""
        if not content_list:
            return "❌ 没有找到流媒体热度排行榜数据"
        
        from datetime import datetime
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        type_name = "电影" if content_type == "movie" else "电视剧"
        country_flag = get_country_flag(country)
        
        lines = [f"🏆 **{country_flag} 综合流媒体{type_name}热度排行榜** (更新: {current_time})\n"]
        
        for i, entry in enumerate(content_list[:15], 1):
            title = entry.title
            year = entry.release_year
            content_icon = "🎬" if entry.object_type == "MOVIE" else "📺"
            
            # 计算并显示热度分数
            score = self._calculate_streaming_score(entry)
            
            # 基本信息行
            lines.append(f"**#{i}** {content_icon} **{title}** ({year}) `热度: {score:.1f}`")
            
            # 详细指标
            details = []
            
            # JustWatch流媒体排名
            if hasattr(entry, 'streaming_charts') and entry.streaming_charts:
                charts = entry.streaming_charts
                if charts.rank:
                    trend_symbol = {'UP': '📈', 'DOWN': '📉', 'STABLE': '➡️'}.get(charts.trend, '➡️')
                    details.append(f"JW排名: {trend_symbol}#{charts.rank}")
                
                if charts.days_in_top_100:
                    details.append(f"TOP100停留: {charts.days_in_top_100}天")
                
                if charts.top_rank:
                    details.append(f"历史最高: #{charts.top_rank}")
            
            # 评分信息
            ratings = []
            if hasattr(entry, 'scoring') and entry.scoring:
                if entry.scoring.tmdb_popularity:
                    ratings.append(f"TMDB热度: {entry.scoring.tmdb_popularity:.1f}")
                if entry.scoring.jw_rating:
                    jw_score = entry.scoring.jw_rating * 10
                    ratings.append(f"JW评分: {jw_score:.1f}")
                if entry.scoring.imdb_score:
                    ratings.append(f"IMDb: {entry.scoring.imdb_score}")
            
            # 用户互动
            if hasattr(entry, 'interactions') and entry.interactions:
                likes = entry.interactions.likes
                dislikes = entry.interactions.dislikes
                if likes and dislikes:
                    total = likes + dislikes
                    like_percent = likes / total * 100
                    details.append(f"用户喜爱: {like_percent:.1f}% ({total:,}互动)")
            
            # 流媒体平台
            platforms = []
            if hasattr(entry, 'offers') and entry.offers:
                platform_names = set()
                for offer in entry.offers[:3]:  # 只显示前3个平台
                    if offer.package and offer.package.name:
                        platform_names.add(offer.package.name)
                platforms = list(platform_names)[:3]
            
            # 组装详细信息
            if details:
                lines.append(f"   📊 {' | '.join(details)}")
            if ratings:
                lines.append(f"   ⭐ {' | '.join(ratings)}")
            if platforms:
                lines.append(f"   🎬 平台: {' | '.join(platforms)}")
            
            # 搜索命令
            if entry.tmdb_id:
                search_cmd = "/movie_detail" if entry.object_type == "MOVIE" else "/tv_detail"
                lines.append(f"   `{search_cmd} {entry.tmdb_id}`")
            
            lines.append("")
        
        # 添加算法说明
        lines.extend([
            "─────────────────────────",
            "📋 **热度算法说明**:",
            "• 🏆 JustWatch排名 + 趋势 (40%)",
            "• ⭐ 评分质量 (20%)",
            "• 🔥 TMDB全球热度 (25%)",
            "• 👥 用户互动反馈 (15%)",
            "",
            "💡 数据整合多个流媒体平台的观看行为统计"
        ])
        
        return "\n".join(lines)
    
    def format_mixed_popular_content(self, tmdb_data: Dict, justwatch_data: List, content_type: str = "movie", trakt_data: List = None) -> str:
        """格式化混合热门内容（TMDB + JustWatch + Trakt）"""
        from datetime import datetime
        lines = []
        current_time = datetime.now().strftime("%Y-%m-%d")
        
        type_name = "电影" if content_type == "movie" else "电视剧"
        lines.append(f"🔥 **热门{type_name}排行榜** 📊 (更新: {current_time})\n")
        
        # TMDB数据部分
        if tmdb_data and tmdb_data.get("results"):
            lines.append("📊 **TMDB全球热门** (实时数据)")
            results = tmdb_data["results"][:4]  # 显示前4个
            
            for i, item in enumerate(results, 1):
                if content_type == "movie":
                    title = item.get("title", "未知标题")
                    date_field = "release_date"
                    detail_cmd = "/movie_detail"
                else:
                    title = item.get("name", "未知标题") 
                    date_field = "first_air_date"
                    detail_cmd = "/tv_detail"
                
                release_date = item.get(date_field, "")
                year = release_date[:4] if release_date else ""
                vote_average = item.get("vote_average", 0)
                popularity = item.get("popularity", 0)
                item_id = item.get("id")
                
                year_text = f" ({year})" if year else ""
                rating_text = f" ⭐ {vote_average:.1f}" if vote_average > 0 else ""
                
                lines.append(f"{i}. 🎬 **{title}**{year_text}{rating_text}")
                lines.append(f"   📊 TMDB热度: {popularity:.1f}")
                if item_id:
                    lines.append(f"   `{detail_cmd} {item_id}`")
            
            lines.append("")
        
        # JustWatch数据部分
        if justwatch_data:
            lines.append("🏆 **JustWatch综合流媒体热度** (智能排序)")
            
            for i, item in enumerate(justwatch_data[:4], 1):
                # 处理包装对象和直接MediaEntry对象
                if isinstance(item, dict) and 'entry' in item:
                    entry = item['entry']
                else:
                    entry = item
                
                title = entry.title
                year = entry.release_year
                tmdb_id = entry.tmdb_id
                object_type = entry.object_type
                
                # 计算热度分数
                score = self._calculate_streaming_score(entry)
                
                # 排名和趋势信息
                rank_info = f" `热度: {score:.1f}`"
                if hasattr(entry, 'streaming_charts') and entry.streaming_charts and entry.streaming_charts.rank:
                    rank = entry.streaming_charts.rank
                    trend = entry.streaming_charts.trend
                    trend_symbol = {"UP": "📈", "DOWN": "📉", "STABLE": "➡️"}.get(trend, "➡️")
                    rank_info += f" {trend_symbol}#{rank}"
                
                lines.append(f"{i}. 🎬 **{title}** ({year}){rank_info}")
                
                # 简化的详细信息
                details = []
                if hasattr(entry, 'scoring') and entry.scoring:
                    if entry.scoring.jw_rating:
                        details.append(f"JW: {entry.scoring.jw_rating * 10:.1f}")
                    if entry.scoring.imdb_score:
                        details.append(f"IMDb: {entry.scoring.imdb_score}")
                
                # 平台信息（只显示前2个主要平台）
                platforms = []
                if hasattr(entry, 'offers') and entry.offers:
                    platform_names = set()
                    for offer in entry.offers[:2]:
                        if offer.package and offer.package.name:
                            platform_names.add(offer.package.name)
                    platforms = list(platform_names)[:2]
                
                if details or platforms:
                    info_parts = []
                    if details:
                        info_parts.append(" | ".join(details))
                    if platforms:
                        info_parts.append(f"平台: {' | '.join(platforms)}")
                    lines.append(f"   ⭐ {' | '.join(info_parts)}")
                
                # 优先使用TMDB ID生成详情命令
                if tmdb_id:
                    detail_cmd = "/movie_detail" if object_type == "MOVIE" else "/tv_detail"
                    lines.append(f"   `{detail_cmd} {tmdb_id}`")
            
            lines.append("")
        else:
            lines.extend([
                "⚠️ **JustWatch数据**",
                "❌ JustWatch API暂时不可用",
                ""
            ])
        
        # Trakt数据部分
        if trakt_data:
            lines.append("🎯 **Trakt用户热门** (实时数据)")
            
            for i, item in enumerate(trakt_data[:4], 1):
                if content_type == "movie":
                    movie_data = item.get("movie", {})
                    title = movie_data.get("title", "未知标题")
                    year = movie_data.get("year", "")
                    tmdb_id = movie_data.get("ids", {}).get("tmdb")
                    watchers = item.get("watchers") or 0
                    plays = item.get("plays") or 0
                    
                    year_text = f" ({year})" if year else ""
                    stats_text = f"👥 {watchers}人观看" + (f" | 🎬 {plays}次播放" if plays else "")
                    
                    if tmdb_id:
                        lines.append(f"{i}. 🎬 **{title}**{year_text}")
                        lines.append(f"   {stats_text}")
                        lines.append(f"   `/movie_detail {tmdb_id}`")
                    else:
                        lines.append(f"{i}. 🎬 **{title}**{year_text}")
                        lines.append(f"   {stats_text}")
                else:
                    show_data = item.get("show", {})
                    title = show_data.get("title", "未知标题")
                    year = show_data.get("year", "")
                    tmdb_id = show_data.get("ids", {}).get("tmdb")
                    watchers = item.get("watchers") or 0
                    
                    year_text = f" ({year})" if year else ""
                    stats_text = f"👥 {watchers}人观看" if watchers > 0 else ""
                    
                    if tmdb_id:
                        lines.append(f"{i}. 🎬 **{title}**{year_text}{stats_text}")
                        lines.append(f"   `/tv_detail {tmdb_id}`")
                    else:
                        lines.append(f"{i}. 🎬 **{title}**{year_text}{stats_text}")
            
            lines.append("")
        else:
            lines.extend([
                "⚠️ **Trakt数据**",
                "❌ Trakt API暂时不可用",
                ""
            ])
        
        # 数据源说明
        lines.extend([
            "─────────────────────────",
            "💡 **数据源说明**:",
            "• 📊 TMDB - 全球电影数据库热度",
            "• 📺 JustWatch - 流媒体平台排名", 
            "• 🎯 Trakt - 用户追踪数据",
            "",
            "🔧 **参数选项**:",
            f"• `/{'movie_hot' if content_type == 'movie' else 'tv_hot'}` - 混合显示所有数据源",
            f"• `/{'movie_hot' if content_type == 'movie' else 'tv_hot'} tmdb` - 仅TMDB热门数据",
            f"• `/{'movie_hot' if content_type == 'movie' else 'tv_hot'} justwatch` - 仅JustWatch排行榜",
            f"• `/{'movie_hot' if content_type == 'movie' else 'tv_hot'} justwatch US` - 指定国家JustWatch数据",
            f"• `/{'movie_hot' if content_type == 'movie' else 'tv_hot'} trakt` - 仅Trakt用户数据"
        ])
        
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
    
    def format_trending_persons(self, trending_data: Dict, time_window: str = "day") -> str:
        """格式化热门人物数据 - 专门针对人物优化的格式"""
        if not trending_data or not trending_data.get("results"):
            return "❌ 获取热门人物数据失败"
        
        results = trending_data["results"][:10]  # 显示前10个结果
        time_text = "今日" if time_window == "day" else "本周"
        lines = [f"🌟 *{time_text}热门人物*\n"]
        
        for i, person in enumerate(results, 1):
            name = person.get("name", "未知人物")
            person_id = person.get("id")
            known_for_department = person.get("known_for_department", "")
            
            # 添加部门信息
            department_emoji = {
                "Acting": "🎭",
                "Directing": "🎬", 
                "Writing": "✍️",
                "Production": "🎪",
                "Camera": "📹",
                "Sound": "🎵",
                "Art": "🎨"
            }.get(known_for_department, "👤")
            
            lines.append(f"{i}. {department_emoji} *{name}*")
            if known_for_department:
                department_cn = {
                    "Acting": "演员",
                    "Directing": "导演", 
                    "Writing": "编剧",
                    "Production": "制片人",
                    "Camera": "摄影师",
                    "Sound": "音效师",
                    "Art": "美术师"
                }.get(known_for_department, known_for_department)
                lines.append(f"   🏷️ {department_cn}")
            
            # 显示代表作品（known_for）
            known_for = person.get("known_for", [])
            if known_for:
                works = []
                for work in known_for[:3]:  # 最多显示3部作品
                    if work.get("media_type") == "movie":
                        title = work.get("title", work.get("original_title", ""))
                        if title:
                            works.append(f"🎬 {title}")
                    elif work.get("media_type") == "tv":
                        title = work.get("name", work.get("original_name", ""))
                        if title:
                            works.append(f"📺 {title}")
                
                if works:
                    lines.append(f"   🎯 代表作品: {', '.join(works[:2])}")  # 最多显示2部
            
            lines.append(f"   🆔 ID: `{person_id}`")
            lines.append("")
        
        lines.append("💡 使用人物ID查看详细信息:")
        lines.append("通过 **👤 人物详情** 功能输入ID即可查看完整资料")
        
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
        """格式化流媒体热度排名信息（增强版）"""
        if not justwatch_entry or not hasattr(justwatch_entry, 'streaming_charts') or not justwatch_entry.streaming_charts:
            return ""
        
        charts = justwatch_entry.streaming_charts
        lines = []
        
        # 获取更新时间
        from datetime import datetime, timezone
        try:
            if charts.updated:
                update_time = datetime.fromisoformat(charts.updated.replace('Z', '+00:00'))
                local_time = update_time.replace(tzinfo=timezone.utc).astimezone()
                time_str = local_time.strftime("%m-%d %H:%M")
            else:
                time_str = "未知"
        except:
            time_str = "未知"
        
        # 当前排名和趋势
        if charts.rank:
            trend_emoji = {"UP": "📈", "DOWN": "📉", "STABLE": "➡️"}.get(charts.trend, "➡️")
            trend_text = ""
            if charts.trend_difference and charts.trend_difference != 0:
                if charts.trend == "UP":
                    trend_text = f" ↑{abs(charts.trend_difference)}"
                elif charts.trend == "DOWN":
                    trend_text = f" ↓{abs(charts.trend_difference)}"
                else:
                    trend_text = " (持平)"
            
            lines.append(f"   • 📊 **当前排名**: #{charts.rank:,} {trend_emoji}{trend_text}")
        
        # 历史最高排名和成就
        achievements = []
        if charts.top_rank:
            if charts.top_rank <= 3:
                achievements.append(f"🏆 历史最高#{charts.top_rank}")
            elif charts.top_rank <= 10:
                achievements.append(f"🥉 历史最高#{charts.top_rank}")
            else:
                achievements.append(f"📈 历史最高#{charts.top_rank}")
        
        # 榜单成就统计
        chart_achievements = []
        if hasattr(charts, 'days_in_top_3') and charts.days_in_top_3 > 0:
            chart_achievements.append(f"🔥前3名{charts.days_in_top_3}天")
        if hasattr(charts, 'days_in_top_10') and charts.days_in_top_10 > 0:
            chart_achievements.append(f"⭐前10名{charts.days_in_top_10}天")
        elif hasattr(charts, 'days_in_top_100') and charts.days_in_top_100 > 0:
            chart_achievements.append(f"📋前100名{charts.days_in_top_100}天")
        elif hasattr(charts, 'days_in_top_1000') and charts.days_in_top_1000 > 0:
            chart_achievements.append(f"📊前1000名{charts.days_in_top_1000}天")
        
        # 合并成就信息
        if achievements:
            lines.append(f"   • 🏆 **历史成就**: {' | '.join(achievements)}")
        
        if chart_achievements:
            lines.append(f"   • 📈 **榜单统计**: {' | '.join(chart_achievements)}")
        
        # 趋势分析
        if charts.trend and charts.rank:
            if charts.rank <= 10:
                status = "🔥 热门爆款"
            elif charts.rank <= 50:
                status = "⭐ 热门内容"
            elif charts.rank <= 100:
                status = "📈 上榜内容"
            else:
                status = "📊 榜单内容"
            
            trend_desc = {
                "UP": "持续上升中",
                "DOWN": "热度下降中", 
                "STABLE": "排名稳定"
            }.get(charts.trend, "排名稳定")
            
            lines.append(f"   • 🎯 **状态**: {status} ({trend_desc})")
        
        # 数据源和更新时间
        lines.append(f"   • 🕐 **数据更新**: {time_str} (JustWatch)")
        
        if lines:
            return "📺 **JustWatch流媒体排行榜**:\n" + "\n".join(lines)
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
            "`/streaming_movie_ranking [国家码|multi]` - 获取综合流媒体电影热度排行榜\n"
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
    """处理 /movie_hot 命令 - 获取热门电影（支持多数据源）
    
    用法:
    /movie_hot - 混合显示TMDB、JustWatch和Trakt数据（默认）
    /movie_hot tmdb - 只显示TMDB数据
    /movie_hot justwatch - 多国综合JustWatch数据（默认）
    /movie_hot justwatch US - 显示美国JustWatch数据
    /movie_hot justwatch multi US GB DE - 指定国家多国综合
    /movie_hot trakt - 只显示Trakt用户数据
    """
    if not update.message or not update.effective_chat:
        return
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    if not movie_service:
        error_message = "❌ 电影查询服务未初始化"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        return
    
    # 解析参数
    source = context.args[0].lower() if context.args else "mixed"
    
    # JustWatch源的国家解析逻辑（支持多国模式）
    if source == "justwatch" and len(context.args) > 1:
        # 检查是否为单国模式（单个有效国家代码）
        valid_countries = {"US", "JP", "KR", "TH", "SG", "MY", "TW", "HK"}
        if (len(context.args) == 2 and 
            context.args[1].upper() in valid_countries and 
            context.args[1].lower() != "multi"):
            # 单国模式: /movie_hot justwatch US
            country = context.args[1].upper()
            use_multi_country = False
        else:
            # 多国模式: /movie_hot justwatch 或 /movie_hot justwatch multi [countries...]
            use_multi_country = True
            start_idx = 2 if context.args[1].lower() == "multi" else 1
            countries = None
            if len(context.args) > start_idx:
                countries = [arg.upper() for arg in context.args[start_idx:] 
                           if len(arg) == 2 and arg.upper() in valid_countries]
                if not countries:
                    countries = None
            country = countries  # 存储国家列表
    else:
        # 其他源或无参数时的默认逻辑
        if source == "mixed":
            # 混合模式默认使用多国综合JustWatch数据
            use_multi_country = True
            country = None
        else:
            country = context.args[1].upper() if len(context.args) > 1 else "US"
            use_multi_country = False
    
    # 验证数据源参数
    valid_sources = ["mixed", "tmdb", "justwatch", "trakt"]
    if source not in valid_sources:
        await send_error(
            context,
            update.effective_chat.id,
            foldable_text_v2(f"❌ 无效的数据源: {source}\n支持的数据源: {', '.join(valid_sources)}"),
            parse_mode="MarkdownV2"
        )
        return
    
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="🔍 正在获取热门电影\.\.\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    try:
        if source == "justwatch":
            # 显示JustWatch数据 - 支持单国和多国模式
            if not JUSTWATCH_AVAILABLE:
                await message.edit_text("❌ JustWatch API不可用，请使用TMDB数据源")
                return
            
            if use_multi_country:
                # 多国综合模式
                justwatch_data = await movie_service.get_multi_country_streaming_ranking(
                    content_type="movie", countries=country, limit=10
                )
                if justwatch_data:
                    result_text = movie_service.format_multi_country_streaming_ranking(
                        justwatch_data, content_type="movie", countries=country
                    )
                else:
                    result_text = "❌ JustWatch多国热门电影数据获取失败，请稍后重试"
            else:
                # 单国模式
                justwatch_data = await movie_service.get_comprehensive_streaming_ranking(
                    content_type="movie", country=country, limit=10
                )
                if justwatch_data:
                    result_text = movie_service.format_comprehensive_streaming_ranking(
                        justwatch_data, content_type="movie", country=country
                    )
                else:
                    result_text = "❌ JustWatch热门电影数据获取失败，请稍后重试"
                
        elif source == "tmdb":
            # 只显示TMDB数据
            popular_data = await movie_service.get_popular_movies()
            if popular_data:
                result_text = movie_service.format_popular_movies(popular_data)
            else:
                result_text = "❌ 获取TMDB热门电影失败，请稍后重试"
                
        elif source == "trakt":
            # 只显示Trakt数据
            try:
                trakt_data = await movie_service._get_trakt_trending_movies(15)
                if trakt_data:
                    result_text = movie_service.format_trakt_trending_movies(trakt_data)
                else:
                    result_text = "❌ 获取Trakt热门电影失败，请稍后重试"
            except Exception as e:
                logger.warning(f"获取Trakt电影数据失败: {e}")
                result_text = "❌ Trakt API暂时不可用，请稍后重试"
                
        else:  # mixed
            # 混合显示TMDB、JustWatch和Trakt数据
            tmdb_data = await movie_service.get_popular_movies()
            justwatch_data = None
            trakt_data = None
            
            if JUSTWATCH_AVAILABLE:
                if use_multi_country:
                    # 混合模式使用多国综合JustWatch数据
                    justwatch_data = await movie_service.get_multi_country_streaming_ranking(
                        content_type="movie", countries=country, limit=4
                    )
                else:
                    # 单国模式
                    justwatch_data = await movie_service.get_comprehensive_streaming_ranking(
                        content_type="movie", country=country, limit=4
                    )
            
            # 获取Trakt热门数据
            try:
                trakt_data = await movie_service._get_trakt_trending_movies(8)
            except Exception as e:
                logger.warning(f"获取Trakt电影数据失败: {e}")
            
            if tmdb_data or justwatch_data or trakt_data:
                result_text = movie_service.format_mixed_popular_content(
                    tmdb_data, justwatch_data, content_type="movie", trakt_data=trakt_data
                )
            else:
                result_text = "❌ 获取热门电影数据失败，请稍后重试"
        
        await message.edit_text(
            foldable_text_with_markdown_v2(result_text),
            parse_mode=ParseMode.MARKDOWN_V2
        )
        
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
            "justwatch_search_", "justwatch_offers_"
        ]
        for prefix in prefixes:
            await cache_manager.clear_cache(subdirectory="movie", key_prefix=prefix)
        
        success_message = "✅ 所有影视内容查询缓存已清理（包括电影、电视剧、人物、观看平台、JustWatch数据）。"
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
            "`/streaming_tv_ranking [国家码]` - 获取综合流媒体电视剧热度排行榜\n"
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
    """处理 /tv_hot 命令 - 获取热门电视剧（支持多数据源）
    
    用法:
    /tv_hot - 混合显示TMDB、JustWatch和Trakt数据（默认）
    /tv_hot tmdb - 只显示TMDB数据
    /tv_hot justwatch - 多国综合JustWatch数据（默认）
    /tv_hot justwatch US - 显示美国JustWatch数据
    /tv_hot justwatch multi US GB DE - 指定国家多国综合
    /tv_hot trakt - 只显示Trakt用户数据
    """
    if not update.message or not update.effective_chat:
        return
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    if not movie_service:
        error_message = "❌ 电视剧查询服务未初始化"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        return
    
    # 解析参数
    source = context.args[0].lower() if context.args else "mixed"
    
    # JustWatch源的国家解析逻辑（支持多国模式）
    if source == "justwatch" and len(context.args) > 1:
        # 检查是否为单国模式（单个有效国家代码）
        valid_countries = {"US", "JP", "KR", "TH", "SG", "MY", "TW", "HK"}
        if (len(context.args) == 2 and 
            context.args[1].upper() in valid_countries and 
            context.args[1].lower() != "multi"):
            # 单国模式: /tv_hot justwatch US
            country = context.args[1].upper()
            use_multi_country = False
        else:
            # 多国模式: /tv_hot justwatch 或 /tv_hot justwatch multi [countries...]
            use_multi_country = True
            start_idx = 2 if context.args[1].lower() == "multi" else 1
            countries = None
            if len(context.args) > start_idx:
                countries = [arg.upper() for arg in context.args[start_idx:] 
                           if len(arg) == 2 and arg.upper() in valid_countries]
                if not countries:
                    countries = None
            country = countries  # 存储国家列表
    else:
        # 其他源或无参数时的默认逻辑
        if source == "mixed":
            # 混合模式默认使用多国综合JustWatch数据
            use_multi_country = True
            country = None
        else:
            country = context.args[1].upper() if len(context.args) > 1 else "US"
            use_multi_country = False
    
    # 验证数据源参数
    valid_sources = ["mixed", "tmdb", "justwatch", "trakt"]
    if source not in valid_sources:
        await send_error(
            context,
            update.effective_chat.id,
            foldable_text_v2(f"❌ 无效的数据源: {source}\n支持的数据源: {', '.join(valid_sources)}"),
            parse_mode="MarkdownV2"
        )
        return
    
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="🔍 正在获取热门电视剧\.\.\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    try:
        if source == "justwatch":
            # 显示JustWatch数据 - 支持单国和多国模式
            if not JUSTWATCH_AVAILABLE:
                await message.edit_text("❌ JustWatch API不可用，请使用TMDB数据源")
                return
            
            if use_multi_country:
                # 多国综合模式
                justwatch_data = await movie_service.get_multi_country_streaming_ranking(
                    content_type="show", countries=country, limit=10
                )
                if justwatch_data:
                    result_text = movie_service.format_multi_country_streaming_ranking(
                        justwatch_data, content_type="show", countries=country
                    )
                else:
                    result_text = "❌ JustWatch多国热门电视剧数据获取失败，请稍后重试"
            else:
                # 单国模式
                justwatch_data = await movie_service.get_comprehensive_streaming_ranking(
                    content_type="show", country=country, limit=10
                )
                if justwatch_data:
                    result_text = movie_service.format_comprehensive_streaming_ranking(
                        justwatch_data, content_type="show", country=country
                    )
                else:
                    result_text = "❌ JustWatch热门电视剧数据获取失败，请稍后重试"
                
        elif source == "tmdb":
            # 只显示TMDB数据
            popular_data = await movie_service.get_popular_tv_shows()
            if popular_data:
                result_text = movie_service.format_popular_tv_shows(popular_data)
            else:
                result_text = "❌ 获取TMDB热门电视剧失败，请稍后重试"
                
        elif source == "trakt":
            # 只显示Trakt数据
            try:
                trakt_data = await movie_service._get_trakt_trending_tv(15)
                if trakt_data:
                    result_text = movie_service.format_trakt_trending_tv(trakt_data)
                else:
                    result_text = "❌ 获取Trakt热门电视剧失败，请稍后重试"
            except Exception as e:
                logger.warning(f"获取Trakt电视剧数据失败: {e}")
                result_text = "❌ Trakt API暂时不可用，请稍后重试"
                
        else:  # mixed
            # 混合显示TMDB、JustWatch和Trakt数据
            tmdb_data = await movie_service.get_popular_tv_shows()
            justwatch_data = None
            trakt_data = None
            
            if JUSTWATCH_AVAILABLE:
                if use_multi_country:
                    # 混合模式使用多国综合JustWatch数据
                    justwatch_data = await movie_service.get_multi_country_streaming_ranking(
                        content_type="show", countries=country, limit=4
                    )
                else:
                    # 单国模式
                    justwatch_data = await movie_service.get_comprehensive_streaming_ranking(
                        content_type="show", country=country, limit=4
                    )
            
            # 获取Trakt热门数据
            try:
                trakt_data = await movie_service._get_trakt_trending_tv(8)
            except Exception as e:
                logger.warning(f"获取Trakt电视剧数据失败: {e}")
            
            if tmdb_data or justwatch_data or trakt_data:
                result_text = movie_service.format_mixed_popular_content(
                    tmdb_data, justwatch_data, content_type="tv", trakt_data=trakt_data
                )
            else:
                result_text = "❌ 获取热门电视剧数据失败，请稍后重试"
        
        await message.edit_text(
            foldable_text_with_markdown_v2(result_text),
            parse_mode=ParseMode.MARKDOWN_V2
        )
        
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

async def streaming_movie_ranking_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /streaming_movie_ranking 命令 - 获取综合流媒体电影热度排行榜"""
    if not update.message or not update.effective_chat:
        return
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    if not movie_service:
        error_message = "❌ 电影查询服务未初始化"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        return
    
    # 解析参数 - 默认多国模式，单个国家代码切换到单国模式
    valid_countries = {"US", "GB", "DE", "FR", "JP", "KR", "AU", "CA", "CN"}
    
    # 检查是否为单国模式（单个有效国家代码）
    single_country_mode = (
        context.args and 
        len(context.args) == 1 and 
        context.args[0].upper() in valid_countries and
        context.args[0].lower() != "multi"
    )
    
    if not single_country_mode:
        # 多国模式 (默认或明确指定multi)
        countries = None
        start_idx = 1 if context.args and context.args[0].lower() == "multi" else 0
        
        if context.args and len(context.args) > start_idx:
            countries = [arg.upper() for arg in context.args[start_idx:] if len(arg) == 2 and arg.upper() in valid_countries]
            if not countries:
                countries = None
        
        countries_display = countries or ["US", "JP", "KR", "TH", "SG", "MY", "TW", "HK"]
        message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"🌍 正在获取多国综合流媒体电影热度排行榜...\n📊 数据来源: {' | '.join(countries_display)}",
            parse_mode=ParseMode.MARKDOWN
        )
        
        if not JUSTWATCH_AVAILABLE:
            result_text = "❌ JustWatch API不可用，无法获取流媒体排行榜数据"
        else:
            ranking_data = await movie_service.get_multi_country_streaming_ranking(
                content_type="movie", countries=countries, limit=15
            )
            if ranking_data:
                result_text = movie_service.format_multi_country_streaming_ranking(
                    ranking_data, content_type="movie", countries=countries_display
                )
            else:
                result_text = "❌ 获取多国综合流媒体电影热度排行榜失败，请稍后重试"
    else:
        # 单国模式: /streaming_movie_ranking [US]
        country = context.args[0].upper() if context.args else "US"
        
        valid_countries = {"US", "JP", "KR", "TH", "SG", "MY", "TW", "HK"}
        if country not in valid_countries:
            country = "US"
        
        message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="🔍 正在获取综合流媒体电影热度排行榜...",
            parse_mode=ParseMode.MARKDOWN
        )
        
        if not JUSTWATCH_AVAILABLE:
            result_text = "❌ JustWatch API不可用，无法获取流媒体排行榜数据"
        else:
            ranking_data = await movie_service.get_comprehensive_streaming_ranking(
                content_type="movie", country=country, limit=15
            )
            if ranking_data:
                result_text = movie_service.format_comprehensive_streaming_ranking(
                    ranking_data, content_type="movie", country=country
                )
            else:
                result_text = "❌ 获取流媒体电影排行榜失败，请稍后重试"
        
    await message.edit_text(
        foldable_text_with_markdown_v2(result_text),
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    # 调度删除机器人回复消息
    from utils.message_manager import _schedule_deletion
    from utils.config_manager import get_config
    config = get_config()
    await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)

async def streaming_tv_ranking_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /streaming_tv_ranking 命令 - 获取综合流媒体电视剧热度排行榜"""
    if not update.message or not update.effective_chat:
        return
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    if not movie_service:
        error_message = "❌ 电影查询服务未初始化"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        return
    
    # 解析参数 - 默认多国模式，单个国家代码切换到单国模式
    valid_countries = {"US", "GB", "DE", "FR", "JP", "KR", "AU", "CA", "CN"}
    
    # 检查是否为单国模式（单个有效国家代码）
    single_country_mode = (
        context.args and 
        len(context.args) == 1 and 
        context.args[0].upper() in valid_countries and
        context.args[0].lower() != "multi"
    )
    
    if not single_country_mode:
        # 多国模式 (默认或明确指定multi)
        countries = None
        start_idx = 1 if context.args and context.args[0].lower() == "multi" else 0
        
        if context.args and len(context.args) > start_idx:
            countries = [arg.upper() for arg in context.args[start_idx:] if len(arg) == 2 and arg.upper() in valid_countries]
            if not countries:
                countries = None
        
        countries_display = countries or ["US", "JP", "KR", "TH", "SG", "MY", "TW", "HK"]
        message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"🌍 正在获取多国综合流媒体电视剧热度排行榜...\n📊 数据来源: {' | '.join(countries_display)}",
            parse_mode=ParseMode.MARKDOWN
        )
        
        if not JUSTWATCH_AVAILABLE:
            result_text = "❌ JustWatch API不可用，无法获取流媒体排行榜数据"
        else:
            ranking_data = await movie_service.get_multi_country_streaming_ranking(
                content_type="show", countries=countries, limit=15
            )
            if ranking_data:
                result_text = movie_service.format_multi_country_streaming_ranking(
                    ranking_data, content_type="show", countries=countries_display
                )
            else:
                result_text = "❌ 获取多国综合流媒体电视剧热度排行榜失败，请稍后重试"
    else:
        # 单国模式: /streaming_tv_ranking [US]
        country = context.args[0].upper() if context.args else "US"
        
        valid_countries = {"US", "JP", "KR", "TH", "SG", "MY", "TW", "HK"}
        if country not in valid_countries:
            country = "US"
        
        message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="🔍 正在获取综合流媒体电视剧热度排行榜...",
            parse_mode=ParseMode.MARKDOWN
        )
        
        if not JUSTWATCH_AVAILABLE:
            result_text = "❌ JustWatch API不可用，无法获取流媒体排行榜数据"
        else:
            ranking_data = await movie_service.get_comprehensive_streaming_ranking(
                content_type="show", country=country, limit=15
            )
            if ranking_data:
                result_text = movie_service.format_comprehensive_streaming_ranking(
                    ranking_data, content_type="show", country=country
                )
            else:
                result_text = "❌ 获取流媒体电视剧排行榜失败，请稍后重试"
        
    await message.edit_text(
        foldable_text_with_markdown_v2(result_text),
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
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
    """统一的人物服务主命令 /person - 参考flight/hotel的设计模式"""
    if not update.message or not update.effective_chat:
        return
    
    user_id = update.effective_user.id
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    
    # 如果有参数，解析并直接搜索人物（保持向后兼容）
    if context.args:
        query = " ".join(context.args)
        await _execute_person_search(update, context, query)
        return
    
    # 没有参数，显示主菜单 - 与flight/hotel完全一致的菜单结构
    keyboard = [
        [
            InlineKeyboardButton("🔍 搜索人物", callback_data="person_search"),
            InlineKeyboardButton("👤 人物详情", callback_data="person_details")
        ],
        [
            InlineKeyboardButton("🌟 热门人物", callback_data="person_trending"),
            InlineKeyboardButton("❌ 关闭", callback_data="person_close")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    help_text = """👤 智能人物信息服务

🌍 功能介绍:
• **搜索人物**: 智能搜索全球影视人物信息
• **人物详情**: 获取详细的人物资料和作品
• **热门人物**: 查看当前热门影视人物

🤖 智能搜索支持:
• **中文姓名**: `成龙`, `章子怡`, `汤姆·汉克斯`
• **英文姓名**: `Tom Hanks`, `Jackie Chan`, `Scarlett Johansson`
• **演员/导演**: 自动识别职业类型
• **多重身份**: 演员、导演、制片人等

🌟 丰富信息展示:
• 📊 基本资料（生日、出生地、职业）
• 🎬 代表作品（电影、电视剧）
• 📈 人气评分和粉丝数据
• 🖼️ 高清头像照片

💡 快速使用示例:
`/person 汤姆·汉克斯` - 智能搜索汤姆·汉克斯
`/person Tom Cruise` - 英文姓名搜索
`/person 宫崎骏` - 导演信息查询

请选择功能:"""
    
    await send_message_with_auto_delete(
        context=context,
        chat_id=update.message.chat_id,
        text=foldable_text_with_markdown_v2(help_text),
        parse_mode="MarkdownV2",
        reply_markup=reply_markup
    )

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
                    # 获取增强观看平台数据（包含JustWatch）
                    movie_title = detail_data.get("title", "") or detail_data.get("original_title", "")
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
                    # 获取增强观看平台数据（包含JustWatch）
                    tv_title = detail_data.get("name", "") or detail_data.get("original_name", "")
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
    """处理人物功能的回调查询 - 与flight/hotel完全一致的结构"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = update.effective_user.id
    
    if data == "person_close":
        # 清理用户会话 - 与flight/hotel完全一致
        person_session_manager.remove_session(user_id)
        await query.delete_message()
        return
    
    elif data == "person_main_menu":
        # 清理用户会话并返回主菜单 - 与flight/hotel完全一致
        person_session_manager.remove_session(user_id)
        
        # 返回主菜单
        keyboard = [
            [
                InlineKeyboardButton("🔍 搜索人物", callback_data="person_search"),
                InlineKeyboardButton("👤 人物详情", callback_data="person_details")
            ],
            [
                InlineKeyboardButton("🌟 热门人物", callback_data="person_trending"),
                InlineKeyboardButton("❌ 关闭", callback_data="person_close")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        help_text = """👤 智能人物信息服务

🌍 功能介绍:
• **搜索人物**: 智能搜索全球影视人物信息
• **人物详情**: 获取详细的人物资料和作品
• **热门人物**: 查看当前热门影视人物

🤖 智能搜索支持:
• **中文姓名**: `成龙`, `章子怡`, `汤姆·汉克斯`
• **英文姓名**: `Tom Hanks`, `Jackie Chan`, `Scarlett Johansson`
• **演员/导演**: 自动识别职业类型
• **多重身份**: 演员、导演、制片人等

🌟 丰富信息展示:
• 📊 基本资料（生日、出生地、职业）
• 🎬 代表作品（电影、电视剧）
• 📈 人气评分和粉丝数据
• 🖼️ 高清头像照片

💡 快速使用示例:
`/person 汤姆·汉克斯` - 智能搜索汤姆·汉克斯
`/person Tom Cruise` - 英文姓名搜索
`/person 宫崎骏` - 导演信息查询

请选择功能:"""
        
        await query.edit_message_text(
            text=foldable_text_with_markdown_v2(help_text),
            parse_mode="MarkdownV2",
            reply_markup=reply_markup
        )
    
    elif data == "person_search":
        # 设置会话状态 - 与flight/hotel完全一致的会话管理
        person_session_manager.set_session(user_id, {
            "action": "person_search",
            "waiting_for": "person_name"
        })
        
        search_help_text = """🔍 智能人物搜索

📝 请输入要搜索的人物姓名:

🌟 智能识别支持:
**中文姓名**: `成龙`, `章子怡`, `汤姆·汉克斯`
**英文姓名**: `Tom Hanks`, `Jackie Chan`, `Leonardo DiCaprio`
**导演**: `宫崎骏`, `克里斯托弗·诺兰`, `昆汀·塔伦蒂诺`
**制片人**: `凯文·费奇`, `杰瑞·布鲁克海默`

💡 搜索技巧:
• 支持模糊匹配，无需完全准确
• 中英文姓名都能识别
• 自动匹配最相关的人物
• 显示人物的所有作品和资料

🌍 覆盖范围:
• **好莱坞**: 主流影视明星和幕后人员
• **华语圈**: 港台大陆影视人物
• **国际**: 各国知名导演演员
• **经典**: 历史上的传奇人物"""

        await query.edit_message_text(
            text=foldable_text_with_markdown_v2(search_help_text),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="person_main_menu")]
            ]),
            parse_mode="MarkdownV2"
        )
    
    elif data == "person_details":
        # 设置会话状态
        person_session_manager.set_session(user_id, {
            "action": "person_details",
            "waiting_for": "person_id"
        })
        
        details_help_text = """👤 人物详情查询

📝 请输入人物ID:

💡 如何获取人物ID:
• 先使用 **🔍 搜索人物** 功能
• 在搜索结果中会显示每个人物的ID
• 复制ID数字即可查询详情

🌟 详情信息包含:
• **基本资料**: 姓名、生日、出生地、职业
• **生平介绍**: 详细的个人简介
• **代表作品**: 主要电影和电视作品
• **获奖记录**: 重要奖项和提名
• **高清头像**: 官方宣传照片

📋 示例:
如果搜索结果显示 "🆔 ID: `31`"
则输入 `31` 即可查看该人物详情"""

        await query.edit_message_text(
            text=foldable_text_with_markdown_v2(details_help_text),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="person_main_menu")]
            ]),
            parse_mode="MarkdownV2"
        )
    
    elif data == "person_trending":
        # 热门人物功能 - 使用TMDB API获取真实数据
        loading_message = await query.edit_message_text(
            text="🔍 正在获取热门人物数据... ⏳"
        )
        
        try:
            # 调用TMDB trending person API
            trending_data = await movie_service.get_trending_content("person", "day")
            
            if trending_data and trending_data.get("results"):
                # 格式化热门人物结果
                result_text = movie_service.format_trending_persons(trending_data)
                
                await query.edit_message_text(
                    text=foldable_text_with_markdown_v2(result_text),
                    parse_mode="MarkdownV2",
                    reply_markup=InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("🔍 搜索人物", callback_data="person_search"),
                            InlineKeyboardButton("👤 人物详情", callback_data="person_details")
                        ],
                        [InlineKeyboardButton("🔙 返回主菜单", callback_data="person_main_menu")]
                    ])
                )
            else:
                await query.edit_message_text(
                    text="❌ 获取热门人物数据失败，请稍后重试",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 返回主菜单", callback_data="person_main_menu")]
                    ])
                )
        except Exception as e:
            logger.error(f"获取热门人物失败: {e}")
            await query.edit_message_text(
                text="❌ 获取热门人物时发生错误",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 返回主菜单", callback_data="person_main_menu")]
                ])
            )
    
    # 保留原有的搜索结果处理逻辑
    elif data.startswith("person_select_") or data.startswith("person_page_"):
        # 处理旧的搜索结果回调（兼容性）
        await _handle_legacy_person_search_callback(query, context, data)

# 注册命令
command_factory.register_command("movie", movie_command, permission=Permission.USER, description="搜索电影信息（按钮选择）")
command_factory.register_command("movies", movies_command, permission=Permission.USER, description="搜索电影信息（文本列表）")
command_factory.register_command("movie_hot", movie_hot_command, permission=Permission.USER, description="获取热门电影")
command_factory.register_command("movie_detail", movie_detail_command, permission=Permission.USER, description="获取电影详情")
command_factory.register_command("movie_rec", movie_rec_command, permission=Permission.USER, description="获取电影推荐")
command_factory.register_command("movie_videos", movie_videos_command, permission=Permission.USER, description="获取电影预告片")
command_factory.register_command("movie_reviews", movie_reviews_command, permission=Permission.USER, description="获取电影用户评价")
command_factory.register_command("movie_trending", movie_trending_command, permission=Permission.USER, description="获取Trakt热门电影")
command_factory.register_command("streaming_movie_ranking", streaming_movie_ranking_command, permission=Permission.USER, description="获取综合流媒体电影热度排行榜")
command_factory.register_command("movie_related", movie_related_command, permission=Permission.USER, description="获取Trakt相关电影推荐")
# 已迁移到统一缓存管理命令 /cleancache
# command_factory.register_command("movie_cleancache", movie_clean_cache_command, permission=Permission.ADMIN, description="清理电影和电视剧查询缓存")

# 注册电视剧命令
command_factory.register_command("tv", tv_command, permission=Permission.USER, description="搜索电视剧信息（按钮选择）")
command_factory.register_command("tvs", tvs_command, permission=Permission.USER, description="搜索电视剧信息（文本列表）")
command_factory.register_command("tv_hot", tv_hot_command, permission=Permission.USER, description="获取热门电视剧")
command_factory.register_command("tv_detail", tv_detail_command, permission=Permission.USER, description="获取电视剧详情")
command_factory.register_command("tv_rec", tv_rec_command, permission=Permission.USER, description="获取电视剧推荐")
command_factory.register_command("tv_videos", tv_videos_command, permission=Permission.USER, description="获取电视剧预告片")
command_factory.register_command("tv_reviews", tv_reviews_command, permission=Permission.USER, description="获取电视剧用户评价")
command_factory.register_command("tv_trending", tv_trending_command, permission=Permission.USER, description="获取Trakt热门电视剧")
command_factory.register_command("streaming_tv_ranking", streaming_tv_ranking_command, permission=Permission.USER, description="获取综合流媒体电视剧热度排行榜")
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

# 注册人物搜索命令
# 注册人物相关命令 - 统一的/person命令
command_factory.register_command("person", person_command, permission=Permission.USER, description="智能人物信息服务 - 搜索、详情、热门")

# 注册观看平台命令
command_factory.register_command("movie_watch", movie_watch_command, permission=Permission.USER, description="获取电影观看平台")
command_factory.register_command("tv_watch", tv_watch_command, permission=Permission.USER, description="获取电视剧观看平台")

# 注册回调处理器
command_factory.register_callback(r"^movie_", movie_callback_handler, permission=Permission.USER, description="电影搜索结果选择")
command_factory.register_callback(r"^tv_", tv_callback_handler, permission=Permission.USER, description="电视剧搜索结果选择")
command_factory.register_callback(r"^person_", person_callback_handler, permission=Permission.USER, description="人物功能回调处理 - 搜索、详情、热门等")