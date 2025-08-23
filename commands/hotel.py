#!/usr/bin/env python3
"""
Google Hotels API 集成模块
基于 flight.py 架构，提供酒店搜索、价格对比、预订信息等功能
完全遵循 flight.py 的缓存和自动删除模式
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
from utils.location_mapper import (
    resolve_hotel_location,
    format_location_selection_message,
    get_location_query,
    format_location_info,
    MAJOR_CITIES_LOCATIONS
)

logger = logging.getLogger(__name__)

# 全局变量 - 与 flight.py 完全一致的模式
cache_manager = None
httpx_client = None
hotel_service_manager = None

# SerpAPI配置
SERPAPI_BASE_URL = "https://serpapi.com/search"

# Telegraph相关配置
TELEGRAPH_API_URL = "https://api.telegra.ph"

# 酒店数据ID映射缓存 - 与 flight.py 完全一致的ID管理
hotel_data_mapping = {}
mapping_counter = 0

# 创建酒店会话管理器 - 与 flight.py 相同的配置
hotel_session_manager = SessionManager("HotelService", max_age=1800, max_sessions=200)  # 30分钟会话

async def _schedule_auto_delete(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, delay: int):
    """调度自动删除消息 - 与 flight.py 完全一致"""
    try:
        if context and hasattr(context, "bot_data"):
            scheduler = context.bot_data.get("message_delete_scheduler")
            if scheduler and hasattr(scheduler, "schedule_deletion"):
                await scheduler.schedule_deletion(chat_id, message_id, delay, None)
                logger.info(f"已调度酒店消息删除: chat_id={chat_id}, message_id={message_id}, delay={delay}s")
            else:
                logger.warning(f"消息删除调度器未正确初始化: scheduler={scheduler}")
        else:
            logger.warning("无法获取bot_data或context")
    except Exception as e:
        logger.error(f"调度自动删除失败: {e}")

def set_dependencies(cm, hc=None):
    """设置依赖项 - 与 flight.py 完全一致的签名和模式"""
    global cache_manager, httpx_client, hotel_service_manager
    cache_manager = cm
    httpx_client = hc
    
    # 初始化酒店服务管理器
    config = get_config()
    hotel_service_manager = HotelServiceManager(
        serpapi_key=getattr(config, 'serpapi_key', None)
    )

def get_short_hotel_id(data_id: str) -> str:
    """生成短ID用于callback_data - 与 flight.py 完全一致的逻辑"""
    global mapping_counter, hotel_data_mapping
    
    # 查找是否已存在映射
    for short_id, full_id in hotel_data_mapping.items():
        if full_id == data_id:
            return short_id
    
    # 创建新的短ID
    mapping_counter += 1
    short_id = str(mapping_counter)
    hotel_data_mapping[short_id] = data_id
    
    # 清理过多的映射（保持最近500个）
    if len(hotel_data_mapping) > 500:
        # 删除前50个旧映射
        old_keys = list(hotel_data_mapping.keys())[:50]
        for key in old_keys:
            del hotel_data_mapping[key]
    
    return short_id

def get_full_hotel_id(short_id: str) -> Optional[str]:
    """根据短ID获取完整数据ID - 与 flight.py 完全一致"""
    return hotel_data_mapping.get(short_id)

def parse_hotel_dates(date_str: str) -> Tuple[Optional[str], Optional[str]]:
    """
    解析酒店日期输入
    支持格式:
    - "2024-01-15" (单日期，自动设置check_out为次日)
    - "2024-01-15,2024-01-18" (入住,退房)
    - "2024-01-15 2024-01-18" (入住 退房)
    - "01-15" (当年月日)
    - "15" (当月日期，自动设置2天)
    """
    if not date_str:
        # 默认明天入住，后天退房
        tomorrow = datetime.now() + timedelta(days=1)
        day_after = tomorrow + timedelta(days=1)
        return tomorrow.strftime('%Y-%m-%d'), day_after.strftime('%Y-%m-%d')
    
    date_str = date_str.strip()
    current_year = datetime.now().year
    current_month = datetime.now().month
    
    # 处理逗号或空格分隔的两个日期
    for separator in [',', ' ']:
        if separator in date_str:
            parts = [part.strip() for part in date_str.split(separator) if part.strip()]
            if len(parts) == 2:
                try:
                    check_in = parse_single_date(parts[0])
                    check_out = parse_single_date(parts[1])
                    if check_in and check_out:
                        return check_in, check_out
                except:
                    pass
    
    # 处理单个日期
    check_in = parse_single_date(date_str)
    if check_in:
        # 自动设置退房日期为入住日期后一天
        check_in_dt = datetime.strptime(check_in, '%Y-%m-%d')
        check_out_dt = check_in_dt + timedelta(days=1)
        return check_in, check_out_dt.strftime('%Y-%m-%d')
    
    return None, None

def parse_single_date(date_str: str) -> Optional[str]:
    """解析单个日期字符串"""
    date_str = date_str.strip()
    current_year = datetime.now().year
    current_month = datetime.now().month
    
    # 完整日期格式: 2024-01-15
    if re.match(r'^\d{4}-\d{1,2}-\d{1,2}$', date_str):
        try:
            dt = datetime.strptime(date_str, '%Y-%m-%d')
            return dt.strftime('%Y-%m-%d')
        except:
            pass
    
    # 月-日格式: 01-15 或 1-15
    if re.match(r'^\d{1,2}-\d{1,2}$', date_str):
        try:
            month_day = f"{current_year}-{date_str}"
            dt = datetime.strptime(month_day, '%Y-%m-%d')
            return dt.strftime('%Y-%m-%d')
        except:
            pass
    
    # 只有日期: 15
    if re.match(r'^\d{1,2}$', date_str):
        try:
            day = int(date_str)
            if 1 <= day <= 31:
                dt = datetime(current_year, current_month, day)
                return dt.strftime('%Y-%m-%d')
        except:
            pass
    
    return None

def calculate_stay_duration(check_in: str, check_out: str) -> Dict:
    """计算住宿时长信息"""
    try:
        check_in_dt = datetime.strptime(check_in, '%Y-%m-%d')
        check_out_dt = datetime.strptime(check_out, '%Y-%m-%d')
        
        if check_out_dt <= check_in_dt:
            return {"error": "退房日期必须在入住日期之后"}
        
        duration = (check_out_dt - check_in_dt).days
        
        # 判断住宿类型
        if duration == 1:
            stay_type = "短住"
        elif duration <= 3:
            stay_type = "短期"
        elif duration <= 7:
            stay_type = "中期"
        elif duration <= 30:
            stay_type = "长期"
        else:
            stay_type = "月租"
        
        return {
            "days": duration,
            "nights": duration,  # 对于酒店，天数等于夜数
            "type": stay_type,
            "check_in_day": check_in_dt.strftime('%A'),  # 星期几
            "check_out_day": check_out_dt.strftime('%A')
        }
        
    except Exception as e:
        logger.error(f"计算住宿时长失败: {e}")
        return {"error": f"日期解析错误: {e}"}

def enhance_hotel_location_display(api_search_data: Dict, search_params: Dict) -> str:
    """
    增强酒店位置显示，结合API数据和本地位置信息
    """
    location_query = search_params.get('location_query', '')
    check_in_date = search_params.get('check_in_date', '')
    check_out_date = search_params.get('check_out_date', '')
    adults = search_params.get('adults', 1)
    children = search_params.get('children', 0)
    
    # 从API数据获取位置信息
    api_location_info = {}
    if api_search_data:
        search_metadata = api_search_data.get('search_metadata', {})
        if search_metadata:
            api_location_info = search_metadata.get('location', {})
    
    # 计算住宿时长
    duration_info = calculate_stay_duration(check_in_date, check_out_date)
    
    # 构建显示信息
    from telegram.helpers import escape_markdown
    
    # 安全转义所有字段
    safe_location = escape_markdown(location_query, version=2)
    
    result_parts = [
        f"🏨 *{safe_location}* 酒店搜索"
    ]
    
    # 添加日期信息
    if check_in_date and check_out_date:
        result_parts[0] += f" ({check_in_date} - {check_out_date})"
        
        if "error" not in duration_info:
            duration = duration_info['days']
            stay_type = duration_info['type']
            check_in_day = duration_info['check_in_day']
            check_out_day = duration_info['check_out_day']
            
            safe_check_in_day = escape_markdown(check_in_day, version=2)
            safe_check_out_day = escape_markdown(check_out_day, version=2)
            safe_stay_type = escape_markdown(stay_type, version=2)
            
            result_parts.extend([
                "",
                f"📅 *住宿信息*:",
                f"• 入住: {check_in_date} ({safe_check_in_day})",
                f"• 退房: {check_out_date} ({safe_check_out_day})",
                f"• 时长: {duration}晚 ({safe_stay_type})"
            ])
    
    # 添加客人信息
    guest_info = f"{adults}位成人"
    if children > 0:
        guest_info += f", {children}位儿童"
    
    safe_guest_info = escape_markdown(guest_info, version=2)
    result_parts.extend([
        "",
        f"👥 *客人信息*: {safe_guest_info}"
    ])
    
    # 添加位置相关信息
    if api_location_info:
        city = api_location_info.get('city', '')
        country = api_location_info.get('country', '')
        if city and country:
            safe_city = escape_markdown(city, version=2)
            safe_country = escape_markdown(country, version=2)
            
            # 获取国家标志
            from utils.country_data import get_country_flag
            country_code = api_location_info.get('country_code', '')
            flag = get_country_flag(country_code) if country_code else ''
            
            result_parts.extend([
                "",
                f"📍 *位置*: {safe_city}, {safe_country} {flag}"
            ])
    
    # 添加住宿类型建议
    if "error" not in duration_info:
        duration = duration_info['days']
        if duration == 1:
            result_parts.extend([
                "",
                "💡 *短住提醒*:",
                "• 建议选择市中心位置",
                "• 关注交通便利性",
                "• 可考虑商务酒店"
            ])
        elif duration >= 7:
            result_parts.extend([
                "",
                "💡 *长期住宿提醒*:",
                "• 考虑公寓式酒店",
                "• 关注周边生活设施",
                "• 可能有长住优惠"
            ])
    
    result_parts.append("")
    
    return "\n".join(result_parts)

def format_hotel_price(price_info: Dict, currency: str = "USD") -> str:
    """格式化酒店价格显示"""
    if not price_info:
        return "价格暂无"
    
    # 处理不同的价格格式
    if isinstance(price_info, (int, float)):
        return f"{currency} {price_info:,.0f}"
    
    if isinstance(price_info, dict):
        # 优先使用extracted_lowest (数字格式)
        if 'extracted_lowest' in price_info:
            return f"{currency} {price_info['extracted_lowest']:,.0f}"
        # 其次使用lowest (可能是字符串格式)
        elif 'lowest' in price_info:
            lowest = price_info['lowest']
            if isinstance(lowest, str):
                # 提取数字部分，如"$34" -> 34
                import re
                numbers = re.findall(r'\d+(?:\.\d+)?', lowest)
                if numbers:
                    return f"{currency} {float(numbers[0]):,.0f}"
                else:
                    return lowest  # 无法解析，直接返回原字符串
            elif isinstance(lowest, (int, float)):
                return f"{currency} {lowest:,.0f}"
        # 处理其他字段
        value = price_info.get('value', price_info.get('amount', 0))
        if value:
            currency_code = price_info.get('currency', currency)
            return f"{currency_code} {value:,.0f}"
    
    # 如果是字符串，直接返回
    return str(price_info)

def calculate_price_per_night(total_price, nights: int, currency: str = "USD") -> str:
    """计算每晚价格"""
    if nights <= 0:
        return "N/A"
    
    # 处理字符串价格格式
    if isinstance(total_price, str):
        import re
        numbers = re.findall(r'\d+(?:\.\d+)?', total_price)
        if numbers:
            total_price = float(numbers[0])
        else:
            return "N/A"
    
    if not isinstance(total_price, (int, float)) or total_price <= 0:
        return "N/A"
    
    price_per_night = total_price / nights
    return f"{currency} {price_per_night:,.0f}/晚"

class HotelServiceManager:
    """酒店服务管理器 - 对应 flight.py 的 FlightServiceManager"""
    
    def __init__(self, serpapi_key: str = None):
        self.serpapi_key = serpapi_key
    
    def is_available(self) -> bool:
        """检查服务是否可用"""
        return bool(self.serpapi_key)
    
    async def search_hotels(self, location_query: str, check_in_date: str, check_out_date: str,
                           adults: int = 1, children: int = 0, **kwargs) -> Optional[Dict]:
        """搜索酒店"""
        if not self.is_available():
            logger.error("SerpAPI key not configured")
            return None
        
        params = {
            "engine": "google_hotels",
            "q": location_query,
            "check_in_date": check_in_date,
            "check_out_date": check_out_date,
            "adults": adults,
            "api_key": self.serpapi_key,
            "hl": kwargs.get("language", "en"),
            "currency": kwargs.get("currency", "USD")
        }
        
        # 添加儿童数量
        if children > 0:
            params["children"] = children
        
        # 添加其他可选参数
        if "hotel_class" in kwargs:
            params["hotel_class"] = kwargs["hotel_class"]
        if "sort_by" in kwargs:
            params["sort_by"] = kwargs["sort_by"]  # price_low_to_high, price_high_to_low, rating, etc.
        if "max_price" in kwargs:
            params["max_price"] = kwargs["max_price"]
        if "min_rating" in kwargs:
            params["min_rating"] = kwargs["min_rating"]
        
        try:
            logger.info(f"Searching hotels with params: {params}")
            response = await httpx_client.get(SERPAPI_BASE_URL, params=params)
            
            if response.status_code != 200:
                logger.error(f"SerpAPI request failed: {response.status_code}")
                logger.error(f"Response: {response.text[:1000]}...")
                return None
            
            data = response.json()
            
            # 验证响应数据
            if data and data.get('search_metadata', {}).get('status') == 'Success':
                logger.info(f"Hotel search successful, found {len(data.get('properties', []))} hotels")
                return data
            else:
                logger.error(f"SerpAPI search failed: {data.get('search_metadata', {})}")
                return None
                
        except Exception as e:
            logger.error(f"Hotel search failed: {e}")
            return None
    
    async def get_hotel_details(self, hotel_id: str, **kwargs) -> Optional[Dict]:
        """获取酒店详细信息"""
        if not self.is_available():
            logger.error("SerpAPI key not configured")
            return None
        
        params = {
            "engine": "google_hotels",
            "hotel_id": hotel_id,
            "api_key": self.serpapi_key,
            "hl": kwargs.get("language", "en"),
            "currency": kwargs.get("currency", "USD")
        }
        
        try:
            response = await httpx_client.get(SERPAPI_BASE_URL, params=params)
            if response.status_code != 200:
                logger.error(f"Hotel details request failed: {response.status_code}")
                return None
            
            return response.json()
            
        except Exception as e:
            logger.error(f"Hotel details fetch failed: {e}")
            return None

class HotelCacheService:
    """酒店缓存服务 - 基于 flight.py 的缓存逻辑"""
    
    def __init__(self, cache_manager):
        self.cache_manager = cache_manager
        self.cache_prefix = "hotel_"
        self.default_ttl = 3600  # 1小时缓存
    
    def _make_cache_key(self, location: str, check_in: str, check_out: str, 
                       adults: int = 1, children: int = 0, **kwargs) -> str:
        """生成缓存键"""
        key_parts = [
            self.cache_prefix,
            location.lower().replace(' ', '_'),
            check_in,
            check_out,
            str(adults),
            str(children)
        ]
        
        # 添加其他参数
        if kwargs.get("currency"):
            key_parts.append(kwargs["currency"])
        if kwargs.get("hotel_class"):
            key_parts.append(str(kwargs["hotel_class"]))
        if kwargs.get("sort_by"):
            key_parts.append(kwargs["sort_by"])
        
        return "_".join(key_parts)
    
    async def get_cached_search(self, location: str, check_in: str, check_out: str,
                              adults: int = 1, children: int = 0, **kwargs) -> Optional[Dict]:
        """获取缓存的搜索结果"""
        if not self.cache_manager:
            return None
        
        cache_key = self._make_cache_key(location, check_in, check_out, adults, children, **kwargs)
        
        try:
            cached_data = await self.cache_manager.get(cache_key, subdirectory="hotels")
            if cached_data:
                logger.info(f"使用缓存的酒店搜索结果: {cache_key}")
                return cached_data
        except Exception as e:
            logger.error(f"获取缓存失败: {e}")
        
        return None
    
    async def cache_search_result(self, location: str, check_in: str, check_out: str,
                                adults: int = 1, children: int = 0, data: Dict = None, **kwargs) -> bool:
        """缓存搜索结果"""
        if not self.cache_manager or not data:
            return False
        
        cache_key = self._make_cache_key(location, check_in, check_out, adults, children, **kwargs)
        
        try:
            await self.cache_manager.set(cache_key, data, ttl=self.default_ttl, subdirectory="hotels")
            logger.info(f"缓存酒店搜索结果: {cache_key}")
            return True
        except Exception as e:
            logger.error(f"缓存搜索结果失败: {e}")
            return False

def format_hotel_summary(hotels_data: Dict, search_params: Dict) -> str:
    """格式化酒店搜索摘要"""
    from telegram.helpers import escape_markdown
    
    if not hotels_data or 'properties' not in hotels_data:
        return "未找到酒店信息"
    
    properties = hotels_data['properties'][:10]  # 只显示前10个
    location_query = search_params.get('location_query', '')
    check_in_date = search_params.get('check_in_date', '')
    check_out_date = search_params.get('check_out_date', '')
    currency = search_params.get('currency', 'USD')
    
    # 计算住宿时长
    duration_info = calculate_stay_duration(check_in_date, check_out_date)
    nights = duration_info.get('days', 1) if 'error' not in duration_info else 1
    
    result_parts = []
    
    for i, hotel in enumerate(properties):
        try:
            # 提取酒店基本信息
            name = hotel.get('name', '未知酒店')
            hotel_class = hotel.get('hotel_class', 0)
            rating = hotel.get('overall_rating', 0)
            reviews = hotel.get('reviews', 0)
            
            # 提取价格信息
            rate_per_night = hotel.get('rate_per_night', {})
            total_rate = hotel.get('total_rate', {})
            
            # 安全转义
            safe_name = escape_markdown(str(name), version=2)
            
            # 构建星级显示
            star_display = "⭐" * int(hotel_class) if hotel_class else ""
            
            # 构建评分显示
            rating_display = ""
            if rating:
                rating_display = f"⭐ {rating:.1f}"
                if reviews:
                    rating_display += f" ({reviews:,})"
            
            # 构建价格显示
            price_display = "价格询价"
            if rate_per_night:
                if isinstance(rate_per_night, dict):
                    # 优先使用extracted_lowest (数字格式)
                    price_value = rate_per_night.get('extracted_lowest')
                    if price_value is None:
                        # 如果没有extracted_lowest，尝试解析lowest字符串
                        lowest_str = rate_per_night.get('lowest')
                        if lowest_str and isinstance(lowest_str, str):
                            import re
                            numbers = re.findall(r'\d+(?:\.\d+)?', lowest_str)
                            if numbers:
                                price_value = float(numbers[0])
                    
                    if price_value:
                        price_display = f"{currency} {price_value:,.0f}/晚"
                        if nights > 1:
                            total_price = price_value * nights
                            price_display += f" (共{nights}晚: {currency} {total_price:,.0f})"
            elif total_rate:
                if isinstance(total_rate, dict):
                    # 优先使用extracted_lowest (数字格式)
                    price_value = total_rate.get('extracted_lowest')
                    if price_value is None:
                        # 如果没有extracted_lowest，尝试解析lowest字符串
                        lowest_str = total_rate.get('lowest')
                        if lowest_str and isinstance(lowest_str, str):
                            import re
                            numbers = re.findall(r'\d+(?:\.\d+)?', lowest_str)
                            if numbers:
                                price_value = float(numbers[0])
                    
                    if price_value:
                        price_display = f"总价: {currency} {price_value:,.0f}"
                        if nights > 1:
                            per_night = price_value / nights
                            price_display += f" ({currency} {per_night:,.0f}/晚)"
            
            # 构建单个酒店条目
            hotel_entry = f"🏨 *{safe_name}*"
            if star_display:
                hotel_entry += f" {star_display}"
            
            hotel_entry += f"\n💰 {price_display}"
            
            if rating_display:
                hotel_entry += f"\n{rating_display}"
            
            # 添加位置信息（如果有）
            if hotel.get('location'):
                location = hotel['location']
                safe_location = escape_markdown(str(location), version=2)
                hotel_entry += f"\n📍 {safe_location}"
            
            result_parts.append(hotel_entry)
            
        except Exception as e:
            logger.error(f"格式化酒店信息失败: {e}")
            continue
    
    if result_parts:
        header = f"🏨 找到 {len(properties)} 家酒店"
        return f"{header}\n\n" + "\n\n".join(result_parts)
    else:
        return "暂无可显示的酒店信息"

# 注册命令处理器
@command_factory.register("hotel", permissions=[Permission.BASIC])
@with_error_handling
async def hotel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    酒店搜索命令
    用法: /hotel <位置> [入住日期] [退房日期]
    示例: /hotel 北京 2024-01-15 2024-01-18
    """
    args = context.args if context.args else []
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    # 删除用户命令消息
    await delete_user_command(update, context)
    
    # 检查服务可用性
    if not hotel_service_manager or not hotel_service_manager.is_available():
        config = get_config()
        error_msg = "🚫 酒店搜索服务暂不可用\n\n请联系管理员配置 SerpAPI 密钥"
        message = await send_error(context, chat_id, error_msg)
        await _schedule_auto_delete(context, message.chat_id, message.message_id, 5)
        return
    
    if not args:
        help_text = """
🏨 *酒店搜索帮助*

*用法:*
`/hotel <位置> [入住日期] [退房日期]`

*参数说明:*
• `位置` - 城市名称或具体地址
• `入住日期` - 可选，格式: YYYY-MM-DD
• `退房日期` - 可选，格式: YYYY-MM-DD

*支持的位置格式:*
• 中文城市名: `北京`、`上海`、`东京`
• 英文城市名: `New York`、`London`、`Tokyo`
• 具体地址: `上海外滩`、`Times Square NYC`

*日期格式:*
• 完整格式: `2024-01-15`
• 月-日格式: `01-15` (当年)
• 只有日期: `15` (当月)
• 两个日期: `2024-01-15,2024-01-18` 或 `2024-01-15 2024-01-18`

*示例:*
• `/hotel 北京` - 搜索北京酒店(明天入住)
• `/hotel Tokyo 2024-03-15` - 搜索东京酒店，3月15日入住
• `/hotel 上海外滩 01-20 01-25` - 搜索上海外滩酒店，1月20-25日
• `/hotel New York 15 18` - 搜索纽约酒店，本月15-18日

*支持的主要城市:*
🇨🇳 北京、上海、广州、深圳、香港、澳门、台北
🇯🇵 东京、大阪、名古屋、福冈、札幌
🇰🇷 首尔、釜山、济州
🇸🇬 新加坡、🇹🇭 曼谷、🇲🇾 吉隆坡
🇺🇸 纽约、洛杉矶、旧金山、芝加哥
🇬🇧 伦敦、🇫🇷 巴黎、🇩🇪 法兰克福
🇦🇪 迪拜、🇦🇺 悉尼、墨尔本

💡 *提示:* 支持智能位置识别，可使用中英文混合输入
        """
        message = await send_help(context, chat_id, help_text)
        config = get_config()
        await _schedule_auto_delete(context, message.chat_id, message.message_id, 
                                  getattr(config, 'auto_delete_delay', 600))
        return
    
    # 解析参数
    location_input = args[0]
    date_input = " ".join(args[1:]) if len(args) > 1 else ""
    
    # 解析位置
    location_result = resolve_hotel_location(location_input)
    
    if location_result['status'] == 'not_found':
        config = get_config()
        message = await send_error(
            context,
            chat_id,
            f"❓ 未找到位置 '{location_input}'\n\n💡 请尝试使用更具体的城市名称或地址"
        )
        await _schedule_auto_delete(context, message.chat_id, message.message_id, 5)
        return
    
    if location_result['status'] == 'multiple':
        # 需要用户选择具体位置
        message_text = format_location_selection_message(location_result)
        
        # 创建选择按钮
        keyboard = []
        if 'areas' in location_result:
            areas = location_result['areas'][:10]  # 最多显示10个选项
            for i, area in enumerate(areas):
                area_name = area['name']
                callback_data = f"hotel_loc_{get_short_hotel_id(f'{location_input}_{i}_{date_input}')}"
                keyboard.append([InlineKeyboardButton(area_name, callback_data=callback_data)])
        
        keyboard.append([InlineKeyboardButton("❌ 取消", callback_data="hotel_cancel")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = await context.bot.send_message(
            chat_id=chat_id,
            text=message_text,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=reply_markup
        )
        
        # 保存会话数据
        session_data = {
            'message_id': message.message_id,
            'location_result': location_result,
            'date_input': date_input,
            'step': 'location_selection'
        }
        hotel_session_manager.set_session(user_id, session_data)
        
        # 调度自动删除
        await _schedule_auto_delete(context, chat_id, message.message_id, 300)  # 5分钟后删除
        return
    
    # 获取位置查询字符串
    location_query = get_location_query(location_result)
    
    # 解析日期
    check_in_date, check_out_date = parse_hotel_dates(date_input)
    
    if not check_in_date or not check_out_date:
        config = get_config()
        message = await send_error(
            context,
            chat_id,
            f"📅 日期格式错误\n\n请使用格式: YYYY-MM-DD 或 MM-DD 或 DD\n示例: 2024-01-15 或 01-15 或 15"
        )
        await _schedule_auto_delete(context, message.chat_id, message.message_id, 5)
        return
    
    # 验证日期有效性
    duration_info = calculate_stay_duration(check_in_date, check_out_date)
    if 'error' in duration_info:
        config = get_config()
        message = await send_error(
            context,
            chat_id,
            f"📅 日期错误: {duration_info['error']}"
        )
        await _schedule_auto_delete(context, message.chat_id, message.message_id, 5)
        return
    
    # 发送搜索中消息
    search_msg = await send_info(
        context, 
        chat_id, 
        f"🔍 正在搜索酒店...\n📍 位置: {location_query}\n📅 日期: {check_in_date} - {check_out_date}"
    )
    
    try:
        # 搜索参数
        search_params = {
            'location_query': location_query,
            'check_in_date': check_in_date,
            'check_out_date': check_out_date,
            'adults': 1,  # 默认1位成人，后续可以扩展
            'children': 0,
            'currency': 'USD',  # 默认美元，后续可以根据用户设置调整
            'language': 'en'
        }
        
        # 初始化缓存服务
        cache_service = HotelCacheService(cache_manager)
        
        # 检查缓存
        cached_result = await cache_service.get_cached_search(
            location_query, check_in_date, check_out_date, 
            search_params['adults'], search_params['children'],
            currency=search_params['currency']
        )
        
        if cached_result:
            hotels_data = cached_result
            logger.info("使用缓存的酒店搜索结果")
        else:
            # 执行搜索
            hotels_data = await hotel_service_manager.search_hotels(
                location_query=location_query,
                check_in_date=check_in_date,
                check_out_date=check_out_date,
                adults=search_params['adults'],
                children=search_params['children'],
                currency=search_params['currency'],
                language=search_params['language']
            )
            
            if hotels_data:
                # 缓存结果
                await cache_service.cache_search_result(
                    location_query, check_in_date, check_out_date,
                    search_params['adults'], search_params['children'],
                    hotels_data,
                    currency=search_params['currency']
                )
        
        # 删除搜索中消息
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=search_msg.message_id)
        except:
            pass
        
        if not hotels_data:
            config = get_config()
            message = await send_error(
                context,
                chat_id,
                "🚫 搜索失败\n\n请稍后重试或检查位置和日期是否正确"
            )
            await _schedule_auto_delete(context, message.chat_id, message.message_id, 
                                      getattr(config, 'auto_delete_delay', 600))
            return
        
        if 'properties' not in hotels_data or len(hotels_data['properties']) == 0:
            config = get_config()
            message = await send_error(
                context,
                chat_id,
                f"😔 未找到酒店\n\n位置: {location_query}\n日期: {check_in_date} - {check_out_date}\n\n请尝试:\n• 调整搜索日期\n• 使用更宽泛的位置描述\n• 检查拼写是否正确"
            )
            await _schedule_auto_delete(context, message.chat_id, message.message_id, 
                                      getattr(config, 'auto_delete_delay', 600))
            return
        
        # 构建增强的位置显示
        enhanced_display = enhance_hotel_location_display(hotels_data, search_params)
        
        # 格式化酒店摘要
        hotels_summary = format_hotel_summary(hotels_data, search_params)
        
        # 组合完整消息
        full_message = f"{enhanced_display}\n{hotels_summary}"
        
        # 创建操作按钮
        keyboard = [
            [
                InlineKeyboardButton("🔄 重新搜索", callback_data="hotel_research"),
                InlineKeyboardButton("⚙️ 筛选条件", callback_data="hotel_filter")
            ],
            [
                InlineKeyboardButton("💰 价格排序", callback_data="hotel_sort_price"),
                InlineKeyboardButton("⭐ 评分排序", callback_data="hotel_sort_rating")
            ],
            [
                InlineKeyboardButton("📋 详细列表", callback_data="hotel_detailed_list"),
                InlineKeyboardButton("🗺️ 地图查看", callback_data="hotel_map_view")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # 发送结果
        result_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=full_message,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=reply_markup
        )
        
        # 保存会话数据，供后续操作使用
        session_data = {
            'message_id': result_msg.message_id,
            'hotels_data': hotels_data,
            'search_params': search_params,
            'step': 'results_displayed'
        }
        hotel_session_manager.set_session(user_id, session_data)
        
        # 调度自动删除 - 10分钟
        await _schedule_auto_delete(context, chat_id, result_msg.message_id, 600)
        
    except Exception as e:
        # 删除搜索中消息
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=search_msg.message_id)
        except:
            pass
        
        logger.error(f"酒店搜索处理失败: {e}")
        config = get_config()
        message = await send_error(
            context,
            chat_id,
            f"🚫 处理失败: {str(e)}\n\n请稍后重试"
        )
        await _schedule_auto_delete(context, message.chat_id, message.message_id, 
                                  getattr(config, 'auto_delete_delay', 600))

# 回调查询处理器
@with_error_handling
async def hotel_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理酒店搜索相关的回调查询"""
    query = update.callback_query
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if not query.data.startswith('hotel_'):
        return
    
    await query.answer()
    
    # 获取用户会话
    session_data = hotel_session_manager.get_session(user_id)
    
    if query.data == "hotel_cancel":
        # 取消操作
        try:
            await query.edit_message_text("❌ 已取消酒店搜索")
            config = get_config()
            await _schedule_auto_delete(context, query.message.chat_id, query.message.message_id, 5)
        except:
            pass
        hotel_session_manager.remove_session(user_id)
        return
    
    elif query.data.startswith("hotel_loc_"):
        # 位置选择
        if not session_data or session_data.get('step') != 'location_selection':
            config = get_config()
            await query.edit_message_text("❌ 会话已过期，请重新搜索")
            await _schedule_auto_delete(context, query.message.chat_id, query.message.message_id, 5)
            return
        
        # 解析选择的位置索引
        short_id = query.data.replace("hotel_loc_", "")
        full_data_id = get_full_hotel_id(short_id)
        
        if not full_data_id:
            config = get_config()
            await query.edit_message_text("❌ 数据已过期，请重新搜索")
            await _schedule_auto_delete(context, query.message.chat_id, query.message.message_id, 5)
            return
        
        # 解析数据ID: location_input_area_index_date_input
        parts = full_data_id.split('_', 2)  # 最多分割2次，因为日期可能包含下划线
        if len(parts) < 3:
            config = get_config()
            await query.edit_message_text("❌ 数据格式错误，请重新搜索")
            await _schedule_auto_delete(context, query.message.chat_id, query.message.message_id, 5)
            return
        
        location_input = parts[0]
        area_index = int(parts[1])
        date_input = parts[2] if len(parts) > 2 else ""
        
        # 获取选择的区域
        location_result = session_data.get('location_result', {})
        areas = location_result.get('areas', [])
        
        if area_index >= len(areas):
            config = get_config()
            await query.edit_message_text("❌ 选择无效，请重新搜索")
            await _schedule_auto_delete(context, query.message.chat_id, query.message.message_id, 5)
            return
        
        selected_area = areas[area_index]
        location_query = selected_area['query']
        
        # 解析日期
        check_in_date, check_out_date = parse_hotel_dates(date_input)
        if not check_in_date or not check_out_date:
            # 使用默认日期
            tomorrow = datetime.now() + timedelta(days=1)
            day_after = tomorrow + timedelta(days=1)
            check_in_date = tomorrow.strftime('%Y-%m-%d')
            check_out_date = day_after.strftime('%Y-%m-%d')
        
        # 更新消息为搜索中
        await query.edit_message_text(
            f"🔍 正在搜索酒店...\n📍 位置: {selected_area['name']}\n📅 日期: {check_in_date} - {check_out_date}",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        
        try:
            # 执行搜索
            search_params = {
                'location_query': location_query,
                'check_in_date': check_in_date,
                'check_out_date': check_out_date,
                'adults': 1,
                'children': 0,
                'currency': 'USD',
                'language': 'en'
            }
            
            cache_service = HotelCacheService(cache_manager)
            
            # 检查缓存
            cached_result = await cache_service.get_cached_search(
                location_query, check_in_date, check_out_date,
                search_params['adults'], search_params['children'],
                currency=search_params['currency']
            )
            
            if cached_result:
                hotels_data = cached_result
            else:
                hotels_data = await hotel_service_manager.search_hotels(
                    location_query=location_query,
                    check_in_date=check_in_date,
                    check_out_date=check_out_date,
                    adults=search_params['adults'],
                    children=search_params['children'],
                    currency=search_params['currency'],
                    language=search_params['language']
                )
                
                if hotels_data:
                    await cache_service.cache_search_result(
                        location_query, check_in_date, check_out_date,
                        search_params['adults'], search_params['children'],
                        hotels_data,
                        currency=search_params['currency']
                    )
            
            if not hotels_data or 'properties' not in hotels_data or len(hotels_data['properties']) == 0:
                config = get_config()
                await query.edit_message_text(
                    f"😔 未找到酒店\n\n位置: {selected_area['name']}\n日期: {check_in_date} - {check_out_date}"
                )
                await _schedule_auto_delete(context, query.message.chat_id, query.message.message_id, 
                                          getattr(config, 'auto_delete_delay', 600))
                hotel_session_manager.remove_session(user_id)
                return
            
            # 构建结果消息
            enhanced_display = enhance_hotel_location_display(hotels_data, search_params)
            hotels_summary = format_hotel_summary(hotels_data, search_params)
            full_message = f"{enhanced_display}\n{hotels_summary}"
            
            # 创建操作按钮
            keyboard = [
                [
                    InlineKeyboardButton("🔄 重新搜索", callback_data="hotel_research"),
                    InlineKeyboardButton("⚙️ 筛选条件", callback_data="hotel_filter")
                ],
                [
                    InlineKeyboardButton("💰 价格排序", callback_data="hotel_sort_price"),
                    InlineKeyboardButton("⭐ 评分排序", callback_data="hotel_sort_rating")
                ],
                [
                    InlineKeyboardButton("📋 详细列表", callback_data="hotel_detailed_list"),
                    InlineKeyboardButton("🗺️ 地图查看", callback_data="hotel_map_view")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # 更新消息
            await query.edit_message_text(
                text=full_message,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=reply_markup
            )
            
            # 更新会话数据
            session_data = {
                'message_id': query.message.message_id,
                'hotels_data': hotels_data,
                'search_params': search_params,
                'step': 'results_displayed'
            }
            hotel_session_manager.set_session(user_id, session_data)
            
        except Exception as e:
            logger.error(f"酒店搜索回调处理失败: {e}")
            config = get_config()
            await query.edit_message_text(f"🚫 搜索失败: {str(e)}")
            await _schedule_auto_delete(context, query.message.chat_id, query.message.message_id, 
                                      getattr(config, 'auto_delete_delay', 600))
            hotel_session_manager.remove_session(user_id)
    
    elif query.data == "hotel_research":
        # 重新搜索 - 清除会话，提示用户重新使用命令
        config = get_config()
        await query.edit_message_text(
            "🔄 请使用 /hotel 命令重新搜索酒店\n\n格式: /hotel <位置> [日期]"
        )
        await _schedule_auto_delete(context, query.message.chat_id, query.message.message_id, 
                                  getattr(config, 'auto_delete_delay', 600))
        hotel_session_manager.remove_session(user_id)
    
    elif query.data == "hotel_filter":
        # 筛选条件 - 显示筛选选项
        if not session_data or 'hotels_data' not in session_data:
            config = get_config()
            await query.edit_message_text("❌ 会话已过期，请重新搜索")
            await _schedule_auto_delete(context, query.message.chat_id, query.message.message_id, 5)
            return
        
        filter_keyboard = [
            [
                InlineKeyboardButton("💰 价格范围", callback_data="hotel_filter_price"),
                InlineKeyboardButton("⭐ 最低评分", callback_data="hotel_filter_rating")
            ],
            [
                InlineKeyboardButton("🏨 酒店星级", callback_data="hotel_filter_class"),
                InlineKeyboardButton("🏷️ 酒店类型", callback_data="hotel_filter_type")
            ],
            [
                InlineKeyboardButton("🔙 返回", callback_data="hotel_back_to_results"),
                InlineKeyboardButton("❌ 关闭", callback_data="hotel_cancel")
            ]
        ]
        
        await query.edit_message_text(
            "⚙️ *筛选条件*\n\n请选择筛选类型:",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=InlineKeyboardMarkup(filter_keyboard)
        )
    
    elif query.data == "hotel_sort_price":
        # 价格排序
        await _sort_hotels_by_price(query, session_data, context)
    
    elif query.data == "hotel_sort_rating":
        # 评分排序
        await _sort_hotels_by_rating(query, session_data, context)
    
    elif query.data == "hotel_detailed_list":
        # 详细列表 - 使用Telegraph生成长页面
        await _show_detailed_hotel_list(query, session_data, context)
    
    elif query.data == "hotel_map_view":
        # 地图查看 - 显示位置信息和地图链接
        await _show_hotel_map_view(query, session_data, context)
    
    elif query.data == "hotel_back_to_results":
        # 返回结果页面
        if not session_data or 'hotels_data' not in session_data:
            config = get_config()
            await query.edit_message_text("❌ 会话已过期，请重新搜索")
            await _schedule_auto_delete(context, query.message.chat_id, query.message.message_id, 5)
            return
        
        # 重新构建结果页面
        hotels_data = session_data['hotels_data']
        search_params = session_data['search_params']
        
        enhanced_display = enhance_hotel_location_display(hotels_data, search_params)
        hotels_summary = format_hotel_summary(hotels_data, search_params)
        full_message = f"{enhanced_display}\n{hotels_summary}"
        
        keyboard = [
            [
                InlineKeyboardButton("🔄 重新搜索", callback_data="hotel_research"),
                InlineKeyboardButton("⚙️ 筛选条件", callback_data="hotel_filter")
            ],
            [
                InlineKeyboardButton("💰 价格排序", callback_data="hotel_sort_price"),
                InlineKeyboardButton("⭐ 评分排序", callback_data="hotel_sort_rating")
            ],
            [
                InlineKeyboardButton("📋 详细列表", callback_data="hotel_detailed_list"),
                InlineKeyboardButton("🗺️ 地图查看", callback_data="hotel_map_view")
            ]
        ]
        
        await query.edit_message_text(
            text=full_message,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def _sort_hotels_by_price(query: CallbackQuery, session_data: Dict, context: ContextTypes.DEFAULT_TYPE):
    """按价格排序酒店"""
    if not session_data or 'hotels_data' not in session_data:
        config = get_config()
        await query.edit_message_text("❌ 会话已过期，请重新搜索")
        await _schedule_auto_delete(context, query.message.chat_id, query.message.message_id, 5)
        return
    
    hotels_data = session_data['hotels_data']
    search_params = session_data['search_params']
    
    # 复制并排序酒店数据
    sorted_hotels_data = hotels_data.copy()
    properties = sorted_hotels_data.get('properties', [])
    
    # 按价格排序（从低到高）
    def get_hotel_price(hotel):
        rate_per_night = hotel.get('rate_per_night', {})
        total_rate = hotel.get('total_rate', {})
        
        # 尝试从rate_per_night获取价格
        if isinstance(rate_per_night, dict):
            price_value = rate_per_night.get('extracted_lowest')
            if price_value is not None:
                return price_value
            
            # 如果没有extracted_lowest，尝试解析lowest字符串
            lowest_str = rate_per_night.get('lowest')
            if lowest_str and isinstance(lowest_str, str):
                import re
                numbers = re.findall(r'\d+(?:\.\d+)?', lowest_str)
                if numbers:
                    return float(numbers[0])
        
        # 尝试从total_rate获取价格
        if isinstance(total_rate, dict):
            price_value = total_rate.get('extracted_lowest')
            if price_value is not None:
                return price_value
                
            # 如果没有extracted_lowest，尝试解析lowest字符串
            lowest_str = total_rate.get('lowest')
            if lowest_str and isinstance(lowest_str, str):
                import re
                numbers = re.findall(r'\d+(?:\.\d+)?', lowest_str)
                if numbers:
                    return float(numbers[0])
        
        return float('inf')  # 没有价格的排在最后
    
    sorted_properties = sorted(properties, key=get_hotel_price)
    sorted_hotels_data['properties'] = sorted_properties
    
    # 重新生成消息
    enhanced_display = enhance_hotel_location_display(sorted_hotels_data, search_params)
    hotels_summary = format_hotel_summary(sorted_hotels_data, search_params)
    full_message = f"{enhanced_display}\n💰 *已按价格排序（低到高）*\n\n{hotels_summary}"
    
    # 创建操作按钮
    keyboard = [
        [
            InlineKeyboardButton("🔄 重新搜索", callback_data="hotel_research"),
            InlineKeyboardButton("⚙️ 筛选条件", callback_data="hotel_filter")
        ],
        [
            InlineKeyboardButton("💰 价格排序", callback_data="hotel_sort_price"),
            InlineKeyboardButton("⭐ 评分排序", callback_data="hotel_sort_rating")
        ],
        [
            InlineKeyboardButton("📋 详细列表", callback_data="hotel_detailed_list"),
            InlineKeyboardButton("🗺️ 地图查看", callback_data="hotel_map_view")
        ]
    ]
    
    await query.edit_message_text(
        text=full_message,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def _sort_hotels_by_rating(query: CallbackQuery, session_data: Dict, context: ContextTypes.DEFAULT_TYPE):
    """按评分排序酒店"""
    if not session_data or 'hotels_data' not in session_data:
        config = get_config()
        await query.edit_message_text("❌ 会话已过期，请重新搜索")
        await _schedule_auto_delete(context, query.message.chat_id, query.message.message_id, 5)
        return
    
    hotels_data = session_data['hotels_data']
    search_params = session_data['search_params']
    
    # 复制并排序酒店数据
    sorted_hotels_data = hotels_data.copy()
    properties = sorted_hotels_data.get('properties', [])
    
    # 按评分排序（从高到低）
    def get_hotel_rating(hotel):
        return hotel.get('overall_rating', 0)
    
    sorted_properties = sorted(properties, key=get_hotel_rating, reverse=True)
    sorted_hotels_data['properties'] = sorted_properties
    
    # 重新生成消息
    enhanced_display = enhance_hotel_location_display(sorted_hotels_data, search_params)
    hotels_summary = format_hotel_summary(sorted_hotels_data, search_params)
    full_message = f"{enhanced_display}\n⭐ *已按评分排序（高到低）*\n\n{hotels_summary}"
    
    # 创建操作按钮
    keyboard = [
        [
            InlineKeyboardButton("🔄 重新搜索", callback_data="hotel_research"),
            InlineKeyboardButton("⚙️ 筛选条件", callback_data="hotel_filter")
        ],
        [
            InlineKeyboardButton("💰 价格排序", callback_data="hotel_sort_price"),
            InlineKeyboardButton("⭐ 评分排序", callback_data="hotel_sort_rating")
        ],
        [
            InlineKeyboardButton("📋 详细列表", callback_data="hotel_detailed_list"),
            InlineKeyboardButton("🗺️ 地图查看", callback_data="hotel_map_view")
        ]
    ]
    
    await query.edit_message_text(
        text=full_message,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def _show_detailed_hotel_list(query: CallbackQuery, session_data: Dict, context: ContextTypes.DEFAULT_TYPE):
    """显示详细酒店列表（使用Telegraph）"""
    if not session_data or 'hotels_data' not in session_data:
        config = get_config()
        await query.edit_message_text("❌ 会话已过期，请重新搜索")
        await _schedule_auto_delete(context, query.message.chat_id, query.message.message_id, 5)
        return
    
    await query.edit_message_text("📋 正在生成详细列表...")
    
    try:
        hotels_data = session_data['hotels_data']
        search_params = session_data['search_params']
        
        # 生成Telegraph页面
        telegraph_url = await _create_hotel_telegraph_page(hotels_data, search_params)
        
        if telegraph_url:
            # 创建按钮
            keyboard = [
                [InlineKeyboardButton("📖 查看详细列表", url=telegraph_url)],
                [
                    InlineKeyboardButton("🔙 返回", callback_data="hotel_back_to_results"),
                    InlineKeyboardButton("❌ 关闭", callback_data="hotel_cancel")
                ]
            ]
            
            await query.edit_message_text(
                "📋 *详细酒店列表已生成*\n\n点击下方按钮查看完整的酒店信息，包括详细介绍、设施、评价等。",
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            config = get_config()
            await query.edit_message_text("❌ 生成详细列表失败，请稍后重试")
            await _schedule_auto_delete(context, query.message.chat_id, query.message.message_id, 
                                      getattr(config, 'auto_delete_delay', 600))
            
    except Exception as e:
        logger.error(f"生成详细酒店列表失败: {e}")
        config = get_config()
        await query.edit_message_text("❌ 生成详细列表失败，请稍后重试")
        await _schedule_auto_delete(context, query.message.chat_id, query.message.message_id, 
                                  getattr(config, 'auto_delete_delay', 600))

async def _show_hotel_map_view(query: CallbackQuery, session_data: Dict, context: ContextTypes.DEFAULT_TYPE):
    """显示酒店地图视图"""
    if not session_data or 'hotels_data' not in session_data:
        config = get_config()
        await query.edit_message_text("❌ 会话已过期，请重新搜索")
        await _schedule_auto_delete(context, query.message.chat_id, query.message.message_id, 5)
        return
    
    hotels_data = session_data['hotels_data']
    search_params = session_data['search_params']
    location_query = search_params.get('location_query', '')
    
    # 生成地图搜索URL
    google_maps_url = f"https://www.google.com/maps/search/hotels+near+{location_query.replace(' ', '+')}"
    
    # 创建按钮
    keyboard = [
        [InlineKeyboardButton("🗺️ 在Google地图中查看", url=google_maps_url)],
        [
            InlineKeyboardButton("🔙 返回", callback_data="hotel_back_to_results"),
            InlineKeyboardButton("❌ 关闭", callback_data="hotel_cancel")
        ]
    ]
    
    from telegram.helpers import escape_markdown
    safe_location = escape_markdown(location_query, version=2)
    
    await query.edit_message_text(
        f"🗺️ *地图查看*\n\n位置: {safe_location}\n\n点击下方按钮在Google地图中查看该区域的酒店分布和位置信息。",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def _create_hotel_telegraph_page(hotels_data: Dict, search_params: Dict) -> Optional[str]:
    """创建Telegraph页面显示详细酒店信息"""
    if not httpx_client:
        logger.error("HTTP client not available for Telegraph")
        return None
    
    try:
        properties = hotels_data.get('properties', [])[:20]  # 最多显示20家酒店
        location_query = search_params.get('location_query', '')
        check_in_date = search_params.get('check_in_date', '')
        check_out_date = search_params.get('check_out_date', '')
        currency = search_params.get('currency', 'USD')
        
        # 计算住宿时长
        duration_info = calculate_stay_duration(check_in_date, check_out_date)
        nights = duration_info.get('days', 1) if 'error' not in duration_info else 1
        
        # 创建Telegraph内容
        content = []
        
        # 标题和基本信息
        content.append({
            "tag": "h3",
            "children": [f"🏨 {location_query} 酒店列表"]
        })
        
        content.append({
            "tag": "p",
            "children": [
                f"📅 入住: {check_in_date} - 退房: {check_out_date} ({nights}晚)",
                {"tag": "br"},
                f"🔍 找到 {len(properties)} 家酒店"
            ]
        })
        
        # 添加每个酒店的详细信息
        for i, hotel in enumerate(properties, 1):
            try:
                name = hotel.get('name', f'酒店 #{i}')
                hotel_class = hotel.get('hotel_class', 0)
                rating = hotel.get('overall_rating', 0)
                reviews = hotel.get('reviews', 0)
                
                # 价格信息
                rate_per_night = hotel.get('rate_per_night', {})
                total_rate = hotel.get('total_rate', {})
                
                # 构建酒店条目
                hotel_content = []
                
                # 酒店名称和星级
                hotel_title = f"{i}. {name}"
                if hotel_class:
                    hotel_title += f" {'⭐' * int(hotel_class)}"
                
                hotel_content.append({
                    "tag": "h4",
                    "children": [hotel_title]
                })
                
                # 评分信息
                if rating:
                    rating_text = f"⭐ 评分: {rating:.1f}/5.0"
                    if reviews:
                        rating_text += f" ({reviews:,} 条评价)"
                    hotel_content.append({
                        "tag": "p",
                        "children": [rating_text]
                    })
                
                # 价格信息
                price_content = []
                if rate_per_night and isinstance(rate_per_night, dict):
                    # 优先使用extracted_lowest (数字格式)
                    price_value = rate_per_night.get('extracted_lowest')
                    if price_value is None:
                        # 如果没有extracted_lowest，尝试解析lowest字符串
                        lowest_str = rate_per_night.get('lowest')
                        if lowest_str and isinstance(lowest_str, str):
                            import re
                            numbers = re.findall(r'\d+(?:\.\d+)?', lowest_str)
                            if numbers:
                                price_value = float(numbers[0])
                    
                    if price_value:
                        price_content.append(f"💰 价格: {currency} {price_value:,.0f}/晚")
                        if nights > 1:
                            total_price = price_value * nights
                            price_content.append(f" (总计: {currency} {total_price:,.0f})")
                elif total_rate and isinstance(total_rate, dict):
                    # 优先使用extracted_lowest (数字格式)
                    price_value = total_rate.get('extracted_lowest')
                    if price_value is None:
                        # 如果没有extracted_lowest，尝试解析lowest字符串
                        lowest_str = total_rate.get('lowest')
                        if lowest_str and isinstance(lowest_str, str):
                            import re
                            numbers = re.findall(r'\d+(?:\.\d+)?', lowest_str)
                            if numbers:
                                price_value = float(numbers[0])
                    
                    if price_value:
                        price_content.append(f"💰 总价: {currency} {price_value:,.0f}")
                        if nights > 1:
                            per_night = price_value / nights
                            price_content.append(f" (约 {currency} {per_night:,.0f}/晚)")
                
                if price_content:
                    hotel_content.append({
                        "tag": "p",
                        "children": price_content
                    })
                
                # 位置信息
                location = hotel.get('location')
                if location:
                    hotel_content.append({
                        "tag": "p",
                        "children": [f"📍 位置: {location}"]
                    })
                
                # 设施信息
                amenities = hotel.get('amenities', [])
                if amenities:
                    amenities_text = "🏢 设施: " + ", ".join(amenities[:5])
                    if len(amenities) > 5:
                        amenities_text += f"等 {len(amenities)} 项设施"
                    hotel_content.append({
                        "tag": "p",
                        "children": [amenities_text]
                    })
                
                # 描述信息
                description = hotel.get('description')
                if description and len(description) < 200:
                    hotel_content.append({
                        "tag": "p",
                        "children": [f"📝 简介: {description}"]
                    })
                
                # 添加分隔线
                hotel_content.append({"tag": "hr"})
                
                content.extend(hotel_content)
                
            except Exception as e:
                logger.error(f"处理酒店 {i} 信息失败: {e}")
                continue
        
        # 添加页脚
        content.append({
            "tag": "p",
            "children": [
                {"tag": "em", "children": [
                    f"数据更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                    {"tag": "br"},
                    "🤖 由 Claude Code 生成"
                ]}
            ]
        })
        
        # 创建Telegraph页面
        page_data = {
            "access_token": "b968da509bb76866c35425099bc7c93181e3c9ca3e7b7a05",  # 匿名access token
            "title": f"🏨 {location_query} 酒店搜索结果",
            "author_name": "Claude Code Hotel Search",
            "content": content,
            "return_content": True
        }
        
        response = await httpx_client.post(
            f"{TELEGRAPH_API_URL}/createPage",
            json=page_data
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get('ok'):
                page_url = result['result']['url']
                logger.info(f"Telegraph页面创建成功: {page_url}")
                return page_url
        
        logger.error(f"Telegraph页面创建失败: {response.text}")
        return None
        
    except Exception as e:
        logger.error(f"创建Telegraph页面失败: {e}")
        return None

# 注册回调查询处理器
command_factory.register_callback(r"^hotel_", hotel_callback_handler, permission=Permission.USER, description="酒店服务回调")

# 导出主要函数供外部使用
__all__ = [
    'hotel_command',
    'hotel_callback_handler', 
    'set_dependencies',
    'HotelServiceManager',
    'HotelCacheService'
]