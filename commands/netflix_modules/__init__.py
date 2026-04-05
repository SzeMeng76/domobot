"""
Netflix 模块

重构的 Netflix 功能模块，提供订阅价格查询功能
"""

import logging
import os

from .price_bot import NetflixPriceBot
from utils.constants import DEFAULT_NETFLIX_REDIS_CACHE

__all__ = ["NetflixPriceBot", "init_netflix_bot"]

logger = logging.getLogger(__name__)


def init_netflix_bot(
    application,
    cache_manager,
    rate_converter,
    smart_cache_manager=None,
    task_scheduler=None,
):
    """初始化 Netflix 价格查询机器人并存储到 bot_data

    Args:
        application: Telegram Application 实例
        cache_manager: Redis 缓存管理器
        rate_converter: 汇率转换器
        smart_cache_manager: 智能缓存管理器（可选，当前未使用）
        task_scheduler: 任务调度器（可选）
    """
    cache_duration = int(os.getenv("NETFLIX_REDIS_CACHE", DEFAULT_NETFLIX_REDIS_CACHE))

    bot = NetflixPriceBot(
        service_name="Netflix",
        cache_manager=cache_manager,
        rate_converter=rate_converter,
        cache_duration_seconds=cache_duration,
        subdirectory="netflix",
    )
    application.bot_data["netflix_price_bot"] = bot
    logger.info("✅ Netflix 价格查询机器人初始化完成")
