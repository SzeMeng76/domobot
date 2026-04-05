"""
Disney+ 模块

重构的 Disney+ 功能模块，提供订阅价格查询功能
"""

import logging
import os

from .price_bot import DisneyPriceBot
from utils.constants import DEFAULT_DISNEY_REDIS_CACHE

__all__ = ["DisneyPriceBot", "init_disney_bot"]

logger = logging.getLogger(__name__)


def init_disney_bot(
    application,
    cache_manager,
    rate_converter,
    smart_cache_manager=None,
    task_scheduler=None,
):
    """初始化 Disney+ 价格查询机器人并存储到 bot_data

    Args:
        application: Telegram Application 实例
        cache_manager: Redis 缓存管理器
        rate_converter: 汇率转换器
        smart_cache_manager: 智能缓存管理器（可选，当前未使用）
        task_scheduler: 任务调度器（可选）
    """
    cache_duration = int(os.getenv("DISNEY_REDIS_CACHE", DEFAULT_DISNEY_REDIS_CACHE))

    bot = DisneyPriceBot(
        service_name="Disney+",
        cache_manager=cache_manager,
        rate_converter=rate_converter,
        cache_duration_seconds=cache_duration,
        subdirectory="disney_plus",
    )
    application.bot_data["disney_price_bot"] = bot
    logger.info("✅ Disney+ 价格查询机器人初始化完成")
