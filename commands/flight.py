#!/usr/bin/env python3
"""
Google Flights API 集成模块
提供航班搜索、价格监控、预订信息等功能
完全遵循map.py的缓存和自动删除模式
"""

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

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

logger = logging.getLogger(__name__)

# 全局变量 - 与map.py完全一致的模式
cache_manager = None
httpx_client = None
flight_service_manager = None

# SerpAPI配置
SERPAPI_BASE_URL = "https://serpapi.com/search"

# Telegraph相关配置
TELEGRAPH_API_URL = "https://api.telegra.ph"

# 航班数据ID映射缓存 - 与map.py完全一致的ID管理
flight_data_mapping = {}
mapping_counter = 0

# 创建航班会话管理器 - 与map.py相同的配置
flight_session_manager = SessionManager("FlightService", max_age=1800, max_sessions=200)  # 30分钟会话

async def _schedule_auto_delete(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, delay: int):
    """调度自动删除消息 - 与map.py完全一致"""
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
    """设置依赖项 - 与map.py完全一致的签名和模式"""
    global cache_manager, httpx_client, flight_service_manager
    cache_manager = cm
    httpx_client = hc
    
    # 初始化航班服务管理器
    config = get_config()
    flight_service_manager = FlightServiceManager(
        serpapi_key=getattr(config, 'serpapi_key', None)
    )

def get_short_flight_id(data_id: str) -> str:
    """生成短ID用于callback_data - 与map.py完全一致的逻辑"""
    global mapping_counter, flight_data_mapping
    
    # 查找是否已存在映射
    for short_id, full_id in flight_data_mapping.items():
        if full_id == data_id:
            return short_id
    
    # 创建新的短ID
    mapping_counter += 1
    short_id = str(mapping_counter)
    flight_data_mapping[short_id] = data_id
    
    # 清理过多的映射（保持最近500个）
    if len(flight_data_mapping) > 500:
        # 删除前50个旧映射
        old_keys = list(flight_data_mapping.keys())[:50]
        for key in old_keys:
            del flight_data_mapping[key]
    
    return short_id

def get_full_flight_id(short_id: str) -> Optional[str]:
    """根据短ID获取完整数据ID - 与map.py完全一致"""
    return flight_data_mapping.get(short_id)

class FlightServiceManager:
    """航班服务管理器 - 对应map.py的MapServiceManager"""
    
    def __init__(self, serpapi_key: str = None):
        self.serpapi_key = serpapi_key
    
    def is_available(self) -> bool:
        """检查服务是否可用"""
        return bool(self.serpapi_key)
    
    async def search_flights(self, departure_id: str, arrival_id: str, outbound_date: str, 
                           return_date: str = None, **kwargs) -> Optional[Dict]:
        """搜索航班"""
        if not self.is_available():
            logger.error("SerpAPI key not configured")
            return None
        
        params = {
            "engine": "google_flights",
            "departure_id": departure_id,
            "arrival_id": arrival_id,
            "outbound_date": outbound_date,
            "api_key": self.serpapi_key,
            "hl": kwargs.get("language", "en"),
            "currency": kwargs.get("currency", "USD")
        }
        
        # 添加返程日期（往返航班）
        if return_date:
            params["return_date"] = return_date
            params["type"] = "1"  # Round trip
        else:
            params["type"] = "2"  # One way
        
        # 添加其他可选参数
        if "travel_class" in kwargs:
            params["travel_class"] = kwargs["travel_class"]
        if "adults" in kwargs:
            params["adults"] = kwargs["adults"]
        if "children" in kwargs:
            params["children"] = kwargs["children"]
        
        try:
            response = await httpx_client.get(SERPAPI_BASE_URL, params=params)
            if response.status_code == 200:
                data = response.json()
                return data
            else:
                logger.error(f"SerpAPI request failed: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Flight search failed: {e}")
            return None
    
    async def get_booking_options(self, booking_token: str, search_params: Dict, **kwargs) -> Optional[Dict]:
        """获取预订选项 - 需要原始搜索参数"""
        if not self.is_available():
            return None
        
        # 构建完整的参数，包括原始搜索参数
        params = {
            "engine": "google_flights",
            "booking_token": booking_token,
            "departure_id": search_params.get('departure_id'),
            "arrival_id": search_params.get('arrival_id'),
            "outbound_date": search_params.get('outbound_date'),
            "api_key": self.serpapi_key,
            "hl": kwargs.get("language", "en"),
            "currency": kwargs.get("currency", "USD")
        }
        
        # 添加返程日期和类型
        if search_params.get('return_date'):
            params["return_date"] = search_params['return_date']
            params["type"] = "1"  # Round trip
        else:
            params["type"] = "2"  # One way
        
        # 添加其他可选参数
        if "travel_class" in kwargs:
            params["travel_class"] = kwargs["travel_class"]
        if "adults" in kwargs:
            params["adults"] = kwargs["adults"]
        if "children" in kwargs:
            params["children"] = kwargs["children"]
        
        try:
            response = await httpx_client.get(SERPAPI_BASE_URL, params=params)
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"SerpAPI booking request failed: {response.status_code}")
                logger.error(f"Response: {response.text}")
                return None
        except Exception as e:
            logger.error(f"Booking options request failed: {e}")
            return None

class FlightCacheService:
    """航班缓存服务类 - 与MapCacheService完全一致的结构"""
    
    async def search_flights_with_cache(self, departure_id: str, arrival_id: str, 
                                      outbound_date: str, return_date: str = None, 
                                      language: str = "en", **kwargs) -> Optional[Dict]:
        """带缓存的航班搜索 - 与map.py的search_location_with_cache相同模式"""
        # 构建缓存键
        route = f"{departure_id}_{arrival_id}_{outbound_date}"
        if return_date:
            route += f"_{return_date}"
        
        cache_key = f"flight_search_{language}_{route}_{kwargs.get('travel_class', '1')}"
        
        if cache_manager:
            config = get_config()
            cached_data = await cache_manager.load_cache(
                cache_key,
                max_age_seconds=getattr(config, 'flight_cache_duration', 3600),  # 1小时缓存
                subdirectory="flights"
            )
            if cached_data:
                logger.info(f"使用缓存的航班搜索数据: {route}")
                return cached_data
        
        try:
            if not flight_service_manager:
                return None
            
            flight_data = await flight_service_manager.search_flights(
                departure_id, arrival_id, outbound_date, return_date, 
                language=language, **kwargs
            )
            
            if flight_data and cache_manager:
                await cache_manager.save_cache(cache_key, flight_data, subdirectory="flights")
                logger.info(f"已缓存航班搜索数据: {route}")
            
            return flight_data
            
        except Exception as e:
            logger.error(f"航班搜索失败: {e}")
            return None
    
    async def get_booking_options_with_cache(self, booking_token: str, search_params: Dict, language: str = "en", **kwargs) -> Optional[Dict]:
        """带缓存的预订选项获取 - 需要原始搜索参数"""
        # 使用完整booking_token的哈希值作为缓存键，确保每个航班都有唯一的缓存
        import hashlib
        token_hash = hashlib.md5(booking_token.encode()).hexdigest()
        cache_key = f"flight_booking_{language}_{token_hash}"
        
        if cache_manager:
            config = get_config()
            cached_data = await cache_manager.load_cache(
                cache_key,
                max_age_seconds=getattr(config, 'flight_booking_cache_duration', 1800),  # 30分钟缓存
                subdirectory="flights"
            )
            if cached_data:
                logger.info(f"使用缓存的预订选项数据")
                return cached_data
        
        try:
            if not flight_service_manager:
                return None
            
            # 使用原始搜索参数+booking_token获取预订选项
            booking_data = await flight_service_manager.get_booking_options(
                booking_token, search_params=search_params, language=language, **kwargs
            )
            
            if booking_data and cache_manager:
                await cache_manager.save_cache(cache_key, booking_data, subdirectory="flights")
                logger.info(f"已缓存预订选项数据")
            
            return booking_data
            
        except Exception as e:
            logger.error(f"获取预订选项失败: {e}")
            return None
    
    async def get_price_insights_with_cache(self, departure_id: str, arrival_id: str, 
                                          outbound_date: str, language: str = "en") -> Optional[Dict]:
        """带缓存的价格洞察获取"""
        cache_key = f"flight_prices_{language}_{departure_id}_{arrival_id}_{outbound_date}"
        
        if cache_manager:
            config = get_config()
            cached_data = await cache_manager.load_cache(
                cache_key,
                max_age_seconds=getattr(config, 'flight_price_cache_duration', 7200),  # 2小时缓存
                subdirectory="flights"
            )
            if cached_data:
                logger.info(f"使用缓存的价格洞察数据: {departure_id} -> {arrival_id}")
                return cached_data
        
        try:
            # 价格洞察通常包含在航班搜索结果中
            flight_data = await self.search_flights_with_cache(
                departure_id, arrival_id, outbound_date, language=language
            )
            
            if flight_data and 'price_insights' in flight_data:
                price_insights = flight_data['price_insights']
                
                if cache_manager:
                    await cache_manager.save_cache(cache_key, price_insights, subdirectory="flights")
                    logger.info(f"已缓存价格洞察数据: {departure_id} -> {arrival_id}")
                
                return price_insights
            
            return None
            
        except Exception as e:
            logger.error(f"获取价格洞察失败: {e}")
            return None

# 创建全局航班缓存服务实例 - 与map.py完全一致
flight_cache_service = FlightCacheService()

def format_flight_info(flight: Dict) -> str:
    """格式化单个航班信息 - 最完整版本"""
    flights = flight.get('flights', [])
    if not flights:
        return "❌ 航班信息不完整"
    
    result = ""
    
    # 显示航班段信息
    for i, segment in enumerate(flights):
        if i > 0:
            result += "\n📍 *中转*\n"
        
        departure = segment.get('departure_airport', {})
        arrival = segment.get('arrival_airport', {})
        
        result += f"✈️ {segment.get('airline', 'Unknown')} {segment.get('flight_number', '')}\n"
        result += f"🛫 {departure.get('time', '')} {departure.get('name', departure.get('id', ''))}\n"
        result += f"🛬 {arrival.get('time', '')} {arrival.get('name', arrival.get('id', ''))}\n"
        
        # 飞行时间
        if 'duration' in segment:
            hours = segment['duration'] // 60
            minutes = segment['duration'] % 60
            result += f"⏱️ 飞行时间: {hours}小时{minutes}分钟\n"
        
        # 机型信息
        if 'airplane' in segment:
            result += f"✈️ 机型: {segment['airplane']}\n"
        
        # 舱位等级
        if 'travel_class' in segment:
            result += f"🎫 舱位: {segment['travel_class']}\n"
        
        # 座位空间信息
        legroom = segment.get('legroom')
        if legroom:
            result += f"📏 座位空间: {legroom}\n"
        
        # 过夜航班警告
        if segment.get('overnight'):
            result += f"🌙 过夜航班\n"
        
        # 延误警告
        if segment.get('often_delayed_by_over_30_min'):
            result += f"⚠️ 经常延误超过30分钟\n"
        
        # 航班特性
        extensions = segment.get('extensions', [])
        if extensions:
            # 显示前3个最重要的特性
            for ext in extensions[:3]:
                if 'Wi-Fi' in ext:
                    result += f"📶 {ext}\n"
                elif 'legroom' in ext:
                    result += f"💺 {ext}\n"
                elif 'power' in ext or 'USB' in ext:
                    result += f"🔌 {ext}\n"
                elif 'video' in ext or 'entertainment' in ext:
                    result += f"📺 {ext}\n"
        
        # 其他售票方
        also_sold_by = segment.get('ticket_also_sold_by', [])
        if also_sold_by:
            result += f"🎫 也可通过: {', '.join(also_sold_by[:2])}\n"  # 只显示前2个
        
        # 机组信息
        plane_crew = segment.get('plane_and_crew_by')
        if plane_crew:
            result += f"👥 运营: {plane_crew}\n"
    
    # 显示总时长
    if 'total_duration' in flight:
        total_hours = flight['total_duration'] // 60
        total_minutes = flight['total_duration'] % 60
        result += f"\n⏰ 总时长: {total_hours}小时{total_minutes}分钟\n"
    
    # 显示价格
    if 'price' in flight:
        result += f"💰 价格: ${flight['price']}\n"
    
    # 改进的中转信息显示
    layovers = flight.get('layovers', [])
    if layovers:
        result += f"\n🔄 中转: "
        layover_info = []
        for layover in layovers:
            duration_min = layover.get('duration', 0)
            hours = duration_min // 60
            minutes = duration_min % 60
            time_str = f"{hours}h{minutes}m" if minutes else f"{hours}h"
            
            airport_name = layover.get('name', layover.get('id', '未知'))
            layover_display = f"{airport_name} ({time_str})"
            
            # 过夜中转标识
            if layover.get('overnight'):
                layover_display += " 🌙过夜"
            
            layover_info.append(layover_display)
        result += " → ".join(layover_info)
        result += "\n"
    
    # 环保信息
    if 'carbon_emissions' in flight:
        emissions = flight['carbon_emissions']
        result += f"🌱 碳排放: {emissions.get('this_flight', 0):,}g"
        if 'difference_percent' in emissions:
            diff = emissions['difference_percent']
            if diff > 0:
                result += f" (+{diff}%)"
            elif diff < 0:
                result += f" ({diff}%)"
        result += "\n"
    
    # 航班类型信息
    flight_type = flight.get('type')
    if flight_type:
        result += f"🎫 航班类型: {flight_type}\n"
    
    # 预订建议（从Telegraph版本整合）
    flights_info = flight.get('flights', [])
    if flights_info:
        airline = flights_info[0].get('airline', '')
        if airline:
            result += f"💡 预订建议: 访问 {airline} 官网预订\n"
    
    return result

def format_flight_results(flight_data: Dict, search_params: Dict) -> str:
    """格式化航班搜索结果 - 与map.py的格式化函数相同模式"""
    if not flight_data:
        return "❌ 未找到航班信息"
    
    # 获取搜索参数
    departure_id = search_params.get('departure_id', '')
    arrival_id = search_params.get('arrival_id', '')
    outbound_date = search_params.get('outbound_date', '')
    return_date = search_params.get('return_date', '')
    
    trip_type = "往返" if return_date else "单程"
    
    result = f"✈️ *航班搜索结果*\n\n"
    result += f"🛫 {departure_id} → {arrival_id}\n"
    result += f"📅 出发: {outbound_date}"
    if return_date:
        result += f" | 返回: {return_date}"
    result += f" ({trip_type})\n\n"
    
    # 显示最佳航班
    best_flights = flight_data.get('best_flights', [])
    other_flights = flight_data.get('other_flights', [])
    
    all_flights = best_flights + other_flights
    
    if not all_flights:
        result += "❌ 未找到可用航班\n"
        result += "💡 建议:\n"
        result += "• 检查机场代码是否正确\n"
        result += "• 尝试其他日期\n"
        result += "• 检查是否有直航服务\n"
    else:
        # 显示前5个航班
        flights_to_show = min(5, len(all_flights))
        
        if best_flights:
            result += "🌟 *推荐航班:*\n\n"
            for i, flight in enumerate(best_flights[:3], 1):
                result += f"`{i}.` "
                result += format_flight_info(flight)
                result += "\n"
        
        if other_flights and flights_to_show > len(best_flights):
            result += "📋 *其他选择:*\n\n"
            remaining = flights_to_show - len(best_flights)
            for i, flight in enumerate(other_flights[:remaining], len(best_flights) + 1):
                result += f"`{i}.` "
                result += format_flight_info(flight)
                result += "\n"
        
        # 价格洞察
        price_insights = flight_data.get('price_insights', {})
        if price_insights:
            result += "📊 *价格分析:*\n"
            if 'lowest_price' in price_insights:
                result += f"💰 最低价格: ${price_insights['lowest_price']}\n"
            if 'price_level' in price_insights:
                level = price_insights['price_level']
                level_emoji = {"low": "🟢", "typical": "🟡", "high": "🔴"}.get(level, "⚪")
                result += f"{level_emoji} 价格水平: {level}\n"
            if 'typical_price_range' in price_insights:
                price_range = price_insights['typical_price_range']
                result += f"📈 典型价格区间: ${price_range[0]} - ${price_range[1]}\n"
    
    result += f"\n_数据来源: Google Flights via SerpAPI_"
    result += f"\n_更新时间: {datetime.now().strftime('%H:%M:%S')}_"
    
    return result

def format_price_insights(price_insights: Dict, departure_id: str, arrival_id: str) -> str:
    """格式化价格洞察信息"""
    if not price_insights:
        return f"❌ 暂无 {departure_id} → {arrival_id} 的价格信息"
    
    result = f"📊 *价格洞察* ({departure_id} → {arrival_id})\n\n"
    
    # 当前最低价格
    if 'lowest_price' in price_insights:
        result += f"💰 当前最低价格: ${price_insights['lowest_price']}\n"
    
    # 价格水平
    if 'price_level' in price_insights:
        level = price_insights['price_level']
        level_emoji = {
            "low": "🟢 偏低",
            "typical": "🟡 正常", 
            "high": "🔴 偏高"
        }.get(level, f"⚪ {level}")
        result += f"📈 价格水平: {level_emoji}\n"
    
    # 典型价格区间
    if 'typical_price_range' in price_insights:
        price_range = price_insights['typical_price_range']
        result += f"📊 典型价格区间: ${price_range[0]} - ${price_range[1]}\n"
    
    # 价格历史趋势
    if 'price_history' in price_insights:
        history = price_insights['price_history']
        if len(history) >= 2:
            latest_price = history[-1][1]
            previous_price = history[-2][1]
            change = latest_price - previous_price
            change_emoji = "📈" if change > 0 else "📉" if change < 0 else "➡️"
            result += f"{change_emoji} 价格趋势: "
            if change > 0:
                result += f"上涨 ${change}"
            elif change < 0:
                result += f"下降 ${abs(change)}"
            else:
                result += "无变化"
            result += "\n"
    
    # 最佳预订时机
    if 'best_time_to_book' in price_insights:
        booking_time = price_insights['best_time_to_book']
        result += f"⏰ 最佳预订时机: {booking_time}\n"
    
    # 价格预测
    if 'price_forecast' in price_insights:
        forecast = price_insights['price_forecast']
        if forecast:
            result += f"🔮 价格预测: {forecast}\n"
    
    # 预订建议
    result += f"\n💡 *建议:*\n"
    if price_insights.get('price_level') == 'low':
        result += "• 🟢 价格较低，建议预订\n"
    elif price_insights.get('price_level') == 'high':
        result += "• 🔴 价格偏高，可考虑其他日期\n"
        result += "• 📅 尝试工作日出行\n"
    else:
        result += "• 🟡 价格合理，可根据需要预订\n"
    
    # 价格趋势建议
    if 'price_history' in price_insights:
        history = price_insights['price_history']
        if len(history) >= 3:
            recent_trend = [h[1] for h in history[-3:]]
            if recent_trend[-1] < recent_trend[0]:
                result += "• 📉 近期价格下降，可继续观察\n"
            elif recent_trend[-1] > recent_trend[0]:
                result += "• 📈 近期价格上涨，建议尽早预订\n"
    
    result += f"\n_更新时间: {datetime.now().strftime('%H:%M:%S')}_"
    
    return result

async def create_telegraph_page(title: str, content: str) -> Optional[str]:
    """创建Telegraph页面用于显示长内容"""
    try:
        # 创建Telegraph账户
        account_data = {
            "short_name": "FlightBot",
            "author_name": "MengBot Flight Service",
            "author_url": "https://t.me/mengpricebot"
        }
        
        response = await httpx_client.post(f"{TELEGRAPH_API_URL}/createAccount", data=account_data)
        if response.status_code != 200:
            logger.warning(f"创建Telegraph账户失败: {response.status_code}")
            return None
            
        account_info = response.json()
        if not account_info.get("ok"):
            logger.warning(f"Telegraph账户创建响应错误: {account_info}")
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
            logger.warning(f"创建Telegraph页面失败: {response.status_code}")
            return None
            
        page_info = response.json()
        if not page_info.get("ok"):
            logger.warning(f"Telegraph页面创建响应错误: {page_info}")
            return None
            
        logger.info(f"成功创建Telegraph页面: {page_info['result']['url']}")
        return page_info["result"]["url"]
    
    except Exception as e:
        logger.error(f"创建Telegraph页面失败: {e}")
        return None

async def create_booking_telegraph_page(all_flights: List[Dict], search_params: Dict) -> str:
    """将航班预订选项格式化为Telegraph友好的格式 - 与主消息完全一致"""
    departure_id = search_params.get('departure_id', '')
    arrival_id = search_params.get('arrival_id', '')
    outbound_date = search_params.get('outbound_date', '')
    return_date = search_params.get('return_date', '')
    
    trip_type = "往返" if return_date else "单程"
    
    content = f"""航班预订详情

📍 航线: {departure_id} → {arrival_id}
📅 出发: {outbound_date}"""
    
    if return_date:
        content += f"\n📅 返回: {return_date}"
    
    content += f"\n🎫 类型: {trip_type}\n\n"
    
    content += f"💺 可预订航班 (共{len(all_flights)}个选项):\n\n"
    
    # 显示所有航班 - 完全复制_show_booking_options的逻辑
    for i, flight in enumerate(all_flights, 1):
        content += f"{i}. "
        
        # 航班基本信息
        flights_info = flight.get('flights', [])
        if flights_info:
            segment = flights_info[0]
            airline = segment.get('airline', '未知')
            flight_number = segment.get('flight_number', '')
            content += f"{airline} {flight_number}\n"
            
            departure = segment.get('departure_airport', {})
            arrival = segment.get('arrival_airport', {})
            content += f"   🛫 {departure.get('time', '')}\n"
            content += f"   🛬 {arrival.get('time', '')}\n"
        
        # 价格信息
        price = flight.get('price')
        if price:
            content += f"   💰 价格: ${price}\n"
        
        # 航班特性信息 - 复制主消息的逻辑
        if flights_info:
            segment = flights_info[0]
            
            # 座位空间信息
            legroom = segment.get('legroom')
            if legroom:
                content += f"   📏 座位空间: {legroom}\n"
            
            # 过夜航班警告
            if segment.get('overnight'):
                content += f"   🌙 过夜航班\n"
            
            # 延误警告
            if segment.get('often_delayed_by_over_30_min'):
                content += f"   ⚠️ 经常延误超过30分钟\n"
            
            # 航班特性
            extensions = segment.get('extensions', [])
            if extensions:
                # 只显示前3个最重要的特性
                for ext in extensions[:3]:
                    if 'Wi-Fi' in ext:
                        content += f"   📶 {ext}\n"
                    elif 'legroom' in ext:
                        content += f"   💺 {ext}\n"
                    elif 'power' in ext or 'USB' in ext:
                        content += f"   🔌 {ext}\n"
            
            # 其他售票方
            also_sold_by = segment.get('ticket_also_sold_by', [])
            if also_sold_by:
                content += f"   🎫 也可通过: {', '.join(also_sold_by)}\n"
        
        # 中转信息改进 - 复制主消息的逻辑
        layovers = flight.get('layovers', [])
        if layovers:
            for layover in layovers:
                duration_min = layover.get('duration', 0)
                hours = duration_min // 60
                minutes = duration_min % 60
                time_str = f"{hours}h{minutes}m" if minutes else f"{hours}h"
                
                airport_name = layover.get('name', layover.get('id', '未知'))
                content += f"   ✈️ 中转: {airport_name} ({time_str})"
                
                # 过夜中转标识
                if layover.get('overnight'):
                    content += " 🌙过夜"
                content += "\n"
        
        # 预订信息处理 - 这里需要模拟主消息的booking_token处理
        # 由于Telegraph是静态内容，我们只能显示基本的预订建议
        if flights_info:
            airline = flights_info[0].get('airline', '')
            if airline:
                content += f"   🏢 预订商: {airline}\n"
                content += f"   💡 建议直接访问 {airline} 官网预订\n"
            else:
                content += f"   💡 建议访问航空公司官网预订\n"
        
        content += "\n"
    
    content += f"""

预订建议:
• 比较不同航空公司的价格
• 灵活选择日期可能有更好价格
• 提前预订通常价格更优
• 预订前请确认航班时间和政策

---
数据来源: Google Flights via SerpAPI
生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
来源: MengBot 航班服务"""
    
    return content

async def flight_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """航班服务主命令 /flight - 与map.py的map_command完全一致的结构"""
    if not update.message:
        return
        
    # 检查是否配置了API密钥
    config = get_config()
    if not getattr(config, 'serpapi_key', None):
        await send_error(
            context, 
            update.message.chat_id,
            "❌ 航班服务未配置API密钥，请联系管理员"
        )
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        return
    
    # 如果有参数，解析并搜索航班
    if context.args:
        # 简单参数解析: /flight PEK LAX 2024-12-25 [2024-12-30]
        args = context.args
        if len(args) >= 3:
            departure_id = args[0].upper()
            arrival_id = args[1].upper()
            outbound_date = args[2]
            return_date = args[3] if len(args) > 3 else None
            
            await _execute_flight_search(update, context, departure_id, arrival_id, outbound_date, return_date)
        else:
            await send_error(context, update.message.chat_id, 
                           "❌ 参数不足\n\n格式: `/flight 出发机场 到达机场 出发日期 [返回日期]`\n"
                           "例如: `/flight PEK LAX 2024-12-25 2024-12-30`")
        
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        return
    
    # 没有参数，显示主菜单 - 与map.py完全一致的菜单结构
    keyboard = [
        [
            InlineKeyboardButton("🔍 搜索航班", callback_data="flight_search"),
            InlineKeyboardButton("📊 价格监控", callback_data="flight_prices")
        ],
        [
            InlineKeyboardButton("🎫 预订信息", callback_data="flight_booking"),
            InlineKeyboardButton("🗺️ 多城市", callback_data="flight_multi_city")
        ],
        [
            InlineKeyboardButton("❌ 关闭", callback_data="flight_close")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    help_text = """✈️ 智能航班服务

🌍 功能介绍:
• **搜索航班**: 查找最佳航班和价格
• **价格监控**: 跟踪价格趋势和预警
• **预订信息**: 获取详细预订选项
• **多城市**: 复杂行程规划

🤖 智能特性:
• 实时价格比较
• 价格历史趋势分析
• 最佳出行时间建议
• 碳排放信息

💡 快速使用:
`/flight PEK LAX 2024-12-25` - 搜索单程
`/flight PEK LAX 2024-12-25 2024-12-30` - 搜索往返

请选择功能:"""
    
    await send_message_with_auto_delete(
        context=context,
        chat_id=update.message.chat_id,
        text=foldable_text_with_markdown_v2(help_text),
        parse_mode="MarkdownV2",
        reply_markup=reply_markup
    )
    
    await delete_user_command(context, update.message.chat_id, update.message.message_id)

async def _execute_flight_search(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                departure_id: str, arrival_id: str, outbound_date: str, 
                                return_date: str = None, callback_query: CallbackQuery = None) -> None:
    """执行航班搜索 - 与map.py的_execute_location_search相同模式"""
    # 检测用户语言
    user_locale = update.effective_user.language_code if update.effective_user else None
    language = detect_user_language("", user_locale)  # 航班搜索主要使用locale检测
    
    trip_type = "往返" if return_date else "单程"
    loading_message = f"✈️ 正在搜索航班 {departure_id} → {arrival_id} ({trip_type})... ⏳"
    
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
        # 调度自动删除 - 与map.py完全一致
        config = get_config()
        await _schedule_auto_delete(context, message.chat_id, message.message_id, 
                                  getattr(config, 'auto_delete_delay', 600))
    
    try:
        # 检查服务可用性
        if not flight_service_manager or not flight_service_manager.is_available():
            error_msg = "❌ 航班服务暂不可用"
            if callback_query:
                await callback_query.edit_message_text(error_msg)
                await _schedule_auto_delete(context, callback_query.message.chat_id, 
                                          callback_query.message.message_id, 5)
            else:
                await message.edit_text(error_msg)
                await _schedule_auto_delete(context, message.chat_id, message.message_id, 5)
            return
        
        # 使用缓存服务搜索航班 - 与map.py完全一致的缓存模式
        search_params = {
            'departure_id': departure_id,
            'arrival_id': arrival_id,
            'outbound_date': outbound_date,
            'return_date': return_date
        }
        
        flight_data = await flight_cache_service.search_flights_with_cache(
            departure_id=departure_id,
            arrival_id=arrival_id,
            outbound_date=outbound_date,
            return_date=return_date,
            language=language,
            currency="USD"
        )
        
        if flight_data and (flight_data.get('best_flights') or flight_data.get('other_flights')):
            # 找到航班信息
            result_text = format_flight_results(flight_data, search_params)
            
            # 创建操作按钮 - 与map.py相同的按钮生成模式
            search_data = f"{departure_id}:{arrival_id}:{outbound_date}:{return_date or ''}:{language}"
            prices_short_id = get_short_flight_id(f"price_insights:{search_data}")
            booking_short_id = get_short_flight_id(f"booking_info:{search_data}")
            
            keyboard = [
                [
                    InlineKeyboardButton("📊 价格分析", callback_data=f"flight_short:{prices_short_id}"),
                    InlineKeyboardButton("🎫 预订选项", callback_data=f"flight_short:{booking_short_id}")
                ],
                [
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
            # 未找到结果 - 与map.py相同的错误处理模式
            error_msg = f"❌ 未找到航班: {departure_id} → {arrival_id}\n\n"
            error_msg += "💡 建议:\n"
            error_msg += "• 检查机场代码是否正确\n"
            error_msg += "• 尝试其他日期\n"
            error_msg += "• 检查是否有直航服务"
            
            keyboard = [
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if callback_query:
                await callback_query.edit_message_text(
                    text=error_msg,
                    reply_markup=reply_markup
                )
                config = get_config()
                await _schedule_auto_delete(context, callback_query.message.chat_id, 
                                          callback_query.message.message_id, 
                                          getattr(config, 'auto_delete_delay', 600))
            else:
                await message.edit_text(
                    text=error_msg,
                    reply_markup=reply_markup
                )
                config = get_config()
                await _schedule_auto_delete(context, message.chat_id, message.message_id, 
                                          getattr(config, 'auto_delete_delay', 600))
                
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
            await _schedule_auto_delete(context, callback_query.message.chat_id, 
                                      callback_query.message.message_id, 
                                      getattr(config, 'auto_delete_delay', 600))
        else:
            await message.edit_text(
                text=error_msg,
                reply_markup=reply_markup
            )
            await _schedule_auto_delete(context, message.chat_id, message.message_id, 
                                      getattr(config, 'auto_delete_delay', 600))

async def flight_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理航班功能的文本输入 - 与map.py的map_text_handler完全一致的结构"""
    if not update.message or not update.message.text:
        return
    
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # 获取用户会话 - 与map.py完全一致的会话管理
    session_data = flight_session_manager.get_session(user_id)
    if not session_data:
        return  # 没有活动会话，忽略
    
    action = session_data.get("action")
    waiting_for = session_data.get("waiting_for")
    
    try:
        # 删除用户输入的命令 - 与map.py完全一致
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        
        if action == "flight_search" and waiting_for == "search_params":
            # 处理航班搜索参数
            await _parse_and_execute_flight_search(update, context, text)
            flight_session_manager.remove_session(user_id)
            
        elif action == "price_monitor" and waiting_for == "route":
            # 处理价格监控设置
            await _execute_price_monitoring(update, context, text)
            flight_session_manager.remove_session(user_id)
            
    except Exception as e:
        logger.error(f"处理航班文本输入失败: {e}")
        await send_error(context, update.message.chat_id, f"处理失败: {str(e)}")
        flight_session_manager.remove_session(user_id)

async def _parse_and_execute_flight_search(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """解析并执行航班搜索"""
    # 解析格式: "PEK LAX 2024-12-25 [2024-12-30]"
    parts = text.strip().split()
    
    if len(parts) < 3:
        await send_error(context, update.message.chat_id, 
                        "❌ 格式错误\n\n请使用: `出发机场 到达机场 出发日期 [返回日期]`\n"
                        "例如: `PEK LAX 2024-12-25 2024-12-30`")
        return
    
    departure_id = parts[0].upper()
    arrival_id = parts[1].upper()
    outbound_date = parts[2]
    return_date = parts[3] if len(parts) > 3 else None
    
    # 简单的日期格式验证
    try:
        datetime.strptime(outbound_date, '%Y-%m-%d')
        if return_date:
            datetime.strptime(return_date, '%Y-%m-%d')
    except ValueError:
        await send_error(context, update.message.chat_id, 
                        "❌ 日期格式错误，请使用 YYYY-MM-DD 格式")
        return
    
    await _execute_flight_search(update, context, departure_id, arrival_id, outbound_date, return_date)

async def _execute_price_monitoring(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """执行价格监控设置"""
    # 解析航线信息
    parts = text.strip().split()
    
    if len(parts) < 3:
        await send_error(context, update.message.chat_id, 
                        "❌ 格式错误\n\n请使用: `出发机场 到达机场 出发日期`")
        return
    
    departure_id = parts[0].upper()
    arrival_id = parts[1].upper()
    outbound_date = parts[2]
    
    loading_message = f"📊 正在获取价格信息 {departure_id} → {arrival_id}... ⏳"
    
    message = await context.bot.send_message(
        chat_id=update.message.chat_id,
        text=foldable_text_v2(loading_message),
        parse_mode="MarkdownV2"
    )
    
    # 调度自动删除
    config = get_config()
    await _schedule_auto_delete(context, message.chat_id, message.message_id, 
                              getattr(config, 'auto_delete_delay', 600))
    
    try:
        # 获取价格洞察
        price_insights = await flight_cache_service.get_price_insights_with_cache(
            departure_id, arrival_id, outbound_date
        )
        
        if price_insights:
            result_text = format_price_insights(price_insights, departure_id, arrival_id)
            
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
            error_msg = f"❌ 无法获取 {departure_id} → {arrival_id} 的价格信息"
            keyboard = [
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await message.edit_text(
                text=error_msg,
                reply_markup=reply_markup
            )
            await _schedule_auto_delete(context, message.chat_id, message.message_id, 
                                      getattr(config, 'auto_delete_delay', 600))
            
    except Exception as e:
        logger.error(f"价格监控失败: {e}")
        error_msg = f"❌ 价格监控失败: {str(e)}"
        keyboard = [
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await message.edit_text(
            text=error_msg,
            reply_markup=reply_markup
        )
        await _schedule_auto_delete(context, message.chat_id, message.message_id, 
                                  getattr(config, 'auto_delete_delay', 600))

async def flight_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理航班功能的回调查询 - 与map.py的map_callback_handler完全一致的结构"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "flight_close":
        # 清理用户会话 - 与map.py完全一致
        user_id = update.effective_user.id
        flight_session_manager.remove_session(user_id)
        await query.delete_message()
        return
    
    elif data == "flight_main_menu":
        # 清理用户会话并返回主菜单 - 与map.py完全一致
        user_id = update.effective_user.id
        flight_session_manager.remove_session(user_id)
        
        # 返回主菜单
        keyboard = [
            [
                InlineKeyboardButton("🔍 搜索航班", callback_data="flight_search"),
                InlineKeyboardButton("📊 价格监控", callback_data="flight_prices")
            ],
            [
                InlineKeyboardButton("🎫 预订信息", callback_data="flight_booking"),
                InlineKeyboardButton("🗺️ 多城市", callback_data="flight_multi_city")
            ],
            [
                InlineKeyboardButton("❌ 关闭", callback_data="flight_close")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        help_text = """✈️ 智能航班服务

🌍 功能介绍:
• **搜索航班**: 查找最佳航班和价格
• **价格监控**: 跟踪价格趋势和预警
• **预订信息**: 获取详细预订选项
• **多城市**: 复杂行程规划

🤖 智能特性:
• 实时价格比较
• 价格历史趋势分析
• 最佳出行时间建议
• 碳排放信息

💡 快速使用:
`/flight PEK LAX 2024-12-25` - 搜索单程
`/flight PEK LAX 2024-12-25 2024-12-30` - 搜索往返

请选择功能:"""
        
        await query.edit_message_text(
            text=foldable_text_with_markdown_v2(help_text),
            parse_mode="MarkdownV2",
            reply_markup=reply_markup
        )
    
    elif data == "flight_search":
        user_id = update.effective_user.id
        
        # 设置会话状态 - 与map.py完全一致的会话管理
        flight_session_manager.set_session(user_id, {
            "action": "flight_search",
            "waiting_for": "search_params"
        })
        
        # 航班搜索指引
        search_help_text = """🔍 请输入航班搜索信息:

格式: `出发机场 到达机场 出发日期 [返回日期]`

例如:
• `PEK LAX 2025-09-25` (单程)
• `PEK LAX 2025-09-25 2025-09-30` (往返)
• `BJS NYC 2025-09-25` (单程)"""

        await query.edit_message_text(
            text=foldable_text_with_markdown_v2(search_help_text),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
            ]),
            parse_mode="MarkdownV2"
        )
    
    elif data == "flight_prices":
        user_id = update.effective_user.id
        
        # 设置会话状态
        flight_session_manager.set_session(user_id, {
            "action": "price_monitor",
            "waiting_for": "route"
        })
        
        await query.edit_message_text(
            text="📊 价格监控设置:\n\n"
                 "请输入要监控的航线信息:\n"
                 "格式: `出发机场 到达机场 出发日期`\n\n"
                 "例如: `PEK LAX 2024-12-25`",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
            ])
        )
    
    elif data == "flight_booking":
        # 预订信息功能
        booking_help_text = """🎫 预订信息功能

此功能需要先搜索具体航班后才能使用。

请先使用 **搜索航班** 功能找到合适的航班，
然后在结果中查看预订选项。"""

        await query.edit_message_text(
            text=foldable_text_with_markdown_v2(booking_help_text),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔍 搜索航班", callback_data="flight_search")],
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
            ]),
            parse_mode="MarkdownV2"
        )
    
    elif data == "flight_multi_city":
        # 多城市功能
        await query.edit_message_text(
            text="🗺️ 多城市行程规划\n\n"
                 "此功能目前支持复杂行程的价格查询。\n\n"
                 "💡 使用建议:\n"
                 "• 分段搜索各个航段\n"
                 "• 比较不同路线的总价格\n"
                 "• 考虑中转时间和便利性",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔍 开始搜索", callback_data="flight_search")],
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
            ])
        )
    
    elif data.startswith("flight_short:"):
        # 处理短ID映射的callback - 与map.py完全一致的短ID处理
        short_id = data.split(":", 1)[1]
        full_data = get_full_flight_id(short_id)
        
        if not full_data:
            await query.edit_message_text("❌ 链接已过期，请重新搜索")
            config = get_config()
            await _schedule_auto_delete(context, query.message.chat_id, query.message.message_id, 5)
            return
        
        # 解析完整数据并转发到相应处理器
        if full_data.startswith("price_insights:"):
            search_data = full_data.replace("price_insights:", "")
            parts = search_data.split(":")
            if len(parts) >= 4:
                departure_id, arrival_id, outbound_date = parts[0], parts[1], parts[2]
                language = parts[4] if len(parts) > 4 else "en"
                
                # 获取价格洞察
                await _show_price_insights(query, context, departure_id, arrival_id, outbound_date, language)
                
        elif full_data.startswith("booking_info:"):
            search_data = full_data.replace("booking_info:", "")
            parts = search_data.split(":")
            if len(parts) >= 4:
                departure_id, arrival_id, outbound_date = parts[0], parts[1], parts[2]
                return_date = parts[3] if parts[3] else None
                language = parts[4] if len(parts) > 4 else "en"
                
                # 显示预订信息
                await _show_booking_options(query, context, departure_id, arrival_id, outbound_date, return_date, language)
            else:
                await query.edit_message_text(
                    text="❌ 预订信息数据错误",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
                    ])
                )

async def _show_price_insights(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, 
                             departure_id: str, arrival_id: str, outbound_date: str, language: str) -> None:
    """显示价格洞察信息"""
    loading_message = f"📊 正在分析价格 {departure_id} → {arrival_id}... ⏳"
    
    await query.edit_message_text(
        text=foldable_text_v2(loading_message),
        parse_mode="MarkdownV2"
    )
    
    try:
        price_insights = await flight_cache_service.get_price_insights_with_cache(
            departure_id, arrival_id, outbound_date, language
        )
        
        if price_insights:
            result_text = format_price_insights(price_insights, departure_id, arrival_id)
            
            keyboard = [
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                text=foldable_text_with_markdown_v2(result_text),
                parse_mode="MarkdownV2",
                reply_markup=reply_markup
            )
        else:
            error_msg = f"❌ 无法获取 {departure_id} → {arrival_id} 的价格信息"
            keyboard = [
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                text=error_msg,
                reply_markup=reply_markup
            )
            config = get_config()
            await _schedule_auto_delete(context, query.message.chat_id, query.message.message_id, 
                                      getattr(config, 'auto_delete_delay', 600))
            
    except Exception as e:
        logger.error(f"显示价格洞察失败: {e}")
        error_msg = f"❌ 价格分析失败: {str(e)}"
        keyboard = [
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text=error_msg,
            reply_markup=reply_markup
        )
        config = get_config()
        await _schedule_auto_delete(context, query.message.chat_id, query.message.message_id, 
                                  getattr(config, 'auto_delete_delay', 600))

async def _show_booking_options(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, 
                              departure_id: str, arrival_id: str, outbound_date: str, 
                              return_date: str = None, language: str = "en") -> None:
    """显示航班预订选项"""
    trip_type = "往返" if return_date else "单程"
    loading_message = f"🎫 正在获取预订选项 {departure_id} → {arrival_id} ({trip_type})... ⏳"
    
    await query.edit_message_text(
        text=foldable_text_v2(loading_message),
        parse_mode="MarkdownV2"
    )
    
    try:
        # 先获取航班搜索结果
        search_params = {
            'departure_id': departure_id,
            'arrival_id': arrival_id,
            'outbound_date': outbound_date,
            'return_date': return_date
        }
        
        flight_data = await flight_cache_service.search_flights_with_cache(
            departure_id=departure_id,
            arrival_id=arrival_id,
            outbound_date=outbound_date,
            return_date=return_date,
            language=language,
            currency="USD"
        )
        
        if flight_data and (flight_data.get('best_flights') or flight_data.get('other_flights')):
            result_text = f"🎫 *预订选项* ({departure_id} → {arrival_id})\n\n"
            result_text += f"📅 出发: {outbound_date}"
            if return_date:
                result_text += f" | 返回: {return_date}"
            result_text += f" ({trip_type})\n\n"
            
            # 获取可预订的航班选项
            best_flights = flight_data.get('best_flights', [])
            other_flights = flight_data.get('other_flights', [])
            all_flights = best_flights + other_flights
            
            if all_flights:
                result_text += "💺 *可预订航班:*\n\n"
                
                # 显示前5个航班的预订信息  
                flights_to_show = min(5, len(all_flights))
                should_use_telegraph = len(all_flights) > 5  # 超过5个使用Telegraph
                
                for i, flight in enumerate(all_flights[:flights_to_show], 1):
                    result_text += f"`{i}.` "
                    
                    # 航班基本信息
                    flights_info = flight.get('flights', [])
                    if flights_info:
                        segment = flights_info[0]
                        airline = segment.get('airline', '未知')
                        flight_number = segment.get('flight_number', '')
                        result_text += f"*{airline} {flight_number}*\n"
                        
                        departure = segment.get('departure_airport', {})
                        arrival = segment.get('arrival_airport', {})
                        result_text += f"   🛫 {departure.get('time', '')}\n"
                        result_text += f"   🛬 {arrival.get('time', '')}\n"
                    
                    # 价格信息
                    price = flight.get('price')
                    if price:
                        result_text += f"   💰 价格: *${price}*\n"
                    
                    # 航班特性信息
                    if flights_info:
                        segment = flights_info[0]
                        
                        # 座位空间信息
                        legroom = segment.get('legroom')
                        if legroom:
                            result_text += f"   📏 座位空间: {legroom}\n"
                        
                        # 过夜航班警告
                        if segment.get('overnight'):
                            result_text += f"   🌙 过夜航班\n"
                        
                        # 延误警告
                        if segment.get('often_delayed_by_over_30_min'):
                            result_text += f"   ⚠️ 经常延误超过30分钟\n"
                        
                        # 航班特性
                        extensions = segment.get('extensions', [])
                        if extensions:
                            # 只显示前3个最重要的特性
                            for ext in extensions[:3]:
                                if 'Wi-Fi' in ext:
                                    result_text += f"   📶 {ext}\n"
                                elif 'legroom' in ext:
                                    result_text += f"   💺 {ext}\n"
                                elif 'power' in ext or 'USB' in ext:
                                    result_text += f"   🔌 {ext}\n"
                        
                        # 其他售票方
                        also_sold_by = segment.get('ticket_also_sold_by', [])
                        if also_sold_by:
                            result_text += f"   🎫 也可通过: {', '.join(also_sold_by)}\n"
                    
                    # 中转信息改进
                    layovers = flight.get('layovers', [])
                    if layovers:
                        for layover in layovers:
                            duration_min = layover.get('duration', 0)
                            hours = duration_min // 60
                            minutes = duration_min % 60
                            time_str = f"{hours}h{minutes}m" if minutes else f"{hours}h"
                            
                            airport_name = layover.get('name', layover.get('id', '未知'))
                            result_text += f"   ✈️ 中转: {airport_name} ({time_str})"
                            
                            # 过夜中转标识
                            if layover.get('overnight'):
                                result_text += " 🌙过夜"
                            result_text += "\n"
                    
                    # 获取真实预订选项
                    booking_token = flight.get('booking_token')
                    if booking_token:
                        try:
                            # 使用booking_token获取详细预订选项
                            booking_options = await flight_cache_service.get_booking_options_with_cache(
                                booking_token, search_params, language=language
                            )
                            
                            if booking_options and booking_options.get('booking_options'):
                                booking_option = booking_options['booking_options'][0]  # 取第一个选项
                                
                                # 检查是否为分别预订的机票
                                separate_tickets = booking_option.get('separate_tickets', False)
                                if separate_tickets:
                                    result_text += f"   🎫 *分别预订机票*\n"
                                    
                                    # 处理出发段预订
                                    departing = booking_option.get('departing', {})
                                    if departing:
                                        result_text += f"   🛫 *出发段预订:*\n"
                                        book_with = departing.get('book_with', '')
                                        if book_with:
                                            result_text += f"      🏢 预订商: {book_with}\n"
                                        price = departing.get('price')
                                        if price:
                                            result_text += f"      💰 价格: ${price}\n"
                                    
                                    # 处理返程段预订
                                    returning = booking_option.get('returning', {})
                                    if returning:
                                        result_text += f"   🛬 *返程段预订:*\n"
                                        book_with = returning.get('book_with', '')
                                        if book_with:
                                            result_text += f"      🏢 预订商: {book_with}\n"
                                        price = returning.get('price')
                                        if price:
                                            result_text += f"      💰 价格: ${price}\n"
                                else:
                                    # 一起预订的处理
                                    together_option = booking_option.get('together', {})
                                    
                                    # 显示预订提供商
                                    book_with = together_option.get('book_with', '')
                                    if book_with:
                                        result_text += f"   🏢 预订商: *{book_with}*\n"
                                    
                                    # 显示本地价格
                                    local_prices = together_option.get('local_prices', [])
                                    if local_prices:
                                        for local_price in local_prices[:2]:  # 显示前2个本地价格
                                            currency = local_price.get('currency', 'USD')
                                            price_val = local_price.get('price', 0)
                                            result_text += f"   💱 本地价格: {currency} {price_val:,}\n"
                                    
                                    # 显示电话服务费
                                    phone_fee = together_option.get('estimated_phone_service_fee')
                                    if phone_fee:
                                        result_text += f"   📞 电话服务费: ${phone_fee}\n"
                                    
                                    # 显示真实预订链接
                                    booking_request = together_option.get('booking_request', {})
                                    booking_url_from_api = booking_request.get('url', '')
                                    
                                    if booking_url_from_api and 'google.com/travel/clk/' in booking_url_from_api:
                                        # Google Flights的redirect URL需要POST数据，对用户不友好
                                        # 显示预订商信息并提供搜索建议
                                        book_with = together_option.get('book_with', '')
                                        if book_with:
                                            result_text += f"   💡 建议直接访问 *{book_with}* 官网预订\n"
                                        else:
                                            result_text += f"   💡 建议访问航空公司官网预订\n"
                                    elif booking_url_from_api and 'google.com' not in booking_url_from_api:
                                        # 如果是航空公司官网链接，直接使用
                                        result_text += f"   🔗 [立即预订]({booking_url_from_api})\n"
                                    elif together_option.get('booking_phone'):
                                        phone = together_option['booking_phone']
                                        result_text += f"   📞 预订电话: {phone}\n"
                                    else:
                                        # 备用方案：提供建议
                                        result_text += f"   💡 建议访问航空公司官网预订\n"
                            else:
                                # 如果获取详细预订选项失败，提供建议
                                result_text += f"   💡 建议访问航空公司官网预订\n"
                                
                        except Exception as e:
                            logger.warning(f"获取预订选项失败: {e}")
                            # 备用方案：提供建议
                            result_text += f"   💡 建议访问航空公司官网预订\n"
                    else:
                        # 备用方案：使用Google Flights通用搜索链接
                        google_flights_url = f"https://www.google.com/travel/flights?q=flights%20from%20{departure_id}%20to%20{arrival_id}"
                        result_text += f"   🔗 [在Google Flights查看]({google_flights_url})\n"
                    
                    result_text += "\n"
                
                # Telegraph支持长列表
                if should_use_telegraph:
                    # 创建Telegraph页面显示完整预订信息
                    booking_title = f"预订选项: {departure_id} → {arrival_id}"
                    telegraph_content = await create_booking_telegraph_page(all_flights, search_params)
                    telegraph_url = await create_telegraph_page(booking_title, telegraph_content)
                    
                    if telegraph_url:
                        result_text += f"📋 *完整预订列表*: [查看全部 {len(all_flights)} 个选项]({telegraph_url})\n\n"
                    else:
                        result_text += f"📋 *还有 {len(all_flights) - flights_to_show} 个其他选项*\n"
                        result_text += "💡 使用 **搜索航班** 功能查看完整列表\n\n"
                else:
                    # 添加更多选项提示
                    if len(all_flights) > flights_to_show:
                        result_text += f"📋 *还有 {len(all_flights) - flights_to_show} 个其他选项*\n"
                        result_text += "💡 使用 **搜索航班** 功能查看完整列表\n\n"
                
                # 预订建议
                result_text += "💡 *预订建议:*\n"
                result_text += "• 🔍 比较不同航空公司的价格\n"
                result_text += "• 📅 灵活选择日期可能有更好价格\n"
                result_text += "• 🎫 提前预订通常价格更优\n"
                result_text += "• ⚠️ 预订前请确认航班时间和政策\n\n"
                
            else:
                result_text += "❌ 暂无可预订的航班选项\n\n"
                result_text += "💡 建议:\n"
                result_text += "• 尝试其他日期\n"
                result_text += "• 检查机场代码\n"
                result_text += "• 考虑附近的其他机场\n\n"
            
            result_text += f"_数据来源: Google Flights via SerpAPI_\n"
            result_text += f"_更新时间: {datetime.now().strftime('%H:%M:%S')}_"
            
            keyboard = [
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                text=foldable_text_with_markdown_v2(result_text),
                parse_mode="MarkdownV2",
                reply_markup=reply_markup
            )
        else:
            error_msg = f"❌ 无法获取 {departure_id} → {arrival_id} 的预订信息\n\n"
            error_msg += "可能原因:\n"
            error_msg += "• 该航线暂无可预订航班\n"
            error_msg += "• 选择的日期没有航班服务\n"
            error_msg += "• 航班数据暂时不可用"
            
            keyboard = [
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                text=error_msg,
                reply_markup=reply_markup
            )
            config = get_config()
            await _schedule_auto_delete(context, query.message.chat_id, query.message.message_id, 
                                      getattr(config, 'auto_delete_delay', 600))
            
    except Exception as e:
        logger.error(f"显示预订选项失败: {e}")
        error_msg = f"❌ 获取预订信息失败: {str(e)}"
        keyboard = [
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text=error_msg,
            reply_markup=reply_markup
        )
        config = get_config()
        await _schedule_auto_delete(context, query.message.chat_id, query.message.message_id, 
                                  getattr(config, 'auto_delete_delay', 600))

# =============================================================================
# 注册命令和回调 - 与map.py完全一致的注册模式
# =============================================================================

# 注册主命令
command_factory.register_command(
    "flight",
    flight_command,
    permission=Permission.USER,
    description="✈️ 智能航班服务 - 航班搜索、价格监控、预订信息"
)

# 注册回调处理器
command_factory.register_callback(r"^flight_", flight_callback_handler, permission=Permission.USER, description="航班服务回调")

# 注册文本消息处理器
command_factory.register_text_handler(flight_text_handler, permission=Permission.USER, description="航班服务文本输入处理")