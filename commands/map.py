#!/usr/bin/env python3
"""
地图服务命令模块
提供位置搜索、导航、附近服务等功能
支持根据用户语言自动选择Google Maps或高德地图
"""

import asyncio
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

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
from utils.map_services import MapServiceManager
from utils.session_manager import SessionManager

logger = logging.getLogger(__name__)

# 全局变量
cache_manager = None
httpx_client = None
map_service_manager = None

# 地图数据ID映射缓存
map_data_mapping = {}
mapping_counter = 0

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
    global mapping_counter
    mapping_counter += 1
    short_id = str(mapping_counter)
    map_data_mapping[short_id] = data_id
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
    
    # 基本信息 - 移除手动转义，让foldable_text_with_markdown_v2统一处理
    name = location_data.get('name', 'Unknown')
    address = location_data.get('address', '')
    
    result = f"📍 *{name}*\n\n"
    result += f"📮 地址: {address}\n"
    result += f"🌐 坐标: `{lat:.6f}, {lng:.6f}`\n"
    
    # 添加评分信息 (Google Maps)
    if 'rating' in location_data and location_data['rating']:
        rating = location_data['rating']
        stars = "⭐" * int(rating)
        result += f"⭐ 评分: {stars} `{rating}`\n"
    
    # 添加类型信息
    if 'types' in location_data and location_data['types']:
        # 格式化类型名称
        types_list = []
        for t in location_data['types'][:3]:
            formatted_type = format_place_type(t)
            types_list.append(formatted_type)
        types_str = ', '.join(types_list)
        result += f"🏷️ 类型: {types_str}\n"
    elif 'type' in location_data:
        # 处理单个类型
        formatted_type = format_place_type(str(location_data['type']))
        result += f"🏷️ 类型: {formatted_type}\n"
    
    # 添加城市信息 (高德地图)
    if 'cityname' in location_data:
        result += f"🏙️ 城市: {location_data['cityname']}\n"
    
    service_name = "Google Maps" if service_type == "google_maps" else "高德地图"
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
    
    for i, place in enumerate(places[:8], 1):  # 显示前8个结果
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
        
        # 评分信息 (Google Maps)
        if 'rating' in place and place['rating']:
            rating = place['rating']
            stars = "⭐" * int(rating)
            result += f"     ⭐ 评分: {stars} `{rating}`\n"
        
        result += "\n"
    
    service_name = "Google Maps" if service_type == "google_maps" else "高德地图"
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
    result += f"📏 距离: `{distance}`\n"
    result += f"⏱️ 时间: `{duration}`\n\n"
    
    # 添加路线步骤
    if 'steps' in directions and directions['steps']:
        result += "📋 *路线指引:*\n"
        for i, step in enumerate(directions['steps'][:5], 1):
            # 清理HTML标签
            step_clean = re.sub(r'<[^>]+>', '', step)
            result += f"`{i}.` {step_clean}\n"
    
    service_name = "Google Maps" if service_type == "google_maps" else "高德地图"
    result += f"\n_数据来源: {service_name}_"
    result += f"_更新时间: {datetime.now().strftime('%H:%M:%S')}_"
    
    return result

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
    
    # 如果有参数，直接搜索位置
    if context.args:
        query = " ".join(context.args)
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
            error_msg = f"❌ 未找到附近的{type_name}"
            keyboard = [
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="map_main_menu")]
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
        logger.error(f"附近搜索失败: {e}")
        error_msg = f"❌ 搜索失败: {str(e)}"
        keyboard = [
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="map_main_menu")]
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

async def _execute_location_search(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str, callback_query: CallbackQuery = None) -> None:
    """执行位置搜索"""
    # 检测用户语言
    user_locale = update.effective_user.language_code if update.effective_user else None
    language = detect_user_language(query, user_locale)
    
    loading_message = f"🔍 正在搜索 {query}... ⏳"
    
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
        # 获取对应的地图服务
        service = map_service_manager.get_service(language)
        if not service:
            error_msg = "❌ 地图服务暂不可用"
            if callback_query:
                await callback_query.edit_message_text(error_msg)
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
            
            # 创建按钮
            keyboard = [
                [
                    InlineKeyboardButton("🗺️ 查看地图", url=map_url),
                    InlineKeyboardButton("🧭 开始导航", url=nav_url)
                ],
                [
                    InlineKeyboardButton("📍 附近服务", callback_data=f"map_nearby_here:{lat},{lng}:{language}"),
                    InlineKeyboardButton("🛣️ 路线规划", callback_data=f"map_route_to:{query}")
                ],
                [
                    InlineKeyboardButton("🔙 返回主菜单", callback_data="map_main_menu")
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
            error_msg = f"❌ 未找到位置: {query}"
            keyboard = [
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="map_main_menu")]
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
        logger.error(f"位置搜索失败: {e}")
        error_msg = f"❌ 搜索失败: {str(e)}"
        keyboard = [
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="map_main_menu")]
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

async def map_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理地图功能的文本输入"""
    if not update.message or not update.message.text:
        return
    
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # 获取用户会话
    session_data = map_session_manager.get_session(user_id)
    if not session_data:
        return  # 没有活动会话，忽略
    
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

async def _execute_route_planning(update: Update, context: ContextTypes.DEFAULT_TYPE, origin: str, destination: str) -> None:
    """执行路线规划"""
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
            error_msg = f"❌ 无法规划路线: {origin} → {destination}"
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
        
        await query.edit_message_text(
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
        await query.edit_message_text(
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
        
        await query.edit_message_text(
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
        
        await query.edit_message_text(
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
        
        await query.edit_message_text(
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
    
    elif data.startswith("map_route_to:"):
        destination = data.split(":", 1)[1]
        user_id = update.effective_user.id
        
        # 设置会话状态
        map_session_manager.set_session(user_id, {
            "action": "route_planning",
            "destination": destination,
            "waiting_for": "origin"
        })
        
        await query.edit_message_text(
            text=f"🛣️ 路线规划到: {destination}\n\n请输入起点地址或发送位置信息",
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
        
        await query.edit_message_text(
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
        
        await query.edit_message_text(
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
        
        await query.edit_message_text(
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
        
        await query.edit_message_text(
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

# 注册文本消息处理器
command_factory.register_text_handler(map_text_handler, permission=Permission.USER, description="地图服务文本输入处理")