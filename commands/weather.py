import datetime
import urllib.parse
import logging
from typing import Optional, Tuple, Dict, List
import traceback

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown

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
    '100': '☀️', '101': '🌤️', '102': '☁️', '103': '🌥️', '104': '⛅', '150': '🍃', 
    '300': '🌦️', '301': '🌧️', '302': '⛈️', '305': '🌧️', '306': '🌧️', '307': '⛈️',
    '309': '🌦️', '310': '🌧️', '311': '⛈️', '312': '⛈️', '313': '⛈️', '399': '🌨️',
    '400': '❄️', '401': '❄️', '402': '❄️', '403': '❄️', '404': '🌨️', '405': '❄️',
    '406': '❄️', '407': '❄️', '499': '❓', '501': '⛈️', '502': '⛈️', '900': '🌪️', '901': '🌀'
}

async def _get_api_response(endpoint: str, params: Dict) -> Optional[Dict]:
    config = get_config()
    if not config.qweather_api_key:
        logging.error("和风天气 API Key 未配置")
        return None
    try:
        base_url = "https://api.qweather.com/v7/"
        all_params = {"key": config.qweather_api_key, "lang": "zh", **params}
        
        response = await httpx_client.get(f"{base_url}{endpoint}", params=all_params, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            if data.get("code") == "200":
                return data
            else:
                logging.warning(f"和风天气 API 返回错误代码: {data.get('code')} for endpoint {endpoint}")
                return data # 返回错误信息以供调试
        else:
            logging.warning(f"和风天气 API 请求失败 ({endpoint}): HTTP {response.status_code}")
    except Exception as e:
        logging.error(f"和风天气 API 请求异常 ({endpoint}): {e}")
    return None

async def get_location_id(location: str) -> Optional[Dict]:
    cache_key = f"weather_location_{location.lower()}"
    cached_data = await cache_manager.load_cache(cache_key, subdirectory="weather")
    if cached_data:
        return cached_data
    
    base_url = "https://geoapi.qweather.com/v2/city/lookup"
    params = {"location": location, "key": get_config().qweather_api_key}
    
    try:
        response = await httpx_client.get(base_url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get("code") == "200" and data.get("location"):
                location_data = data["location"][0]
                await cache_manager.save_cache(cache_key, location_data, subdirectory="weather")
                return location_data
    except Exception as e:
        logging.error(f"查询位置失败: {e}")
    return None

def format_daily_weather(daily_data: list) -> str:
    result = []
    for daily in daily_data:
        date_obj = datetime.datetime.strptime(daily.get("fxDate", ""), "%Y-%m-%d")
        date_str = date_obj.strftime("%m-%d")
        day_icon = WEATHER_ICONS.get(daily.get("iconDay"), "❓")
        result.append(f"*{date_str}*: {day_icon} {daily.get('textDay', '')}, {daily.get('tempMin')}~{daily.get('tempMax')}°C")
    return "\n".join(result)

def format_hourly_weather(hourly_data: list) -> str:
    result = ["\n*逐小时预报*"]
    for hour in hourly_data:
        time_str = datetime.datetime.fromisoformat(hour.get("fxTime").replace('Z', '+00:00')).strftime('%H:%M')
        icon = WEATHER_ICONS.get(hour.get("icon"), "❓")
        result.append(f"`{time_str}`: {icon} {hour.get('temp')}°C, {hour.get('text')}")
    return "\n".join(result)

def format_minutely_rainfall(rainfall_data: dict) -> str:
    summary = rainfall_data.get('summary', '暂无降水信息')
    return f"\n*分钟级降水*: {escape_markdown(summary, version=2)}"

def format_indices_data(indices_data: dict) -> str:
    result = ["\n*生活指数*"]
    for index in indices_data.get("daily", []):
        result.append(f"• *{escape_markdown(index.get('name'), version=2)}*: {escape_markdown(index.get('category'), version=2)}")
    return "\n".join(result)

def format_air_quality(air_data: dict) -> str:
    aqi = air_data.get('now', {})
    return f"\n*空气质量*: {aqi.get('aqi', 'N/A')} - {escape_markdown(aqi.get('category', 'N/A'), version=2)}"

#@command_factory.register_command("tq", permission=Permission.USER, description="查询天气，例如 /tq 北京 或 /tq 上海 3")
async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat: return
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)

    if not context.args:
        # 你原来的详细帮助信息
        help_text = (
            "**天气查询帮助**\n\n"
            "`/tq [城市] [参数]`\n\n"
            "**参数说明:**\n"
            "- `(无参数)`: 查询当天天气和空气质量\n"
            "- `数字(1-7)`: 查询未来指定天数天气\n"
            "- `24h`: 查询未来24小时天气\n"
            "- `降水`: 查询分钟级降水\n"
            "- `指数`: 查询当天生活指数\n"
        )
        await send_message_with_auto_delete(context, update.effective_chat.id, help_text, parse_mode=ParseMode.MARKDOWN_V2)
        return

    location = context.args[0]
    param = context.args[1].lower() if len(context.args) > 1 else None
    
    message = await context.bot.send_message(chat_id=update.effective_chat.id, text=f"🔍 正在查询 *{escape_markdown(location, version=2)}* 的天气...", parse_mode=ParseMode.MARKDOWN_V2)

    location_data = await get_location_id(location)
    if not location_data:
        await message.edit_text(f"❌ 找不到城市 *{escape_markdown(location, version=2)}*，请检查拼写。", parse_mode=ParseMode.MARKDOWN_V2)
        return
    
    location_id = location_data['id']
    location_name = f"{location_data['name']}, {location_data['adm1']}, {location_data['country']}"

    result_text = ""

    # ---- 参数处理逻辑 ----
    if not param: # 默认情况：实时天气 + 空气质量
        realtime_data = await _get_api_response("weather/now", {"location": location_id})
        air_data = await _get_api_response("air/now", {"location": location_id})
        
        if realtime_data:
            now = realtime_data.get("now", {})
            icon = WEATHER_ICONS.get(now.get("icon"), "❓")
            result_text = f"🌍 *{escape_markdown(location_name, version=2)}*\n\n"
            result_text += f"*{icon} {escape_markdown(now.get('text', 'N/A'), version=2)}*\n"
            result_text += f"🌡️ {now.get('temp', 'N/A')}°C (体感: {now.get('feelsLike', 'N/A')}°C)\n"
            result_text += f"💨 {escape_markdown(now.get('windDir', 'N/A'), version=2)} {now.get('windScale', 'N/A')}级"
        else:
            result_text = f"❌ 获取 *{escape_markdown(location_name, version=2)}* 实时天气失败。\n"
        
        if air_data:
            result_text += format_air_quality(air_data)
        
    elif param.isdigit() and 1 <= int(param) <= 7:
        days = int(param)
        endpoint = "weather/3d" if days <= 3 else "weather/7d"
        data = await _get_api_response(endpoint, {"location": location_id})
        if data and data.get("daily"):
            result_text = f"🌍 *{escape_markdown(location_name, version=2)}* 未来 {days} 天天气预报：\n\n"
            result_text += format_daily_weather(data.get("daily", [])[:days])
        else:
            result_text = f"❌ 获取 *{escape_markdown(location_name, version=2)}* 的天气信息失败。"
            
    elif param.endswith('h') and param[:-1].isdigit() and 1 <= int(param[:-1]) <= 24:
        endpoint = "weather/24h"
        data = await _get_api_response(endpoint, {"location": location_id})
        if data:
            result_text = f"🌍 *{escape_markdown(location_name, version=2)}* 天气预报："
            result_text += format_hourly_weather(data.get("hourly", []))
        else:
            result_text = f"❌ 获取 *{escape_markdown(location_name, version=2)}* 的逐小时天气失败。"
    
    elif param == "降水":
        coords = f"{location_data['lon']},{location_data['lat']}"
        data = await _get_api_response("minutely/5m", {"location": coords})
        if data:
            result_text = f"🌍 *{escape_markdown(location_name, version=2)}* "
            result_text += format_minutely_rainfall(data)
        else:
            result_text = f"❌ 获取 *{escape_markdown(location_name, version=2)}* 的分钟级降水失败。"
            
    elif param == "指数":
        data = await _get_api_response("indices/1d", {"location": location_id, "type": "0"})
        if data:
            result_text = f"🌍 *{escape_markdown(location_name, version=2)}* "
            result_text += format_indices_data(data)
        else:
            result_text = f"❌ 获取 *{escape_markdown(location_name, version=2)}* 的生活指数失败。"
    
    else:
        result_text = f"❌ 无效的参数: `{escape_markdown(param, version=2)}`。\n\n请查看 `/help tq`"

    await message.edit_text(result_text, parse_mode=ParseMode.MARKDOWN_V2)

command_factory.register_command(
    "tq",
    weather_command,  # Pass the function as an argument here
    permission=Permission.USER,
    description="查询天气预报和空气质量"
)
