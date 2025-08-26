"""
Redis 缓存管理器
保持与现有 CacheManager 相同的接口，底层改用 Redis
"""

import json
import logging
import time

import redis.asyncio as redis
from redis.asyncio.connection import ConnectionPool
from redis.exceptions import RedisError

from utils.config_manager import get_config


logger = logging.getLogger(__name__)


class RedisCacheManager:
    """Redis 缓存管理器，保持与文件缓存相同的接口"""

    def __init__(self, host: str = "localhost", port: int = 6379, db: int = 0, password: str | None = None):
        """初始化 Redis 缓存管理器"""
        self.config = get_config()

        # 创建连接池
        pool_kwargs = {
            "host": host,
            "port": port,
            "db": db,
            "decode_responses": True,
            "max_connections": self.config.redis_max_connections,
            "socket_keepalive": True,
            "socket_keepalive_options": {},
            "health_check_interval": self.config.redis_health_check_interval,
        }

        if password:
            pool_kwargs["password"] = password

        self.pool = ConnectionPool(**pool_kwargs)
        self.redis_client = redis.Redis(connection_pool=self.pool)
        self._connected = False

    async def connect(self):
        """建立 Redis 连接"""
        try:
            await self.redis_client.ping()
            self._connected = True
            logger.info("✅ Redis 连接成功")
        except RedisError as e:
            logger.error(f"❌ Redis 连接失败: {e}")
            raise

    async def close(self):
        """关闭 Redis 连接"""
        if self.redis_client:
            await self.redis_client.close()
            await self.pool.disconnect()
            self._connected = False
            logger.info("Redis 连接已关闭")

    def _get_cache_key(self, key: str, subdirectory: str | None = None) -> str:
        """生成缓存键名，保持与文件系统相同的命名规则"""
        if subdirectory:
            return f"cache:{subdirectory}:{key}"
        return f"cache:{key}"

    def _get_ttl_for_subdirectory(self, subdirectory: str | None, key: str | None = None) -> int:
        """根据子目录获取对应的 TTL"""
        ttl_mapping = {
            "exchange_rates": self.config.rate_cache_duration,
            "app_store": self.config.app_store_cache_duration,
            "apple_services": self.config.apple_services_cache_duration,
            "google_play": self.config.google_play_app_cache_duration,
            "steam": self.config.steam_cache_duration,
            "netflix": self.config.netflix_cache_duration,
            "crypto": self.config.crypto_cache_duration,
            "spotify": self.config.spotify_cache_duration,  # 8天，配合周日清理
            "disney_plus": self.config.disney_cache_duration,  # 8天，配合周日清理
            "max": self.config.max_cache_duration,  # 8天，配合周日清理
            "movie": self.config.movie_cache_duration,  # 2小时，电影和电视剧缓存
            "news": self.config.news_cache_duration,  # 5分钟，新闻缓存
            "whois": self.config.whois_cache_duration,  # 6小时，WHOIS查询缓存
            "time": self.config.time_cache_duration,  # 24小时，时区缓存
            "cooking": self.config.cooking_cache_duration,  # 7天，烹饪菜谱缓存
            "memes": self.config.memes_cache_duration,  # 10分钟，表情包缓存
            "finance": self.config.finance_cache_duration,  # 5分钟，金融数据缓存
            "map": self.config.map_cache_duration,  # 30分钟，地图服务缓存
            "flights": self.config.flight_cache_duration,  # 1小时，航班服务缓存
            "hotels": self.config.hotel_cache_duration,  # 1小时，酒店服务缓存
        }

        # 对于搜索结果特殊处理
        if subdirectory == "google_play" and key and "search_" in key:
            return self.config.google_play_search_cache_duration
        if subdirectory == "app_store" and key and "search_" in key:
            return self.config.app_store_search_cache_duration
        if subdirectory == "finance" and key:
            if "search_" in key:
                return self.config.finance_search_cache_duration
            elif "trending_" in key:
                return self.config.finance_ranking_cache_duration
        
        # crypto子目录的特殊处理 - 区分CMC和CoinGecko
        if subdirectory == "crypto" and key:
            if "coingecko_markets_" in key:
                return self.config.coingecko_markets_cache_duration
            elif "coingecko_trending" in key:
                return self.config.coingecko_trending_cache_duration  
            elif "coingecko_single_" in key:
                return self.config.coingecko_single_cache_duration
            # 默认使用crypto_cache_duration (CMC API)
        
        if subdirectory == "map" and key:
            if "geocode_" in key or "reverse_" in key:
                return self.config.map_geocode_cache_duration
            elif "directions_" in key:
                return self.config.map_directions_cache_duration
            # 默认使用map_cache_duration (搜索和附近服务)
        
        if subdirectory == "flights" and key:
            if "flight_booking_" in key:
                return self.config.flight_booking_cache_duration
            elif "flight_prices_" in key:
                return self.config.flight_price_cache_duration
            # 默认使用flight_cache_duration (航班搜索)
        
        if subdirectory == "hotels" and key:
            if "hotel_details_" in key:
                return self.config.hotel_details_cache_duration
            # 默认使用hotel_cache_duration (酒店搜索)

        return ttl_mapping.get(subdirectory, self.config.default_cache_duration)

    async def load_cache(
        self, key: str, max_age_seconds: int | None = None, subdirectory: str | None = None
    ) -> dict | None:
        """
        加载缓存数据，保持与 CacheManager 相同的接口

        Args:
            key: 缓存键
            max_age_seconds: 最大缓存时间（秒），如果指定则检查应用级过期时间
            subdirectory: 子目录

        Returns:
            缓存的数据或 None
        """
        if not self._connected:
            logger.warning("Redis 未连接，返回 None")
            return None

        cache_key = self._get_cache_key(key, subdirectory)

        try:
            # 获取数据
            data = await self.redis_client.get(cache_key)
            if data is None:
                return None

            # 解析 JSON
            cache_data = json.loads(data)

            # 检查应用级过期时间（如果指定了 max_age_seconds）
            if max_age_seconds is not None and isinstance(cache_data, dict) and "timestamp" in cache_data:
                cache_timestamp = cache_data["timestamp"]
                current_time = time.time()
                cache_age = current_time - cache_timestamp

                if cache_age > max_age_seconds:
                    logger.debug(f"缓存已过期 {cache_key}，缓存年龄: {cache_age:.1f}s > {max_age_seconds}s")
                    # 删除过期的缓存
                    await self.redis_client.delete(cache_key)
                    return None

            # 为了兼容性，保持返回数据格式
            # 原 CacheManager 返回的是 data 字段的内容
            if isinstance(cache_data, dict) and "data" in cache_data:
                return cache_data["data"]
            return cache_data

        except (json.JSONDecodeError, RedisError) as e:
            logger.error(f"加载缓存失败 {cache_key}: {e}")
            return None

    async def save_cache(self, key: str, data: dict, subdirectory: str | None = None):
        """
        保存数据到缓存，保持与 CacheManager 相同的接口

        Args:
            key: 缓存键
            data: 要缓存的数据
            subdirectory: 子目录
        """
        if not self._connected:
            logger.warning("Redis 未连接，无法保存缓存")
            return

        cache_key = self._get_cache_key(key, subdirectory)
        ttl = self._get_ttl_for_subdirectory(subdirectory, key)

        try:
            # 为了兼容性，保持数据格式
            cache_data = {"timestamp": time.time(), "data": data}

            # 保存到 Redis，设置过期时间
            await self.redis_client.setex(cache_key, ttl, json.dumps(cache_data, ensure_ascii=False))

            logger.debug(f"缓存已保存 {cache_key}，TTL: {ttl}秒")

        except (RedisError, json.JSONEncodeError) as e:
            logger.error(f"保存缓存失败 {cache_key}: {e}")

    async def clear_cache(self, key: str | None = None, key_prefix: str | None = None, subdirectory: str | None = None):
        """
        清除缓存，保持与 CacheManager 相同的接口

        Args:
            key: 特定的缓存键
            key_prefix: 键前缀
            subdirectory: 子目录
        """
        if not self._connected:
            logger.warning("Redis 未连接，无法清除缓存")
            return

        try:
            # 场景1：清除整个子目录
            if subdirectory and not key and not key_prefix:
                pattern = f"cache:{subdirectory}:*"
                await self._delete_by_pattern(pattern)
                logger.info(f"已清除子目录缓存: {subdirectory}")

            # 场景2：清除特定键
            elif key:
                cache_key = self._get_cache_key(key, subdirectory)
                result = await self.redis_client.delete(cache_key)
                if result:
                    logger.info(f"已清除缓存: {cache_key}")
                else:
                    logger.info(f"缓存不存在: {cache_key}")

            # 场景3：按前缀清除
            elif key_prefix:
                pattern = f"cache:{subdirectory}:{key_prefix}*" if subdirectory else f"cache:{key_prefix}*"
                await self._delete_by_pattern(pattern)
                logger.info(f"已清除前缀缓存: {pattern}")

            # 场景4：清除所有缓存（根目录）
            elif not subdirectory:
                pattern = "cache:*"
                await self._delete_by_pattern(pattern)
                logger.info("已清除所有缓存")

        except RedisError as e:
            logger.error(f"清除缓存失败: {e}")

    async def _delete_by_pattern(self, pattern: str):
        """通过模式删除键"""
        cursor = 0
        deleted_count = 0
        while True:
            cursor, keys = await self.redis_client.scan(cursor, match=pattern, count=100)
            if keys:
                deleted_count += len(keys)
                await self.redis_client.delete(*keys)
                logger.debug(f"删除了 {len(keys)} 个缓存键，匹配模式: {pattern}")
            if cursor == 0:
                break

        logger.info(f"总共删除了 {deleted_count} 个缓存键，匹配模式: {pattern}")

    async def get_cache_timestamp(self, key: str, subdirectory: str | None = None) -> float | None:
        """获取缓存的时间戳，保持兼容性"""
        if not self._connected:
            return None

        cache_key = self._get_cache_key(key, subdirectory)

        try:
            data = await self.redis_client.get(cache_key)
            if data:
                cache_data = json.loads(data)
                return cache_data.get("timestamp")
            return None
        except (json.JSONDecodeError, RedisError) as e:
            logger.error(f"获取时间戳失败 {cache_key}: {e}")
            return None

    async def clear_all_cache(self):
        """清除所有缓存"""
        await self.clear_cache()

    # 兼容性别名方法
    async def get(self, key: str, max_age_seconds: int | None = None, subdirectory: str | None = None) -> dict | None:
        """获取缓存数据（别名方法）"""
        return await self.load_cache(key, max_age_seconds, subdirectory)

    async def set(self, key: str, data: dict, ttl: int | None = None, subdirectory: str | None = None):
        """设置缓存数据（别名方法）"""
        await self.save_cache(key, data, subdirectory)

    # 同步包装方法（用于向后兼容）
    def load_cache_sync(
        self, key: str, max_age_seconds: int | None = None, subdirectory: str | None = None
    ) -> dict | None:
        """同步版本的 load_cache（仅用于兼容）"""
        import asyncio

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        return loop.run_until_complete(self.load_cache(key, max_age_seconds, subdirectory))

    def save_cache_sync(self, key: str, data: dict, subdirectory: str | None = None):
        """同步版本的 save_cache（仅用于兼容）"""
        import asyncio

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        loop.run_until_complete(self.save_cache(key, data, subdirectory))
