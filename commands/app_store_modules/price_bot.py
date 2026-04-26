"""
App Store 价格查询机器人类

提供 App Store 应用搜索和价格查询功能
"""

import asyncio
import logging
import time
from datetime import datetime

from commands.app_store_modules import AppStoreWebAPI, AppStoreParser
from utils.country_data import SUPPORTED_COUNTRIES, get_country_flag
from utils.price_parser import extract_currency_and_price
from utils.search_ui import SearchUIBuilder
from utils.task_manager import task_manager

logger = logging.getLogger(__name__)

# 搜索配置常量
RESULTS_PER_PAGE = 5
SEARCH_RESULT_LIMIT = 200


class CacheKeyBuilder:
    """缓存键构建器"""

    @staticmethod
    def search(query: str, country_code: str, platform: str) -> str:
        """构建搜索缓存键"""
        return f"app_store:search:{platform}:{country_code}:{query}"

    @staticmethod
    def app_prices(app_id: int, country_code: str, platform: str) -> str:
        """构建应用价格缓存键"""
        return f"app_store:prices:{platform}:{app_id}:{country_code}"


class AppStorePriceBot:
    """App Store 价格查询机器人类

    功能：
    - 应用搜索（支持全平台：iOS/macOS/iPad/tvOS/watchOS/visionOS）
    - 多国价格对比
    - 价格缓存（Redis + MySQL）
    - 搜索会话管理
    """

    def __init__(
        self,
        cache_manager,
        rate_converter,
        smart_cache_manager=None,
        redis_cache_duration: int = 21600,
        db_freshness: int = 86400,
    ):
        """初始化 App Store 价格查询机器人

        Args:
            cache_manager: Redis 缓存管理器
            rate_converter: 汇率转换器
            smart_cache_manager: 智能缓存管理器（可选，用于 MySQL 持久化）
            redis_cache_duration: Redis 缓存时长
            db_freshness: 数据库新鲜度阈值
        """
        self.cache_manager = cache_manager
        self.rate_converter = rate_converter
        self.smart_cache_manager = smart_cache_manager
        self.redis_cache_duration = redis_cache_duration
        self.db_freshness = db_freshness

        # 初始化搜索 UI 构建器
        self.search_ui = SearchUIBuilder(
            service_name="App Store",
            service_icon="🍎",
            callback_prefix="app",
            type_icons={
                "software": "📱",
                "mac-software": "💻",
                "ipad-software": "📱",
                "default": "📱",
            },
            page_size=RESULTS_PER_PAGE,
            max_name_length=35,
        )

        logger.info("✅ AppStorePriceBot 初始化完成")

    async def load_or_fetch_search_results(
        self, query: str, country_code: str = "US", platform: str = "iphone"
    ) -> list[dict]:
        """加载或获取搜索结果

        Args:
            query: 搜索关键词
            country_code: 国家代码
            platform: 平台类型

        Returns:
            list[dict]: 搜索结果列表
        """
        search_cache_key = CacheKeyBuilder.search(query, country_code, platform)

        # 尝试从缓存加载
        cached_data = await self.cache_manager.load_cache(
            search_cache_key,
            max_age_seconds=self.redis_cache_duration,
            subdirectory="app_store",
        )

        if cached_data:
            logger.info(f"使用缓存的搜索结果: {query} in {country_code}")
            return cached_data.get("results", [])

        # 执行网页搜索
        logger.info(f"网页搜索: {query} in {country_code}, platform: {platform}")
        raw_data = await AppStoreWebAPI.search_apps_by_web(
            query, country=country_code, platform=platform, limit=SEARCH_RESULT_LIMIT
        )
        all_results = raw_data.get("results", [])
        logger.info(f"✅ 网页搜索完成: 找到 {len(all_results)} 个应用")

        # 搜索失败或无结果时不缓存，避免空结果被长期缓存
        if not all_results:
            return all_results

        # 保存缓存
        cache_data = {
            "query": query,
            "country": country_code,
            "platform": platform,
            "results": all_results,
            "timestamp": int(time.time()),
        }
        await self.cache_manager.save_cache(
            search_cache_key,
            cache_data,
            subdirectory="app_store",
            ttl=self.redis_cache_duration,
        )

        return all_results

    async def get_app_prices(
        self, app_name: str, country_code: str, app_id: int, platform: str
    ) -> dict:
        """获取指定国家的应用价格信息（方案C: 分层缓存）"""
        cache_key = CacheKeyBuilder.app_prices(app_id, country_code, platform)

        # 第1层：Redis热缓存查询
        cached_data = await self.cache_manager.load_cache(
            cache_key,
            max_age_seconds=self.redis_cache_duration,
            subdirectory="app_store",
        )

        if cached_data:
            logger.debug(f"✅ App Store Redis缓存命中: {app_id}/{country_code}")
            cache_timestamp = await self.cache_manager.get_cache_timestamp(
                cache_key, subdirectory="app_store"
            )
            cache_info = (
                f"*(缓存于: {datetime.fromtimestamp(cache_timestamp).strftime('%Y-%m-%d %H:%M')})*"
                if cache_timestamp
                else ""
            )
            return {
                "country_code": country_code,
                "country_name": SUPPORTED_COUNTRIES.get(country_code, {}).get(
                    "name", country_code
                ),
                "flag_emoji": get_country_flag(country_code),
                "status": "ok",
                "app_price_str": cached_data.get("app_price_str"),
                "app_price_cny": cached_data.get("app_price_cny"),
                "in_app_purchases": cached_data.get("in_app_purchases", []),
                "cache_info": cache_info,
                "real_app_name": cached_data.get("real_app_name"),
                # 元数据
                "developer_name": cached_data.get("developer_name"),
                "developer_url": cached_data.get("developer_url"),
                "rating_value": cached_data.get("rating_value"),
                "review_count": cached_data.get("review_count"),
                "app_category": cached_data.get("app_category"),
                "operating_system": cached_data.get("operating_system"),
                "supported_devices": cached_data.get("supported_devices"),
                "icon_url": cached_data.get("icon_url"),
            }

        # 第2层：MySQL持久化缓存查询
        if self.smart_cache_manager:
            try:
                db_data = await self.smart_cache_manager.db.get_latest_price(
                    service="app_store",
                    item_id=str(app_id),
                    country_code=country_code,
                    freshness_threshold=self.db_freshness,
                )
                if db_data:
                    logger.info(f"✅ App Store MySQL缓存命中: {app_id}/{country_code}")
                    # 回写Redis热缓存
                    await self.cache_manager.save_cache(
                        cache_key,
                        db_data,
                        subdirectory="app_store",
                        ttl=self.redis_cache_duration,
                    )
                    return {
                        "country_code": country_code,
                        "country_name": SUPPORTED_COUNTRIES.get(country_code, {}).get(
                            "name", country_code
                        ),
                        "flag_emoji": get_country_flag(country_code),
                        "status": "ok",
                        "app_price_str": db_data.get("app_price_str"),
                        "app_price_cny": db_data.get("app_price_cny"),
                        "in_app_purchases": db_data.get("in_app_purchases", []),
                        "cache_info": f"*(数据更新于: {db_data.get('age_hours', 0):.1f}小时前)*",
                        "real_app_name": db_data.get("real_app_name")
                        or db_data.get("item_name"),
                        # 元数据
                        "developer_name": db_data.get("developer_name"),
                        "developer_url": db_data.get("developer_url"),
                        "rating_value": db_data.get("rating_value"),
                        "review_count": db_data.get("review_count"),
                        "app_category": db_data.get("app_category"),
                        "operating_system": db_data.get("operating_system"),
                        "supported_devices": db_data.get("supported_devices"),
                        "icon_url": db_data.get("icon_url"),
                    }
            except Exception as e:
                logger.warning(f"App Store MySQL查询失败: {e}")

        # 第3层：爬取新数据
        logger.info(f"🔄 App Store缓存未命中，开始爬取: {app_id}/{country_code}")

        country_info = SUPPORTED_COUNTRIES.get(country_code, {})
        country_name = country_info.get("name", country_code)
        flag_emoji = get_country_flag(country_code)

        # 获取应用页面 HTML
        html_content = await AppStoreWebAPI.fetch_app_page(app_id, country_code)

        if not html_content:
            return {
                "country_code": country_code,
                "country_name": country_name,
                "flag_emoji": flag_emoji,
                "status": "not_listed",
                "error_message": "未上架",
            }

        try:
            # 使用 JSON-LD 解析器
            offers_data = AppStoreParser.parse_json_ld_offers(
                html_content, country_code
            )

            if not offers_data:
                logger.warning(f"无法解析 App {app_id} 在 {country_code} 的价格数据")
                return {
                    "country_code": country_code,
                    "country_name": country_name,
                    "flag_emoji": flag_emoji,
                    "status": "error",
                    "error_message": "解析失败",
                }

            # 提取应用元数据（开发者、评分、分类等）
            metadata = AppStoreParser.extract_metadata(html_content)

            real_app_name = offers_data.get("app_name", "")
            currency = offers_data.get("currency", "USD")
            price = offers_data.get("price", 0)
            category = offers_data.get("category", "free")

            # 格式化应用价格
            if category == "free" or price == 0:
                app_price_str = "免费"
                app_price_cny = 0.0
            else:
                app_price_str = f"{price} {currency}"
                if country_code == "CN":
                    # CN 区域价格本身就是 CNY
                    app_price_cny = float(price)
                elif self.rate_converter and self.rate_converter.rates:
                    if currency.upper() in self.rate_converter.rates:
                        cny_price = await self.rate_converter.convert(
                            float(price), currency.upper(), "CNY"
                        )
                        if cny_price is not None:
                            app_price_cny = cny_price
                        else:
                            app_price_cny = None
                    else:
                        app_price_cny = None
                else:
                    app_price_cny = None

            # 解析内购项目
            in_app_purchases_raw = AppStoreParser.parse_in_app_purchases_html(
                html_content
            )

            # 转换内购项目的货币
            in_app_purchases = []
            for iap in in_app_purchases_raw:
                price_str = iap["price_str"]
                detected_currency, price_value = extract_currency_and_price(
                    price_str, country_code, service="app_store"
                )

                if price_value is None:
                    price_value = 0

                cny_price = None
                price_usd = None
                if price_value > 0 and self.rate_converter and self.rate_converter.rates:
                    # 优先使用检测到的货币，如果检测失败则使用应用主货币
                    iap_currency = detected_currency or currency
                    if iap_currency.upper() in self.rate_converter.rates:
                        if country_code != "CN":
                            cny_price = await self.rate_converter.convert(
                                price_value, iap_currency.upper(), "CNY"
                            )
                        else:
                            cny_price = price_value
                        try:
                            price_usd = await self.rate_converter.convert(
                                price_value, iap_currency.upper(), "USD"
                            )
                            if price_usd is not None:
                                price_usd = round(price_usd, 2)
                        except Exception:
                            pass

                in_app_purchases.append(
                    {
                        "name": iap["name"],
                        "price_str": price_str,
                        "cny_price": cny_price,
                        "price_usd": price_usd,
                    }
                )

            result_data = {
                "country_code": country_code,
                "country_name": country_name,
                "flag_emoji": flag_emoji,
                "status": "ok",
                "app_price_str": app_price_str,
                "app_price_cny": app_price_cny,
                "in_app_purchases": in_app_purchases,
                "real_app_name": real_app_name,
                # 元数据（开发者、评分、分类等）
                "developer_name": metadata.get("developer_name"),
                "developer_url": metadata.get("developer_url"),
                "rating_value": metadata.get("rating_value"),
                "review_count": metadata.get("review_count"),
                "app_category": metadata.get("category"),
                "operating_system": metadata.get("operating_system"),
                "supported_devices": metadata.get("supported_devices"),
                "icon_url": metadata.get("icon_url"),
            }

            # 保存到Redis热缓存
            await self.cache_manager.save_cache(
                cache_key,
                result_data,
                subdirectory="app_store",
                ttl=self.redis_cache_duration,
            )

            # 异步保存到MySQL持久化
            if self.smart_cache_manager:
                task_manager.create_task(
                    self._save_app_price_to_mysql(
                        app_id=app_id,
                        country_code=country_code,
                        real_app_name=real_app_name,
                        currency=currency,
                        price=price,
                        app_price_cny=app_price_cny,
                        result_data=result_data,
                    ),
                    name=f"appstore_save_{app_id}_{country_code}",
                    context="app_store_mysql",
                )

            return result_data

        except Exception as e:
            logger.error(
                f"解析 App {app_id} 在 {country_code} 的价格时出错: {e}", exc_info=True
            )
            return {
                "country_code": country_code,
                "country_name": country_name,
                "flag_emoji": flag_emoji,
                "status": "error",
                "error_message": "解析失败",
            }

    @staticmethod
    def _extract_developer_id(developer_url: str) -> str | None:
        """从开发者 URL 中提取 developer_id"""
        if not developer_url:
            return None
        import re
        match = re.search(r"/id(\d+)", developer_url)
        return match.group(1) if match else None

    async def _save_app_price_to_mysql(
        self,
        app_id: int,
        country_code: str,
        real_app_name: str,
        currency: str,
        price: float,
        app_price_cny: float | None,
        result_data: dict,
    ):
        """异步保存App Store价格数据到MySQL"""
        if not self.smart_cache_manager:
            return

        try:
            price_data = {
                "currency": currency,
                "original_price": price,
                "current_price": price,
                "discount_percent": 0,
                "price_cny": app_price_cny,
                # 额外数据
                "app_price_str": result_data.get("app_price_str"),
                "in_app_purchases": result_data.get("in_app_purchases", []),
                "real_app_name": real_app_name,
                # 元数据（开发者、评分、分类等）
                "developer_name": result_data.get("developer_name"),
                "developer_url": result_data.get("developer_url"),
                "developer_id": self._extract_developer_id(result_data.get("developer_url", "")),
                "rating_value": result_data.get("rating_value"),
                "review_count": result_data.get("review_count"),
                "app_category": result_data.get("app_category"),
                "operating_system": result_data.get("operating_system"),
                "supported_devices": result_data.get("supported_devices"),
                "icon_url": result_data.get("icon_url"),
            }

            await self.smart_cache_manager.db.save_price(
                service="app_store",
                item_id=str(app_id),
                item_name=real_app_name,
                country_code=country_code,
                price_data=price_data,
            )
            logger.debug(f"App Store价格已保存到MySQL: {app_id}/{country_code}")
        except Exception as e:
            logger.error(f"保存App Store价格到MySQL失败: {e}")

    async def get_multi_country_prices(
        self, app_name: str, app_id: int, platform: str, countries: list[str]
    ) -> list[dict]:
        """获取多个国家的应用价格"""
        tasks = [
            self.get_app_prices(app_name, country, app_id, platform)
            for country in countries
        ]
        price_results = await asyncio.gather(*tasks)
        return price_results
