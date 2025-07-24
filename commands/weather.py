import datetime
import jwt
import urllib.parse
import logging
from typing import Optional, Tuple, Dict
import traceback

import httpx
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from utils.command_factory import command_factory
from utils.permissions import Permission
from utils.config_manager import get_config
from utils.message_manager import send_message_with_auto_delete, delete_user_command, MessageType

# 全局变量 (由 main.py 注入)
cache_manager = None
httpx_client = None

def set_dependencies(c_manager, h_client):
    global cache_manager, httpx_client
    cache_manager = c_manager
    httpx_client = h_client

# 和风天气图标
WEATHER_ICONS = {
    '100': '☀️', '101': '🌤️', '102': '☁️', '103': '🌥️', '104': '⛅',
    '150': '🍃', '151': '🌬️', '152': '💨', '153': '🌪️', '300': '🌦️',
    '301': '🌧️', '302': '🌧️', '303': '⛈️', '304': '🌦️', '305': '🌧️',
    '306': '🌧️', '307': '⛈️', '308': '🌧️', '309': '🌦️', '310': '🌧️',
    '311': '🌧️', '312': '⛈️', '313': '🌧️', '399': '🌨️', '400': '❄️', '401': '❄️',
    '402': '❄️', '403': '❄️', '404': '🌨️', '405': '❄️', '406': '❄️',
    '407': '❄️', '499': '❓', '501': '⛈️', '502': '⛈️', '900': '🌪️', '901': '🌀'
}

class JWTManager:
    _cached_token: Optional[str] = None
    _expiry: Optional[int] = None

    @staticmethod
    def generate_jwt() -> str:
        now = datetime.datetime.utcnow()
        if JWTManager._cached_token and JWTManager._expiry and now.timestamp() < JWTManager._expiry:
            return JWTManager._cached_token
        
        config = get_config()
        if not all([config.qweather_kid, config.qweather_sub, config.qweather_private_key]):
            logging.error("和风天气 API 配置不完整")
            return ""

        try:
            header = {"alg": "EdDSA", "kid": config.qweather_kid}
            iat = int(now.timestamp())
            exp = int((now + datetime.timedelta(minutes=9)).timestamp())
            payload = {"sub": config.qweather_sub, "iat": iat, "exp": exp}
            
            token = jwt.encode(payload, config.qweather_private_key, algorithm="EdDSA", headers=header)
            
            JWTManager._cached_token = token
            JWTManager._expiry = exp
            logging.debug("JWT 生成成功并缓存。")
            return token
        except Exception as e:
            logging.error(f"生成 JWT 时出错: {e}")
            return ""

async def get_location_id(location: str) -> Optional[str]:
    cache_key = f"weather_location_{location.lower()}"
    cached_id = await cache_manager.load_cache(cache_key, subdirectory="weather")
    if cached_id:
        logging.info(f"使用缓存的位置ID: {location} -> {cached_id}")
        return cached_id

    try:
        encoded_location = urllib.parse.quote(location)
        url = f"https://geoapi.qweather.com/v2/city/lookup?location={encoded_location}"
        headers = {"Authorization": f"Bearer {JWTManager.generate_jwt()}"}

        response = await httpx_client.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get("code") == "200" and data.get("location"):
                location_id = data["location"][0]["id"]
                await cache_manager.save_cache(cache_key, location_id, subdirectory="weather")
                logging.info(f"获取并缓存位置ID: {location} -> {location_id}")
                return location_id
    except Exception as e:
        logging.error(f"查询位置失败: {e}")
    return None

async def request_weather_api(endpoint: str, location_id: str) -> Optional[dict]:
    try:
        url = f"https://api.qweather.com/v7/weather/{endpoint}"
        params = {"location": location_id, "lang": "zh"}
        headers = {"Authorization": f"Bearer {JWTManager.generate_jwt()}"}
        
        response = await httpx_client.get(url, params=params, headers=headers, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            if data.get("code") == "200":
                return data
            else:
                logging.warning(f"天气 API 返回错误代码: {data.get('code')}")
                return None
    except Exception as e:
        logging.error(f"天气API请求失败: {e}")
    return None

def format_realtime_weather(data: dict, location: str) -> str:
    now = data.get("now", {})
    weather_icon = WEATHER_ICONS.get(now.get("icon"), "❓")
    
    # 和风天气返回的是 UTC 时间，我们需要转换为本地时间（比如北京时间）
    obs_time_utc = datetime.datetime.fromisoformat(now.get('obsTime', 'N/A').replace('Z', '+00:00'))
    obs_time_local = obs_time_utc.astimezone(datetime.timezone(datetime.timedelta(hours=8))) # 假设为东八区
    
    text = f"🌍 **{location}** 的实时天气：\n\n"
    text += f"🕐 观测时间：{obs_time_local.strftime('%Y-%m-%d %H:%M')}\n"
    text += f"🌤️ 天气：{weather_icon} {now.get('text', 'N/A')}\n"
    text += f"🌡️ 温度：{now.get('temp', 'N/A')}℃ (体感: {now.get('feelsLike', 'N/A')}℃)\n"
    text += f"💨 {now.get('windDir', 'N/A')} {now.get('windScale', 'N/A')}级\n"
    text += f"💧 相对湿度：{now.get('humidity', 'N/A')}%\n"
    text += f"👀 能见度：{now.get('vis', 'N/A')}公里"
    return text

def format_daily_weather(daily_data: list) -> str:
    result = []
    for daily in daily_data:
        date_obj = datetime.datetime.strptime(daily.get("fxDate", ""), "%Y-%m-%d")
        date_str = date_obj.strftime("%m-%d")
        day_icon = WEATHER_ICONS.get(daily.get("iconDay"), "❓")
        night_icon = WEATHER_ICONS.get(daily.get("iconNight"), "❓")
        
        daily_info = [
            f"🗓 **{date_str}**",
            f"├─ 温度: {daily.get('tempMin', '')}~{daily.get('tempMax', '')}℃",
            f"├─ 日间: {day_icon} {daily.get('textDay', '')}",
            f"└─ 夜间: {night_icon} {daily.get('textNight', '')}\n"
        ]
        result.append("\n".join(daily_info))
    return "\n".join(result)

HELP_TEXT = (
    "**天气查询帮助**\n\n"
    "`/weather [城市] [参数]`\n\n"
    "**参数说明:**\n"
    "- `(无参数)`: 查询当天实时天气\n"
    "- `3`: 查询未来3天天气 (支持1-7天)\n\n"
    "**示例:**\n"
    "- `/weather 北京`\n"
    "- `/weather 上海 3`"
)

async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return
    
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)

    if not context.args:
        await send_message_with_auto_delete(context, update.effective_chat.id, HELP_TEXT, parse_mode=ParseMode.MARKDOWN)
        return

    location = context.args[0]
    param = context.args[1] if len(context.args) > 1 else None

    message = await context.bot.send_message(chat_id=update.effective_chat.id, text=f"🔍 正在查询 **{location}** 的天气...", parse_mode=ParseMode.MARKDOWN)

    location_id = await get_location_id(location)
    if not location_id:
        await message.edit_text(f"❌ 找不到城市 **{location}**，请检查拼写。", parse_mode=ParseMode.MARKDOWN)
        return

    # 默认查询当天实时天气
    if not param:
        weather_data = await request_weather_api("now", location_id)
        if not weather_data:
            await message.edit_text(f"❌ 获取 **{location}** 的天气信息失败。", parse_mode=ParseMode.MARKDOWN)
            return
        result_text = format_realtime_weather(weather_data, location)
        await message.edit_text(result_text, parse_mode=ParseMode.MARKDOWN)
        return
        
    # 查询多天天气
    try:
        days = int(param)
        if 1 <= days <= 7:
            endpoint = "3d" if days <= 3 else "7d"
            weather_data = await request_weather_api(endpoint, location_id)
            if not weather_data:
                await message.edit_text(f"❌ 获取 **{location}** 的天气信息失败。", parse_mode=ParseMode.MARKDOWN)
                return
            
            daily_forecast = weather_data.get("daily", [])[:days]
            result_text = f"🌍 **{location}** 未来 {days} 天天气预报：\n\n"
            result_text += format_daily_weather(daily_forecast)
            await message.edit_text(result_text, parse_mode=ParseMode.MARKDOWN)

        else:
            await message.edit_text("查询天数必须在 1-7 之间。")
        return
    except ValueError:
        await message.edit_text(f"无效的参数 '{param}'。请参照 `/weather` 的帮助说明。")
        return
    except Exception as e:
        logging.error(f"处理天气命令时出错: {e}")
        await message.edit_text("处理请求时发生未知错误。")

command_factory.register_command("weather", weather_command, permission=Permission.USER, description="查询实时和多日天气预报")
