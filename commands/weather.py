import datetime
import urllib.parse
import logging
from typing import Optional, Tuple, Dict, List

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown

from utils.command_factory import command_factory
from utils.permissions import Permission
from utils.config_manager import get_config
from utils.formatter import foldable_text_v2, foldable_text_with_markdown_v2
from utils.message_manager import send_message_with_auto_delete, delete_user_command, send_error, send_success

# Import OpenAI for AI weather report
try:
    from openai import AsyncOpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    logging.warning("OpenAI library not available, AI weather report will be disabled")

# 全局变量
cache_manager = None
httpx_client = None

def set_dependencies(c_manager, h_client):
    global cache_manager, httpx_client
    cache_manager = c_manager
    httpx_client = h_client

WEATHER_ICONS = {
    '100': '☀️', '101': '🌤️', '102': '☁️', '103': '🌥️', '104': '⛅',
    '150': '🍃', '151': '🌬️', '152': '💨', '153': '🌪️', '300': '🌦️',
    '301': '🌧️', '302': '🌧️', '303': '⛈️', '304': '🌦️', '305': '🌧️',
    '306': '🌧️', '307': '⛈️', '308': '🌧️', '309': '🌦️', '310': '🌧️',
    '311': '🌧️', '312': '⛈️', '313': '🌧️', '314': '🌧️', '315': '⛈️',
    '316': '🌧️', '317': '🌧️', '318': '⛈️', '350': '🌨️', '351': '🌨️',
    '399': '🌨️', '400': '❄️', '401': '❄️', '402': '❄️', '403': '❄️',
    '404': '🌨️', '405': '❄️', '406': '❄️', '407': '❄️', '408': '❄️🌨️',
    '409': '❄️🌨️', '410': '❄️🌨️', '456': '🌪️', '457': '🌪️', '499': '❓',
    '500': '⛈️', '501': '⛈️', '502': '⛈️', '503': '⛈️', '504': '⛈️',
    '507': '⛈️🌨️', '508': '⛈️🌨️', '509': '⚡', '510': '⚡', '511': '⚡',
    '512': '⚡', '513': '⚡', '514': '⚡', '515': '⚡', '800': '☀️',
    '801': '🌤️', '802': '☁️', '803': '☁️', '804': '☁️', '805': '🌫️',
    '806': '🌫️', '807': '🌧️', '900': '🌪️', '901': '🌀', '999': '❓'
}

INDICES_EMOJI = {
    "1": "🏃",  # 运动
    "2": "🚗",  # 洗车
    "3": "👕",  # 穿衣
    "4": "🎣",  # 钓鱼
    "5": "☀️",  # 紫外线
    "6": "🏞️",  # 旅游
    "7": "🤧",  # 过敏
    "8": "😊",  # 舒适度
    "9": "🤒",  # 感冒
    "10": "🌫️", # 空气污染扩散
    "11": "❄️", # 空调开启
    "12": "🕶️", # 太阳镜
    "13": "💄", # 化妆
    "14": "👔", # 晾晒
    "15": "🚦", # 交通
    "16": "🧴", # 防晒
}

# 生活指数的逻辑分类
CATEGORIES = {
    "户外活动": ["1", "4", "6"],           # 运动, 钓鱼, 旅游
    "出行建议": ["2", "15"],             # 洗车, 交通
    "生活起居": ["3", "8", "11", "14"],   # 穿衣, 舒适度, 空调, 晾晒
    "健康关注": ["7", "9", "10"],          # 过敏, 感冒, 空气污染扩散
    "美妆护理": ["5", "12", "13", "16"],  # 紫外线, 太阳镜, 化妆, 防晒
}

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

# ============================================================================
# 天气预警 API（新版 weather-alert）
# ============================================================================

async def get_weather_alerts(lat: float, lon: float) -> Optional[Dict]:
    """
    获取天气预警信息（使用新版 weather-alert API）

    Args:
        lat: 纬度
        lon: 经度

    Returns:
        预警数据字典，包含 alerts 数组
    """
    config = get_config()
    if not config.qweather_api_key:
        logging.error("和风天气 API Key 未配置")
        return None

    try:
        # 新版API使用不同的base URL和认证方式
        base_url = "https://api.qweather.com/weatheralert/v1/current"
        url = f"{base_url}/{lat:.2f}/{lon:.2f}"

        params = {"key": config.qweather_api_key}

        response = await httpx_client.get(url, params=params, timeout=20)
        if response.status_code == 200:
            data = response.json()
            # 新版API返回格式：{"metadata": {...}, "alerts": [...]}
            if data and "alerts" in data:
                return data
        else:
            logging.warning(f"天气预警 API 请求失败: HTTP {response.status_code}")
    except Exception as e:
        logging.error(f"天气预警 API 请求异常: {e}")
    return None

def format_weather_alerts(alerts_data: Dict, location_name: str) -> str:
    """
    格式化天气预警信息

    Args:
        alerts_data: 预警API返回的数据
        location_name: 地点名称

    Returns:
        格式化的预警文本
    """
    alerts = alerts_data.get("alerts", [])

    if not alerts:
        return f"✅ *{escape_markdown(location_name, version=2)}* 当前无天气预警。"

    result = [f"⚠️ *{escape_markdown(location_name, version=2)} 天气预警* （共 {len(alerts)} 条）\n"]

    # 颜色等级emoji映射
    color_emoji = {
        "red": "🔴",
        "orange": "🟠",
        "yellow": "🟡",
        "blue": "🔵"
    }

    for i, alert in enumerate(alerts, 1):
        event_type = alert.get("eventType", {}).get("name", "未知")
        severity = alert.get("severity", "moderate")
        color_code = alert.get("color", {}).get("code", "")
        headline = alert.get("headline", "")
        description = alert.get("description", "")
        sender = alert.get("senderName", "")

        # 获取颜色emoji
        emoji = color_emoji.get(color_code, "⚠️")

        # 截断描述文字（最多200字符）
        desc_short = description[:200] + "..." if len(description) > 200 else description

        # 预警详情不转义，保持原文可读性（日期、温度等）
        # 只对标题等简短字段转义
        result.append(f"{emoji} *预警 #{i}: {escape_markdown(event_type, version=2)}*")
        result.append(f"├─ 标题: {escape_markdown(headline, version=2)}")
        result.append(f"├─ 等级: {escape_markdown(severity, version=2)} {emoji}")
        result.append(f"├─ 发布: {escape_markdown(sender, version=2)}")
        result.append(f"└─ 详情: {desc_short}\n")

    return "\n".join(result)

# ============================================================================
# 台风追踪 API
# ============================================================================

async def get_active_typhoons(basin: str = "NP") -> Optional[Dict]:
    """
    获取活跃台风列表

    Args:
        basin: 海洋流域代码，默认NP（西北太平洋）

    Returns:
        台风列表数据
    """
    config = get_config()
    if not config.qweather_api_key:
        logging.error("和风天气 API Key 未配置")
        return None

    try:
        base_url = "https://api.qweather.com/v7/tropical/storm-active"
        params = {
            "key": config.qweather_api_key,
            "basin": basin
        }

        response = await httpx_client.get(base_url, params=params, timeout=20)
        if response.status_code == 200:
            data = response.json()
            if data and data.get("code") == "200":
                return data
        else:
            logging.warning(f"活跃台风 API 请求失败: HTTP {response.status_code}")
    except Exception as e:
        logging.error(f"活跃台风 API 请求异常: {e}")
    return None

async def get_typhoon_track(storm_id: str) -> Optional[Dict]:
    """
    获取台风路径信息

    Args:
        storm_id: 台风ID（格式：NP_2501）

    Returns:
        台风路径数据
    """
    config = get_config()
    if not config.qweather_api_key:
        logging.error("和风天气 API Key 未配置")
        return None

    try:
        base_url = "https://api.qweather.com/v7/tropical/storm-track"
        params = {
            "key": config.qweather_api_key,
            "stormid": storm_id
        }

        response = await httpx_client.get(base_url, params=params, timeout=20)
        if response.status_code == 200:
            data = response.json()
            if data and data.get("code") == "200":
                return data
        else:
            logging.warning(f"台风路径 API 请求失败: HTTP {response.status_code}")
    except Exception as e:
        logging.error(f"台风路径 API 请求异常: {e}")
    return None

def format_typhoon_info(typhoon_data: Dict) -> str:
    """
    格式化台风信息

    Args:
        typhoon_data: 台风路径数据

    Returns:
        格式化的台风信息文本
    """
    if not typhoon_data or not typhoon_data.get("track"):
        return "❌ 无法获取台风数据。"

    is_active = typhoon_data.get("isActive", "0") == "1"
    track = typhoon_data.get("track", [])

    if not track:
        return "❌ 台风路径数据为空。"

    # 获取最新数据点
    latest = track[-1]

    time = latest.get("time", "N/A")
    lat = latest.get("lat", "N/A")
    lon = latest.get("lon", "N/A")
    type_code = latest.get("type", "N/A")
    pressure = latest.get("pressure", "N/A")
    wind_speed = latest.get("windSpeed", "N/A")
    move_speed = latest.get("moveSpeed", "N/A")
    move_dir = latest.get("moveDir", "N/A")

    # 台风类型映射
    type_map = {
        "TD": "热带低压",
        "TS": "热带风暴",
        "STS": "强热带风暴",
        "TY": "台风",
        "STY": "强台风",
        "SuperTY": "超强台风"
    }
    type_name = type_map.get(type_code, type_code)

    status = "🌀 活跃" if is_active else "✅ 已消散"

    result = [
        f"🌀 *台风信息*\n",
        f"状态: {status}",
        f"等级: {escape_markdown(type_name, version=2)} \\({type_code}\\)",
        f"位置: {lat}°N, {lon}°E",
        f"中心气压: {pressure} hPa",
        f"最大风速: {wind_speed} m/s",
        f"移动速度: {move_speed} km/h",
        f"移动方向: {escape_markdown(move_dir, version=2)}",
        f"更新时间: {escape_markdown(time, version=2)}"
    ]

    return "\n".join(result)

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
            date_str = date_obj.strftime("%m-%d")
            
            moon_phase = day.get('moonPhase', '')
            temp_min = day.get('tempMin', 'N/A')
            temp_max = day.get('tempMax', 'N/A')
            
            day_icon = WEATHER_ICONS.get(day.get("iconDay"), "❓")
            text_day = day.get('textDay', 'N/A')
            wind_dir_day = day.get('windDirDay', 'N/A')
            wind_scale_day = day.get('windScaleDay', 'N/A')
            
            night_icon = WEATHER_ICONS.get(day.get("iconNight"), "❓")
            text_night = day.get('textNight', 'N/A')
            wind_dir_night = day.get('windDirNight', 'N/A')
            wind_scale_night = day.get('windScaleNight', 'N/A')
            
            humidity = day.get('humidity', 'N/A')
            precip = day.get('precip', 'N/A')
            sunrise = day.get('sunrise', 'N/A')
            sunset = day.get('sunset', 'N/A')
            vis = day.get('vis', 'N/A')
            uv_index = day.get('uvIndex', 'N/A')

            # --- 构建格式化字符串列表 ---
            # 注意：MarkdownV2 需要对 | ~ 等特殊字符进行转义
            daily_info = [
                f"🗓 *{date_str} {moon_phase}*",
                f"├─ 温度: {temp_min}~{temp_max}°C",
                f"├─ 日间: {day_icon} {text_day}",
                f"│   └─ {wind_dir_day} {wind_scale_day}级",
                f"├─ 夜间: {night_icon} {text_night}",
                f"│   └─ {wind_dir_night} {wind_scale_night}级",
                f"└─ 详情:",
                f"    💧 湿度: {humidity}% | ☔️ 降水: {precip}mm",
                f"    🌅 日出: {sunrise} | 🌄 日落: {sunset}",
                f"    👁️ 能见度: {vis}km | ☀️ UV指数: {uv_index}"
            ]
            
            result_lines.append("\n".join(daily_info))

        except Exception as e:
            logging.error(f"格式化单日天气数据时出错: {e}")
            continue
            
    # 每天的预报之间用两个换行符隔开，以获得更好的视觉间距
    return "\n\n".join(result_lines)

def format_hourly_weather(hourly_data: list[dict]) -> str:
    """
    将逐小时天气数据格式化为详细的、类似代码1的多行卡片结构。
    """
    result_lines = []
    for hour in hourly_data:
        try:
            # --- 安全地获取并转义所有需要的数据 ---
            time_str = escape_markdown(datetime.datetime.fromisoformat(hour.get("fxTime").replace('Z', '+00:00')).strftime('%H:%M'), version=2)
            temp = escape_markdown(hour.get('temp', 'N/A'), version=2)
            icon = WEATHER_ICONS.get(hour.get("icon"), "❓")
            text = escape_markdown(hour.get('text', 'N/A'), version=2)
            wind_dir = hour.get('windDir', 'N/A')
            wind_scale = hour.get('windScale', 'N/A')
            humidity = escape_markdown(hour.get('humidity', 'N/A'), version=2)
            # 和风天气API返回的pop是字符串"0"~"100"，直接用即可
            pop = escape_markdown(hour.get('pop', 'N/A'), version=2) 
            
            # --- 构建单个小时的格式化文本 ---
            hourly_info = [
                f"⏰ {time_str}",
                f"🌡️ {temp}°C {icon} {text}",
                f"💨 {wind_dir} {wind_scale}级",
                f"💧 湿度: {humidity}% | ☔️ 降水概率: {pop}%",
                "━━━━━━━━━━━━━━━━━━━━" # 分隔线
            ]
            result_lines.append("\n".join(hourly_info))

        except Exception as e:
            # 如果单条数据处理失败，记录日志并跳过，不影响其他数据显示
            logging.error(f"格式化单小时天气数据时出错: {e}")
            continue
            
    # 将每个小时的文本块用换行符连接起来
    return "\n".join(result_lines)

def format_minutely_rainfall(rainfall_data: dict) -> str:
    """
    将分钟级降水数据格式化为包含摘要和详细时间点的列表。
    """
    result = []

    # 1. 添加摘要和主分隔线
    summary = rainfall_data.get('summary', '暂无降水信息')
    result.append(f"📝 {summary}")
    result.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # 2. 遍历每个时间点的数据并格式化
    for minute in rainfall_data.get("minutely", []):
        try:
            time_str = datetime.datetime.fromisoformat(minute.get("fxTime").replace('Z', '+00:00')).strftime('%H:%M')
            precip = minute.get('precip', 'N/A')
            
            precip_type_text = "雨" if minute.get("type") == "rain" else "雪"
            precip_type_icon = "🌧️" if minute.get("type") == "rain" else "❄️"
            
            # 构建单个时间点的信息块
            minute_info = (
                f"\n⏰ {time_str}\n"
                # ↓↓↓ 修正了这一行，为括号添加了转义符 \ ↓↓↓
                f"💧 预计降水: {precip}mm ({precip_type_icon} {precip_type_text})\n"
                "━━━━━━━━━━━━━━━━━━━━"
            )
            result.append(minute_info)

        except Exception as e:
            logging.error(f"格式化分钟级降水数据时出错: {e}")
            continue

    return "\n".join(result)

def format_indices_data(indices_data: dict) -> str:
    """
    将生活指数数据格式化为详细的、按日期和类别分组的结构。
    """
    result = []
    grouped_by_date = {}

    # 1. 首先按日期将所有指数分组
    for index in indices_data.get("daily", []):
        date = index.get("date")
        if date not in grouped_by_date:
            grouped_by_date[date] = []
        grouped_by_date[date].append(index)
    
    # 2. 遍历每个日期，生成该日期的指数报告
    for date, indices in sorted(grouped_by_date.items()):
        date_str = datetime.datetime.strptime(date, "%Y-%m-%d").strftime("%m-%d")
        result.append(f"\n📅 *{date_str} 天气生活指数*")

        # 3. 遍历预设的分类，在当前日期的指数中查找并显示
        for category_name, type_ids in CATEGORIES.items():
            # 筛选出属于当前分类的指数
            category_indices = [idx for idx in indices if idx.get("type") in type_ids]
            
            if category_indices:
                result.append(f"\n*【{escape_markdown(category_name, version=2)}】*")
                for index in category_indices:
                    index_type = index.get("type")
                    emoji = INDICES_EMOJI.get(index_type, "ℹ️") # 获取对应的Emoji
                    name = index.get('name', 'N/A')
                    level = index.get('category', 'N/A')
                    text = index.get('text', 'N/A')
                    
                    # 构建最终的图文并茂格式
                    result.append(f"{emoji} *{name}*: {level}")
                    result.append(f"    ↳ {text}")

    return "\n".join(result)

def format_air_quality(air_data: dict) -> str:
    aqi_data = air_data.get('now', {})
    aqi = aqi_data.get('aqi', 'N/A')
    category = aqi_data.get('category', 'N/A')
    primary = aqi_data.get('primary', 'NA')
    lines = [
        f"\n🌫️ *空气质量*：{aqi} ({category})",
        f"🔍 主要污染物：{primary}",
        f"🌬️ PM2.5：{aqi_data.get('pm2p5', 'N/A')}μg/m³ | PM10：{aqi_data.get('pm10', 'N/A')}μg/m³",
        f"🌡️ SO₂：{aqi_data.get('so2', 'N/A')}μg/m³ | NO₂：{aqi_data.get('no2', 'N/A')}μg/m³",
        f"💨 CO：{aqi_data.get('co', 'N/A')}mg/m³ | O₃：{aqi_data.get('o3', 'N/A')}μg/m³"
    ]
    return "\n".join(lines)

def create_weather_main_keyboard(location: str) -> InlineKeyboardMarkup:
    """创建天气查询主菜单键盘"""
    keyboard = [
        [
            InlineKeyboardButton("🌤️ 实时天气", callback_data=f"weather_now_{location}"),
            InlineKeyboardButton("📅 3天预报", callback_data=f"weather_3d_{location}")
        ],
        [
            InlineKeyboardButton("📊 7天预报", callback_data=f"weather_7d_{location}"),
            InlineKeyboardButton("📈 15天预报", callback_data=f"weather_15d_{location}")
        ],
        [
            InlineKeyboardButton("⏰ 24小时预报", callback_data=f"weather_24h_{location}"),
            InlineKeyboardButton("🕐 72小时预报", callback_data=f"weather_72h_{location}")
        ],
        [
            InlineKeyboardButton("🌧️ 分钟降水", callback_data=f"weather_rain_{location}"),
            InlineKeyboardButton("📋 生活指数", callback_data=f"weather_indices_{location}")
        ],
        [
            InlineKeyboardButton("❌ 关闭", callback_data="weather_close")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

async def generate_ai_weather_report(location_name: str, realtime_data: dict, daily_data: dict, hourly_data: dict, indices_data: dict, air_data: dict = None, alerts_data: dict = None) -> Optional[str]:
    """使用 AI 生成个性化天气日报"""
    if not OPENAI_AVAILABLE:
        logging.warning("OpenAI not available, cannot generate AI weather report")
        return None

    config = get_config()
    if not config.openai_api_key:
        logging.warning("OpenAI API key not configured")
        return None

    try:
        # 构建天气数据摘要
        now = realtime_data.get("now", {})
        current_time = datetime.datetime.now().strftime("%H:%M")
        current_date = datetime.datetime.now().strftime("%m月%d日")

        # 提取关键天气信息
        current_temp = now.get('temp', 'N/A')
        feels_like = now.get('feelsLike', 'N/A')
        weather_text = now.get('text', 'N/A')
        humidity = now.get('humidity', 'N/A')
        wind_dir = now.get('windDir', 'N/A')
        wind_scale = now.get('windScale', 'N/A')

        # 未来天气
        tomorrow = daily_data.get("daily", [])[1] if len(daily_data.get("daily", [])) > 1 else {}
        tomorrow_weather_day = tomorrow.get('textDay', 'N/A')
        tomorrow_weather_night = tomorrow.get('textNight', 'N/A')
        tomorrow_temp_min = tomorrow.get('tempMin', 'N/A')
        tomorrow_temp_max = tomorrow.get('tempMax', 'N/A')

        # 未来几小时
        next_hours = hourly_data.get("hourly", [])[:6]  # 获取未来6小时
        hourly_summary = []
        for h in next_hours:
            hour_time = datetime.datetime.fromisoformat(h.get("fxTime").replace('Z', '+00:00')).strftime('%H时')
            hour_temp = h.get('temp', 'N/A')
            hour_text = h.get('text', 'N/A')
            hourly_summary.append(f"{hour_time} {hour_text} {hour_temp}°C")

        # 生活指数
        indices_list = indices_data.get("daily", [])
        dressing_index = next((idx for idx in indices_list if idx.get("type") == "3"), {})
        sport_index = next((idx for idx in indices_list if idx.get("type") == "1"), {})
        carwash_index = next((idx for idx in indices_list if idx.get("type") == "2"), {})

        # 空气质量
        air_quality = ""
        if air_data and air_data.get('now') and air_data.get('now').get('aqi'):
            aqi = air_data.get('now', {}).get('aqi', 'N/A')
            category = air_data.get('now', {}).get('category', 'N/A')
            air_quality = f"空气质量 {aqi} ({category})"

        # 天气预警
        alerts_summary = ""
        if alerts_data and alerts_data.get('alerts'):
            alerts_list = alerts_data.get('alerts', [])
            alerts_summary = "\n【天气预警】⚠️\n"
            for alert in alerts_list[:3]:  # 最多显示3条预警
                event_type = alert.get('eventType', {}).get('name', '未知')
                severity = alert.get('severity', 'moderate')
                headline = alert.get('headline', '')
                description = alert.get('description', '')[:100]  # 限制长度
                alerts_summary += f"- {event_type} ({severity})\n  标题：{headline}\n  详情：{description}...\n"

        # 构建 AI prompt
        weather_data_summary = f"""
当前时间：{current_date} {current_time}
地点：{location_name}

【实时天气】
天气状况：{weather_text}
当前温度：{current_temp}°C
体感温度：{feels_like}°C
湿度：{humidity}%
风向风力：{wind_dir} {wind_scale}级
{air_quality}
{alerts_summary}
【未来几小时】
{', '.join(hourly_summary)}

【明天天气】
白天：{tomorrow_weather_day}
夜间：{tomorrow_weather_night}
温度：{tomorrow_temp_min}°C 到 {tomorrow_temp_max}°C

【生活指数】
穿衣指数：{dressing_index.get('category', 'N/A')} - {dressing_index.get('text', '')}
运动指数：{sport_index.get('category', 'N/A')} - {sport_index.get('text', '')}
洗车指数：{carwash_index.get('category', 'N/A')} - {carwash_index.get('text', '')}
"""

        # AI prompt - 参考最佳实践，使用清晰直接的指令
        system_prompt = """你是敏敏，一个可爱活泼的天气播报助手！🌈

你的播报风格：
1. 开场问候：根据时间问候（早上好/下午好/晚上好），用"敏敏来送上..."开场
2. ⚠️ 天气预警优先：如果有天气预警，必须在开场后立即提醒！用亲切但认真的语气强调，比如"今天有XX预警，大家一定要注意安全哦！"
3. 语气活泼可爱，使用emoji和口语化表达（比如"热腾腾"、"小火炉"、"洗澡惊喜"等）
4. 重点突出：温度、天气状况、体感差异、明天重要变化
5. 生活建议：基于指数给出实用建议（穿衣、运动、出行等）
6. 温馨结尾：用"敏敏播报完毕"结束，祝福用户

格式要求：
- 第一行：🤖 [地点] 天气日报
- 第二行：敏敏的天气播报小站！🌈
- 第三行：[日期时间]
- 空一行后开始正文
- 如果有天气预警：第一段专门说预警，用友好但严肃的语气提醒注意事项
- 正文3-4段，每段2-3句话

注意：
- 保持友好可爱的语气，但不要过度幼稚
- 重要信息（温度、天气状况）要清晰呈现
- 适当使用emoji增加趣味性（每段1-3个）
- 如果有极端天气（高温、暴雨等）或预警要特别提醒
- **天气预警是最重要的信息，一定要突出提醒用户注意安全**
- **重要：只输出纯文本，不要使用任何Markdown格式符号（如*、_、`、[、]等），只使用emoji和普通文字**"""

        user_prompt = f"请根据以下天气数据，生成一份可爱活泼的天气日报：\n\n{weather_data_summary}"

        # 调用 OpenAI API
        client = AsyncOpenAI(
            api_key=config.openai_api_key,
            base_url=config.openai_base_url if config.openai_base_url else None
        )

        weather_model = config.openai_model or "gpt-5-mini"

        stream = await client.chat.completions.create(
            model=weather_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.8,
            stream=True
        )

        ai_report = ""
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                ai_report += chunk.choices[0].delta.content

        # 过滤掉思考过程标签
        import re
        ai_report = re.sub(r'<think>.*?</think>', '', ai_report, flags=re.DOTALL)
        ai_report = ai_report.strip()

        # 添加模型署名
        ai_report += f"\n\n🤖 Generated by {weather_model}"

        return ai_report

    except Exception as e:
        logging.error(f"AI weather report generation failed: {e}")
        return None

def format_realtime_weather(realtime_data: dict, location_name: str) -> str:
    now = realtime_data.get("now", {})
    icon = WEATHER_ICONS.get(now.get("icon"), "❓")
    obs_time_str = "N/A"
    try:
        obs_time_utc = datetime.datetime.fromisoformat(now.get('obsTime', '').replace('Z', '+00:00'))
        obs_time_local = obs_time_utc.astimezone(datetime.timezone(datetime.timedelta(hours=8)))
        obs_time_str = obs_time_local.strftime('%Y-%m-%d %H:%M')
    except: pass
    lines = [
        f"🌍 *{location_name}* 的实时天气：\n",
        f"🕐 观测时间：{obs_time_str}",
        f"🌤️ 天气：{icon} {now.get('text', 'N/A')}",
        f"🌡️ 温度：{now.get('temp', 'N/A')}°C",
        f"🌡️ 体感温度：{now.get('feelsLike', 'N/A')}°C",
        f"💨 {now.get('windDir', 'N/A')} {now.get('windScale', 'N/A')}级 ({now.get('windSpeed', 'N/A')}km/h)",
        f"💧 相对湿度：{now.get('humidity', 'N/A')}%",
        f"☔️ 降水量：{now.get('precip', 'N/A')}mm",
        f"👀 能见度：{now.get('vis', 'N/A')}km",
        f"☁️ 云量：{now.get('cloud', 'N/A')}%",
        f"🌫️ 露点温度：{now.get('dew', 'N/A')}°C",
        f"📈 气压：{now.get('pressure', 'N/A')}hPa"
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
        # 显示主菜单
        keyboard = [
            [
                InlineKeyboardButton("🌤️ 查询天气", callback_data="weather_menu_search"),
                InlineKeyboardButton("🌀 台风追踪", callback_data="typhoon_list")
            ],
            [
                InlineKeyboardButton("❌ 关闭", callback_data="weather_close")
            ]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        menu_text = """🌤️ *天气查询菜单*

*功能选择：*
• 🌤️ 查询天气 \\- 查询指定城市的实时天气
• 🌀 台风追踪 \\- 查看当前活跃台风信息

*直接查询：*
发送 `/tq 城市名` 即可快速查询天气
例如：`/tq 吉隆坡`"""

        message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=menu_text,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=reply_markup
        )

        # 调度删除消息
        from utils.message_manager import _schedule_deletion
        config = get_config()
        await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)
        return

    location = context.args[0]
    param = context.args[1].lower() if len(context.args) > 1 else None

    safe_location = escape_markdown(location, version=2)
    message = await context.bot.send_message(chat_id=update.effective_chat.id, text=f"🔍 正在查询 *{safe_location}* 的天气\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)

    location_data = await get_location_id(location)
    if not location_data:
        await message.edit_text(f"❌ 找不到城市 *{safe_location}*，请检查拼写。", parse_mode=ParseMode.MARKDOWN_V2)
        # 调度删除错误消息
        from utils.message_manager import _schedule_deletion
        config = get_config()
        await _schedule_deletion(context, update.effective_chat.id, message.message_id, 10)  # 错误消息10秒后删除
        return

    location_id = location_data['id']
    location_name = f"{location_data['name']}, {location_data['adm1']}"
    safe_location_name = escape_markdown(location_name, version=2)

    result_text = ""
    reply_markup = None
    
    if not param:
        realtime_data = await _get_api_response("weather/now", {"location": location_id})
        air_data = await _get_api_response("air/now", {"location": location_id})

        if realtime_data:
            result_text = format_realtime_weather(realtime_data, location_name)
        else:
            result_text = f"❌ 获取 *{safe_location_name}* 实时天气失败。\n"

        # 只有当空气质量数据有效时才显示
        if air_data and air_data.get('now') and air_data.get('now').get('aqi'):
            result_text += format_air_quality(air_data)
        # 对于没有空气质量数据的地区，不显示任何信息（静默处理）

        # 创建功能按钮
        keyboard = [
            [
                InlineKeyboardButton("🤖 AI日报", callback_data=f"weather_aireport_{location}"),
                InlineKeyboardButton("📅 3天预报", callback_data=f"weather_3d_{location}")
            ],
            [
                InlineKeyboardButton("📊 7天预报", callback_data=f"weather_7d_{location}"),
                InlineKeyboardButton("📈 15天预报", callback_data=f"weather_15d_{location}")
            ],
            [
                InlineKeyboardButton("⏰ 24小时预报", callback_data=f"weather_24h_{location}"),
                InlineKeyboardButton("🕐 72小时预报", callback_data=f"weather_72h_{location}")
            ],
            [
                InlineKeyboardButton("🌧️ 分钟降水", callback_data=f"weather_rain_{location}"),
                InlineKeyboardButton("📋 生活指数", callback_data=f"weather_indices_{location}")
            ],
            [
                InlineKeyboardButton("⚠️ 天气预警", callback_data=f"weather_alert_{location}"),
                InlineKeyboardButton("🌀 台风追踪", callback_data="typhoon_list")
            ],
            [
                InlineKeyboardButton("🔄 刷新", callback_data=f"weather_now_{location}"),
                InlineKeyboardButton("❌ 关闭", callback_data="weather_close")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

    elif param.endswith('h') and param[:-1].isdigit() and 1 <= int(param[:-1]) <= 168:
        hours = int(param[:-1])
        endpoint = "weather/24h" if hours <= 24 else "weather/72h" if hours <= 72 else "weather/168h"
        data = await _get_api_response(endpoint, {"location": location_id})
        if data and data.get("hourly"):
            result_text = f"🌍 *{safe_location_name}* 未来 {hours} 小时天气预报：\n\n"
            result_text += format_hourly_weather(data["hourly"][:hours])
        else:
            result_text = f"❌ 获取 *{safe_location_name}* 的逐小时天气失败。"

    elif param == "降水":
        coords = f"{location_data['lon']},{location_data['lat']}"
        data = await _get_api_response("minutely/5m", {"location": coords})
        if data:
            result_text = f"🌍 *{safe_location_name}* 未来2小时分钟级降水预报：\n"
            result_text += format_minutely_rainfall(data)
        else:
            result_text = f"❌ 获取 *{safe_location_name}* 的分钟级降水失败。"
            
    elif param.startswith("指数"):
        days_param = "3d" if param.endswith("3") else "1d"
        data = await _get_api_response(f"indices/{days_param}", {"location": location_id, "type": "0"})
        if data:
            result_text = f"🌍 *{safe_location_name}* 的天气指数预报："
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
                    result_text = f"🌍 *{safe_location_name}* {escape_markdown(date1.strftime('%m月%d日'), version=2)} 天气预报：\n\n"
                    daily_data = [d for d in data["daily"] if d["fxDate"] == date1.strftime("%Y-%m-%d")]
                else:
                    start_str = date1.strftime('%m月%d日')
                    end_str = date2.strftime('%m月%d日')
                    title = f"未来 {(date2 - date1).days + 1} 天" if query_type == 'multiple_days' else f"{start_str}到{end_str}"
                    result_text = f"🌍 *{safe_location_name}* {escape_markdown(title, version=2)}天气预报：\n\n"
                    daily_data = [d for d in data["daily"] if date1 <= datetime.datetime.strptime(d["fxDate"], "%Y-%m-%d").date() <= date2]
                result_text += format_daily_weather(daily_data)
            else:
                result_text = f"\n❌ 获取 *{safe_location_name}* 的天气信息失败。"

    await message.edit_text(
        foldable_text_with_markdown_v2(result_text),
        parse_mode=ParseMode.MARKDOWN_V2,
        disable_web_page_preview=True,
        reply_markup=reply_markup
    )

    # 调度删除机器人回复消息，使用配置的延迟时间
    from utils.message_manager import _schedule_deletion
    config = get_config()
    await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)

async def tq_clean_cache_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /tq_cleancache 命令以清理天气查询相关缓存"""
    if not update.message or not update.effective_chat:
        return
    try:
        # 清理所有天气相关缓存
        prefixes = [
            "weather_location_", "weather_realtime_", "weather_forecast_",
            "weather_hourly_", "weather_air_", "weather_indices_", "weather_minutely_"
        ]
        for prefix in prefixes:
            await context.bot_data["cache_manager"].clear_cache(
                subdirectory="weather", 
                key_prefix=prefix
            )
        success_message = "✅ 天气查询缓存已清理。"
        await send_success(context, update.effective_chat.id, foldable_text_v2(success_message), parse_mode="MarkdownV2")
        await delete_user_command(context, update.effective_chat.id, update.message.message_id)
        return
    except Exception as e:
        logging.error(f"Error clearing weather cache: {e}")
        error_message = f"❌ 清理天气缓存时发生错误: {e!s}"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        await delete_user_command(context, update.effective_chat.id, update.message.message_id)
        return

# 新增专门的分类清理命令
async def tq_clean_location_cache_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """清理天气位置缓存"""
    if not update.message or not update.effective_chat:
        return
    try:
        await context.bot_data["cache_manager"].clear_cache(
            subdirectory="weather", 
            key_prefix="weather_location_"
        )
        success_message = "✅ 天气位置缓存已清理。"
        await send_success(context, update.effective_chat.id, foldable_text_v2(success_message), parse_mode="MarkdownV2")
        await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    except Exception as e:
        logging.error(f"Error clearing weather location cache: {e}")
        error_message = f"❌ 清理天气位置缓存时发生错误: {e!s}"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        await delete_user_command(context, update.effective_chat.id, update.message.message_id)

async def tq_clean_forecast_cache_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """清理天气预报缓存"""
    if not update.message or not update.effective_chat:
        return
    try:
        prefixes = ["weather_forecast_", "weather_hourly_"]
        for prefix in prefixes:
            await context.bot_data["cache_manager"].clear_cache(
                subdirectory="weather", 
                key_prefix=prefix
            )
        success_message = "✅ 天气预报缓存已清理。"
        await send_success(context, update.effective_chat.id, foldable_text_v2(success_message), parse_mode="MarkdownV2")
        await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    except Exception as e:
        logging.error(f"Error clearing weather forecast cache: {e}")
        error_message = f"❌ 清理天气预报缓存时发生错误: {e!s}"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        await delete_user_command(context, update.effective_chat.id, update.message.message_id)

async def tq_clean_realtime_cache_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """清理实时天气缓存"""
    if not update.message or not update.effective_chat:
        return
    try:
        prefixes = ["weather_realtime_", "weather_air_", "weather_minutely_"]
        for prefix in prefixes:
            await context.bot_data["cache_manager"].clear_cache(
                subdirectory="weather", 
                key_prefix=prefix
            )
        success_message = "✅ 实时天气缓存已清理。"
        await send_success(context, update.effective_chat.id, foldable_text_v2(success_message), parse_mode="MarkdownV2")
        await delete_user_command(context, update.effective_chat.id, update.message.message_id)
    except Exception as e:
        logging.error(f"Error clearing weather realtime cache: {e}")
        error_message = f"❌ 清理实时天气缓存时发生错误: {e!s}"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        await delete_user_command(context, update.effective_chat.id, update.message.message_id)

async def weather_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理天气查询的回调"""
    query = update.callback_query
    if not query:
        return

    await query.answer()
    data = query.data

    try:
        if data == "weather_close":
            # 关闭消息
            await query.message.delete()
            return

        # 处理菜单搜索
        if data == "weather_menu_search":
            help_text = """🌤️ *天气查询说明*

请使用以下格式查询天气：
`/tq 城市名`

*示例：*
• `/tq 吉隆坡` \\- 查询吉隆坡实时天气
• `/tq 北京` \\- 查询北京实时天气
• `/tq 上海 3` \\- 查询上海3天预报

查询后可通过按钮查看：
• 🤖 AI日报、📅 多日预报
• ⏰ 小时预报、🌧️ 分钟降水
• 📋 生活指数、⚠️ 天气预警"""

            await query.edit_message_text(
                help_text,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ 关闭", callback_data="weather_close")
                ]])
            )
            return

        # 解析回调数据 - 格式: weather_action_location
        parts = data.split('_', 2)
        if len(parts) < 3:
            await query.edit_message_text(
                "❌ 无效的请求",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ 关闭", callback_data="weather_close")
                ]])
            )
            # 调度删除错误消息
            from utils.message_manager import _schedule_deletion
            await _schedule_deletion(context, query.message.chat_id, query.message.message_id, 10)
            return

        action = parts[1]
        location = parts[2]

        # 显示加载状态
        safe_location = escape_markdown(location, version=2)
        await query.edit_message_text(
            f"🔍 正在查询 *{safe_location}* 的天气\\.\\.\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )

        # 获取位置信息
        location_data = await get_location_id(location)
        if not location_data:
            await query.edit_message_text(
                f"❌ 找不到城市 *{safe_location}*，请检查拼写。",
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ 关闭", callback_data="weather_close")
                ]])
            )
            # 调度删除错误消息
            from utils.message_manager import _schedule_deletion
            await _schedule_deletion(context, query.message.chat_id, query.message.message_id, 10)  # 错误消息10秒后删除
            return

        location_id = location_data['id']
        location_name = f"{location_data['name']}, {location_data['adm1']}"
        safe_location_name = escape_markdown(location_name, version=2)

        result_text = ""
        keyboard = []

        # 根据action执行不同操作
        if action == "now":
            # 实时天气
            realtime_data = await _get_api_response("weather/now", {"location": location_id})
            air_data = await _get_api_response("air/now", {"location": location_id})

            if realtime_data:
                result_text = format_realtime_weather(realtime_data, location_name)
            else:
                result_text = f"❌ 获取 *{safe_location_name}* 实时天气失败。\n"

            if air_data and air_data.get('now') and air_data.get('now').get('aqi'):
                result_text += format_air_quality(air_data)

            # 创建功能按钮
            keyboard = [
                [
                    InlineKeyboardButton("🤖 AI日报", callback_data=f"weather_aireport_{location}"),
                    InlineKeyboardButton("📅 3天预报", callback_data=f"weather_3d_{location}")
                ],
                [
                    InlineKeyboardButton("📊 7天预报", callback_data=f"weather_7d_{location}"),
                    InlineKeyboardButton("📈 15天预报", callback_data=f"weather_15d_{location}")
                ],
                [
                    InlineKeyboardButton("⏰ 24小时预报", callback_data=f"weather_24h_{location}"),
                    InlineKeyboardButton("🕐 72小时预报", callback_data=f"weather_72h_{location}")
                ],
                [
                    InlineKeyboardButton("🌧️ 分钟降水", callback_data=f"weather_rain_{location}"),
                    InlineKeyboardButton("📋 生活指数", callback_data=f"weather_indices_{location}")
                ],
                [
                    InlineKeyboardButton("⚠️ 天气预警", callback_data=f"weather_alert_{location}"),
                    InlineKeyboardButton("🌀 台风追踪", callback_data="typhoon_list")
                ],
                [
                    InlineKeyboardButton("🔄 刷新", callback_data=f"weather_now_{location}"),
                    InlineKeyboardButton("❌ 关闭", callback_data="weather_close")
                ]
            ]

        elif action in ["3d", "7d", "15d", "30d"]:
            # 多日预报
            days = int(action[:-1])
            endpoint = f"weather/{action}"
            data = await _get_api_response(endpoint, {"location": location_id})

            if data and data.get("daily"):
                result_text = f"🌍 *{safe_location_name}* 未来 {days} 天天气预报：\n\n"
                result_text += format_daily_weather(data["daily"][:days])
            else:
                result_text = f"❌ 获取 *{safe_location_name}* 的天气预报失败。"

            keyboard = [
                [
                    InlineKeyboardButton("🔙 返回实时", callback_data=f"weather_now_{location}"),
                    InlineKeyboardButton("❌ 关闭", callback_data="weather_close")
                ]
            ]

        elif action in ["24h", "72h", "168h"]:
            # 逐小时预报
            hours = int(action[:-1])
            endpoint = f"weather/{action}"
            data = await _get_api_response(endpoint, {"location": location_id})

            if data and data.get("hourly"):
                result_text = f"🌍 *{safe_location_name}* 未来 {hours} 小时天气预报：\n\n"
                result_text += format_hourly_weather(data["hourly"][:hours])
            else:
                result_text = f"❌ 获取 *{safe_location_name}* 的逐小时天气失败。"

            keyboard = [
                [
                    InlineKeyboardButton("🔙 返回实时", callback_data=f"weather_now_{location}"),
                    InlineKeyboardButton("❌ 关闭", callback_data="weather_close")
                ]
            ]

        elif action == "rain":
            # 分钟级降水
            coords = f"{location_data['lon']},{location_data['lat']}"
            data = await _get_api_response("minutely/5m", {"location": coords})

            if data:
                result_text = f"🌍 *{safe_location_name}* 未来2小时分钟级降水预报：\n"
                result_text += format_minutely_rainfall(data)
            else:
                result_text = f"❌ 获取 *{safe_location_name}* 的分钟级降水失败。"

            keyboard = [
                [
                    InlineKeyboardButton("🔙 返回实时", callback_data=f"weather_now_{location}"),
                    InlineKeyboardButton("❌ 关闭", callback_data="weather_close")
                ]
            ]

        elif action in ["indices", "indices3"]:
            # 生活指数
            days_param = "3d" if action == "indices3" else "1d"
            data = await _get_api_response(f"indices/{days_param}", {"location": location_id, "type": "0"})

            if data:
                result_text = f"🌍 *{safe_location_name}* 的天气指数预报："
                result_text += format_indices_data(data)
            else:
                result_text = f"❌ 获取 *{safe_location_name}* 的生活指数失败。"

            keyboard = [
                [
                    InlineKeyboardButton("🔙 返回实时", callback_data=f"weather_now_{location}"),
                    InlineKeyboardButton("❌ 关闭", callback_data="weather_close")
                ]
            ]

        elif action == "aireport":
            # AI 天气日报
            if not OPENAI_AVAILABLE:
                result_text = "❌ AI 功能未启用，请安装 openai 库。"
            elif not get_config().openai_api_key:
                result_text = "❌ 未配置 OpenAI API Key，请在 .env 文件中配置 OPENAI_API_KEY。"
            else:
                # 获取所有需要的数据
                realtime_data = await _get_api_response("weather/now", {"location": location_id})
                daily_data = await _get_api_response("weather/3d", {"location": location_id})
                hourly_data = await _get_api_response("weather/24h", {"location": location_id})
                indices_data = await _get_api_response("indices/1d", {"location": location_id, "type": "0"})
                air_data = await _get_api_response("air/now", {"location": location_id})

                # 获取天气预警数据
                lat = float(location_data['lat'])
                lon = float(location_data['lon'])
                alerts_data = await get_weather_alerts(lat, lon)

                if not realtime_data or not daily_data or not hourly_data or not indices_data:
                    result_text = f"❌ 获取 *{safe_location_name}* 的天气数据失败，无法生成 AI 日报。"
                else:
                    # 生成 AI 日报
                    await query.edit_message_text(
                        f"🤖 正在生成 *{safe_location_name}* 的 AI 天气日报\\.\\.\\.\n\n⏳ 敏敏正在努力整理天气信息中\\.\\.\\.请稍候～",
                        parse_mode=ParseMode.MARKDOWN_V2
                    )

                    ai_report = await generate_ai_weather_report(
                        location_name,
                        realtime_data,
                        daily_data,
                        hourly_data,
                        indices_data,
                        air_data,
                        alerts_data
                    )

                    if ai_report:
                        result_text = ai_report
                    else:
                        result_text = f"❌ AI 日报生成失败，请稍后重试。"

            keyboard = [
                [
                    InlineKeyboardButton("🔙 返回实时", callback_data=f"weather_now_{location}"),
                    InlineKeyboardButton("❌ 关闭", callback_data="weather_close")
                ]
            ]

        elif action == "alert":
            # 天气预警
            lat = float(location_data['lat'])
            lon = float(location_data['lon'])
            alerts_data = await get_weather_alerts(lat, lon)

            if alerts_data:
                result_text = format_weather_alerts(alerts_data, location_name)
            else:
                result_text = f"❌ 获取 *{safe_location_name}* 的天气预警失败。"

            keyboard = [
                [
                    InlineKeyboardButton("🔙 返回实时", callback_data=f"weather_now_{location}"),
                    InlineKeyboardButton("❌ 关闭", callback_data="weather_close")
                ]
            ]

        else:
            await query.edit_message_text(
                "❌ 未知的操作",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ 关闭", callback_data="weather_close")
                ]])
            )
            # 调度删除错误消息
            from utils.message_manager import _schedule_deletion
            await _schedule_deletion(context, query.message.chat_id, query.message.message_id, 10)
            return

        # 发送结果
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        await query.edit_message_text(
            foldable_text_with_markdown_v2(result_text),
            parse_mode=ParseMode.MARKDOWN_V2,
            disable_web_page_preview=True,
            reply_markup=reply_markup
        )

    except Exception as e:
        logging.error(f"天气回调处理失败: {e}")
        await query.edit_message_text(
            "❌ 处理请求时发生错误，请稍后重试",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ 关闭", callback_data="weather_close")
            ]])
        )
        # 调度删除错误消息
        from utils.message_manager import _schedule_deletion
        await _schedule_deletion(context, query.message.chat_id, query.message.message_id, 10)

async def typhoon_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理台风追踪的回调"""
    query = update.callback_query
    if not query:
        return

    await query.answer()
    data = query.data

    try:
        # 处理台风列表查询
        if data == "typhoon_list":
            # 显示加载状态
            await query.edit_message_text(
                "🌀 正在查询活跃台风\\.\\.\\.",
                parse_mode=ParseMode.MARKDOWN_V2
            )

            # 获取活跃台风列表
            active_data = await get_active_typhoons(basin="NP")  # 西北太平洋

            if not active_data or not active_data.get("storms"):
                # 没有活跃台风
                await query.edit_message_text(
                    "✅ *当前西北太平洋无活跃台风*\n\n"
                    "💡 提示：台风季节通常为 5\\-11 月",
                    parse_mode=ParseMode.MARKDOWN_V2,
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("❌ 关闭", callback_data="weather_close")
                    ]])
                )
                return

            # 有活跃台风，显示列表
            storms = active_data.get("storms", [])
            result_text = f"🌀 *当前活跃台风* （共 {len(storms)} 个）\n\n"

            for storm in storms:
                storm_id = storm.get("stormId", "N/A")
                name = storm.get("name", "未命名")
                basin_name = storm.get("basinName", "N/A")

                result_text += f"• *{escape_markdown(name, version=2)}*\n"
                result_text += f"  ID: {escape_markdown(storm_id, version=2)}\n"
                result_text += f"  区域: {escape_markdown(basin_name, version=2)}\n\n"

            # 创建按钮 - 为每个台风创建一个查看详情按钮
            keyboard = []
            for storm in storms:
                storm_id = storm.get("stormId", "")
                name = storm.get("name", "未命名")
                if storm_id:
                    keyboard.append([
                        InlineKeyboardButton(
                            f"📊 查看 {name} 详情",
                            callback_data=f"typhoon_detail_{storm_id}"
                        )
                    ])

            keyboard.append([InlineKeyboardButton("❌ 关闭", callback_data="weather_close")])

            await query.edit_message_text(
                result_text,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        # 解析回调数据 - 格式: typhoon_detail_{storm_id}
        elif data.startswith("typhoon_detail_"):
            storm_id = data.replace("typhoon_detail_", "")

            # 显示加载状态
            await query.edit_message_text(
                f"🌀 正在获取台风详情\\.\\.\\.",
                parse_mode=ParseMode.MARKDOWN_V2
            )

            # 获取台风路径数据
            track_data = await get_typhoon_track(storm_id)

            if track_data:
                result_text = format_typhoon_info(track_data)
            else:
                result_text = f"❌ 获取台风 {escape_markdown(storm_id, version=2)} 的详情失败。"

            # 返回按钮
            keyboard = [[InlineKeyboardButton("❌ 关闭", callback_data="weather_close")]]

            await query.edit_message_text(
                result_text,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        else:
            await query.edit_message_text(
                "❌ 未知的操作",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ 关闭", callback_data="weather_close")
                ]])
            )
            # 调度删除错误消息
            from utils.message_manager import _schedule_deletion
            await _schedule_deletion(context, query.message.chat_id, query.message.message_id, 10)

    except Exception as e:
        logging.error(f"台风回调处理失败: {e}")
        await query.edit_message_text(
            "❌ 处理请求时发生错误，请稍后重试",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ 关闭", callback_data="weather_close")
            ]])
        )
        # 调度删除错误消息
        from utils.message_manager import _schedule_deletion
        await _schedule_deletion(context, query.message.chat_id, query.message.message_id, 10)

command_factory.register_command(
    "tq",
    weather_command,
    permission=Permission.USER,
    description="查询天气预报，支持多日、小时、指数等"
)

# 注册回调处理器
command_factory.register_callback(
    "^weather_",
    weather_callback_handler,
    permission=Permission.USER,
    description="天气功能回调处理器"
)

# 注册台风回调处理器（不注册独立命令，只通过菜单按钮访问）
command_factory.register_callback(
    "^typhoon_",
    typhoon_callback_handler,
    permission=Permission.USER,
    description="台风追踪回调处理器"
)

# 已迁移到统一缓存管理命令 /cleancache
# command_factory.register_command(
#     "tq_cleancache", 
#     tq_clean_cache_command, 
#     permission=Permission.ADMIN, 
#     description="清理天气查询缓存"
# )

# 已迁移到统一缓存管理命令 /cleancache
# command_factory.register_command(
#     "tq_cleanlocation", 
#     tq_clean_location_cache_command, 
#     permission=Permission.ADMIN, 
#     description="清理天气位置缓存"
# )

# command_factory.register_command(
#     "tq_cleanforecast", 
#     tq_clean_forecast_cache_command, 
#     permission=Permission.ADMIN, 
#     description="清理天气预报缓存"
# )

# command_factory.register_command(
#     "tq_cleanrealtime",
#     tq_clean_realtime_cache_command,
#     permission=Permission.ADMIN,
#     description="清理实时天气缓存"
# )


# =============================================================================
# Inline 执行入口
# =============================================================================

async def weather_inline_execute(args: str, use_ai_report: bool = True) -> dict:
    """
    Inline Query 执行入口 - 提供完整的天气查询功能（含 AI 日报）

    Args:
        args: 用户输入的参数字符串，如 "北京" 或 "上海"
        use_ai_report: 是否生成 AI 日报（默认 True）

    Returns:
        dict: {
            "success": bool,
            "title": str,
            "message": str,
            "description": str,
            "error": str | None
        }
    """
    if not args or not args.strip():
        return {
            "success": False,
            "title": "❌ 请输入城市名",
            "message": "请提供城市名称\\n\\n*使用方法:*\\n• `weather 北京` \\\\- 查询北京天气\\n• `weather 上海` \\\\- 查询上海天气",
            "description": "请提供城市名称",
            "error": "未提供城市参数"
        }

    if not cache_manager or not httpx_client:
        return {
            "success": False,
            "title": "❌ 服务未初始化",
            "message": "天气查询服务未初始化，请联系管理员",
            "description": "服务未初始化",
            "error": "服务未初始化"
        }

    location = args.strip().split()[0]  # 只取第一个参数作为城市名

    try:
        # 获取位置信息
        location_data = await get_location_id(location)
        if not location_data:
            return {
                "success": False,
                "title": f"❌ 找不到城市 {location}",
                "message": f"找不到城市 *{location}*，请检查拼写",
                "description": f"找不到城市: {location}",
                "error": "城市不存在"
            }

        location_id = location_data['id']
        location_name = f"{location_data['name']}, {location_data['adm1']}"

        # 获取实时天气和空气质量
        realtime_data = await _get_api_response("weather/now", {"location": location_id})
        air_data = await _get_api_response("air/now", {"location": location_id})

        if not realtime_data:
            return {
                "success": False,
                "title": f"❌ 获取天气失败",
                "message": f"无法获取 *{location_name}* 的天气数据",
                "description": "获取天气数据失败",
                "error": "API 请求失败"
            }

        # 尝试生成 AI 日报
        ai_report = None
        if use_ai_report and OPENAI_AVAILABLE and get_config().openai_api_key:
            try:
                # 获取更多数据用于 AI 日报
                daily_data = await _get_api_response("weather/3d", {"location": location_id})
                hourly_data = await _get_api_response("weather/24h", {"location": location_id})
                indices_data = await _get_api_response("indices/1d", {"location": location_id, "type": "0"})

                # 获取天气预警
                lat = float(location_data['lat'])
                lon = float(location_data['lon'])
                alerts_data = await get_weather_alerts(lat, lon)

                if realtime_data and daily_data and hourly_data and indices_data:
                    ai_report = await generate_ai_weather_report(
                        location_name,
                        realtime_data,
                        daily_data,
                        hourly_data,
                        indices_data,
                        air_data,
                        alerts_data
                    )
            except Exception as e:
                logging.warning(f"AI 日报生成失败: {e}")

        # 构建结果
        if ai_report:
            # 使用 AI 日报
            result_text = ai_report
            title = f"🤖 {location_name} AI天气日报"
            description = f"敏敏为你播报 {location_name} 天气"
        else:
            # 使用传统格式
            result_text = format_realtime_weather(realtime_data, location_name)
            if air_data and air_data.get('now') and air_data.get('now').get('aqi'):
                result_text += format_air_quality(air_data)
            title = f"🌤️ {location_name} 实时天气"

            # 提取简短描述
            now = realtime_data.get("now", {})
            temp = now.get('temp', 'N/A')
            text = now.get('text', 'N/A')
            description = f"{text} {temp}°C"

        return {
            "success": True,
            "title": title,
            "message": result_text,
            "description": description,
            "error": None
        }

    except Exception as e:
        logging.error(f"Inline weather query failed: {e}")
        return {
            "success": False,
            "title": "❌ 查询失败",
            "message": f"查询天气失败: {str(e)}",
            "description": "查询失败",
            "error": str(e)
        }
