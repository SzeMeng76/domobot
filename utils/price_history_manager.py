"""
价格历史管理器
管理 price_history 表的增删改查操作
支持分层缓存策略（方案C）
"""

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from aiomysql import DictCursor, create_pool

logger = logging.getLogger(__name__)


class PriceHistoryManager:
    """价格历史管理器 - MySQL持久化层"""

    def __init__(self, host: str, port: int, database: str, user: str, password: str):
        """初始化 MySQL 连接参数"""
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.pool = None
        self._connected = False

    async def connect(self):
        """创建连接池"""
        try:
            # 获取连接池配置
            from utils.config_manager import get_config

            config = get_config()

            self.pool = await create_pool(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                db=self.database,
                charset="utf8mb4",
                autocommit=True,
                minsize=config.db_min_connections,
                maxsize=config.db_max_connections,
                echo=False,
                cursorclass=DictCursor,
            )
            self._connected = True
            logger.info("✅ PriceHistoryManager 连接池创建成功")

        except Exception as e:
            logger.error(f"❌ PriceHistoryManager 连接失败: {e}")
            raise

    async def close(self):
        """关闭连接池"""
        if self.pool:
            self.pool.close()
            await self.pool.wait_closed()
            self._connected = False
            logger.info("PriceHistoryManager 连接池已关闭")

    @asynccontextmanager
    async def get_cursor(self):
        """获取数据库游标的上下文管理器"""
        async with self.pool.acquire() as conn, conn.cursor(DictCursor) as cursor:
            yield cursor

    async def get_latest_price(
        self,
        service: str,
        item_id: str,
        country_code: str,
        freshness_threshold: int = 86400,
    ) -> Optional[Dict]:
        """
        获取最新价格记录（带新鲜度检查）

        Args:
            service: 服务名称（steam/app_store/google_play等）
            item_id: 商品ID
            country_code: 国家代码
            freshness_threshold: 新鲜度阈值（秒），默认24小时

        Returns:
            如果数据新鲜（<threshold）: 返回价格数据字典
            如果数据过期（>threshold）: 返回 None
        """
        if not self._connected:
            logger.warning("PriceHistoryManager 未连接")
            return None

        try:
            async with self.get_cursor() as cursor:
                # 查询最新记录
                await cursor.execute(
                    """
                    SELECT
                        id,
                        service,
                        item_id,
                        item_name,
                        country_code,
                        currency,
                        original_price,
                        current_price,
                        discount_percent,
                        price_cny,
                        extra_data,
                        recorded_at,
                        TIMESTAMPDIFF(SECOND, recorded_at, NOW()) as age_seconds
                    FROM price_history
                    WHERE service = %s AND item_id = %s AND country_code = %s
                    ORDER BY recorded_at DESC
                    LIMIT 1
                    """,
                    (service, item_id, country_code),
                )

                result = await cursor.fetchone()

                if not result:
                    logger.debug(f"MySQL未找到记录: {service}/{item_id}/{country_code}")
                    return None

                # 检查新鲜度
                age_seconds = result["age_seconds"]
                if age_seconds > freshness_threshold:
                    logger.debug(
                        f"MySQL数据过期: {service}/{item_id}/{country_code}, "
                        f"年龄={age_seconds}s, 阈值={freshness_threshold}s"
                    )
                    return None

                # 数据新鲜，返回
                logger.info(
                    f"✅ MySQL数据命中: {service}/{item_id}/{country_code}, 年龄={age_seconds}s"
                )

                # 构造返回数据
                price_data = {
                    "item_id": result["item_id"],
                    "item_name": result["item_name"],
                    "country_code": result["country_code"],
                    "currency": result["currency"],
                    "original_price": (
                        float(result["original_price"])
                        if result["original_price"]
                        else None
                    ),
                    "current_price": (
                        float(result["current_price"])
                        if result["current_price"]
                        else None
                    ),
                    "discount_percent": result["discount_percent"],
                    "price_cny": (
                        float(result["price_cny"]) if result["price_cny"] else None
                    ),
                    "recorded_at": (
                        result["recorded_at"].isoformat()
                        if result["recorded_at"]
                        else None
                    ),
                    "age_seconds": age_seconds,
                    "age_hours": round(age_seconds / 3600, 2),
                }

                # 合并 extra_data（如果有）
                if result["extra_data"]:
                    try:
                        extra_data = (
                            json.loads(result["extra_data"])
                            if isinstance(result["extra_data"], str)
                            else result["extra_data"]
                        )
                        price_data.update(extra_data)
                    except Exception as e:
                        logger.warning(f"解析extra_data失败: {e}")

                return price_data

        except Exception as e:
            logger.error(f"查询最新价格失败: {e}")
            return None

    async def save_price(
        self,
        service: str,
        item_id: str,
        item_name: str,
        country_code: str,
        price_data: Dict,
    ) -> bool:
        """
        保存单条价格记录

        Args:
            service: 服务名称
            item_id: 商品ID
            item_name: 商品名称
            country_code: 国家代码
            price_data: 价格数据字典，包含：
                - currency: 货币代码
                - original_price: 原价
                - current_price: 当前价格
                - discount_percent: 折扣百分比
                - price_cny: CNY等值价格
                - extra_data: 额外数据（可选）

        Returns:
            True: 保存成功
            False: 保存失败
        """
        if not self._connected:
            logger.warning("PriceHistoryManager 未连接")
            return False

        try:
            # 提取必需字段
            currency = price_data.get("currency")
            original_price = price_data.get("original_price")
            current_price = price_data.get("current_price")
            discount_percent = price_data.get("discount_percent", 0)
            price_cny = price_data.get("price_cny")

            # 提取额外数据（排除已使用的标准字段）
            standard_fields = {
                "currency",
                "original_price",
                "current_price",
                "discount_percent",
                "price_cny",
                "item_id",
                "item_name",
                "country_code",
                "recorded_at",
                "age_seconds",
                "age_hours",
            }
            extra_data = {
                k: v for k, v in price_data.items() if k not in standard_fields
            }
            extra_data_json = (
                json.dumps(extra_data, ensure_ascii=False) if extra_data else None
            )

            async with self.get_cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT IGNORE INTO price_history (
                        service, item_id, item_name, country_code,
                        currency, original_price, current_price,
                        discount_percent, price_cny, extra_data
                    ) VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s
                    )
                    """,
                    (
                        service,
                        item_id,
                        item_name,
                        country_code,
                        currency,
                        original_price,
                        current_price,
                        discount_percent,
                        price_cny,
                        extra_data_json,
                    ),
                )

            logger.debug(f"价格记录已保存: {service}/{item_id}/{country_code}")
            return True

        except Exception as e:
            logger.error(f"保存价格记录失败: {e}")
            return False

    async def save_prices_batch(self, prices_list: List[Dict]) -> int:
        """
        批量保存价格记录（性能优化）

        Args:
            prices_list: 价格记录列表，每条记录包含：
                - service: 服务名称
                - item_id: 商品ID
                - item_name: 商品名称
                - country_code: 国家代码
                - price_data: 价格数据字典

        Returns:
            成功保存的记录数
        """
        if not self._connected:
            logger.warning("PriceHistoryManager 未连接")
            return 0

        if not prices_list:
            return 0

        try:
            values = []
            for item in prices_list:
                service = item["service"]
                item_id = item["item_id"]
                item_name = item["item_name"]
                country_code = item["country_code"]
                price_data = item["price_data"]

                # 提取字段
                currency = price_data.get("currency")
                original_price = price_data.get("original_price")
                current_price = price_data.get("current_price")
                discount_percent = price_data.get("discount_percent", 0)
                price_cny = price_data.get("price_cny")

                # 提取额外数据
                standard_fields = {
                    "currency",
                    "original_price",
                    "current_price",
                    "discount_percent",
                    "price_cny",
                    "item_id",
                    "item_name",
                    "country_code",
                    "recorded_at",
                    "age_seconds",
                    "age_hours",
                }
                extra_data = {
                    k: v for k, v in price_data.items() if k not in standard_fields
                }
                extra_data_json = (
                    json.dumps(extra_data, ensure_ascii=False) if extra_data else None
                )

                values.append(
                    (
                        service,
                        item_id,
                        item_name,
                        country_code,
                        currency,
                        original_price,
                        current_price,
                        discount_percent,
                        price_cny,
                        extra_data_json,
                    )
                )

            # 批量插入
            async with self.get_cursor() as cursor:
                await cursor.executemany(
                    """
                    INSERT IGNORE INTO price_history (
                        service, item_id, item_name, country_code,
                        currency, original_price, current_price,
                        discount_percent, price_cny, extra_data
                    ) VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s
                    )
                    """,
                    values,
                )

            logger.info(f"✅ 批量保存成功: {len(values)} 条价格记录")
            return len(values)

        except Exception as e:
            logger.error(f"批量保存价格记录失败: {e}")
            return 0

    async def get_price_history(
        self,
        service: str,
        item_id: str,
        country_code: Optional[str] = None,
        days: int = 30,
    ) -> List[Dict]:
        """
        查询价格历史记录（供Web前端使用）

        Args:
            service: 服务名称
            item_id: 商品ID
            country_code: 国家代码（可选，不指定则查询所有国家）
            days: 查询天数

        Returns:
            价格历史记录列表
        """
        if not self._connected:
            logger.warning("PriceHistoryManager 未连接")
            return []

        try:
            start_date = datetime.now() - timedelta(days=days)

            async with self.get_cursor() as cursor:
                if country_code:
                    # 查询特定国家
                    await cursor.execute(
                        """
                        SELECT
                            id,
                            service,
                            item_id,
                            item_name,
                            country_code,
                            currency,
                            original_price,
                            current_price,
                            discount_percent,
                            price_cny,
                            extra_data,
                            recorded_at
                        FROM price_history
                        WHERE service = %s AND item_id = %s AND country_code = %s
                          AND recorded_at >= %s
                        ORDER BY recorded_at ASC
                        """,
                        (service, item_id, country_code, start_date),
                    )
                else:
                    # 查询所有国家
                    await cursor.execute(
                        """
                        SELECT
                            id,
                            service,
                            item_id,
                            item_name,
                            country_code,
                            currency,
                            original_price,
                            current_price,
                            discount_percent,
                            price_cny,
                            extra_data,
                            recorded_at
                        FROM price_history
                        WHERE service = %s AND item_id = %s
                          AND recorded_at >= %s
                        ORDER BY country_code, recorded_at ASC
                        """,
                        (service, item_id, start_date),
                    )

                results = await cursor.fetchall()

                # 转换数据类型
                history = []
                for row in results:
                    record = {
                        "id": row["id"],
                        "service": row["service"],
                        "item_id": row["item_id"],
                        "item_name": row["item_name"],
                        "country_code": row["country_code"],
                        "currency": row["currency"],
                        "original_price": (
                            float(row["original_price"])
                            if row["original_price"]
                            else None
                        ),
                        "current_price": (
                            float(row["current_price"])
                            if row["current_price"]
                            else None
                        ),
                        "discount_percent": row["discount_percent"],
                        "price_cny": (
                            float(row["price_cny"]) if row["price_cny"] else None
                        ),
                        "recorded_at": (
                            row["recorded_at"].isoformat()
                            if row["recorded_at"]
                            else None
                        ),
                    }

                    # 合并 extra_data
                    if row["extra_data"]:
                        try:
                            extra_data = (
                                json.loads(row["extra_data"])
                                if isinstance(row["extra_data"], str)
                                else row["extra_data"]
                            )
                            record["extra_data"] = extra_data
                        except Exception as e:
                            logger.warning(f"解析extra_data失败: {e}")

                    history.append(record)

                logger.debug(
                    f"查询历史记录: {service}/{item_id}/{country_code or 'all'}, 共 {len(history)} 条"
                )
                return history

        except Exception as e:
            logger.error(f"查询价格历史失败: {e}")
            return []

    async def get_latest_prices_by_service(
        self,
        service: str,
        freshness_threshold: int = 86400,
    ) -> List[Dict]:
        """
        批量查询某服务所有最新价格记录

        通过子查询找到每个 (item_id, country_code) 的最新记录，
        再过滤掉超过新鲜度阈值的数据。

        Args:
            service: 服务名称 (如 "icloud")
            freshness_threshold: 新鲜度阈值（秒），默认24小时

        Returns:
            价格数据列表，每条记录同 get_latest_price() 格式
        """
        if not self._connected:
            logger.warning("PriceHistoryManager 未连接")
            return []

        try:
            async with self.get_cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT
                        ph.id,
                        ph.service,
                        ph.item_id,
                        ph.item_name,
                        ph.country_code,
                        ph.currency,
                        ph.original_price,
                        ph.current_price,
                        ph.discount_percent,
                        ph.price_cny,
                        ph.extra_data,
                        ph.recorded_at,
                        TIMESTAMPDIFF(SECOND, ph.recorded_at, NOW()) as age_seconds
                    FROM price_history ph
                    INNER JOIN (
                        SELECT item_id, country_code, MAX(recorded_at) as max_at
                        FROM price_history
                        WHERE service = %s
                        GROUP BY item_id, country_code
                    ) latest ON ph.item_id = latest.item_id
                        AND ph.country_code = latest.country_code
                        AND ph.recorded_at = latest.max_at
                    WHERE ph.service = %s
                        AND TIMESTAMPDIFF(SECOND, ph.recorded_at, NOW()) < %s
                    """,
                    (service, service, freshness_threshold),
                )

                results = await cursor.fetchall()

                records = []
                for row in results:
                    price_data = {
                        "item_id": row["item_id"],
                        "item_name": row["item_name"],
                        "country_code": row["country_code"],
                        "currency": row["currency"],
                        "original_price": (
                            float(row["original_price"])
                            if row["original_price"]
                            else None
                        ),
                        "current_price": (
                            float(row["current_price"])
                            if row["current_price"]
                            else None
                        ),
                        "discount_percent": row["discount_percent"],
                        "price_cny": (
                            float(row["price_cny"]) if row["price_cny"] else None
                        ),
                        "recorded_at": (
                            row["recorded_at"].isoformat()
                            if row["recorded_at"]
                            else None
                        ),
                        "age_seconds": row["age_seconds"],
                    }

                    # 合并 extra_data
                    if row["extra_data"]:
                        try:
                            extra = (
                                json.loads(row["extra_data"])
                                if isinstance(row["extra_data"], str)
                                else row["extra_data"]
                            )
                            price_data.update(extra)
                        except Exception as e:
                            logger.warning(f"解析extra_data失败: {e}")

                    records.append(price_data)

                logger.info(
                    f"批量查询 {service} 最新价格: {len(records)} 条记录"
                )
                return records

        except Exception as e:
            logger.error(f"批量查询最新价格失败: {e}", exc_info=True)
            return []

    async def cleanup_old_data(self, days_to_keep: int = 90) -> int:
        """
        清理旧数据（性能优化）

        Args:
            days_to_keep: 保留天数，默认90天

        Returns:
            删除的记录数
        """
        if not self._connected:
            logger.warning("PriceHistoryManager 未连接")
            return 0

        try:
            cutoff_date = datetime.now() - timedelta(days=days_to_keep)

            async with self.get_cursor() as cursor:
                await cursor.execute(
                    "DELETE FROM price_history WHERE recorded_at < %s",
                    (cutoff_date,),
                )
                deleted_count = cursor.rowcount

            logger.info(
                f"✅ 清理旧数据完成: 删除 {deleted_count} 条记录（保留 {days_to_keep} 天）"
            )
            return deleted_count

        except Exception as e:
            logger.error(f"清理旧数据失败: {e}")
            return 0

    async def get_statistics(self, service: Optional[str] = None) -> Dict:
        """
        获取价格历史统计信息（可选功能）

        Args:
            service: 服务名称（可选，不指定则统计所有服务）

        Returns:
            统计信息字典
        """
        if not self._connected:
            logger.warning("PriceHistoryManager 未连接")
            return {}

        try:
            async with self.get_cursor() as cursor:
                if service:
                    # 特定服务统计
                    await cursor.execute(
                        """
                        SELECT
                            COUNT(*) as total_records,
                            COUNT(DISTINCT item_id) as unique_items,
                            COUNT(DISTINCT country_code) as countries_covered,
                            MIN(recorded_at) as earliest_record,
                            MAX(recorded_at) as latest_record
                        FROM price_history
                        WHERE service = %s
                        """,
                        (service,),
                    )
                else:
                    # 全局统计
                    await cursor.execute("""
                        SELECT
                            COUNT(*) as total_records,
                            COUNT(DISTINCT service) as services,
                            COUNT(DISTINCT item_id) as unique_items,
                            COUNT(DISTINCT country_code) as countries_covered,
                            MIN(recorded_at) as earliest_record,
                            MAX(recorded_at) as latest_record
                        FROM price_history
                        """)

                result = await cursor.fetchone()

                if result:
                    stats = {
                        "total_records": result["total_records"],
                        "unique_items": result["unique_items"],
                        "countries_covered": result["countries_covered"],
                        "earliest_record": (
                            result["earliest_record"].isoformat()
                            if result["earliest_record"]
                            else None
                        ),
                        "latest_record": (
                            result["latest_record"].isoformat()
                            if result["latest_record"]
                            else None
                        ),
                    }

                    if not service:
                        stats["services"] = result["services"]

                    return stats

                return {}

        except Exception as e:
            logger.error(f"获取统计信息失败: {e}")
            return {}

    async def delete_item(
        self, service: str, item_id: str, country_code: Optional[str] = None
    ) -> int:
        """
        删除指定服务与商品ID的价格记录，可选按国家筛选。

        Args:
            service: 服务名称，例如 "app_store"
            item_id: 商品ID，例如 App ID 字符串
            country_code: 国家代码（可选）。不提供则删除该 item 在所有国家的记录。

        Returns:
            实际删除的记录数
        """
        if not self._connected:
            logger.warning("PriceHistoryManager 未连接")
            return 0

        try:
            async with self.get_cursor() as cursor:
                if country_code:
                    await cursor.execute(
                        "DELETE FROM price_history WHERE service=%s AND item_id=%s AND country_code=%s",
                        (service, item_id, country_code.upper()),
                    )
                else:
                    await cursor.execute(
                        "DELETE FROM price_history WHERE service=%s AND item_id=%s",
                        (service, item_id),
                    )
                deleted = cursor.rowcount or 0
                logger.info(
                    f"✅ 删除价格记录: service={service}, item_id={item_id}, country={country_code or 'ALL'}, deleted={deleted}"
                )
                return deleted
        except Exception as e:
            logger.error(f"删除价格记录失败: {e}")
            return 0
