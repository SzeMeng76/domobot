import logging
import re
from typing import Any

import httpx
from telegram.ext import ContextTypes

from utils.country_data import SUPPORTED_COUNTRIES, get_country_flag
from utils.formatter import foldable_text_v2, foldable_text_with_markdown_v2
from utils.price_formatter import get_rank_emoji, format_cache_timestamp
from utils.price_query_service import PriceQueryService


logger = logging.getLogger(__name__)


class DisneyPriceBot(PriceQueryService):
    """Manages Disney+ price data fetching, caching, and formatting."""

    PRICE_URL = "https://raw.githubusercontent.com/SzeMeng76/disneyplus-prices/refs/heads/main/disneyplus_prices_processed.json"

    async def _fetch_data(self, context: ContextTypes.DEFAULT_TYPE) -> dict | None:
        """Fetches Disney+ price data from the specified URL."""
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
            logger.error(f"Failed to fetch Disney+ price data: {e}")
            return None

    def _init_country_mapping(self) -> dict[str, dict]:
        """Initializes country name/code to data mapping."""
        mapping = {}
        if not self.data:
            return mapping

        for code, country_data in self.data.items():
            if code.startswith("_"):
                continue

            mapping[code.upper()] = country_data
            if country_data.get("name_cn"):
                mapping[country_data["name_cn"]] = country_data
            if code.upper() in SUPPORTED_COUNTRIES and "name" in SUPPORTED_COUNTRIES[code.upper()]:
                mapping[SUPPORTED_COUNTRIES[code.upper()]["name"]] = country_data
        return mapping

    async def _format_price_message(self, country_code: str, price_info: dict) -> str | None:
        """Formats single country Disney+ price info into Markdown string."""
        if not price_info or "plans" not in price_info:
            return None

        country_name_cn = price_info.get(
            "name_cn", SUPPORTED_COUNTRIES.get(country_code.upper(), {}).get("name", country_code)
        )
        country_flag = get_country_flag(country_code)

        lines = [f"📍 国家/地区: {country_flag} {country_name_cn} ({country_code.upper()})"]

        plans = price_info["plans"]

        def clean_price(price_str_val, currency_code_val):
            if price_str_val is None or price_str_val == "N/A":
                return "N/A"
            cleaned = re.sub(r"[^\d.]", "", str(price_str_val))
            if not cleaned:
                return "N/A"

            if currency_code_val == "CNY":
                return f"¥ {cleaned}"
            else:
                return f"{currency_code_val} {cleaned}"

        for plan in plans:
            plan_name = plan.get("plan_name", "未知套餐")
            currency_code = plan.get("currency_code", "")

            monthly_original = clean_price(plan.get("monthly_price_original", "N/A"), currency_code)
            monthly_cny = clean_price(plan.get("monthly_price_cny", "N/A"), "CNY")
            annual_original = clean_price(plan.get("annual_price_original"), currency_code)
            annual_cny = clean_price(plan.get("annual_price_cny"), "CNY")

            monthly_text = f"{monthly_original} ≈ {monthly_cny}"
            annual_text = ""
            if annual_original != "N/A" and annual_cny != "N/A":
                annual_text = f" | 年付: {annual_original} ≈ {annual_cny}"

            lines.append(f"  • {plan_name}: 月付: {monthly_text}{annual_text}")

        return "\n".join(lines)

    def _extract_comparison_price(self, country_data: dict) -> float | None:
        """Extracts the Premium plan's monthly CNY price for ranking."""
        if "plans" in country_data:
            for plan in country_data["plans"]:
                plan_name = plan.get("plan_name", "")
                monthly_cny_raw = plan.get("monthly_price_cny")
                if ("Premium" in plan_name or "高級版" in plan_name) and monthly_cny_raw and monthly_cny_raw != "N/A":
                    try:
                        return float(re.sub(r"[^\d.]", "", monthly_cny_raw))
                    except (ValueError, TypeError):
                        logger.warning(f"Could not parse price from {monthly_cny_raw}")
                        continue
        return None

    async def get_top_cheapest(self, top_n: int = 10) -> str:
        if not self.data:
            error_msg = f"❌ 错误：未能加载 {self.service_name} 价格数据。请稍后再试或检查日志。"
            return foldable_text_v2(error_msg)

        # 优先使用内置的预排序数据
        if "_top_10_cheapest_premium_plans" in self.data and "data" in self.data["_top_10_cheapest_premium_plans"]:
            cheapest_data = self.data["_top_10_cheapest_premium_plans"]["data"]
            top_countries = []

            for item in cheapest_data[:top_n]:
                top_countries.append({
                    "code": item["country_code"],
                    "name_cn": item["country_name_cn"],
                    "price": item["price_cny"],
                    "plan_details": {
                        "plan_name": item["plan_name"],
                        "monthly_price_original": item["original_price"],
                        "currency_code": item["currency"]
                    }
                })
        else:
            # 降级到原有的排序逻辑
            countries_with_prices = []
            for code, country_data in self.data.items():
                if code.startswith("_"):
                    continue

                comparison_price = self._extract_comparison_price(country_data)
                if comparison_price is not None:
                    country_name_cn = country_data.get(
                        "name_cn", SUPPORTED_COUNTRIES.get(code.upper(), {}).get("name", code)
                    )

                    premium_plan_details = next(
                        (
                            plan
                            for plan in country_data.get("plans", [])
                            if ("Premium" in plan.get("plan_name", "") or "高級版" in plan.get("plan_name", ""))
                        ),
                        None,
                    )

                    countries_with_prices.append(
                        {
                            "code": code,
                            "name_cn": country_name_cn,
                            "price": comparison_price,
                            "plan_details": premium_plan_details,
                        }
                    )

            if not countries_with_prices:
                error_msg = f"未能找到足够的可比较 {self.service_name} Premium 套餐价格信息。"
                return foldable_text_v2(error_msg)

            countries_with_prices.sort(key=lambda x: x["price"])
            top_countries = countries_with_prices[:top_n]

        message_lines = [f"*🏆 {self.service_name} 全球最低价格排名 (基于 Premium 套餐月付)*"]
        message_lines.append("")

        for idx, country in enumerate(top_countries, 1):
            country_code_upper = country["code"].upper()
            country_flag = get_country_flag(country_code_upper)
            rank_emoji = get_rank_emoji(idx)

            plan_details = country.get("plan_details")
            if plan_details:
                monthly_original = plan_details.get("monthly_price_original", "N/A")
                price_line = f"{monthly_original} ≈ ¥{country['price']:.2f}"
                plan_name = plan_details.get("plan_name", "Premium Plan")

                message_lines.append(f"{rank_emoji} {country['name_cn']} ({country_code_upper}) {country_flag}")
                message_lines.append(f"💰 {plan_name}: {price_line}")
            else:
                message_lines.append(f"{rank_emoji} {country['name_cn']} ({country_code_upper}) {country_flag}")
                message_lines.append(f"💰 Premium: ¥{country['price']:.2f}")

            if idx < len(top_countries):
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
            normalized_query = "UK" if query.upper() == "GB" else query
            price_info = self.country_mapping.get(normalized_query.upper()) or self.country_mapping.get(
                normalized_query
            )

            if not price_info:
                not_found.append(query)
                continue

            found_code = None
            for code, data_val in self.data.items():
                if data_val == price_info:
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
            raw_message_parts.append(f"❌ 未找到以下地区的价格信息：{not_found_str}")

        if self.cache_timestamp:
            raw_message_parts.append("")
            raw_message_parts.append(format_cache_timestamp(self.cache_timestamp))

        raw_final_message = "\n".join(raw_message_parts).strip()
        return foldable_text_with_markdown_v2(raw_final_message)
