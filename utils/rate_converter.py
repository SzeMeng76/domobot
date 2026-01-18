import asyncio
import logging
import time
from statistics import median
from typing import Optional

import httpx


# Note: CacheManager import removed - now uses injected cache manager from main.py


logger = logging.getLogger(__name__)


class RateConverter:
    def __init__(self, api_keys: list, cache_manager, cache_duration_seconds: int = 3600):
        if not api_keys:
            raise ValueError("API keys list cannot be empty.")
        self.api_keys = api_keys
        self.cache_manager = cache_manager
        self.current_key_index = 0
        self.rates: dict = {}
        self.rates_timestamp: int = 0
        self.cache_duration = cache_duration_seconds
        self._lock = asyncio.Lock()

        # GitHub 数据源配置（免费，每8小时更新）
        self.github_sources = [
            {
                "name": "Coinbase",
                "url": "https://raw.githubusercontent.com/DyAxy/NewExchangeRatesTable/refs/heads/main/data/coinbase.json",
                "cache_key": "github_coinbase",
                "cache_duration": 28800  # 8小时
            },
            {
                "name": "Neutrino",
                "url": "https://raw.githubusercontent.com/DyAxy/NewExchangeRatesTable/refs/heads/main/data/neutrino.json",
                "cache_key": "github_neutrino",
                "cache_duration": 28800
            },
            {
                "name": "UnionPay",
                "url": "https://raw.githubusercontent.com/DyAxy/NewExchangeRatesTable/refs/heads/main/data/unionpay.json",
                "cache_key": "github_unionpay",
                "cache_duration": 28800
            },
            {
                "name": "Visa",
                "url": "https://raw.githubusercontent.com/SzeMeng76/NewExchangeRatesTable/refs/heads/main/data/visa.json",
                "cache_key": "github_visa",
                "cache_duration": 28800
            },
            {
                "name": "Wise",
                "url": "https://raw.githubusercontent.com/DyAxy/NewExchangeRatesTable/refs/heads/main/data/wise.json",
                "cache_key": "github_wise",
                "cache_duration": 28800
            }
        ]

        # 存储各个平台的汇率数据（用于对比）
        self.platform_rates: dict = {}  # {platform_name: {"rates": {...}, "timestamp": xxx}}

    def _get_next_api_key(self) -> str:
        """Rotates and returns the next available API key."""
        key = self.api_keys[self.current_key_index]
        self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
        return key

    async def _fetch_rates(self) -> dict | None:
        """Fetches the latest exchange rates from the API."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        for _ in self.api_keys:
            api_key = self._get_next_api_key()
            url = f"https://openexchangerates.org/api/latest.json?app_id={api_key}"
            try:
                from utils.http_client import create_custom_client

                async with create_custom_client(headers=headers, timeout=5) as client:
                    response = await client.get(url)
                    response.raise_for_status()
                    data = response.json()
                    if "rates" in data and "timestamp" in data:
                        logger.info(f"Successfully fetched rates using API key ending in ...{api_key[-4:]}")
                        return data
            except httpx.HTTPStatusError as e:
                logger.warning(
                    f"API key ...{api_key[-4:]} failed with status {e.response.status_code}. Trying next key."
                )
            except httpx.RequestError as e:
                logger.error(f"Request failed for API key ...{api_key[-4:]}: {e}")

        logger.error("All API keys failed. Could not fetch exchange rates.")
        return None

    async def _fetch_github_source(self, source: dict) -> Optional[dict]:
        """获取单个 GitHub 数据源的汇率数据"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        try:
            from utils.http_client import create_custom_client

            async with create_custom_client(headers=headers, timeout=10) as client:
                response = await client.get(source["url"])
                response.raise_for_status()
                data = response.json()

                # GitHub 源的数据格式是 {"timestamp": xxx, "data": {...}}
                # 需要转换为 {"timestamp": xxx, "rates": {...}} 以保持一致性
                if "data" in data and "timestamp" in data:
                    # 过滤掉值为 -1 的货币（表示不可用）
                    valid_rates = {k: v for k, v in data["data"].items() if v != -1}
                    logger.info(f"Successfully fetched {source['name']} rates: {len(valid_rates)} currencies")
                    return {
                        "rates": valid_rates,
                        "timestamp": data["timestamp"],
                        "source": source["name"]
                    }
        except httpx.HTTPStatusError as e:
            logger.warning(f"{source['name']} source failed with status {e.response.status_code}")
        except httpx.RequestError as e:
            logger.warning(f"Request failed for {source['name']}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error fetching {source['name']}: {e}")

        return None

    async def _fetch_all_github_sources(self) -> dict:
        """并行获取所有 GitHub 数据源"""
        tasks = [self._fetch_github_source(source) for source in self.github_sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        successful_sources = {}
        for source, result in zip(self.github_sources, results):
            if result and not isinstance(result, Exception):
                successful_sources[source["name"]] = result

        logger.info(f"Fetched {len(successful_sources)}/{len(self.github_sources)} GitHub sources successfully")
        return successful_sources

    async def get_rates(self, force_refresh: bool = False, fetch_github_sources: bool = False):
        """
        Loads rates from cache or fetches them from the API.
        Uses a lock to prevent concurrent fetches.

        Args:
            force_refresh: 强制刷新所有数据
            fetch_github_sources: 是否同时获取 GitHub 数据源（用于平台对比）
        """
        # First, check without a lock for the most common case (in-memory cache is fresh)
        current_time = time.time()
        if not force_refresh and self.rates and (current_time - self.rates_timestamp < self.cache_duration):
            # 如果需要 GitHub 源但还没有，则同步加载（避免 fallback 时没有数据）
            if fetch_github_sources and not self.platform_rates:
                await self._load_github_sources()
            return

        async with self._lock:
            # Re-check condition inside the lock to handle race conditions
            if not force_refresh and self.rates and (current_time - self.rates_timestamp < self.cache_duration):
                if fetch_github_sources and not self.platform_rates:
                    await self._load_github_sources()
                return

            cache_key = "exchange_rates"
            cached_data = await self.cache_manager.load_cache(cache_key, subdirectory="exchange_rates")

            if not force_refresh and cached_data:
                cached_timestamp = cached_data.get("timestamp", 0)
                if current_time - cached_timestamp < self.cache_duration:
                    self.rates = cached_data["rates"]
                    self.rates_timestamp = cached_timestamp
                    logger.info(f"Loaded exchange rates from file cache. Data is from {time.ctime(cached_timestamp)}.")

                    # 如果需要，加载 GitHub 源
                    if fetch_github_sources:
                        await self._load_github_sources()
                    return

            logger.info("Cache is stale or refresh is forced. Fetching new rates from API.")

            # 优先使用 Open Exchange Rates（更新频率高）
            api_data = await self._fetch_rates()
            if api_data:
                self.rates = api_data["rates"]
                self.rates_timestamp = api_data["timestamp"]
                await self.cache_manager.save_cache(cache_key, api_data, subdirectory="exchange_rates")
                logger.info(
                    f"Fetched and cached new rates from API. Data timestamp: {time.ctime(self.rates_timestamp)}"
                )
            else:
                # 如果主 API 失败，尝试使用 GitHub 源作为降级
                logger.warning("Open Exchange Rates API failed, trying GitHub sources as fallback")
                github_data = await self._fetch_all_github_sources()

                if github_data:
                    # 使用中位数聚合多个源的数据
                    aggregated_rates = self._aggregate_rates(github_data)
                    if aggregated_rates:
                        self.rates = aggregated_rates
                        self.rates_timestamp = int(time.time())
                        logger.info("Using aggregated rates from GitHub sources")
                    else:
                        logger.error("Failed to aggregate GitHub sources")
                else:
                    logger.warning("All data sources failed, keeping existing data")

            # 如果需要平台对比数据，异步加载 GitHub 源
            if fetch_github_sources:
                await self._load_github_sources()

    async def _load_github_sources(self):
        """加载 GitHub 数据源到 platform_rates"""
        current_time = time.time()

        # 检查缓存中的 GitHub 源
        for source in self.github_sources:
            cache_key = source["cache_key"]
            cached = await self.cache_manager.load_cache(cache_key, subdirectory="exchange_rates")

            if cached and (current_time - cached.get("timestamp", 0) < source["cache_duration"]):
                # 使用缓存数据
                self.platform_rates[source["name"]] = cached
            else:
                # 缓存过期，重新获取
                data = await self._fetch_github_source(source)
                if data:
                    self.platform_rates[source["name"]] = data
                    await self.cache_manager.save_cache(cache_key, data, subdirectory="exchange_rates")

        logger.info(f"Loaded {len(self.platform_rates)} GitHub sources for platform comparison")

    def _aggregate_rates(self, sources_data: dict) -> Optional[dict]:
        """
        聚合多个数据源的汇率，使用中位数策略

        Args:
            sources_data: {source_name: {"rates": {...}, "timestamp": xxx}}

        Returns:
            聚合后的汇率字典
        """
        if not sources_data:
            return None

        # 收集所有货币代码
        all_currencies = set()
        for source_data in sources_data.values():
            all_currencies.update(source_data["rates"].keys())

        aggregated = {}
        for currency in all_currencies:
            # 收集该货币在所有源中的汇率
            rates = []
            for source_data in sources_data.values():
                if currency in source_data["rates"]:
                    rate = source_data["rates"][currency]
                    if isinstance(rate, (int, float)) and rate > 0:
                        rates.append(rate)

            # 使用中位数（更抗异常值）
            if rates:
                if len(rates) == 1:
                    aggregated[currency] = rates[0]
                else:
                    aggregated[currency] = median(rates)

        logger.info(f"Aggregated rates for {len(aggregated)} currencies from {len(sources_data)} sources")
        return aggregated

    async def get_platform_comparison(self, amount: float, from_currency: str, to_currency: str) -> Optional[dict]:
        """
        获取多个平台的汇率对比

        Returns:
            {
                "primary": {
                    "source": "Open Exchange Rates",
                    "rate": xxx,
                    "converted": xxx,
                    "timestamp": xxx
                },
                "platforms": {
                    "Coinbase": {"rate": xxx, "converted": xxx},
                    "Visa": {...},
                    ...
                }
            }
        """
        from_currency = from_currency.upper()
        to_currency = to_currency.upper()

        # 确保有平台数据
        if not self.platform_rates:
            await self._load_github_sources()

        result = {
            "primary": None,
            "platforms": {}
        }

        # 主源（Open Exchange Rates）
        if self.rates and from_currency in self.rates and to_currency in self.rates:
            from_rate = self.rates[from_currency]
            to_rate = self.rates[to_currency]
            converted = round((amount / from_rate) * to_rate, 2)
            result["primary"] = {
                "source": "Open Exchange Rates",
                "rate": round(to_rate / from_rate, 6),
                "converted": converted,
                "timestamp": self.rates_timestamp
            }

        # GitHub 平台源
        for platform_name, platform_data in self.platform_rates.items():
            rates = platform_data["rates"]
            if from_currency in rates and to_currency in rates:
                from_rate = rates[from_currency]
                to_rate = rates[to_currency]
                converted = round((amount / from_rate) * to_rate, 2)
                result["platforms"][platform_name] = {
                    "rate": round(to_rate / from_rate, 6),
                    "converted": converted,
                    "timestamp": platform_data.get("timestamp", 0)
                }

        return result if (result["primary"] or result["platforms"]) else None

    async def convert(self, amount: float, from_currency: str, to_currency: str) -> float | None:
        """Converts an amount from one currency to another."""
        # 快速检查数据可用性，如果数据太旧才加载
        if not await self.is_data_available():
            await self.get_rates()  # Ensure rates are loaded

        from_currency = from_currency.upper()
        to_currency = to_currency.upper()

        if not self.rates:
            logger.error("Cannot perform conversion, exchange rates are not available.")
            return None

        if from_currency not in self.rates or to_currency not in self.rates:
            logger.warning(f"Attempted conversion with unknown currency: {from_currency} or {to_currency}")
            return None

        # Conversion is done via the base currency (USD)
        from_rate = self.rates[from_currency]
        to_rate = self.rates[to_currency]

        converted_amount = (amount / from_rate) * to_rate
        return round(converted_amount, 2)

    async def is_data_available(self) -> bool:
        """检查是否有可用的汇率数据（无需等待网络）"""
        return bool(self.rates) and time.time() - self.rates_timestamp < 21600  # 6小时内的数据视为可用


async def main():
    # Example usage
    from .config_manager import get_config
    from .redis_cache_manager import RedisCacheManager

    config = get_config()

    # Assuming API keys are comma-separated in the config
    api_keys = config.exchange_rate_api_keys

    if not api_keys:
        logger.error("No API keys configured for RateConverter.")
        return

    # Use Redis cache manager instead of file cache
    cache_manager = RedisCacheManager(
        host=config.redis_host,
        port=config.redis_port,
        password=config.redis_password,
        db=config.redis_db
    )
    await cache_manager.connect()

    converter = RateConverter(api_keys, cache_manager, config.rate_cache_duration)

    # Test basic functionality
    try:
        cny_amount = 100
        usd_amount = await converter.convert(cny_amount, "CNY", "USD")
        if usd_amount is not None:
            logger.info(f"Rate converter test: {cny_amount} CNY ≈ {usd_amount} USD")

        eur_amount = 50
        gbp_amount = await converter.convert(eur_amount, "EUR", "GBP")
        if gbp_amount is not None:
            logger.info(f"Rate converter test: {eur_amount} EUR ≈ {gbp_amount} GBP")
    except Exception as e:
        logger.error(f"Rate converter test failed: {e}")
    finally:
        # Clean up Redis connection
        await cache_manager.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
