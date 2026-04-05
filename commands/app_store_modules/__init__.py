"""
App Store 模块

重构的 App Store 功能模块，提供应用搜索和价格查询功能
"""

from .api import AppStoreWebAPI
from .constants import DEFAULT_COUNTRIES, PLATFORM_FLAGS, PLATFORM_INFO
from .parser import AppStoreParser
from .price_bot import AppStorePriceBot

__all__ = [
    "AppStoreWebAPI",
    "AppStoreParser",
    "DEFAULT_COUNTRIES",
    "PLATFORM_FLAGS",
    "PLATFORM_INFO",
    "AppStorePriceBot",
]


def init_app_store_bot(
    application, cache_manager, rate_converter, smart_cache_manager, task_scheduler=None
):
    """初始化 App Store 价格查询机器人并存储到 bot_data

    Args:
        application: Telegram Application 实例
        cache_manager: Redis 缓存管理器
        rate_converter: 汇率转换器
        smart_cache_manager: 智能缓存管理器
        task_scheduler: 任务调度器（可选）
    """
    import os
    import logging
    from utils.constants import (
        DEFAULT_APP_STORE_REDIS_CACHE,
        DEFAULT_APP_STORE_DB_FRESHNESS,
    )

    logger = logging.getLogger(__name__)

    redis_cache = int(os.getenv("APP_STORE_REDIS_CACHE", DEFAULT_APP_STORE_REDIS_CACHE))
    db_freshness = int(
        os.getenv("APP_STORE_DB_FRESHNESS", DEFAULT_APP_STORE_DB_FRESHNESS)
    )

    bot = AppStorePriceBot(
        cache_manager,
        rate_converter,
        smart_cache_manager,
        redis_cache_duration=redis_cache,
        db_freshness=db_freshness,
    )
    application.bot_data["app_store_price_bot"] = bot
    logger.info("✅ App Store 价格查询机器人初始化完成")

