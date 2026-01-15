"""
Redis 任务调度器
使用 Redis Sorted Set 实现定时任务调度
"""

import asyncio
import json
import logging
import time
from collections.abc import Callable

import redis.asyncio as redis


logger = logging.getLogger(__name__)


class RedisTaskScheduler:
    """Redis 任务调度器，替代文件系统版本"""

    def __init__(self, redis_client: redis.Redis):
        """初始化调度器"""
        self.redis = redis_client
        self._running = False
        self._task: asyncio.Task | None = None
        self._cache_manager = None
        self._handlers: dict[str, Callable] = {}

        # 注册默认处理器
        self._register_default_handlers()

    def set_cache_manager(self, cache_manager):
        """设置缓存管理器（用于缓存清理任务）"""
        self._cache_manager = cache_manager

    def set_rate_converter(self, rate_converter):
        """设置汇率转换器（用于汇率刷新任务）"""
        self._rate_converter = rate_converter

    def _register_default_handlers(self):
        """注册默认任务处理器"""
        self._handlers["cache_cleanup"] = self._handle_cache_cleanup
        self._handlers["weekly_cleanup"] = self._handle_cache_cleanup
        self._handlers["rate_refresh"] = self._handle_rate_refresh

    def start(self):
        """启动调度器"""
        self._running = True
        self._task = asyncio.create_task(self._scheduler_worker())
        # 自动启动汇率刷新任务
        asyncio.create_task(self._ensure_rate_refresh_task())
        logger.info("✅ Redis 任务调度器已启动")

    def stop(self):
        """停止调度器"""
        self._running = False
        if self._task:
            self._task.cancel()
        logger.info("Redis 任务调度器已停止")

    async def schedule_task(self, task_id: str, task_type: str, execute_at: float, data: dict | None = None):
        """
        调度任务

        Args:
            task_id: 任务ID
            task_type: 任务类型
            execute_at: 执行时间（时间戳）
            data: 任务数据
        """
        # 任务数据
        task_data = {"id": task_id, "type": task_type, "data": data or {}}

        # 存储任务详情
        await self.redis.hset("tasks:details", task_id, json.dumps(task_data))

        # 添加到调度队列
        await self.redis.zadd("tasks:scheduled", {task_id: execute_at})

        logger.debug(f"任务已调度: {task_id}, 执行时间: {execute_at}")

    async def add_weekly_cache_cleanup(
        self, task_id: str, cache_key: str, weekday: int = 6, hour: int = 5, minute: int = 0
    ):
        """
        添加每周缓存清理任务（兼容原接口）

        Args:
            task_id: 任务ID
            cache_key: 要清理的缓存键/子目录
            weekday: 星期几（0-6，0是周一）
            hour: 小时（UTC）
            minute: 分钟
        """
        # 计算下次执行时间
        import datetime

        now = datetime.datetime.utcnow()
        days_ahead = weekday - now.weekday()
        if days_ahead <= 0:
            days_ahead += 7

        next_run = now + datetime.timedelta(days=days_ahead)
        next_run = next_run.replace(hour=hour, minute=minute, second=0, microsecond=0)

        # 如果计算出的时间已过，推迟到下周
        if next_run <= now:
            next_run += datetime.timedelta(days=7)

        # 调度任务
        await self.schedule_task(
            task_id=f"weekly_cleanup_{cache_key}",
            task_type="weekly_cleanup",
            execute_at=next_run.timestamp(),
            data={"cache_key": cache_key, "weekday": weekday, "hour": hour, "minute": minute},
        )

        logger.info(f"已添加每周清理任务: {cache_key}, 下次执行: {next_run}")

    async def _scheduler_worker(self):
        """调度工作器"""
        logger.info("任务调度工作器已启动")

        while self._running:
            try:
                # 获取当前时间
                current_time = time.time()

                # 获取到期任务
                due_tasks = await self.redis.zrangebyscore("tasks:scheduled", 0, current_time, withscores=False)

                if due_tasks:
                    # 处理到期任务
                    for task_id in due_tasks:
                        await self._execute_task(task_id)

                        # 从调度队列移除
                        await self.redis.zrem("tasks:scheduled", task_id)

                # 每秒检查一次
                await asyncio.sleep(1)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"任务调度工作器错误: {e}")
                await asyncio.sleep(5)

        logger.info("任务调度工作器已停止")

    async def _execute_task(self, task_id: str):
        """执行任务"""
        try:
            # 获取任务详情
            task_json = await self.redis.hget("tasks:details", task_id)
            if not task_json:
                logger.warning(f"任务详情不存在: {task_id}")
                return

            task_data = json.loads(task_json)
            task_type = task_data.get("type")
            data = task_data.get("data", {})

            # 获取处理器
            handler = self._handlers.get(task_type)
            if handler:
                await handler(task_id, data)
                logger.info(f"任务已执行: {task_id}")
            else:
                logger.warning(f"未找到任务处理器: {task_type}")

            # 清理任务详情
            await self.redis.hdel("tasks:details", task_id)

            # 如果是周期性任务，重新调度
            if task_type == "weekly_cleanup":
                # 计算下次执行时间（7天后）
                next_run = time.time() + (7 * 24 * 60 * 60)
                await self.schedule_task(task_id, task_type, next_run, data)
            elif task_type == "antispam_cleanup":
                # AI反垃圾清理任务每周执行一次
                next_run = time.time() + (7 * 24 * 60 * 60)
                await self.schedule_task(task_id, task_type, next_run, data)
            elif task_type == "rate_refresh":
                # 汇率刷新任务每30分钟执行一次
                next_run = time.time() + (30 * 60)
                await self.schedule_task(task_id, task_type, next_run, data)

        except Exception as e:
            logger.error(f"执行任务失败 {task_id}: {e}")

    async def _handle_cache_cleanup(self, task_id: str, data: dict):
        """处理缓存清理任务"""
        cache_key = data.get("cache_key")
        if not cache_key or not self._cache_manager:
            logger.warning(f"无法执行缓存清理: cache_key={cache_key}")
            return

        try:
            # 清理指定子目录的缓存
            await self._cache_manager.clear_cache(subdirectory=cache_key)
            logger.info(f"缓存清理完成: {cache_key}")
        except Exception as e:
            logger.error(f"缓存清理失败 {cache_key}: {e}")

    async def _handle_rate_refresh(self, task_id: str, data: dict):
        """处理汇率刷新任务"""
        if not hasattr(self, "_rate_converter") or not self._rate_converter:
            logger.warning("汇率转换器未设置，跳过汇率刷新任务")
            return

        try:
            # 检查数据是否需要刷新（超过50分钟）
            current_time = time.time()
            if current_time - self._rate_converter.rates_timestamp > 3000:
                logger.info("Redis调度：汇率数据即将过期，开始更新")
                await self._rate_converter.get_rates(force_refresh=True)
                logger.info("Redis调度：汇率刷新完成")
            else:
                logger.debug("Redis调度：汇率数据仍然新鲜，跳过更新")
        except Exception as e:
            logger.error(f"汇率刷新失败: {e}")

    async def cancel_task(self, task_id: str):
        """取消任务"""
        # 从调度队列移除
        result = await self.redis.zrem("tasks:scheduled", task_id)

        # 删除任务详情
        await self.redis.hdel("tasks:details", task_id)

        if result:
            logger.debug(f"任务已取消: {task_id}")

    async def get_scheduled_tasks(self) -> dict[str, float]:
        """获取所有已调度任务"""
        tasks = await self.redis.zrange("tasks:scheduled", 0, -1, withscores=True)
        return dict(tasks)

    async def get_task_count(self) -> int:
        """获取调度任务数量"""
        return await self.redis.zcard("tasks:scheduled")

    async def clear_all_tasks(self):
        """清除所有任务"""
        # 获取所有任务ID
        task_ids = await self.redis.zrange("tasks:scheduled", 0, -1)

        # 删除任务详情
        if task_ids:
            await self.redis.hdel("tasks:details", *task_ids)

        # 清空调度队列
        await self.redis.delete("tasks:scheduled")

        logger.info("已清除所有调度任务")

    async def schedule_rate_refresh(self, delay_minutes: int = 30):
        """调度汇率刷新任务"""
        task_id = "rate_refresh_periodic"
        execute_at = time.time() + (delay_minutes * 60)

        await self.schedule_task(task_id=task_id, task_type="rate_refresh", execute_at=execute_at, data={})

        logger.info(f"已调度汇率刷新任务，将在 {delay_minutes} 分钟后执行")

    async def _ensure_rate_refresh_task(self):
        """确保汇率刷新任务存在，如果不存在则创建"""
        try:
            task_id = "rate_refresh_periodic"

            # 检查任务是否已存在
            existing_task = await self.redis.zscore("tasks:scheduled", task_id)

            if existing_task is None:
                # 任务不存在，创建新任务（5分钟后开始执行）
                await self.schedule_rate_refresh(delay_minutes=5)
                logger.info("✅ 自动创建汇率刷新任务")
            else:
                logger.info("汇率刷新任务已存在，跳过创建")

        except Exception as e:
            logger.error(f"检查汇率刷新任务失败: {e}")

    def register_handler(self, task_type: str, handler: Callable):
        """注册任务处理器"""
        self._handlers[task_type] = handler
        logger.info(f"已注册任务处理器: {task_type}")


# 全局实例（用于兼容性）
_redis_task_scheduler: RedisTaskScheduler | None = None


def init_task_scheduler(cache_manager, redis_client: redis.Redis) -> RedisTaskScheduler:
    """初始化任务调度器（兼容原接口）"""
    global _redis_task_scheduler
    if _redis_task_scheduler is None:
        _redis_task_scheduler = RedisTaskScheduler(redis_client)
        _redis_task_scheduler.set_cache_manager(cache_manager)
    return _redis_task_scheduler
