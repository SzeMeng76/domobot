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

def parse_date_param(param: str) -> tuple[str, Optional[datetime.date], Optional[datetime.date]]:
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

def format_daily_weather(daily_data: list[dict]) -> str:
    """
    将每日天气数据格式化为详细的、类似代码1的树状结构。
    使用 MarkdownV2 进行格式化。
    """
    result_lines = []
    for day in daily_data:
        try:
            # --- 安全地获取并转义所有需要的数据 ---
            date_obj = datetime.datetime.strptime(day.get("fxDate", ""), "%Y-%m-%d")
            date_str = escape_markdown(date_obj.strftime("%m-%d"), version=2)
            
            moon_phase = escape_markdown(day.get('moonPhase', ''), version=2)
            temp_min = escape_markdown(day.get('tempMin', 'N/A'), version=2)
            temp_max = escape_markdown(day.get('tempMax', 'N/A'), version=2)
            
            day_icon = WEATHER_ICONS.get(day.get("iconDay"), "❓")
            text_day = escape_markdown(day.get('textDay', 'N/A'), version=2)
            wind_dir_day = escape_markdown(day.get('windDirDay', 'N/A'), version=2)
            wind_scale_day = escape_markdown(day.get('windScaleDay', 'N/A'), version=2)
            
            night_icon = WEATHER_ICONS.get(day.get("iconNight"), "❓")
            text_night = escape_markdown(day.get('textNight', 'N/A'), version=2)
            wind_dir_night = escape_markdown(day.get('windDirNight', 'N/A'), version=2)
            wind_scale_night = escape_markdown(day.get('windScaleNight', 'N/A'), version=2)
            
            humidity = escape_markdown(day.get('humidity', 'N/A'), version=2)
            precip = escape_markdown(day.get('precip', 'N/A'), version=2)
            sunrise = escape_markdown(day.get('sunrise', 'N/A'), version=2)
            sunset = escape_markdown(day.get('sunset', 'N/A'), version=2)
            vis = escape_markdown(day.get('vis', 'N/A'), version=2)
            uv_index = escape_markdown(day.get('uvIndex', 'N/A'), version=2)

            # --- 构建格式化字符串列表 ---
            # 注意：MarkdownV2 需要对 | ~ 等特殊字符进行转义
            daily_info = [
                f"🗓 *{date_str} {moon_phase}*",
                f"├─ 温度: {temp_min}\\~{temp_max}°C",
                f"├─ 日间: {day_icon} {text_day}",
                f"│   └─ {wind_dir_day} {wind_scale_day}级",
                f"├─ 夜间: {night_icon} {text_night}",
                f"│   └─ {wind_dir_night} {wind_scale_night}级",
                f"└─ 详情:",
                f"    💧 湿度: {humidity}% \\| ☔️ 降水: {precip}mm",
                f"    🌅 日出: {sunrise} \\| 🌄 日落: {sunset}",
                f"    👁️ 能见度: {vis}km \\| ☀️ UV指数: {uv_index}"
            ]
            
            result_lines.append("\n".join(daily_info))

        except Exception as e:
            logging.error(f"格式化单日天气数据时出错: {e}")
            continue
            
    # 每天的预报之间用两个换行符隔开，以获得更好的视觉间距
    return "\n\n".join(result_lines)

def format_hourly_weather(hourly_data: list[dict]) -> str:
    result = ["\n*逐小时预报*"]
    for hour in hourly_data:
        time_str = escape_markdown(datetime.datetime.fromisoformat(hour.get("fxTime").replace('Z', '+00:00')).strftime('%H:%M'), version=2)
        icon = WEATHER_ICONS.get(hour.get("icon"), "❓")
        temp = escape_markdown(hour.get('temp'), version=2)
        text = escape_markdown(hour.get('text'), version=2)
        result.append(f"`{time_str}`: {icon} {temp}°C, {text}")
    return "\n".join(result)

def format_minutely_rainfall(rainfall_data: dict) -> str:
    summary = escape_markdown(rainfall_data.get('summary', '暂无降水信息'), version=2)
    return f"\n*分钟级降水*: {summary}"

def format_indices_data(indices_data: dict) -> str:
    result = ["\n*生活指数*"]
    for index in indices_data.get("daily", []):
        name = escape_markdown(index.get('name'), version=2)
        category = escape_markdown(index.get('category'), version=2)
        result.append(f"• *{name}*: {category}")
    return "\n".join(result)

def format_air_quality(air_data: dict) -> str:
    aqi_data = air_data.get('now', {})
    aqi = escape_markdown(aqi_data.get('aqi', 'N/A'), version=2)
    category = escape_markdown(aqi_data.get('category', 'N/A'), version=2)
    primary = escape_markdown(aqi_data.get('primary', 'NA'), version=2)
    lines = [
        f"\n🌫️ *空气质量*：{aqi} \\({category}\\)",
        f"🔍 主要污染物：{primary}",
        f"🌬️ PM2\\.5：{escape_markdown(aqi_data.get('pm2p5', 'N/A'), version=2)}μg/m³ \\| PM10：{escape_markdown(aqi_data.get('pm10', 'N/A'), version=2)}μg/m³",
        f"🌡️ SO₂：{escape_markdown(aqi_data.get('so2', 'N/A'), version=2)}μg/m³ \\| NO₂：{escape_markdown(aqi_data.get('no2', 'N/A'), version=2)}μg/m³",
        f"💨 CO：{escape_markdown(aqi_data.get('co', 'N/A'), version=2)}mg/m³ \\| O₃：{escape_markdown(aqi_data.get('o3', 'N/A'), version=2)}μg/m³"
    ]
    return "\n".join(lines)

def format_realtime_weather(realtime_data: dict, location_name: str) -> str:
    now = realtime_data.get("now", {})
    icon = WEATHER_ICONS.get(now.get("icon"), "❓")
    obs_time_str = "N/A"
    try:
        obs_time_utc = datetime.datetime.fromisoformat(now.get('obsTime', '').replace('Z', '+00:00'))
        obs_time_local = obs_time_utc.astimezone(datetime.timezone(datetime.timedelta(hours=8)))
        obs_time_str = escape_markdown(obs_time_local.strftime('%Y-%m-%d %H:%M'), version=2)
    except: pass
    lines = [
        f"🌍 *{escape_markdown(location_name, version=2)}* 的实时天气：\n",
        f"🕐 观测时间：{obs_time_str}",
        f"🌤️ 天气：{icon} {escape_markdown(now.get('text', 'N/A'), version=2)}",
        f"🌡️ 温度：{escape_markdown(now.get('temp', 'N/A'), version=2)}°C",
        f"🌡️ 体感温度：{escape_markdown(now.get('feelsLike', 'N/A'), version=2)}°C",
        f"💨 {escape_markdown(now.get('windDir', 'N/A'), version=2)} {escape_markdown(now.get('windScale', 'N/A'), version=2)}级 \\({escape_markdown(now.get('windSpeed', 'N/A'), version=2)}km/h\\)",
        f"💧 相对湿度：{escape_markdown(now.get('humidity', 'N/A'), version=2)}%",
        f"☔️ 降水量：{escape_markdown(now.get('precip', 'N/A'), version=2)}mm",
        f"👀 能见度：{escape_markdown(now.get('vis', 'N/A'), version=2)}km",
        f"☁️ 云量：{escape_markdown(now.get('cloud', 'N/A'), version=2)}%",
        f"🌫️ 露点温度：{escape_markdown(now.get('dew', 'N/A'), version=2)}°C",
        f"📈 气压：{escape_markdown(now.get('pressure', 'N/A'), version=2)}hPa"
    ]
    return "\n".join(lines)

HELP_TEXT = (
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

async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat: return
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)

    if not context.args:
        await send_message_with_auto_delete(context, update.effective_chat.id, HELP_TEXT, parse_mode=ParseMode.MARKDOWN_V2)
        return

    location = context.args[0]
    param = context.args[1].lower() if len(context.args) > 1 else None
    
    safe_location = escape_markdown(location, version=2)
    message = await context.bot.send_message(chat_id=update.effective_chat.id, text=f"🔍 正在查询 *{safe_location}* 的天气\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)

    location_data = await get_location_id(location)
    if not location_data:
        await message.edit_text(f"❌ 找不到城市 *{safe_location}*，请检查拼写。", parse_mode=ParseMode.MARKDOWN_V2)
        return
    
    location_id = location_data['id']
    location_name = f"{location_data['name']}, {location_data['adm1']}"
    safe_location_name = escape_markdown(location_name, version=2)

    result_text = ""
    
    if not param:
        realtime_data = await _get_api_response("weather/now", {"location": location_id})
        air_data = await _get_api_response("air/now", {"location": location_id})
        
        if realtime_data:
            result_text = format_realtime_weather(realtime_data, location_name)
        else:
            result_text = f"❌ 获取 *{safe_location_name}* 实时天气失败。\n"
        
        if air_data:
            result_text += format_air_quality(air_data)
        else:
            result_text += f"\n*空气质量*: 获取失败"

    elif param.endswith('h') and param[:-1].isdigit() and 1 <= int(param[:-1]) <= 168:
        hours = int(param[:-1])
        endpoint = "weather/24h" if hours <= 24 else "weather/72h" if hours <= 72 else "weather/168h"
        data = await _get_api_response(endpoint, {"location": location_id})
        if data and data.get("hourly"):
            result_text = f"🌍 *{safe_location_name}* 未来 {hours} 小时天气："
            result_text += format_hourly_weather(data["hourly"][:hours])
        else:
            result_text = f"❌ 获取 *{safe_location_name}* 的逐小时天气失败。"

    elif param == "降水":
        coords = f"{location_data['lon']},{location_data['lat']}"
        data = await _get_api_response("minutely/5m", {"location": coords})
        if data:
            result_text = f"🌍 *{safe_location_name}*"
            result_text += format_minutely_rainfall(data)
        else:
            result_text = f"❌ 获取 *{safe_location_name}* 的分钟级降水失败。"
            
    elif param.startswith("指数"):
        days_param = "3d" if param.endswith("3") else "1d"
        data = await _get_api_response(f"indices/{days_param}", {"location": location_id, "type": "0"})
        if data:
            result_text = f"🌍 *{safe_location_name}* "
            result_text += format_indices_data(data)
        else:
            result_text = f"❌ 获取 *{safe_location_name}* 的生活指数失败。"
    
    else:
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
                    result_text = f"🌍 *{escape_markdown(date1.strftime('%m月%d日'), version=2)}* 天气预报：\n\n"
                    daily_data = [d for d in data["daily"] if d["fxDate"] == date1.strftime("%Y-%m-%d")]
                else:
                    start_str = date1.strftime('%m月%d日')
                    end_str = date2.strftime('%m月%d日')
                    title = f"未来 {(date2 - date1).days + 1} 天" if query_type == 'multiple_days' else f"{start_str}到{end_str}"
                    result_text = f"🌍 *{escape_markdown(title, version=2)}* 天气预报：\n\n"
                    daily_data = [d for d in data["daily"] if date1 <= datetime.datetime.strptime(d["fxDate"], "%Y-%m-%d").date() <= date2]
                result_text += format_daily_weather(daily_data)
            else:
                result_text = f"\n❌ 获取 *{safe_location_name}* 的天气信息失败。"

    await message.edit_text(result_text, parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True)

command_factory.register_command(
    "tq",
    weather_command,
    permission=Permission.USER,
    description="查询天气预报，支持多日、小时、指数等"
)
