import datetime
import logging
from datetime import timedelta
from typing import Optional, Dict, Any
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from utils.command_factory import command_factory
from utils.permissions import Permission
from utils.config_manager import get_config
from utils.formatter import foldable_text_v2, foldable_text_with_markdown_v2
from utils.message_manager import send_message_with_auto_delete, send_error, send_success, delete_user_command
from utils.timezone_mapper import (
    resolve_timezone_with_country_data, 
    get_supported_countries_for_timezone,
    get_supported_cities
)

logger = logging.getLogger(__name__)

# 全局变量
cache_manager = None

def set_dependencies(c_manager):
    """设置依赖"""
    global cache_manager
    cache_manager = c_manager

class TimeService:
    """时间服务类，提供时间查询和转换功能"""
    
    @staticmethod
    def get_zoneinfo(timezone_name: str) -> ZoneInfo:
        """获取时区信息"""
        try:
            return ZoneInfo(timezone_name)
        except Exception as e:
            raise ValueError(f"无效的时区: {timezone_name}")
    
    @staticmethod
    def get_system_timezone() -> str:
        """获取系统时区"""
        try:
            from tzlocal import get_localzone_name
            return get_localzone_name() or "UTC"
        except ImportError:
            return "UTC"
    
    async def get_current_time(self, timezone_name: str = None) -> Dict[str, Any]:
        """获取当前时间"""
        if not timezone_name:
            timezone_name = self.get_system_timezone()
        
        # 对于当前时间查询，不使用缓存（因为时间实时变化）
        timezone = self.get_zoneinfo(timezone_name)
        current_time = datetime.datetime.now(timezone)
        
        return {
            "timezone": timezone_name,
            "datetime": current_time.isoformat(timespec="seconds"),
            "formatted": current_time.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "is_dst": bool(current_time.dst()),
            "utc_offset": str(current_time.utcoffset())
        }
    
    async def convert_time(self, source_tz: str, time_str: str, target_tz: str) -> Dict[str, Any]:
        """时区转换"""
        # 为时区转换结果创建缓存键（基于时区对和时差计算，而非具体时间）
        cache_key = f"timezone_diff_{source_tz}_{target_tz}"
        
        source_timezone = self.get_zoneinfo(source_tz)
        target_timezone = self.get_zoneinfo(target_tz)
        
        try:
            parsed_time = datetime.datetime.strptime(time_str, "%H:%M").time()
        except ValueError:
            raise ValueError("时间格式错误，请使用 HH:MM 格式（24小时制）")
        
        now = datetime.datetime.now(source_timezone)
        source_time = datetime.datetime(
            now.year, now.month, now.day,
            parsed_time.hour, parsed_time.minute,
            tzinfo=source_timezone
        )
        
        target_time = source_time.astimezone(target_timezone)
        source_offset = source_time.utcoffset() or timedelta()
        target_offset = target_time.utcoffset() or timedelta()
        hours_difference = (target_offset - source_offset).total_seconds() / 3600
        
        if hours_difference.is_integer():
            time_diff_str = f"{hours_difference:+.0f}小时"
        else:
            time_diff_str = f"{hours_difference:+.1f}小时"
        
        # 如果有缓存管理器，缓存时差信息（用于下次快速计算）
        if cache_manager:
            try:
                await cache_manager.save_cache(
                    cache_key, 
                    {"hours_difference": hours_difference, "time_diff_str": time_diff_str},
                    subdirectory="timezone",
                    expire_time=86400  # 24小时过期，因为夏令时可能变化
                )
            except Exception as e:
                logger.warning(f"缓存时区差异失败: {e}")
        
        return {
            "source": {
                "timezone": source_tz,
                "datetime": source_time.isoformat(timespec="seconds"),
                "formatted": source_time.strftime("%Y-%m-%d %H:%M:%S %Z"),
                "is_dst": bool(source_time.dst())
            },
            "target": {
                "timezone": target_tz,
                "datetime": target_time.isoformat(timespec="seconds"),
                "formatted": target_time.strftime("%Y-%m-%d %H:%M:%S %Z"),
                "is_dst": bool(target_time.dst())
            },
            "time_difference": time_diff_str
        }

def resolve_timezone(user_input: str) -> tuple[str, dict]:
    """解析用户输入的时区，返回(timezone, country_info)"""
    if not user_input:
        return TimeService.get_system_timezone(), {}
    
    return resolve_timezone_with_country_data(user_input)

def format_time_result(result: Dict[str, Any], country_info: dict = None) -> str:
    """格式化时间结果"""
    dst_indicator = " (夏令时)" if result.get("is_dst") else ""
    
    # 构建标题
    if country_info and country_info.get("flag") and country_info.get("name"):
        title = f"{country_info['flag']} **{country_info['name']}**"
        if country_info.get("currency"):
            title += f" ({country_info['currency']})"
    else:
        title = f"🕐 **{result['timezone']}**"
    
    return (
        f"{title}{dst_indicator}\n"
        f"📅 {result['formatted']}\n"
        f"🌍 时区: {result['timezone']}\n"
        f"⏰ UTC偏移: {result['utc_offset']}"
    )

def format_conversion_result(result: Dict[str, Any], source_country: dict = None, target_country: dict = None) -> str:
    """格式化时区转换结果"""
    source = result['source']
    target = result['target']
    
    source_dst = " (夏令时)" if source.get("is_dst") else ""
    target_dst = " (夏令时)" if target.get("is_dst") else ""
    
    # 格式化源时区标题
    if source_country and source_country.get("flag") and source_country.get("name"):
        source_title = f"{source_country['flag']} **{source_country['name']}**"
    else:
        source_title = f"📍 **{source['timezone']}**"
    
    # 格式化目标时区标题
    if target_country and target_country.get("flag") and target_country.get("name"):
        target_title = f"{target_country['flag']} **{target_country['name']}**"
    else:
        target_title = f"📍 **{target['timezone']}**"
    
    return (
        f"🔄 **时区转换结果**\n\n"
        f"{source_title}{source_dst}\n"
        f"⏰ {source['formatted']}\n"
        f"🌍 {source['timezone']}\n\n"
        f"{target_title}{target_dst}\n"
        f"⏰ {target['formatted']}\n"
        f"🌍 {target['timezone']}\n\n"
        f"⏱️ **时差: {result['time_difference']}**"
    )

async def time_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """获取当前时间"""
    try:
        # 解析参数
        args = context.args
        timezone_input = " ".join(args) if args else None
        timezone, country_info = resolve_timezone(timezone_input)
        
        # 获取时间服务
        time_service = TimeService()
        
        # 查询时间
        result = await time_service.get_current_time(timezone)
        
        # 格式化结果
        response = format_time_result(result, country_info)
        
        # 如果使用了国家/城市名映射，添加提示
        if timezone_input and country_info:
            if country_info.get("name"):
                response += f"\n\n💡 已识别为 {country_info['name']}"
        
        await send_message_with_auto_delete(
            context=context,
            chat_id=update.effective_chat.id,
            text=response,
            parse_mode=ParseMode.MARKDOWN_V2
        )
        
        # 删除用户命令
        await delete_user_command(
            context=context,
            chat_id=update.effective_chat.id,
            message_id=update.effective_message.message_id
        )
        
    except ValueError as e:
        await send_error(
            context=context,
            chat_id=update.effective_chat.id,
            text=str(e)
        )
        await delete_user_command(
            context=context,
            chat_id=update.effective_chat.id,
            message_id=update.effective_message.message_id
        )
    except Exception as e:
        logger.error(f"时间查询失败: {e}")
        await send_error(
            context=context,
            chat_id=update.effective_chat.id,
            text="查询时间失败，请检查时区格式"
        )
        await delete_user_command(
            context=context,
            chat_id=update.effective_chat.id,
            message_id=update.effective_message.message_id
        )

async def convert_time_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """时区转换"""
    try:
        args = context.args
        if len(args) < 3:
            await send_error(
                context=context,
                chat_id=update.effective_chat.id,
                text="参数不足，请使用格式: /convert_time <源时区> <时间> <目标时区>"
            )
            await delete_user_command(
                context=context,
                chat_id=update.effective_chat.id,
                message_id=update.effective_message.message_id
            )
            return
        
        # 解析参数 - 支持带空格的时区名
        if len(args) == 3:
            source_tz_input, time_str, target_tz_input = args
        else:
            # 尝试智能解析
            time_str = None
            for i, arg in enumerate(args):
                if ":" in arg and len(arg) <= 5:  # 假设是时间格式
                    time_str = arg
                    source_tz_input = " ".join(args[:i])
                    target_tz_input = " ".join(args[i+1:])
                    break
            
            if not time_str:
                await send_error(
                    context=context,
                    chat_id=update.effective_chat.id,
                    text="未找到有效的时间格式，请使用 HH:MM 格式"
                )
                await delete_user_command(
                    context=context,
                    chat_id=update.effective_chat.id,
                    message_id=update.effective_message.message_id
                )
                return
        
        # 解析时区
        source_tz, source_country = resolve_timezone(source_tz_input)
        target_tz, target_country = resolve_timezone(target_tz_input)
        
        # 获取时间服务
        time_service = TimeService()
        
        # 执行转换
        result = await time_service.convert_time(source_tz, time_str, target_tz)
        
        # 格式化结果
        response = format_conversion_result(result, source_country, target_country)
        
        await send_message_with_auto_delete(
            context=context,
            chat_id=update.effective_chat.id,
            text=response,
            parse_mode=ParseMode.MARKDOWN_V2
        )
        
        # 删除用户命令
        await delete_user_command(
            context=context,
            chat_id=update.effective_chat.id,
            message_id=update.effective_message.message_id
        )
        
    except ValueError as e:
        await send_error(
            context=context,
            chat_id=update.effective_chat.id,
            text=str(e)
        )
        await delete_user_command(
            context=context,
            chat_id=update.effective_chat.id,
            message_id=update.effective_message.message_id
        )
    except Exception as e:
        logger.error(f"时区转换失败: {e}")
        await send_error(
            context=context,
            chat_id=update.effective_chat.id,
            text="时区转换失败，请检查参数格式"
        )
        await delete_user_command(
            context=context,
            chat_id=update.effective_chat.id,
            message_id=update.effective_message.message_id
        )

async def timezone_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """显示支持的时区列表"""
    try:
        # 获取支持的城市列表
        cities = get_supported_cities()
        city_list = []
        for i, city in enumerate(cities[:15]):  # 只显示前15个城市，避免消息过长
            city_list.append(f"• {city}")
        
        # 获取支持的国家列表（前10个）
        countries = get_supported_countries_for_timezone()[:10]
        country_list = []
        for country in countries:
            country_list.append(f"{country['flag']} {country['name']}")
        
        response = (
            "🌍 **支持的时区查询**\n\n"
            "🏙️ **常用城市:**\n" + "\n".join(city_list) +
            f"\n...等 {len(cities)} 个城市\n\n"
            "🇺🇳 **支持的国家:**\n" + "\n".join(country_list) +
            f"\n...等 {len(countries)} 个国家\n\n"
            "💡 **使用方法:**\n"
            "• 城市名: `/time 北京`\n"
            "• 国家名: `/time 日本`\n"
            "• 国家代码: `/time JP`\n"
            "• IANA时区: `/time Asia/Tokyo`\n"
            "• 时区转换: `/convert_time 中国 14:30 美国`\n\n"
            "🔗 完整IANA时区列表: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones"
        )
        
        await send_message_with_auto_delete(
            context=context,
            chat_id=update.effective_chat.id,
            text=response,
            parse_mode=ParseMode.MARKDOWN_V2
        )
        
        # 删除用户命令
        await delete_user_command(
            context=context,
            chat_id=update.effective_chat.id,
            message_id=update.effective_message.message_id
        )
        
    except Exception as e:
        logger.error(f"显示时区列表失败: {e}")
        await send_error(
            context=context,
            chat_id=update.effective_chat.id,
            text="显示时区列表失败"
        )
        await delete_user_command(
            context=context,
            chat_id=update.effective_chat.id,
            message_id=update.effective_message.message_id
        )

# Register commands
command_factory.register_command("time", time_command, permission=Permission.NONE, description="查询当前时间（可指定时区）")
command_factory.register_command("convert_time", convert_time_command, permission=Permission.NONE, description="时区转换")
command_factory.register_command("timezone", timezone_list_command, permission=Permission.NONE, description="查看支持的时区列表")
