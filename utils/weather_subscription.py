"""
天气订阅管理器
支持每日定时推送天气简报和降雨提醒
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class WeatherSubscriptionManager:
    """天气订阅管理器"""

    def __init__(self, cache_manager):
        self.cache_manager = cache_manager
        self.cache_key_prefix = "weather_subscription"

    async def subscribe(self, chat_id: int, location: str, sub_type: str = "daily") -> bool:
        """
        订阅天气推送

        Args:
            chat_id: 聊天ID
            location: 城市名称
            sub_type: 订阅类型 (daily: 每日简报, rain: 降雨提醒)

        Returns:
            是否订阅成功
        """
        try:
            # 获取该聊天的订阅列表
            cache_key = f"{self.cache_key_prefix}:{sub_type}:{chat_id}"
            subscriptions = await self.cache_manager.get(cache_key, subdirectory="weather") or []

            # 检查是否已订阅
            if location in subscriptions:
                return False

            # 添加订阅
            subscriptions.append(location)
            await self.cache_manager.set(
                cache_key,
                subscriptions,
                subdirectory="weather",
                ttl=None  # 永久保存
            )

            logger.info(f"Chat {chat_id} 订阅了 {location} 的 {sub_type} 推送")
            return True

        except Exception as e:
            logger.error(f"订阅失败: {e}")
            return False

    async def unsubscribe(self, chat_id: int, location: str, sub_type: str = "daily") -> bool:
        """
        取消订阅

        Args:
            chat_id: 聊天ID
            location: 城市名称
            sub_type: 订阅类型

        Returns:
            是否取消成功
        """
        try:
            cache_key = f"{self.cache_key_prefix}:{sub_type}:{chat_id}"
            subscriptions = await self.cache_manager.get(cache_key, subdirectory="weather") or []

            if location not in subscriptions:
                return False

            subscriptions.remove(location)
            await self.cache_manager.set(
                cache_key,
                subscriptions,
                subdirectory="weather",
                ttl=None
            )

            logger.info(f"Chat {chat_id} 取消订阅了 {location} 的 {sub_type} 推送")
            return True

        except Exception as e:
            logger.error(f"取消订阅失败: {e}")
            return False

    async def get_subscriptions(self, chat_id: int, sub_type: str = "daily") -> List[str]:
        """
        获取订阅列表

        Args:
            chat_id: 聊天ID
            sub_type: 订阅类型

        Returns:
            订阅的城市列表
        """
        try:
            cache_key = f"{self.cache_key_prefix}:{sub_type}:{chat_id}"
            subscriptions = await self.cache_manager.get(cache_key, subdirectory="weather") or []
            return subscriptions
        except Exception as e:
            logger.error(f"获取订阅列表失败: {e}")
            return []

    async def get_all_subscriptions(self, sub_type: str = "daily") -> Dict[int, List[str]]:
        """
        获取所有订阅（用于定时推送）

        Args:
            sub_type: 订阅类型

        Returns:
            {chat_id: [locations]} 字典
        """
        try:
            # 这里需要遍历所有缓存键，实际实现可能需要根据你的缓存系统调整
            # 简化版本：返回空字典，实际使用时需要实现完整的遍历逻辑
            logger.warning("get_all_subscriptions 需要根据实际缓存系统实现")
            return {}
        except Exception as e:
            logger.error(f"获取所有订阅失败: {e}")
            return {}
