#!/usr/bin/env python3
"""
统一缓存管理命令模块
替换所有 *_cleancache 命令，提供统一的缓存管理接口
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler

from utils.command_factory import command_factory
from utils.config_manager import get_config
from utils.error_handling import with_error_handling
from utils.message_manager import send_success, send_error, delete_user_command, send_help
from utils.permissions import Permission

logger = logging.getLogger(__name__)

# 缓存服务映射
CACHE_SERVICES = {
    'all': '清理所有缓存',
    'memes': '表情包缓存',
    'news': '新闻缓存', 
    'crypto': '加密货币缓存',
    'movie': '电影电视缓存',
    'steam': 'Steam游戏缓存',
    'weather': '天气缓存',
    'cooking': '烹饪菜谱缓存',
    'finance': '金融数据缓存',
    'whois': 'WHOIS查询缓存',
    'app_store': 'App Store缓存',
    'netflix': 'Netflix缓存',
    'spotify': 'Spotify缓存',
    'disney_plus': 'Disney+缓存',
    'max': 'HBO Max缓存',
    'rate': '汇率缓存',
    'bin': 'BIN查询缓存',
    'google_play': 'Google Play缓存',
    'apple_services': 'Apple服务缓存',
    'timezone': '时区缓存',
    'dns': 'DNS查询缓存',
    'map': '地图服务缓存',
    'flights': '航班服务缓存',
    'hotels': '酒店服务缓存',
}

async def clear_service_cache(service: str, context: ContextTypes.DEFAULT_TYPE):
    """清理指定服务的缓存"""
    cache_manager = context.bot_data.get('cache_manager')
    if not cache_manager:
        return False, "缓存管理器不可用"
    
    try:
        if service == 'all':
            # 清理所有缓存
            for svc in CACHE_SERVICES.keys():
                if svc != 'all':
                    if svc == 'weather':
                        # 特殊处理weather的复杂缓存结构
                        prefixes = [
                            "weather_location_", "weather_realtime_", "weather_forecast_",
                            "weather_hourly_", "weather_air_", "weather_indices_", "weather_minutely_"
                        ]
                        for prefix in prefixes:
                            await cache_manager.clear_cache(subdirectory="weather", key_prefix=prefix)
                    elif svc == 'whois':
                        # 特殊处理whois的双子目录结构
                        await cache_manager.clear_cache(subdirectory="whois")
                        await cache_manager.clear_cache(subdirectory="dns")
                    elif svc == 'flights':
                        # 特殊处理flights的复杂缓存结构
                        prefixes = [
                            "flight_search_", "flight_booking_", "flight_prices_"
                        ]
                        for prefix in prefixes:
                            await cache_manager.clear_cache(subdirectory="flights", key_prefix=prefix)
                    elif svc == 'hotels':
                        # 特殊处理hotels的复杂缓存结构
                        prefixes = [
                            "hotel_", "hotel_details_"
                        ]
                        for prefix in prefixes:
                            await cache_manager.clear_cache(subdirectory="hotels", key_prefix=prefix)
                    elif svc == 'movie':
                        # 特殊处理movie的复杂缓存结构，包括排行榜相关缓存
                        prefixes = [
                            "movie_", "tv_", "trending_", "now_playing_", "upcoming_", 
                            "person_", "movie_watch_", "tv_watch_"
                        ]
                        for prefix in prefixes:
                            await cache_manager.clear_cache(subdirectory="movie", key_prefix=prefix)
                    else:
                        await cache_manager.clear_cache(subdirectory=svc)
            return True, "✅ 所有缓存已清理完成"
        else:
            # 清理指定缓存
            if service == 'weather':
                # 特殊处理weather的复杂缓存结构
                prefixes = [
                    "weather_location_", "weather_realtime_", "weather_forecast_",
                    "weather_hourly_", "weather_air_", "weather_indices_", "weather_minutely_"
                ]
                for prefix in prefixes:
                    await cache_manager.clear_cache(subdirectory="weather", key_prefix=prefix)
            elif service == 'whois':
                # 特殊处理whois的双子目录结构
                await cache_manager.clear_cache(subdirectory="whois")
                await cache_manager.clear_cache(subdirectory="dns")
            elif service == 'flights':
                # 特殊处理flights的复杂缓存结构
                prefixes = [
                    "flight_search_", "flight_booking_", "flight_prices_"
                ]
                for prefix in prefixes:
                    await cache_manager.clear_cache(subdirectory="flights", key_prefix=prefix)
            elif service == 'hotels':
                # 特殊处理hotels的复杂缓存结构
                prefixes = [
                    "hotel_", "hotel_details_"
                ]
                for prefix in prefixes:
                    await cache_manager.clear_cache(subdirectory="hotels", key_prefix=prefix)
            elif service == 'movie':
                # 特殊处理movie的复杂缓存结构，包括排行榜相关缓存
                prefixes = [
                    "movie_", "tv_", "trending_", "now_playing_", "upcoming_", 
                    "person_", "movie_watch_", "tv_watch_"
                ]
                for prefix in prefixes:
                    await cache_manager.clear_cache(subdirectory="movie", key_prefix=prefix)
            else:
                await cache_manager.clear_cache(subdirectory=service)
            
            service_name = CACHE_SERVICES.get(service, service)
            return True, f"✅ {service_name}已清理完成"
    except Exception as e:
        logger.error(f"清理{service}缓存失败: {e}")
        return False, f"❌ 清理缓存失败: {e}"

def create_cache_menu():
    """创建缓存管理菜单"""
    keyboard = []
    
    # 按行排列服务
    services_per_row = 3
    services = [(k, v) for k, v in CACHE_SERVICES.items() if k != 'all']
    
    for i in range(0, len(services), services_per_row):
        row = []
        for j in range(services_per_row):
            if i + j < len(services):
                service_key, service_name = services[i + j]
                row.append(InlineKeyboardButton(
                    service_name.replace('缓存', ''), 
                    callback_data=f"cleancache_{service_key}"
                ))
        keyboard.append(row)
    
    # 添加特殊操作按钮
    keyboard.append([
        InlineKeyboardButton("🗑️ 清理全部", callback_data="cleancache_all"),
        InlineKeyboardButton("❌ 关闭", callback_data="cleancache_close")
    ])
    
    return InlineKeyboardMarkup(keyboard)

@with_error_handling
async def cleancache_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """统一缓存清理命令"""
    if not update.message:
        return
    
    args = context.args or []
    
    if not args:
        # 显示交互式菜单
        keyboard = create_cache_menu()
        message = (
            "🧹 **缓存管理中心**\n\n"
            "请选择要清理的缓存类型：\n\n"
            "💡 也可以直接使用命令：\n"
            "`/cleancache [service]` - 清理指定缓存\n"
            "`/cleancache all` - 清理所有缓存"
        )
        
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=message,
            parse_mode='Markdown',
            reply_markup=keyboard
        )
        
        # 调度删除菜单消息 - 给用户足够时间操作菜单
        from utils.message_manager import _schedule_deletion
        await _schedule_deletion(context, update.effective_chat.id, sent_message.message_id, 300)  # 5分钟后删除菜单
        
        # 删除用户命令
        await delete_user_command(context, update.effective_chat.id, update.message.message_id)
        return
    
    # 解析参数
    service = args[0].lower()
    
    if service in ['-h', '--help', 'help']:
        help_text = (
            "🧹 **缓存管理帮助**\n\n"
            "**基本用法:**\n"
            "`/cleancache` - 显示交互式菜单\n"
            "`/cleancache [服务名]` - 清理指定服务缓存\n"
            "`/cleancache all` - 清理所有缓存\n\n"
            "**支持的服务:**\n"
        )
        
        for service_key, service_name in CACHE_SERVICES.items():
            if service_key != 'all':
                help_text += f"• `{service_key}` - {service_name}\n"
        
        help_text += "\n**示例:**\n"
        help_text += "• `/cleancache memes` - 清理表情包缓存\n"
        help_text += "• `/cleancache news` - 清理新闻缓存\n" 
        help_text += "• `/cleancache all` - 清理所有缓存"
        
        await send_help(context, update.effective_chat.id, help_text, parse_mode='Markdown')
        await delete_user_command(context, update.effective_chat.id, update.message.message_id)
        return
    
    if service not in CACHE_SERVICES:
        available_services = ', '.join([k for k in CACHE_SERVICES.keys() if k != 'all'])
        await send_error(
            context,
            update.effective_chat.id,
            f"❌ 不支持的服务: `{service}`\n\n支持的服务: {available_services}\n\n使用 `/cleancache help` 查看详细说明",
            parse_mode='Markdown'
        )
        await delete_user_command(context, update.effective_chat.id, update.message.message_id)
        return
    
    # 执行缓存清理
    success, message = await clear_service_cache(service, context)
    
    if success:
        await send_success(context, update.effective_chat.id, message)
        logger.info(f"缓存清理成功: {service}")
    else:
        await send_error(context, update.effective_chat.id, message)
        logger.error(f"缓存清理失败: {service}")
    
    # 删除用户命令
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)

@with_error_handling
async def cleancache_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理缓存清理的回调查询"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "cleancache_close":
        await query.message.delete()
        return
    
    if data.startswith("cleancache_"):
        service = data.replace("cleancache_", "")
        
        # 显示处理中状态
        service_name = CACHE_SERVICES.get(service, service)
        await query.edit_message_text(f"🔄 正在清理{service_name}...")
        
        # 执行清理
        success, message = await clear_service_cache(service, context)
        
        # 显示结果
        await query.edit_message_text(message)
        
        # 调度删除机器人回复消息
        from utils.message_manager import _schedule_deletion
        await _schedule_deletion(context, query.message.chat_id, query.message.message_id, 60)
        
        logger.info(f"通过回调清理缓存: {service}, 结果: {success}")

# 注册命令
command_factory.register_command(
    "cleancache",
    cleancache_command,
    permission=Permission.ADMIN,
    description="统一缓存管理（替代所有*_cleancache命令）"
)

# 注册回调处理器
command_factory.register_callback(
    "^cleancache_",
    cleancache_callback_handler,
    permission=Permission.ADMIN,
    description="缓存清理回调处理器"
)

logger.info("统一缓存管理命令模块已加载")