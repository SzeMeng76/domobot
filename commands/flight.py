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
from utils.error_handling import with_error_handling
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
from utils.airport_mapper import (
    resolve_flight_airports,
    format_airport_selection_message,
    get_recommended_airport_pair,
    format_airport_info,
    MAJOR_CITIES_AIRPORTS
)

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

def get_airport_info_from_code(airport_code: str) -> Dict:
    """从机场代码获取详细信息"""
    for city, city_info in MAJOR_CITIES_AIRPORTS.items():
        for airport in city_info["airports"]:
            if airport["code"] == airport_code:
                return {
                    "code": airport_code,
                    "name": airport["name"], 
                    "name_en": airport["name_en"],
                    "city": city,
                    "note": airport.get("note", ""),
                    "primary": airport_code == city_info["primary"]
                }
    return {"code": airport_code, "name": f"{airport_code}机场", "city": "未知城市"}

def calculate_time_difference(departure_code: str, arrival_code: str) -> Dict:
    """计算两个机场之间的时差信息 - 使用time_command的动态时区计算"""
    from datetime import datetime, timedelta
    import zoneinfo
    from utils.timezone_mapper import COUNTRY_TO_TIMEZONE, resolve_timezone_with_country_data
    
    # 机场代码到国家代码的映射 
    airport_to_country = {
        # 中国
        "PEK": "CN", "PKX": "CN", "PVG": "CN", "SHA": "CN", "CAN": "CN",
        # 日本
        "NRT": "JP", "HND": "JP",
        # 韩国  
        "ICN": "KR",
        # 东南亚
        "SIN": "SG", "BKK": "TH", "DMK": "TH", "KUL": "MY",
        "CGK": "ID", "MNL": "PH", "HKG": "HK", "TPE": "TW",
        # 美国
        "LAX": "US", "SFO": "US", "JFK": "US", "LGA": "US", "EWR": "US", 
        "ORD": "US", "SEA": "US", "DFW": "US", "ATL": "US",
        # 加拿大
        "YYZ": "CA", "YVR": "CA", 
        # 欧洲
        "LHR": "GB", "CDG": "FR", "FRA": "DE", "AMS": "NL", "FCO": "IT", "MAD": "ES",
        # 澳洲
        "SYD": "AU", "MEL": "AU",
        # 中东
        "DXB": "AE", "DOH": "QA", "JED": "SA", "RUH": "SA",
        # 印度
        "DEL": "IN", "BOM": "IN",
        # 其他
        "LHE": "PK", "KHI": "PK"
    }

    def get_timezone_name(airport_code: str) -> str:
        """获取机场对应的时区名称"""
        country_code = airport_to_country.get(airport_code)
        if not country_code:
            return "UTC"
        return COUNTRY_TO_TIMEZONE.get(country_code, "UTC")
    
    def get_timezone_info(airport_code: str, timezone_name: str) -> Dict:
        """获取机场时区信息 - 使用time_command的动态计算逻辑"""
        try:
            # 使用zoneinfo获取时区（与time_command一致）
            tz = zoneinfo.ZoneInfo(timezone_name)
            now = datetime.now(tz)
            
            # 动态计算UTC偏移（考虑夏令时）
            offset_seconds = now.utcoffset().total_seconds() if now.utcoffset() else 0
            offset_hours = int(offset_seconds / 3600)
            
            # 检查是否是夏令时
            is_dst = bool(now.dst()) if now.dst() is not None else False
            
            # 生成友好的时区名称
            timezone_display_names = {
                "Asia/Shanghai": "北京时间",
                "Asia/Tokyo": "日本时间", 
                "Asia/Seoul": "韩国时间",
                "Asia/Singapore": "新加坡时间",
                "Asia/Bangkok": "泰国时间",
                "Asia/Kuala_Lumpur": "马来西亚时间",
                "Asia/Jakarta": "印度尼西亚时间",
                "Asia/Manila": "菲律宾时间",
                "Asia/Hong_Kong": "香港时间",
                "Asia/Taipei": "台北时间",
                "America/Los_Angeles": "太平洋时间",
                "America/New_York": "东部时间", 
                "America/Chicago": "中部时间",
                "America/Toronto": "东部时间",
                "America/Vancouver": "太平洋时间",
                "Europe/London": "格林威治时间",
                "Europe/Paris": "中欧时间",
                "Europe/Berlin": "中欧时间",
                "Europe/Amsterdam": "中欧时间",
                "Australia/Sydney": "澳东时间",
                "Australia/Melbourne": "澳东时间",
                "Asia/Dubai": "阿联酋时间",
                "Asia/Qatar": "卡塔尔时间",
                "Asia/Kolkata": "印度时间"
            }
            
            display_name = timezone_display_names.get(timezone_name, timezone_name.split("/")[-1] + "时间")
            
            return {
                "offset": offset_hours,
                "name": display_name,
                "timezone": timezone_name,
                "is_dst": is_dst
            }
            
        except Exception as e:
            return {"offset": 0, "name": "未知时区", "timezone": "UTC", "is_dst": False}

    # 获取两个机场的时区名称
    dep_timezone_name = get_timezone_name(departure_code)
    arr_timezone_name = get_timezone_name(arrival_code)
    
    # 获取时区信息
    dep_tz = get_timezone_info(departure_code, dep_timezone_name)
    arr_tz = get_timezone_info(arrival_code, arr_timezone_name)
    
    # 使用time_command的精确时差计算逻辑
    try:
        # 创建两个时区的datetime对象
        dep_timezone = zoneinfo.ZoneInfo(dep_timezone_name)
        arr_timezone = zoneinfo.ZoneInfo(arr_timezone_name)
        
        # 使用当前时间计算精确的UTC偏移差异
        now_dep = datetime.now(dep_timezone)
        now_arr = datetime.now(arr_timezone)
        
        dep_offset = now_dep.utcoffset() or timedelta()
        arr_offset = now_arr.utcoffset() or timedelta()
        
        # 计算时差（与time_command完全一致的算法）
        hours_difference = (arr_offset - dep_offset).total_seconds() / 3600
        
        # 格式化时差字符串（与time_command一致）
        if hours_difference.is_integer():
            time_diff_str = f"{hours_difference:+.0f}小时"
        else:
            time_diff_str = f"{hours_difference:+.1f}小时"
        
        time_diff = hours_difference
        
    except Exception:
        # 降级到简单计算
        time_diff = arr_tz["offset"] - dep_tz["offset"]
        if time_diff != 0:
            time_diff_str = f"{time_diff:+.0f}小时"
        else:
            time_diff_str = "0小时"
    
    return {
        "departure_tz": dep_tz,
        "arrival_tz": arr_tz,
        "time_difference": time_diff,
        "time_diff_str": time_diff_str if 'time_diff_str' in locals() else (f"{time_diff:+.0f}小时" if time_diff != 0 else "无时差")
    }

def get_flight_distance_info(departure_code: str, arrival_code: str) -> Dict:
    """获取航班距离和飞行时间信息"""
    # 主要航线距离数据库 (公里)
    flight_distances = {
        # 中美航线
        ("PEK", "LAX"): {"distance": 11129, "flight_time": "13小时30分", "type": "跨太平洋"},
        ("PEK", "SFO"): {"distance": 11141, "flight_time": "12小时45分", "type": "跨太平洋"},
        ("PEK", "JFK"): {"distance": 11013, "flight_time": "14小时30分", "type": "跨极地"},
        ("PVG", "LAX"): {"distance": 11666, "flight_time": "13小时15分", "type": "跨太平洋"},
        ("PVG", "SFO"): {"distance": 11577, "flight_time": "12小时30分", "type": "跨太平洋"},
        ("PVG", "JFK"): {"distance": 11836, "flight_time": "15小时", "type": "跨极地"},
        
        # 中欧航线  
        ("PEK", "LHR"): {"distance": 8147, "flight_time": "11小时30分", "type": "欧亚大陆"},
        ("PEK", "CDG"): {"distance": 8214, "flight_time": "11小时45分", "type": "欧亚大陆"},
        ("PEK", "FRA"): {"distance": 7766, "flight_time": "11小时15分", "type": "欧亚大陆"},
        ("PVG", "LHR"): {"distance": 9217, "flight_time": "12小时45分", "type": "欧亚大陆"},
        
        # 中日韩
        ("PEK", "NRT"): {"distance": 2097, "flight_time": "3小时20分", "type": "东北亚"},
        ("PEK", "ICN"): {"distance": 954, "flight_time": "2小时", "type": "东北亚"},
        ("PVG", "NRT"): {"distance": 1771, "flight_time": "3小时", "type": "东北亚"},
        ("PVG", "ICN"): {"distance": 891, "flight_time": "2小时", "type": "东北亚"},
        
        # 东南亚
        ("PEK", "SIN"): {"distance": 4473, "flight_time": "6小时30分", "type": "东南亚"},
        ("PEK", "BKK"): {"distance": 2865, "flight_time": "5小时15分", "type": "东南亚"},
        ("PVG", "SIN"): {"distance": 4128, "flight_time": "6小时", "type": "东南亚"},
        
        # 跨大西洋
        ("JFK", "LHR"): {"distance": 5585, "flight_time": "7小时", "type": "跨大西洋"},
        ("JFK", "CDG"): {"distance": 5851, "flight_time": "7小时30分", "type": "跨大西洋"},
        
        # 澳洲
        ("PEK", "SYD"): {"distance": 8998, "flight_time": "11小时30分", "type": "跨赤道"},
        ("PVG", "SYD"): {"distance": 8333, "flight_time": "10小时45分", "type": "跨赤道"},
        
        # 中东
        ("PEK", "DXB"): {"distance": 5951, "flight_time": "8小时15分", "type": "丝绸之路"},
    }
    
    # 查找距离信息（支持双向）
    distance_info = flight_distances.get((departure_code, arrival_code)) or flight_distances.get((arrival_code, departure_code))
    
    if distance_info:
        return distance_info
    
    # 默认估算（基于航线类型）
    return {"distance": 0, "flight_time": "未知", "type": "国际航线"}

def enhance_flight_route_display(api_search_data: Dict, search_params: Dict) -> str:
    """
    增强航线显示，结合API数据和本地机场信息
    """
    departure_id = search_params.get('departure_id', '')
    arrival_id = search_params.get('arrival_id', '')
    outbound_date = search_params.get('outbound_date', '')
    return_date = search_params.get('return_date', '')
    
    # 从API数据获取机场信息
    api_departure_info = {}
    api_arrival_info = {}
    
    if api_search_data:
        search_metadata = api_search_data.get('search_metadata', {})
        if search_metadata:
            api_departure_info = search_metadata.get('departure', [{}])[0] if search_metadata.get('departure') else {}
            api_arrival_info = search_metadata.get('arrival', [{}])[0] if search_metadata.get('arrival') else {}
    
    # 获取本地机场信息
    dep_local_info = get_airport_info_from_code(departure_id)
    arr_local_info = get_airport_info_from_code(arrival_id)
    
    # 合并信息 - API优先，本地补充
    dep_info = {
        "code": departure_id,
        "name": api_departure_info.get('airport', {}).get('name', dep_local_info['name']),
        "city": api_departure_info.get('city', dep_local_info['city']),
        "country": api_departure_info.get('country', ''),
        "country_code": api_departure_info.get('country_code', ''),
        "local_info": dep_local_info
    }
    
    arr_info = {
        "code": arrival_id,
        "name": api_arrival_info.get('airport', {}).get('name', arr_local_info['name']),
        "city": api_arrival_info.get('city', arr_local_info['city']),
        "country": api_arrival_info.get('country', ''),
        "country_code": api_arrival_info.get('country_code', ''),
        "local_info": arr_local_info
    }
    
    # 获取时差信息
    time_info = calculate_time_difference(departure_id, arrival_id)
    
    # 获取距离信息
    distance_info = get_flight_distance_info(departure_id, arrival_id)
    
    # 获取国家标志
    from utils.country_data import get_country_flag
    dep_flag = get_country_flag(dep_info['country_code']) if dep_info['country_code'] else ''
    arr_flag = get_country_flag(arr_info['country_code']) if arr_info['country_code'] else ''
    
    # 构建增强显示
    from telegram.helpers import escape_markdown
    
    # 安全转义所有字段
    safe_dep_city = escape_markdown(dep_info['city'], version=2)
    safe_arr_city = escape_markdown(arr_info['city'], version=2)
    safe_dep_name = escape_markdown(dep_info['name'], version=2)
    safe_arr_name = escape_markdown(arr_info['name'], version=2)
    safe_dep_country = escape_markdown(dep_info['country'], version=2)
    safe_arr_country = escape_markdown(arr_info['country'], version=2)
    # 日期不需要转义，它们是安全的格式
    trip_type = "往返" if return_date else "单程"
    
    result_parts = [
        f"🛫 *{safe_dep_city} → {safe_arr_city}* 航班搜索"
    ]
    
    if return_date:
        result_parts[0] += f" ({outbound_date} - {return_date})"
    else:
        result_parts[0] += f" ({outbound_date})"
    
    result_parts.extend([
        "",
        f"📍 *出发*: {safe_dep_name} ({departure_id})",
        f"{dep_flag} {safe_dep_country}{safe_dep_city} | 🕐 {time_info['departure_tz']['name']} (UTC{time_info['departure_tz']['offset']:+d})",
        "",
        f"📍 *到达*: {safe_arr_name} ({arrival_id})",  
        f"{arr_flag} {safe_arr_country}{safe_arr_city} | 🕐 {time_info['arrival_tz']['name']} (UTC{time_info['arrival_tz']['offset']:+d})"
    ])
    
    # 添加航线信息
    if time_info['time_difference'] != 0:
        time_diff_str = escape_markdown(time_info['time_diff_str'], version=2)
        if time_info['time_difference'] > 0:
            result_parts.append(f"⏰ *时差*: 到达地比出发地快{time_diff_str}")
        else:
            result_parts.append(f"⏰ *时差*: 到达地比出发地慢{abs(time_info['time_difference'])}小时")
    
    # 添加距离和飞行信息
    if distance_info['distance'] > 0:
        safe_flight_time = escape_markdown(distance_info['flight_time'], version=2)
        safe_route_type = escape_markdown(distance_info['type'], version=2)
        result_parts.extend([
            f"✈️ *航线信息*:",
            f"• 飞行距离: {distance_info['distance']:,}公里",
            f"• 预计飞行: {safe_flight_time}",
            f"• 航线类型: {safe_route_type}"
        ])
    
    # 添加特殊提醒
    if distance_info['type'] in ['跨太平洋', '跨极地'] and abs(time_info['time_difference']) >= 10:
        result_parts.extend([
            "",
            "💡 *长途飞行提醒*:",
            "• 建议提前调整作息时间",
            "• 到达后可能需要1-3天适应时差",
            "• 选择合适的座位和餐食"
        ])
    elif distance_info['type'] in ['东北亚', '东南亚'] and distance_info['distance'] < 3000:
        result_parts.extend([
            "",
            "💡 *短途航线*:",
            "• 适合商务出行",
            "• 当日往返可行",
            "• 通常有多个航班选择"
        ])
    
    result_parts.append("")
    
    return "\n".join(result_parts)

def add_flight_time_context(flight_data: Dict, search_params: Dict) -> str:
    """添加具体航班时间上下文信息"""
    departure_id = search_params.get('departure_id', '')
    arrival_id = search_params.get('arrival_id', '')
    outbound_date = search_params.get('outbound_date', '')
    
    # 获取时差信息
    time_info = calculate_time_difference(departure_id, arrival_id)
    
    # 如果有具体的航班数据，显示时间提醒
    best_flights = flight_data.get('best_flights', [])
    if best_flights and len(best_flights) > 0:
        first_flight = best_flights[0]
        flights = first_flight.get('flights', [])
        
        if flights and len(flights) > 0:
            departure_flight = flights[0]
            departure_time = departure_flight.get('departure_time', '')
            
            if departure_time and time_info['time_difference'] != 0:
                from telegram.helpers import escape_markdown
                # 日期不需要转义，但出发时间需要转义
                safe_dep_time = escape_markdown(departure_time, version=2)
                
                result_parts = [
                    "",
                    f"🕐 *航班时间提醒* ({outbound_date}):",
                    f"🌅 出发: {safe_dep_time} {time_info['departure_tz']['name']}"
                ]
                
                # 计算到达当地时间提醒
                if abs(time_info['time_difference']) >= 8:
                    if time_info['time_difference'] > 0:
                        result_parts.append("🌍 跨越多个时区，到达时请注意调整时间")
                    else:
                        result_parts.append("🌍 向西飞行，白天时间会延长")
                        
                return "\n".join(result_parts)
    
    return ""

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
            # 第一次调用：获取出发段航班
            response = await httpx_client.get(SERPAPI_BASE_URL, params=params)
            if response.status_code != 200:
                logger.error(f"SerpAPI request failed: {response.status_code}")
                return None
            
            data = response.json()
            
            # 如果是往返航班，需要获取返程航班
            if return_date and data:
                data = await self._get_complete_round_trip_data(data, params)
            
            return data
            
        except Exception as e:
            logger.error(f"Flight search failed: {e}")
            return None
    
    async def _get_complete_round_trip_data(self, outbound_data: Dict, original_params: Dict) -> Dict:
        """获取完整的往返航班数据（包含返程段）"""
        try:
            # 合并所有出发段航班
            all_outbound_flights = []
            if outbound_data.get('best_flights'):
                all_outbound_flights.extend(outbound_data['best_flights'])
            if outbound_data.get('other_flights'):
                all_outbound_flights.extend(outbound_data['other_flights'])
            
            # 为每个出发段航班获取对应的返程航班
            enhanced_flights = []
            
            for outbound_flight in all_outbound_flights[:10]:  # 限制处理前10个航班
                departure_token = outbound_flight.get('departure_token')
                if not departure_token:
                    # 如果没有departure_token，保持原样
                    enhanced_flights.append(outbound_flight)
                    continue
                
                # 使用departure_token获取返程航班
                return_params = original_params.copy()
                return_params.pop('outbound_date', None)
                return_params.pop('return_date', None)
                return_params['departure_token'] = departure_token
                
                return_response = await httpx_client.get(SERPAPI_BASE_URL, params=return_params)
                if return_response.status_code == 200:
                    return_data = return_response.json()
                    
                    # 合并出发段和返程段
                    combined_flight = self._combine_outbound_and_return_flights(
                        outbound_flight, return_data
                    )
                    enhanced_flights.append(combined_flight)
                else:
                    # 返程请求失败，保持原出发段航班
                    enhanced_flights.append(outbound_flight)
                
                # 避免过于频繁的API调用
                await asyncio.sleep(0.1)
            
            # 更新原数据
            result_data = outbound_data.copy()
            if enhanced_flights:
                # 根据原始分类更新数据
                best_count = len(outbound_data.get('best_flights', []))
                if best_count > 0:
                    result_data['best_flights'] = enhanced_flights[:best_count]
                    if len(enhanced_flights) > best_count:
                        result_data['other_flights'] = enhanced_flights[best_count:]
                else:
                    result_data['other_flights'] = enhanced_flights
            
            return result_data
            
        except Exception as e:
            logger.error(f"获取返程航班失败: {e}")
            return outbound_data  # 返回原始数据
    
    def _combine_outbound_and_return_flights(self, outbound_flight: Dict, return_data: Dict) -> Dict:
        """合并出发段和返程段航班信息"""
        try:
            # 获取返程段的最佳航班
            return_flights = []
            if return_data.get('best_flights'):
                return_flights = return_data['best_flights']
            elif return_data.get('other_flights'):
                return_flights = return_data['other_flights']
            
            if not return_flights:
                return outbound_flight
            
            # 取第一个返程航班作为默认选择
            return_flight = return_flights[0]
            
            # 合并航班段
            combined_flight = outbound_flight.copy()
            
            # 合并flights数组
            outbound_segments = outbound_flight.get('flights', [])
            return_segments = return_flight.get('flights', [])
            combined_flight['flights'] = outbound_segments + return_segments
            
            # 合并layovers
            outbound_layovers = outbound_flight.get('layovers', [])
            return_layovers = return_flight.get('layovers', [])
            combined_flight['layovers'] = outbound_layovers + return_layovers
            
            # 更新总时长
            outbound_duration = outbound_flight.get('total_duration', 0)
            return_duration = return_flight.get('total_duration', 0)
            combined_flight['total_duration'] = outbound_duration + return_duration
            
            # 更新价格（如果都有的话）
            outbound_price = outbound_flight.get('price', 0)
            return_price = return_flight.get('price', 0)
            if outbound_price and return_price:
                combined_flight['price'] = outbound_price + return_price
            
            # 合并碳排放
            outbound_emissions = outbound_flight.get('carbon_emissions', {})
            return_emissions = return_flight.get('carbon_emissions', {})
            if outbound_emissions and return_emissions:
                combined_emissions = {
                    'this_flight': outbound_emissions.get('this_flight', 0) + return_emissions.get('this_flight', 0),
                    'typical_for_this_route': outbound_emissions.get('typical_for_this_route', 0) + return_emissions.get('typical_for_this_route', 0)
                }
                # 重新计算差异百分比
                if combined_emissions['typical_for_this_route'] > 0:
                    combined_emissions['difference_percent'] = int(
                        (combined_emissions['this_flight'] - combined_emissions['typical_for_this_route']) / 
                        combined_emissions['typical_for_this_route'] * 100
                    )
                combined_flight['carbon_emissions'] = combined_emissions
            
            # 保持往返标记
            combined_flight['type'] = 'Round trip'
            
            return combined_flight
            
        except Exception as e:
            logger.error(f"合并航班信息失败: {e}")
            return outbound_flight
    
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
    flight_type = flight.get('type', '')  # "Round trip", "One way", etc.
    is_round_trip = flight_type == "Round trip"
    
    # 用于检测返程段开始的逻辑（改进版）
    original_departure = None
    is_return_leg = False
    return_start_index = -1
    
    if len(flights) > 1 and is_round_trip:
        # 获取原始出发地
        original_departure = flights[0].get('departure_airport', {}).get('id', '')
        
        # 寻找返程开始点：从某个航班返回到原始出发地
        for i in range(1, len(flights)):
            arrival_id = flights[i].get('arrival_airport', {}).get('id', '')
            if arrival_id == original_departure:
                # 找到返回原始出发地的航班，向前寻找返程开始点
                for j in range(i, 0, -1):
                    departure_id = flights[j].get('departure_airport', {}).get('id', '')
                    # 如果这个航班的出发地不是前一个航班的到达地（非中转），则可能是返程开始
                    if j == 1 or flights[j-1].get('arrival_airport', {}).get('id', '') != departure_id:
                        return_start_index = j
                        break
                break
    
    for i, segment in enumerate(flights):
        departure = segment.get('departure_airport', {})
        arrival = segment.get('arrival_airport', {})
        
        departure_id = departure.get('id', '')
        arrival_id = arrival.get('id', '')
        
        # 检测是否是返程段开始
        if (is_round_trip and return_start_index > 0 and i == return_start_index and not is_return_leg):
            result += "\n🔄 *返程航班*\n"
            is_return_leg = True
        elif i > 0 and not is_return_leg:
            # 普通中转
            result += "\n📍 *中转*\n"
        elif i == 0 and is_round_trip:
            # 第一段，如果是往返航班则标记为出发段
            result += "🛫 *出发航班*\n"
        
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
    
    # 航班类型信息和总结
    flight_type = flight.get('type')
    if flight_type:
        result += f"🎫 航班类型: {flight_type}\n"
        
        # 为往返航班添加详细总结
        if flight_type == "Round trip" and len(flights) > 1:
            original_departure = flights[0].get('departure_airport', {})
            final_arrival = flights[-1].get('arrival_airport', {})
            
            outbound_count = 0
            return_count = 0
            
            # 计算出发段和返程段的航班数量
            for i, segment in enumerate(flights):
                departure_id = segment.get('departure_airport', {}).get('id', '')
                arrival_id = segment.get('arrival_airport', {}).get('id', '')
                
                # 如果到达原始出发地，说明是返程段
                if arrival_id == original_departure.get('id', ''):
                    return_count += 1
                elif outbound_count == 0 or return_count == 0:
                    outbound_count += 1
            
            if outbound_count == 0:
                outbound_count = len(flights) - return_count
            
            result += f"📋 行程总结: 出发 {outbound_count} 段 + 返程 {return_count} 段\n"
            result += f"🛫 原始出发: {original_departure.get('name', original_departure.get('id', ''))}\n"
            result += f"🛬 最终返回: {final_arrival.get('name', final_arrival.get('id', ''))}\n"
    
    # 预订建议（从Telegraph版本整合）
    flights_info = flight.get('flights', [])
    if flights_info:
        airline = flights_info[0].get('airline', '')
        if airline:
            result += f"💡 预订建议: 访问 {airline} 官网预订\n"
    
    return result

def format_flight_results(flight_data: Dict, search_params: Dict) -> str:
    """格式化航班搜索结果 - 增强版显示"""
    if not flight_data:
        return "❌ 未找到航班信息"
    
    # 使用增强显示功能替换原有标题
    enhanced_header = enhance_flight_route_display(flight_data, search_params)
    
    result = enhanced_header
    
    # 添加具体航班时间上下文
    time_context = add_flight_time_context(flight_data, search_params)
    if time_context:
        result += time_context
    
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
        should_use_telegraph = len(all_flights) > 5  # 超过5个使用Telegraph
        
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
        
        # Telegraph支持长列表
        if should_use_telegraph:
            result += f"📋 *完整航班列表*: 点击查看全部 {len(all_flights)} 个选项\n"
            result += "💡 使用下方 **🎫 预订选项** 按钮查看完整列表\n\n"
        elif len(all_flights) > flights_to_show:
            result += f"📋 *还有 {len(all_flights) - flights_to_show} 个其他选项*\n"
            result += "💡 使用下方 **🎫 预订选项** 按钮查看完整列表\n\n"
        
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

async def create_flight_search_telegraph_page(all_flights: List[Dict], search_params: Dict) -> str:
    """将航班搜索结果格式化为Telegraph友好的格式 - 只显示航班信息，不含预订信息"""
    departure_id = search_params.get('departure_id', '')
    arrival_id = search_params.get('arrival_id', '')
    outbound_date = search_params.get('outbound_date', '')
    return_date = search_params.get('return_date', '')
    
    trip_type = "往返" if return_date else "单程"
    
    # 获取增强路线信息（纯文本版本）
    def get_enhanced_route_info_plain_text() -> str:
        """获取增强路线信息的纯文本版本"""
        # 获取本地机场信息
        dep_local_info = get_airport_info_from_code(departure_id)
        arr_local_info = get_airport_info_from_code(arrival_id)
        
        # 获取时差和距离信息
        time_info = calculate_time_difference(departure_id, arrival_id)
        distance_info = get_flight_distance_info(departure_id, arrival_id)
        
        # 获取国家标志（简化显示）
        from utils.country_data import get_country_flag
        dep_flag = get_country_flag('CN') if departure_id in ['PEK', 'PKX', 'PVG', 'SHA', 'CAN'] else '🌍'
        arr_flag = '🌍'  # 简化处理
        
        result_parts = [
            f"✈️ {dep_local_info['city']} → {arr_local_info['city']} 航班搜索",
            f"📅 出发: {outbound_date}" + (f" | 返回: {return_date}" if return_date else ""),
            f"🎫 类型: {trip_type}",
            "",
            f"📍 出发: {dep_local_info['name']} ({departure_id})",
            f"{dep_flag} {dep_local_info['city']} | 🕐 {time_info['departure_tz']['name']} (UTC{time_info['departure_tz']['offset']:+d})",
            "",
            f"📍 到达: {arr_local_info['name']} ({arrival_id})",  
            f"{arr_flag} {arr_local_info['city']} | 🕐 {time_info['arrival_tz']['name']} (UTC{time_info['arrival_tz']['offset']:+d})"
        ]
        
        # 添加时差信息
        if time_info['time_difference'] != 0:
            if time_info['time_difference'] > 0:
                result_parts.append(f"⏰ 时差: 到达地比出发地快{abs(time_info['time_difference'])}小时")
            else:
                result_parts.append(f"⏰ 时差: 到达地比出发地慢{abs(time_info['time_difference'])}小时")
        
        # 添加距离和飞行信息
        if distance_info['distance'] > 0:
            result_parts.extend([
                f"✈️ 航线信息:",
                f"• 飞行距离: {distance_info['distance']:,}公里",
                f"• 预计飞行: {distance_info['flight_time']}",
                f"• 航线类型: {distance_info['type']}"
            ])
        
        # 添加特殊提醒
        if distance_info['type'] in ['跨太平洋', '跨极地'] and abs(time_info['time_difference']) >= 10:
            result_parts.extend([
                "",
                "💡 长途飞行提醒:",
                "• 建议提前调整作息时间",
                "• 到达后可能需要1-3天适应时差",
                "• 选择合适的座位和餐食"
            ])
        elif distance_info['type'] in ['东北亚', '东南亚'] and distance_info['distance'] < 3000:
            result_parts.extend([
                "",
                "💡 短途航线:",
                "• 适合商务出行",
                "• 当日往返可行",
                "• 通常有多个航班选择"
            ])
        
        return "\n".join(result_parts)
    
    # 构建Telegraph页面内容
    content = get_enhanced_route_info_plain_text()
    content += f"\n\n✈️ 找到 {len(all_flights)} 个航班选项:\n\n"
    
    # 显示所有航班 - 使用format_flight_info的完整逻辑，纯文本格式
    for i, flight in enumerate(all_flights, 1):
        content += f"{i}. "
        
        # 使用format_flight_info的完整逻辑，但转换为纯文本格式
        flight_info = format_flight_info(flight)
        # 移除markdown格式并添加适当的缩进
        flight_lines = flight_info.split('\n')
        for j, line in enumerate(flight_lines):
            if j == 0:  # 第一行不需要额外缩进
                content += line + "\n"
            elif line.strip():  # 非空行添加缩进
                content += f"   {line}\n"
            else:
                content += "\n"
        
        content += "\n"
    
    content += f"""

查看选项:
• 使用 📊 价格分析 按钮查看价格趋势
• 使用 🎫 预订选项 按钮获取预订信息
• 比较不同航班的特性和价格

---
数据来源: Google Flights via SerpAPI
生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
来源: MengBot 航班服务"""
    
    return content

async def create_booking_telegraph_page(all_flights: List[Dict], search_params: Dict) -> str:
    """将航班预订选项格式化为Telegraph友好的格式 - 与主消息完全一致，包含所有预订信息"""
    departure_id = search_params.get('departure_id', '')
    arrival_id = search_params.get('arrival_id', '')
    outbound_date = search_params.get('outbound_date', '')
    return_date = search_params.get('return_date', '')
    language = "en"  # 默认语言
    
    trip_type = "往返" if return_date else "单程"
    
    # 获取增强路线信息（纯文本版本）
    def get_enhanced_route_info_plain_text() -> str:
        """获取增强路线信息的纯文本版本"""
        # 获取本地机场信息
        dep_local_info = get_airport_info_from_code(departure_id)
        arr_local_info = get_airport_info_from_code(arrival_id)
        
        # 获取时差和距离信息
        time_info = calculate_time_difference(departure_id, arrival_id)
        distance_info = get_flight_distance_info(departure_id, arrival_id)
        
        trip_type = "往返" if return_date else "单程"
        
        result_parts = [
            f"💺 {dep_local_info['city']} → {arr_local_info['city']} 航班预订",
            f"📅 出发: {outbound_date}" + (f" | 返回: {return_date}" if return_date else ""),
            f"🎫 类型: {trip_type}",
            "",
            f"📍 出发: {dep_local_info['name']} ({departure_id})",
            f"📍 到达: {arr_local_info['name']} ({arrival_id})",
        ]
        
        # 添加航线特点
        if distance_info['distance'] > 0:
            result_parts.extend([
                f"✈️ 航线: {distance_info['distance']:,}公里 | {distance_info['flight_time']} | {distance_info['type']}"
            ])
        
        # 添加时差提醒
        if time_info['time_difference'] != 0:
            if time_info['time_difference'] > 0:
                result_parts.append(f"⏰ 时差: 到达地快{abs(time_info['time_difference'])}小时")
            else:
                result_parts.append(f"⏰ 时差: 到达地慢{abs(time_info['time_difference'])}小时")
        
        return "\n".join(result_parts)
    
    # 构建Telegraph页面内容
    content = get_enhanced_route_info_plain_text()
    content += f"\n\n💺 可预订航班 (共{len(all_flights)}个选项):\n\n"
    
    # 显示所有航班 - 完全复制_show_booking_options的逻辑，包括API调用
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
        
        # 环保信息
        if 'carbon_emissions' in flight:
            emissions = flight['carbon_emissions']
            content += f"   🌱 碳排放: {emissions.get('this_flight', 0):,}g"
            if 'difference_percent' in emissions:
                diff = emissions['difference_percent']
                if diff > 0:
                    content += f" (+{diff}%)"
                elif diff < 0:
                    content += f" ({diff}%)"
            content += "\n"
        
        # 获取真实预订选项 - 完全复制主消息的逻辑
        booking_token = flight.get('booking_token')
        if booking_token:
            try:
                # 使用booking_token获取详细预订选项
                booking_options = await flight_cache_service.get_booking_options_with_cache(
                    booking_token, search_params, language=language
                )
                
                if booking_options and booking_options.get('booking_options'):
                    booking_option = booking_options['booking_options'][0]
                    
                    # 检查是否为分别预订的机票
                    separate_tickets = booking_option.get('separate_tickets', False)
                    if separate_tickets:
                        content += f"   🎫 分别预订机票\n"
                        
                        total_price = 0
                        
                        # 处理出发段预订
                        departing = booking_option.get('departing', {})
                        if departing:
                            content += f"   🛫 出发段预订:\n"
                            book_with = departing.get('book_with', '')
                            if book_with:
                                content += f"      🏢 预订商: {book_with}\n"
                            price = departing.get('price')
                            if price:
                                content += f"      💰 价格: ${price}\n"
                                total_price += price
                            # 显示出发段的预订链接
                            booking_request = departing.get('booking_request', {})
                            booking_url = booking_request.get('url', '')
                            if booking_url and 'google.com' not in booking_url:
                                content += f"      🔗 立即预订出发段: {booking_url}\n"
                            elif book_with:
                                content += f"      💡 建议访问 {book_with} 官网预订\n"
                        
                        # 处理返程段预订
                        returning = booking_option.get('returning', {})
                        if returning:
                            content += f"   🛬 返程段预订:\n"
                            book_with = returning.get('book_with', '')
                            if book_with:
                                content += f"      🏢 预订商: {book_with}\n"
                            price = returning.get('price')
                            if price:
                                content += f"      💰 价格: ${price}\n"
                                total_price += price
                            # 显示返程段的预订链接
                            booking_request = returning.get('booking_request', {})
                            booking_url = booking_request.get('url', '')
                            if booking_url and 'google.com' not in booking_url:
                                content += f"      🔗 立即预订返程段: {booking_url}\n"
                            elif book_with:
                                content += f"      💡 建议访问 {book_with} 官网预订\n"
                        
                        # 显示总价（如果有往返价格）
                        if total_price > 0:
                            content += f"   💵 往返总价: ${total_price}\n"
                    else:
                        # 一起预订的处理
                        together_option = booking_option.get('together', {})
                        
                        # 显示预订提供商
                        book_with = together_option.get('book_with', '')
                        if book_with:
                            content += f"   🏢 预订商: {book_with}\n"
                        
                        # 显示本地价格
                        local_prices = together_option.get('local_prices', [])
                        if local_prices:
                            for local_price in local_prices[:2]:
                                currency = local_price.get('currency', 'USD')
                                price_val = local_price.get('price', 0)
                                content += f"   💱 本地价格: {currency} {price_val:,}\n"
                        
                        # 显示电话服务费
                        phone_fee = together_option.get('estimated_phone_service_fee')
                        if phone_fee:
                            content += f"   📞 电话服务费: ${phone_fee}\n"
                        
                        # 显示预订建议
                        booking_request = together_option.get('booking_request', {})
                        booking_url_from_api = booking_request.get('url', '')
                        
                        if booking_url_from_api and 'google.com/travel/clk/' in booking_url_from_api:
                            book_with = together_option.get('book_with', '')
                            if book_with:
                                content += f"   💡 建议直接访问 {book_with} 官网预订\n"
                            else:
                                content += f"   💡 建议访问航空公司官网预订\n"
                        elif booking_url_from_api and 'google.com' not in booking_url_from_api:
                            content += f"   🔗 立即预订: {booking_url_from_api}\n"
                        elif together_option.get('booking_phone'):
                            phone = together_option['booking_phone']
                            content += f"   📞 预订电话: {phone}\n"
                        else:
                            content += f"   💡 建议访问航空公司官网预订\n"
                else:
                    # 如果获取详细预订选项失败，提供建议
                    content += f"   💡 建议访问航空公司官网预订\n"
                    
            except Exception as e:
                # 备用方案：提供建议
                content += f"   💡 建议访问航空公司官网预订\n"
        else:
            # 备用方案：使用Google Flights通用搜索链接
            google_flights_url = f"https://www.google.com/travel/flights?q=flights%20from%20{departure_id}%20to%20{arrival_id}"
            content += f"   🔗 在Google Flights查看: {google_flights_url}\n"
        
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
        args = context.args
        if len(args) >= 3:
            departure_input = args[0]
            arrival_input = args[1]
            outbound_date = args[2]
            return_date = args[3] if len(args) > 3 else None
            
            # 智能解析机场输入
            airport_resolution = resolve_flight_airports(departure_input, arrival_input)
            resolution_status = airport_resolution.get("status")
            
            if resolution_status == "ready":
                # 直接搜索
                dep_primary, arr_primary = get_recommended_airport_pair(
                    airport_resolution["departure"], 
                    airport_resolution["arrival"]
                )
                await _execute_flight_search(update, context, dep_primary, arr_primary, outbound_date, return_date)
                
            elif resolution_status in ["multiple_choice", "suggestion_needed"]:
                # 显示选择菜单
                selection_message = format_airport_selection_message(
                    airport_resolution["departure"], 
                    airport_resolution["arrival"]
                )
                
                # 创建快速选择按钮
                keyboard = []
                
                # 如果有推荐的机场对，提供快速选择
                dep_result = airport_resolution["departure"]
                arr_result = airport_resolution["arrival"]
                
                if (dep_result.get("status") in ["success", "multiple"] and 
                    arr_result.get("status") in ["success", "multiple"]):
                    dep_primary, arr_primary = get_recommended_airport_pair(dep_result, arr_result)
                    if dep_primary and arr_primary:
                        quick_search_data = f"flight_quick_search:{dep_primary}:{arr_primary}:{outbound_date}:{return_date or ''}"
                        short_id = get_short_flight_id(quick_search_data)
                        keyboard.append([
                            InlineKeyboardButton(f"⚡ 推荐: {dep_primary}→{arr_primary}", callback_data=f"flight_qs:{short_id}")
                        ])
                
                # 添加详细选择按钮
                airport_selection_data = f"airport_selection:{departure_input}:{arrival_input}:{outbound_date}:{return_date or ''}"
                selection_short_id = get_short_flight_id(airport_selection_data)
                keyboard.append([
                    InlineKeyboardButton("🔍 详细选择", callback_data=f"flight_as:{selection_short_id}")
                ])
                keyboard.append([
                    InlineKeyboardButton("❌ 取消", callback_data="flight_close")
                ])
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await send_message_with_auto_delete(
                    context=context,
                    chat_id=update.message.chat_id,
                    text=foldable_text_with_markdown_v2(selection_message),
                    parse_mode="MarkdownV2",
                    reply_markup=reply_markup
                )
                
            elif resolution_status == "not_found":
                error_parts = ["❌ 无法识别机场信息\n"]
                
                dep_result = airport_resolution["departure"]
                arr_result = airport_resolution["arrival"]
                
                if dep_result.get("status") == "not_found":
                    dep_input = dep_result.get("input", departure_input)
                    error_parts.append(f"• 出发地 '{dep_input}' 无法识别")
                
                if arr_result.get("status") == "not_found":
                    arr_input = arr_result.get("input", arrival_input)
                    error_parts.append(f"• 到达地 '{arr_input}' 无法识别")
                
                error_parts.extend([
                    "\n💡 *支持格式*:",
                    "• 城市名: `北京`, `东京`, `纽约`",
                    "• IATA代码: `PEK`, `NRT`, `JFK`",
                    "• 英文城市: `Beijing`, `Tokyo`, `New York`",
                    "\n📋 *使用示例*:",
                    "• `/flight 北京 东京 2024-12-25`",
                    "• `/flight PEK NRT 2024-12-25 2024-12-30`",
                    "• `/flight Shanghai New York 2024-12-25`"
                ])
                
                await send_error(context, update.message.chat_id, "\n".join(error_parts))
            
        else:
            await send_error(context, update.message.chat_id, 
                           "❌ 参数不足\n\n格式: `/flight 出发地 到达地 出发日期 [返回日期]`\n\n"
                           "🌟 *智能输入支持*:\n"
                           "• 城市名: `/flight 北京 东京 2024-12-25`\n"
                           "• 机场代码: `/flight PEK NRT 2024-12-25`\n"
                           "• 中英混合: `/flight 上海 New York 2024-12-25`")
        
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
            InlineKeyboardButton("🛬 机场信息", callback_data="flight_airport_info"),
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
• 智能机场识别

💡 智能搜索 (支持中文城市名):
`/flight 北京 洛杉矶 2024-12-25` - 智能识别机场
`/flight 上海 纽约 2024-12-25 2024-12-30` - 自动推荐最佳机场
`/flight PEK LAX 2024-12-25` - 传统机场代码

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
    # 检测用户语言 - 安全获取用户信息
    user_locale = None
    if hasattr(update, 'effective_user') and update.effective_user:
        user_locale = update.effective_user.language_code
    elif callback_query and hasattr(callback_query, 'from_user') and callback_query.from_user:
        user_locale = callback_query.from_user.language_code
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
            
            # 检查是否需要Telegraph支持
            best_flights = flight_data.get('best_flights', [])
            other_flights = flight_data.get('other_flights', [])
            all_flights = best_flights + other_flights
            
            if len(all_flights) > 5:
                # 创建Telegraph页面显示完整航班列表
                search_title = f"航班搜索: {departure_id} → {arrival_id}"
                telegraph_content = await create_flight_search_telegraph_page(all_flights, search_params)
                telegraph_url = await create_telegraph_page(search_title, telegraph_content)
                
                if telegraph_url:
                    # 替换结果文本中的提示为Telegraph链接
                    result_text = result_text.replace(
                        f"📋 *完整航班列表*: 点击查看全部 {len(all_flights)} 个选项\n💡 使用下方 **🎫 预订选项** 按钮查看完整列表",
                        f"📋 *完整航班列表*: [查看全部 {len(all_flights)} 个选项]({telegraph_url})"
                    )
            
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
            
            # 检查消息长度限制（Telegram限制为4096字符）
            formatted_text = foldable_text_with_markdown_v2(result_text)
            if len(formatted_text) > 4000:  # 留一些安全边距
                # 如果消息过长，创建简化版本
                simplified_text = result_text.split("📋 *其他选择*:")[0]  # 只保留推荐航班部分
                if "📋 *完整航班列表*:" in simplified_text:
                    # 保留Telegraph链接
                    parts = simplified_text.split("📋 *完整航班列表*:")
                    if len(parts) > 1:
                        simplified_text = parts[0] + "📋 *完整航班列表*:" + parts[1]
                else:
                    simplified_text += f"\n\n📋 *查看更多选项*: 使用下方按钮查看完整航班列表"
                
                formatted_text = foldable_text_with_markdown_v2(simplified_text)
            
            if callback_query:
                await callback_query.edit_message_text(
                    text=formatted_text,
                    parse_mode="MarkdownV2",
                    reply_markup=reply_markup
                )
            else:
                await message.edit_text(
                    text=formatted_text,
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
            
        elif action == "airport_info" and waiting_for == "airport_query":
            # 处理机场信息查询
            await _execute_airport_query(update, context, text)
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
    
    departure_input = parts[0]
    arrival_input = parts[1]
    outbound_date = parts[2]
    return_date = parts[3] if len(parts) > 3 else None
    
    # 日期格式验证
    try:
        datetime.strptime(outbound_date, '%Y-%m-%d')
        if return_date:
            datetime.strptime(return_date, '%Y-%m-%d')
    except ValueError:
        await send_error(context, update.message.chat_id, 
                        "❌ 日期格式错误\n\n请使用 YYYY-MM-DD 格式\n例如: 2024-12-25")
        return
    
    # 智能解析机场输入
    airport_resolution = resolve_flight_airports(departure_input, arrival_input)
    resolution_status = airport_resolution.get("status")
    
    if resolution_status == "ready":
        # 直接搜索
        dep_primary, arr_primary = get_recommended_airport_pair(
            airport_resolution["departure"], 
            airport_resolution["arrival"]
        )
        await _execute_flight_search(update, context, dep_primary, arr_primary, outbound_date, return_date)
        
    elif resolution_status in ["multiple_choice", "suggestion_needed"]:
        # 显示选择信息但提供自动搜索推荐选项
        selection_message = format_airport_selection_message(
            airport_resolution["departure"], 
            airport_resolution["arrival"]
        )
        
        dep_result = airport_resolution["departure"]
        arr_result = airport_resolution["arrival"]
        
        # 如果可以推荐，提供快速搜索并显示选择信息
        if (dep_result.get("status") in ["success", "multiple"] and 
            arr_result.get("status") in ["success", "multiple"]):
            dep_primary, arr_primary = get_recommended_airport_pair(dep_result, arr_result)
            if dep_primary and arr_primary:
                selection_message += f"\n⚡ *自动选择推荐*: {dep_primary} → {arr_primary}"
                
                # 先发送选择信息
                info_message = await context.bot.send_message(
                    chat_id=update.message.chat_id,
                    text=foldable_text_with_markdown_v2(selection_message),
                    parse_mode="MarkdownV2"
                )
                
                config = get_config()
                await _schedule_auto_delete(context, info_message.chat_id, info_message.message_id, 10)
                
                # 然后执行搜索
                await _execute_flight_search(update, context, dep_primary, arr_primary, outbound_date, return_date)
                return
        
        # 如果无法自动推荐，显示错误和建议
        selection_message += "\n\n❌ 无法自动选择机场，请明确指定\n"
        await send_error(context, update.message.chat_id, selection_message)
        
    else:
        # 无法识别
        await send_error(context, update.message.chat_id, 
                        f"❌ 无法识别机场: {departure_input}, {arrival_input}\n\n"
                        "请使用:\n"
                        "• 标准IATA代码: `PEK LAX`\n"  
                        "• 中文城市名: `北京 洛杉矶`\n"
                        "• 英文城市名: `Beijing Los Angeles`")

async def _execute_airport_query(update: Update, context: ContextTypes.DEFAULT_TYPE, query_text: str) -> None:
    """执行机场信息查询"""
    from telegram.helpers import escape_markdown
    from utils.airport_mapper import resolve_airport_codes
    
    # 检查是否是机场代码
    if len(query_text) == 3 and query_text.isupper() and query_text.isalpha():
        # 直接查询机场代码
        airport_info = format_airport_info(query_text)
        
        keyboard = [
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = await context.bot.send_message(
            chat_id=update.message.chat_id,
            text=foldable_text_with_markdown_v2(airport_info),
            parse_mode="MarkdownV2",
            reply_markup=reply_markup
        )
        
        # 调度自动删除
        config = get_config()
        await _schedule_auto_delete(context, message.chat_id, message.message_id, 
                                  getattr(config, 'auto_delete_delay', 600))
        
    else:
        # 查询城市的机场
        result = resolve_airport_codes(query_text)
        
        if result.get("status") == "success":
            airport_info = format_airport_info(result["primary"])
            
            keyboard = [
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message = await context.bot.send_message(
                chat_id=update.message.chat_id,
                text=foldable_text_with_markdown_v2(airport_info),
                parse_mode="MarkdownV2",
                reply_markup=reply_markup
            )
            
        elif result.get("status") == "multiple":
            # 多个机场，显示列表
            city = result.get("city", query_text)
            airports = result.get("airports", [])
            safe_city = escape_markdown(city, version=2)
            
            response_parts = [f"🛬 *{safe_city}的机场信息*\n"]
            
            for i, airport in enumerate(airports, 1):
                code = airport.get("code", "")
                name = airport.get("name", "")
                note = airport.get("note", "")
                
                safe_name = escape_markdown(name, version=2)
                safe_note = escape_markdown(note, version=2)
                
                response_parts.append(f"{i}. *{code}* - {safe_name}")
                if note:
                    response_parts.append(f"   💡 {safe_note}")
                response_parts.append("")
            
            # 添加快速航班搜索按钮
            keyboard = []
            if len(airports) <= 3:  # 如果机场不多，提供快速搜索按钮
                for airport in airports[:2]:  # 最多显示前2个
                    code = airport.get("code", "")
                    keyboard.append([
                        InlineKeyboardButton(f"✈️ 从{code}出发搜索航班", callback_data=f"flight_search_from:{code}")
                    ])
            
            keyboard.append([InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message = await context.bot.send_message(
                chat_id=update.message.chat_id,
                text=foldable_text_with_markdown_v2("\n".join(response_parts)),
                parse_mode="MarkdownV2",
                reply_markup=reply_markup
            )
            
        elif result.get("status") == "suggestion_needed":
            # 显示建议
            city = result.get("city", query_text)
            suggestions = result.get("suggestions", [])
            safe_city = escape_markdown(city, version=2)
            
            response_parts = [
                f"❓ *{safe_city}* 暂无国际机场\n",
                "🔍 *建议方案*:"
            ]
            
            for suggestion in suggestions:
                airport = suggestion.get("airport", "")
                airport_city = suggestion.get("city", "")
                transport = suggestion.get("transport", "")
                note = suggestion.get("note", "")
                
                safe_airport_city = escape_markdown(airport_city, version=2)
                safe_transport = escape_markdown(transport, version=2)
                
                note_icon = "⭐" if note == "推荐" else "🚄"
                response_parts.append(f"{note_icon} *{airport}* - {safe_airport_city}")
                response_parts.append(f"   🚅 {safe_transport}")
            
            keyboard = [
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message = await context.bot.send_message(
                chat_id=update.message.chat_id,
                text=foldable_text_with_markdown_v2("\n".join(response_parts)),
                parse_mode="MarkdownV2",
                reply_markup=reply_markup
            )
            
        else:
            # 未找到
            safe_query = escape_markdown(query_text, version=2)
            error_message = f"❌ 未找到 '{safe_query}' 的机场信息\n\n请检查输入格式或尝试使用其他关键词"
            
            keyboard = [
                [InlineKeyboardButton("🔄 重新查询", callback_data="flight_airport_info")],
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message = await context.bot.send_message(
                chat_id=update.message.chat_id,
                text=foldable_text_with_markdown_v2(error_message),
                parse_mode="MarkdownV2",
                reply_markup=reply_markup
            )
        
        # 调度自动删除
        config = get_config()
        await _schedule_auto_delete(context, message.chat_id, message.message_id, 
                                  getattr(config, 'auto_delete_delay', 600))

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

@with_error_handling
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
                InlineKeyboardButton("🛬 机场信息", callback_data="flight_airport_info"),
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

格式: `出发地 到达地 出发日期 [返回日期]`

🌟 智能输入支持:
• 城市名: `北京 洛杉矶 2024-12-25`
• 机场代码: `PEK LAX 2024-12-25 2024-12-30`
• 中英混合: `上海 New York 2024-12-25`"""

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
    
    elif data == "flight_airport_info":
        user_id = update.effective_user.id
        
        # 设置会话状态
        flight_session_manager.set_session(user_id, {
            "action": "airport_info",
            "waiting_for": "airport_query"
        })
        
        airport_help_text = """🛬 *机场信息查询*

请输入要查询的机场或城市:

🌟 *支持格式*:
• 机场代码: `PEK`, `LAX`, `NRT`
• 中文城市: `北京`, `上海`, `东京`
• 英文城市: `Beijing`, `New York`, `Tokyo`

💡 *示例*:
• `PVG` - 查询浦东机场详细信息
• `上海` - 查询上海的所有机场
• `New York` - 查询纽约地区机场"""

        await query.edit_message_text(
            text=foldable_text_with_markdown_v2(airport_help_text),
            reply_markup=InlineKeyboardMarkup([
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
    
    elif data.startswith("flight_qs:"):
        # 处理快速搜索 (quick search) 
        short_id = data.split(":", 1)[1]
        full_data = get_full_flight_id(short_id)
        
        if not full_data:
            await query.edit_message_text("❌ 链接已过期，请重新输入")
            config = get_config()
            await _schedule_auto_delete(context, query.message.chat_id, query.message.message_id, 5)
            return
        
        if full_data.startswith("flight_quick_search:"):
            search_data = full_data.replace("flight_quick_search:", "")
            parts = search_data.split(":")
            if len(parts) >= 4:
                departure_id, arrival_id, outbound_date = parts[0], parts[1], parts[2]
                return_date = parts[3] if parts[3] else None
                
                await _execute_flight_search(update, context, departure_id, arrival_id, outbound_date, return_date, query)
    
    elif data.startswith("flight_as:"):
        # 处理机场选择 (airport selection) - 详细交互选择UI
        short_id = data.split(":", 1)[1]
        full_data = get_full_flight_id(short_id)
        
        if not full_data:
            await query.edit_message_text(
                text="❌ 选择会话已过期，请重新输入航班搜索命令",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
                ])
            )
            return
        
        # 解析数据: airport_selection:departure_input:arrival_input:outbound_date:return_date
        parts = full_data.split(":", 4)
        if len(parts) != 5:
            await query.edit_message_text(
                text="❌ 数据格式错误，请重新选择",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
                ])
            )
            return
        
        departure_input, arrival_input, outbound_date, return_date = parts[1], parts[2], parts[3], parts[4]
        return_date = return_date if return_date else None
        
        # 重新解析机场信息
        airport_resolution = resolve_flight_airports(departure_input, arrival_input)
        dep_result = airport_resolution["departure"]
        arr_result = airport_resolution["arrival"]
        
        # 构建详细选择界面
        from telegram.helpers import escape_markdown
        
        message_lines = [
            "✈️ **详细机场选择**",
            "",
            f"📅 **搜索日期**: {outbound_date}" + (f" - {return_date}" if return_date else ""),
            ""
        ]
        
        # 创建选择按钮
        keyboard = []
        
        # 出发机场选择
        if dep_result.get("status") == "multiple":
            message_lines.extend([
                f"🛫 **出发**: {departure_input}",
                "请选择出发机场:"
            ])
            
            airports = dep_result.get("airports", [])
            for airport in airports[:6]:  # 最多显示6个选项
                airport_code = airport["code"]
                airport_name = escape_markdown(airport["name"], version=2)
                note = escape_markdown(airport.get("note", ""), version=2)
                
                display_text = f"{airport_code} - {airport_name}"
                if note:
                    display_text += f" ({note})"
                
                # 创建选择按钮 - 使用临时数据格式
                selection_data = f"flight_dep_select:{airport_code}:{arrival_input}:{outbound_date}:{return_date or ''}"
                selection_short_id = get_short_flight_id(selection_data)
                keyboard.append([
                    InlineKeyboardButton(display_text, callback_data=f"flight_short:{selection_short_id}")
                ])
            
            message_lines.append("")
        
        # 到达机场选择
        if arr_result.get("status") == "multiple":
            message_lines.extend([
                f"🛬 **到达**: {arrival_input}",
                "请选择到达机场:"
            ])
            
            airports = arr_result.get("airports", [])
            for airport in airports[:6]:  # 最多显示6个选项
                airport_code = airport["code"]
                airport_name = escape_markdown(airport["name"], version=2)
                note = escape_markdown(airport.get("note", ""), version=2)
                
                display_text = f"{airport_code} - {airport_name}"
                if note:
                    display_text += f" ({note})"
                
                # 创建选择按钮
                selection_data = f"flight_arr_select:{departure_input}:{airport_code}:{outbound_date}:{return_date or ''}"
                selection_short_id = get_short_flight_id(selection_data)
                keyboard.append([
                    InlineKeyboardButton(display_text, callback_data=f"flight_short:{selection_short_id}")
                ])
        
        # 如果两个都已确定，显示组合选择
        if (dep_result.get("status") == "multiple" and arr_result.get("status") == "multiple" and
            len(dep_result.get("airports", [])) <= 3 and len(arr_result.get("airports", [])) <= 3):
            
            message_lines.extend([
                "",
                "🔄 **直接组合选择**:"
            ])
            
            # 生成常见组合
            dep_airports = dep_result.get("airports", [])[:3]
            arr_airports = arr_result.get("airports", [])[:3]
            
            for dep_airport in dep_airports:
                for arr_airport in arr_airports:
                    if dep_airport["code"] != arr_airport["code"]:  # 避免相同机场
                        combo_text = f"{dep_airport['code']} → {arr_airport['code']}"
                        search_data = f"flight_search:{dep_airport['code']}:{arr_airport['code']}:{outbound_date}:{return_date or ''}"
                        combo_short_id = get_short_flight_id(search_data)
                        keyboard.append([
                            InlineKeyboardButton(combo_text, callback_data=f"flight_short:{combo_short_id}")
                        ])
        
        # 添加返回按钮
        keyboard.append([
            InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")
        ])
        
        await query.edit_message_text(
            text=foldable_text_with_markdown_v2("\n".join(message_lines)),
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(keyboard)
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
                
        elif full_data.startswith("flight_search:"):
            # 处理直接航班搜索
            search_data = full_data.replace("flight_search:", "")
            parts = search_data.split(":")
            if len(parts) >= 4:
                departure_id, arrival_id, outbound_date = parts[0], parts[1], parts[2]
                return_date = parts[3] if parts[3] else None
                
                await _execute_flight_search(query, context, departure_id, arrival_id, outbound_date, return_date, query)
            else:
                await query.edit_message_text("❌ 搜索数据格式错误")
                
        elif full_data.startswith("flight_dep_select:"):
            # 处理出发机场选择后，显示到达机场选择界面
            select_data = full_data.replace("flight_dep_select:", "")
            parts = select_data.split(":")
            if len(parts) >= 4:
                selected_dep_code, arrival_input, outbound_date = parts[0], parts[1], parts[2]
                return_date = parts[3] if parts[3] else None
                
                # 重新解析到达机场
                from utils.airport_mapper import resolve_airport_codes
                arr_result = resolve_airport_codes(arrival_input)
                
                if arr_result.get("status") == "multiple":
                    # 显示到达机场选择界面
                    message_lines = [
                        "✈️ **机场选择 - 第2步**",
                        "",
                        f"✅ **已选出发**: {selected_dep_code}",
                        f"🛬 **请选择到达**: {arrival_input}",
                        ""
                    ]
                    
                    keyboard = []
                    airports = arr_result.get("airports", [])
                    for airport in airports[:6]:
                        airport_code = airport["code"]
                        airport_name = airport["name"]
                        note = airport.get("note", "")
                        
                        display_text = f"{airport_code} - {airport_name}"
                        if note:
                            display_text += f" ({note})"
                        
                        # 直接搜索
                        search_data = f"flight_search:{selected_dep_code}:{airport_code}:{outbound_date}:{return_date or ''}"
                        search_short_id = get_short_flight_id(search_data)
                        keyboard.append([
                            InlineKeyboardButton(display_text, callback_data=f"flight_short:{search_short_id}")
                        ])
                    
                    keyboard.append([
                        InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")
                    ])
                    
                    await query.edit_message_text(
                        text=foldable_text_with_markdown_v2("\n".join(message_lines)),
                        parse_mode="MarkdownV2",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                else:
                    # 直接搜索
                    primary_code = arr_result.get("primary", arrival_input)
                    await _execute_flight_search(query, context, selected_dep_code, primary_code, outbound_date, return_date, query)
            else:
                await query.edit_message_text("❌ 选择数据格式错误")
                
        elif full_data.startswith("flight_arr_select:"):
            # 处理到达机场选择后，显示出发机场选择界面
            select_data = full_data.replace("flight_arr_select:", "")
            parts = select_data.split(":")
            if len(parts) >= 4:
                departure_input, selected_arr_code, outbound_date = parts[0], parts[1], parts[2]
                return_date = parts[3] if parts[3] else None
                
                # 重新解析出发机场
                from utils.airport_mapper import resolve_airport_codes
                dep_result = resolve_airport_codes(departure_input)
                
                if dep_result.get("status") == "multiple":
                    # 显示出发机场选择界面
                    message_lines = [
                        "✈️ **机场选择 - 第2步**",
                        "",
                        f"🛫 **请选择出发**: {departure_input}",
                        f"✅ **已选到达**: {selected_arr_code}",
                        ""
                    ]
                    
                    keyboard = []
                    airports = dep_result.get("airports", [])
                    for airport in airports[:6]:
                        airport_code = airport["code"]
                        airport_name = airport["name"]
                        note = airport.get("note", "")
                        
                        display_text = f"{airport_code} - {airport_name}"
                        if note:
                            display_text += f" ({note})"
                        
                        # 直接搜索
                        search_data = f"flight_search:{airport_code}:{selected_arr_code}:{outbound_date}:{return_date or ''}"
                        search_short_id = get_short_flight_id(search_data)
                        keyboard.append([
                            InlineKeyboardButton(display_text, callback_data=f"flight_short:{search_short_id}")
                        ])
                    
                    keyboard.append([
                        InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")
                    ])
                    
                    await query.edit_message_text(
                        text=foldable_text_with_markdown_v2("\n".join(message_lines)),
                        parse_mode="MarkdownV2",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                else:
                    # 直接搜索
                    primary_code = dep_result.get("primary", departure_input)
                    await _execute_flight_search(query, context, primary_code, selected_arr_code, outbound_date, return_date, query)
            else:
                await query.edit_message_text("❌ 选择数据格式错误")

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
                    
                    # 环保信息
                    if 'carbon_emissions' in flight:
                        emissions = flight['carbon_emissions']
                        result_text += f"   🌱 碳排放: {emissions.get('this_flight', 0):,}g"
                        if 'difference_percent' in emissions:
                            diff = emissions['difference_percent']
                            if diff > 0:
                                result_text += f" (+{diff}%)"
                            elif diff < 0:
                                result_text += f" ({diff}%)"
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
                                    
                                    total_price = 0
                                    
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
                                            total_price += price
                                        # 显示出发段的预订链接
                                        booking_request = departing.get('booking_request', {})
                                        booking_url = booking_request.get('url', '')
                                        if booking_url and 'google.com' not in booking_url:
                                            result_text += f"      🔗 [立即预订出发段]({booking_url})\n"
                                        elif book_with:
                                            result_text += f"      💡 建议访问 {book_with} 官网预订\n"
                                    
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
                                            total_price += price
                                        # 显示返程段的预订链接
                                        booking_request = returning.get('booking_request', {})
                                        booking_url = booking_request.get('url', '')
                                        if booking_url and 'google.com' not in booking_url:
                                            result_text += f"      🔗 [立即预订返程段]({booking_url})\n"
                                        elif book_with:
                                            result_text += f"      💡 建议访问 {book_with} 官网预订\n"
                                    
                                    # 显示总价（如果有往返价格）
                                    if total_price > 0:
                                        result_text += f"   💵 *往返总价: ${total_price}*\n"
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