"""
智能缓存管理器 - 方案C实现
Redis热缓存(6h) + MySQL持久化(24h)

查询流程：
1. Redis查询 (TTL: 6小时) → 有则返回
2. MySQL查询 (新鲜度: 24小时) → 有且新鲜则使用，回写Redis
3. 爬取新数据 → 保存到MySQL → 缓存到Redis
"""

import asyncio
import logging
from typing import Callable, Dict, Optional

from utils.constants import TIME_ONE_DAY, TIME_SIX_HOURS
from utils.price_history_manager import PriceHistoryManager
from utils.redis_cache_manager import RedisCacheManager

logger = logging.getLogger(__name__)


class SmartCacheManager:
    """
    智能缓存管理器 - 方案C实现
    Redis热缓存(6h) + MySQL持久化(24h)
    """

    def __init__(
        self,
        redis_cache_manager: RedisCacheManager,
        price_history_manager: PriceHistoryManager,
    ):
        """
        初始化智能缓存管理器

        Args:
            redis_cache_manager: Redis缓存管理器实例
            price_history_manager: 价格历史管理器实例
        """
        self.redis = redis_cache_manager
        self.db = price_history_manager
        self.background_tasks: set = set()  # 追踪后台任务（防止内存泄漏）
        logger.info("✅ SmartCacheManager 已初始化")

    async def get_or_fetch(
        self,
        service: str,
        item_id: str,
        country_code: str,
        fetcher: Callable,
        redis_ttl: int = TIME_SIX_HOURS,  # Redis缓存6小时
        db_freshness: int = TIME_ONE_DAY,  # 数据库新鲜度24小时
        cache_key: Optional[str] = None,
        item_name: Optional[str] = None,
        async_save: bool = True,  # 异步保存到MySQL（性能优化）
        **fetcher_kwargs,
    ) -> Dict:
        """
        智能缓存查询 - 方案C核心逻辑

        查询流程：
        1. Redis查询 (TTL: redis_ttl) → 有则返回
        2. MySQL查询 (新鲜度: db_freshness) → 有且新鲜则使用，回写Redis
        3. 爬取新数据 → 保存到MySQL → 缓存到Redis

        Args:
            service: 服务名称 (steam/app_store/google_play等)
            item_id: 商品ID
            country_code: 国家代码
            fetcher: 数据获取函数（爬虫函数）
            redis_ttl: Redis缓存时长（秒），默认6小时
            db_freshness: 数据库数据有效期（秒），默认24小时
            cache_key: 自定义Redis缓存键（可选）
            item_name: 商品名称（可选，用于MySQL记录）
            async_save: 是否异步保存到MySQL，默认True（性能优化）
            **fetcher_kwargs: 传给fetcher的其他参数

        Returns:
            价格数据字典
        """
        # ===== 第1层：Redis热缓存查询 =====
        if cache_key:
            try:
                cached = await self.redis.load_cache(
                    cache_key, max_age_seconds=redis_ttl, subdirectory=service
                )
                if cached:
                    logger.debug(
                        f"✅ Redis缓存命中: {service}/{item_id}/{country_code}"
                    )
                    return cached
            except Exception as e:
                logger.warning(f"Redis查询失败，继续查询MySQL: {e}")

        # ===== 第2层：MySQL持久化查询 =====
        try:
            db_data = await self.db.get_latest_price(
                service, item_id, country_code, db_freshness
            )

            if db_data:
                age_hours = db_data.get("age_hours", 0)
                logger.info(
                    f"✅ MySQL数据命中: {service}/{item_id}/{country_code}, 年龄={age_hours}小时"
                )

                # 回写Redis（使数据重新热起来）
                if cache_key:
                    try:
                        await self.redis.save_cache(
                            cache_key, db_data, subdirectory=service
                        )
                        logger.debug(f"MySQL数据已回写Redis: {cache_key}")
                    except Exception as e:
                        logger.warning(f"回写Redis失败: {e}")

                return db_data

        except Exception as e:
            logger.warning(f"MySQL查询失败，将爬取新数据: {e}")

        # ===== 第3层：爬取新数据 =====
        logger.info(f"🔄 缓存未命中，开始爬取: {service}/{item_id}/{country_code}")

        try:
            # 调用爬虫函数获取数据
            fresh_data = await fetcher(**fetcher_kwargs)

            if not fresh_data:
                logger.error(f"爬取数据失败: {service}/{item_id}/{country_code}")
                return {}

            # 提取item_name（如果未提供）
            if not item_name:
                item_name = (
                    fresh_data.get("name") or fresh_data.get("item_name") or item_id
                )

            # ===== 保存到MySQL =====
            if async_save:
                # 异步保存，不阻塞响应（性能优化2）
                task = asyncio.create_task(
                    self._save_to_db_async(
                        service, item_id, item_name, country_code, fresh_data
                    )
                )
                # 追踪后台任务（防止内存泄漏）
                self.background_tasks.add(task)
                task.add_done_callback(self.background_tasks.discard)
            else:
                # 同步保存
                await self.db.save_price(
                    service, item_id, item_name, country_code, fresh_data
                )
                logger.debug(f"MySQL同步保存完成: {service}/{item_id}/{country_code}")

            # ===== 缓存到Redis =====
            if cache_key:
                try:
                    await self.redis.save_cache(
                        cache_key, fresh_data, subdirectory=service
                    )
                    logger.debug(f"Redis缓存已保存: {cache_key}")
                except Exception as e:
                    logger.warning(f"保存Redis缓存失败: {e}")

            return fresh_data

        except Exception as e:
            logger.error(f"爬取数据失败: {service}/{item_id}/{country_code}, 错误: {e}")
            return {}

    async def _save_to_db_async(
        self,
        service: str,
        item_id: str,
        item_name: str,
        country_code: str,
        price_data: Dict,
    ):
        """
        异步保存到MySQL（后台任务）

        Args:
            service: 服务名称
            item_id: 商品ID
            item_name: 商品名称
            country_code: 国家代码
            price_data: 价格数据
        """
        try:
            await self.db.save_price(
                service, item_id, item_name, country_code, price_data
            )
            logger.debug(f"MySQL异步保存完成: {service}/{item_id}/{country_code}")
        except Exception as e:
            logger.error(
                f"MySQL异步保存失败: {service}/{item_id}/{country_code}, 错误: {e}"
            )

    async def get_or_fetch_batch(
        self,
        service: str,
        item_id: str,
        country_codes: list[str],
        fetcher: Callable,
        redis_ttl: int = TIME_SIX_HOURS,
        db_freshness: int = TIME_ONE_DAY,
        cache_key_template: Optional[str] = None,
        item_name: Optional[str] = None,
        **fetcher_kwargs,
    ) -> Dict[str, Dict]:
        """
        批量查询多个国家的价格（性能优化）

        Args:
            service: 服务名称
            item_id: 商品ID
            country_codes: 国家代码列表
            fetcher: 数据获取函数
            redis_ttl: Redis缓存时长
            db_freshness: 数据库新鲜度
            cache_key_template: 缓存键模板，使用{country_code}占位符
            item_name: 商品名称
            **fetcher_kwargs: 传给fetcher的参数

        Returns:
            {country_code: price_data} 字典
        """
        results = {}
        tasks = []

        for cc in country_codes:
            # 生成缓存键
            cache_key = (
                cache_key_template.format(country_code=cc)
                if cache_key_template
                else None
            )

            # 更新fetcher参数中的country_code
            kwargs = fetcher_kwargs.copy()
            kwargs["country_code"] = cc

            # 创建任务
            task = self.get_or_fetch(
                service=service,
                item_id=item_id,
                country_code=cc,
                fetcher=fetcher,
                redis_ttl=redis_ttl,
                db_freshness=db_freshness,
                cache_key=cache_key,
                item_name=item_name,
                async_save=True,  # 批量查询使用异步保存
                **kwargs,
            )
            tasks.append((cc, task))

        # 并发执行所有查询
        for cc, task in tasks:
            try:
                result = await task
                results[cc] = result
            except Exception as e:
                logger.error(f"批量查询失败: {service}/{item_id}/{cc}, 错误: {e}")
                results[cc] = {}

        logger.info(
            f"批量查询完成: {service}/{item_id}, 成功 {len(results)}/{len(country_codes)} 个国家"
        )
        return results

    async def save_prices_batch(self, prices_list: list[Dict]) -> int:
        """
        批量保存价格到MySQL（性能优化1）

        Args:
            prices_list: 价格记录列表，格式参考 PriceHistoryManager.save_prices_batch()

        Returns:
            成功保存的记录数
        """
        try:
            count = await self.db.save_prices_batch(prices_list)
            logger.info(f"✅ 批量保存完成: {count} 条记录")
            return count
        except Exception as e:
            logger.error(f"批量保存失败: {e}")
            return 0

    async def clear_redis_cache(
        self, service: Optional[str] = None, key: Optional[str] = None
    ):
        """
        清除Redis缓存

        Args:
            service: 服务名称（子目录），None则清除所有
            key: 特定缓存键，None则清除整个服务
        """
        try:
            await self.redis.clear_cache(key=key, subdirectory=service)
            logger.info(f"Redis缓存已清除: service={service}, key={key}")
        except Exception as e:
            logger.error(f"清除Redis缓存失败: {e}")

    async def cleanup_old_data(self, days_to_keep: int = 90) -> int:
        """
        清理MySQL旧数据（性能优化4）

        Args:
            days_to_keep: 保留天数，默认90天

        Returns:
            删除的记录数
        """
        try:
            count = await self.db.cleanup_old_data(days_to_keep)
            logger.info(f"✅ MySQL旧数据清理完成: 删除 {count} 条记录")
            return count
        except Exception as e:
            logger.error(f"清理MySQL旧数据失败: {e}")
            return 0

    async def get_statistics(self, service: Optional[str] = None) -> Dict:
        """
        获取价格历史统计信息

        Args:
            service: 服务名称（可选）

        Returns:
            统计信息字典
        """
        try:
            stats = await self.db.get_statistics(service)
            return stats
        except Exception as e:
            logger.error(f"获取统计信息失败: {e}")
            return {}

    async def get_price_history(
        self,
        service: str,
        item_id: str,
        country_code: Optional[str] = None,
        days: int = 30,
    ) -> list[Dict]:
        """
        获取价格历史记录（供Web前端使用）

        Args:
            service: 服务名称
            item_id: 商品ID
            country_code: 国家代码（可选）
            days: 查询天数

        Returns:
            价格历史记录列表
        """
        try:
            history = await self.db.get_price_history(
                service, item_id, country_code, days
            )
            return history
        except Exception as e:
            logger.error(f"获取价格历史失败: {e}")
            return []

    async def wait_for_background_tasks(self, timeout: float = 10.0):
        """
        等待所有后台任务完成（优雅关闭时使用）

        Args:
            timeout: 超时时间（秒），默认10秒

        Returns:
            完成的任务数
        """
        if not self.background_tasks:
            logger.info("没有后台任务需要等待")
            return 0

        task_count = len(self.background_tasks)
        logger.info(f"等待 {task_count} 个后台任务完成...")

        try:
            await asyncio.wait_for(
                asyncio.gather(*self.background_tasks, return_exceptions=True),
                timeout=timeout,
            )
            logger.info(f"✅ {task_count} 个后台任务已完成")
            return task_count
        except asyncio.TimeoutError:
            remaining = len(self.background_tasks)
            logger.warning(
                f"⏱ 后台任务等待超时，剩余 {remaining}/{task_count} 个任务未完成"
            )
            return task_count - remaining
        except Exception as e:
            logger.error(f"等待后台任务时发生错误: {e}")
            return 0
