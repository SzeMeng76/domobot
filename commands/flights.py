#!/usr/bin/env python3
"""
完整航班搜索服务模块

功能特性:
- 🔍 智能机场搜索和自动补全
- ✈️ 单程/往返/多城市航班搜索
- 📊 价格洞察和历史价格趋势
- 🛒 多平台预订选项比较
- ⚙️ 高级搜索过滤器
- 📲 价格追踪和变化提醒
- 🔗 直接预订链接
- 🌍 碳排放计算
- 💰 最佳价格推荐

基于SerpAPI Google Flights API
"""

import asyncio
import json
import logging
import re
import hashlib
from datetime import datetime, timedelta, date
from typing import Any, Dict, List, Optional, Tuple, Union
from dataclasses import dataclass
from enum import Enum

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, CallbackQueryHandler
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown

from utils.command_factory import command_factory
from utils.config_manager import get_config
from utils.formatter import foldable_text_v2, foldable_text_with_markdown_v2, format_with_markdown_v2
from utils.message_manager import (
    delete_user_command, 
    send_error, 
    send_success, 
    send_message_with_auto_delete,
    send_info,
    send_help
)
from utils.permissions import Permission
from utils.language_detector import detect_user_language
from utils.session_manager import SessionManager
from utils.airport_data import search_airports, get_airport_by_code, Airport

logger = logging.getLogger(__name__)

# 全局变量
cache_manager = None
httpx_client = None

# 创建航班会话管理器
flight_session_manager = SessionManager("FlightService", max_age=1800, max_sessions=200)  # 30分钟会话

# SerpAPI配置
SERPAPI_BASE_URL = "https://serpapi.com/search"

# 机场数据缓存
airport_data_cache = {}

# 价格追踪存储
price_tracking = {}

class TripType(Enum):
    """行程类型枚举"""
    ROUND_TRIP = 1
    ONE_WAY = 2
    MULTI_CITY = 3

class TravelClass(Enum):
    """舱位类型枚举"""
    ECONOMY = 1
    PREMIUM_ECONOMY = 2
    BUSINESS = 3
    FIRST = 4

class SortOption(Enum):
    """排序选项枚举"""
    BEST = "best"
    PRICE = "price"
    DURATION = "duration"
    DEPARTURE_TIME = "departure_time"
    ARRIVAL_TIME = "arrival_time"

@dataclass
class FlightSearchParams:
    """航班搜索参数"""
    departure_id: str
    arrival_id: str
    outbound_date: str
    return_date: Optional[str] = None
    trip_type: TripType = TripType.ONE_WAY
    adults: int = 1
    children: int = 0
    infants_in_seat: int = 0
    infants_on_lap: int = 0
    travel_class: TravelClass = TravelClass.ECONOMY
    max_price: Optional[int] = None
    stops: Optional[int] = None
    exclude_airlines: Optional[List[str]] = None
    include_airlines: Optional[List[str]] = None
    outbound_times: Optional[Dict] = None
    return_times: Optional[Dict] = None
    bags: Optional[int] = None
    sort_by: SortOption = SortOption.BEST
    
@dataclass
class FlightSegment:
    """航班段信息"""
    airline: str
    airline_logo: str
    flight_number: str
    aircraft: str
    departure_airport: Airport
    arrival_airport: Airport
    departure_time: str
    arrival_time: str
    duration: int
    legroom: str = ""
    
@dataclass
class FlightOption:
    """航班选项"""
    flights: List[FlightSegment]
    price: int
    currency: str
    total_duration: int
    layovers: List[Dict]
    carbon_emissions: Dict
    booking_token: str
    booking_options: List[Dict]
    departure_token: Optional[str] = None

@dataclass
class AirportResult:
    """机场API结果"""
    id: str
    name: str
    city: str
    country: str
    country_code: str
    image: str = ""
    
@dataclass
class AirportsResponse:
    """机场API响应"""
    departure_airports: List[AirportResult]
    arrival_airports: List[AirportResult]

async def _schedule_auto_delete(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, delay: int):
    """调度自动删除消息"""
    try:
        if context and hasattr(context, "bot_data"):
            scheduler = context.bot_data.get("message_delete_scheduler")
            if scheduler and hasattr(scheduler, "schedule_deletion"):
                await scheduler.schedule_deletion(chat_id, message_id, delay, None)
                logger.info(f"已调度航班消息删除: chat_id={chat_id}, message_id={message_id}, delay={delay}s")
            else:
                logger.warning(f"消息删除调度器未正确初始化: scheduler={scheduler}")
        else:
            logger.warning("无法获取bot_data或context")
    except Exception as e:
        logger.error(f"调度自动删除失败: {e}")

def set_dependencies(cm, hc=None):
    """设置依赖项"""
    global cache_manager, httpx_client
    cache_manager = cm
    httpx_client = hc

class AdvancedFlightService:
    """高级航班搜索服务类"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session_cache = {}
    
    async def search_airports(self, query: str, client, language: str = "en") -> List[Airport]:
        """智能机场搜索 - 支持城市名、国家名、机场代码"""
        try:
            # 先检查缓存
            cache_key = f"airport_search_{language}_{query.lower()}"
            if cache_key in airport_data_cache:
                return airport_data_cache[cache_key]
            
            # 使用机场数据库进行智能搜索
            from utils.airport_data import search_airports as search_airport_db
            airports = search_airport_db(query)
            
            # 缓存结果
            airport_data_cache[cache_key] = airports
            return airports
            
        except Exception as e:
            logger.error(f"机场搜索失败: {e}")
            return []
    
    async def search_flights(self, params: FlightSearchParams, client, language: str = "en") -> Optional[Dict]:
        """高级航班搜索"""
        try:
            # 验证日期不能是过去的日期
            from datetime import datetime, date
            try:
                outbound_date_obj = datetime.strptime(params.outbound_date, "%Y-%m-%d").date()
                if outbound_date_obj < date.today():
                    logger.error(f"出发日期不能是过去的日期: {params.outbound_date}")
                    return {"error": "出发日期不能是过去的日期，请选择未来的日期"}
                
                if params.return_date:
                    return_date_obj = datetime.strptime(params.return_date, "%Y-%m-%d").date()
                    if return_date_obj < date.today():
                        logger.error(f"返程日期不能是过去的日期: {params.return_date}")
                        return {"error": "返程日期不能是过去的日期，请选择未来的日期"}
                    if return_date_obj <= outbound_date_obj:
                        logger.error(f"返程日期必须晚于出发日期")
                        return {"error": "返程日期必须晚于出发日期"}
            except ValueError as e:
                logger.error(f"日期格式错误: {e}")
                return {"error": "日期格式错误，请使用 YYYY-MM-DD 格式"}
            
            search_params = {
                "engine": "google_flights",
                "api_key": self.api_key,
                "departure_id": params.departure_id,
                "arrival_id": params.arrival_id,
                "outbound_date": params.outbound_date,
                "type": str(params.trip_type.value),
                "adults": str(params.adults),
                "travel_class": str(params.travel_class.value),
                "hl": "en",  # 统一使用英文，避免中文导致400错误
                "currency": "CNY" if language == "zh" else "USD"
            }
            
            # 添加可选参数
            if params.return_date:
                search_params["return_date"] = params.return_date
            if params.children > 0:
                search_params["children"] = str(params.children)
            if params.infants_in_seat > 0:
                search_params["infants_in_seat"] = str(params.infants_in_seat)
            if params.infants_on_lap > 0:
                search_params["infants_on_lap"] = str(params.infants_on_lap)
            if params.max_price:
                search_params["max_price"] = str(params.max_price)
            if params.stops is not None:
                search_params["stops"] = str(params.stops)
            if params.exclude_airlines:
                search_params["exclude_airlines"] = ",".join(params.exclude_airlines)
            if params.include_airlines:
                search_params["include_airlines"] = ",".join(params.include_airlines)
            if params.outbound_times:
                search_params["outbound_times"] = params.outbound_times
            if params.return_times:
                search_params["return_times"] = params.return_times
            if params.bags:
                search_params["bags"] = str(params.bags)
            if params.sort_by != SortOption.BEST:
                # 根据文档，sort_by 应该是数字
                sort_mapping = {
                    SortOption.BEST: "1",
                    SortOption.PRICE: "2", 
                    SortOption.DURATION: "3",
                    SortOption.DEPARTURE_TIME: "4",
                    SortOption.ARRIVAL_TIME: "5"
                }
                search_params["sort_by"] = sort_mapping.get(params.sort_by, "1")
            
            logger.info(f"发送SerpAPI请求: {search_params}")
            
            response = await client.get(SERPAPI_BASE_URL, params=search_params)
            
            logger.info(f"SerpAPI响应状态: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                if "error" in data:
                    logger.error(f"SerpAPI错误: {data['error']}")
                    return {"error": f"SerpAPI错误: {data['error']}"}
                return data
            else:
                error_text = response.text if hasattr(response, 'text') else 'Unknown error'
                logger.error(f"SerpAPI请求失败: {response.status_code}, 响应: {error_text}")
                
                if response.status_code == 400:
                    return {"error": "请求参数错误，请检查机场代码和日期格式"}
                elif response.status_code == 401:
                    return {"error": "API密钥无效，请联系管理员"}
                elif response.status_code == 429:
                    return {"error": "API请求过于频繁，请稍后再试"}
                else:
                    return {"error": f"SerpAPI服务暂时不可用 (状态码: {response.status_code})"}
                
        except Exception as e:
            logger.error(f"航班搜索失败: {e}")
            return {"error": f"搜索失败: {str(e)}"}
    
    async def get_price_insights(self, departure_id: str, arrival_id: str, client) -> Optional[Dict]:
        """获取价格洞察"""
        try:
            search_params = {
                "engine": "google_flights",
                "api_key": self.api_key,
                "departure_id": departure_id,
                "arrival_id": arrival_id,
                "type": "2"  # 单程查询价格洞察
            }
            
            response = await client.get(SERPAPI_BASE_URL, params=search_params)
            
            if response.status_code == 200:
                data = response.json()
                return data.get("price_insights", {})
            
            return None
            
        except Exception as e:
            logger.error(f"价格洞察获取失败: {e}")
            return None
    
    async def get_booking_options(self, booking_token: str, client) -> Optional[Dict]:
        """获取预订选项"""
        try:
            search_params = {
                "engine": "google_flights_booking_options",
                "api_key": self.api_key,
                "booking_token": booking_token
            }
            
            response = await client.get(SERPAPI_BASE_URL, params=search_params)
            
            if response.status_code == 200:
                data = response.json()
                return data
            
            return None
            
        except Exception as e:
            logger.error(f"预订选项获取失败: {e}")
            return None
    
    async def get_airports_results(self, departure_id: str, arrival_id: str, outbound_date: str, client, language: str = "en") -> Optional[AirportsResponse]:
        """获取机场API结果"""
        try:
            search_params = {
                "engine": "google_flights",
                "api_key": self.api_key,
                "departure_id": departure_id,
                "arrival_id": arrival_id,
                "outbound_date": outbound_date,
                "type": "2",  # 单程
                "hl": "en",  # 统一使用英文
                "currency": "CNY" if language == "zh" else "USD"
            }
            
            logger.info(f"发送机场API请求: {search_params}")
            
            response = await client.get(SERPAPI_BASE_URL, params=search_params)
            
            logger.info(f"机场API响应状态: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                if "error" in data:
                    logger.error(f"机场API错误: {data['error']}")
                    return None
                
                # 解析机场数据
                airports_response = self._parse_airports_response(data)
                return airports_response
            else:
                error_text = response.text if hasattr(response, 'text') else 'Unknown error'
                logger.error(f"机场API请求失败: {response.status_code}, 响应: {error_text}")
                return None
                
        except Exception as e:
            logger.error(f"机场API请求失败: {e}")
            return None
    
    def _parse_airports_response(self, data: Dict) -> Optional[AirportsResponse]:
        """解析机场API响应"""
        try:
            departure_airports = []
            arrival_airports = []
            
            # 根据实际API响应结构解析机场数据
            if "airports" in data and data["airports"]:
                airports_data = data["airports"][0]  # 取第一个元素
                
                # 解析出发机场
                if "departure" in airports_data:
                    for airport_info in airports_data["departure"]:
                        airport = AirportResult(
                            id=airport_info.get("airport", {}).get("id", ""),
                            name=airport_info.get("airport", {}).get("name", ""),
                            city=airport_info.get("city", ""),
                            country=airport_info.get("country", ""),
                            country_code=airport_info.get("country_code", ""),
                            image=airport_info.get("image", "")
                        )
                        departure_airports.append(airport)
                
                # 解析到达机场
                if "arrival" in airports_data:
                    for airport_info in airports_data["arrival"]:
                        airport = AirportResult(
                            id=airport_info.get("airport", {}).get("id", ""),
                            name=airport_info.get("airport", {}).get("name", ""),
                            city=airport_info.get("city", ""),
                            country=airport_info.get("country", ""),
                            country_code=airport_info.get("country_code", ""),
                            image=airport_info.get("image", "")
                        )
                        arrival_airports.append(airport)
            
            return AirportsResponse(
                departure_airports=departure_airports,
                arrival_airports=arrival_airports
            )
            
        except Exception as e:
            logger.error(f"解析机场响应失败: {e}")
            return None
    
    async def search_multi_city(self, segments: List[Dict], client, language: str = "en") -> Optional[Dict]:
        """多城市航班搜索"""
        try:
            search_params = {
                "engine": "google_flights",
                "api_key": self.api_key,
                "type": "3",  # 多城市
                "hl": "en",  # 统一使用英文
                "currency": "CNY" if language == "zh" else "USD"
            }
            
            # 添加多城市段信息
            for i, segment in enumerate(segments):
                search_params[f"departure_id_{i+1}"] = segment["departure_id"]
                search_params[f"arrival_id_{i+1}"] = segment["arrival_id"]
                search_params[f"outbound_date_{i+1}"] = segment["date"]
            
            response = await client.get(SERPAPI_BASE_URL, params=search_params)
            
            if response.status_code == 200:
                data = response.json()
                if "error" in data:
                    logger.error(f"SerpAPI错误: {data['error']}")
                    return None
                return data
            
            return None
            
        except Exception as e:
            logger.error(f"多城市搜索失败: {e}")
            return None

class AdvancedFlightCacheService:
    """高级航班缓存服务类"""
    
    async def search_flights_with_cache(self, params: FlightSearchParams, language: str) -> Optional[Dict]:
        """带缓存的航班搜索"""
        import hashlib
        cache_key = f"flight_search_{language}_{hashlib.md5(f'{params.departure_id}_{params.arrival_id}_{params.outbound_date}_{params.return_date}_{params.adults}_{params.travel_class.value}'.encode()).hexdigest()}"
        
        if cache_manager:
            config = get_config()
            cached_data = await cache_manager.load_cache(
                cache_key,
                max_age_seconds=config.flight_cache_duration,
                subdirectory="flights"
            )
            if cached_data:
                logger.info(f"使用缓存的航班搜索数据")
                return cached_data
        
        try:
            config = get_config()
            flight_service = AdvancedFlightService(config.serpapi_key)
            
            flight_data = await flight_service.search_flights(params, httpx_client, language)
            
            if flight_data and cache_manager and "error" not in flight_data:
                await cache_manager.save_cache(cache_key, flight_data, subdirectory="flights")
                logger.info(f"已缓存航班搜索数据")
            
            return flight_data
            
        except Exception as e:
            logger.error(f"航班搜索失败: {e}")
            return None
    
    async def search_airports_with_cache(self, query: str, language: str) -> List[Airport]:
        """带缓存的机场搜索"""
        cache_key = f"airport_search_{language}_{query.lower()}"
        
        if cache_manager:
            config = get_config()
            cached_data = await cache_manager.load_cache(
                cache_key,
                max_age_seconds=config.flight_cache_duration,
                subdirectory="airports"
            )
            if cached_data:
                logger.info(f"使用缓存的机场搜索数据: {query}")
                return cached_data
        
        try:
            config = get_config()
            flight_service = AdvancedFlightService(config.serpapi_key)
            
            airports = await flight_service.search_airports(query, httpx_client, language)
            
            if airports and cache_manager:
                await cache_manager.save_cache(cache_key, airports, subdirectory="airports")
                logger.info(f"已缓存机场搜索数据: {query}")
            
            return airports
            
        except Exception as e:
            logger.error(f"机场搜索失败: {e}")
            return []
    
    async def get_price_insights_with_cache(self, departure_id: str, arrival_id: str, language: str) -> Optional[Dict]:
        """带缓存的价格洞察"""
        cache_key = f"price_insights_{language}_{departure_id}_{arrival_id}"
        
        if cache_manager:
            config = get_config()
            cached_data = await cache_manager.load_cache(
                cache_key,
                max_age_seconds=3600,  # 价格数据1小时更新
                subdirectory="price_insights"
            )
            if cached_data:
                logger.info(f"使用缓存的价格洞察数据")
                return cached_data
        
        try:
            config = get_config()
            flight_service = AdvancedFlightService(config.serpapi_key)
            
            insights = await flight_service.get_price_insights(departure_id, arrival_id, httpx_client)
            
            if insights and cache_manager:
                await cache_manager.save_cache(cache_key, insights, subdirectory="price_insights")
                logger.info(f"已缓存价格洞察数据")
            
            return insights
            
        except Exception as e:
            logger.error(f"价格洞察获取失败: {e}")
            return None

    async def get_airports_results_with_cache(self, departure_id: str, arrival_id: str, outbound_date: str, language: str) -> Optional[AirportsResponse]:
        """带缓存的机场API结果"""
        cache_key = f"airports_results_{language}_{departure_id}_{arrival_id}_{outbound_date}"
        
        if cache_manager:
            config = get_config()
            cached_data = await cache_manager.load_cache(
                cache_key,
                max_age_seconds=config.flight_cache_duration,
                subdirectory="flights"
            )
            if cached_data and isinstance(cached_data, dict):
                logger.info(f"使用缓存的机场API数据")
                # 重构为AirportsResponse对象
                departure_airports = [AirportResult(**airport) for airport in cached_data.get("departure_airports", [])]
                arrival_airports = [AirportResult(**airport) for airport in cached_data.get("arrival_airports", [])]
                return AirportsResponse(departure_airports=departure_airports, arrival_airports=arrival_airports)
        
        try:
            config = get_config()
            flight_service = AdvancedFlightService(config.serpapi_key)
            
            airports_data = await flight_service.get_airports_results(departure_id, arrival_id, outbound_date, httpx_client, language)
            
            if airports_data and cache_manager:
                # 转换为可序列化的字典格式
                cache_data = {
                    "departure_airports": [
                        {
                            "id": airport.id,
                            "name": airport.name,
                            "city": airport.city,
                            "country": airport.country,
                            "country_code": airport.country_code,
                            "image": airport.image
                        } for airport in airports_data.departure_airports
                    ],
                    "arrival_airports": [
                        {
                            "id": airport.id,
                            "name": airport.name,
                            "city": airport.city,
                            "country": airport.country,
                            "country_code": airport.country_code,
                            "image": airport.image
                        } for airport in airports_data.arrival_airports
                    ]
                }
                await cache_manager.save_cache(cache_key, cache_data, subdirectory="flights")
                logger.info(f"已缓存机场API数据")
            
            return airports_data
            
        except Exception as e:
            logger.error(f"机场API请求失败: {e}")
            return None

# 创建全局高级航班缓存服务实例
advanced_flight_cache_service = AdvancedFlightCacheService()

def format_airports_results(airports_response: AirportsResponse, departure_query: str, arrival_query: str) -> str:
    """格式化机场API结果"""
    if not airports_response:
        return "❌ 未找到机场信息"
    
    result = f"✈️ **机场搜索结果**\\n\\n"
    result += f"🔍 搜索: {departure_query} → {arrival_query}\\n\\n"
    
    # 出发机场
    if airports_response.departure_airports:
        result += "🛫 **出发机场:**\\n"
        for i, airport in enumerate(airports_response.departure_airports[:5], 1):
            result += f"`{i}.` **{airport.name}** ({airport.id})\\n"
            result += f"     📍 {airport.city}, {airport.country}\\n"
            if airport.country_code:
                result += f"     🌍 {airport.country_code}\\n"
            result += "\\n"
    
    # 到达机场
    if airports_response.arrival_airports:
        result += "🛬 **到达机场:**\\n"
        for i, airport in enumerate(airports_response.arrival_airports[:5], 1):
            result += f"`{i}.` **{airport.name}** ({airport.id})\\n"
            result += f"     📍 {airport.city}, {airport.country}\\n"
            if airport.country_code:
                result += f"     🌍 {airport.country_code}\\n"
            result += "\\n"
    
    result += f"_更新时间: {datetime.now().strftime('%H:%M:%S')}_"
    
    return result

def format_travel_class(travel_class: TravelClass) -> str:
    """格式化舱位类型"""
    mapping = {
        TravelClass.ECONOMY: "经济舱",
        TravelClass.PREMIUM_ECONOMY: "高端经济舱",
        TravelClass.BUSINESS: "商务舱",
        TravelClass.FIRST: "头等舱"
    }
    return mapping.get(travel_class, "经济舱")

def format_duration(minutes: int) -> str:
    """格式化飞行时间"""
    if minutes < 60:
        return f"{minutes}分钟"
    
    hours = minutes // 60
    mins = minutes % 60
    
    if mins == 0:
        return f"{hours}小时"
    else:
        return f"{hours}小时{mins}分钟"

def format_layovers(layovers: List[Dict]) -> str:
    """格式化转机信息"""
    if not layovers:
        return "🚁 直飞"
    
    layover_info = []
    for layover in layovers:
        airport = layover.get('id', '')
        duration = layover.get('duration', 0)
        layover_info.append(f"{airport}({format_duration(duration)})") 
    
    return f"🔄 {len(layovers)}次转机: {', '.join(layover_info)}"

def format_carbon_emissions(emissions: Dict) -> str:
    """格式化碳排放信息"""
    if not emissions:
        return ""
    
    this_flight = emissions.get('this_flight', 0)
    typical_for_route = emissions.get('typical_for_this_route', 0)
    difference = emissions.get('difference_percent', 0)
    
    result = f"🌿 碳排放: {this_flight}kg CO2"
    
    if typical_for_route > 0:
        if difference > 0:
            result += f" (比平均高{difference}%)"
        elif difference < 0:
            result += f" (比平均低{abs(difference)}%)"
    
    return result

def format_price_with_insights(price: int, currency: str, insights: Optional[Dict] = None) -> str:
    """格式化价格和洞察"""
    symbol = "$" if currency == "USD" else "¥"
    price_text = f"💰 {symbol}{price:,}"
    
    if insights:
        price_level = insights.get('price_level', '')
        if price_level == 'low':
            price_text += " 🟢 低价"
        elif price_level == 'typical':
            price_text += " 🟡 正常"
        elif price_level == 'high':
            price_text += " 🔴 高价"
        
        lowest_price = insights.get('lowest_price')
        if lowest_price and lowest_price < price:
            price_text += f" (最低{symbol}{lowest_price:,})"
    
    return price_text

def format_flight_segment(segment: Dict, is_detailed: bool = False) -> str:
    """格式化单个航班段"""
    airline = segment.get('airline', '未知航空')
    flight_number = segment.get('flight_number', '')
    aircraft = segment.get('airplane', '')
    
    dep_airport = segment.get('departure_airport', {})
    arr_airport = segment.get('arrival_airport', {})
    
    dep_code = dep_airport.get('id', '')
    dep_name = dep_airport.get('name', '')
    dep_time = dep_airport.get('time', '')
    
    arr_code = arr_airport.get('id', '')
    arr_name = arr_airport.get('name', '')
    arr_time = arr_airport.get('time', '')
    
    duration = segment.get('duration', 0)
    legroom = segment.get('legroom', '')
    
    result = f"✈️ **{airline} {flight_number}**"
    if aircraft:
        result += f" ({aircraft})"
    result += "\n"
    
    if is_detailed:
        result += f"🛫 {dep_name} ({dep_code}) - {dep_time}\n"
        result += f"🛬 {arr_name} ({arr_code}) - {arr_time}\n"
    else:
        result += f"🛫 {dep_code} {dep_time} → 🛬 {arr_code} {arr_time}\n"
    
    result += f"⏱️ 飞行时间: {format_duration(duration)}"
    
    if legroom:
        result += f" | 🚀 腿部空间: {legroom}"
    
    return result

def format_complete_flight(flight_data: Dict, include_booking: bool = True) -> str:
    """格式化完整航班信息"""
    # SerpAPI 返回的航班数据结构：flight_data 本身就包含航班信息
    # flights 字段包含具体的航段信息
    flights = flight_data.get('flights', [])
    if not flights:
        return "无航班信息"
    
    # 基本信息
    price = flight_data.get('price', 0)
    currency = flight_data.get('currency', 'USD')
    total_duration = flight_data.get('total_duration', 0)
    layovers = flight_data.get('layovers', [])
    carbon_emissions = flight_data.get('carbon_emissions', {})
    
    result = ""
    
    # 航班段信息 - 每个flight都是一个航段字典
    for i, flight_segment in enumerate(flights):
        if i > 0:
            result += "\n┌" + "─" * 20 + "┐\n"
        result += format_flight_segment(flight_segment, True) + "\n"
    
    result += "\n" + "─" * 25 + "\n"
    
    # 总结信息
    result += f"📅 总时间: {format_duration(total_duration)}\n"
    result += format_layovers(layovers) + "\n"
    result += format_price_with_insights(price, currency) + "\n"
    
    emissions_text = format_carbon_emissions(carbon_emissions)
    if emissions_text:
        result += emissions_text + "\n"
    
    # 预订信息
    if include_booking and 'booking_options' in flight_data:
        booking_options = flight_data['booking_options']
        if booking_options:
            result += "\n🛒 **预订选项:**\n"
            for i, option in enumerate(booking_options[:3], 1):
                book_with = option.get('book_with', '未知')
                booking_price = option.get('price', price)
                result += f"{i}. {book_with} - {format_price_with_insights(booking_price, currency)}\n"
    
    return result

def format_flight_results_advanced(flights_data: Dict, search_params: FlightSearchParams) -> str:
    """高级格式化航班搜索结果"""
    if not flights_data:
        return "❌ 未找到航班信息"
    
    best_flights = flights_data.get("best_flights", [])
    other_flights = flights_data.get("other_flights", [])
    price_insights = flights_data.get("price_insights", {})
    
    if not best_flights and not other_flights:
        return "❌ 未找到相关航班"
    
    # 搜索参数信息
    trip_type = "往返" if search_params.trip_type == TripType.ROUND_TRIP else "单程"
    result = f"✈️ **{trip_type}航班搜索结果**\n\n"
    result += f"🛤️ {search_params.departure_id} → {search_params.arrival_id}\n"
    result += f"📅 {search_params.outbound_date}"
    if search_params.return_date:
        result += f" - {search_params.return_date}"
    result += f" | 👥 {search_params.adults}人 | {format_travel_class(search_params.travel_class)}\n\n"
    
    # 最佳航班 - 直接格式化航班信息，不使用format_complete_flight
    if best_flights:
        result += "🌟 **推荐航班:**\n\n"
        for i, flight in enumerate(best_flights[:2], 1):
            if isinstance(flight, dict):
                # 直接提取和显示关键信息
                price = flight.get('price', 0)
                currency = flight.get('currency', 'USD')
                total_duration = flight.get('total_duration', 0)
                
                result += f"`{i}.` "
                result += f"💰 ${price:,} | ⏱️ {format_duration(total_duration)}\n"
                
                # 显示航班段信息
                flights_segments = flight.get('flights', [])
                for j, segment in enumerate(flights_segments):
                    if isinstance(segment, dict):
                        airline = segment.get('airline', '未知航空')
                        flight_number = segment.get('flight_number', '')
                        dep_airport = segment.get('departure_airport', {})
                        arr_airport = segment.get('arrival_airport', {})
                        
                        dep_code = dep_airport.get('id', '') if isinstance(dep_airport, dict) else ''
                        dep_time = dep_airport.get('time', '') if isinstance(dep_airport, dict) else ''
                        arr_code = arr_airport.get('id', '') if isinstance(arr_airport, dict) else ''
                        arr_time = arr_airport.get('time', '') if isinstance(arr_airport, dict) else ''
                        
                        result += f"   ✈️ {airline} {flight_number} | {dep_code} {dep_time} → {arr_code} {arr_time}\n"
                
                result += "\n"
            else:
                result += f"`{i}.` 航班数据格式错误\n"
    
    # 其他选项 - 同样直接格式化
    if other_flights and len(best_flights) < 3:
        result += "🔍 **其他选项:**\n\n"
        remaining_slots = 3 - len(best_flights)
        for i, flight in enumerate(other_flights[:remaining_slots], len(best_flights) + 1):
            if isinstance(flight, dict):
                price = flight.get('price', 0)
                currency = flight.get('currency', 'USD')
                total_duration = flight.get('total_duration', 0)
                
                result += f"`{i}.` "
                result += f"💰 ${price:,} | ⏱️ {format_duration(total_duration)}\n"
                
                # 显示航班段信息  
                flights_segments = flight.get('flights', [])
                for j, segment in enumerate(flights_segments):
                    if isinstance(segment, dict):
                        airline = segment.get('airline', '未知航空')
                        flight_number = segment.get('flight_number', '')
                        dep_airport = segment.get('departure_airport', {})
                        arr_airport = segment.get('arrival_airport', {})
                        
                        dep_code = dep_airport.get('id', '') if isinstance(dep_airport, dict) else ''
                        dep_time = dep_airport.get('time', '') if isinstance(dep_airport, dict) else ''
                        arr_code = arr_airport.get('id', '') if isinstance(arr_airport, dict) else ''
                        arr_time = arr_airport.get('time', '') if isinstance(arr_airport, dict) else ''
                        
                        result += f"   ✈️ {airline} {flight_number} | {dep_code} {dep_time} → {arr_code} {arr_time}\n"
                
                result += "\n"
            else:
                result += f"`{i}.` 航班数据格式错误\n"
    
    # 价格洞察
    if price_insights:
        result += "\n📊 **价格分析:**\n"
        if "lowest_price" in price_insights:
            currency = "USD"  # 默认
            result += f"💵 最低价格: {format_price_with_insights(price_insights['lowest_price'], currency)}\n"
        if "price_level" in price_insights:
            result += f"📈 价格水平: {price_insights['price_level']}\n"
        if "typical_price_range" in price_insights:
            range_data = price_insights['typical_price_range']
            low = range_data.get('low', 0)
            high = range_data.get('high', 0)
            result += f"📉 常见价格区间: ${low:,} - ${high:,}\n"
    
    result += f"\n_更新时间: {datetime.now().strftime('%H:%M:%S')}_"
    
    return result

def format_airport_suggestions(airports: List[Airport], query: str) -> str:
    """格式化机场建议"""
    if not airports:
        return f"❌ 未找到匹配 '{query}' 的机场"
    
    result = f"🎯 **机场搜索结果: '{query}'**\n\n"
    
    for i, airport in enumerate(airports[:8], 1):
        result += f"`{airport.code}` **{airport.name}**\n"
        result += f"    🏠 {airport.city}, {airport.country}"
        if airport.timezone:
            result += f" ({airport.timezone})"
        result += "\n\n"
    
    if len(airports) > 8:
        result += f"_...还有 {len(airports) - 8} 个结果_\n"
    
    return result

def format_price_tracking_summary(route: str, tracked_prices: List[Dict]) -> str:
    """格式化价格追踪总结"""
    if not tracked_prices:
        return f"📊 **{route} 价格追踪**\n\n暂无价格数据"
    
    result = f"📊 **{route} 价格追踪**\n\n"
    
    # 最新价格
    latest = tracked_prices[-1]
    result += f"🔄 最新价格: ${latest['price']:,} ({latest['date']})\n"
    
    # 价格变化趋势
    if len(tracked_prices) > 1:
        previous = tracked_prices[-2]
        price_change = latest['price'] - previous['price']
        if price_change > 0:
            result += f"📈 较上次上涨: ${price_change:,}\n"
        elif price_change < 0:
            result += f"📉 较上次下降: ${abs(price_change):,}\n"
        else:
            result += f"➡️ 价格未变\n"
    
    # 统计信息
    prices = [p['price'] for p in tracked_prices]
    min_price = min(prices)
    max_price = max(prices)
    avg_price = sum(prices) // len(prices)
    
    result += f"\n📉 最低价: ${min_price:,}\n"
    result += f"📈 最高价: ${max_price:,}\n"
    result += f"📄 平均价: ${avg_price:,}\n"
    
    return result

async def advanced_flight_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """高级航班搜索主命令 /flight"""
    if not update.message:
        return
        
    # 检查是否配置了SerpAPI密钥
    config = get_config()
    if not hasattr(config, 'serpapi_key') or not config.serpapi_key:
        await send_error(
            context, 
            update.message.chat_id,
            "❌ 航班搜索服务未配置API密钥，请联系管理员"
        )
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        return
    
    # 如果有参数，尝试快速搜索
    if context.args and len(context.args) >= 3:
        # 快速搜索格式: /flight PEK LAX 2025-09-25 [2025-10-05] [2] [business]
        departure = context.args[0].upper()
        arrival = context.args[1].upper()
        outbound_date = context.args[2]
        return_date = context.args[3] if len(context.args) > 3 and context.args[3] != "-" else None
        adults = int(context.args[4]) if len(context.args) > 4 and context.args[4].isdigit() else 1
        travel_class_str = context.args[5] if len(context.args) > 5 else "economy"
        
        # 验证日期格式
        try:
            from datetime import datetime, date
            outbound_date_obj = datetime.strptime(outbound_date, "%Y-%m-%d").date()
            if outbound_date_obj < date.today():
                await send_error(
                    context, 
                    update.message.chat_id,
                    "❌ 出发日期不能是过去的日期，请选择未来的日期\n💡 例如: /flight PEK LAX 2025-12-25"
                )
                await delete_user_command(context, update.message.chat_id, update.message.message_id)
                return
                
            if return_date:
                return_date_obj = datetime.strptime(return_date, "%Y-%m-%d").date()
                if return_date_obj < date.today():
                    await send_error(
                        context, 
                        update.message.chat_id,
                        "❌ 返程日期不能是过去的日期，请选择未来的日期"
                    )
                    await delete_user_command(context, update.message.chat_id, update.message.message_id)
                    return
                if return_date_obj <= outbound_date_obj:
                    await send_error(
                        context, 
                        update.message.chat_id,
                        "❌ 返程日期必须晚于出发日期"
                    )
                    await delete_user_command(context, update.message.chat_id, update.message.message_id)
                    return
        except ValueError:
            await send_error(
                context, 
                update.message.chat_id,
                "❌ 日期格式错误，请使用 YYYY-MM-DD 格式\n💡 例如: /flight PEK LAX 2025-12-25"
            )
            await delete_user_command(context, update.message.chat_id, update.message.message_id)
            return
        
        # 转换舱位类型
        travel_class_map = {
            "economy": TravelClass.ECONOMY,
            "premium": TravelClass.PREMIUM_ECONOMY,
            "business": TravelClass.BUSINESS,
            "first": TravelClass.FIRST
        }
        travel_class = travel_class_map.get(travel_class_str.lower(), TravelClass.ECONOMY)
        
        # 创建搜索参数
        search_params = FlightSearchParams(
            departure_id=departure,
            arrival_id=arrival,
            outbound_date=outbound_date,
            return_date=return_date,
            trip_type=TripType.ROUND_TRIP if return_date else TripType.ONE_WAY,
            adults=adults,
            travel_class=travel_class
        )
        
        await _execute_advanced_flight_search(update, context, search_params)
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        return
    
    # 没有参数，显示高级主菜单
    keyboard = [
        [
            InlineKeyboardButton("✈️ 智能搜索", callback_data="flight_smart_search"),
            InlineKeyboardButton("🔍 机场查询", callback_data="flight_airport_search")
        ],
        [
            InlineKeyboardButton("✈️ 单程航班", callback_data="flight_oneway"),
            InlineKeyboardButton("🔄 往返航班", callback_data="flight_roundtrip")
        ],
        [
            InlineKeyboardButton("🌍 多城市", callback_data="flight_multicity"),
            InlineKeyboardButton("🏢 机场API", callback_data="flight_airports_results")
        ],
        [
            InlineKeyboardButton("📊 价格洞察", callback_data="flight_price_insights"),
            InlineKeyboardButton("📲 价格追踪", callback_data="flight_price_tracking")
        ],
        [
            InlineKeyboardButton("❌ 关闭", callback_data="flight_close")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    help_text = """✈️ **智能航班搜索服务**

🌍 **全面功能:**
• **智能搜索**: AI智能匹配最佳航班
• **机场查询**: 全球机场代码和信息
• **单程/往返**: 灵活的行程选择
• **多城市**: 复杂行程规划
• **机场API**: 详细机场信息和图片

📊 **价格智能:**
• **实时价格**: 多平台价格比较
• **价格洞察**: 历史价格趋势分析
• **价格追踪**: 自动监控和提醒
• **最佳时机**: 价格预测和建议

🌱 **环保特性:**
• **碳足迹**: 详细碳排放计算
• **环保选择**: 优先推荐低排放航班

🛒 **预订便利:**
• **多平台**: 比较各大预订网站
• **直接链接**: 一键跳转预订
• **实时库存**: 显示剩余座位

💡 **快速使用:**
`/flight PEK LAX 2025-12-25` - 北京到洛杉矶单程
`/flight PEK LAX 2025-12-25 2026-01-05` - 往返航班
`/flight PEK LAX 2025-12-25 - 2 business` - 2人商务舱

请选择功能:"""
    
    await send_message_with_auto_delete(
        context=context,
        chat_id=update.message.chat_id,
        text=foldable_text_with_markdown_v2(help_text),
        parse_mode="MarkdownV2",
        reply_markup=reply_markup
    )
    
    await delete_user_command(context, update.message.chat_id, update.message.message_id)

async def _execute_advanced_flight_search(update: Update, context: ContextTypes.DEFAULT_TYPE, params: FlightSearchParams, callback_query: CallbackQuery = None) -> None:
    """执行高级航班搜索"""
    # 检测用户语言
    user_locale = update.effective_user.language_code if update.effective_user else None
    language = detect_user_language("", user_locale)
    
    trip_type = "往返" if params.trip_type == TripType.ROUND_TRIP else "单程"
    if params.trip_type == TripType.MULTI_CITY:
        trip_type = "多城市"
        
    loading_message = f"✈️ 正在搜索{trip_type}航班: {params.departure_id} → {params.arrival_id}... ⏳"
    
    if callback_query:
        await callback_query.edit_message_text(
            text=foldable_text_v2(loading_message),
            parse_mode="MarkdownV2"
        )
        message = callback_query.message
    else:
        message = await context.bot.send_message(
            chat_id=update.message.chat_id,
            text=foldable_text_v2(loading_message),
            parse_mode="MarkdownV2"
        )
        # 调度自动删除
        config = get_config()
        await _schedule_auto_delete(context, message.chat_id, message.message_id, config.auto_delete_delay)
    
    try:
        # 使用高级缓存服务搜索航班
        flights_data = await advanced_flight_cache_service.search_flights_with_cache(params, language)
        
        if flights_data:
            # 检查是否有错误
            if "error" in flights_data:
                error_msg = f"❌ {flights_data['error']}"
                keyboard = [
                    [
                        InlineKeyboardButton("🔍 机场查询", callback_data="flight_airport_search"),
                        InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                if callback_query:
                    await callback_query.edit_message_text(
                        text=error_msg,
                        reply_markup=reply_markup
                    )
                    config = get_config()
                    await _schedule_auto_delete(context, callback_query.message.chat_id, callback_query.message.message_id, config.auto_delete_delay)
                else:
                    await message.edit_text(
                        text=error_msg,
                        reply_markup=reply_markup
                    )
                    config = get_config()
                    await _schedule_auto_delete(context, message.chat_id, message.message_id, config.auto_delete_delay)
                return
            
            # 找到航班信息
            result_text = format_flight_results_advanced(flights_data, params)
            
            # 获取价格洞察
            price_insights = await advanced_flight_cache_service.get_price_insights_with_cache(
                params.departure_id, params.arrival_id, language
            )
            
            # 创建复杂按钮菜单
            keyboard = [
                [
                    InlineKeyboardButton("📊 价格洞察", callback_data=f"flight_insights:{params.departure_id}:{params.arrival_id}"),
                    InlineKeyboardButton("🛒 预订选项", callback_data=f"flight_booking:{params.departure_id}:{params.arrival_id}")
                ],
                [
                    InlineKeyboardButton("⚙️ 调整过滤", callback_data=f"flight_filter:{params.departure_id}:{params.arrival_id}"),
                    InlineKeyboardButton("📲 追踪价格", callback_data=f"flight_track:{params.departure_id}:{params.arrival_id}")
                ],
                [
                    InlineKeyboardButton("🔄 重新搜索", callback_data="flight_smart_search"),
                    InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if callback_query:
                await callback_query.edit_message_text(
                    text=foldable_text_with_markdown_v2(result_text),
                    parse_mode="MarkdownV2",
                    reply_markup=reply_markup
                )
            else:
                await message.edit_text(
                    text=foldable_text_with_markdown_v2(result_text),
                    parse_mode="MarkdownV2",
                    reply_markup=reply_markup
                )
        else:
            # 未找到结果
            error_msg = f"❌ 未找到航班: {params.departure_id} → {params.arrival_id} ({params.outbound_date})"
            if params.return_date:
                error_msg += f" - {params.return_date}"
            
            keyboard = [
                [
                    InlineKeyboardButton("🔍 机场查询", callback_data="flight_airport_search"),
                    InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if callback_query:
                await callback_query.edit_message_text(
                    text=error_msg,
                    reply_markup=reply_markup
                )
                config = get_config()
                await _schedule_auto_delete(context, callback_query.message.chat_id, callback_query.message.message_id, config.auto_delete_delay)
            else:
                await message.edit_text(
                    text=error_msg,
                    reply_markup=reply_markup
                )
                config = get_config()
                await _schedule_auto_delete(context, message.chat_id, message.message_id, config.auto_delete_delay)
                
    except Exception as e:
        logger.error(f"航班搜索失败: {e}")
        error_msg = f"❌ 搜索失败: {str(e)}"
        keyboard = [
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        config = get_config()
        if callback_query:
            await callback_query.edit_message_text(
                text=error_msg,
                reply_markup=reply_markup
            )
            await _schedule_auto_delete(context, callback_query.message.chat_id, callback_query.message.message_id, config.auto_delete_delay)
        else:
            await message.edit_text(
                text=error_msg,
                reply_markup=reply_markup
            )
            await _schedule_auto_delete(context, message.chat_id, message.message_id, config.auto_delete_delay)

async def _execute_airport_search(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str, callback_query: CallbackQuery = None) -> None:
    """执行朼场搜索"""
    user_locale = update.effective_user.language_code if update.effective_user else None
    language = detect_user_language(query, user_locale)
    
    loading_message = f"🔍 正在搜索朼场: {query}... ⏳"
    
    if callback_query:
        await callback_query.edit_message_text(
            text=foldable_text_v2(loading_message),
            parse_mode="MarkdownV2"
        )
        message = callback_query.message
    else:
        message = await context.bot.send_message(
            chat_id=update.message.chat_id,
            text=foldable_text_v2(loading_message),
            parse_mode="MarkdownV2"
        )
        config = get_config()
        await _schedule_auto_delete(context, message.chat_id, message.message_id, config.auto_delete_delay)
    
    try:
        # 使用高级缓存服务搜索朼场
        airports = await advanced_flight_cache_service.search_airports_with_cache(query, language)
        
        if airports:
            result_text = format_airport_suggestions(airports, query)
            
            # 创建机场选择按钮
            keyboard = []
            for airport in airports[:6]:  # 显示前6个结果
                keyboard.append([
                    InlineKeyboardButton(
                        f"{airport.code} - {airport.city}",
                        callback_data=f"flight_select_airport:{airport.code}:{airport.name}"
                    )
                ])
            
            keyboard.append([InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if callback_query:
                await callback_query.edit_message_text(
                    text=foldable_text_with_markdown_v2(result_text),
                    parse_mode="MarkdownV2",
                    reply_markup=reply_markup
                )
            else:
                await message.edit_text(
                    text=foldable_text_with_markdown_v2(result_text),
                    parse_mode="MarkdownV2",
                    reply_markup=reply_markup
                )
        else:
            error_msg = f"❌ 未找到匹配 '{query}' 的机场"
            keyboard = [[
                InlineKeyboardButton("🔍 重新搜索", callback_data="flight_airport_search"),
                InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")
            ]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if callback_query:
                await callback_query.edit_message_text(text=error_msg, reply_markup=reply_markup)
            else:
                await message.edit_text(text=error_msg, reply_markup=reply_markup)
                
    except Exception as e:
        logger.error(f"机场搜索失败: {e}")
        error_msg = f"❌ 搜索失败: {str(e)}"
        keyboard = [[InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if callback_query:
            await callback_query.edit_message_text(text=error_msg, reply_markup=reply_markup)
        else:
            await message.edit_text(text=error_msg, reply_markup=reply_markup)

async def advanced_flight_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理高级航班功能的文本输入"""
    if not update.message or not update.message.text:
        return
    
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # 获取用户会话
    session_data = flight_session_manager.get_session(user_id)
    if not session_data:
        return  # 没有活动会话，忽略
    
    action = session_data.get("action")
    waiting_for = session_data.get("waiting_for")
    
    try:
        # 删除用户输入的命令
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        
        if action == "smart_search" and waiting_for == "query":
            # 处理智能搜索
            await _parse_smart_search(update, context, text)
            flight_session_manager.remove_session(user_id)
            
        elif action == "airport_search" and waiting_for == "query":
            # 处理朼场搜索
            await _execute_airport_search(update, context, text)
            flight_session_manager.remove_session(user_id)
            
        elif action == "oneway_search" and waiting_for == "route":
            # 处理单程航班搜索
            await _parse_and_execute_oneway_search(update, context, text)
            flight_session_manager.remove_session(user_id)
            
        elif action == "roundtrip_search" and waiting_for == "route":
            # 处理往返航班搜索
            await _parse_and_execute_roundtrip_search(update, context, text)
            flight_session_manager.remove_session(user_id)
            
        elif action == "multicity_search" and waiting_for == "segments":
            # 处理多城市搜索
            await _parse_and_execute_multicity_search(update, context, text)
            flight_session_manager.remove_session(user_id)
            
        elif action == "airports_results" and waiting_for == "route_date":
            # 处理机场API结果查询
            await _parse_and_execute_airports_results(update, context, text)
            flight_session_manager.remove_session(user_id)
            
    except Exception as e:
        logger.error(f"处理航班文本输入失败: {e}")
        await send_error(context, update.message.chat_id, f"处理失败: {str(e)}")
        flight_session_manager.remove_session(user_id)

async def _parse_smart_search(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """解析智能搜索输入"""
    # 智能解析多种格式
    # 格式1: PEK LAX 2025-12-25
    # 格式2: 北京 洛杉矶 2025-12-25 2026-01-05
    # 格式3: PEK to LAX on 2025-12-25 return 2026-01-05 2 passengers business class
    
    parts = text.strip().split()
    if len(parts) < 3:
        await send_error(context, update.message.chat_id, "格式错误，请至少提供: 出发地 目的地 日期")
        return
    
    # 基本解析
    departure_input = parts[0]
    arrival_input = parts[1]
    outbound_date = parts[2]
    
    # 智能转换为机场代码
    departure = departure_input.upper()
    arrival = arrival_input.upper()
    
    # 如果不是3位代码，尝试从机场数据库搜索
    if len(departure_input) != 3:
        from utils.airport_data import search_airports
        dep_airports = search_airports(departure_input)
        if dep_airports:
            departure = dep_airports[0].code
            logger.info(f"智能转换: {departure_input} -> {departure}")
    
    if len(arrival_input) != 3:
        from utils.airport_data import search_airports
        arr_airports = search_airports(arrival_input)
        if arr_airports:
            arrival = arr_airports[0].code
            logger.info(f"智能转换: {arrival_input} -> {arrival}")
    
    # 高级解析
    return_date = None
    adults = 1
    travel_class = TravelClass.ECONOMY
    
    # 尝试解析额外参数
    for i, part in enumerate(parts[3:], 3):
        if part.isdigit() and int(part) <= 9:  # 可能是乘客数
            adults = int(part)
        elif part.lower() in ['business', 'first', 'premium', 'economy']:
            class_map = {
                'economy': TravelClass.ECONOMY,
                'premium': TravelClass.PREMIUM_ECONOMY,
                'business': TravelClass.BUSINESS,
                'first': TravelClass.FIRST
            }
            travel_class = class_map[part.lower()]
        elif '-' in part and len(part) == 10:  # 可能是日期
            return_date = part
    
    # 如果没有显式设置返程日期，检查第4个参数
    if not return_date and len(parts) > 3 and '-' in parts[3]:
        return_date = parts[3]
    
    # 创建搜索参数
    search_params = FlightSearchParams(
        departure_id=departure,
        arrival_id=arrival,
        outbound_date=outbound_date,
        return_date=return_date,
        trip_type=TripType.ROUND_TRIP if return_date else TripType.ONE_WAY,
        adults=adults,
        travel_class=travel_class
    )
    
    await _execute_advanced_flight_search(update, context, search_params)

async def _parse_and_execute_oneway_search(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """解析并执行单程搜索"""
    parts = text.strip().split()
    if len(parts) < 3:
        await send_error(context, update.message.chat_id, "格式错误，请使用: 出发机场 到达机场 日期\n例如: PEK LAX 2025-12-25")
        return
    
    departure, arrival, date = parts[0].upper(), parts[1].upper(), parts[2]
    
    search_params = FlightSearchParams(
        departure_id=departure,
        arrival_id=arrival,
        outbound_date=date,
        trip_type=TripType.ONE_WAY
    )
    
    await _execute_advanced_flight_search(update, context, search_params)

async def _parse_and_execute_roundtrip_search(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """解析并执行往返搜索"""
    parts = text.strip().split()
    if len(parts) < 4:
        await send_error(context, update.message.chat_id, "格式错误，请使用: 出发机场 到达机场 出发日期 返程日期\n例如: PEK LAX 2025-12-25 2026-01-05")
        return
    
    departure, arrival, outbound_date, return_date = parts[0].upper(), parts[1].upper(), parts[2], parts[3]
    
    search_params = FlightSearchParams(
        departure_id=departure,
        arrival_id=arrival,
        outbound_date=outbound_date,
        return_date=return_date,
        trip_type=TripType.ROUND_TRIP
    )
    
    await _execute_advanced_flight_search(update, context, search_params)

async def _parse_and_execute_multicity_search(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """解析并执行多城市搜索"""
    # 格式: PEK-LAX-2025-12-25,LAX-SFO-2025-12-28,SFO-PEK-2026-01-05
    try:
        segments = []
        for segment_str in text.split(','):
            parts = segment_str.strip().split('-')
            if len(parts) != 3:
                await send_error(context, update.message.chat_id, "多城市格式错误\n请使用: 出发-到达-日期,出发-到达-日期")
                return
            
            segments.append({
                "departure_id": parts[0].upper(),
                "arrival_id": parts[1].upper(),
                "date": parts[2]
            })
        
        if len(segments) < 2:
            await send_error(context, update.message.chat_id, "多城市行程至少需要2段")
            return
        
        # 使用SerpAPI多城市搜索
        user_locale = update.effective_user.language_code if update.effective_user else None
        language = detect_user_language("", user_locale)
        
        config = get_config()
        flight_service = AdvancedFlightService(config.serpapi_key)
        
        loading_message = f"✈️ 正在搜索多城市航班 ({len(segments)}段)... ⏳"
        message = await context.bot.send_message(
            chat_id=update.message.chat_id,
            text=foldable_text_v2(loading_message),
            parse_mode="MarkdownV2"
        )
        
        multicity_data = await flight_service.search_multi_city(segments, httpx_client, language)
        
        if multicity_data:
            # 格式化多城市结果
            result_text = "✈️ **多城市航班搜索结果**\n\n"
            
            for i, segment in enumerate(segments, 1):
                result_text += f"{i}. {segment['departure_id']} → {segment['arrival_id']} ({segment['date']})\n"
            
            result_text += "\n正在开发中，请先使用单程搜索功能。"
            
            keyboard = [[
                InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")
            ]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await message.edit_text(
                text=foldable_text_with_markdown_v2(result_text),
                parse_mode="MarkdownV2",
                reply_markup=reply_markup
            )
        else:
            await message.edit_text(
                "❌ 多城市搜索失败，请检查输入格式",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")
                ]])
            )
            
    except Exception as e:
        logger.error(f"多城市搜索失败: {e}")
        await send_error(context, update.message.chat_id, f"多城市搜索失败: {str(e)}")

async def _parse_and_execute_airports_results(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """解析并执行机场API结果查询"""
    parts = text.strip().split()
    if len(parts) < 3:
        await send_error(context, update.message.chat_id, "格式错误，请使用: 出发机场 到达机场 日期\n例如: PEK LAX 2025-12-25")
        return
    
    departure_input = parts[0]
    arrival_input = parts[1]
    outbound_date = parts[2]
    
    # 检测用户语言
    user_locale = update.effective_user.language_code if update.effective_user else None
    language = detect_user_language(text, user_locale)
    
    loading_message = f"🏢 正在查询机场API结果: {departure_input} → {arrival_input} ({outbound_date})... ⏳"
    
    message = await context.bot.send_message(
        chat_id=update.message.chat_id,
        text=foldable_text_v2(loading_message),
        parse_mode="MarkdownV2"
    )
    
    # 调度自动删除
    config = get_config()
    await _schedule_auto_delete(context, message.chat_id, message.message_id, config.auto_delete_delay)
    
    try:
        # 智能转换输入为机场代码
        departure_id = departure_input.upper()
        arrival_id = arrival_input.upper()
        
        # 如果不是3位代码，尝试从机场数据库搜索
        if len(departure_input) != 3:
            from utils.airport_data import search_airports
            dep_airports = search_airports(departure_input)
            if dep_airports:
                departure_id = dep_airports[0].code
        
        if len(arrival_input) != 3:
            from utils.airport_data import search_airports
            arr_airports = search_airports(arrival_input)
            if arr_airports:
                arrival_id = arr_airports[0].code
        
        # 验证日期格式和有效性
        from datetime import datetime, date
        try:
            outbound_date_obj = datetime.strptime(outbound_date, "%Y-%m-%d").date()
            if outbound_date_obj < date.today():
                await message.edit_text("❌ 日期不能是过去的日期，请选择未来的日期")
                await _schedule_auto_delete(context, message.chat_id, message.message_id, 10)
                return
        except ValueError:
            await message.edit_text("❌ 日期格式错误，请使用 YYYY-MM-DD 格式")
            await _schedule_auto_delete(context, message.chat_id, message.message_id, 10)
            return
        
        # 使用缓存服务获取机场API结果
        airports_results = await advanced_flight_cache_service.get_airports_results_with_cache(
            departure_id, arrival_id, outbound_date, language
        )
        
        if airports_results:
            # 格式化并显示结果
            result_text = format_airports_results(airports_results, departure_input, arrival_input)
            
            keyboard = [
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await message.edit_text(
                text=foldable_text_with_markdown_v2(result_text),
                parse_mode="MarkdownV2",
                reply_markup=reply_markup
            )
        else:
            error_msg = f"❌ 未找到机场API结果: {departure_input} → {arrival_input} ({outbound_date})"
            keyboard = [
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await message.edit_text(
                text=error_msg,
                reply_markup=reply_markup
            )
            await _schedule_auto_delete(context, message.chat_id, message.message_id, config.auto_delete_delay)
            
    except Exception as e:
        logger.error(f"机场API结果查询失败: {e}")
        error_msg = f"❌ 查询失败: {str(e)}"
        keyboard = [
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await message.edit_text(
            text=error_msg,
            reply_markup=reply_markup
        )
        await _schedule_auto_delete(context, message.chat_id, message.message_id, config.auto_delete_delay)

async def flight_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理航班功能的回调查询"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "flight_close":
        # 清理用户会话
        user_id = update.effective_user.id
        flight_session_manager.remove_session(user_id)
        await query.delete_message()
        return
    
    elif data == "flight_main_menu":
        # 清理用户会话并返回主菜单
        user_id = update.effective_user.id
        flight_session_manager.remove_session(user_id)
        
        # 返回主菜单
        keyboard = [
            [
                InlineKeyboardButton("✈️ 单程航班", callback_data="flight_oneway"),
                InlineKeyboardButton("🔄 往返航班", callback_data="flight_roundtrip")
            ],
            [
                InlineKeyboardButton("🌍 多城市", callback_data="flight_multicity"),
                InlineKeyboardButton("🏢 机场查询", callback_data="flight_airports")
            ],
            [
                InlineKeyboardButton("❌ 关闭", callback_data="flight_close")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        help_text = """✈️ 智能航班搜索服务

🌍 功能介绍:
• **单程航班**: 搜索单程航班
• **往返航班**: 搜索往返航班  
• **多城市**: 复杂行程规划
• **机场查询**: 查找机场代码

🤖 智能特性:
• 实时价格比较
• 航班时间优化
• 碳排放信息
• 价格趋势分析

💡 快速使用:
`/flight PEK LAX 2025-12-25` - 北京到洛杉矶单程
`/flight PEK LAX 2025-12-25 2026-01-05` - 往返航班

请选择功能:"""
        
        await query.edit_message_text(
            text=foldable_text_with_markdown_v2(help_text),
            parse_mode="MarkdownV2",
            reply_markup=reply_markup
        )
    
    elif data == "flight_oneway":
        user_id = update.effective_user.id
        
        # 设置会话状态
        flight_session_manager.set_session(user_id, {
            "action": "oneway_search",
            "waiting_for": "route"
        })
        
        await query.edit_message_text(
            text="✈️ 单程航班搜索\n\n请输入搜索信息:\n格式: 出发机场 到达机场 日期\n\n例如:\n• PEK LAX 2025-12-25\n• 北京 洛杉矶 2025-12-25",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
            ])
        )
    
    elif data == "flight_roundtrip":
        user_id = update.effective_user.id
        
        # 设置会话状态
        flight_session_manager.set_session(user_id, {
            "action": "roundtrip_search",
            "waiting_for": "route"
        })
        
        await query.edit_message_text(
            text="🔄 往返航班搜索\n\n请输入搜索信息:\n格式: 出发机场 到达机场 出发日期 返程日期\n\n例如:\n• PEK LAX 2025-12-25 2026-01-05\n• 北京 洛杉矶 2025-12-25 2026-01-05",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
            ])
        )
    
    elif data == "flight_multicity":
        await query.edit_message_text(
            text="🌍 多城市航班搜索\n\n此功能正在开发中，敬请期待！\n\n当前可以使用单程和往返搜索功能。",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
            ])
        )
    
    elif data == "flight_airports":
        await query.edit_message_text(
            text="🏢 机场查询\n\n常用机场代码:\n\n🇨🇳 **中国**\n• PEK - 北京首都国际机场\n• PVG - 上海浦东国际机场\n• CAN - 广州白云国际机场\n• SZX - 深圳宝安国际机场\n\n🇺🇸 **美国**\n• LAX - 洛杉矶国际机场\n• JFK - 纽约肯尼迪国际机场\n• SFO - 旧金山国际机场\n• ORD - 芝加哥奥黑尔国际机场\n\n🇬🇧 **英国**\n• LHR - 伦敦希思罗机场\n• LGW - 伦敦盖特威克机场\n\n🇯🇵 **日本**\n• NRT - 东京成田国际机场\n• HND - 东京羽田机场\n• KIX - 大阪关西国际机场",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
            ])
        )

async def advanced_flight_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理高级航班功能的回调查询"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "flight_close":
        user_id = update.effective_user.id
        flight_session_manager.remove_session(user_id)
        await query.delete_message()
        return
    
    elif data == "flight_main_menu":
        user_id = update.effective_user.id
        flight_session_manager.remove_session(user_id)
        
        keyboard = [
            [
                InlineKeyboardButton("✈️ 智能搜索", callback_data="flight_smart_search"),
                InlineKeyboardButton("🔍 机场查询", callback_data="flight_airport_search")
            ],
            [
                InlineKeyboardButton("✈️ 单程航班", callback_data="flight_oneway"),
                InlineKeyboardButton("🔄 往返航班", callback_data="flight_roundtrip")
            ],
            [
                InlineKeyboardButton("🌍 多城市", callback_data="flight_multicity"),
                InlineKeyboardButton("🏢 机场API", callback_data="flight_airports_results")
            ],
            [
                InlineKeyboardButton("📊 价格洞察", callback_data="flight_price_insights"),
                InlineKeyboardButton("📲 价格追踪", callback_data="flight_price_tracking")
            ],
            [
                InlineKeyboardButton("❌ 关闭", callback_data="flight_close")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        help_text = """✈️ **智能航班搜索服务**

🌍 **全面功能:**
• **智能搜索**: AI智能匹配最佳航班
• **机场查询**: 全球机场代码和信息
• **单程/往返**: 灵活的行程选择
• **多城市**: 复杂行程规划
• **机场API**: 详细机场信息和图片

📊 **价格智能:**
• **实时价格**: 多平台价格比较
• **价格洞察**: 历史价格趋势分析
• **价格追踪**: 自动监控和提醒
• **最佳时机**: 价格预测和建议

💡 **快速使用:**
`/flight PEK LAX 2025-12-25` - 北京到洛杉矶单程
`/flight PEK LAX 2025-12-25 2026-01-05` - 往返航班
`/flight PEK LAX 2025-12-25 - 2 business` - 2人商务舱

请选择功能:"""
        
        await query.edit_message_text(
            text=foldable_text_with_markdown_v2(help_text),
            parse_mode="MarkdownV2",
            reply_markup=reply_markup
        )
    
    elif data == "flight_smart_search":
        user_id = update.effective_user.id
        flight_session_manager.set_session(user_id, {
            "action": "smart_search",
            "waiting_for": "query"
        })
        
        await query.edit_message_text(
            text=foldable_text_with_markdown_v2("🤖 **智能航班搜索**\n\n请输入你的行程信息，我会智能解析：\n\n**支持格式:**\n• `PEK LAX 2025-12-25` - 单程\n• `PEK LAX 2025-12-25 2026-01-05` - 往返\n• `PEK LAX 2025-12-25 2 business` - 2人商务舱\n• `北京 洛杉矶 2025-12-25` - 中文城市\n\n**支持参数:**\n• 乘客数: 1-9\n• 舱位: economy, business, first, premium"),
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")
            ]])
        )
    
    elif data == "flight_airport_search":
        user_id = update.effective_user.id
        flight_session_manager.set_session(user_id, {
            "action": "airport_search",
            "waiting_for": "query"
        })
        
        await query.edit_message_text(
            text=foldable_text_with_markdown_v2("🔍 **机场查询**\n\n请输入机场代码、城市名或机场名称：\n\n**示例:**\n• `PEK` - 机场代码\n• `北京` - 城市名\n• `首都机场` - 机场名\n• `Beijing` - 英文名称"),
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")
            ]])
        )
    
    elif data == "flight_airports_results":
        user_id = update.effective_user.id
        flight_session_manager.set_session(user_id, {
            "action": "airports_results",
            "waiting_for": "route_date"
        })
        
        await query.edit_message_text(
            text="🏢 **机场API结果查询**\\n\\n请输入路线和日期信息：\\n格式: 出发机场 到达机场 日期\\n\\n例如:\\n• `PEK LAX 2025-12-25`\\n• `北京 洛杉矶 2025-12-25`\\n\\n将显示该路线的详细机场信息",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")
            ]])
        )
    
    elif data == "flight_oneway":
        user_id = update.effective_user.id
        flight_session_manager.set_session(user_id, {
            "action": "oneway_search",
            "waiting_for": "route"
        })
        
        await query.edit_message_text(
            text="✈️ 单程航班搜索\n\n请输入搜索信息：\n格式: 出发机场 到达机场 日期\n\n例如:\n• PEK LAX 2025-12-25\n• 北京 洛杉矶 2025-12-25",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")
            ]])
        )
    
    elif data == "flight_roundtrip":
        user_id = update.effective_user.id
        flight_session_manager.set_session(user_id, {
            "action": "roundtrip_search",
            "waiting_for": "route"
        })
        
        await query.edit_message_text(
            text="🔄 往返航班搜索\n\n请输入搜索信息：\n格式: 出发机场 到达机场 出发日期 返程日期\n\n例如:\n• PEK LAX 2025-12-25 2026-01-05\n• 北京 洛杉矶 2025-12-25 2026-01-05",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")
            ]])
        )
    
    elif data == "flight_multicity":
        user_id = update.effective_user.id
        flight_session_manager.set_session(user_id, {
            "action": "multicity_search",
            "waiting_for": "segments"
        })
        
        await query.edit_message_text(
            text="🌍 **多城市航班搜索**\\n\\n请输入多段行程：\\n格式: 出发-到达-日期,出发-到达-日期\\n\\n例如:\\n`PEK-LAX-2025-12-25,LAX-SFO-2025-12-28,SFO-PEK-2026-01-05`\\n\\n**注意:** 至少需要2段行程",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")
            ]])
        )
    
    # 其他功能暂时显示开发中
    else:
        await query.edit_message_text(
            text="🚧 此功能正在开发中，敬请期待！",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")
            ]])
        )

# =============================================================================
# 注册命令和回调
# =============================================================================

# 注册主命令
command_factory.register_command(
    "flight",
    advanced_flight_command,
    permission=Permission.USER,
    description="✈️ 智能航班搜索 - 全球航班查询、价格分析、智能推荐"
)

# 注册回调处理器
command_factory.register_callback(r"^flight_", advanced_flight_callback_handler, permission=Permission.USER, description="航班搜索回调")

# 注册文本消息处理器
command_factory.register_text_handler(advanced_flight_text_handler, permission=Permission.USER, description="航班搜索文本输入处理")