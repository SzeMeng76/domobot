# Description: Steam 模块的配置和错误处理类
# 从原 steam.py 拆分

import logging
import os

from utils.constants import (
    DEFAULT_STEAM_REDIS_CACHE,
    DEFAULT_STEAM_DB_FRESHNESS,
)

logger = logging.getLogger(__name__)


class Config:
    """Steam 模块配置类"""

    DEFAULT_CC = "CN"
    DEFAULT_LANG = "schinese"
    MAX_SEARCH_RESULTS = 20
    MAX_BUNDLE_RESULTS = 10
    MAX_SEARCH_ITEMS = 15
    REQUEST_DELAY = 1.0  # 请求延迟，避免速率限制

    def __init__(self):
        self.steam_redis_cache = int(
            os.getenv("STEAM_REDIS_CACHE", DEFAULT_STEAM_REDIS_CACHE)
        )
        self.steam_db_freshness = int(
            os.getenv("STEAM_DB_FRESHNESS", DEFAULT_STEAM_DB_FRESHNESS)
        )

    @property
    def PRICE_CACHE_DURATION(self):
        return self.steam_redis_cache


class ErrorHandler:
    """错误处理和消息格式化"""

    @staticmethod
    def log_error(error: Exception, context: str = "") -> str:
        logger.error(f"Error in {context}: {error}")
        return f"❌ {context}失败: {error!s}"

    @staticmethod
    def handle_network_error(error: Exception) -> str:
        if "timeout" in str(error).lower():
            return "❌ 请求超时，请稍后重试"
        elif "connection" in str(error).lower():
            return "❌ 网络连接失败，请检查网络"
        else:
            return f"❌ 网络请求失败: {error!s}"
