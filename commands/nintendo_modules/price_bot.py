import logging
import re
from typing import Any

import httpx
from telegram.ext import ContextTypes

from utils.country_data import SUPPORTED_COUNTRIES, get_country_flag
from utils.formatter import foldable_text_v2, foldable_text_with_markdown_v2, escape_v2
from utils.price_formatter import get_rank_emoji, format_cache_timestamp
from utils.price_query_service import PriceQueryService


logger = logging.getLogger(__name__)


class NintendoSwitchPriceBot(PriceQueryService):
    """Manages Nintendo Switch Online price data fetching, caching, and formatting."""

    PRICE_URL = "https://cdn.jsdelivr.net/gh/SzeMeng76/nintendo-switch-online-prices@main/nintendo_prices_cny_sorted.json"

    async def _fetch_data(self, context: ContextTypes.DEFAULT_TYPE) -> dict | None:
        """Fetches Nintendo Switch Online price data from the specified URL."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        try:
            from utils.http_client import create_custom_client

            async with create_custom_client(headers=headers) as client:
                response = await client.get(self.PRICE_URL, timeout=20.0)
                response.raise_for_status()
                return response.json()
        except httpx.RequestError as e:
            logger.error(f"Failed to fetch Nintendo Switch Online price data: {e}")
            return None

    def _init_country_mapping(self) -> dict[str, dict]:
        """Initializes country name/code to data mapping."""
        mapping = {}
        if not self.data or "by_country" not in self.data:
            return mapping

        for code, plans_list in self.data["by_country"].items():
            if not plans_list:
                continue

            mapping[code.upper()] = plans_list

            # Use country name from first plan
            if plans_list and "country_name" in plans_list[0]:
                country_name = plans_list[0]["country_name"]
                mapping[country_name] = plans_list

            # Add SUPPORTED_COUNTRIES name mapping
            if code.upper() in SUPPORTED_COUNTRIES and "name" in SUPPORTED_COUNTRIES[code.upper()]:
                mapping[SUPPORTED_COUNTRIES[code.upper()]["name"]] = plans_list

        return mapping

    async def _format_price_message(self, country_code: str, price_info: Any) -> str | None:
        """Formats single country Nintendo Switch Online price info into Markdown string."""
        if not price_info or not isinstance(price_info, list):
            return None

        # Get country name from first plan
        country_name = price_info[0].get("country_name", country_code) if price_info else country_code
        country_flag = get_country_flag(country_code)

        lines = [f"📍 国家/地区: {country_flag} {escape_v2(country_name)} ({country_code.upper()})"]

        for plan in price_info:
            plan_type = plan.get("plan_type", "Unknown")
            duration = plan.get("duration", "Unknown")
            currency = plan.get("currency", "")
            amount = plan.get("amount", 0)
            price_cny_total = plan.get("price_cny_total", 0)
            price_cny_per_month = plan.get("price_cny_per_month", 0)

            original_price = f"{currency} {amount:.2f}" if amount else "N/A"
            cny_price = f"¥ {price_cny_total:.2f}" if price_cny_total else "N/A"

            if plan.get("duration_months", 1) > 1:
                per_month_text = f" (¥ {price_cny_per_month:.2f}/月)"
            else:
                per_month_text = ""

            lines.append(f"  • {escape_v2(plan_type)} - {escape_v2(duration)}: {escape_v2(original_price)} ≈ {escape_v2(cny_price)}{escape_v2(per_month_text)}")

        return "\n".join(lines)

    def _extract_comparison_price(self, country_data: Any) -> float | None:
        """Extracts Individual 12-month per-month CNY price for ranking."""
        if not isinstance(country_data, list):
            return None

        for plan in country_data:
            if plan.get("plan_type") == "Individual" and plan.get("duration_months") == 12:
                price_cny_per_month = plan.get("price_cny_per_month")
                if price_cny_per_month:
                    try:
                        return float(price_cny_per_month)
                    except (ValueError, TypeError):
                        continue
        return None

    async def get_top_cheapest(self, top_n: int = 10) -> str:
        """Gets the top N cheapest Individual 12-month plans."""
        if not self.data:
            error_msg = f"❌ 错误：未能加载 {self.service_name} 价格数据。请稍后再试或检查日志。"
            return foldable_text_v2(error_msg)

        # Use pre-sorted data from _top_10_cheapest_individual_12month
        if "_top_10_cheapest_individual_12month" in self.data:
            cheapest_data = self.data["_top_10_cheapest_individual_12month"][:top_n]
        else:
            error_msg = f"未能找到 {self.service_name} 排名数据。"
            return foldable_text_v2(error_msg)

        message_lines = [f"*🏆 {self.service_name} 全球最低价格排名 \\(Individual 12个月套餐\\)*"]
        message_lines.append("")

        for idx, plan in enumerate(cheapest_data, 1):
            country_code = plan.get("country_code", "").upper()
            country_name = plan.get("country_name", country_code)
            country_flag = get_country_flag(country_code)
            rank_emoji = get_rank_emoji(idx)

            currency = plan.get("currency", "")
            amount = plan.get("amount", 0)
            price_cny_total = plan.get("price_cny_total", 0)
            price_cny_per_month = plan.get("price_cny_per_month", 0)

            original_price = f"{currency} {amount:.2f}"

            message_lines.append(f"{rank_emoji} {escape_v2(country_name)} \\({country_code}\\) {country_flag}")
            message_lines.append(f"💰 {escape_v2(original_price)} ≈ ¥{price_cny_total:.2f} \\(¥{price_cny_per_month:.2f}/月\\)")

            if idx < len(cheapest_data):
                message_lines.append("")

        if self.cache_timestamp:
            message_lines.append("")
            message_lines.append(format_cache_timestamp(self.cache_timestamp))

        body_text = "\n".join(message_lines).strip()
        return foldable_text_with_markdown_v2(body_text)

    async def query_prices(self, query_list: list[str]) -> str:
        """Queries prices for a list of specified countries."""
        if not self.data:
            error_message = f"❌ 错误：未能加载 {self.service_name} 价格数据。请稍后再试或检查日志。"
            return foldable_text_v2(error_message)

        result_messages = []
        not_found = []

        for query in query_list:
            normalized_query = query.upper()
            price_info = self.country_mapping.get(normalized_query) or self.country_mapping.get(query)

            if not price_info:
                not_found.append(query)
                continue

            # Find country code
            found_code = None
            if "by_country" in self.data:
                for code, plans_list in self.data["by_country"].items():
                    if plans_list == price_info:
                        found_code = code
                        break

            if found_code:
                formatted_message = await self._format_price_message(found_code, price_info)
                if formatted_message:
                    result_messages.append(formatted_message)
                else:
                    not_found.append(query)
            else:
                not_found.append(query)

        raw_message_parts = []
        raw_message_parts.append(f"*📱 {self.service_name} 订阅价格查询*")
        raw_message_parts.append("")

        if result_messages:
            for i, msg in enumerate(result_messages):
                raw_message_parts.append(msg)
                if i < len(result_messages) - 1:
                    raw_message_parts.append("")
        elif query_list:
            raw_message_parts.append("未能查询到您指定的国家/地区的价格信息。")

        if not_found:
            raw_message_parts.append("")
            not_found_str = ", ".join(not_found)
            raw_message_parts.append(f"❌ 未找到以下地区的价格信息：{escape_v2(not_found_str)}")

        if self.cache_timestamp:
            raw_message_parts.append("")
            raw_message_parts.append(format_cache_timestamp(self.cache_timestamp))

        raw_final_message = "\n".join(raw_message_parts).strip()
        return foldable_text_with_markdown_v2(raw_final_message)
