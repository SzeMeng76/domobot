"""
Nintendo Switch Online 价格查询机器人
参考 disney_modules/price_bot.py 的架构实现
"""

import logging
from typing import Dict, List, Optional
from telegram.ext import ContextTypes

from utils.country_data import get_country_flag
from utils.formatter import escape_markdown_v2
from utils.price_formatter import format_price_cny
from utils.price_query_service import PriceQueryService

logger = logging.getLogger(__name__)


class NintendoSwitchPriceBot(PriceQueryService):
    """Nintendo Switch Online 价格查询机器人"""

    def __init__(self, service_name: str, cache_manager, rate_converter, cache_duration_seconds: int, subdirectory: str):
        from utils.http_client import get_http_client
        http_client = get_http_client()

        super().__init__(
            service_name=service_name,
            cache_manager=cache_manager,
            rate_converter=rate_converter,
            cache_duration_seconds=cache_duration_seconds,
            subdirectory=subdirectory,
            http_client=http_client,
        )
        self.data_url = "https://cdn.jsdelivr.net/gh/SzeMeng76/nintendo-switch-online-prices@main/nintendo_prices_cny_sorted.json"

    async def fetch_data(self, context: Optional[ContextTypes.DEFAULT_TYPE] = None) -> Optional[Dict]:
        """从CDN获取价格数据"""
        try:
            response = await self.http_client.get(self.data_url, timeout=15)
            if response.status_code == 200:
                data = response.json()
                logger.info(f"✅ 成功从CDN获取 Nintendo Switch Online 数据")
                return data
            else:
                logger.error(f"❌ CDN返回状态码: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"❌ 获取 Nintendo Switch Online 数据失败: {e}")
            return None

    async def get_top_rankings(self) -> str:
        """获取 Individual + Family 12个月套餐 TOP 10 排行"""
        data = await self.get_data()
        if not data:
            return escape_markdown_v2("❌ 数据加载失败")

        individual_list = data.get("_top_10_cheapest_individual_12month", [])
        family_list = data.get("_top_10_cheapest_family_12month", [])

        lines = ["🎮 *Nintendo Switch Online 全球价格排行*\n"]

        # Individual 12个月
        lines.append("*📱 Individual \\(12个月\\)*")
        for i, plan in enumerate(individual_list[:10], 1):
            country_name = escape_markdown_v2(plan.get("country_name", "Unknown"))
            country_code = plan.get("country_code", "")
            flag = get_country_flag(country_code)
            price_cny_per_month = plan.get("price_cny_per_month", 0)
            price_cny_total = plan.get("price_cny_total", 0)
            currency = plan.get("currency", "")
            amount = plan.get("amount", 0)

            lines.append(
                f"{i}\\. {flag} {country_name} \\| "
                f"{escape_markdown_v2(format_price_cny(price_cny_per_month))}/月 \\| "
                f"总计: {escape_markdown_v2(format_price_cny(price_cny_total))} \\| "
                f"{escape_markdown_v2(currency)} {escape_markdown_v2(str(amount))}"
            )

        # Family 12个月
        lines.append("\n*👨‍👩‍👧‍👦 Family \\(12个月\\)*")
        for i, plan in enumerate(family_list[:10], 1):
            country_name = escape_markdown_v2(plan.get("country_name", "Unknown"))
            country_code = plan.get("country_code", "")
            flag = get_country_flag(country_code)
            price_cny_per_month = plan.get("price_cny_per_month", 0)
            price_cny_total = plan.get("price_cny_total", 0)
            currency = plan.get("currency", "")
            amount = plan.get("amount", 0)

            lines.append(
                f"{i}\\. {flag} {country_name} \\| "
                f"{escape_markdown_v2(format_price_cny(price_cny_per_month))}/月 \\| "
                f"总计: {escape_markdown_v2(format_price_cny(price_cny_total))} \\| "
                f"{escape_markdown_v2(currency)} {escape_markdown_v2(str(amount))}"
            )

        return "\n".join(lines)

    async def get_individual_ranking(self) -> str:
        """获取 Individual 12个月套餐 TOP 10"""
        data = await self.get_data()
        if not data:
            return escape_markdown_v2("❌ 数据加载失败")

        individual_list = data.get("_top_10_cheapest_individual_12month", [])

        lines = ["🎮 *Nintendo Switch Online \\- Individual \\(12个月\\)*\n"]

        for i, plan in enumerate(individual_list[:10], 1):
            country_name = escape_markdown_v2(plan.get("country_name", "Unknown"))
            country_code = plan.get("country_code", "")
            flag = get_country_flag(country_code)
            price_cny_per_month = plan.get("price_cny_per_month", 0)
            price_cny_total = plan.get("price_cny_total", 0)
            currency = plan.get("currency", "")
            amount = plan.get("amount", 0)

            lines.append(
                f"{i}\\. {flag} {country_name} \\| "
                f"{escape_markdown_v2(format_price_cny(price_cny_per_month))}/月 \\| "
                f"总计: {escape_markdown_v2(format_price_cny(price_cny_total))} \\| "
                f"{escape_markdown_v2(currency)} {escape_markdown_v2(str(amount))}"
            )

        return "\n".join(lines)

    async def get_family_ranking(self) -> str:
        """获取 Family 12个月套餐 TOP 10"""
        data = await self.get_data()
        if not data:
            return escape_markdown_v2("❌ 数据加载失败")

        family_list = data.get("_top_10_cheapest_family_12month", [])

        lines = ["🎮 *Nintendo Switch Online \\- Family \\(12个月\\)*\n"]

        for i, plan in enumerate(family_list[:10], 1):
            country_name = escape_markdown_v2(plan.get("country_name", "Unknown"))
            country_code = plan.get("country_code", "")
            flag = get_country_flag(country_code)
            price_cny_per_month = plan.get("price_cny_per_month", 0)
            price_cny_total = plan.get("price_cny_total", 0)
            currency = plan.get("currency", "")
            amount = plan.get("amount", 0)

            lines.append(
                f"{i}\\. {flag} {country_name} \\| "
                f"{escape_markdown_v2(format_price_cny(price_cny_per_month))}/月 \\| "
                f"总计: {escape_markdown_v2(format_price_cny(price_cny_total))} \\| "
                f"{escape_markdown_v2(currency)} {escape_markdown_v2(str(amount))}"
            )

        return "\n".join(lines)

    async def query_countries(self, country_codes: List[str]) -> str:
        """查询指定国家的所有套餐"""
        data = await self.get_data()
        if not data:
            return escape_markdown_v2("❌ 数据加载失败")

        by_country = data.get("by_country", {})
        lines = ["🎮 *Nintendo Switch Online 价格查询*\n"]

        for country_code in country_codes:
            country_code_upper = country_code.upper()
            plans = by_country.get(country_code_upper, [])

            if not plans:
                lines.append(f"❌ {escape_markdown_v2(country_code_upper)}: 未找到数据")
                continue

            flag = get_country_flag(country_code_upper)
            country_name = escape_markdown_v2(plans[0].get("country_name", country_code_upper))
            lines.append(f"\n*{flag} {country_name}*")

            for plan in plans:
                plan_name = escape_markdown_v2(plan.get("plan", "Unknown"))
                plan_type = escape_markdown_v2(plan.get("plan_type", ""))
                duration = escape_markdown_v2(plan.get("duration", ""))
                price_cny_per_month = plan.get("price_cny_per_month", 0)
                price_cny_total = plan.get("price_cny_total", 0)
                currency = plan.get("currency", "")
                amount = plan.get("amount", 0)

                lines.append(
                    f"• {plan_type} \\- {duration}: "
                    f"{escape_markdown_v2(format_price_cny(price_cny_per_month))}/月 "
                    f"\\(总计: {escape_markdown_v2(format_price_cny(price_cny_total))}\\) "
                    f"\\| {escape_markdown_v2(currency)} {escape_markdown_v2(str(amount))}"
                )

        return "\n".join(lines)
