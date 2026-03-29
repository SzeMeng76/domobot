#!/usr/bin/env python3
"""
地图服务命令模块
提供位置搜索、导航、附近服务等功能
支持根据用户语言自动选择Google Maps或高德地图
"""

import asyncio
import json
import logging
import re
from datetime import datetime
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
from utils.map_services import MapServiceManager, AmapService
from utils.session_manager import SessionManager
from utils.error_handling import with_error_handling

logger = logging.getLogger(__name__)

# 全局变量
cache_manager = None
httpx_client = None
map_service_manager = None

# Telegraph 相关配置
TELEGRAPH_API_URL = "https://api.telegra.ph"

# 地图数据ID映射缓存
map_data_mapping = {}
mapping_counter = 0

# 价格等级映射
PRICE_LEVEL_MAP = {
    '$': '💵 便宜',
    '$$': '💵💵 中等',
    '$$$': '💵💵💵 较贵',
    '$$$$': '💵💵💵💵 很贵'
}

# 创建地图会话管理器
map_session_manager = SessionManager("MapService", max_age=1800, max_sessions=200)  # 30分钟会话

async def _schedule_auto_delete(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, delay: int):
    """调度自动删除消息"""
    try:
        if context and hasattr(context, "bot_data"):
            scheduler = context.bot_data.get("message_delete_scheduler")
            if scheduler and hasattr(scheduler, "schedule_deletion"):
                await scheduler.schedule_deletion(chat_id, message_id, delay, None)
                logger.info(f"已调度地图消息删除: chat_id={chat_id}, message_id={message_id}, delay={delay}s")
            else:
                logger.warning(f"消息删除调度器未正确初始化: scheduler={scheduler}")
        else:
            logger.warning("无法获取bot_data或context")
    except Exception as e:
        logger.error(f"调度自动删除失败: {e}")

def set_dependencies(cm, hc=None):
    """设置依赖项"""
    global cache_manager, httpx_client, map_service_manager
    cache_manager = cm
    httpx_client = hc
    
    # 初始化地图服务管理器
    config = get_config()
    map_service_manager = MapServiceManager(
        google_api_key=config.google_maps_api_key,
        amap_api_key=config.amap_api_key
    )

def get_short_map_id(data_id: str) -> str:
    """生成短ID用于callback_data"""
    global mapping_counter, map_data_mapping
    
    # 查找是否已存在映射
    for short_id, full_id in map_data_mapping.items():
        if full_id == data_id:
            return short_id
    
    # 创建新的短ID
    mapping_counter += 1
    short_id = str(mapping_counter)
    map_data_mapping[short_id] = data_id
    
    # 清理过多的映射（保持最近500个）
    if len(map_data_mapping) > 500:
        # 删除前50个旧映射
        old_keys = list(map_data_mapping.keys())[:50]
        for key in old_keys:
            del map_data_mapping[key]
    
    return short_id

def get_full_map_id(short_id: str) -> Optional[str]:
    """根据短ID获取完整数据ID"""
    return map_data_mapping.get(short_id)

class MapCacheService:
    """地图缓存服务类"""
    
    async def search_location_with_cache(self, query: str, language: str) -> Optional[Dict]:
        """带缓存的位置搜索"""
        cache_key = f"map_search_{language}_{query.lower()}"
        
        if cache_manager:
            config = get_config()
            cached_data = await cache_manager.load_cache(
                cache_key,
                max_age_seconds=config.map_cache_duration,
                subdirectory="map"
            )
            if cached_data:
                logger.info(f"使用缓存的位置搜索数据: {query}")
                return cached_data
        
        try:
            service = map_service_manager.get_service(language)
            if not service:
                return None
            
            location_data = await service.search_location(query, httpx_client)
            
            if location_data and cache_manager:
                await cache_manager.save_cache(cache_key, location_data, subdirectory="map")
                logger.info(f"已缓存位置搜索数据: {query}")
            
            return location_data
            
        except Exception as e:
            logger.error(f"位置搜索失败: {e}")
            return None
    
    async def geocode_with_cache(self, address: str, language: str) -> Optional[Dict]:
        """带缓存的地理编码"""
        cache_key = f"map_geocode_{language}_{address.lower()}"
        
        if cache_manager:
            config = get_config()
            cached_data = await cache_manager.load_cache(
                cache_key,
                max_age_seconds=config.map_geocode_cache_duration,
                subdirectory="map"
            )
            if cached_data:
                logger.info(f"使用缓存的地理编码数据: {address}")
                return cached_data
        
        try:
            service = map_service_manager.get_service(language)
            if not service:
                return None
            
            geocode_data = await service.geocode(address, httpx_client)
            
            if geocode_data and cache_manager:
                await cache_manager.save_cache(cache_key, geocode_data, subdirectory="map")
                logger.info(f"已缓存地理编码数据: {address}")
            
            return geocode_data
            
        except Exception as e:
            logger.error(f"地理编码失败: {e}")
            return None
    
    async def reverse_geocode_with_cache(self, lat: float, lng: float, language: str) -> Optional[Dict]:
        """带缓存的逆地理编码"""
        cache_key = f"map_reverse_{language}_{lat:.6f}_{lng:.6f}"
        
        if cache_manager:
            config = get_config()
            cached_data = await cache_manager.load_cache(
                cache_key,
                max_age_seconds=config.map_geocode_cache_duration,
                subdirectory="map"
            )
            if cached_data:
                logger.info(f"使用缓存的逆地理编码数据: {lat},{lng}")
                return cached_data
        
        try:
            service = map_service_manager.get_service(language)
            if not service:
                return None
            
            reverse_data = await service.reverse_geocode(lat, lng, httpx_client)
            
            if reverse_data and cache_manager:
                await cache_manager.save_cache(cache_key, reverse_data, subdirectory="map")
                logger.info(f"已缓存逆地理编码数据: {lat},{lng}")
            
            return reverse_data
            
        except Exception as e:
            logger.error(f"逆地理编码失败: {e}")
            return None
    
    async def get_directions_with_cache(self, origin: str, destination: str, mode: str, language: str) -> Optional[Dict]:
        """带缓存的路线规划"""
        cache_key = f"map_directions_{language}_{mode}_{origin.lower()}_{destination.lower()}"
        
        if cache_manager:
            config = get_config()
            cached_data = await cache_manager.load_cache(
                cache_key,
                max_age_seconds=config.map_directions_cache_duration,
                subdirectory="map"
            )
            if cached_data:
                logger.info(f"使用缓存的路线规划数据: {origin} -> {destination}")
                return cached_data
        
        try:
            service = map_service_manager.get_service(language)
            if not service:
                return None
            
            directions_data = await service.get_directions(origin, destination, mode, httpx_client)
            
            if directions_data and cache_manager:
                await cache_manager.save_cache(cache_key, directions_data, subdirectory="map")
                logger.info(f"已缓存路线规划数据: {origin} -> {destination}")
            
            return directions_data
            
        except Exception as e:
            logger.error(f"路线规划失败: {e}")
            return None
    
    async def search_nearby_with_cache(self, lat: float, lng: float, place_type: str, language: str, radius: int = 1000) -> List[Dict]:
        """带缓存的附近搜索"""
        cache_key = f"map_nearby_{language}_{place_type}_{lat:.6f}_{lng:.6f}_{radius}"
        
        if cache_manager:
            config = get_config()
            cached_data = await cache_manager.load_cache(
                cache_key,
                max_age_seconds=config.map_cache_duration,
                subdirectory="map"
            )
            if cached_data:
                logger.info(f"使用缓存的附近搜索数据: {place_type} at {lat},{lng}")
                return cached_data
        
        try:
            service = map_service_manager.get_service(language)
            if not service:
                return []
            
            nearby_data = await service.search_nearby(lat, lng, place_type, radius, httpx_client)
            
            if nearby_data and cache_manager:
                await cache_manager.save_cache(cache_key, nearby_data, subdirectory="map")
                logger.info(f"已缓存附近搜索数据: {place_type} at {lat},{lng}")
            
            return nearby_data
            
        except Exception as e:
            logger.error(f"附近搜索失败: {e}")
            return []

# 创建全局地图缓存服务实例
map_cache_service = MapCacheService()

def format_place_type(place_type: str) -> str:
    """格式化地点类型名称，使其更易读"""
    # 常见类型的中英文映射
    type_mapping = {
        'shopping_mall': '购物中心',
        'point_of_interest': '兴趣点',
        'establishment': '商业场所',
        'restaurant': '餐厅',
        'food': '美食',
        'tourist_attraction': '旅游景点',
        'lodging': '住宿',
        'gas_station': '加油站',
        'hospital': '医院',
        'bank': '银行',
        'school': '学校',
        'university': '大学',
        'local_government_office': '政府机构',
        'subway_station': '地铁站',
        'bus_station': '汽车站',
        'airport': '机场',
        'train_station': '火车站',
        'parking': '停车场',
        'atm': 'ATM',
        'pharmacy': '药店',
        'supermarket': '超市',
        'convenience_store': '便利店',
        'clothing_store': '服装店',
        'electronics_store': '电子产品店',
        'book_store': '书店',
        'gym': '健身房',
        'beauty_salon': '美容院',
        'hair_care': '理发店',
        'movie_theater': '电影院',
        'night_club': '夜店',
        'bar': '酒吧',
        'cafe': '咖啡厅',
        'church': '教堂',
        'mosque': '清真寺',
        'hindu_temple': '印度教寺庙',
        'park': '公园',
        'zoo': '动物园',
        'museum': '博物馆',
        'library': '图书馆',
        'post_office': '邮局',
        'police': '警察局',
        'fire_station': '消防局',
        'car_dealer': '汽车经销商',
        'car_rental': '租车',
        'car_repair': '汽车维修',
        'furniture_store': '家具店',
        'home_goods_store': '家居用品店',
        'jewelry_store': '珠宝店',
        'shoe_store': '鞋店',
        'sports_goods_store': '体育用品店'
    }
    
    # 如果有中文映射，使用中文
    if place_type in type_mapping:
        return type_mapping[place_type]
    
    # 否则将下划线替换为空格，首字母大写
    return place_type.replace('_', ' ').title()

def format_location_info(location_data: Dict, service_type: str) -> str:
    """格式化位置信息"""
    name = location_data.get('name', 'Unknown')
    address = location_data.get('address', '')
    lat = location_data.get('lat')
    lng = location_data.get('lng')

    result = f"📍 *{name}*\n\n"
    result += f"📮 地址: {address}\n"
    result += f"🌐 坐标: `{lat:.6f}, {lng:.6f}`\n"

    # Places API (New) 新功能
    api_version = location_data.get('api_version', 'places_legacy')

    # 评分信息
    if 'rating' in location_data and location_data['rating']:
        rating = location_data['rating']
        stars = "⭐" * int(rating)
        result += f"⭐ 评分: {stars} `{rating}`"

        # 评分数量 (New API)
        if 'user_ratings_total' in location_data and location_data['user_ratings_total']:
            result += f" ({location_data['user_ratings_total']} 条评价)"
        result += "\n"

    # 价格等级 (New API)
    if 'price_level' in location_data and location_data['price_level']:
        price_text = PRICE_LEVEL_MAP.get(location_data['price_level'], location_data['price_level'])
        result += f"💰 价格: {price_text}\n"

    # 营业状态 (New API)
    if 'business_status' in location_data:
        status = location_data['business_status']
        if status == 'OPERATIONAL':
            status_text = "✅ 营业中"
        elif status == 'CLOSED_TEMPORARILY':
            status_text = "⏸️ 暂停营业"
        elif status == 'CLOSED_PERMANENTLY':
            status_text = "❌ 已关闭"
        else:
            status_text = status
        result += f"🏪 状态: {status_text}\n"

    # 营业时间 (New API)
    if 'opening_hours' in location_data and location_data['opening_hours']:
        hours = location_data['opening_hours']
        if 'open_now' in hours:
            open_status = "🟢 营业中" if hours['open_now'] else "🔴 已打烊"
            result += f"🕐 营业: {open_status}\n"

    # 电话 (New API)
    if 'phone' in location_data and location_data['phone']:
        result += f"📞 电话: {location_data['phone']}\n"

    # 网站 (New API)
    if 'website' in location_data and location_data['website']:
        result += f"🌐 网站: {location_data['website']}\n"

    # 简介 (New API)
    if 'editorial_summary' in location_data and location_data['editorial_summary']:
        summary = location_data['editorial_summary']
        if len(summary) > 100:
            summary = summary[:100] + "..."
        result += f"\n📝 简介: _{summary}_\n"

    # 类型信息
    if 'types' in location_data and location_data['types']:
        types_list = []
        for t in location_data['types'][:3]:
            formatted_type = format_place_type(t)
            types_list.append(formatted_type)
        types_str = ', '.join(types_list)
        result += f"\n🏷️ 类型: {types_str}\n"
    elif 'type' in location_data:
        formatted_type = format_place_type(str(location_data['type']))
        result += f"\n🏷️ 类型: {formatted_type}\n"

    # 城市信息 (高德地图)
    if 'cityname' in location_data:
        result += f"🏙️ 城市: {location_data['cityname']}\n"

    service_name = "Google Maps" if service_type == "google_maps" else "高德地图"
    if api_version == 'places_new':
        service_name += " (Places API New)"
    result += f"\n_数据来源: {service_name}_"
    result += f"\n_更新时间: {datetime.now().strftime('%H:%M:%S')}_"

    return result

def format_nearby_results(places: List[Dict], service_type: str, place_type: str) -> str:
    """格式化附近搜索结果"""
    if not places:
        return f"❌ 未找到附近的{place_type}服务"

    type_names = {
        'restaurant': '餐厅',
        'hospital': '医院',
        'bank': '银行',
        'gas_station': '加油站',
        'supermarket': '超市',
        'school': '学校',
        'hotel': '酒店'
    }

    type_name = type_names.get(place_type, place_type)
    result = f"📍 *附近的{type_name}*\n\n"

    for i, place in enumerate(places[:5], 1):  # 显示前5个结果，避免caption太长
        name = place['name']
        address = place.get('address', '')

        result += f"`{i:2d}.` *{name}*\n"
        if address:
            result += f"     📮 {address}\n"

        # 距离信息
        if 'distance' in place:
            distance = place['distance']
            if isinstance(distance, str):
                result += f"     📏 距离: {distance}\n"
            else:
                result += f"     📏 距离: {distance}米\n"

        # 评分信息
        if 'rating' in place and place['rating']:
            rating = place['rating']
            stars = "⭐" * int(rating)
            result += f"     ⭐ 评分: {stars} `{rating}`"

            # 评分数量 (New API)
            if 'user_ratings_total' in place and place['user_ratings_total']:
                result += f" ({place['user_ratings_total']})"
            result += "\n"

        # 价格等级 (New API)
        if 'price_level' in place and place['price_level']:
            price_text = PRICE_LEVEL_MAP.get(place['price_level'], place['price_level'])
            result += f"     💰 价格: {price_text}\n"

        # 营业状态 (New API)
        if 'is_open' in place and place['is_open'] is not None:
            open_status = "🟢 营业中" if place['is_open'] else "🔴 已打烊"
            result += f"     🕐 {open_status}\n"

        result += "\n"

    service_name = "Google Maps" if service_type == "google_maps" else "高德地图"

    # 检查是否使用新版 API
    if places and places[0].get('api_version') == 'places_new':
        service_name += " (Places API New)"

    result += f"_数据来源: {service_name}_\n"
    result += f"_更新时间: {datetime.now().strftime('%H:%M:%S')}_"

    return result

def format_directions(directions: Dict, service_type: str) -> str:
    """格式化路线规划结果"""
    distance = directions.get('distance', '未知')
    duration = directions.get('duration', '未知')
    start = directions.get('start_address', '')
    end = directions.get('end_address', '')

    result = f"🛣️ *路线规划*\n\n"
    result += f"🚩 起点: {start}\n"
    result += f"🏁 终点: {end}\n\n"

    # 检查主路线是否有toll
    main_has_tolls = False
    if 'steps' in directions and directions['steps']:
        main_has_tolls = any('Toll road' in step for step in directions['steps'])

    toll_status = " 💰" if main_has_tolls else " 🆓"
    result += f"📏 距离: `{distance}`{toll_status}\n"
    result += f"⏱️ 时间: `{duration}`\n"

    # Routes API v2 新功能
    api_version = directions.get('api_version', 'directions_v1')

    if api_version == 'routes_v2':
        # 环保路线标识
        if directions.get('is_eco_friendly'):
            result += f"🌱 环保路线: 已优化油耗\n"

        # 油耗估算
        if directions.get('fuel_consumption'):
            result += f"⛽ 预估油耗: `{directions['fuel_consumption']}`\n"

        # 过路费信息
        if directions.get('toll_info'):
            toll_info = directions['toll_info']
            if 'estimatedPrice' in toll_info:
                toll_price = toll_info['estimatedPrice']
                currency = toll_price.get('currencyCode', 'USD')
                amount = toll_price.get('units', 0)
                nanos = toll_price.get('nanos', 0)
                total = float(amount) + (float(nanos) / 1_000_000_000)
                result += f"💰 过路费: `{currency} {total:.2f}`\n"

        # 备选路线
        if directions.get('alternative_routes'):
            alt_routes = directions['alternative_routes']
            if alt_routes:
                result += f"\n🔀 *备选路线* ({len(alt_routes)} 条):\n"
                for i, alt in enumerate(alt_routes[:2], 2):  # 最多显示2条备选
                    eco_tag = " 🌱" if alt.get('is_eco_friendly') else ""
                    toll_tag = " 💰" if alt.get('has_tolls') else " 🆓"
                    result += f"`{i}.` {alt['distance']} · {alt['duration']}{eco_tag}{toll_tag}\n"

                    # 显示路线描述（主要道路）
                    if alt.get('description'):
                        desc = alt['description']
                        if len(desc) > 50:
                            desc = desc[:50] + "..."
                        result += f"   _经由: {desc}_\n"

                    # 显示过路费（如果有）
                    if alt.get('toll_info') and alt['toll_info'].get('estimatedPrice'):
                        toll_price = alt['toll_info']['estimatedPrice']
                        currency = toll_price.get('currencyCode', 'USD')
                        amount = toll_price.get('units', 0)
                        nanos = toll_price.get('nanos', 0)
                        total = float(amount) + (float(nanos) / 1_000_000_000)
                        result += f"   过路费: {currency} {total:.2f}\n"

    result += "\n"

    # 添加路线步骤 - 显示前8步，如果超过则提示使用Telegraph
    if 'steps' in directions and directions['steps']:
        result += "📋 *路线指引:*\n"
        steps_to_show = min(8, len(directions['steps']))
        for i, step in enumerate(directions['steps'][:steps_to_show], 1):
            # 清理HTML标签并添加适当的分隔
            step_clean = re.sub(r'<[^>]+>', ' ', step)  # 用空格替换HTML标签
            step_clean = re.sub(r'\s+', ' ', step_clean)  # 合并多个空格
            step_clean = step_clean.strip()  # 去除首尾空格
            result += f"`{i}.` {step_clean}\n"

        # 如果步骤超过8个，添加提示
        if len(directions['steps']) > 8:
            result += f"\n_...还有 {len(directions['steps']) - 8} 个步骤，完整路线将通过Telegraph显示_\n"

    service_name = "Google Maps" if service_type == "google_maps" else "高德地图"
    if api_version == 'routes_v2':
        service_name += " (Routes API v2)"
    result += f"\n📊 数据来源: {service_name}"
    result += f"\n🕐 更新时间: {datetime.now().strftime('%H:%M:%S')}"

    return result

async def create_telegraph_page(title: str, content: str) -> Optional[str]:
    """创建Telegraph页面用于显示长内容"""
    try:
        # 创建Telegraph账户
        account_data = {
            "short_name": "MapBot",
            "author_name": "MengBot Map Service",
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

def format_directions_for_telegraph(directions: Dict, service_type: str) -> str:
    """将路线规划格式化为Telegraph友好的格式"""
    distance = directions.get('distance', '未知')
    duration = directions.get('duration', '未知')
    start = directions.get('start_address', '')
    end = directions.get('end_address', '')

    content = f"""路线规划详情

📍 起点: {start}
📍 终点: {end}

📊 路线信息:
• 距离: {distance}
• 预计时间: {duration}
"""

    # Routes API v2 新功能
    api_version = directions.get('api_version', 'directions_v1')

    if api_version == 'routes_v2':
        # 环保路线标识
        if directions.get('is_eco_friendly'):
            content += "• 🌱 环保路线: 已优化油耗\n"

        # 燃油消耗
        if directions.get('fuel_consumption_liters'):
            fuel = directions['fuel_consumption_liters']
            content += f"• ⛽ 预计油耗: {fuel:.2f} L\n"

        # 过路费信息
        if directions.get('tolls'):
            tolls = directions['tolls']
            if tolls.get('estimatedPrice'):
                price = tolls['estimatedPrice']
                currency = price.get('currencyCode', 'USD')
                amount = price.get('units', 0)
                nanos = price.get('nanos', 0)
                total = amount + nanos / 1_000_000_000
                content += f"• 💰 过路费: {total:.2f} {currency}\n"

        content += f"\n_使用 Routes API v2_\n"

    content += "\n🛣️ 主路线详细指引:\n"

    # 添加主路线所有步骤
    if 'steps' in directions and directions['steps']:
        for i, step in enumerate(directions['steps'], 1):
            # 清理HTML标签
            step_clean = re.sub(r'<[^>]+>', ' ', step)
            step_clean = re.sub(r'\s+', ' ', step_clean)
            step_clean = step_clean.strip()

            # 如果包含 "Toll road"，添加收费标记
            if 'Toll road' in step_clean:
                step_clean = step_clean.replace('Toll road', '💰 收费路段')

            content += f"{i}. {step_clean}\n\n"
    else:
        content += "暂无详细指引信息\n\n"

    # 添加备选路线
    if directions.get('alternative_routes'):
        alt_routes = directions['alternative_routes']
        for route_num, alt in enumerate(alt_routes, 2):
            toll_tag = " 💰 有收费" if alt.get('has_tolls') else " 🆓 无收费"
            eco_tag = " 🌱 环保" if alt.get('is_eco_friendly') else ""

            content += f"\n{'='*60}\n"
            content += f"🔀 备选路线 {route_num}: {alt['distance']} · {alt['duration']}{toll_tag}{eco_tag}\n"

            if alt.get('description'):
                content += f"经由: {alt['description']}\n"

            if alt.get('toll_info') and alt['toll_info'].get('estimatedPrice'):
                toll_price = alt['toll_info']['estimatedPrice']
                currency = toll_price.get('currencyCode', 'USD')
                amount = toll_price.get('units', 0)
                nanos = toll_price.get('nanos', 0)
                total = amount + nanos / 1_000_000_000
                content += f"过路费: {total:.2f} {currency}\n"

            content += f"\n详细指引:\n"

            # 添加备选路线的步骤
            if alt.get('steps'):
                for i, step in enumerate(alt['steps'], 1):
                    # 清理HTML标签
                    step_clean = re.sub(r'<[^>]+>', ' ', step)
                    step_clean = re.sub(r'\s+', ' ', step_clean)
                    step_clean = step_clean.strip()

                    # 如果包含 "Toll road"，添加收费标记
                    if 'Toll road' in step_clean:
                        step_clean = step_clean.replace('Toll road', '💰 收费路段')

                    content += f"{i}. {step_clean}\n\n"
            else:
                content += "暂无详细指引信息\n\n"

    service_name = "Google Maps" if service_type == "google_maps" else "高德地图"
    content += f"""
---
数据来源: {service_name}
生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
来源: MengBot 地图服务"""

    return content

async def map_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """地图服务主命令 /map"""
    if not update.message:
        return
        
    # 检查是否配置了地图API
    config = get_config()
    if not config.google_maps_api_key and not config.amap_api_key:
        await send_error(
            context, 
            update.message.chat_id,
            "❌ 地图服务未配置API密钥，请联系管理员"
        )
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        return
    
    # 如果有参数，检测是位置搜索还是路线规划
    if context.args:
        query = " ".join(context.args)

        # 检测是否是路线规划（包含 "to" 或 "到"）
        if ' to ' in query.lower() or ' 到 ' in query:
            # 路线规划: "起点 to 终点" 或 "起点 到 终点"
            if ' to ' in query.lower():
                parts = query.lower().split(' to ', 1)
                origin = query[:len(parts[0])].strip()
                destination = query[len(parts[0])+4:].strip()
            else:
                parts = query.split(' 到 ', 1)
                origin = parts[0].strip()
                destination = parts[1].strip()

            if origin and destination:
                await _execute_route_planning(update, context, origin, destination)
            else:
                await send_error(
                    context,
                    update.message.chat_id,
                    "❌ 路线规划格式错误\n\n请使用格式: `/map 起点 to 终点` 或 `/map 起点 到 终点`\n\n例如: `/map 北京站 到 天安门`"
                )
        else:
            # 位置搜索
            await _execute_location_search(update, context, query)

        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        return
    
    # 没有参数，显示主菜单
    keyboard = [
        [
            InlineKeyboardButton("🔍 搜索位置", callback_data="map_search"),
            InlineKeyboardButton("📍 附近服务", callback_data="map_nearby")
        ],
        [
            InlineKeyboardButton("🗺️ 地理编码", callback_data="map_geocode"),
            InlineKeyboardButton("🛣️ 路线规划", callback_data="map_directions")
        ],
        [
            InlineKeyboardButton("❌ 关闭", callback_data="map_close")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    help_text = """🗺️ 智能地图服务

🌍 功能介绍:
• **搜索位置**: 查找地点并获取详细信息
• **附近服务**: 查找附近的餐厅、医院等
• **地理编码**: 地址与坐标转换
• **路线规划**: 获取出行路线和导航

🤖 智能特性:
• 自动语言检测
• 中文用户 → 高德地图
• 英文用户 → Google Maps

💡 快速使用:
`/map 北京天安门` - 搜索天安门
`/map Eiffel Tower` - 搜索埃菲尔铁塔

请选择功能:"""
    
    await send_message_with_auto_delete(
        context=context,
        chat_id=update.message.chat_id,
        text=foldable_text_with_markdown_v2(help_text),
        parse_mode="MarkdownV2",
        reply_markup=reply_markup
    )
    
    await delete_user_command(context, update.message.chat_id, update.message.message_id)

async def _execute_nearby_search(update: Update, context: ContextTypes.DEFAULT_TYPE, lat: float, lng: float, place_type: str, callback_query: CallbackQuery = None, language: str = None) -> None:
    """执行附近服务搜索"""
    # 如果没有传递语言参数，则进行检测
    if language is None:
        user_locale = update.effective_user.language_code if update.effective_user else None
        language = detect_user_language("", user_locale)  # 用空字符串，主要依赖locale检测
    
    type_names = {
        'restaurant': '餐厅',
        'hospital': '医院',
        'bank': '银行',
        'gas_station': '加油站',
        'supermarket': '超市',
        'school': '学校',
        'hotel': '酒店'
    }
    type_name = type_names.get(place_type, place_type)
    loading_message = f"🔍 正在搜索附近的{type_name}... ⏳"

    if callback_query:
        await _safe_edit_message(
            callback_query,
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
        service_type = "amap" if language == "zh" else "google_maps"

        # 使用缓存服务搜索附近
        nearby_places = await map_cache_service.search_nearby_with_cache(lat, lng, place_type, language, 1000)

        if nearby_places:
            # 找到附近服务
            result_text = format_nearby_results(nearby_places, service_type, place_type)

            keyboard = [
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="map_main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            if callback_query:
                # callback_query 不能发送照片
                await _safe_edit_message(
                    callback_query,
                    text=foldable_text_with_markdown_v2(result_text),
                    parse_mode="MarkdownV2",
                    reply_markup=reply_markup
                )
            else:
                # 删除 loading 消息
                await message.delete()

                # 收集有照片的地点
                places_with_photos = [p for p in nearby_places if p.get('photos') and len(p['photos']) > 0]

                # 如果有照片，先发送照片组（最多10张）
                if places_with_photos:
                    from telegram import InputMediaPhoto

                    media_group = []
                    for i, place in enumerate(places_with_photos[:10], 1):  # Telegram 限制最多10张
                        photo_url = place['photos'][0]
                        # 第一张照片带简短说明
                        if i == 1:
                            caption = f"{i}. {place['name']}"
                            if place.get('rating'):
                                caption += f" - {place['rating']}★"
                        else:
                            caption = f"{i}. {place['name']}"

                        media_group.append(InputMediaPhoto(media=photo_url, caption=caption))

                    try:
                        # 发送照片组
                        await context.bot.send_media_group(
                            chat_id=update.message.chat_id,
                            media=media_group
                        )
                    except Exception as e:
                        logger.warning(f"发送照片组失败: {e}")

                # 发送详细文本信息
                sent_msg = await context.bot.send_message(
                    chat_id=update.message.chat_id,
                    text=foldable_text_with_markdown_v2(result_text),
                    parse_mode="MarkdownV2",
                    reply_markup=reply_markup
                )
                config = get_config()
                await _schedule_auto_delete(context, sent_msg.chat_id, sent_msg.message_id, config.auto_delete_delay)
        else:
            # 未找到结果
            error_msg = f"❌ 未找到附近的{type_name}"
            keyboard = [
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="map_main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if callback_query:
                await _safe_edit_message(
                    callback_query,
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
        logger.error(f"附近搜索失败: {e}")
        error_msg = f"❌ 搜索失败: {str(e)}"
        keyboard = [
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="map_main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        config = get_config()
        if callback_query:
            await _safe_edit_message(callback_query, 
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

async def _execute_location_search(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str, callback_query: CallbackQuery = None) -> None:
    """执行位置搜索"""
    # 检测用户语言
    user_locale = update.effective_user.language_code if update.effective_user else None
    language = detect_user_language(query, user_locale)
    
    loading_message = f"🔍 正在搜索 {query}... ⏳"
    
    if callback_query:
        await _safe_edit_message(callback_query, 
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
        # 获取对应的地图服务
        service = map_service_manager.get_service(language)
        if not service:
            error_msg = "❌ 地图服务暂不可用"
            if callback_query:
                await _safe_edit_message(callback_query, error_msg)
                await _schedule_auto_delete(context, callback_query.message.chat_id, callback_query.message.message_id, 5)
            else:
                await message.edit_text(error_msg)
                await _schedule_auto_delete(context, message.chat_id, message.message_id, 5)
            return
        
        service_type = "amap" if language == "zh" else "google_maps"
        
        # 使用缓存服务搜索位置
        location_data = await map_cache_service.search_location_with_cache(query, language)
        
        if location_data:
            # 找到位置信息
            result_text = format_location_info(location_data, service_type)

            # 生成地图和导航链接
            lat, lng = location_data['lat'], location_data['lng']
            map_url = service.get_map_url(lat, lng)
            nav_url = service.get_navigation_url(query)

            # 创建按钮 - 使用精确坐标而不是原始查询
            lat, lng = location_data['lat'], location_data['lng']

            # 生成短ID用于callback_data
            nearby_data = f"{lat},{lng}:{language}"
            route_data = f"{lat},{lng}:{location_data['name']}:{language}"
            nearby_short_id = get_short_map_id(f"nearby_here:{nearby_data}")
            route_short_id = get_short_map_id(f"route_to_coords:{route_data}")

            keyboard = [
                [
                    InlineKeyboardButton("🗺️ 查看地图", url=map_url),
                    InlineKeyboardButton("🧭 开始导航", url=nav_url)
                ],
                [
                    InlineKeyboardButton("📍 附近服务", callback_data=f"map_short:{nearby_short_id}"),
                    InlineKeyboardButton("🛣️ 路线规划", callback_data=f"map_short:{route_short_id}")
                ],
                [
                    InlineKeyboardButton("🔙 返回主菜单", callback_data="map_main_menu")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            # 检查是否有照片
            has_photo = location_data.get('photos') and len(location_data['photos']) > 0

            if callback_query:
                # callback_query 不能发送照片，只能编辑文本
                await _safe_edit_message(callback_query, 
                    text=foldable_text_with_markdown_v2(result_text),
                    parse_mode="MarkdownV2",
                    reply_markup=reply_markup
                )
            else:
                # 删除 loading 消息
                await message.delete()

                # 如果有照片，发送照片+caption
                if has_photo:
                    photo_url = location_data['photos'][0]
                    try:
                        sent_msg = await context.bot.send_photo(
                            chat_id=update.message.chat_id,
                            photo=photo_url,
                            caption=foldable_text_with_markdown_v2(result_text),
                            parse_mode="MarkdownV2",
                            reply_markup=reply_markup
                        )
                        # 调度自动删除
                        config = get_config()
                        await _schedule_auto_delete(context, sent_msg.chat_id, sent_msg.message_id, config.auto_delete_delay)
                    except Exception as e:
                        logger.warning(f"发送照片失败，fallback 到纯文本: {e}")
                        # 照片发送失败，fallback 到纯文本
                        sent_msg = await context.bot.send_message(
                            chat_id=update.message.chat_id,
                            text=foldable_text_with_markdown_v2(result_text),
                            parse_mode="MarkdownV2",
                            reply_markup=reply_markup
                        )
                        config = get_config()
                        await _schedule_auto_delete(context, sent_msg.chat_id, sent_msg.message_id, config.auto_delete_delay)
                else:
                    # 没有照片，发送纯文本
                    sent_msg = await context.bot.send_message(
                        chat_id=update.message.chat_id,
                        text=foldable_text_with_markdown_v2(result_text),
                        parse_mode="MarkdownV2",
                        reply_markup=reply_markup
                    )
                    config = get_config()
                    await _schedule_auto_delete(context, sent_msg.chat_id, sent_msg.message_id, config.auto_delete_delay)
        else:
            # 未找到结果
            error_msg = f"❌ 未找到位置: {query}"
            keyboard = [
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="map_main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if callback_query:
                await _safe_edit_message(
                    callback_query,
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
        logger.error(f"位置搜索失败: {e}")
        error_msg = f"❌ 搜索失败: {str(e)}"
        keyboard = [
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="map_main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        config = get_config()
        if callback_query:
            await _safe_edit_message(callback_query, 
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

async def map_text_handler_core(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """地图文本处理的核心逻辑"""
    if not update.message or not update.message.text:
        return
    
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # 获取用户会话
    session_data = map_session_manager.get_session(user_id)
    if not session_data:
        logger.debug(f"MapService: 用户 {user_id} 没有活动会话")
        return
    
    logger.info(f"MapService: 用户 {user_id} 活动会话 - action: {session_data.get('action')}, waiting_for: {session_data.get('waiting_for')}, 输入: {text[:50]}")
    
    action = session_data.get("action")
    waiting_for = session_data.get("waiting_for")
    
    try:
        # 删除用户输入的命令
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        
        if action == "location_search" and waiting_for == "location":
            # 处理位置搜索
            await _execute_location_search(update, context, text)
            map_session_manager.remove_session(user_id)
            
        elif action == "route_planning" and waiting_for == "origin":
            # 处理路线规划
            destination = session_data.get("destination")
            await _execute_route_planning(update, context, text, destination)
            map_session_manager.remove_session(user_id)
            
        elif action == "route_planning_coords" and waiting_for == "origin":
            # 处理使用精确坐标的路线规划
            destination_name = session_data.get("destination_name")
            destination_coords = session_data.get("destination_coords")
            destination_language = session_data.get("destination_language", "en")
            await _execute_route_planning_with_coords(update, context, text, destination_name, destination_coords, destination_language)
            map_session_manager.remove_session(user_id)
            
        elif action == "directions" and waiting_for == "route":
            # 处理直接路线规划 (起点 到 终点格式)
            await _parse_and_execute_directions(update, context, text)
            map_session_manager.remove_session(user_id)
            
        elif action == "geocoding" and waiting_for == "address":
            # 处理地理编码
            await _execute_geocoding(update, context, text)
            map_session_manager.remove_session(user_id)
            
        elif action == "reverse_geocoding" and waiting_for == "coordinates":
            # 处理逆地理编码
            await _execute_reverse_geocoding(update, context, text)
            map_session_manager.remove_session(user_id)
            
    except Exception as e:
        logger.error(f"处理地图文本输入失败: {e}")
        await send_error(context, update.message.chat_id, f"处理失败: {str(e)}")
        map_session_manager.remove_session(user_id)
    
    # 消息已处理完成
    return

@with_error_handling
async def map_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理地图功能的文本输入 - 向后兼容的包装器"""
    await map_text_handler_core(update, context)

async def _execute_route_planning_with_coords(update: Update, context: ContextTypes.DEFAULT_TYPE, origin: str, destination_name: str, destination_coords: Tuple[float, float], destination_language: str) -> None:
    """执行使用精确坐标的路线规划"""
    dest_lat, dest_lng = destination_coords
    
    # 检测起点语言
    user_locale = update.effective_user.language_code if update.effective_user else None
    origin_language = detect_user_language(origin, user_locale)
    
    # 使用目标地点的语言作为主要语言
    primary_language = destination_language
    
    loading_message = f"🛣️ 正在规划路线: {origin} → {destination_name}... ⏳"
    
    message = await context.bot.send_message(
        chat_id=update.message.chat_id,
        text=foldable_text_v2(loading_message),
        parse_mode="MarkdownV2"
    )
    # 调度自动删除
    config = get_config()
    await _schedule_auto_delete(context, message.chat_id, message.message_id, config.auto_delete_delay)
    
    try:
        service = map_service_manager.get_service(primary_language)
        if not service:
            error_msg = "❌ 地图服务暂不可用"
            await message.edit_text(error_msg)
            await _schedule_auto_delete(context, message.chat_id, message.message_id, 5)
            return
        
        service_type = "amap" if primary_language == "zh" else "google_maps"
        
        # 先获取起点的精确坐标
        origin_data = await map_cache_service.search_location_with_cache(origin, origin_language)
        if not origin_data:
            # 如果搜索不到起点，尝试地理编码
            origin_data = await map_cache_service.geocode_with_cache(origin, origin_language)
        
        if not origin_data:
            error_msg = f"❌ 无法找到起点位置: {origin}"
            keyboard = [
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="map_main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await message.edit_text(
                text=error_msg,
                reply_markup=reply_markup
            )
            await _schedule_auto_delete(context, message.chat_id, message.message_id, config.auto_delete_delay)
            return
        
        # 使用精确坐标进行路线规划
        # 构建坐标字符串用于缓存服务
        origin_location_string = f"{origin_data['lat']},{origin_data['lng']}"
        destination_location_string = f"{dest_lat},{dest_lng}"
        
        # 使用缓存服务获取路线，但传递坐标而不是地址
        directions_data = await map_cache_service.get_directions_with_cache(
            origin_location_string, 
            destination_location_string, 
            "driving", 
            primary_language
        )
        
        # 如果缓存服务返回的数据为空，手动设置地址信息
        if directions_data:
            # 更新起点终点地址为真实地址而不是坐标
            directions_data['start_address'] = origin_data.get('address', origin)
            directions_data['end_address'] = destination_name
        
        if directions_data:
            # 检查是否需要使用Telegraph（步骤超过8个）
            steps = directions_data.get('steps', [])
            should_use_telegraph = len(steps) > 8
            
            if should_use_telegraph:
                # 创建Telegraph页面显示完整路线
                route_title = f"路线规划: {origin_data.get('address', origin)} → {destination_name}"
                telegraph_content = format_directions_for_telegraph(directions_data, service_type)
                telegraph_url = await create_telegraph_page(route_title, telegraph_content)
                
                # 生成带Telegraph链接的简短结果
                result_text = format_directions(directions_data, service_type)
                
                if telegraph_url:
                    result_text += f"\n\n🔗 **完整路线指引**: [查看详细步骤]({telegraph_url})"
                
                keyboard = [
                    [InlineKeyboardButton("🔙 返回主菜单", callback_data="map_main_menu")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await message.edit_text(
                    text=foldable_text_with_markdown_v2(result_text),
                    parse_mode="MarkdownV2",
                    reply_markup=reply_markup
                )
            else:
                # 步骤不多，直接显示
                result_text = format_directions(directions_data, service_type)
                
                keyboard = [
                    [InlineKeyboardButton("🔙 返回主菜单", callback_data="map_main_menu")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await message.edit_text(
                    text=foldable_text_with_markdown_v2(result_text),
                    parse_mode="MarkdownV2",
                    reply_markup=reply_markup
                )
        else:
            error_msg = f"""❌ *路线规划失败*

🚩 起点: {origin}
🏁 终点: {destination_name}

可能原因:
• 两地之间无可用路线
• 距离过远超出服务范围
• 路线计算服务暂时不可用

💡 建议: 尝试分段规划或选择其他交通方式"""
            
            keyboard = [
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="map_main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await message.edit_text(
                text=error_msg,
                reply_markup=reply_markup
            )
            await _schedule_auto_delete(context, message.chat_id, message.message_id, config.auto_delete_delay)
            
    except Exception as e:
        logger.error(f"坐标路线规划失败: {e}")
        error_msg = f"❌ 路线规划失败: {str(e)}"
        keyboard = [
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="map_main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        config = get_config()
        await message.edit_text(
            text=error_msg,
            reply_markup=reply_markup
        )
        await _schedule_auto_delete(context, message.chat_id, message.message_id, config.auto_delete_delay)

async def _execute_route_planning(update: Update, context: ContextTypes.DEFAULT_TYPE, origin: str, destination: str) -> None:
    # 检测用户语言
    user_locale = update.effective_user.language_code if update.effective_user else None
    language = detect_user_language(f"{origin} {destination}", user_locale)
    
    loading_message = f"🛣️ 正在规划路线: {origin} → {destination}... ⏳"
    
    message = await context.bot.send_message(
        chat_id=update.message.chat_id,
        text=foldable_text_v2(loading_message),
        parse_mode="MarkdownV2"
    )
    # 调度自动删除
    config = get_config()
    await _schedule_auto_delete(context, message.chat_id, message.message_id, config.auto_delete_delay)
    
    try:
        service_type = "amap" if language == "zh" else "google_maps"
        
        # 使用缓存服务获取路线
        directions_data = await map_cache_service.get_directions_with_cache(origin, destination, "driving", language)
        
        if directions_data:
            # 检查是否需要使用Telegraph（步骤超过8个）
            steps = directions_data.get('steps', [])
            should_use_telegraph = len(steps) > 8
            
            if should_use_telegraph:
                # 创建Telegraph页面显示完整路线
                route_title = f"路线规划: {origin} → {destination}"
                telegraph_content = format_directions_for_telegraph(directions_data, service_type)
                telegraph_url = await create_telegraph_page(route_title, telegraph_content)
                
                # 生成带Telegraph链接的简短结果
                result_text = format_directions(directions_data, service_type)
                
                if telegraph_url:
                    result_text += f"\n\n🔗 **完整路线指引**: [查看详细步骤]({telegraph_url})"
                
                keyboard = [
                    [InlineKeyboardButton("🔙 返回主菜单", callback_data="map_main_menu")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await message.edit_text(
                    text=foldable_text_with_markdown_v2(result_text),
                    parse_mode="MarkdownV2",
                    reply_markup=reply_markup
                )
            else:
                # 步骤不多，直接显示
                result_text = format_directions(directions_data, service_type)
                
                keyboard = [
                    [InlineKeyboardButton("🔙 返回主菜单", callback_data="map_main_menu")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await message.edit_text(
                    text=foldable_text_with_markdown_v2(result_text),
                    parse_mode="MarkdownV2",
                    reply_markup=reply_markup
                )
        else:
            error_msg = f"""❌ *路线规划失败*

🚩 起点: {origin}
🏁 终点: {destination}

可能原因:
• 地点名称无法识别
• 两地之间无可用路线
• 起点或终点位置不准确

💡 建议: 尝试使用更具体的地址或地标名称"""
            keyboard = [
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="map_main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await message.edit_text(
                text=error_msg,
                reply_markup=reply_markup
            )
            await _schedule_auto_delete(context, message.chat_id, message.message_id, config.auto_delete_delay)
            
    except Exception as e:
        logger.error(f"路线规划失败: {e}")
        error_msg = f"❌ 路线规划失败: {str(e)}"
        keyboard = [
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="map_main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        config = get_config()
        await message.edit_text(
            text=error_msg,
            reply_markup=reply_markup
        )
        await _schedule_auto_delete(context, message.chat_id, message.message_id, config.auto_delete_delay)

async def _parse_and_execute_directions(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """解析并执行路线规划 (起点 到 终点格式)"""
    # 解析 "起点 到 终点" 格式
    if " 到 " in text:
        parts = text.split(" 到 ", 1)
    elif " to " in text.lower():
        parts = text.lower().split(" to ", 1)
    else:
        await send_error(context, update.message.chat_id, "格式错误，请使用: 起点 到 终点")
        return
    
    if len(parts) != 2:
        await send_error(context, update.message.chat_id, "格式错误，请使用: 起点 到 终点")
        return
    
    origin = parts[0].strip()
    destination = parts[1].strip()
    
    if not origin or not destination:
        await send_error(context, update.message.chat_id, "起点和终点不能为空")
        return
    
    await _execute_route_planning(update, context, origin, destination)

async def _execute_geocoding(update: Update, context: ContextTypes.DEFAULT_TYPE, address: str) -> None:
    """执行地理编码"""
    user_locale = update.effective_user.language_code if update.effective_user else None
    language = detect_user_language(address, user_locale)
    
    loading_message = f"🗺️ 正在转换地址: {address}... ⏳"
    
    message = await context.bot.send_message(
        chat_id=update.message.chat_id,
        text=foldable_text_v2(loading_message),
        parse_mode="MarkdownV2"
    )
    # 调度自动删除
    config = get_config()
    await _schedule_auto_delete(context, message.chat_id, message.message_id, config.auto_delete_delay)
    
    try:
        service_type = "amap" if language == "zh" else "google_maps"
        
        # 使用缓存服务地理编码
        geocode_data = await map_cache_service.geocode_with_cache(address, language)
        
        if geocode_data:
            result_text = format_geocoding_result(geocode_data, service_type)
            
            keyboard = [
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="map_main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await message.edit_text(
                text=foldable_text_with_markdown_v2(result_text),
                parse_mode="MarkdownV2",
                reply_markup=reply_markup
            )
        else:
            error_msg = f"❌ 无法找到地址: {address}"
            keyboard = [
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="map_main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await message.edit_text(
                text=error_msg,
                reply_markup=reply_markup
            )
            await _schedule_auto_delete(context, message.chat_id, message.message_id, config.auto_delete_delay)
            
    except Exception as e:
        logger.error(f"地理编码失败: {e}")
        error_msg = f"❌ 地理编码失败: {str(e)}"
        keyboard = [
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="map_main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        config = get_config()
        await message.edit_text(
            text=error_msg,
            reply_markup=reply_markup
        )
        await _schedule_auto_delete(context, message.chat_id, message.message_id, config.auto_delete_delay)

async def _execute_reverse_geocoding(update: Update, context: ContextTypes.DEFAULT_TYPE, coordinates: str) -> None:
    """执行逆地理编码"""
    try:
        # 解析坐标
        coords = coordinates.replace(" ", "").split(",")
        if len(coords) != 2:
            await send_error(context, update.message.chat_id, "坐标格式错误，请使用: 纬度,经度")
            return
        
        lat, lng = float(coords[0]), float(coords[1])
        
        user_locale = update.effective_user.language_code if update.effective_user else None
        language = detect_user_language("", user_locale)
        
        loading_message = f"🌐 正在转换坐标: {lat}, {lng}... ⏳"
        
        message = await context.bot.send_message(
            chat_id=update.message.chat_id,
            text=foldable_text_v2(loading_message),
            parse_mode="MarkdownV2"
        )
        # 调度自动删除
        config = get_config()
        await _schedule_auto_delete(context, message.chat_id, message.message_id, config.auto_delete_delay)
        
        service_type = "amap" if language == "zh" else "google_maps"
        
        # 使用缓存服务逆地理编码
        reverse_data = await map_cache_service.reverse_geocode_with_cache(lat, lng, language)
        
        if reverse_data:
            result_text = format_reverse_geocoding_result(reverse_data, service_type, lat, lng)
            
            keyboard = [
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="map_main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await message.edit_text(
                text=foldable_text_with_markdown_v2(result_text),
                parse_mode="MarkdownV2",
                reply_markup=reply_markup
            )
        else:
            error_msg = f"❌ 无法转换坐标: {lat}, {lng}"
            keyboard = [
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="map_main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await message.edit_text(
                text=error_msg,
                reply_markup=reply_markup
            )
            await _schedule_auto_delete(context, message.chat_id, message.message_id, config.auto_delete_delay)
            
    except ValueError:
        await send_error(context, update.message.chat_id, "坐标格式错误，请输入有效的数字")
    except Exception as e:
        logger.error(f"逆地理编码失败: {e}")
        await send_error(context, update.message.chat_id, f"逆地理编码失败: {str(e)}")

def format_geocoding_result(geocode_data: Dict, service_type: str) -> str:
    """格式化地理编码结果"""
    address = geocode_data.get('address', '')
    lat = geocode_data.get('lat')
    lng = geocode_data.get('lng')
    
    result = f"🗺️ *地理编码结果*\n\n"
    result += f"📮 地址: {address}\n"
    result += f"🌐 坐标: `{lat:.6f}, {lng:.6f}`\n"
    
    # 添加地区信息
    if 'province' in geocode_data:
        result += f"🏛️ 省份: {geocode_data['province']}\n"
    if 'city' in geocode_data:
        result += f"🏙️ 城市: {geocode_data['city']}\n"
    if 'district' in geocode_data:
        result += f"🏙️ 区县: {geocode_data['district']}\n"
    
    service_name = "Google Maps" if service_type == "google_maps" else "高德地图"
    result += f"\n_数据来源: {service_name}_"
    result += f"\n_更新时间: {datetime.now().strftime('%H:%M:%S')}_"
    
    return result

def format_reverse_geocoding_result(reverse_data: Dict, service_type: str, lat: float, lng: float) -> str:
    """格式化逆地理编码结果"""
    address = reverse_data.get('address', '')
    
    result = f"🌐 *逆地理编码结果*\n\n"
    result += f"📍 坐标: `{lat:.6f}, {lng:.6f}`\n"
    result += f"📮 地址: {address}\n"
    
    # 添加地区信息
    if 'province' in reverse_data:
        result += f"🏛️ 省份: {reverse_data['province']}\n"
    if 'city' in reverse_data:
        result += f"🏙️ 城市: {reverse_data['city']}\n"
    if 'district' in reverse_data:
        result += f"🏙️ 区县: {reverse_data['district']}\n"
    
    service_name = "Google Maps" if service_type == "google_maps" else "高德地图"
    result += f"\n_数据来源: {service_name}_"
    result += f"\n_更新时间: {datetime.now().strftime('%H:%M:%S')}_"
    
    return result

async def _safe_edit_message(query, text, reply_markup=None, parse_mode=None):
    """安全地编辑消息，处理内容相同的情况和照片消息"""
    try:
        # 检查消息是否包含照片
        if query.message.photo:
            # 检查caption长度（Telegram限制1024字符）
            if len(text) > 1024:
                # Caption太长，删除照片改用纯文本消息
                logger.warning(f"Caption太长 ({len(text)} 字符)，删除照片改用文本消息")
                chat_id = query.message.chat_id
                await query.message.delete()
                await query.message.get_bot().send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode
                )
            else:
                # 如果是照片消息，使用 edit_message_caption
                await query.edit_message_caption(
                    caption=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode
                )
        else:
            # 如果是文本消息，使用 edit_message_text
            await query.edit_message_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
    except Exception as e:
        error_str = str(e)
        if "Message is not modified" in error_str:
            # 消息内容相同，忽略这个错误
            logger.debug(f"消息内容相同，跳过编辑: {text[:50]}...")
        elif "Message to edit not found" in error_str or "Message to be replied not found" in error_str:
            # 消息已被删除，无法编辑，忽略
            logger.warning(f"消息已被删除，无法编辑")
        elif "There is no text in the message to edit" in error_str:
            # 照片消息但尝试编辑文本，尝试用 caption
            try:
                if len(text) > 1024:
                    # Caption太长，删除照片改用纯文本消息
                    logger.warning(f"Caption太长 ({len(text)} 字符)，删除照片改用文本消息")
                    chat_id = query.message.chat_id
                    await query.message.delete()
                    await query.message.get_bot().send_message(
                        chat_id=chat_id,
                        text=text,
                        reply_markup=reply_markup,
                        parse_mode=parse_mode
                    )
                else:
                    await query.edit_message_caption(
                        caption=text,
                        reply_markup=reply_markup,
                        parse_mode=parse_mode
                    )
            except Exception as e2:
                if "Message to edit not found" in str(e2):
                    logger.warning(f"消息已被删除，无法编辑")
                else:
                    logger.error(f"编辑消息失败: {e2}")
                    raise
        elif "Media_caption_too_long" in error_str:
            # Caption太长，删除照片改用纯文本消息
            logger.warning(f"Caption太长，删除照片改用文本消息")
            try:
                chat_id = query.message.chat_id
                await query.message.delete()
                await query.message.get_bot().send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode
                )
            except Exception as e2:
                if "Message to edit not found" in str(e2):
                    logger.warning(f"消息已被删除，无法编辑")
                else:
                    logger.error(f"删除照片并发送文本失败: {e2}")
                    raise
        else:
            logger.error(f"编辑消息失败: {e}")
            raise

@with_error_handling
async def map_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理地图功能的回调查询"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "map_close":
        # 清理用户会话
        user_id = update.effective_user.id
        map_session_manager.remove_session(user_id)
        await query.delete_message()
        return
    
    elif data == "map_main_menu":
        # 清理用户会话并返回主菜单
        user_id = update.effective_user.id
        map_session_manager.remove_session(user_id)
        
        # 返回主菜单
        keyboard = [
            [
                InlineKeyboardButton("🔍 搜索位置", callback_data="map_search"),
                InlineKeyboardButton("📍 附近服务", callback_data="map_nearby")
            ],
            [
                InlineKeyboardButton("🗺️ 地理编码", callback_data="map_geocode"),
                InlineKeyboardButton("🛣️ 路线规划", callback_data="map_directions")
            ],
            [
                InlineKeyboardButton("❌ 关闭", callback_data="map_close")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        help_text = """🗺️ 智能地图服务

🌍 功能介绍:
• **搜索位置**: 查找地点并获取详细信息
• **附近服务**: 查找附近的餐厅、医院等
• **地理编码**: 地址与坐标转换
• **路线规划**: 获取出行路线和导航

🤖 智能特性:
• 自动语言检测
• 中文用户 → 高德地图
• 英文用户 → Google Maps

💡 快速使用:
`/map 北京天安门` - 搜索天安门
`/map Eiffel Tower` - 搜索埃菲尔铁塔

请选择功能:"""
        
        await _safe_edit_message(
            query,
            text=foldable_text_with_markdown_v2(help_text),
            parse_mode="MarkdownV2",
            reply_markup=reply_markup
        )
    
    elif data == "map_search":
        user_id = update.effective_user.id
        
        # 设置会话状态
        map_session_manager.set_session(user_id, {
            "action": "location_search",
            "waiting_for": "location"
        })
        
        # 位置搜索指引
        await _safe_edit_message(
            query,
            text="🔍 请输入要搜索的位置名称:\n\n例如:\n• 北京天安门\n• Eiffel Tower\n• 上海外滩\n• Times Square",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="map_main_menu")]
            ])
        )
    
    elif data == "map_nearby":
        # 附近服务选择
        keyboard = [
            [
                InlineKeyboardButton("🍽️ 餐厅", callback_data="map_nearby_type:restaurant"),
                InlineKeyboardButton("🏥 医院", callback_data="map_nearby_type:hospital")
            ],
            [
                InlineKeyboardButton("🏦 银行", callback_data="map_nearby_type:bank"),
                InlineKeyboardButton("⛽ 加油站", callback_data="map_nearby_type:gas_station")
            ],
            [
                InlineKeyboardButton("🛒 超市", callback_data="map_nearby_type:supermarket"),
                InlineKeyboardButton("🏫 学校", callback_data="map_nearby_type:school")
            ],
            [
                InlineKeyboardButton("🏨 酒店", callback_data="map_nearby_type:hotel")
            ],
            [
                InlineKeyboardButton("🔙 返回主菜单", callback_data="map_main_menu")
            ]
        ]
        
        await _safe_edit_message(
            query,
            text="📍 请选择要搜索的服务类型:\n\n注意: 需要先提供你的位置信息",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif data.startswith("map_nearby_type:"):
        place_type = data.split(":", 1)[1]
        type_names = {
            'restaurant': '餐厅',
            'hospital': '医院', 
            'bank': '银行',
            'gas_station': '加油站',
            'supermarket': '超市',
            'school': '学校',
            'hotel': '酒店'
        }
        type_name = type_names.get(place_type, place_type)

        await _safe_edit_message(
            query,
            text=f"📍 请发送你的位置信息或输入地址\n\n将为你搜索附近的{type_name}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="map_main_menu")]
            ])
        )
    
    elif data.startswith("map_nearby_here:"):
        parts = data.split(":", 2)
        coords = parts[1]
        language = parts[2] if len(parts) > 2 else "en"  # 默认英文
        lat, lng = map(float, coords.split(","))
        
        # 显示附近服务类型选择
        keyboard = [
            [
                InlineKeyboardButton("🍽️ 餐厅", callback_data=f"map_search_nearby:{lat},{lng}:restaurant:{language}"),
                InlineKeyboardButton("🏥 医院", callback_data=f"map_search_nearby:{lat},{lng}:hospital:{language}")
            ],
            [
                InlineKeyboardButton("🏦 银行", callback_data=f"map_search_nearby:{lat},{lng}:bank:{language}"),
                InlineKeyboardButton("⛽ 加油站", callback_data=f"map_search_nearby:{lat},{lng}:gas_station:{language}")
            ],
            [
                InlineKeyboardButton("🛒 超市", callback_data=f"map_search_nearby:{lat},{lng}:supermarket:{language}"),
                InlineKeyboardButton("🏫 学校", callback_data=f"map_search_nearby:{lat},{lng}:school:{language}")
            ],
            [
                InlineKeyboardButton("🏨 酒店", callback_data=f"map_search_nearby:{lat},{lng}:hotel:{language}")
            ],
            [
                InlineKeyboardButton("🔙 返回主菜单", callback_data="map_main_menu")
            ]
        ]
        
        await _safe_edit_message(
            query,
            text=f"📍 请选择要搜索的服务类型:\n\n位置: {lat:.6f}, {lng:.6f}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif data.startswith("map_search_nearby:"):
        parts = data.split(":", 3)
        coords = parts[1]
        place_type = parts[2]
        language = parts[3] if len(parts) > 3 else "en"  # 默认英文
        lat, lng = map(float, coords.split(","))
        
        # 执行附近搜索
        await _execute_nearby_search(update, context, lat, lng, place_type, query, language)
    
    elif data.startswith("map_short:"):
        # 处理短ID映射的callback
        short_id = data.split(":", 1)[1]
        full_data = get_full_map_id(short_id)

        if not full_data:
            await _safe_edit_message(query, "❌ 链接已过期，请重新搜索")
            config = get_config()
            await _schedule_auto_delete(context, query.message.chat_id, query.message.message_id, 5)
            return
        
        # 解析完整数据并转发到相应处理器
        if full_data.startswith("nearby_here:"):
            nearby_data = full_data.replace("nearby_here:", "")
            parts = nearby_data.split(":")
            coords = parts[0]
            language = parts[1] if len(parts) > 1 else "en"
            lat, lng = map(float, coords.split(","))
            
            # 显示附近服务类型选择
            keyboard = [
                [
                    InlineKeyboardButton("🍽️ 餐厅", callback_data=f"map_search_nearby:{lat},{lng}:restaurant:{language}"),
                    InlineKeyboardButton("🏥 医院", callback_data=f"map_search_nearby:{lat},{lng}:hospital:{language}")
                ],
                [
                    InlineKeyboardButton("🏦 银行", callback_data=f"map_search_nearby:{lat},{lng}:bank:{language}"),
                    InlineKeyboardButton("⛽ 加油站", callback_data=f"map_search_nearby:{lat},{lng}:gas_station:{language}")
                ],
                [
                    InlineKeyboardButton("🛒 超市", callback_data=f"map_search_nearby:{lat},{lng}:supermarket:{language}"),
                    InlineKeyboardButton("🏫 学校", callback_data=f"map_search_nearby:{lat},{lng}:school:{language}")
                ],
                [
                    InlineKeyboardButton("🏨 酒店", callback_data=f"map_search_nearby:{lat},{lng}:hotel:{language}")
                ],
                [
                    InlineKeyboardButton("🔙 返回主菜单", callback_data="map_main_menu")
                ]
            ]
            
            await _safe_edit_message(
                query,
                text=f"📍 请选择要搜索的服务类型:\n\n位置: {lat:.6f}, {lng:.6f}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
        elif full_data.startswith("route_to_coords:"):
            route_data = full_data.replace("route_to_coords:", "")
            parts = route_data.split(":", 2)
            coords = parts[0]
            destination_name = parts[1]
            language = parts[2] if len(parts) > 2 else "en"
            dest_lat, dest_lng = map(float, coords.split(","))
            
            user_id = update.effective_user.id
            
            # 设置会话状态，包含目标地点的精确坐标
            map_session_manager.set_session(user_id, {
                "action": "route_planning_coords",
                "destination_name": destination_name,
                "destination_coords": (dest_lat, dest_lng),
                "destination_language": language,
                "waiting_for": "origin"
            })
            
            await _safe_edit_message(
                query,
                text=f"🛣️ 路线规划到: {destination_name}\n\n请输入起点地址或发送位置信息",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 返回主菜单", callback_data="map_main_menu")]
                ])
            )
    
    elif data.startswith("map_route_to:"):
        destination = data.split(":", 1)[1]
        user_id = update.effective_user.id
        
        # 设置会话状态
        map_session_manager.set_session(user_id, {
            "action": "route_planning",
            "destination": destination,
            "waiting_for": "origin"
        })

        await _safe_edit_message(
            query,
            text=f"🛣️ 路线规划到: {destination}\n\n请输入起点地址或发送位置信息",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="map_main_menu")]
            ])
        )
    
    elif data.startswith("map_route_to_coords:"):
        # 新的处理方式：使用精确坐标和地点名称
        parts = data.split(":", 3)
        coords = parts[1]
        destination_name = parts[2]
        language = parts[3] if len(parts) > 3 else "en"
        dest_lat, dest_lng = map(float, coords.split(","))
        
        user_id = update.effective_user.id
        
        # 设置会话状态，包含目标地点的精确坐标
        map_session_manager.set_session(user_id, {
            "action": "route_planning_coords",
            "destination_name": destination_name,
            "destination_coords": (dest_lat, dest_lng),
            "destination_language": language,
            "waiting_for": "origin"
        })
        
        await _safe_edit_message(
            query,
            text=f"🛣️ 路线规划到: {destination_name}\n\n请输入起点地址或发送位置信息",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="map_main_menu")]
            ])
        )
    
    elif data == "map_geocode":
        # 地理编码功能
        keyboard = [
            [
                InlineKeyboardButton("📮 地址转坐标", callback_data="map_geo_forward"),
                InlineKeyboardButton("🌐 坐标转地址", callback_data="map_geo_reverse")
            ],
            [
                InlineKeyboardButton("🔙 返回主菜单", callback_data="map_main_menu")
            ]
        ]
        
        await _safe_edit_message(
            query,
            text="🗺️ 地理编码服务:\n\n• **地址转坐标**: 输入地址获取经纬度\n• **坐标转地址**: 输入坐标获取详细地址",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="MarkdownV2"
        )
    
    elif data == "map_geo_forward":
        user_id = update.effective_user.id
        
        # 设置会话状态
        map_session_manager.set_session(user_id, {
            "action": "geocoding",
            "waiting_for": "address"
        })
        
        await _safe_edit_message(
            query,
            text="📮 请输入要转换的地址:\n\n例如: 北京市天安门广场",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="map_main_menu")]
            ])
        )
    
    elif data == "map_geo_reverse":
        user_id = update.effective_user.id
        
        # 设置会话状态
        map_session_manager.set_session(user_id, {
            "action": "reverse_geocoding",
            "waiting_for": "coordinates"
        })
        
        await _safe_edit_message(
            query,
            text="🌐 请输入坐标 (格式: 纬度,经度):\n\n例如: 39.9042,116.4074",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="map_main_menu")]
            ])
        )
    
    elif data == "map_directions":
        user_id = update.effective_user.id
        
        # 设置会话状态
        map_session_manager.set_session(user_id, {
            "action": "directions",
            "waiting_for": "route"
        })
        
        await _safe_edit_message(
            query,
            text="🛣️ 路线规划:\n\n请提供起点和终点信息\n格式: 起点 到 终点\n\n例如: 北京西站 到 天安门",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="map_main_menu")]
            ])
        )

# =============================================================================
# 注册命令和回调
# =============================================================================

# 注册主命令
command_factory.register_command(
    "map",
    map_command,
    permission=Permission.USER,
    description="🗺️ 智能地图服务 - 位置搜索、导航、附近服务"
)

# 注册回调处理器
command_factory.register_callback(r"^map_", map_callback_handler, permission=Permission.USER, description="地图服务回调")

# 不注册单独的文本处理器，由统一处理器管理  
# command_factory.register_text_handler(map_text_handler, permission=Permission.USER, description="地图服务文本输入处理")