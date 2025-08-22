#!/usr/bin/env python3
"""
优化后的航班查询功能模块
集成 Variflight API 提供智能航班信息查询服务
"""

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from utils.command_factory import command_factory
from utils.config_manager import get_config
from utils.error_handling import with_error_handling
from utils.formatter import foldable_text_v2, foldable_text_with_markdown_v2
from utils.message_manager import (
    delete_user_command, 
    send_error, 
    send_message_with_auto_delete
)
from utils.permissions import Permission
from utils.session_manager import SessionManager
from utils.flight_utils import FlightSearchHelper, format_price_info

logger = logging.getLogger(__name__)
config = get_config()

# 全局变量
cache_manager = None
httpx_client = None
flight_service = None

# 创建航班会话管理器
flight_session_manager = SessionManager("FlightService", max_age=1800, max_sessions=200)


class VariflightService:
    """Variflight API 服务类"""
    
    def __init__(self, cache_manager, httpx_client):
        self.cache_manager = cache_manager
        self.httpx_client = httpx_client
        self.base_url = "https://mcp.variflight.com/api/v1/mcp/data"
        self.api_key = config.variflight_api_key
        
    async def _make_request(self, endpoint: str, params: dict) -> dict:
        """发起API请求"""
        if not self.api_key:
            raise ValueError("VARIFLIGHT_API_KEY 未配置")
            
        payload = {"endpoint": endpoint, "params": params}
        headers = {
            "X-VARIFLIGHT-KEY": self.api_key,
            "Content-Type": "application/json"
        }
        
        try:
            response = await self.httpx_client.post(
                self.base_url, 
                json=payload, 
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 401:
                raise ValueError("API密钥无效或已过期")
            elif response.status_code == 429:
                raise ValueError("API调用次数超限，请稍后重试")
            elif response.status_code != 200:
                raise ValueError(f"API请求失败: {response.status_code}")
                
            # 根据MCP API代码，返回格式是包装过的，需要解包
            result = response.json()
            
            # 直接返回JSON结果
            if isinstance(result, dict):
                return result
            else:
                # 如果是字符串格式的JSON，尝试解析
                import json
                if isinstance(result, str):
                    return json.loads(result)
                return result
                
        except Exception as e:
            logger.error(f"Variflight API调用失败: {e}")
            raise ValueError(f"航班信息服务暂时不可用: {str(e)}")
    
    async def search_flight_by_number(self, flight_num: str, date: str) -> dict:
        """根据航班号查询航班信息"""
        cache_key = f"flight:number:{flight_num}:{date}"
        cached = await self.cache_manager.load_cache(
            cache_key, 
            max_age_seconds=300,  # 5分钟缓存
            subdirectory="flight"
        )
        if cached:
            return cached
            
        result = await self._make_request("flight", {
            "fnum": flight_num.upper(),
            "date": date
        })
        
        if result and self.cache_manager:
            await self.cache_manager.save_cache(cache_key, result, subdirectory="flight")
        
        return result
    
    async def search_flights_by_route(self, dep: str, arr: str, date: str, use_city: bool = False) -> dict:
        """根据航线查询航班"""
        cache_key = f"flight:route:{dep}:{arr}:{date}:{use_city}"
        cached = await self.cache_manager.load_cache(
            cache_key,
            max_age_seconds=600,  # 10分钟缓存
            subdirectory="flight"
        )
        if cached:
            return cached
            
        params = {"date": date}
        if use_city:
            params["depcity"] = dep.upper()
            params["arrcity"] = arr.upper()
        else:
            params["dep"] = dep.upper()
            params["arr"] = arr.upper()
            
        result = await self._make_request("flights", params)
        
        if result and self.cache_manager:
            await self.cache_manager.save_cache(cache_key, result, subdirectory="flight")
        
        return result
    
    async def get_airport_weather(self, airport: str) -> dict:
        """获取机场天气预报"""
        cache_key = f"flight:weather:{airport}"
        cached = await self.cache_manager.load_cache(
            cache_key,
            max_age_seconds=1800,  # 30分钟缓存
            subdirectory="flight"
        )
        if cached:
            return cached
            
        result = await self._make_request("futureAirportWeather", {
            "code": airport.upper(),
            "type": "1"
        })
        
        if result and self.cache_manager:
            await self.cache_manager.save_cache(cache_key, result, subdirectory="flight")
        
        return result
    
    async def get_flight_happiness_index(self, flight_num: str, date: str) -> dict:
        """获取航班舒适度指数"""
        cache_key = f"flight:happiness:{flight_num}:{date}"
        cached = await self.cache_manager.load_cache(
            cache_key,
            max_age_seconds=3600,  # 1小时缓存
            subdirectory="flight"
        )
        if cached:
            return cached
            
        result = await self._make_request("happiness", {
            "fnum": flight_num.upper(),
            "date": date
        })
        
        if result and self.cache_manager:
            await self.cache_manager.save_cache(cache_key, result, subdirectory="flight")
        
        return result
    
    async def search_flight_itineraries(self, dep_city: str, arr_city: str, dep_date: str) -> dict:
        """搜索可购买的航班行程"""
        cache_key = f"flight:itinerary:{dep_city}:{arr_city}:{dep_date}"
        cached = await self.cache_manager.load_cache(
            cache_key,
            max_age_seconds=1800,  # 30分钟缓存
            subdirectory="flight"
        )
        if cached:
            return cached
            
        result = await self._make_request("searchFlightItineraries", {
            "depCityCode": dep_city.upper(),
            "arrCityCode": arr_city.upper(),
            "depDate": dep_date
        })
        
        if result and self.cache_manager:
            await self.cache_manager.save_cache(cache_key, result, subdirectory="flight")
        
        return result


def set_dependencies(cm, hc):
    """设置依赖项"""
    global cache_manager, httpx_client, flight_service
    cache_manager = cm
    httpx_client = hc
    flight_service = VariflightService(cache_manager, httpx_client)


async def _schedule_auto_delete(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, delay: int):
    """调度自动删除消息"""
    try:
        if context and hasattr(context, "bot_data"):
            scheduler = context.bot_data.get("message_delete_scheduler")
            if scheduler and hasattr(scheduler, "schedule_deletion"):
                await scheduler.schedule_deletion(chat_id, message_id, delay, None)
                logger.info(f"已调度航班消息删除: chat_id={chat_id}, message_id={message_id}, delay={delay}s")
    except Exception as e:
        logger.error(f"调度自动删除失败: {e}")


def format_flight_info(flight_data: dict) -> str:
    """格式化航班信息"""
    if not flight_data or not flight_data.get("data"):
        return "❌ 未找到航班信息"
    
    data = flight_data["data"]
    if isinstance(data, list):
        if not data:
            return "❌ 未找到航班信息"
        data = data[0]  # 取第一个结果
    
    # 根据实际API返回格式提取信息
    flight_num = data.get("FlightNo", "未知")
    dep_airport = data.get("FlightDepcode", "")
    arr_airport = data.get("FlightArrcode", "")
    dep_city = data.get("FlightDep", "")
    arr_city = data.get("FlightArr", "")
    
    # 时间信息 - 格式化为 HH:MM
    def format_time(time_str):
        if not time_str:
            return ""
        try:
            # 从 "2025-08-22 12:00:00" 提取 "12:00"
            return time_str.split(" ")[1][:5]
        except:
            return time_str
    
    std = format_time(data.get("FlightDeptimePlanDate", ""))  # 计划起飞
    sta = format_time(data.get("FlightArrtimePlanDate", ""))  # 计划到达
    etd = format_time(data.get("FlightDeptimeDate", ""))      # 实际起飞
    eta = format_time(data.get("FlightArrtimeDate", ""))      # 实际到达
    
    # 状态信息
    status = data.get("FlightState", "")
    airline = data.get("FlightCompany", "")
    
    formatted = f"""✈️ *{flight_num} 航班信息*

📍 *航线*: {dep_city} \\({dep_airport}\\) → {arr_city} \\({arr_airport}\\)

⏰ *时间安排*:
🛫 计划起飞: `{std}`
🛬 计划到达: `{sta}`"""

    if etd and etd != std:
        formatted += f"\n🕐 实际起飞: `{etd}`"
    if eta and eta != sta:
        formatted += f"\n🕐 实际到达: `{eta}`"
    
    if status:
        formatted += f"\n\n📊 *状态*: {status}"
    
    if airline:
        formatted += f"\n🏢 *航空公司*: {airline}"
    
    formatted += f"\n\n_更新时间: {datetime.now().strftime('%H:%M:%S')}_"
    
    return formatted


def format_route_flights(flights_data: dict, dep_city: str = "", arr_city: str = "") -> str:
    """格式化航线航班列表"""
    if not flights_data or not flights_data.get("data"):
        return "❌ 未找到航班信息"
    
    data = flights_data["data"]
    if not isinstance(data, list) or not data:
        return "❌ 未找到航班信息"
    
    # 限制显示前8个航班
    flights = data[:8]
    
    route_display = f"{dep_city}→{arr_city}" if dep_city and arr_city else "航班"
    formatted = f"✈️ *{route_display} - 找到 {len(data)} 个航班*\n\n"
    
    for i, flight in enumerate(flights, 1):
        # 使用正确的字段名
        flight_num = flight.get("FlightNo", "未知")
        airline = flight.get("FlightCompany", "")
        
        # 格式化时间
        def format_time(time_str):
            if not time_str:
                return ""
            try:
                return time_str.split(" ")[1][:5]
            except:
                return time_str
        
        std = format_time(flight.get("FlightDeptimePlanDate", ""))
        sta = format_time(flight.get("FlightArrtimePlanDate", ""))
        status = flight.get("FlightState", "")
        
        # 显示航空公司和航班号
        display_name = f"{airline} {flight_num}" if airline else flight_num
        # 简化航空公司名称显示
        if "有限公司" in airline:
            airline_short = airline.replace("有限公司", "").replace("股份", "")
            display_name = f"{airline_short} {flight_num}"
        
        formatted += f"*{i}\\. {display_name}*\n"
        formatted += f"🕐 `{std}` \\- `{sta}`"
        
        if status and status != "正常":
            formatted += f" | {status}"
        
        formatted += "\n\n"
    
    if len(data) > 8:
        formatted += f"\\.\\.\\. 还有 {len(data) - 8} 个航班\n"
    
    formatted += f"_更新时间: {datetime.now().strftime('%H:%M:%S')}_"
    
    return formatted


def format_weather_info(weather_data: dict) -> str:
    """格式化天气信息"""
    if not weather_data or not weather_data.get("data"):
        return "❌ 未找到天气信息"
    
    data = weather_data["data"]
    
    # 根据实际API测试结果，data包含current和future字段
    if not isinstance(data, dict):
        return "❌ 天气数据格式错误"
    
    current = data.get("current", {})
    future = data.get("future", {})
    
    # 提取机场信息
    airport_name = future.get("aptCname", current.get("AirportCity", "未知机场"))
    city_name = future.get("cityCname", "")
    
    formatted = f"🌤️ *{airport_name} 天气预报*\n\n"
    
    # 当前天气
    if current:
        temp = current.get("Temperature", "")
        weather_type = current.get("Type", "")
        wind_info = current.get("WindPower", "")
        wind_dir = current.get("WindDirection", "")
        pm25 = current.get("PM2.5", "")
        quality = current.get("Quality", "")
        
        formatted += f"📍 **当前天气** ({city_name})\n"
        formatted += f"🌡️ 温度: {temp}°C\n"
        formatted += f"☁️ 天气: {weather_type}\n"
        if wind_info and wind_dir:
            formatted += f"💨 风力: {wind_dir} {wind_info}\n"
        if pm25 and quality:
            formatted += f"🌫️ PM2.5: {pm25} ({quality})\n"
        formatted += "\n"
    
    # 未来天气预报
    if future and "detail" in future and future["detail"]:
        formatted += f"📅 **未来3天预报**:\n\n"
        
        for day_info in future["detail"][:3]:  # 显示3天
            date = day_info.get("date", "")
            sky_desc = day_info.get("d_skydesc", "").replace("CLEAR_DAY", "晴").replace("CLOUDY", "多云").replace("RAIN", "雨")
            temp_info = day_info.get("d_temperature", {})
            
            if temp_info:
                max_temp = temp_info.get("max", "")
                min_temp = temp_info.get("min", "")
                formatted += f"**{date}**: {sky_desc} {min_temp}°-{max_temp}°C\n"
            else:
                formatted += f"**{date}**: {sky_desc}\n"
    
    formatted += f"\n_数据来源: Variflight_"
    formatted += f"\n_更新时间: {datetime.now().strftime('%H:%M:%S')}_"
    
    return formatted


@with_error_handling
async def flight_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """航班查询主命令 /flight"""
    if not update.message:
        return
    
    # 检查服务是否可用
    if not flight_service or not config.variflight_api_key:
        await send_error(
            context,
            update.message.chat_id,
            "❌ 航班服务未配置或API密钥无效，请联系管理员"
        )
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        return
    
    # 如果有参数，尝试智能解析并直接查询
    if context.args:
        query = " ".join(context.args)
        await _handle_smart_query(update, context, query)
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        return
    
    # 没有参数，显示主菜单
    keyboard = [
        [
            InlineKeyboardButton("🔍 航班号查询", callback_data="flight_search_number"),
            InlineKeyboardButton("🛣️ 航线查询", callback_data="flight_search_route")
        ],
        [
            InlineKeyboardButton("🌤️ 机场天气", callback_data="flight_weather"),
            InlineKeyboardButton("😊 舒适度指数", callback_data="flight_happiness")
        ],
        [
            InlineKeyboardButton("💰 机票价格", callback_data="flight_price"),
            InlineKeyboardButton("🔄 中转查询", callback_data="flight_transfer")
        ],
        [
            InlineKeyboardButton("❌ 关闭", callback_data="flight_close")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    help_text = """✈️ 智能航班服务

🌍 功能介绍:
• **航班号查询**: 根据航班号查询实时信息
• **航线查询**: 查询特定航线的所有航班
• **机场天气**: 获取机场未来3天天气预报
• **舒适度指数**: 查询航班舒适度评分
• **机票价格**: 搜索可购买的航班选项和价格
• **中转查询**: 查找最佳中转航班方案

💡 智能搜索:
`/flight MU2157` \\- 查询东航2157航班
`/flight 北京 上海` \\- 中文城市名称搜索
`/flight Beijing Shanghai` \\- 英文城市名称搜索
`/flight PEK SHA 明天` \\- 机场代码\\+日期
`/flight MU2157 Dec 25` \\- 多种日期格式

🎯 特色功能:
• 支持中英文城市名称智能转换
• 支持多种日期格式解析
• 提供实时机票价格查询

请选择功能:"""
    
    await send_message_with_auto_delete(
        context=context,
        chat_id=update.message.chat_id,
        text=foldable_text_with_markdown_v2(help_text),
        parse_mode="MarkdownV2",
        reply_markup=reply_markup
    )
    
    await delete_user_command(context, update.message.chat_id, update.message.message_id)


async def _handle_smart_query(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str) -> None:
    """处理智能查询（智能识别）"""
    try:
        # 尝试解析为航班号
        flight_num, date = FlightSearchHelper.parse_flight_input(query)
        if flight_num:
            # 航班号查询
            loading_message = f"🔍 正在查询 {flight_num} 航班信息\\.\\.\\. ⏳"
            message = await context.bot.send_message(
                chat_id=update.message.chat_id,
                text=foldable_text_v2(loading_message),
                parse_mode="MarkdownV2"
            )
            await _schedule_auto_delete(context, message.chat_id, message.message_id, config.auto_delete_delay)
            
            result = await flight_service.search_flight_by_number(flight_num, date)
            formatted_result = format_flight_info(result)
            
            keyboard = [
                [
                    InlineKeyboardButton("😊 舒适度指数", callback_data=f"flight_happiness_direct:{flight_num}:{date}"),
                    InlineKeyboardButton("🔄 换个日期", callback_data=f"flight_number_date:{flight_num}")
                ],
                [
                    InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await message.edit_text(
                text=foldable_text_with_markdown_v2(formatted_result),
                parse_mode="MarkdownV2",
                reply_markup=reply_markup
            )
            return
        
        # 尝试解析为航线
        dep_code, arr_code, date = FlightSearchHelper.parse_route_input(query)
        if dep_code and arr_code:
            # 获取城市显示名称
            dep_city = FlightSearchHelper.get_city_display_name(dep_code)
            arr_city = FlightSearchHelper.get_city_display_name(arr_code)
            
            loading_message = f"🔍 正在查询 {dep_city}→{arr_city} 航线\\.\\.\\. ⏳"
            message = await context.bot.send_message(
                chat_id=update.message.chat_id,
                text=foldable_text_v2(loading_message),
                parse_mode="MarkdownV2"
            )
            await _schedule_auto_delete(context, message.chat_id, message.message_id, config.auto_delete_delay)
            
            result = await flight_service.search_flights_by_route(dep_code, arr_code, date)
            formatted_result = format_route_flights(result, dep_city, arr_city)
            
            keyboard = [
                [
                    InlineKeyboardButton("🔄 换个日期", callback_data=f"flight_route_date:{dep_code}:{arr_code}"),
                    InlineKeyboardButton("💰 机票价格", callback_data=f"flight_price_direct:{dep_code}:{arr_code}:{date}")
                ],
                [
                    InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await message.edit_text(
                text=foldable_text_with_markdown_v2(formatted_result),
                parse_mode="MarkdownV2",
                reply_markup=reply_markup
            )
            return
        
        # 无法识别的格式，显示智能帮助
        error_msg = """❌ *无法识别输入格式*

*支持的智能搜索*:
• `MU2157` \\- 航班号查询
• `MU2157 明天` \\- 指定日期查询  
• `北京 上海` \\- 城市名称查询
• `PEK SHA` \\- 机场代码查询
• `Beijing Shanghai 12\\-25` \\- 英文城市+日期

*示例*:
• `/flight 东航2157`
• `/flight 北京 上海 明天`
• `/flight PEK SHA Dec 25`

请重新输入或选择菜单功能"""

        keyboard = [
            [InlineKeyboardButton("📋 查看功能菜单", callback_data="flight_main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = await context.bot.send_message(
            chat_id=update.message.chat_id,
            text=foldable_text_with_markdown_v2(error_msg),
            parse_mode="MarkdownV2",
            reply_markup=reply_markup
        )
        await _schedule_auto_delete(context, message.chat_id, message.message_id, config.auto_delete_delay)
        
    except Exception as e:
        error_msg = f"❌ 查询失败: {str(e)}"
        message = await context.bot.send_message(
            chat_id=update.message.chat_id,
            text=error_msg
        )
        await _schedule_auto_delete(context, message.chat_id, message.message_id, config.auto_delete_delay)


async def flight_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理航班功能的文本输入"""
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
        
        if action == "flight_number_search" and waiting_for == "flight_number":
            # 处理航班号输入
            flight_num, date = FlightSearchHelper.parse_flight_input(text)
            
            if not flight_num:
                await send_error(context, update.message.chat_id, "航班号格式错误，请输入如 MU2157 的格式")
                return
            
            await _execute_flight_number_search(update, context, flight_num, date)
            flight_session_manager.remove_session(user_id)
            
        elif action == "route_search" and waiting_for == "route":
            # 处理航线输入
            dep_code, arr_code, date = FlightSearchHelper.parse_route_input(text)
            
            if not dep_code or not arr_code:
                await send_error(context, update.message.chat_id, "请输入出发地和目的地，如：北京 上海 或 PEK SHA")
                return
            
            await _execute_route_search(update, context, dep_code, arr_code, date)
            flight_session_manager.remove_session(user_id)
            
        elif action == "airport_weather" and waiting_for == "airport":
            # 处理机场天气查询
            # 尝试智能转换城市/机场代码
            airport_code = FlightSearchHelper.convert_to_airport_code(text)
            
            if not airport_code:
                await send_error(context, update.message.chat_id, "无法识别机场，请输入如：北京、PEK、Beijing 等")
                return
                
            await _execute_weather_search(update, context, airport_code)
            flight_session_manager.remove_session(user_id)
            
        elif action == "happiness_search" and waiting_for == "flight_info":
            # 处理舒适度查询
            flight_num, date = FlightSearchHelper.parse_flight_input(text)
            
            if not flight_num:
                await send_error(context, update.message.chat_id, "航班号格式错误，请输入如 MU2157 的格式")
                return
            
            await _execute_happiness_search(update, context, flight_num, date)
            flight_session_manager.remove_session(user_id)
            
        elif action == "price_search" and waiting_for == "route_info":
            # 处理机票价格查询
            dep_code, arr_code, date = FlightSearchHelper.parse_route_input(text)
            
            if not dep_code or not arr_code:
                await send_error(context, update.message.chat_id, "请输入出发地和目的地，如：北京 上海 或 PEK SHA")
                return
            
            await _execute_price_search(update, context, dep_code, arr_code, date)
            flight_session_manager.remove_session(user_id)
            
    except Exception as e:
        logger.error(f"处理航班文本输入失败: {e}")
        await send_error(context, update.message.chat_id, f"处理失败: {str(e)}")
        flight_session_manager.remove_session(user_id)


async def _execute_flight_number_search(update: Update, context: ContextTypes.DEFAULT_TYPE, flight_num: str, date: str) -> None:
    """执行航班号查询"""
    loading_message = f"🔍 正在查询 {flight_num} 航班信息\\.\\.\\. ⏳"
    
    message = await context.bot.send_message(
        chat_id=update.message.chat_id,
        text=foldable_text_v2(loading_message),
        parse_mode="MarkdownV2"
    )
    await _schedule_auto_delete(context, message.chat_id, message.message_id, config.auto_delete_delay)
    
    try:
        result = await flight_service.search_flight_by_number(flight_num, date)
        formatted_result = format_flight_info(result)
        
        keyboard = [
            [
                InlineKeyboardButton("😊 舒适度指数", callback_data=f"flight_happiness_direct:{flight_num}:{date}"),
                InlineKeyboardButton("🔄 换个日期", callback_data=f"flight_number_date:{flight_num}")
            ],
            [
                InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await message.edit_text(
            text=foldable_text_with_markdown_v2(formatted_result),
            parse_mode="MarkdownV2",
            reply_markup=reply_markup
        )
        
    except Exception as e:
        error_msg = f"❌ 航班查询失败: {str(e)}"
        keyboard = [
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await message.edit_text(
            text=error_msg,
            reply_markup=reply_markup
        )


async def _execute_route_search(update: Update, context: ContextTypes.DEFAULT_TYPE, dep_code: str, arr_code: str, date: str) -> None:
    """执行航线查询"""
    dep_city = FlightSearchHelper.get_city_display_name(dep_code)
    arr_city = FlightSearchHelper.get_city_display_name(arr_code)
    loading_message = f"🔍 正在查询 {dep_city}→{arr_city} 航线\\.\\.\\. ⏳"
    
    message = await context.bot.send_message(
        chat_id=update.message.chat_id,
        text=foldable_text_v2(loading_message),
        parse_mode="MarkdownV2"
    )
    await _schedule_auto_delete(context, message.chat_id, message.message_id, config.auto_delete_delay)
    
    try:
        result = await flight_service.search_flights_by_route(dep_code, arr_code, date)
        formatted_result = format_route_flights(result, dep_city, arr_city)
        
        keyboard = [
            [
                InlineKeyboardButton("🔄 换个日期", callback_data=f"flight_route_date:{dep_code}:{arr_code}"),
                InlineKeyboardButton("💰 机票价格", callback_data=f"flight_price_direct:{dep_code}:{arr_code}:{date}")
            ],
            [
                InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await message.edit_text(
            text=foldable_text_with_markdown_v2(formatted_result),
            parse_mode="MarkdownV2",
            reply_markup=reply_markup
        )
        
    except Exception as e:
        error_msg = f"❌ 航线查询失败: {str(e)}"
        keyboard = [
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await message.edit_text(
            text=error_msg,
            reply_markup=reply_markup
        )


async def _execute_weather_search(update: Update, context: ContextTypes.DEFAULT_TYPE, airport: str) -> None:
    """执行机场天气查询"""
    loading_message = f"🌤️ 正在查询 {airport} 机场天气\\.\\.\\. ⏳"
    
    message = await context.bot.send_message(
        chat_id=update.message.chat_id,
        text=foldable_text_v2(loading_message),
        parse_mode="MarkdownV2"
    )
    await _schedule_auto_delete(context, message.chat_id, message.message_id, config.auto_delete_delay)
    
    try:
        result = await flight_service.get_airport_weather(airport)
        formatted_result = format_weather_info(result)
        
        keyboard = [
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await message.edit_text(
            text=foldable_text_with_markdown_v2(formatted_result),
            parse_mode="MarkdownV2",
            reply_markup=reply_markup
        )
        
    except Exception as e:
        error_msg = f"❌ 天气查询失败: {str(e)}"
        keyboard = [
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await message.edit_text(
            text=error_msg,
            reply_markup=reply_markup
        )


async def _execute_price_search(update: Update, context: ContextTypes.DEFAULT_TYPE, dep_code: str, arr_code: str, date: str) -> None:
    """执行机票价格搜索"""
    dep_city = FlightSearchHelper.get_city_display_name(dep_code)
    arr_city = FlightSearchHelper.get_city_display_name(arr_code)
    loading_message = f"💰 正在查询 {dep_city}→{arr_city} 机票价格\\.\\.\\. ⏳"
    
    message = await context.bot.send_message(
        chat_id=update.message.chat_id,
        text=foldable_text_v2(loading_message),
        parse_mode="MarkdownV2"
    )
    await _schedule_auto_delete(context, message.chat_id, message.message_id, config.auto_delete_delay)
    
    try:
        result = await flight_service.search_flight_itineraries(dep_code, arr_code, date)
        formatted_result = format_price_info(result)
        
        keyboard = [
            [
                InlineKeyboardButton("🔄 换个日期", callback_data=f"flight_price_date:{dep_code}:{arr_code}"),
                InlineKeyboardButton("✈️ 查看航班", callback_data=f"flight_route_direct:{dep_code}:{arr_code}:{date}")
            ],
            [
                InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await message.edit_text(
            text=foldable_text_with_markdown_v2(formatted_result),
            parse_mode="MarkdownV2",
            reply_markup=reply_markup
        )
        
    except Exception as e:
        error_msg = f"❌ 价格查询失败: {str(e)}"
        keyboard = [
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await message.edit_text(
            text=error_msg,
            reply_markup=reply_markup
        )


async def _execute_happiness_search(update: Update, context: ContextTypes.DEFAULT_TYPE, flight_num: str, date: str) -> None:
    """执行航班舒适度查询"""
    loading_message = f"😊 正在查询 {flight_num} 舒适度指数\\.\\.\\. ⏳"
    
    message = await context.bot.send_message(
        chat_id=update.message.chat_id,
        text=foldable_text_v2(loading_message),
        parse_mode="MarkdownV2"
    )
    await _schedule_auto_delete(context, message.chat_id, message.message_id, config.auto_delete_delay)
    
    try:
        result = await flight_service.get_flight_happiness_index(flight_num, date)
        
        # 格式化舒适度信息
        formatted_result = f"😊 *{flight_num} 舒适度指数*\n\n"
        if result.get("data"):
            data = result["data"]
            # 根据实际API返回格式调整显示
            formatted_result += f"📊 舒适度信息: {str(data)}\n\n"
        else:
            formatted_result += "❌ 暂无舒适度信息\n\n"
        
        formatted_result += f"_更新时间: {datetime.now().strftime('%H:%M:%S')}_"
        
        keyboard = [
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await message.edit_text(
            text=foldable_text_with_markdown_v2(formatted_result),
            parse_mode="MarkdownV2",
            reply_markup=reply_markup
        )
        
    except Exception as e:
        error_msg = f"❌ 舒适度查询失败: {str(e)}"
        keyboard = [
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await message.edit_text(
            text=error_msg,
            reply_markup=reply_markup
        )


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
                InlineKeyboardButton("🔍 航班号查询", callback_data="flight_search_number"),
                InlineKeyboardButton("🛣️ 航线查询", callback_data="flight_search_route")
            ],
            [
                InlineKeyboardButton("🌤️ 机场天气", callback_data="flight_weather"),
                InlineKeyboardButton("😊 舒适度指数", callback_data="flight_happiness")
            ],
            [
                InlineKeyboardButton("💰 机票价格", callback_data="flight_price"),
                InlineKeyboardButton("🔄 中转查询", callback_data="flight_transfer")
            ],
            [
                InlineKeyboardButton("❌ 关闭", callback_data="flight_close")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        help_text = """✈️ 智能航班服务

🌍 功能介绍:
• **航班号查询**: 根据航班号查询实时信息
• **航线查询**: 查询特定航线的所有航班
• **机场天气**: 获取机场未来3天天气预报
• **舒适度指数**: 查询航班舒适度评分
• **机票价格**: 搜索可购买的航班选项和价格
• **中转查询**: 查找最佳中转航班方案

💡 智能搜索:
`/flight MU2157` \\- 查询东航2157航班
`/flight 北京 上海` \\- 中文城市名称搜索
`/flight Beijing Shanghai` \\- 英文城市名称搜索
`/flight PEK SHA 明天` \\- 机场代码\\+日期
`/flight MU2157 Dec 25` \\- 多种日期格式

🎯 特色功能:
• 支持中英文城市名称智能转换
• 支持多种日期格式解析
• 提供实时机票价格查询

请选择功能:"""
        
        await query.edit_message_text(
            text=foldable_text_with_markdown_v2(help_text),
            parse_mode="MarkdownV2",
            reply_markup=reply_markup
        )
    
    elif data == "flight_search_number":
        user_id = update.effective_user.id
        
        # 设置会话状态
        flight_session_manager.set_session(user_id, {
            "action": "flight_number_search",
            "waiting_for": "flight_number"
        })
        
        await query.edit_message_text(
            text="🔍 请输入航班号和日期（可选）:\n\n例如:\n• MU2157\n• MU2157 明天\n• CZ3969 12-25",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
            ])
        )
    
    elif data == "flight_search_route":
        user_id = update.effective_user.id
        
        # 设置会话状态
        flight_session_manager.set_session(user_id, {
            "action": "route_search",
            "waiting_for": "route"
        })
        
        await query.edit_message_text(
            text="🛣️ 请输入航线信息:\n\n格式: 出发地 目的地 日期（可选）\n\n例如:\n• 北京 上海\n• PEK SHA 明天\n• Beijing Shanghai 12-25",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
            ])
        )
    
    elif data == "flight_weather":
        user_id = update.effective_user.id
        
        # 设置会话状态
        flight_session_manager.set_session(user_id, {
            "action": "airport_weather",
            "waiting_for": "airport"
        })
        
        await query.edit_message_text(
            text="🌤️ 请输入机场或城市名称:\n\n例如:\n• 北京 (自动转换为PEK)\n• 上海 (自动识别虹桥/浦东)\n• PEK (北京首都)\n• Beijing",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
            ])
        )
    
    elif data == "flight_happiness":
        user_id = update.effective_user.id
        
        # 设置会话状态
        flight_session_manager.set_session(user_id, {
            "action": "happiness_search", 
            "waiting_for": "flight_info"
        })
        
        await query.edit_message_text(
            text="😊 请输入航班号和日期（可选）:\n\n例如:\n• MU2157\n• MU2157 明天\n• CZ3969 12-25",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
            ])
        )
    
    elif data.startswith("flight_happiness_direct:"):
        # 直接查询舒适度指数
        parts = data.split(":", 2)
        flight_num = parts[1]
        date = parts[2]
        
        await _execute_happiness_search(update, context, flight_num, date)
    
    elif data == "flight_price":
        user_id = update.effective_user.id
        
        # 设置会话状态
        flight_session_manager.set_session(user_id, {
            "action": "price_search",
            "waiting_for": "route_info"
        })
        
        await query.edit_message_text(
            text="💰 请输入航线信息查询机票价格:\n\n格式: 出发地 目的地 日期（可选）\n\n例如:\n• 北京 上海 明天\n• PEK SHA 12-25\n• Beijing Shanghai Dec 25",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
            ])
        )
    
    elif data.startswith("flight_price_direct:"):
        # 直接查询机票价格
        parts = data.split(":", 3)
        dep_code = parts[1]
        arr_code = parts[2] 
        date = parts[3]
        
        await _execute_price_search(update, context, dep_code, arr_code, date)
    
    elif data == "flight_transfer":
        await query.edit_message_text(
            text="🔄 中转查询功能开发中...\n\n此功能将帮助您查找最佳的中转航班方案",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
            ])
        )


# =============================================================================
# 注册命令和回调
# =============================================================================

# 注册主命令（白名单用户权限）
command_factory.register_command(
    "flight",
    flight_command,
    permission=Permission.USER,
    description="✈️ 智能航班服务 - 航班查询、天气预报、舒适度指数、机票价格"
)

# 注册回调处理器
command_factory.register_callback(r"^flight_", flight_callback_handler, permission=Permission.USER, description="航班服务回调")

# 注册文本消息处理器
command_factory.register_text_handler(flight_text_handler, permission=Permission.USER, description="航班服务文本输入处理")

logger.info("✅ 航班查询模块已加载")