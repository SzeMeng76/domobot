import logging
import re
from typing import Any

import httpx
from telegram import Update
from telegram.ext import ContextTypes

from utils.country_data import SUPPORTED_COUNTRIES, get_country_flag
from utils.formatter import escape_v2, foldable_text_v2, foldable_text_with_markdown_v2
from utils.message_manager import delete_user_command, send_error, send_search_result
from utils.price_formatter import get_rank_emoji, format_cache_timestamp
from utils.price_query_service import PriceQueryService


logger = logging.getLogger(__name__)

PLAN_DISPLAY = {
    "PC Game Pass":        "PC Game Pass",
    "Game Pass Core":      "Core",
    "Game Pass Standard":  "Standard",
    "Game Pass Ultimate":  "Ultimate",
}


class XboxPriceBot(PriceQueryService):
    """Manages Xbox Game Pass price data fetching, caching, and formatting."""

    PRICE_URL = "https://raw.githubusercontent.com/SzeMeng76/xbox-gamepass-prices/refs/heads/master/xbox_gamepass_prices_processed.json"

    async def _fetch_data(self, context: ContextTypes.DEFAULT_TYPE) -> dict | None:
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
            logger.error(f"Failed to fetch Xbox Game Pass price data: {e}")
            return None

    def _init_country_mapping(self) -> dict[str, dict]:
        mapping = {}
        if not self.data:
            return mapping

        regions = self.data.get("regions", [])
        for region_data in regions:
            code = region_data.get("region_code", "")
            if not code:
                continue
            mapping[code.upper()] = region_data
            if region_data.get("name_cn"):
                mapping[region_data["name_cn"]] = region_data
            country_code = code.split("-")[-1].upper()
            mapping[country_code] = region_data
            if country_code in SUPPORTED_COUNTRIES and "name" in SUPPORTED_COUNTRIES[country_code]:
                mapping[SUPPORTED_COUNTRIES[country_code]["name"]] = region_data
        return mapping

    async def _format_price_message(self, region_code: str, region_data: dict) -> str | None:
        if not region_data or "plans" not in region_data:
            return None

        name_cn = region_data.get("name_cn", region_code)
        country_code = region_code.split("-")[-1].upper()
        flag = get_country_flag(country_code)

        lines = [f"📍 国家/地区: {flag} {name_cn} ({region_code.upper()})"]

        currency = region_data.get("currency", "")
        for plan in region_data["plans"]:
            plan_name = PLAN_DISPLAY.get(plan.get("plan", ""), plan.get("plan", ""))
            regular = plan.get("regular_price")
            intro = plan.get("intro_price")
            regular_cny = plan.get("regular_price_cny")

            if regular is None:
                continue

            price_str = f"{currency} {regular:,.2f}" if regular % 1 else f"{currency} {regular:,.0f}"
            cny_str = f" ≈ ¥{regular_cny:.2f}" if regular_cny else ""

            if intro:
                intro_str = f"{currency} {intro:,.2f}" if intro % 1 else f"{currency} {intro:,.0f}"
                lines.append(f"  • {plan_name}: 首月 {intro_str} → {price_str}/月{cny_str}")
            else:
                lines.append(f"  • {plan_name}: {price_str}/月{cny_str}")

        return "\n".join(lines)

    def _extract_comparison_price(self, region_data: dict) -> float | None:
        for plan in region_data.get("plans", []):
            if plan.get("plan") == "Game Pass Ultimate":
                cny = plan.get("regular_price_cny")
                if cny:
                    try:
                        return float(cny)
                    except (ValueError, TypeError):
                        continue
        return None

    async def get_top_cheapest(self, top_n: int = 10, plan: str = "pc") -> str:
        """
        plan: "pc" → PC Game Pass ranking, "ultimate" → Ultimate ranking
        """
        if not self.data:
            return foldable_text_v2(f"❌ 错误：未能加载 {self.service_name} 价格数据。请稍后再试或检查日志。")

        use_ultimate = plan.lower() == "ultimate"
        cache_key = "_top10_cheapest_ultimate" if use_ultimate else "_top10_cheapest_pc_game_pass"
        plan_label = "Ultimate" if use_ultimate else "PC Game Pass"
        plan_full = "Game Pass Ultimate" if use_ultimate else "PC Game Pass"

        if cache_key in self.data and "data" in self.data[cache_key]:
            top_items = self.data[cache_key]["data"][:top_n]
            message_lines = [f"*🏆 {self.service_name} 全球最低价格排名 (基于 {plan_label} 套餐月付)*", ""]

            for idx, item in enumerate(top_items, 1):
                region_code = item["region_code"]
                name_cn = item.get("name_cn", region_code)
                country_code = region_code.split("-")[-1].upper()
                flag = get_country_flag(country_code)
                rank_emoji = get_rank_emoji(idx)
                currency = item["currency"]
                price = item["auto_renew_price"]
                price_cny = item["auto_renew_price_cny"]

                price_str = f"{currency} {price:,.2f}" if price % 1 else f"{currency} {price:,.0f}"

                message_lines.append(f"{rank_emoji} {name_cn} ({region_code}) {flag}")
                message_lines.append(f"💰 {plan_label}: {price_str} ≈ ¥{price_cny:.2f}")
                if idx < len(top_items):
                    message_lines.append("")
        else:
            # 降级到自行排序
            regions = self.data.get("regions", [])
            rankable = []
            for region_data in regions:
                code = region_data.get("region_code", "")
                if not code:
                    continue
                plan_data = next((p for p in region_data.get("plans", []) if p.get("plan") == plan_full), None)
                if not plan_data:
                    continue
                cny = plan_data.get("regular_price_cny")
                if cny is None:
                    continue
                rankable.append({
                    "code": code,
                    "name_cn": region_data.get("name_cn", code),
                    "price": float(cny),
                    "currency": region_data.get("currency", ""),
                    "price_raw": plan_data.get("regular_price", 0),
                })

            if not rankable:
                return foldable_text_v2(f"未能找到足够的可比较 {plan_label} 套餐价格信息。")

            rankable.sort(key=lambda x: x["price"])
            top_items_raw = rankable[:top_n]

            message_lines = [f"*🏆 {self.service_name} 全球最低价格排名 (基于 {plan_label} 套餐月付)*", ""]

            for idx, item in enumerate(top_items_raw, 1):
                region_code = item["code"]
                country_code = region_code.split("-")[-1].upper()
                flag = get_country_flag(country_code)
                rank_emoji = get_rank_emoji(idx)
                price_raw = item["price_raw"]
                currency = item["currency"]
                price_str = f"{currency} {price_raw:,.2f}" if price_raw % 1 else f"{currency} {price_raw:,.0f}"

                message_lines.append(f"{rank_emoji} {item['name_cn']} ({region_code}) {flag}")
                message_lines.append(f"💰 {plan_label}: {price_str} ≈ ¥{item['price']:.2f}")
                if idx < len(top_items_raw):
                    message_lines.append("")

        if self.cache_timestamp:
            message_lines.append("")
            message_lines.append(format_cache_timestamp(self.cache_timestamp))

        return foldable_text_with_markdown_v2("\n".join(message_lines).strip())

    async def command_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message:
            return
        try:
            await self.load_or_fetch_data(context)

            if not self.data:
                await send_error(context, update.message.chat_id, escape_v2(f"❌ 错误：未能加载 {self.service_name} 价格数据，请稍后再试。"), parse_mode="MarkdownV2")
                await delete_user_command(context, update.message.chat_id, update.message.message_id)
                return

            args = context.args or []
            if not args:
                result = await self.get_top_cheapest(plan="pc")
            elif len(args) == 1 and args[0].lower() == "ultimate":
                result = await self.get_top_cheapest(plan="ultimate")
            else:
                result = await self.query_prices(args)

            await send_search_result(context, update.message.chat_id, result, parse_mode="MarkdownV2", disable_web_page_preview=True)
            await delete_user_command(context, update.message.chat_id, update.message.message_id)
        except Exception as e:
            logger.error(f"Error processing {self.service_name} command: {e}", exc_info=True)
            await send_error(context, update.message.chat_id, escape_v2(f"❌ 执行查询时发生错误: {e}"), parse_mode="MarkdownV2")
            await delete_user_command(context, update.message.chat_id, update.message.message_id)

    async def query_prices(self, query_list: list[str]) -> str:
        if not self.data:
            return foldable_text_v2(f"❌ 错误：未能加载 {self.service_name} 价格数据。请稍后再试或检查日志。")

        result_messages = []
        not_found = []

        for query in query_list:
            price_info = self.country_mapping.get(query.upper()) or self.country_mapping.get(query)

            if not price_info:
                not_found.append(query)
                continue

            found_code = None
            regions = self.data.get("regions", [])
            for data_val in regions:
                if data_val is price_info:
                    found_code = data_val.get("region_code")
                    break

            if found_code:
                formatted = await self._format_price_message(found_code, price_info)
                if formatted:
                    result_messages.append(formatted)
                else:
                    not_found.append(query)
            else:
                not_found.append(query)

        raw_parts = [f"*🎮 {self.service_name} 订阅价格查询*", ""]

        if result_messages:
            for i, msg in enumerate(result_messages):
                raw_parts.append(msg)
                if i < len(result_messages) - 1:
                    raw_parts.append("")
        elif query_list:
            raw_parts.append("未能查询到您指定的国家/地区的价格信息。")

        if not_found:
            raw_parts.append("")
            raw_parts.append(f"❌ 未找到以下地区的价格信息：{', '.join(not_found)}")

        if self.cache_timestamp:
            raw_parts.append("")
            raw_parts.append(format_cache_timestamp(self.cache_timestamp))

        return foldable_text_with_markdown_v2("\n".join(raw_parts).strip())
