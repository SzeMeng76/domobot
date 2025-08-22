#!/usr/bin/env python3
"""
机票查询命令模块
提供机票搜索、价格比较、机场查询等功能
参考map.py的实现结构，支持交互式界面和智能搜索
"""

import asyncio
import logging
import re
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, CallbackQuery
from telegram.ext import ContextTypes, CallbackQueryHandler
from telegram.constants import ParseMode

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
from utils.flight_service import get_flight_service, FlightService
from utils.airport_data import get_airport_data, AirportData

logger = logging.getLogger(__name__)

# 全局变量
cache_manager = None
httpx_client = None
flight_service = None
airport_data = None

# 机票数据ID映射缓存
flight_data_mapping = {}
mapping_counter = 0

# 创建机票会话管理器
flight_session_manager = SessionManager("FlightService", max_age=1800, max_sessions=200)  # 30分钟会话

async def _schedule_auto_delete(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, delay: int):
    """调度自动删除消息"""
    try:
        if context and hasattr(context, "bot_data"):
            scheduler = context.bot_data.get("message_delete_scheduler")
            if scheduler and hasattr(scheduler, "schedule_deletion"):
                await scheduler.schedule_deletion(chat_id, message_id, delay, None)
                logger.info(f"已调度机票消息删除: chat_id={chat_id}, message_id={message_id}, delay={delay}s")
            else:
                logger.warning(f"消息删除调度器未正确初始化: scheduler={scheduler}")
        else:
            logger.warning("无法获取bot_data或context")
    except Exception as e:
        logger.error(f"调度自动删除失败: {e}")

def set_dependencies(cm, hc=None):
    """设置依赖项"""
    global cache_manager, httpx_client, flight_service, airport_data
    cache_manager = cm
    httpx_client = hc
    
    # 初始化机票服务，使用全局cache_manager
    from utils.flight_service import set_dependencies as set_flight_service_deps
    set_flight_service_deps(cache_manager, None)  # rate_converter将在main.py中单独注入
    
    flight_service = get_flight_service()
    
    # 初始化机场数据
    airport_data = get_airport_data()
    if not airport_data:
        from utils.airport_data import init_airport_data
        airport_data = init_airport_data()

def get_short_flight_id(data_id: str) -> str:
    """生成短ID用于callback_data"""
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
        old_keys = list(flight_data_mapping.keys())[:50]
        for key in old_keys:
            del flight_data_mapping[key]
    
    return short_id

def get_full_flight_id(short_id: str) -> Optional[str]:
    """根据短ID获取完整数据ID"""
    return flight_data_mapping.get(short_id)

def format_price_trend(trend: str) -> str:
    """格式化价格趋势显示"""
    trend_map = {
        "low": "📉 较低",
        "typical": "📊 正常", 
        "high": "📈 较高"
    }
    return trend_map.get(trend, f"❓ {trend}")

def format_flight_result(flight_data: Dict[str, Any]) -> str:
    """格式化航班查询结果"""
    try:
        search_info = flight_data.get("search_info", {})
        price_trend = flight_data.get("price_trend", "unknown")
        flights = flight_data.get("flights", [])
        
        if not flights:
            return "❌ 未找到航班信息"
        
        # 获取机场信息用于显示
        origin_info = airport_data.get_airport_info(search_info.get("origin", ""))
        dest_info = airport_data.get_airport_info(search_info.get("destination", ""))
        
        origin_display = origin_info["city_cn"] if origin_info else search_info.get("origin", "")
        dest_display = dest_info["city_cn"] if dest_info else search_info.get("destination", "")
        
        result = f"✈️ **{origin_display} → {dest_display}** 航班查询\n\n"
        result += f"📅 {search_info.get('departure_date', '')} | "
        result += f"🎯 {search_info.get('trip_type', '').replace('-', ' ').title()}\n"
        result += f"📊 价格趋势: {format_price_trend(price_trend)}\n\n"
        
        # 显示最多5个航班
        for i, flight in enumerate(flights[:5], 1):
            is_best = flight.get("is_best", False)
            prefix = "🏆" if is_best else f"`{i:2d}.`"
            
            result += f"{prefix} **{flight.get('airline', 'Unknown')}**\n"
            result += f"     🛫 {flight.get('departure_time', '')} → 🛬 {flight.get('arrival_time', '')}\n"
            
            duration = flight.get('duration', '')
            stops = flight.get('stops', 0)
            if isinstance(stops, int):
                stops_text = "直飞" if stops == 0 else f"{stops}次中转"
            else:
                stops_text = str(stops)
            
            result += f"     ⏱️ {duration} | 🔄 {stops_text}"
            
            # 延误信息
            delay = flight.get('delay')
            if delay:
                result += f" | ⚠️ {delay}"
            
            result += f"\n     💰 **{flight.get('price', 'N/A')}**\n\n"
        
        if len(flights) > 5:
            result += f"_...还有 {len(flights) - 5} 个航班选项_\n\n"
        
        result += f"🕐 查询时间: {datetime.now().strftime('%H:%M:%S')}\n"
        result += "_数据来源: Google Flights_"
        
        return result
        
    except Exception as e:
        logger.error(f"格式化航班结果失败: {e}")
        return f"❌ 格式化结果时出错: {str(e)}"

def format_airport_search_results(airports: List[Dict[str, Any]], query: str) -> str:
    """格式化机场搜索结果"""
    if not airports:
        return f"❌ 未找到匹配 '{query}' 的机场"
    
    result = f"✈️ **机场搜索结果**: `{query}`\n\n"
    
    for i, airport in enumerate(airports[:8], 1):  # 显示前8个结果
        country_flag = airport.get("country_flag", "🏳️")
        result += f"`{i:2d}.` {country_flag} **{airport['code']}** - {airport['city_cn']} ({airport['city']})\n"
        result += f"     {airport['name_cn']}\n"
        result += f"     _{airport['name']}_\n\n"
    
    if len(airports) > 8:
        result += f"_...还有 {len(airports) - 8} 个匹配结果_\n\n"
    
    result += f"💡 点击下方按钮选择机场进行查询\n"
    result += f"🕐 搜索时间: {datetime.now().strftime('%H:%M:%S')}"
    
    return result

async def flights_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """机票查询主命令 /flights"""
    if not update.message:
        return
    
    # 检查是否可用
    if not flight_service:
        await send_error(
            context,
            update.message.chat_id,
            "❌ 机票服务未初始化，请联系管理员"
        )
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        return
    
    # 如果有参数，尝试解析为快速查询
    if context.args:
        query = " ".join(context.args)
        await _handle_quick_search(update, context, query)
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        return
    
    # 没有参数，显示主菜单
    keyboard = [
        [
            InlineKeyboardButton("✈️ 机票查询", callback_data="flight_search"),
            InlineKeyboardButton("🔍 机场搜索", callback_data="airport_search")
        ],
        [
            InlineKeyboardButton("🔥 热门航线", callback_data="popular_routes"),
            InlineKeyboardButton("📊 价格监控", callback_data="price_monitor")
        ],
        [
            InlineKeyboardButton("❌ 关闭", callback_data="flight_close")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    help_text = """✈️ **智能机票查询服务**

🌟 **功能特色**:
• **机票查询**: 单程/往返机票价格比较
• **智能搜索**: 支持城市名、机场代码查询
• **机场搜索**: 全球机场信息查询
• **热门航线**: 推荐热门旅行路线
• **价格监控**: 跟踪价格变化趋势

🚀 **快速使用**:
`/flights 北京 纽约` - 快速查询机票
`/flights PEK LAX 2025-03-15` - 指定日期查询

🤖 **智能特性**:
• 支持中英文城市名查询
• 自动识别机场代码
• 实时价格趋势分析
• 多种舱位等级选择

请选择功能开始使用:"""
    
    await send_message_with_auto_delete(
        context=context,
        chat_id=update.message.chat_id,
        text=foldable_text_with_markdown_v2(help_text),
        parse_mode="MarkdownV2",
        reply_markup=reply_markup
    )
    
    await delete_user_command(context, update.message.chat_id, update.message.message_id)

async def _handle_quick_search(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str) -> None:
    """处理快速搜索"""
    try:
        parts = query.strip().split()
        
        if len(parts) < 2:
            await send_error(context, update.message.chat_id, 
                           "格式错误，请使用: /flights [起点] [终点] [日期(可选)]")
            return
        
        origin = parts[0]
        destination = parts[1]
        departure_date = parts[2] if len(parts) > 2 else (date.today() + timedelta(days=7)).isoformat()
        
        await _execute_flight_search(update, context, origin, destination, departure_date)
        
    except Exception as e:
        logger.error(f"快速搜索失败: {e}")
        await send_error(context, update.message.chat_id, f"搜索失败: {str(e)}")

async def _execute_flight_search(
    update: Update, 
    context: ContextTypes.DEFAULT_TYPE, 
    origin: str, 
    destination: str, 
    departure_date: str,
    return_date: Optional[str] = None,
    callback_query: CallbackQuery = None
) -> None:
    """执行机票搜索"""
    
    loading_message = f"🔍 正在搜索航班: {origin} → {destination}... ⏳"
    
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
        # 解析机场代码
        origin_airports = airport_data.search_airports(origin, 1)
        dest_airports = airport_data.search_airports(destination, 1)
        
        if not origin_airports:
            error_msg = f"❌ 未找到起点机场: {origin}"
            await _send_search_error(callback_query, message, context, error_msg)
            return
        
        if not dest_airports:
            error_msg = f"❌ 未找到终点机场: {destination}"
            await _send_search_error(callback_query, message, context, error_msg)
            return
        
        origin_code = origin_airports[0]["code"]
        dest_code = dest_airports[0]["code"]
        
        # 查询航班
        flight_result = await flight_service.get_flight_prices(
            origin=origin_code,
            destination=dest_code,
            departure_date=departure_date,
            return_date=return_date,
            adults=1,
            seat_class="economy"
        )
        
        if not flight_result or not flight_result.get("flights"):
            error_msg = f"❌ 未找到航班: {origin} → {destination}"
            await _send_search_error(callback_query, message, context, error_msg)
            return
        
        # 格式化并显示结果
        result_text = format_flight_result(flight_result)
        
        # 创建操作按钮
        keyboard = [
            [
                InlineKeyboardButton("🔄 往返查询", callback_data=f"flight_roundtrip:{origin_code}:{dest_code}:{departure_date}"),
                InlineKeyboardButton("📅 其他日期", callback_data=f"flight_dates:{origin_code}:{dest_code}")
            ],
            [
                InlineKeyboardButton("🎛️ 筛选选项", callback_data=f"flight_filters:{origin_code}:{dest_code}:{departure_date}"),
                InlineKeyboardButton("📊 价格监控", callback_data=f"price_watch:{origin_code}:{dest_code}:{departure_date}")
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
        
    except Exception as e:
        logger.error(f"机票搜索失败: {e}")
        error_msg = f"❌ 搜索失败: {str(e)}"
        await _send_search_error(callback_query, message, context, error_msg)

async def _send_search_error(callback_query, message, context, error_msg):
    """发送搜索错误消息"""
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
                                  callback_query.message.message_id, config.auto_delete_delay)
    else:
        await message.edit_text(
            text=error_msg,
            reply_markup=reply_markup
        )
        await _schedule_auto_delete(context, message.chat_id, message.message_id, config.auto_delete_delay)

async def _execute_airport_search(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                query: str, callback_query: CallbackQuery = None) -> None:
    """执行机场搜索"""
    
    loading_message = f"🔍 正在搜索机场: {query}... ⏳"
    
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
        # 搜索机场
        airports = airport_data.search_airports(query, 10)
        
        if not airports:
            error_msg = f"❌ 未找到匹配 '{query}' 的机场"
            keyboard = [
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if callback_query:
                await callback_query.edit_message_text(
                    text=error_msg,
                    reply_markup=reply_markup
                )
            else:
                await message.edit_text(
                    text=error_msg,
                    reply_markup=reply_markup
                )
            return
        
        # 格式化结果
        result_text = format_airport_search_results(airports, query)
        
        # 创建机场选择按钮
        keyboard = []
        for airport in airports[:6]:  # 显示前6个作为按钮
            button_text = f"{airport['country_flag']} {airport['code']} - {airport['city_cn']}"
            callback_data = f"airport_select:{airport['code']}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
        
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
        
    except Exception as e:
        logger.error(f"机场搜索失败: {e}")
        error_msg = f"❌ 搜索失败: {str(e)}"
        keyboard = [
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if callback_query:
            await callback_query.edit_message_text(
                text=error_msg,
                reply_markup=reply_markup
            )
        else:
            await message.edit_text(
                text=error_msg,
                reply_markup=reply_markup
            )

async def flight_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理机票功能的文本输入"""
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
        
        if action == "airport_search" and waiting_for == "query":
            # 处理机场搜索
            await _execute_airport_search(update, context, text)
            flight_session_manager.remove_session(user_id)
        
        elif action == "flight_search" and waiting_for in ["origin", "destination", "date"]:
            # 处理机票搜索的各个步骤
            await _handle_flight_search_step(update, context, text, session_data)
        
    except Exception as e:
        logger.error(f"处理机票文本输入失败: {e}")
        await send_error(context, update.message.chat_id, f"处理失败: {str(e)}")
        flight_session_manager.remove_session(user_id)

async def _handle_flight_search_step(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                   text: str, session_data: Dict[str, Any]) -> None:
    """处理机票搜索的分步输入"""
    user_id = update.effective_user.id
    waiting_for = session_data.get("waiting_for")
    
    if waiting_for == "origin":
        # 设置起点，询问终点
        session_data["origin"] = text
        session_data["waiting_for"] = "destination"
        flight_session_manager.set_session(user_id, session_data)
        
        sent_message = await context.bot.send_message(
            chat_id=update.message.chat_id,
            text="✅ 起点已设置，请输入目的地:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
            ])
        )
        
        # 调度自动删除
        config = get_config()
        await _schedule_auto_delete(context, sent_message.chat_id, sent_message.message_id, config.auto_delete_delay)
    
    elif waiting_for == "destination":
        # 设置终点，询问日期
        session_data["destination"] = text
        session_data["waiting_for"] = "date"
        flight_session_manager.set_session(user_id, session_data)
        
        # 提供一些日期选项
        today = date.today()
        keyboard = []
        for i in range(1, 8):  # 未来一周的日期
            future_date = today + timedelta(days=i)
            date_str = future_date.isoformat()
            display_date = future_date.strftime("%m-%d (%a)")
            keyboard.append([InlineKeyboardButton(display_date, callback_data=f"flight_date_select:{date_str}")])
        
        keyboard.append([InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")])
        
        sent_message = await context.bot.send_message(
            chat_id=update.message.chat_id,
            text=f"✅ 终点已设置: {text}\n\n请选择出发日期或输入日期 (YYYY-MM-DD):",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        # 调度自动删除
        config = get_config()
        await _schedule_auto_delete(context, sent_message.chat_id, sent_message.message_id, config.auto_delete_delay)
    
    elif waiting_for == "date":
        # 执行搜索
        origin = session_data.get("origin")
        destination = session_data.get("destination")
        
        # 验证日期格式
        try:
            date.fromisoformat(text)
            departure_date = text
        except ValueError:
            await send_error(context, update.message.chat_id, 
                           "❌ 日期格式错误，请使用 YYYY-MM-DD 格式")
            return
        
        await _execute_flight_search(update, context, origin, destination, departure_date)
        flight_session_manager.remove_session(user_id)

async def flight_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理机票功能的回调查询"""
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
        # 返回主菜单
        user_id = update.effective_user.id
        flight_session_manager.remove_session(user_id)
        
        keyboard = [
            [
                InlineKeyboardButton("✈️ 机票查询", callback_data="flight_search"),
                InlineKeyboardButton("🔍 机场搜索", callback_data="airport_search")
            ],
            [
                InlineKeyboardButton("🔥 热门航线", callback_data="popular_routes"),
                InlineKeyboardButton("📊 价格监控", callback_data="price_monitor")
            ],
            [
                InlineKeyboardButton("❌ 关闭", callback_data="flight_close")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        help_text = """✈️ **智能机票查询服务**

🌟 **功能特色**:
• **机票查询**: 单程/往返机票价格比较
• **智能搜索**: 支持城市名、机场代码查询
• **机场搜索**: 全球机场信息查询
• **热门航线**: 推荐热门旅行路线
• **价格监控**: 跟踪价格变化趋势

🚀 **快速使用**:
`/flights 北京 纽约` - 快速查询机票
`/flights PEK LAX 2025-03-15` - 指定日期查询

请选择功能开始使用:"""
        
        await query.edit_message_text(
            text=foldable_text_with_markdown_v2(help_text),
            parse_mode="MarkdownV2",
            reply_markup=reply_markup
        )
    
    elif data == "flight_search":
        # 机票搜索
        user_id = update.effective_user.id
        
        flight_session_manager.set_session(user_id, {
            "action": "flight_search",
            "waiting_for": "origin"
        })
        
        await query.edit_message_text(
            text="✈️ **机票查询**\n\n请输入出发地 (支持城市名或机场代码):\n\n💡 例如: 北京、PEK、Tokyo、LAX",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
            ])
        )
    
    elif data == "airport_search":
        # 机场搜索
        user_id = update.effective_user.id
        
        flight_session_manager.set_session(user_id, {
            "action": "airport_search",
            "waiting_for": "query"
        })
        
        await query.edit_message_text(
            text="🔍 **机场搜索**\n\n请输入搜索关键词:\n\n💡 支持:\n• 城市名: 北京、纽约\n• 机场代码: PEK、LAX\n• 国家名: 中国、美国",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
            ])
        )
    
    elif data == "popular_routes":
        # 热门航线
        routes = airport_data.get_popular_routes()
        
        result_text = "🔥 **热门航线推荐**\n\n"
        for i, (origin, dest, desc) in enumerate(routes[:10], 1):
            origin_info = airport_data.get_airport_info(origin)
            dest_info = airport_data.get_airport_info(dest)
            
            if origin_info and dest_info:
                result_text += f"`{i:2d}.` {origin_info['country_flag']} → {dest_info['country_flag']} {desc}\n"
                result_text += f"     {origin} → {dest}\n\n"
        
        result_text += "💡 点击下方按钮查询特定航线价格"
        
        keyboard = [
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
        ]
        
        await query.edit_message_text(
            text=foldable_text_with_markdown_v2(result_text),
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif data == "price_monitor":
        # 价格监控 (功能占位)
        await query.edit_message_text(
            text="📊 **价格监控功能**\n\n🚧 此功能正在开发中，敬请期待！\n\n即将支持:\n• 价格跟踪提醒\n• 历史价格趋势\n• 最佳购买时机推荐",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
            ])
        )
    
    elif data.startswith("airport_select:"):
        # 选择机场
        airport_code = data.split(":", 1)[1]
        airport_info = airport_data.get_airport_info(airport_code)
        
        if airport_info:
            result_text = f"✈️ **机场详细信息**\n\n"
            result_text += f"{airport_info['country_flag']} **{airport_info['code']}** - {airport_info['display_name']}\n\n"
            result_text += f"🏢 {airport_info['full_info']}\n"
            result_text += f"🌍 国家: {airport_info['country_name']}\n"
            if airport_info.get('timezone'):
                result_text += f"🕐 时区: {airport_info['timezone']}\n"
            
            keyboard = [
                [InlineKeyboardButton("🔍 查询从此机场出发的航班", callback_data=f"flight_from:{airport_code}")],
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
            ]
            
            await query.edit_message_text(
                text=foldable_text_with_markdown_v2(result_text),
                parse_mode="MarkdownV2",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await query.edit_message_text(
                text="❌ 机场信息不可用",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 返回主菜单", callback_data="flight_main_menu")]
                ])
            )

# =============================================================================
# 注册命令和回调
# =============================================================================

# 注册主命令
command_factory.register_command(
    "flights",
    flights_command,
    permission=Permission.USER,
    description="✈️ 智能机票查询 - 航班搜索、价格比较、机场信息"
)

# 注册回调处理器
command_factory.register_callback(r"^flight_", flight_callback_handler, permission=Permission.USER, description="机票服务回调")

# 注册文本消息处理器  
command_factory.register_text_handler(flight_text_handler, permission=Permission.USER, description="机票服务文本输入处理")