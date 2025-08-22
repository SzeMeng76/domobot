#!/usr/bin/env python3
"""
航班查询命令模块 - 参考finance/map设计模式
使用VariFlight MCP API提供航班信息查询
"""

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta
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
    send_info
)
from utils.permissions import Permission
from utils.airport_data import find_airports_by_query, get_airport_info as get_local_airport_info, format_airport_suggestions

logger = logging.getLogger(__name__)

# 全局变量
cache_manager = None
httpx_client = None

# 航班数据ID映射缓存 (参考finance模式)
flight_id_mapping = {}
mapping_counter = 0

def set_dependencies(cm, hc=None):
    """设置依赖项"""
    global cache_manager, httpx_client
    cache_manager = cm
    if hc:
        httpx_client = hc
    else:
        from utils.http_client import get_http_client
        httpx_client = get_http_client()

def get_short_flight_id(full_flight_id: str) -> str:
    """获取短航班ID用于callback_data（参考finance模式）"""
    global flight_id_mapping, mapping_counter
    
    for short_id, full_id in flight_id_mapping.items():
        if full_id == full_flight_id:
            return short_id
    
    mapping_counter += 1
    short_id = str(mapping_counter)
    flight_id_mapping[short_id] = full_flight_id
    
    # 清理过多映射
    if len(flight_id_mapping) > 500:
        old_keys = list(flight_id_mapping.keys())[:50]
        for key in old_keys:
            del flight_id_mapping[key]
    
    return short_id

def get_full_flight_id(short_flight_id: str) -> Optional[str]:
    """根据短ID获取完整航班ID"""
    return flight_id_mapping.get(short_flight_id)

def _is_flight_number(text: str) -> bool:
    """判断是否是航班号"""
    text = text.strip().upper()
    # 航班号通常是2-3位字母 + 2-4位数字
    return (len(text) >= 4 and len(text) <= 8 and 
            any(char.isalpha() for char in text) and 
            any(char.isdigit() for char in text))

def _is_date(text: str) -> bool:
    """判断是否是日期格式"""
    text = text.strip()
    # 支持多种日期格式
    date_patterns = [
        r'^\d{8}$',           # 20241225
        r'^\d{4}-\d{2}-\d{2}$',  # 2024-12-25
        r'^\d{4}/\d{2}/\d{2}$',  # 2024/12/25
        r'^\d{2}-\d{2}$',        # 12-25 (当年)
        r'^\d{2}/\d{2}$',        # 12/25 (当年)
    ]
    
    import re
    for pattern in date_patterns:
        if re.match(pattern, text):
            return True
    return False

def _parse_date(date_str: str) -> str:
    """解析日期字符串为YYYY-MM-DD格式（MCP API需要）"""
    date_str = date_str.strip()
    
    try:
        import re
        from datetime import datetime
        
        # YYYYMMDD格式
        if re.match(r'^\d{8}$', date_str):
            # 验证日期有效性并转换为YYYY-MM-DD
            date_obj = datetime.strptime(date_str, '%Y%m%d')
            return date_obj.strftime('%Y-%m-%d')
        
        # YYYY-MM-DD格式
        elif re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
            # 验证日期有效性
            datetime.strptime(date_str, '%Y-%m-%d')
            return date_str
        
        # YYYY/MM/DD格式
        elif re.match(r'^\d{4}/\d{2}/\d{2}$', date_str):
            date_obj = datetime.strptime(date_str, '%Y/%m/%d')
            return date_obj.strftime('%Y-%m-%d')
        
        # MM-DD格式 (当年)
        elif re.match(r'^\d{2}-\d{2}$', date_str):
            current_year = datetime.now().year
            full_date = f"{current_year}-{date_str}"
            date_obj = datetime.strptime(full_date, '%Y-%m-%d')
            return date_obj.strftime('%Y-%m-%d')
        
        # MM/DD格式 (当年)
        elif re.match(r'^\d{2}/\d{2}$', date_str):
            current_year = datetime.now().year
            full_date = f"{current_year}/{date_str}"
            date_obj = datetime.strptime(full_date, '%Y/%m/%d')
            return date_obj.strftime('%Y-%m-%d')
        
        else:
            return None
            
    except ValueError:
        # 日期格式无效
        return None

async def _schedule_auto_delete(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, delay: int):
    """调度自动删除消息（参考map/finance模式）"""
    try:
        scheduler = context.bot_data.get("message_delete_scheduler")
        if scheduler and hasattr(scheduler, "schedule_deletion"):
            await scheduler.schedule_deletion(chat_id, message_id, delay, None)
            logger.info(f"已调度航班消息删除: chat_id={chat_id}, message_id={message_id}, delay={delay}s")
    except Exception as e:
        logger.error(f"调度自动删除失败: {e}")

class FlightService:
    """航班查询服务类 - 使用VariFlight MCP API"""
    
    def __init__(self):
        self.base_url = "https://mcp.variflight.com/api/v1/mcp/data"
        self.config = get_config()
        
    async def search_flight(self, flight_number: str, date: str = None) -> Optional[Dict]:
        """查询航班信息 - 使用MCP API"""
        try:
            if not date:
                date = datetime.now().strftime('%Y-%m-%d')  # MCP API使用YYYY-MM-DD格式
            else:
                # 转换日期格式从YYYYMMDD到YYYY-MM-DD
                if len(date) == 8 and date.isdigit():
                    date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
            
            # 检查缓存 (使用subdirectory参数)
            cache_key = f"search:{flight_number}:{date}" 
            cached_result = await cache_manager.load_cache(cache_key, subdirectory="flight")
            
            if cached_result:
                logger.info(f"从缓存获取航班信息: {flight_number}")
                return cached_result
            
            # 构建MCP API请求
            api_key = getattr(self.config, 'variflight_api_key', '')
            if not api_key:
                logger.error("VariFlight API密钥未配置")
                return None
            
            # 使用MCP API格式
            request_body = {
                "endpoint": "flight",
                "params": {
                    "fnum": flight_number,
                    "date": date
                }
            }
            
            headers = {
                'X-VARIFLIGHT-KEY': api_key,
                'Content-Type': 'application/json'
            }
            
            response = await httpx_client.post(self.base_url, json=request_body, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                # 保存缓存 (使用subdirectory参数)
                await cache_manager.save_cache(cache_key, data, subdirectory="flight")
                logger.info(f"成功查询航班信息: {flight_number}")
                return data
            else:
                logger.error(f"MCP API请求失败: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"查询航班失败 {flight_number}: {e}")
            return None
    
    async def search_route(self, origin: str, destination: str, date: str = None) -> Optional[Dict]:
        """查询航线信息 - 使用MCP API"""
        try:
            if not date:
                date = datetime.now().strftime('%Y-%m-%d')  # MCP API使用YYYY-MM-DD格式
            else:
                # 转换日期格式从YYYYMMDD到YYYY-MM-DD
                if len(date) == 8 and date.isdigit():
                    date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
            
            cache_key = f"route:{origin}:{destination}:{date}"
            cached_result = await cache_manager.load_cache(cache_key, subdirectory="flight")
            
            if cached_result:
                return cached_result
            
            api_key = getattr(self.config, 'variflight_api_key', '')
            if not api_key:
                return None
            
            # 使用MCP API格式 - flights端点用于航线查询
            # 从机场代码获取城市代码 (基于MCP API要求)
            airport_to_city = {
                'PEK': 'BJS', 'PKX': 'BJS',  # 北京
                'SHA': 'SHA', 'PVG': 'SHA',  # 上海
                'CAN': 'CAN',                # 广州
                'SZX': 'SZX',                # 深圳
                'CTU': 'CTU',                # 成都
                'XMN': 'XMN',                # 厦门
                'HGH': 'HGH',                # 杭州
                'NKG': 'NKG',                # 南京
                'TSN': 'TSN',                # 天津
                'LAX': 'LAX',                # 洛杉矶
                'JFK': 'NYC', 'LGA': 'NYC', 'EWR': 'NYC',  # 纽约
                'NRT': 'TYO', 'HND': 'TYO',  # 东京
                'LHR': 'LON', 'LGW': 'LON', 'STN': 'LON',  # 伦敦
                'CDG': 'PAR', 'ORY': 'PAR',  # 巴黎
                'ICN': 'SEL',                # 首尔
                'SIN': 'SIN',                # 新加坡
            }
            
            origin_city = airport_to_city.get(origin.upper(), origin.upper())
            dest_city = airport_to_city.get(destination.upper(), destination.upper())
            
            request_body = {
                "endpoint": "flights",
                "params": {
                    "dep": origin,
                    "depcity": origin_city,
                    "arr": destination,
                    "arrcity": dest_city,
                    "date": date
                }
            }
            
            headers = {
                'X-VARIFLIGHT-KEY': api_key,
                'Content-Type': 'application/json'
            }
            
            response = await httpx_client.post(self.base_url, json=request_body, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                # 保存缓存 (航线查询)
                await cache_manager.save_cache(cache_key, data, subdirectory="flight")
                return data
            else:
                logger.error(f"MCP航线查询失败: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"查询航线失败 {origin}-{destination}: {e}")
            return None

    async def get_airport_info(self, airport_code: str) -> Optional[Dict]:
        """获取机场信息 - 使用MCP API天气端点作为替代"""
        try:
            cache_key = f"airport_info:{airport_code}"
            cached_result = await cache_manager.load_cache(cache_key, subdirectory="flight")
            
            if cached_result:
                return cached_result
            
            api_key = getattr(self.config, 'variflight_api_key', '')
            if not api_key:
                return None
            
            # MCP API没有专门的机场信息端点，使用天气查询作为替代
            request_body = {
                "endpoint": "futureAirportWeather",
                "params": {
                    "code": airport_code,
                    "type": "1"
                }
            }
            
            headers = {
                'X-VARIFLIGHT-KEY': api_key,
                'Content-Type': 'application/json'
            }
            
            response = await httpx_client.post(self.base_url, json=request_body, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                # 保存缓存 (机场信息)
                await cache_manager.save_cache(cache_key, data, subdirectory="flight")
                return data
            else:
                return None
                
        except Exception as e:
            logger.error(f"查询机场失败 {airport_code}: {e}")
            return None

    async def get_flight_transfer_info(self, origin_city: str, dest_city: str, date: str = None) -> Optional[Dict]:
        """获取航班中转信息 - MCP API新功能"""
        try:
            if not date:
                date = datetime.now().strftime('%Y-%m-%d')
            else:
                # 转换日期格式从YYYYMMDD到YYYY-MM-DD
                if len(date) == 8 and date.isdigit():
                    date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
            
            cache_key = f"transfer:{origin_city}:{dest_city}:{date}"
            cached_result = await cache_manager.load_cache(cache_key, subdirectory="flight")
            
            if cached_result:
                return cached_result
            
            api_key = getattr(self.config, 'variflight_api_key', '')
            if not api_key:
                return None
            
            request_body = {
                "endpoint": "transfer",
                "params": {
                    "depcity": origin_city,
                    "arrcity": dest_city,
                    "depdate": date
                }
            }
            
            headers = {
                'X-VARIFLIGHT-KEY': api_key,
                'Content-Type': 'application/json'
            }
            
            response = await httpx_client.post(self.base_url, json=request_body, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                await cache_manager.save_cache(cache_key, data, subdirectory="flight")
                return data
            else:
                logger.error(f"MCP中转信息查询失败: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"查询中转信息失败 {origin_city}-{dest_city}: {e}")
            return None

    async def get_flight_happiness_index(self, flight_number: str, date: str = None) -> Optional[Dict]:
        """获取航班幸福指数 - MCP API新功能"""
        try:
            if not date:
                date = datetime.now().strftime('%Y-%m-%d')
            else:
                if len(date) == 8 and date.isdigit():
                    date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
            
            cache_key = f"happiness:{flight_number}:{date}"
            cached_result = await cache_manager.load_cache(cache_key, subdirectory="flight")
            
            if cached_result:
                return cached_result
            
            api_key = getattr(self.config, 'variflight_api_key', '')
            if not api_key:
                return None
            
            request_body = {
                "endpoint": "happiness",
                "params": {
                    "fnum": flight_number,
                    "date": date
                }
            }
            
            headers = {
                'X-VARIFLIGHT-KEY': api_key,
                'Content-Type': 'application/json'
            }
            
            response = await httpx_client.post(self.base_url, json=request_body, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                await cache_manager.save_cache(cache_key, data, subdirectory="flight")
                return data
            else:
                logger.error(f"MCP幸福指数查询失败: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"查询幸福指数失败 {flight_number}: {e}")
            return None

    async def get_airport_weather(self, airport_code: str) -> Optional[Dict]:
        """获取机场天气预报 - MCP API功能"""
        try:
            cache_key = f"weather:{airport_code}"
            cached_result = await cache_manager.load_cache(cache_key, subdirectory="flight")
            
            if cached_result:
                return cached_result
            
            api_key = getattr(self.config, 'variflight_api_key', '')
            if not api_key:
                return None
            
            request_body = {
                "endpoint": "futureAirportWeather",
                "params": {
                    "code": airport_code,
                    "type": "1"
                }
            }
            
            headers = {
                'X-VARIFLIGHT-KEY': api_key,
                'Content-Type': 'application/json'
            }
            
            response = await httpx_client.post(self.base_url, json=request_body, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                await cache_manager.save_cache(cache_key, data, subdirectory="flight")
                return data
            else:
                logger.error(f"MCP天气查询失败: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"查询机场天气失败 {airport_code}: {e}")
            return None

    async def search_flight_itineraries(self, origin_city: str, dest_city: str, date: str = None) -> Optional[Dict]:
        """搜索机票行程 - MCP API新功能"""
        try:
            if not date:
                date = datetime.now().strftime('%Y-%m-%d')
            else:
                if len(date) == 8 and date.isdigit():
                    date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
            
            cache_key = f"itineraries:{origin_city}:{dest_city}:{date}"
            cached_result = await cache_manager.load_cache(cache_key, subdirectory="flight")
            
            if cached_result:
                return cached_result
            
            api_key = getattr(self.config, 'variflight_api_key', '')
            if not api_key:
                return None
            
            request_body = {
                "endpoint": "searchFlightItineraries",
                "params": {
                    "depCityCode": origin_city,
                    "arrCityCode": dest_city,
                    "depDate": date
                }
            }
            
            headers = {
                'X-VARIFLIGHT-KEY': api_key,
                'Content-Type': 'application/json'
            }
            
            response = await httpx_client.post(self.base_url, json=request_body, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                await cache_manager.save_cache(cache_key, data, subdirectory="flight")
                return data
            else:
                logger.error(f"MCP机票搜索失败: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"搜索机票失败 {origin_city}-{dest_city}: {e}")
            return None

# 创建服务实例
flight_service = FlightService()

async def flight_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """航班查询主命令 /flight（参考finance模式）"""
    if not update.message:
        return
    
    # 检查API密钥配置
    config = get_config()
    if not getattr(config, 'variflight_api_key', None):
        await send_error(
            context, 
            update.message.chat_id,
            "❌ 航班服务未配置API密钥，请联系管理员"
        )
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        return
    
    # 如果有参数，解析并执行相应操作
    if context.args:
        await _parse_flight_args(update, context, context.args)
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        return
    
    # 没有参数，显示主菜单（基于MCP API功能）
    keyboard = [
        [
            InlineKeyboardButton("✈️ 查询航班", callback_data="flight_search"),
            InlineKeyboardButton("🔍 航线搜索", callback_data="flight_route_search")
        ],
        [
            InlineKeyboardButton("🔄 中转信息", callback_data="flight_transfer"),
            InlineKeyboardButton("😊 幸福指数", callback_data="flight_happiness")
        ],
        [
            InlineKeyboardButton("🌤️ 机场天气", callback_data="flight_weather"),
            InlineKeyboardButton("🎫 机票搜索", callback_data="flight_itineraries")
        ],
        [
            InlineKeyboardButton("🏢 智能搜索", callback_data="flight_smart_search"),
            InlineKeyboardButton("❓ 使用帮助", callback_data="flight_help")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    help_text = """
🛩️ **VariFlight MCP 航班服务**

**快速查询：**
`/flight CZ3101` - 查询航班状态
`/flight CZ3101 20241225` - 查询指定日期航班
`/flight 北京 纽约` - 查询航线
`/flight Beijing` - 搜索机场

**智能搜索支持：**
• 🏢 机场代码 (PEK, LAX, NRT)
• 🌍 城市名称 (北京, New York, Tokyo)  
• 🏳️ 国家名称 (中国, 美国, Japan)
• ✈️ 航班号码 (CZ3101, UA123)

**MCP特色功能：**
• 🔄 智能中转规划
• 😊 航班舒适度评分
• 🌤️ 机场天气预报  
• 🎫 最优机票搜索

💡 点击按钮体验全球97%航班覆盖
"""
    
    await send_message_with_auto_delete(
        context=context,
        chat_id=update.message.chat_id,
        text=foldable_text_with_markdown_v2(help_text),
        parse_mode="MarkdownV2",
        reply_markup=reply_markup
    )
    
    await delete_user_command(context, update.message.chat_id, update.message.message_id)

async def _parse_flight_args(update: Update, context: ContextTypes.DEFAULT_TYPE, args: List[str]):
    """解析航班命令参数 - 支持智能搜索和日期"""
    if len(args) == 1:
        param = args[0].strip()
        
        # 检查是否是航班号 (包含数字且长度合适)
        if len(param) >= 4 and any(char.isdigit() for char in param) and any(char.isalpha() for char in param):
            # 包含字母和数字，当作航班号查询
            await _execute_flight_search(update, context, param.upper())
        else:
            # 尝试智能搜索机场/城市/国家
            await _execute_smart_airport_search(update, context, param)
    
    elif len(args) == 2:
        # 检查第一个参数是否是特殊命令
        if args[0].lower() == 'track':
            # 追踪航班
            await _execute_flight_track(update, context, args[1])
        elif _is_flight_number(args[0]) and _is_date(args[1]):
            # 航班号 + 日期查询
            await _execute_flight_search_with_date(update, context, args[0].upper(), args[1])
        else:
            # 智能航线查询 (支持城市名称/国家名称)
            await _execute_smart_route_search(update, context, args[0], args[1])
    
    elif len(args) == 3:
        if args[0].lower() in ['track', '追踪']:
            # 日期追踪 (未来功能)
            await send_error(context, update.message.chat_id, "❌ 暂不支持指定日期的航班追踪")
        elif _is_date(args[2]):
            # 航线+日期查询
            await _execute_smart_route_search(update, context, args[0], args[1], args[2])
        else:
            # 可能是多词城市名称
            await send_error(context, update.message.chat_id, "❌ 请使用引号包围多词地名或使用日期格式")
    
    elif len(args) == 4:
        # 可能是 航班号 日期 或者其他组合
        if _is_flight_number(args[0]) and _is_date(args[1]):
            await send_error(context, update.message.chat_id, "❌ 航班号查询只需要航班号和日期两个参数")
        else:
            await send_error(context, update.message.chat_id, "❌ 参数过多，请检查格式")
    
    else:
        await send_error(context, update.message.chat_id, 
                        "❌ 参数格式错误\n\n"
                        "**正确格式：**\n"
                        "`/flight CZ3101` - 查询今日航班\n"
                        "`/flight CZ3101 20241225` - 查询指定日期航班\n" 
                        "`/flight 北京 纽约` - 查询今日航线\n"
                        "`/flight 北京 纽约 20241225` - 查询指定日期航线\n"
                        "`/flight Beijing` - 搜索城市机场\n"
                        "`/flight track CZ3101` - 追踪航班")

async def _execute_flight_search(update: Update, context: ContextTypes.DEFAULT_TYPE, flight_number: str):
    """执行航班号查询"""
    try:
        # 发送查询中消息
        loading_msg = await update.message.reply_text("🔍 正在查询航班信息...")
        
        # 查询航班信息
        flight_data = await flight_service.search_flight(flight_number)
        
        if not flight_data or not flight_data.get('success'):
            await loading_msg.edit_text(f"❌ 未找到航班 {flight_number} 的信息")
            config = get_config()
            await _schedule_auto_delete(context, loading_msg.chat_id, loading_msg.message_id, config.auto_delete_delay)
            return
        
        # 删除加载消息
        await loading_msg.delete()
        
        # 格式化并显示结果
        await _format_flight_info(update, context, flight_data, flight_number)
        
    except Exception as e:
        logger.error(f"执行航班查询失败: {e}")
        await send_error(context, update.message.chat_id, f"❌ 查询失败: {str(e)}")

async def _execute_route_search(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                              origin: str, destination: str, date: str = None):
    """执行航线查询"""
    try:
        loading_msg = await update.message.reply_text("🔍 正在查询航线信息...")
        
        route_data = await flight_service.search_route(origin.upper(), destination.upper(), date)
        
        if not route_data or not route_data.get('success'):
            await loading_msg.edit_text(f"❌ 未找到 {origin} → {destination} 的航线信息")
            config = get_config()
            await _schedule_auto_delete(context, loading_msg.chat_id, loading_msg.message_id, config.auto_delete_delay)
            return
        
        await loading_msg.delete()
        await _format_route_info(update, context, route_data, origin, destination)
        
    except Exception as e:
        logger.error(f"执行航线查询失败: {e}")
        await send_error(context, update.message.chat_id, f"❌ 查询失败: {str(e)}")

async def _execute_airport_search(update: Update, context: ContextTypes.DEFAULT_TYPE, airport_code: str):
    """执行机场信息查询"""
    try:
        loading_msg = await update.message.reply_text("🔍 正在查询机场信息...")
        
        airport_data = await flight_service.get_airport_info(airport_code.upper())
        
        if not airport_data or not airport_data.get('success'):
            await loading_msg.edit_text(f"❌ 未找到机场 {airport_code} 的信息")
            config = get_config()
            await _schedule_auto_delete(context, loading_msg.chat_id, loading_msg.message_id, config.auto_delete_delay)
            return
        
        await loading_msg.delete()
        await _format_airport_info(update, context, airport_data, airport_code)
        
    except Exception as e:
        logger.error(f"执行机场查询失败: {e}")
        await send_error(context, update.message.chat_id, f"❌ 查询失败: {str(e)}")

async def _execute_flight_track(update: Update, context: ContextTypes.DEFAULT_TYPE, flight_number: str):
    """执行航班追踪（目前显示追踪信息）"""
    try:
        loading_msg = await update.message.reply_text("📍 正在设置航班追踪...")
        
        # 先查询航班信息
        flight_data = await flight_service.search_flight(flight_number.upper())
        
        if not flight_data or not flight_data.get('success'):
            await loading_msg.edit_text(f"❌ 无法追踪航班 {flight_number}，航班不存在")
            config = get_config()
            await _schedule_auto_delete(context, loading_msg.chat_id, loading_msg.message_id, config.auto_delete_delay)
            return
        
        await loading_msg.delete()
        
        # 显示追踪设置信息
        text = f"""
📍 **航班追踪已启动**

**航班**: {flight_number.upper()}
🔔 **追踪状态**: 已激活
⏰ **更新频率**: 每5分钟检查一次
📊 **追踪内容**: 起飞/降落状态变化

💡 *注意: 这是演示版本，实际追踪功能需要后台服务支持*
"""
        
        keyboard = [
            [
                InlineKeyboardButton("🔄 查看当前状态", callback_data=f"flight_status_{get_short_flight_id(flight_number)}"),
                InlineKeyboardButton("❌ 停止追踪", callback_data=f"flight_untrack_{get_short_flight_id(flight_number)}")
            ],
            [InlineKeyboardButton("🔙 返回菜单", callback_data="flight_main_menu")]
        ]
        
        message = await update.message.reply_text(
            text=foldable_text_with_markdown_v2(text),
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        config = get_config()
        await _schedule_auto_delete(context, message.chat_id, message.message_id, config.auto_delete_delay)
        
    except Exception as e:
        logger.error(f"执行航班追踪失败: {e}")
        await send_error(context, update.message.chat_id, f"❌ 追踪设置失败: {str(e)}")

async def _execute_flight_search_with_date(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                         flight_number: str, date_str: str):
    """执行带日期的航班号查询"""
    try:
        # 解析日期
        parsed_date = _parse_date(date_str)
        if not parsed_date:
            await send_error(context, update.message.chat_id, 
                           f"❌ 日期格式无效: '{date_str}'\n\n"
                           "**支持的日期格式:**\n"
                           "• `20241225` - YYYYMMDD\n"
                           "• `2024-12-25` - YYYY-MM-DD\n"
                           "• `2024/12/25` - YYYY/MM/DD\n"
                           "• `12-25` - MM-DD (当年)\n"
                           "• `12/25` - MM/DD (当年)")
            return
        
        # 发送查询中消息
        from datetime import datetime
        date_obj = datetime.strptime(parsed_date, '%Y-%m-%d')
        date_display = date_obj.strftime('%Y年%m月%d日')
        
        loading_msg = await update.message.reply_text(
            f"🔍 正在查询 {date_display} 的航班 {flight_number}..."
        )
        
        # 查询航班信息
        flight_data = await flight_service.search_flight(flight_number, parsed_date)
        
        if not flight_data or not flight_data.get('success'):
            await loading_msg.edit_text(
                f"❌ 未找到 {date_display} 航班 {flight_number} 的信息\\n\\n"
                f"**查询信息:**\\n"
                f"• 航班号: {flight_number}\\n"
                f"• 日期: {date_display}"
            )
            config = get_config()
            await _schedule_auto_delete(context, loading_msg.chat_id, loading_msg.message_id, config.auto_delete_delay)
            return
        
        # 删除加载消息
        await loading_msg.delete()
        
        # 格式化并显示结果 (添加日期信息)
        await _format_flight_info_with_date(update, context, flight_data, flight_number, date_display)
        
    except Exception as e:
        logger.error(f"执行带日期航班查询失败: {e}")
        await send_error(context, update.message.chat_id, f"❌ 查询失败: {str(e)}")

async def _execute_smart_airport_search(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str):
    """智能机场搜索 - 支持城市名/国家名/机场代码"""
    try:
        # 查找匹配的机场
        airports = find_airports_by_query(query)
        
        if not airports:
            await send_error(context, update.message.chat_id, 
                           f"❌ 未找到与 '{query}' 匹配的机场\n\n"
                           "请尝试：\n"
                           "• 机场代码 (如: PEK, LAX)\n"
                           "• 城市名称 (如: 北京, New York)\n"
                           "• 国家名称 (如: 中国, 美国)")
            return
        
        if len(airports) == 1:
            # 只有一个匹配，直接查询机场信息
            await _execute_airport_search(update, context, airports[0])
        else:
            # 多个匹配，显示选择列表
            await _show_airport_selection(update, context, query, airports)
            
    except Exception as e:
        logger.error(f"智能机场搜索失败: {e}")
        await send_error(context, update.message.chat_id, f"❌ 搜索失败: {str(e)}")

async def _execute_smart_route_search(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                    origin: str, destination: str, date: str = None):
    """智能航线搜索 - 支持城市名/国家名"""
    try:
        # 查找起始地机场
        origin_airports = find_airports_by_query(origin)
        dest_airports = find_airports_by_query(destination)
        
        if not origin_airports:
            await send_error(context, update.message.chat_id, 
                           f"❌ 未找到起始地 '{origin}' 的机场信息")
            return
            
        if not dest_airports:
            await send_error(context, update.message.chat_id, 
                           f"❌ 未找到目的地 '{destination}' 的机场信息")
            return
        
        # 使用第一个匹配的机场进行查询
        origin_code = origin_airports[0]
        dest_code = dest_airports[0]
        
        # 显示实际使用的机场
        origin_info = get_airport_info(origin_code)
        dest_info = get_airport_info(dest_code)
        
        loading_msg = await update.message.reply_text(
            f"🔍 正在查询航线: {origin_info['city']} ({origin_code}) → {dest_info['city']} ({dest_code})..."
        )
        
        # 执行实际的航线查询
        route_data = await flight_service.search_route(origin_code, dest_code, date)
        
        if not route_data or not route_data.get('success'):
            await loading_msg.edit_text(
                f"❌ 未找到 {origin_info['city']} → {dest_info['city']} 的航线信息\\n\\n"
                f"**查询的机场:**\\n"
                f"• 起始: {origin_code} - {origin_info['name']}\\n"
                f"• 目的: {dest_code} - {dest_info['name']}")
            config = get_config()
            await _schedule_auto_delete(context, loading_msg.chat_id, loading_msg.message_id, config.auto_delete_delay)
            return
        
        await loading_msg.delete()
        await _format_route_info(update, context, route_data, origin_code, dest_code)
        
    except Exception as e:
        logger.error(f"智能航线搜索失败: {e}")
        await send_error(context, update.message.chat_id, f"❌ 搜索失败: {str(e)}")

async def _show_airport_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                query: str, airports: List[str]):
    """显示机场选择列表"""
    try:
        # 构建机场选择按钮 (最多显示8个)
        keyboard = []
        for i, airport_code in enumerate(airports[:8]):
            info = get_airport_info(airport_code)
            from utils.country_data import get_country_flag
            flag = get_country_flag(info["country"])
            
            button_text = f"{flag} {airport_code} - {info['city']}"
            callback_data = f"airport_select_{get_short_flight_id(airport_code)}"
            
            keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
        
        # 添加返回按钮
        keyboard.append([InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")])
        
        # 构建显示文本
        text = f"🔍 **搜索 '{query}' 找到多个机场:**\\n\\n"
        for i, airport_code in enumerate(airports[:8]):
            info = get_airport_info(airport_code)
            from utils.country_data import get_country_flag
            flag = get_country_flag(info["country"])
            text += f"**{i+1}\\.** {flag} **{airport_code}** - {escape_markdown(info['name'], version=2)}\\n"
        
        if len(airports) > 8:
            text += f"\\n*\\.\\.\\.还有 {len(airports) - 8} 个机场未显示*"
        
        text += "\\n\\n💡 **请选择要查询的机场:**"
        
        message = await update.message.reply_text(
            text=foldable_text_with_markdown_v2(text),
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        config = get_config()
        await _schedule_auto_delete(context, message.chat_id, message.message_id, config.auto_delete_delay)
        
    except Exception as e:
        logger.error(f"显示机场选择失败: {e}")
        await send_error(context, update.message.chat_id, "❌ 显示选择列表失败")

async def _format_flight_info(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                             flight_data: dict, flight_number: str):
    """格式化航班信息显示"""
    try:
        # 解析MCP API返回数据
        if flight_data.get('success') and flight_data.get('data'):
            data = flight_data['data'][0] if isinstance(flight_data['data'], list) and flight_data['data'] else flight_data.get('data', {})
            
            # 状态映射
            status_emoji = {
                'Scheduled': '🕐', 'Delayed': '⏰', 'Cancelled': '❌',
                'Departed': '🛫', 'Arrived': '🛬', 'Active': '✈️',
                'Unknown': '❓'
            }.get(data.get('status', 'Unknown'), '❓')
            
            # 转义Markdown字符
            dept_city = escape_markdown(str(data.get('dept_city', 'N/A')), version=2)
            arr_city = escape_markdown(str(data.get('arr_city', 'N/A')), version=2)
            airline_name = escape_markdown(str(data.get('airline_name', 'N/A')), version=2)
            
            text = f"""
✈️ **航班信息**

**{flight_number}** {status_emoji}
🛫 **航线**: {dept_city} → {arr_city}
📅 **日期**: {data.get('flight_date', 'N/A')}
⏰ **计划**: {data.get('plan_dept_time', 'N/A')} - {data.get('plan_arr_time', 'N/A')}
🔄 **实际**: {data.get('real_dept_time', 'N/A')} - {data.get('real_arr_time', 'N/A')}
📊 **状态**: {data.get('status', 'N/A')}
🏢 **航司**: {airline_name}
"""
            
            # 添加延误信息
            if data.get('dept_delay'):
                text += f"⏰ **起飞延误**: {data.get('dept_delay')}分钟\\n"
            if data.get('arr_delay'):
                text += f"⏰ **到达延误**: {data.get('arr_delay')}分钟\\n"
            
            # 添加操作按钮
            keyboard = [
                [
                    InlineKeyboardButton("🔄 刷新", callback_data=f"flight_refresh_{get_short_flight_id(flight_number)}"),
                    InlineKeyboardButton("😊 幸福指数", callback_data=f"flight_happiness_{get_short_flight_id(flight_number)}")
                ],
                [InlineKeyboardButton("🔙 返回菜单", callback_data="flight_main_menu")]
            ]
            
            message = await update.message.reply_text(
                text=text,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            # 自动删除 (使用配置的延迟时间)
            config = get_config()
            await _schedule_auto_delete(context, message.chat_id, message.message_id, config.auto_delete_delay)
            
        else:
            await send_error(context, update.message.chat_id, 
                           f"❌ 未找到航班 {flight_number} 的信息")
            
    except Exception as e:
        logger.error(f"格式化航班信息失败: {e}")
        await send_error(context, update.message.chat_id, "❌ 数据格式化失败")

async def _format_flight_info_with_date(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                      flight_data: dict, flight_number: str, date_display: str):
    """格式化航班信息显示 (带日期版本)"""
    try:
        # 解析MCP API返回数据
        if flight_data.get('success') and flight_data.get('data'):
            data = flight_data['data'][0] if isinstance(flight_data['data'], list) and flight_data['data'] else flight_data.get('data', {})
            
            # 状态映射
            status_emoji = {
                'Scheduled': '🕐', 'Delayed': '⏰', 'Cancelled': '❌',
                'Departed': '🛫', 'Arrived': '🛬', 'Active': '✈️',
                'Unknown': '❓'
            }.get(data.get('status', 'Unknown'), '❓')
            
            # 转义Markdown字符
            dept_city = escape_markdown(str(data.get('dept_city', 'N/A')), version=2)
            arr_city = escape_markdown(str(data.get('arr_city', 'N/A')), version=2)
            airline_name = escape_markdown(str(data.get('airline_name', 'N/A')), version=2)
            
            text = f"""
✈️ **航班信息**

**{flight_number}** {status_emoji}
📅 **查询日期**: {date_display}
🛫 **航线**: {dept_city} → {arr_city}
⏰ **计划**: {data.get('plan_dept_time', 'N/A')} - {data.get('plan_arr_time', 'N/A')}
🔄 **实际**: {data.get('real_dept_time', 'N/A')} - {data.get('real_arr_time', 'N/A')}
📊 **状态**: {data.get('status', 'N/A')}
🏢 **航司**: {airline_name}
"""
            
            # 添加延误信息
            if data.get('dept_delay'):
                text += f"⏰ **起飞延误**: {data.get('dept_delay')}分钟\\n"
            if data.get('arr_delay'):
                text += f"⏰ **到达延误**: {data.get('arr_delay')}分钟\\n"
            
            # 添加操作按钮
            keyboard = [
                [
                    InlineKeyboardButton("🔄 刷新", callback_data=f"flight_refresh_{get_short_flight_id(flight_number)}"),
                    InlineKeyboardButton("😊 幸福指数", callback_data=f"flight_happiness_{get_short_flight_id(flight_number)}")
                ],
                [InlineKeyboardButton("🔙 返回菜单", callback_data="flight_main_menu")]
            ]
            
            message = await update.message.reply_text(
                text=text,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            # 自动删除 (使用配置的延迟时间)
            config = get_config()
            await _schedule_auto_delete(context, message.chat_id, message.message_id, config.auto_delete_delay)
            
        else:
            await send_error(context, update.message.chat_id, 
                           f"❌ 未找到 {date_display} 航班 {flight_number} 的信息")
            
    except Exception as e:
        logger.error(f"格式化航班信息失败: {e}")
        await send_error(context, update.message.chat_id, "❌ 数据格式化失败")

async def _format_route_info(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                           route_data: dict, origin: str, destination: str):
    """格式化航线信息显示"""
    try:
        if route_data.get('success') and route_data.get('data'):
            flights = route_data['data'] if isinstance(route_data['data'], list) else [route_data['data']]
            
            text = f"🛩️ **航线查询结果**\\n\\n"
            text += f"📍 **航线**: {origin} → {destination}\\n"
            text += f"📅 **日期**: {datetime.now().strftime('%Y-%m-%d')}\\n\\n"
            
            for i, flight in enumerate(flights[:5]):  # 最多显示5个航班
                status_emoji = {
                    'Scheduled': '🕐', 'Delayed': '⏰', 'Cancelled': '❌',
                    'Departed': '🛫', 'Arrived': '🛬', 'Active': '✈️'
                }.get(flight.get('status', ''), '❓')
                
                flight_num = escape_markdown(str(flight.get('flight_number', 'N/A')), version=2)
                airline = escape_markdown(str(flight.get('airline_name', 'N/A')), version=2)
                
                text += f"**{flight_num}** {status_emoji}\\n"
                text += f"🏢 {airline}\\n"
                text += f"⏰ {flight.get('dept_time', 'N/A')} - {flight.get('arr_time', 'N/A')}\\n"
                
                if i < len(flights) - 1 and i < 4:
                    text += "\\n"
            
            if len(flights) > 5:
                text += f"\\n*\\.\\.\\.还有 {len(flights) - 5} 个航班*"
            
            keyboard = [
                [InlineKeyboardButton("🔙 返回菜单", callback_data="flight_main_menu")]
            ]
            
            message = await update.message.reply_text(
                text=text,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            config = get_config()
            await _schedule_auto_delete(context, message.chat_id, message.message_id, config.auto_delete_delay)
            
        else:
            await send_error(context, update.message.chat_id, 
                           f"❌ 未找到 {origin} → {destination} 的航线信息")
            
    except Exception as e:
        logger.error(f"格式化航线信息失败: {e}")
        await send_error(context, update.message.chat_id, "❌ 数据格式化失败")

async def _format_airport_info(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                             airport_data: dict, airport_code: str):
    """格式化机场信息显示"""
    try:
        if airport_data.get('success') and airport_data.get('data'):
            data = airport_data['data']
            
            airport_name = escape_markdown(str(data.get('airport_name', 'N/A')), version=2)
            city_name = escape_markdown(str(data.get('city_name', 'N/A')), version=2)
            country = escape_markdown(str(data.get('country', 'N/A')), version=2)
            
            text = f"""
🏢 **机场信息**

**{airport_code}** - {airport_name}
🌍 **位置**: {city_name}, {country}
🌐 **坐标**: {data.get('latitude', 'N/A')}, {data.get('longitude', 'N/A')}
⏰ **时区**: {data.get('timezone', 'N/A')}
"""
            
            if data.get('iata_code'):
                text += f"🔖 **IATA代码**: {data.get('iata_code')}\\n"
            if data.get('icao_code'):
                text += f"🔖 **ICAO代码**: {data.get('icao_code')}\\n"
            
            keyboard = [
                [
                    InlineKeyboardButton("🌤️ 天气", callback_data=f"airport_weather_{airport_code}"),
                    InlineKeyboardButton("✈️ 航班", callback_data=f"airport_flights_{airport_code}")
                ],
                [InlineKeyboardButton("🔙 返回菜单", callback_data="flight_main_menu")]
            ]
            
            message = await update.message.reply_text(
                text=text,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            config = get_config()
            await _schedule_auto_delete(context, message.chat_id, message.message_id, config.auto_delete_delay)
            
        else:
            await send_error(context, update.message.chat_id, 
                           f"❌ 未找到机场 {airport_code} 的信息")
            
    except Exception as e:
        logger.error(f"格式化机场信息失败: {e}")
        await send_error(context, update.message.chat_id, "❌ 数据格式化失败")

async def flight_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理航班相关的回调"""
    query = update.callback_query
    if not query or not query.data:
        return
        
    await query.answer()
    
    callback_data = query.data
    
    try:
        if callback_data == "flight_search":
            await _show_flight_search_menu(update, context)
        elif callback_data == "flight_route_search":
            await _show_route_search_menu(update, context)
        elif callback_data == "flight_transfer":
            await _show_transfer_menu(update, context)
        elif callback_data == "flight_happiness":
            await _show_happiness_menu(update, context)
        elif callback_data == "flight_weather":
            await _show_weather_menu(update, context)
        elif callback_data == "flight_itineraries":
            await _show_itineraries_menu(update, context)
        elif callback_data == "flight_smart_search":
            await _show_smart_search_menu(update, context)
        elif callback_data == "flight_help":
            await _show_flight_help(update, context)
        elif callback_data == "flight_main_menu":
            await _show_main_menu(update, context)
        elif callback_data.startswith("flight_refresh_"):
            flight_id = callback_data.split("_", 2)[2]
            full_flight_id = get_full_flight_id(flight_id)
            if full_flight_id:
                await _refresh_flight_info(update, context, full_flight_id)
        elif callback_data.startswith("airport_select_"):
            airport_id = callback_data.split("_", 2)[2]
            full_airport_code = get_full_flight_id(airport_id)
            if full_airport_code:
                await _handle_airport_selection(update, context, full_airport_code)
        elif callback_data.startswith("airport_weather_"):
            airport_code = callback_data.split("_", 2)[2]
            await _show_airport_weather(update, context, airport_code)
        elif callback_data.startswith("flight_happiness_"):
            flight_id = callback_data.split("_", 2)[2]
            full_flight_id = get_full_flight_id(flight_id)
            if full_flight_id:
                await _show_flight_happiness(update, context, full_flight_id)
        else:
            await query.edit_message_text("❌ 未知操作，请返回主菜单重试")
            
    except Exception as e:
        logger.error(f"回调处理失败: {e}")
        await query.edit_message_text("❌ 处理失败，请重试")

async def _show_flight_search_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示航班搜索菜单"""
    text = """
🔍 **航班查询**

请输入航班号进行查询
例如: CZ3101, CA1234, MU5678

💡 支持的航空公司:
• 国内: CA(国航), CZ(南航), MU(东航), 3U(川航) 等
• 国际: BA(英航), UA(美联航), LH(汉莎) 等
"""
    
    keyboard = [
        [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
    ]
    
    await update.callback_query.edit_message_text(
        text=foldable_text_with_markdown_v2(text),
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def _show_route_search_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示航线搜索菜单"""
    text = """
🛩️ **航线查询**

请使用以下格式查询:
`/flight 起始机场 目标机场`
`/flight 起始机场 目标机场 日期`

**示例:**
• `/flight PEK LAX` - 北京到洛杉矶
• `/flight SHA NRT 20241225` - 上海到东京(指定日期)

**常用机场代码:**
• PEK(北京首都) SHA(上海虹桥) CAN(广州)
• LAX(洛杉矶) NRT(东京成田) LHR(伦敦希思罗)
"""
    
    keyboard = [
        [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
    ]
    
    await update.callback_query.edit_message_text(
        text=foldable_text_with_markdown_v2(text),
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def _show_flight_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示帮助信息"""
    text = """
❓ **航班查询帮助**

**基础命令:**
• `/flight` - 显示主菜单
• `/flight CZ3101` - 查询航班号
• `/flight track CZ3101` - 追踪航班

**智能搜索:**
• `/flight 北京` - 搜索城市机场
• `/flight Beijing` - 英文城市名
• `/flight 中国` - 搜索国家机场  
• `/flight US` - 国家代码
• `/flight PEK` - 机场代码

**航线查询:**
• `/flight 北京 纽约` - 中文城市
• `/flight Beijing New York` - 英文城市
• `/flight PEK LAX` - 机场代码
• `/flight 中国 美国` - 国家名称

**数据来源:** VariFlight 航班数据
**覆盖范围:** 全球97%商业航班  
**更新频率:** 实时更新
"""
    
    keyboard = [
        [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
    ]
    
    await update.callback_query.edit_message_text(
        text=foldable_text_with_markdown_v2(text),
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def _show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示主菜单"""
    keyboard = [
        [
            InlineKeyboardButton("✈️ 查询航班", callback_data="flight_search"),
            InlineKeyboardButton("🔍 航线搜索", callback_data="flight_route_search")
        ],
        [
            InlineKeyboardButton("🔄 中转信息", callback_data="flight_transfer"),
            InlineKeyboardButton("😊 幸福指数", callback_data="flight_happiness")
        ],
        [
            InlineKeyboardButton("🌤️ 机场天气", callback_data="flight_weather"),
            InlineKeyboardButton("🎫 机票搜索", callback_data="flight_itineraries")
        ],
        [
            InlineKeyboardButton("🏢 智能搜索", callback_data="flight_smart_search"),
            InlineKeyboardButton("❓ 使用帮助", callback_data="flight_help")
        ]
    ]
    
    help_text = """
🛩️ **VariFlight MCP 航班服务**

**快速查询：**
`/flight CZ3101` - 查询航班状态
`/flight 北京 纽约` - 查询航线
`/flight Beijing` - 搜索机场

**MCP特色功能：**
• 🔄 智能中转规划
• 😊 航班舒适度评分
• 🌤️ 机场天气预报
• 🎫 最优机票搜索

💡 点击按钮体验全球97%航班覆盖
"""
    
    await update.callback_query.edit_message_text(
        text=foldable_text_with_markdown_v2(help_text),
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def _refresh_flight_info(update: Update, context: ContextTypes.DEFAULT_TYPE, flight_number: str):
    """刷新航班信息"""
    try:
        # 清除缓存强制刷新
        date = datetime.now().strftime('%Y-%m-%d')
        cache_key = f"search:{flight_number}:{date}"
        await cache_manager.clear_cache(cache_key, subdirectory="flight")
        
        # 重新查询
        flight_data = await flight_service.search_flight(flight_number)
        
        if flight_data and flight_data.get('success'):
            # 更新显示
            await query.edit_message_text("🔄 信息已刷新！正在更新显示...")
            await asyncio.sleep(1)  # 短暂延迟
            
            # 这里应该调用格式化函数更新消息，但由于callback限制，简化处理
            await update.callback_query.edit_message_text(
                foldable_text_with_markdown_v2(f"✅ 航班 {flight_number} 信息已刷新！\\n\\n使用 `/flight {flight_number}` 查看最新信息"),
                parse_mode="MarkdownV2"
            )
        else:
            await update.callback_query.edit_message_text(
                f"❌ 刷新失败，无法获取航班 {flight_number} 的最新信息"
            )
            
    except Exception as e:
        logger.error(f"刷新航班信息失败: {e}")
        await update.callback_query.edit_message_text("❌ 刷新失败，请重试")

async def _start_flight_tracking(update: Update, context: ContextTypes.DEFAULT_TYPE, flight_number: str):
    """开始追踪航班"""
    text = f"""
📍 **航班追踪已启动**

**航班**: {flight_number}
🔔 **状态**: 追踪中
⏰ **检查频率**: 每5分钟

💡 *注意: 这是演示功能，实际追踪需要后台服务支持*
"""
    
    keyboard = [
        [
            InlineKeyboardButton("🔄 查看状态", callback_data=f"flight_refresh_{get_short_flight_id(flight_number)}"),
            InlineKeyboardButton("❌ 停止追踪", callback_data=f"flight_untrack_{get_short_flight_id(flight_number)}")
        ],
        [InlineKeyboardButton("🔙 返回菜单", callback_data="flight_main_menu")]
    ]
    
    await update.callback_query.edit_message_text(
        text=foldable_text_with_markdown_v2(text),
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def _handle_airport_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, airport_code: str):
    """处理机场选择"""
    try:
        # 编辑消息为加载状态
        await update.callback_query.edit_message_text("🔍 正在查询机场信息...")
        
        # 执行机场信息查询
        airport_data = await flight_service.get_airport_info(airport_code)
        
        if not airport_data or not airport_data.get('success'):
            await update.callback_query.edit_message_text(f"❌ 无法获取机场 {airport_code} 的详细信息")
            config = get_config()
            await _schedule_auto_delete(context, update.callback_query.message.chat_id, 
                                      update.callback_query.message.message_id, config.auto_delete_delay)
            return
        
        # 格式化并显示机场信息
        await _format_airport_info_callback(update, context, airport_data, airport_code)
        
    except Exception as e:
        logger.error(f"处理机场选择失败: {e}")
        await update.callback_query.edit_message_text("❌ 查询失败，请重试")

async def _format_airport_info_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                      airport_data: dict, airport_code: str):
    """格式化机场信息显示 (回调版本)"""
    try:
        if airport_data.get('success') and airport_data.get('data'):
            data = airport_data['data']
            
            # 获取本地机场信息
            local_info = get_airport_info(airport_code)
            from utils.country_data import get_country_flag
            flag = get_country_flag(local_info["country"])
            
            airport_name = escape_markdown(str(data.get('airport_name', local_info['name'])), version=2)
            city_name = escape_markdown(str(data.get('city_name', local_info['city'])), version=2)
            country = escape_markdown(str(data.get('country', local_info['country'])), version=2)
            
            text = f"""
🏢 **机场信息**

{flag} **{airport_code}** - {airport_name}
🌍 **位置**: {city_name}, {country}
"""
            
            # 添加可选信息
            if data.get('latitude') and data.get('longitude'):
                text += f"🌐 **坐标**: {data.get('latitude')}, {data.get('longitude')}\\n"
            if data.get('timezone'):
                text += f"⏰ **时区**: {data.get('timezone')}\\n"
            if data.get('iata_code'):
                text += f"🔖 **IATA代码**: {data.get('iata_code')}\\n"
            if data.get('icao_code'):
                text += f"🔖 **ICAO代码**: {data.get('icao_code')}\\n"
            
            keyboard = [
                [
                    InlineKeyboardButton("🌤️ 天气", callback_data=f"airport_weather_{airport_code}"),
                    InlineKeyboardButton("✈️ 航班", callback_data=f"airport_flights_{airport_code}")
                ],
                [InlineKeyboardButton("🔙 返回菜单", callback_data="flight_main_menu")]
            ]
            
            await update.callback_query.edit_message_text(
                text=foldable_text_with_markdown_v2(text),
                parse_mode="MarkdownV2",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
        else:
            await update.callback_query.edit_message_text(
                f"❌ 未找到机场 {airport_code} 的详细信息"
            )
            
    except Exception as e:
        logger.error(f"格式化机场信息失败: {e}")
        await update.callback_query.edit_message_text("❌ 数据格式化失败")

async def _show_transfer_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示中转信息菜单"""
    text = """
🔄 **智能中转规划**

输入格式：`/flight 北京 洛杉矶 transfer`

**支持城市代码：**
• BJS (北京), SHA (上海), CAN (广州)
• LAX (洛杉矶), NYC (纽约), LON (伦敦)

**功能特色：**
• 🛫 最优中转方案推荐
• ⏱️ 最短中转时间计算
• 💰 价格对比分析
• 🌟 舒适度评估

💡 让AI为您规划最佳中转路线
"""
    
    keyboard = [
        [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
    ]
    
    await update.callback_query.edit_message_text(
        text=foldable_text_with_markdown_v2(text),
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def _show_happiness_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示航班幸福指数菜单"""
    text = """
😊 **航班幸福指数**

输入格式：`/flight CZ3101 happiness`

**评分维度：**
• ✈️ 准点率表现
• 🛋️ 座椅舒适度
• 🍽️ 餐食服务质量
• 📱 娱乐设施完善度
• 🧳 行李处理效率

**指数说明：**
• 🟢 85-100: 优秀体验
• 🟡 70-84: 良好体验  
• 🟠 55-69: 一般体验
• 🔴 <55: 需要改进

💡 选择幸福航班，享受美好旅程
"""
    
    keyboard = [
        [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
    ]
    
    await update.callback_query.edit_message_text(
        text=foldable_text_with_markdown_v2(text),
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def _show_weather_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示机场天气菜单"""
    text = """
🌤️ **机场天气预报**

输入格式：`/flight PEK weather`

**天气信息：**
• 🌡️ 实时温度与体感
• 🌧️ 降水概率预测
• 💨 风向风力状况
• 👁️ 能见度水平
• ✈️ 航班影响评估

**预报时长：**
• 📅 未来3天详细预报
• ⏰ 每6小时更新
• 🚨 恶劣天气预警

**常用机场：**
PEK(北京), SHA(上海), CAN(广州)
LAX(洛杉矶), NRT(东京), LHR(伦敦)

💡 提前了解天气，合理安排行程
"""
    
    keyboard = [
        [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
    ]
    
    await update.callback_query.edit_message_text(
        text=foldable_text_with_markdown_v2(text),
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def _show_itineraries_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示机票搜索菜单"""
    text = """
🎫 **智能机票搜索**

输入格式：`/flight BJS LAX tickets`

**搜索功能：**
• 💰 最低价格发现
• ⚡ 最短飞行时间
• 🛫 最少中转次数
• ⭐ 最佳性价比推荐

**价格对比：**
• 🏢 多航空公司对比
• 📈 价格趋势分析
• 🎯 最佳购票时机
• 💳 支付方式建议

**城市代码：**
BJS(北京), SHA(上海), CAN(广州)
LAX(洛杉矶), NYC(纽约), LON(伦敦)

💡 AI智能推荐，找到最优机票
"""
    
    keyboard = [
        [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
    ]
    
    await update.callback_query.edit_message_text(
        text=foldable_text_with_markdown_v2(text),
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def _show_smart_search_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示智能搜索菜单"""
    text = """
🏢 **智能机场搜索**

**支持搜索类型：**

**🏢 机场代码：**
`/flight PEK` - 直接查询机场

**🌍 城市名称：**
`/flight 北京` - 中文城市名
`/flight Beijing` - 英文城市名

**🏳️ 国家名称：**
`/flight 中国` - 显示主要机场
`/flight Japan` - 英文国家名

**✨ 智能特色：**
• 🔍 模糊匹配支持
• 🌐 多语言识别
• 📍 地理位置智能
• 🎯 精准推荐算法

💡 一次搜索，找到所有相关机场
"""
    
    keyboard = [
        [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
    ]
    
    await update.callback_query.edit_message_text(
        text=foldable_text_with_markdown_v2(text),
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def _show_airport_weather(update: Update, context: ContextTypes.DEFAULT_TYPE, airport_code: str):
    """显示机场天气信息"""
    try:
        await update.callback_query.edit_message_text("🌤️ 正在获取天气信息...")
        
        weather_data = await flight_service.get_airport_weather(airport_code)
        
        if not weather_data or not weather_data.get('success'):
            await update.callback_query.edit_message_text(
                f"❌ 无法获取机场 {airport_code} 的天气信息\\n\\n"
                f"可能原因：\\n"
                f"• 机场代码错误\\n"
                f"• 暂无天气数据\\n"
                f"• 网络连接问题"
            )
            return
        
        # 格式化天气信息显示
        await _format_weather_info(update, context, weather_data, airport_code)
        
    except Exception as e:
        logger.error(f"显示机场天气失败: {e}")
        await update.callback_query.edit_message_text("❌ 天气查询失败，请重试")

async def _show_flight_happiness(update: Update, context: ContextTypes.DEFAULT_TYPE, flight_number: str):
    """显示航班幸福指数"""
    try:
        await update.callback_query.edit_message_text("😊 正在分析航班幸福指数...")
        
        happiness_data = await flight_service.get_flight_happiness_index(flight_number)
        
        if not happiness_data or not happiness_data.get('success'):
            await update.callback_query.edit_message_text(
                f"❌ 无法获取航班 {flight_number} 的幸福指数\\n\\n"
                f"可能原因：\\n"
                f"• 航班号错误\\n"
                f"• 暂无评分数据\\n"
                f"• 航班已取消"
            )
            return
        
        # 格式化幸福指数显示
        await _format_happiness_info(update, context, happiness_data, flight_number)
        
    except Exception as e:
        logger.error(f"显示航班幸福指数失败: {e}")
        await update.callback_query.edit_message_text("❌ 幸福指数查询失败，请重试")

async def _format_weather_info(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                             weather_data: dict, airport_code: str):
    """格式化天气信息显示"""
    try:
        if weather_data.get('success') and weather_data.get('data'):
            data = weather_data['data']
            
            text = f"""
🌤️ **{airport_code} 机场天气**

**当前天气：**
🌡️ **温度**: {data.get('temperature', 'N/A')}°C
💨 **风力**: {data.get('wind', 'N/A')}
👁️ **能见度**: {data.get('visibility', 'N/A')}
☁️ **天气**: {escape_markdown(str(data.get('weather', 'N/A')), version=2)}

**航班影响：**
✈️ **起降状态**: {data.get('flight_impact', '正常')}
⚠️ **注意事项**: {escape_markdown(str(data.get('notice', '无特殊注意事项')), version=2)}

**更新时间**: {data.get('update_time', 'N/A')}
"""
            
            keyboard = [
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
            ]
            
            await update.callback_query.edit_message_text(
                text=foldable_text_with_markdown_v2(text),
                parse_mode="MarkdownV2",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
        else:
            await update.callback_query.edit_message_text(
                f"❌ {airport_code} 机场天气数据格式异常"
            )
            
    except Exception as e:
        logger.error(f"格式化天气信息失败: {e}")
        await update.callback_query.edit_message_text("❌ 天气信息显示失败")

async def _format_happiness_info(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                               happiness_data: dict, flight_number: str):
    """格式化幸福指数显示"""
    try:
        if happiness_data.get('success') and happiness_data.get('data'):
            data = happiness_data['data']
            
            # 获取幸福指数分数
            score = data.get('happiness_score', 0)
            
            # 根据分数确定等级和颜色
            if score >= 85:
                level = "🟢 优秀"
                emoji = "😊"
            elif score >= 70:
                level = "🟡 良好" 
                emoji = "🙂"
            elif score >= 55:
                level = "🟠 一般"
                emoji = "😐"
            else:
                level = "🔴 较差"
                emoji = "😔"
            
            text = f"""
😊 **{flight_number} 幸福指数**

{emoji} **综合评分**: {score}/100 ({level})

**详细评分：**
✈️ **准点率**: {data.get('punctuality', 'N/A')}/100
🛋️ **舒适度**: {data.get('comfort', 'N/A')}/100
🍽️ **服务质量**: {data.get('service', 'N/A')}/100
📱 **设施完善**: {data.get('facilities', 'N/A')}/100

**乘客评价：**
👍 **好评率**: {data.get('positive_rate', 'N/A')}%
💬 **评论数**: {data.get('review_count', 'N/A')} 条

**建议等级**: {level}
"""
            
            keyboard = [
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
            ]
            
            await update.callback_query.edit_message_text(
                text=foldable_text_with_markdown_v2(text),
                parse_mode="MarkdownV2",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
        else:
            await update.callback_query.edit_message_text(
                f"❌ {flight_number} 幸福指数数据格式异常"
            )
            
    except Exception as e:
        logger.error(f"格式化幸福指数失败: {e}")
        await update.callback_query.edit_message_text("❌ 幸福指数显示失败")

# 注册回调处理器（参考finance模式）
command_factory.register_callback(
    r"^flight_",
    flight_callback_handler, 
    permission=Permission.USER,
    description="航班查询回调处理"
)

# 注册主命令
command_factory.register_command(
    "flight",
    flight_command,
    permission=Permission.USER,  # 或 Permission.NONE 看您需求
    description="🛩️ 航班查询 - 实时状态、航线搜索、追踪服务"
)