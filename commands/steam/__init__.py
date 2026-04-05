# Description: Steam 价格查询模块
# 从原 steam.py 模块化拆分

"""
Steam 价格查询模块

提供 Steam 游戏和捆绑包价格查询功能，支持：
- 游戏价格查询和跨区对比
- 捆绑包价格查询
- 价格缓存（Redis + MySQL）

自动发现模式（推荐）:
    # main.py 中会自动调用 init_steam_bot() 函数
    # 无需手动注入依赖

向后兼容模式:
    from commands.steam import set_dependencies

    # 在 main.py 中手动注入依赖
    set_dependencies(cache_manager, rate_converter, smart_cache_manager)
"""

import logging

from utils.rate_converter import RateConverter

from .cache import set_cache_manager, set_rate_converter, set_smart_cache_manager
from .price_bot import SteamPriceBot

# 导出命令处理器（通过导入自动注册）
from .callbacks import steam_callback_handler
from .command import (
    steam_clean_cache_command,
    steam_command,
    steam_bundle_command,
    steam_search_command,
    steamb_callback_handler,
    handle_inline_steam_search,
)

logger = logging.getLogger(__name__)

# 导出依赖注入函数和类
__all__ = [
    # 命令处理器
    "steam_command",
    "steam_clean_cache_command",
    "steam_bundle_command",
    "steam_search_command",
    # 回调处理器
    "steam_callback_handler",
    "steamb_callback_handler",
    # Inline
    "handle_inline_steam_search",
    # 依赖注入
    "set_dependencies",
    "SteamPriceBot",
]


def init_steam_bot(
    application,
    cache_manager,
    rate_converter,
    smart_cache_manager=None,
    task_scheduler=None,
):
    """
    初始化 Steam 价格查询机器人并存储到 bot_data（自动发现模式）

    Args:
        application: Telegram Application 实例
        cache_manager: Redis 缓存管理器
        rate_converter: 汇率转换器
        rate_converter: 汇率转换器
        smart_cache_manager: 智能缓存管理器（可选）
        task_scheduler: 任务调度器（可选）
    """
    bot = SteamPriceBot(cache_manager, rate_converter, smart_cache_manager)
    application.bot_data["steam_price_bot"] = bot
    logger.info("✅ Steam 价格查询机器人初始化完成")


def set_dependencies(
    cache_manager,
    rate_converter: RateConverter,
    smart_cache_manager=None,
):
    """
    统一的依赖注入接口（向后兼容，已废弃）

    推荐使用 init_steam_bot() 函数进行自动发现初始化。

    Args:
        cache_manager: Redis 缓存管理器实例
        rate_converter: 汇率转换器实例
        smart_cache_manager: 智能缓存管理器实例 (可选, 用于 MySQL 持久化)
    """
    set_cache_manager(cache_manager)
    set_rate_converter(rate_converter)
    if smart_cache_manager:
        set_smart_cache_manager(smart_cache_manager)
    logger.warning("⚠️  使用了已废弃的 set_dependencies()，建议迁移到自动发现模式")
