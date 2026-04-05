"""
Google Play 模块包
包含 Sensor Tower API 封装和 Google Play 服务类
"""

import logging

from .sensor_tower_api import SensorTowerAPI
from .service import GooglePlayService

__all__ = ["SensorTowerAPI", "GooglePlayService", "init_google_play_bot"]

logger = logging.getLogger(__name__)


def init_google_play_bot(
    application,
    cache_manager,
    rate_converter,
    smart_cache_manager=None,
    task_scheduler=None,
):
    """初始化 Google Play 服务并存储到 bot_data

    Args:
        application: Telegram Application 实例
        cache_manager: Redis 缓存管理器
        rate_converter: 汇率转换器
        smart_cache_manager: 智能缓存管理器（可选）
        task_scheduler: 任务调度器（可选）
    """
    import os
    from utils.constants import (
        DEFAULT_GOOGLE_PLAY_REDIS_CACHE,
        DEFAULT_GOOGLE_PLAY_DB_FRESHNESS,
    )

    redis_cache = int(
        os.getenv("GOOGLE_PLAY_REDIS_CACHE", DEFAULT_GOOGLE_PLAY_REDIS_CACHE)
    )
    db_freshness = int(
        os.getenv("GOOGLE_PLAY_DB_FRESHNESS", DEFAULT_GOOGLE_PLAY_DB_FRESHNESS)
    )

    service = GooglePlayService(
        cache_manager=cache_manager,
        rate_converter=rate_converter,
        smart_cache_manager=smart_cache_manager,
        redis_cache_duration=redis_cache,
        db_freshness=db_freshness,
    )
    application.bot_data["google_play_service"] = service
    logger.info("✅ Google Play 服务初始化完成")
