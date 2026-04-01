"""
彩云天气 API 适配器
提供智能天气摘要和详细天气数据
"""

import logging
from typing import Optional, Dict
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# 彩云天气天气代码映射
SKYCON_MAP = {
    "CLEAR_DAY": ("晴", "☀️"),
    "CLEAR_NIGHT": ("晴", "🌙"),
    "PARTLY_CLOUDY_DAY": ("多云", "⛅"),
    "PARTLY_CLOUDY_NIGHT": ("多云", "☁️"),
    "CLOUDY": ("阴", "☁️"),
    "LIGHT_HAZE": ("轻度雾霾", "🌫️"),
    "MODERATE_HAZE": ("中度雾霾", "🌫️"),
    "HEAVY_HAZE": ("重度雾霾", "🌫️"),
    "LIGHT_RAIN": ("小雨", "🌧️"),
    "MODERATE_RAIN": ("中雨", "🌧️"),
    "HEAVY_RAIN": ("大雨", "🌧️"),
    "STORM_RAIN": ("暴雨", "⛈️"),
    "FOG": ("雾", "🌫️"),
    "LIGHT_SNOW": ("小雪", "🌨️"),
    "MODERATE_SNOW": ("中雪", "🌨️"),
    "HEAVY_SNOW": ("大雪", "🌨️"),
    "STORM_SNOW": ("暴雪", "❄️"),
    "DUST": ("浮尘", "🌪️"),
    "SAND": ("沙尘", "🌪️"),
    "WIND": ("大风", "🌬️"),
}


class CaiyunAdapter:
    """彩云天气适配器"""

    def __init__(self, api_token: str, httpx_client, cache_manager=None):
        self.api_token = api_token
        self.client = httpx_client
        self.cache_manager = cache_manager
        self.base_url = "https://api.caiyunapp.com/v2.6"

    def _get_skycon_info(self, skycon: str) -> tuple:
        """获取天气代码对应的文本和图标"""
        return SKYCON_MAP.get(skycon, (skycon, "❓"))

    async def get_weather(self, coords: str) -> Optional[Dict]:
        """
        获取彩云天气数据

        Args:
            coords: 经纬度字符串，格式："lon,lat" (例如："116.4074,39.9042")

        Returns:
            天气数据字典，包含智能摘要等信息
        """
        if "," not in coords:
            logger.warning(f"彩云天气需要经纬度格式 (lon,lat)，收到: {coords}")
            return None

        clean_coords = coords.replace(" ", "")

        # 检查缓存
        if self.cache_manager:
            cache_key = f"caiyun_weather_{clean_coords}"
            cached_data = await self.cache_manager.get(cache_key, subdirectory="weather")
            if cached_data:
                logger.info(f"彩云天气缓存命中: {clean_coords}")
                return cached_data

        # 构建请求URL
        url = f"{self.base_url}/{self.api_token}/{clean_coords}/weather.json"
        params = {
            "alert": "true",
            "dailysteps": "7",
            "hourlysteps": "48",
            "unit": "metric:v2"
        }

        try:
            response = await self.client.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data.get("status") != "ok":
                logger.warning(f"彩云天气 API 错误: {data.get('error')}")
                return None

            logger.info("彩云天气 API 请求成功")
            result = data.get("result")

            # 保存到缓存（30分钟）
            if self.cache_manager and result:
                cache_key = f"caiyun_weather_{clean_coords}"
                await self.cache_manager.set(
                    cache_key,
                    result,
                    subdirectory="weather",
                    ttl=1800  # 30分钟
                )
                logger.info(f"彩云天气数据已缓存: {clean_coords}")

            return result

        except Exception as e:
            logger.error(f"彩云天气 API 请求失败: {e}")
            return None

    def extract_summary(self, caiyun_data: Dict) -> Optional[str]:
        """
        提取彩云天气的智能摘要

        Args:
            caiyun_data: 彩云天气返回的result数据

        Returns:
            智能摘要文本
        """
        if not caiyun_data:
            return None

        # 获取 forecast_keypoint（智能摘要）
        keypoint = caiyun_data.get("forecast_keypoint", "")

        # 获取小时级描述
        hourly_desc = caiyun_data.get("hourly", {}).get("description", "")

        # 组合摘要
        if keypoint and hourly_desc:
            return f"{keypoint}\n{hourly_desc}"
        elif keypoint:
            return keypoint
        elif hourly_desc:
            return hourly_desc

        return None

    def get_air_quality(self, caiyun_data: Dict) -> Optional[Dict]:
        """
        提取空气质量数据

        Args:
            caiyun_data: 彩云天气返回的result数据

        Returns:
            空气质量数据字典
        """
        if not caiyun_data:
            return None

        realtime = caiyun_data.get("realtime", {})
        air_quality = realtime.get("air_quality", {})

        if not air_quality:
            return None

        aqi_data = air_quality.get("aqi", {})
        aqi_chn = aqi_data.get("chn", 0)
        desc = air_quality.get("description", {}).get("chn", "")
        pm25 = air_quality.get("pm25", 0)

        # 简单的等级映射
        if not desc:
            if aqi_chn <= 50:
                desc = "优"
            elif aqi_chn <= 100:
                desc = "良"
            elif aqi_chn <= 150:
                desc = "轻度污染"
            elif aqi_chn <= 200:
                desc = "中度污染"
            elif aqi_chn <= 300:
                desc = "重度污染"
            else:
                desc = "严重污染"

        return {
            "aqi": int(aqi_chn),
            "category": desc,
            "pm25": float(pm25),
            "source": "caiyun"
        }
