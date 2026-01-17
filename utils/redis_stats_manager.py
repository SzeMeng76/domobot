"""
Redis 统计管理器
用于命令使用统计和活跃用户追踪
"""

import json
import logging
import time
from datetime import datetime, timedelta

import redis.asyncio as redis


logger = logging.getLogger(__name__)


class RedisStatsManager:
    """Redis 统计管理器"""

    def __init__(self, redis_client: redis.Redis):
        """初始化统计管理器"""
        self.redis = redis_client

    async def record_command_usage(self, command: str, user_id: int, chat_id: int, chat_type: str):
        """
        记录命令使用情况

        Args:
            command: 命令名称
            user_id: 用户ID
            chat_id: 聊天ID
            chat_type: 聊天类型（private/group/supergroup）
        """
        try:
            # 获取当前日期
            today = datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

            # 1. 增加命令总计数
            await self.redis.hincrby("stats:commands:total", command, 1)

            # 2. 增加今日命令计数
            await self.redis.hincrby(f"stats:commands:daily:{today}", command, 1)
            # 设置过期时间（保留7天）
            await self.redis.expire(f"stats:commands:daily:{today}", 7 * 24 * 60 * 60)

            # 3. 记录用户活跃度
            await self.redis.zadd("stats:active_users", {str(user_id): time.time()})

            # 4. 记录每日活跃用户（使用 HyperLogLog）
            await self.redis.pfadd(f"stats:dau:{today}", user_id)
            await self.redis.expire(f"stats:dau:{today}", 30 * 24 * 60 * 60)  # 保留30天

            # 5. 记录聊天类型统计
            await self.redis.hincrby(f"stats:chat_type:{chat_type}", command, 1)

            # 6. 记录用户命令历史（最近10条）
            user_history_key = f"stats:user_history:{user_id}"
            history_entry = {"command": command, "chat_id": chat_id, "chat_type": chat_type, "timestamp": time.time()}

            # 使用列表存储，保持最近10条
            await self.redis.lpush(user_history_key, json.dumps(history_entry))
            await self.redis.ltrim(user_history_key, 0, 9)  # 只保留最近10条
            await self.redis.expire(user_history_key, 30 * 24 * 60 * 60)  # 30天过期

            logger.debug(f"命令使用已记录: {command} by {user_id}")

        except Exception as e:
            logger.error(f"记录命令使用失败: {e}")

    async def get_command_stats(self, period: str = "total") -> dict[str, int]:
        """
        获取命令统计

        Args:
            period: 统计周期（total/today/week）

        Returns:
            命令使用次数字典
        """
        try:
            if period == "total":
                # 获取总计数
                stats = await self.redis.hgetall("stats:commands:total")
                return {cmd: int(count) for cmd, count in stats.items()}

            elif period == "today":
                # 获取今日统计
                today = datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
                stats = await self.redis.hgetall(f"stats:commands:daily:{today}")
                return {cmd: int(count) for cmd, count in stats.items()}

            elif period == "week":
                # 获取最近7天统计
                week_stats = {}
                for i in range(7):
                    date = (datetime.now(datetime.timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")
                    daily_stats = await self.redis.hgetall(f"stats:commands:daily:{date}")

                    for cmd, count in daily_stats.items():
                        if cmd not in week_stats:
                            week_stats[cmd] = 0
                        week_stats[cmd] += int(count)

                return week_stats

            else:
                return {}

        except Exception as e:
            logger.error(f"获取命令统计失败: {e}")
            return {}

    async def get_active_users(self, hours: int = 24) -> list[int]:
        """
        获取活跃用户列表

        Args:
            hours: 时间范围（小时）

        Returns:
            活跃用户ID列表
        """
        try:
            # 计算时间阈值
            threshold = time.time() - (hours * 60 * 60)

            # 获取活跃用户
            users = await self.redis.zrangebyscore("stats:active_users", threshold, "+inf")

            return [int(user_id) for user_id in users]

        except Exception as e:
            logger.error(f"获取活跃用户失败: {e}")
            return []

    async def get_active_users_count(self, hours: int = 24) -> int:
        """获取活跃用户数量"""
        try:
            threshold = time.time() - (hours * 60 * 60)
            return await self.redis.zcount("stats:active_users", threshold, "+inf")
        except Exception as e:
            logger.error(f"获取活跃用户数量失败: {e}")
            return 0

    async def get_daily_active_users(self, date: str | None = None) -> int:
        """
        获取每日活跃用户数（DAU）

        Args:
            date: 日期字符串（YYYY-MM-DD），默认今天

        Returns:
            活跃用户数
        """
        try:
            if date is None:
                date = datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

            return await self.redis.pfcount(f"stats:dau:{date}")

        except Exception as e:
            logger.error(f"获取DAU失败: {e}")
            return 0

    async def get_top_commands(self, limit: int = 10, period: str = "total") -> list[tuple]:
        """
        获取热门命令

        Args:
            limit: 返回数量限制
            period: 统计周期

        Returns:
            [(命令, 使用次数), ...]
        """
        stats = await self.get_command_stats(period)
        sorted_commands = sorted(stats.items(), key=lambda x: x[1], reverse=True)
        return sorted_commands[:limit]

    async def get_user_command_history(self, user_id: int) -> list[dict]:
        """
        获取用户命令历史

        Args:
            user_id: 用户ID

        Returns:
            命令历史列表
        """
        try:
            history_key = f"stats:user_history:{user_id}"
            history_json = await self.redis.lrange(history_key, 0, -1)

            history = []
            for item in history_json:
                try:
                    history.append(json.loads(item))
                except json.JSONDecodeError:
                    continue

            return history

        except Exception as e:
            logger.error(f"获取用户命令历史失败: {e}")
            return []

    async def get_chat_type_stats(self) -> dict[str, dict[str, int]]:
        """
        获取聊天类型统计

        Returns:
            {chat_type: {command: count}}
        """
        try:
            stats = {}
            for chat_type in ["private", "group", "supergroup"]:
                type_stats = await self.redis.hgetall(f"stats:chat_type:{chat_type}")
                stats[chat_type] = {cmd: int(count) for cmd, count in type_stats.items()}

            return stats

        except Exception as e:
            logger.error(f"获取聊天类型统计失败: {e}")
            return {}

    async def cleanup_old_stats(self, days: int = 30):
        """清理旧的统计数据"""
        try:
            # 清理过期的每日统计
            for i in range(days, days + 30):  # 清理30-60天前的数据
                date = (datetime.utcnow() - timedelta(days=i)).strftime("%Y-%m-%d")
                await self.redis.delete(f"stats:commands:daily:{date}")
                await self.redis.delete(f"stats:dau:{date}")

            # 清理不活跃用户（超过30天）
            threshold = time.time() - (30 * 24 * 60 * 60)
            await self.redis.zremrangebyscore("stats:active_users", 0, threshold)

            logger.info("旧统计数据清理完成")

        except Exception as e:
            logger.error(f"清理旧统计数据失败: {e}")

    async def reset_all_stats(self):
        """重置所有统计数据（谨慎使用）"""
        try:
            # 获取所有统计键
            cursor = 0
            while True:
                cursor, keys = await self.redis.scan(cursor, match="stats:*", count=100)
                if keys:
                    await self.redis.delete(*keys)
                if cursor == 0:
                    break

            logger.info("所有统计数据已重置")

        except Exception as e:
            logger.error(f"重置统计数据失败: {e}")

