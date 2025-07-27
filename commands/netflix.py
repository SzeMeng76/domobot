import logging
from datetime import datetime
from typing import Any

import httpx
from telegram import Update
from telegram.ext import ContextTypes

# Note: CacheManager import removed - now uses injected Redis cache manager from main.py
from utils.command_factory import command_factory
from utils.config_manager import config_manager
from utils.country_data import SUPPORTED_COUNTRIES, get_country_flag
from utils.formatter import foldable_text_v2, foldable_text_with_markdown_v2
from utils.message_manager import delete_user_command, send_error
from utils.permissions import Permission
from utils.price_query_service import PriceQueryService
from utils.rate_converter import RateConverter


logger = logging.getLogger(__name__)


class NetflixPriceBot(PriceQueryService):
    PRICE_URL = "https://opensheet.elk.sh/1b3qotAFrjHai7ny3AGGCTHsZ1xyl4yXviPU3Grqt940/by+regions"

    async def _fetch_data(self, context: ContextTypes.DEFAULT_TYPE) -> list[dict[str, Any]] | None:
        """Fetches Netflix price data from the specified URL."""
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
            logger.error(f"Failed to fetch Netflix price data: {e}")
            return None
        except Exception as e:
            logger.error(f"An unexpected error occurred while fetching Netflix data: {e}")
            return None

    def _init_country_mapping(self) -> dict[str, Any]:
        """Initializes country name and code to data mapping."""
        mapping = {}
        if not self.data:
            return mapping
        for item in self.data:
            if item.get("Translation"):
                mapping[item["Translation"]] = item
            if item.get("Code"):
                code_upper = item["Code"].upper()
                mapping[code_upper] = item
                # Use English name from central source if available
                if code_upper in SUPPORTED_COUNTRIES and "name" in SUPPORTED_COUNTRIES[code_upper]:
                    mapping[SUPPORTED_COUNTRIES[code_upper]["name"]] = item
            if item.get("Country"):
                mapping[item["Country"]] = item
        return mapping

    async def _format_price_message(self, country_code: str, price_info: dict) -> str:
        """Formats the price information for a single country as raw text."""
        country_info = SUPPORTED_COUNTRIES.get(country_code.upper(), {})
        country_name = country_info.get("name_cn", price_info.get("Translation", country_code))
        country_flag = get_country_flag(country_code)
        currency = price_info.get("Currency", "")

        lines = [f"📍 国家/地区: {country_name} ({country_code.upper()}) {country_flag}"]

        plan_map = {
            "Mobile": ("移动版", "MobileUSD"),
            "Standard with ads": ("标准广告版", "With_Ads_USD"),
            "Basic": ("基础版", "BasicUSD"),
            "Standard": ("标准版", "StandardUSD"),
            "Premium": ("高级版", "PremiumUSD"),
        }

        plan_keys = list(plan_map.keys())

        # Filter out plans that are not available in the price_info
        available_plans = [key for key in plan_keys if price_info.get(key) and price_info.get(key) != "N/A"]

        for _i, key in enumerate(available_plans):
            name, usd_key = plan_map[key]
            cny_price_str = ""
            try:
                usd_val = float(price_info[usd_key] or 0)
                if usd_val > 0:
                    cny_price = await self.rate_converter.convert(usd_val, "USD", "CNY")
                    if cny_price:
                        cny_price_str = f" ≈ ¥{cny_price:.2f}"
            except (ValueError, TypeError, KeyError):
                pass  # Ignore if conversion fails

            lines.append(f"  • {name}：{price_info[key]} {currency}{cny_price_str}")

        has_extra_members = price_info.get("Extra member slots") and price_info.get("Extra member slots") != "N/A"
        if has_extra_members:
            # Process extra member slots format: "Standard: 1 / Premium: 2"
            extra_members_text = price_info["Extra member slots"]
            # Add currency to numbers in the format
            import re

            # Replace numbers with number + currency
            extra_members_formatted = re.sub(r"(\d+)", r"\1 " + currency, extra_members_text)
            lines.append(f"  • 额外会员：{extra_members_formatted}")

        return "\n".join(lines)

    def _extract_comparison_price(self, item: dict) -> float | None:
        """Extracts the Premium plan's USD price for ranking."""
        if item.get("PremiumUSD") and item.get("PremiumUSD") != "N/A":
            try:
                return float(item["PremiumUSD"])
            except (ValueError, TypeError):
                pass
        return None

    async def query_prices(self, query_list: list[str]) -> str:
        """
        Queries prices for a list of specified countries.
        Note: This overrides the base method to be async.
        """
        if not self.data:
            error_message = f"❌ 错误：未能加载 {self.service_name} 价格数据。请稍后再试或检查日志。"
            return foldable_text_v2(error_message)

        result_messages = []
        not_found = []

        for query in query_list:
            price_info = self.country_mapping.get(query.upper()) or self.country_mapping.get(query)

            if not price_info:
                not_found.append(query)
                continue

            country_code = price_info.get("Code")
            if country_code:
                formatted_message = await self._format_price_message(country_code, price_info)
                if formatted_message:
                    result_messages.append(formatted_message)
                else:
                    not_found.append(query)
            else:
                not_found.append(query)

        # Assemble raw text message
        raw_message_parts = []
        raw_message_parts.append(f"*🎬 {self.service_name} 订阅价格查询*")
        raw_message_parts.append("")  # Empty line after header

        if result_messages:
            # Add blank lines between countries for better readability
            for i, msg in enumerate(result_messages):
                raw_message_parts.append(msg)
                # Add blank line between countries (except for the last one)
                if i < len(result_messages) - 1:
                    raw_message_parts.append("")
        elif query_list:
            raw_message_parts.append("未能查询到您指定的国家/地区的价格信息。")

        if not_found:
            raw_message_parts.append("")  # Empty line before not found section
            not_found_str = ", ".join(not_found)
            raw_message_parts.append(f"❌ 未找到以下地区的价格信息：{not_found_str}")

        if self.cache_timestamp:
            update_time_str = datetime.fromtimestamp(self.cache_timestamp).strftime("%Y-%m-%d %H:%M:%S")
            raw_message_parts.append("")  # Empty line before timestamp
            raw_message_parts.append(f"\n⏱ 数据更新时间 (缓存)：{update_time_str}")

        # Join and apply formatting
        raw_final_message = "\n".join(raw_message_parts).strip()
        return foldable_text_with_markdown_v2(raw_final_message)

    async def get_top_cheapest(self, top_n: int = 10) -> str:
        """Gets the top 10 cheapest countries for the Premium plan."""
        if not self.data:
            error_message = f"❌ 错误：未能加载 {self.service_name} 价格数据。"
            return foldable_text_v2(error_message)

        countries_with_prices = []
        for item in self.data:
            premium_usd = self._extract_comparison_price(item)
            if premium_usd is not None:
                countries_with_prices.append({"data": item, "price": premium_usd})

        countries_with_prices.sort(key=lambda x: x["price"])
        top_countries = countries_with_prices[:top_n]

        # Assemble raw text message
        raw_message_parts = []
        raw_message_parts.append(f"*🏆 {self.service_name} 全球最低价格排名 (高级版)*")
        raw_message_parts.append("")  # Empty line after header

        for idx, country_data in enumerate(top_countries, 1):
            item = country_data["data"]
            country_code = item.get("Code", "N/A").upper()
            country_info = SUPPORTED_COUNTRIES.get(country_code, {})
            country_name = country_info.get("name_cn", item.get("Translation", country_code))
            country_flag = get_country_flag(country_code)
            premium_cny = await self.rate_converter.convert(country_data["price"], "USD", "CNY") or 0.0
            premium_local = item.get("Premium", "")
            currency = item.get("Currency", "")

            # Rank emoji
            rank_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
            if idx == 1:
                rank_emoji = "🥇"
            elif idx == 2:
                rank_emoji = "🥈"
            elif idx == 3:
                rank_emoji = "🥉"
            elif idx <= 10:
                rank_emoji = rank_emojis[idx - 1]
            else:
                rank_emoji = f"{idx}."

            country_block = f"{rank_emoji} {country_name} ({country_code}) {country_flag}\n💰 高级版: {premium_local} {currency} ≈ ¥{premium_cny:.2f}"
            raw_message_parts.append(country_block)

            # Add blank line between countries (except for the last one)
            if idx < len(top_countries):
                raw_message_parts.append("")

        if self.cache_timestamp:
            update_time_str = datetime.fromtimestamp(self.cache_timestamp).strftime("%Y-%m-%d %H:%M:%S")
            raw_message_parts.append(f"⏱ 数据更新时间 (缓存)：{update_time_str}")

        # Join and apply formatting
        raw_final_message = "\n".join(raw_message_parts).strip()
        return foldable_text_with_markdown_v2(raw_final_message)


# --- Command Handler Setup ---
netflix_price_bot: NetflixPriceBot | None = None


def set_dependencies(cache_manager, rate_converter: RateConverter):
    """Initializes the NetflixPriceBot service with Redis cache manager."""
    global netflix_price_bot
    netflix_price_bot = NetflixPriceBot(
        service_name="Netflix",
        cache_manager=cache_manager,
        rate_converter=rate_converter,
        cache_duration_seconds=config_manager.config.netflix_cache_duration,
        subdirectory="netflix",
    )


async def netflix_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /netflix command."""
    if not update.message:
        return

    if not netflix_price_bot:
        error_message = "❌ 错误：Netflix 查询服务未初始化。"
        await send_error(context, update.message.chat_id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        return
    await netflix_price_bot.command_handler(update, context)


async def netflix_clean_cache_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /netflix_cleancache command."""
    if not update.message:
        return

    if not netflix_price_bot:
        error_message = "❌ 错误：Netflix 查询服务未初始化。"
        await send_error(context, update.message.chat_id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        return
    return await netflix_price_bot.clean_cache_command(update, context)


# Register commands
command_factory.register_command("nf", netflix_command, permission=Permission.NONE, description="Netflix订阅价格查询")
command_factory.register_command(
    "nf_cleancache", netflix_clean_cache_command, permission=Permission.ADMIN, description="清理Netflix缓存"
)
