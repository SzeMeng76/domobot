"""
Apple Services 模块
"""

import logging

from .service import AppleServicesService, DEFAULT_COUNTRIES

__all__ = ["AppleServicesService", "DEFAULT_COUNTRIES", "init_apple_services_bot"]

logger = logging.getLogger(__name__)


def init_apple_services_bot(
    application,
    cache_manager,
    rate_converter,
    smart_cache_manager=None,
    task_scheduler=None,
):
    """初始化 Apple Services 价格查询服务并存储到 bot_data

    Args:
        application: Telegram Application 实例
        cache_manager: Redis 缓存管理器
        rate_converter: 汇率转换器
        rate_converter: 汇率转换器
        smart_cache_manager: 智能缓存管理器（可选，Apple Services 暂时不使用）
        task_scheduler: 任务调度器（可选）
    """
    from utils.http_client import get_http_client

    httpx_client = get_http_client()

    import os
    from utils.constants import DEFAULT_APPLE_SERVICES_CACHE_DURATION

    redis_cache = int(
        os.getenv("APPLE_SERVICES_REDIS_CACHE", DEFAULT_APPLE_SERVICES_CACHE_DURATION)
    )

    service = AppleServicesService(
        cache_manager=cache_manager,
        rate_converter=rate_converter,
        httpx_client=httpx_client,
        redis_cache_duration=redis_cache,
    )
    application.bot_data["apple_services_service"] = service
    logger.info("✅ Apple Services 服务初始化完成")
