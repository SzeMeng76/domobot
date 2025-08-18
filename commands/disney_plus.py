import logging
import re
from datetime import datetime

import httpx
from telegram import Update
from telegram.ext import ContextTypes

# Note: CacheManager import removed - now uses injected Redis cache manager from main.py
from utils.command_factory import command_factory
from utils.country_data import SUPPORTED_COUNTRIES, get_country_flag
from utils.formatter import foldable_text_v2, foldable_text_with_markdown_v2
from utils.message_manager import delete_user_command, send_error
from utils.permissions import Permission
from utils.price_query_service import PriceQueryService
from utils.rate_converter import RateConverter


# Configure logging
logger = logging.getLogger(__name__)

# Data source URL
DATA_URL = "https://git.domob.org/https://github.com/domoxiaojun/disneyplus-prices/raw/refs/heads/main/disneyplus_prices_processed.json"


class DisneyPriceBot(PriceQueryService):
    """Manages Disney+ price data fetching, caching, and formatting."""

    async def _fetch_data(self, context: ContextTypes.DEFAULT_TYPE) -> dict | None:
        """Fetches Disney+ price data from the specified URL."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        try:
            from utils.http_client import create_custom_client

            async with create_custom_client(headers=headers) as client:
                response = await client.get(DATA_URL, timeout=20.0)
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
            if code.startswith("_"):  # 跳过元数据键如 _top_10_cheapest_premium_plans
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

        # 不转义，直接组装原始文本
        lines = [f"📍 国家/地区: {country_flag} {country_name_cn} ({country_code.upper()})"]

        plans = price_info["plans"]

        def clean_price(price_str_val, currency_code_val):
            if price_str_val is None or price_str_val == "N/A":
                return "N/A"
            # This regex is more robust for different currency formats
            cleaned = re.sub(r"[^\d.]", "", str(price_str_val))
            if not cleaned:
                return "N/A"

            if currency_code_val == "CNY":
                return f"¥ {cleaned}"
            else:
                return f"{currency_code_val} {cleaned}"

        for _i, plan in enumerate(plans):
            plan_name = plan.get("plan_name", "未知套餐")
            currency_code = plan.get("currency_code", "")

            monthly_original = clean_price(plan.get("monthly_price_original", "N/A"), currency_code)
            monthly_cny = clean_price(plan.get("monthly_price_cny", "N/A"), "CNY")
            annual_original = clean_price(plan.get("annual_price_original"), currency_code)
            annual_cny = clean_price(plan.get("annual_price_cny"), "CNY")

            # 直接组装原始文本，不转义
            monthly_text = f"{monthly_original} ≈ {monthly_cny}"
            annual_text = ""
            if annual_original != "N/A" and annual_cny != "N/A":
                annual_text = f" | 年付: {annual_original} ≈ {annual_cny}"

            lines.append(f"  • {plan_name}: 月付: {monthly_text}{annual_text}")

        # 返回原始文本，不转义
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
            # 降级到原有的排序逻辑（作为备用）
            countries_with_prices = []
            for code, country_data in self.data.items():
                if code.startswith("_"):  # 跳过元数据键
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

        # 组装原始文本，不转义
        message_lines = [f"*🏆 {self.service_name} 全球最低价格排名 (基于 Premium 套餐月付)*"]
        message_lines.append("")  # Empty line after header

        for idx, country in enumerate(top_countries, 1):
            country_code_upper = country["code"].upper()
            country_flag = get_country_flag(country_code_upper)

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

            plan_details = country.get("plan_details")
            if plan_details:
                monthly_original = plan_details.get("monthly_price_original", "N/A")
                price_line = f"{monthly_original} ≈ ¥{country['price']:.2f}"
                plan_name = plan_details.get("plan_name", "Premium Plan")

                message_lines.append(f"{rank_emoji} {country['name_cn']} ({country_code_upper}) {country_flag}")
                message_lines.append(f"💰 {plan_name}: {price_line}")
                # Add blank line between countries (except handled later)
            else:
                message_lines.append(f"{rank_emoji} {country['name_cn']} ({country_code_upper}) {country_flag}")
                message_lines.append(f"💰 Premium: ¥{country['price']:.2f}")
                # Add blank line between countries (except handled later)

            # Add blank line between countries (except for the last one)
            if idx < len(top_countries):
                message_lines.append("")

        if self.cache_timestamp:
            update_time_str = datetime.fromtimestamp(self.cache_timestamp).strftime("%Y-%m-%d %H:%M:%S")
            message_lines.append("")  # Empty line before timestamp
            message_lines.append(f"⏱ 数据更新时间 (缓存)：{update_time_str}")

        # 组装完整文本，使用 foldable_text_with_markdown_v2 处理MarkdownV2格式
        body_text = "\n".join(message_lines).strip()
        return foldable_text_with_markdown_v2(body_text)

    async def query_prices(self, query_list: list[str]) -> str:
        """
        Queries prices for a list of specified countries.
        重写基类方法以支持MarkdownV2格式和国家间空行分隔。
        """
        if not self.data:
            error_message = f"❌ 错误：未能加载 {self.service_name} 价格数据。请稍后再试或检查日志。"
            return foldable_text_v2(error_message)

        result_messages = []
        not_found = []

        for query in query_list:
            # Normalize GB to UK for services that use UK
            normalized_query = "UK" if query.upper() == "GB" else query
            price_info = self.country_mapping.get(normalized_query.upper()) or self.country_mapping.get(
                normalized_query
            )

            if not price_info:
                not_found.append(query)
                continue

            # Find the primary country code for the matched data
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

        # 组装原始文本消息
        raw_message_parts = []
        raw_message_parts.append(f"*📱 {self.service_name} 订阅价格查询*")
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
            raw_message_parts.append(f"⏱ 数据更新时间 (缓存)：{update_time_str}")

        # Join and apply formatting
        raw_final_message = "\n".join(raw_message_parts).strip()
        return foldable_text_with_markdown_v2(raw_final_message)


# --- Command Handler Setup ---
disney_price_bot: DisneyPriceBot | None = None


def set_dependencies(cache_manager, rate_converter: RateConverter):
    """Initializes the DisneyPriceBot service with Redis cache manager."""
    global disney_price_bot
    disney_price_bot = DisneyPriceBot(
        service_name="Disney+",
        cache_manager=cache_manager,
        rate_converter=rate_converter,
        cache_duration_seconds=365 * 24 * 3600,  # 1年，通过定时任务清理而非过期
        subdirectory="disney_plus",
    )


async def disney_plus_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /ds command for Disney+ price queries."""
    if not disney_price_bot:
        if update.message and update.effective_chat:
            error_message = "❌ 错误：Disney+ 查询服务未初始化。"
            await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
            await delete_user_command(context, update.effective_chat.id, update.message.message_id)
        return
    await disney_price_bot.command_handler(update, context)


async def disney_plus_clean_cache_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /ds_cleancache command to clear Disney+ related caches."""
    if not disney_price_bot:
        if update.message and update.effective_chat:
            error_message = "❌ 错误：Disney+ 查询服务未初始化。"
            await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
            await delete_user_command(context, update.effective_chat.id, update.message.message_id)
        return
    return await disney_price_bot.clean_cache_command(update, context)


# Alias for the command
disney_command = disney_plus_command

# Register commands
command_factory.register_command("ds", disney_command, permission=Permission.NONE, description="Disney+订阅价格查询")
# 已迁移到统一缓存管理命令 /cleancache
# command_factory.register_command(
#     "ds_cleancache", disney_plus_clean_cache_command, permission=Permission.ADMIN, description="清理Disney+缓存"
# )
