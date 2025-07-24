import datetime
import urllib.parse
import logging
from typing import Optional, Tuple, Dict, List

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown

from utils.command_factory import command_factory
from utils.permissions import Permission
from utils.config_manager import get_config
from utils.message_manager import send_message_with_auto_delete, delete_user_command

# 全局变量
cache_manager = None
httpx_client = None

def set_dependencies(c_manager, h_client):
    global cache_manager, httpx_client
    cache_manager = c_manager
    httpx_client = h_client

WEATHER_ICONS = {'100': '☀️', '101': '🌤️', '102': '☁️', '103': '🌥️', '104': '⛅', '150': '🍃', '300': '🌦️', '301': '🌧️', '302': '⛈️', '305': '🌧️', '306': '🌧️', '307': '⛈️', '309': '🌦️', '310': '🌧️', '311': '⛈️', '312': '⛈️', '313': '⛈️', '399': '🌨️', '400': '❄️', '401': '❄️', '402': '❄️', '403': '❄️', '404': '🌨️', '405': '❄️', '406': '❄️', '407': '❄️', '499': '❓', '501': '⛈️', '502': '⛈️', '900': '🌪️', '901': '🌀'}

# --- Helper Functions ---
async def _get_api_response(endpoint: str, params: Dict) -> Optional[Dict]:
    config = get_config()
    if not config.qweather_api_key:
        logging.error("和风天气 API Key 未配置")
        return None
    try:
        base_url = "https://api.qweather.com/v7/" if not endpoint.startswith("geo/") else "https://geoapi.qweather.com/v2/"
        api_endpoint = endpoint.replace("geo/", "")
        
        all_params = {"key": config.qweather_api_key, "lang": "zh", **params}
        
        response = await httpx_client.get(f"{base_url}{api_endpoint}", params=all_params, timeout=20)
        
        if response.status_code == 200:
            data = response.json()
            if data.get("code") == "200":
                return data
            else:
                logging.warning(f"和风天气 API ({endpoint}) 返回错误代码: {data.get('code')}")
                return data
        else:
            logging.warning(f"和风天气 API ({endpoint}) 请求失败: HTTP {response.status_code}")
    except Exception as e:
        logging.error(f"和风天气 API ({endpoint}) 请求异常: {e}")
    return None

async def get_location_id(location: str) -> Optional[Dict]:
    cache_key = f"weather_location_{location.lower()}"
    cached_data = await cache_manager.load_cache(cache_key, subdirectory="weather")
    if cached_data: return cached_data
    
    data = await _get_api_response("geo/city/lookup", {"location": location})
    if data and data.get("location"):
        location_data = data["location"][0]
        await cache_manager.save_cache(cache_key, location_data, subdirectory="weather")
        return location_data
    return None

def parse_date_param(param: str) -> Tuple[str, Optional[datetime.date], Optional[datetime.date]]:
    today = datetime.date.today()
    if '-' in param:
        try:
            start_day, end_day = map(int, param.split('-'))
            start_date = today.replace(day=start_day)
            end_date = today.replace(day=end_day)
            if start_date < today: start_date = start_date.replace(month=start_date.month + 1) if today.month < 12 else start_date.replace(year=today.year + 1, month=1)
            if end_date < start_date: end_date = end_date.replace(month=end_date.month + 1) if today.month < 12 else end_date.replace(year=today.year + 1, month=1)
            if 0 <= (end_date - today).days <= 30: return 'date_range', start_date, end_date
            return 'out_of_range', None, None
        except (ValueError, IndexError): pass
    
    if param.startswith('day') and len(param) > 3 and param[3:].isdigit():
        try:
            day = int(param[3:])
            target_date = today.replace(day=day)
            if target_date < today: target_date = target_date.replace(month=target_date.month + 1) if today.month < 12 else target_date.replace(year=today.year + 1, month=1)
            if 0 <= (target_date - today).days <= 30: return 'specific_date', target_date, None
            return 'out_of_range', None, None
        except ValueError: pass

    if param.isdigit():
        try:
            days = int(param)
            if 1 <= days <= 30: return 'multiple_days', today, today + datetime.timedelta(days=days - 1)
            return 'out_of_range', None, None
        except ValueError: pass

    return 'invalid', None, None

def format_daily_weather(daily_data: List[Dict]) -> str:
    lines = []
    for day in daily_data:
        date_str = escape_markdown(datetime.datetime.strptime(day["fxDate"], "%Y-%m-%d").strftime("%m-%d"), version=2)
        icon = WEATHER_ICONS.get(day["iconDay"], "❓")
        text_day = escape_markdown(day.get('textDay', ''), version=2)
        temp_min = escape_markdown(day.get('tempMin', ''), version=2)
        temp_max = escape_markdown(day.get('tempMax', ''), version=2)
        lines.append(f"*{date_str}*: {icon} {text_day}, {temp_min}\\~{temp_max}°C")
    return "\n".join(lines)

def format_hourly_weather(hourly_data: List[Dict]) -> str:
    result = ["\n*逐小时预报*"]
    for hour in hourly_data:
        time_str = escape_markdown(datetime.datetime.fromisoformat(hour.get("fxTime").replace('Z', '+00:00')).strftime('%H:%M'), version=2)
        icon = WEATHER_ICONS.get(hour.get("icon"), "❓")
        temp = escape_markdown(hour.get('temp'), version=2)
        text = escape_markdown(hour.get('text'), version=2)
        result.append(f"`{time_str}`: {icon} {temp}°C, {text}")
    return "\n".join(result)

def format_minutely_rainfall(rainfall_data: Dict) -> str:
    summary = escape_markdown(rainfall_data.get('summary', '暂无降水信息'), version=2)
    return f"\n*分钟级降水*: {summary}"

def format_indices_data(indices_data: Dict) -> str:
    result = ["\n*生活指数*"]
    for index in indices_data.get("daily", []):
        name = escape_markdown(index.get('name'), version=2)
        category = escape_markdown(index.get('category'), version=2)
        result.append(f"• *{name}*: {category}")
    return "\n".join(result)

def format_air_quality(air_data: Dict) -> str:
    aqi_data = air_data.get('now', {})
    aqi = escape_markdown(aqi_data.get('aqi', 'N/A'), version=2)
    category = escape_markdown(aqi_data.get('category', 'N/A'), version=2)
    return f"\n*空气质量*: {aqi} \\- {category}"

async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat: return
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)

    if not context.args:
        help_text = (
            "*天气查询帮助* `(和风天气)`\n\n"
            "`/tq [城市] [参数]`\n\n"
            "**参数说明:**\n"
            "• `(无)`: 当天天气和空气质量\n"
            "• `数字(1-30)`: 未来指定天数天气\n"
            "• `dayXX`: 指定日期天气\n"
            "• `XX-YY`: 指定日期范围天气\n"
            "• `[1-168]h`: 逐小时天气\n"
            "• `降水`: 分钟级降水\n"
            "• `指数`/`指数3`: 生活指数\n\n"
            "**示例:** `/tq 北京`, `/tq 上海 3`, `/tq 广州 24h`"
        )
        await send_message_with_auto_delete(context, update.effective_chat.id, help_text, parse_mode=ParseMode.MARKDOWN_V2)
        return

    location = context.args[0]
    param = context.args[1].lower() if len(context.args) > 1 else None
    
    safe_location = escape_markdown(location, version=2)
    message = await context.bot.send_message(chat_id=update.effective_chat.id, text=f"🔍 正在查询 *{safe_location}* 的天气...", parse_mode=ParseMode.MARKDOWN_V2)

    location_data = await get_location_id(location)
    if not location_data:
        await message.edit_text(f"❌ 找不到城市 *{safe_location}*，请检查拼写。", parse_mode=ParseMode.MARKDOWN_V2)
        return
    
    location_id = location_data['id']
    location_name = f"{location_data['name']}, {location_data['adm1']}"
    safe_location_name = escape_markdown(location_name, version=2)

    result_text = f"🌍 *{safe_location_name}*\n"
    
    # --- Parameter Handling Logic ---
    if not param: # Default case
        realtime_data = await _get_api_response("weather/now", {"location": location_id})
        air_data = await _get_api_response("air/now", {"location": location_id})
        if realtime_data and realtime_data.get("now"):
            now = realtime_data["now"]; icon = WEATHER_ICONS.get(now.get("icon"), "❓")
            result_text += f"*{icon} {escape_markdown(now.get('text', 'N/A'), version=2)}* "
            result_text += f"🌡️ {escape_markdown(now.get('temp', 'N/A'), version=2)}°C \\(体感: {escape_markdown(now.get('feelsLike', 'N/A'), version=2)}°C\\)"
        else: result_text += "\n❌ 获取实时天气失败。"
        if air_data: result_text += format_air_quality(air_data)
    
    elif param.endswith('h') and param[:-1].isdigit() and 1 <= int(param[:-1]) <= 168:
        hours = int(param[:-1])
        endpoint = "weather/24h" if hours <= 24 else "weather/72h" if hours <= 72 else "weather/168h"
        data = await _get_api_response(endpoint, {"location": location_id})
        if data and data.get("hourly"): result_text += format_hourly_weather(data["hourly"][:hours])
        else: result_text += f"\n❌ 获取 *{safe_location_name}* 的逐小时天气失败。"

    elif param == "降水":
        coords = f"{location_data['lon']},{location_data['lat']}"
        data = await _get_api_response("minutely/5m", {"location": coords})
        if data: result_text += format_minutely_rainfall(data)
        else: result_text += f"\n❌ 获取 *{safe_location_name}* 的分钟级降水失败。"
            
    elif param.startswith("指数"):
        days_param = "3d" if param.endswith("3") else "1d"
        data = await _get_api_response(f"indices/{days_param}", {"location": location_id, "type": "0"})
        if data: result_text += format_indices_data(data)
        else: result_text += f"\n❌ 获取 *{safe_location_name}* 的生活指数失败。"
    
    else: # Date-related queries
        query_type, date1, date2 = parse_date_param(param)
        if query_type == 'invalid':
            result_text = f"❌ 无效的参数: `{escape_markdown(param, version=2)}`。"
        elif query_type == 'out_of_range':
            result_text = "❌ 只支持查询未来30天内的天气预报。"
        else:
            days_needed = (date2 - datetime.date.today()).days + 1 if date2 else (date1 - datetime.date.today()).days + 1
            endpoint = "weather/3d" if days_needed <= 3 else "weather/7d" if days_needed <=7 else "weather/15d" if days_needed <= 15 else "weather/30d"
            data = await _get_api_response(endpoint, {"location": location_id})
            if data and data.get("daily"):
                if query_type == 'specific_date':
                    result_text += f"*{date1.strftime('%m月%d日')}* 天气预报：\n"
                    daily_data = [d for d in data["daily"] if d["fxDate"] == date1.strftime("%Y-%m-%d")]
                else:
                    start_str = date1.strftime('%m月%d日')
                    end_str = date2.strftime('%m月%d日')
                    title = f"未来 {(date2 - date1).days + 1} 天" if query_type == 'multiple_days' else f"{start_str}到{end_str}"
                    result_text += f"*{escape_markdown(title, version=2)}* 天气预报：\n"
                    daily_data = [d for d in data["daily"] if date1 <= datetime.datetime.strptime(d["fxDate"], "%Y-%m-%d").date() <= date2]
                result_text += format_daily_weather(daily_data)
            else:
                result_text += f"\n❌ 获取 *{safe_location_name}* 的天气信息失败。"

    await message.edit_text(result_text, parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True)

# 在文件末尾，用正确的方式注册命令
command_factory.register_command(
    "tq",
    weather_command,
    permission=Permission.USER,
    description="查询天气预报，支持多日、小时、指数等"
)
