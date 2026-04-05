"""
Steam 价格查询机器人类

封装 Steam 模块的依赖注入逻辑，统一接口与其他服务保持一致。
"""

import logging

from utils.rate_converter import RateConverter

from .cache import set_cache_manager, set_rate_converter, set_smart_cache_manager

logger = logging.getLogger(__name__)


class SteamPriceBot:
    """Steam 价格查询服务

    封装 Steam 模块的依赖管理，提供统一的初始化接口。
    Steam 模块内部使用全局变量模式，此类负责注入这些依赖。
    """

    def __init__(
        self,
        cache_manager,
        rate_converter: RateConverter,
        smart_cache_manager=None,
    ):
        """
        初始化 Steam 价格查询机器人

        Args:
            cache_manager: Redis 缓存管理器实例
            rate_converter: 汇率转换器实例
            smart_cache_manager: 智能缓存管理器实例 (可选, 用于 MySQL 持久化)
        """
        self.cache_manager = cache_manager
        self.rate_converter = rate_converter
        self.smart_cache_manager = smart_cache_manager

        # 注入依赖到 Steam 模块的全局变量
        set_cache_manager(cache_manager)
        set_rate_converter(rate_converter)
        if smart_cache_manager:
            set_smart_cache_manager(smart_cache_manager)

        logger.info("SteamPriceBot 依赖注入完成")

    def get_dependencies(self):
        """获取当前依赖（用于调试）"""
        return {
            "cache_manager": self.cache_manager,
            "rate_converter": self.rate_converter,
            "smart_cache_manager": self.smart_cache_manager,
        }
