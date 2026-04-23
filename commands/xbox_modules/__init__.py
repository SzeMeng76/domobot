"""
Xbox Game Pass 模块

提供 Xbox Game Pass 订阅价格查询功能
"""

import logging
import os

from .price_bot import XboxPriceBot
from utils.constants import DEFAULT_XBOX_REDIS_CACHE

__all__ = ["XboxPriceBot", "init_xbox_bot"]

logger = logging.getLogger(__name__)


def init_xbox_bot(
    application,
    cache_manager,
    rate_converter,
    smart_cache_manager=None,
    task_scheduler=None,
):
    """初始化 Xbox Game Pass 价格查询机器人并存储到 bot_data"""
    cache_duration = int(os.getenv("XBOX_REDIS_CACHE", DEFAULT_XBOX_REDIS_CACHE))

    bot = XboxPriceBot(
        service_name="Xbox Game Pass",
        cache_manager=cache_manager,
        rate_converter=rate_converter,
        cache_duration_seconds=cache_duration,
        subdirectory="xbox",
    )
    application.bot_data["xbox_price_bot"] = bot
    logger.info("✅ Xbox Game Pass 价格查询机器人初始化完成")
