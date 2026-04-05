# commands/apple_services_modules/service.py
"""
Apple服务价格查询的业务逻辑服务类

支持 iCloud、Apple One、Apple Music 价格查询
"""

import logging
import re

import httpx

from utils.constants import HTTP_TIMEOUT_MEDIUM
from utils.country_data import (
    SUPPORTED_COUNTRIES,
    get_country_flag,
)
from utils.price_parser import (
    extract_currency_and_price,
    extract_price_value_from_country_info,
)

from .apple_music_parser import parse_apple_music_prices
from .apple_one_parser import parse_apple_one_prices
from .icloud_parser import (
    get_icloud_prices_from_apple_website,
    get_icloud_prices_from_html,
    resolve_icloud_currency,
)

logger = logging.getLogger(__name__)

# Default search countries if none are specified by the user
DEFAULT_COUNTRIES = ["CN", "NG", "TR", "JP", "IN", "MY"]

# Apple 官网 URL 中的国家代码映射（ISO 3166 → Apple 路径）
_APPLE_URL_CC = {"GB": "uk"}


class AppleServicesService:
    """Apple服务价格查询的业务逻辑服务类"""

    def __init__(
        self,
        cache_manager,
        rate_converter,
        httpx_client,
        redis_cache_duration: int = 86400,
    ):
        """
        初始化Apple服务服务类

        Args:
            cache_manager: Redis缓存管理器
            rate_converter: 汇率转换器
            httpx_client: HTTP客户端
            redis_cache_duration: Redis缓存时长（秒）
        """
        self.cache_manager = cache_manager
        self.rate_converter = rate_converter
        self.httpx_client = httpx_client
        self.redis_cache_duration = redis_cache_duration

    @staticmethod
    def normalize_pricing_text(price_text: str) -> str:
        """Normalize pricing text to Chinese for consistent display."""
        # First check for free pricing terms in different languages
        free_terms = [
            "ücretsiz",  # Turkish
            "free",  # English
            "gratis",  # Spanish/Portuguese
            "gratuit",  # French
            "kostenlos",  # German
            "無料",  # Japanese
            "무료",  # Korean
            "免费",  # Chinese Simplified
            "免費",  # Chinese Traditional
            "مجاني",  # Arabic
            "gratuito",  # Italian
            "бесплатно",  # Russian
        ]

        price_lower = price_text.lower().strip()
        for term in free_terms:
            if term.lower() in price_lower:
                return "免费"

        # Normalize subscription periods to Chinese
        normalized_text = price_text

        # Remove duplicate period indicators (e.g., "/monthper month", "/maandper maand")
        normalized_text = re.sub(
            r"/month\s*per month", "/month", normalized_text, flags=re.IGNORECASE
        )
        normalized_text = re.sub(
            r"per month\s*/month", "per month", normalized_text, flags=re.IGNORECASE
        )
        normalized_text = re.sub(
            r"/maand\s*per maand", "/maand", normalized_text, flags=re.IGNORECASE
        )
        normalized_text = re.sub(
            r"per maand\s*/maand", "per maand", normalized_text, flags=re.IGNORECASE
        )
        normalized_text = re.sub(
            r"/jaar\s*per jaar", "/jaar", normalized_text, flags=re.IGNORECASE
        )
        normalized_text = re.sub(
            r"per jaar\s*/jaar", "per jaar", normalized_text, flags=re.IGNORECASE
        )

        # Replace various period indicators with Chinese equivalents
        period_replacements = [
            # Monthly patterns
            (r"/month", "每月"),
            (r"per month", "每月"),
            (r"\bmonth\b", "每月"),
            (r"\bayda\b", "每月"),  # Turkish
            (r"月額", "每月"),  # Japanese
            (r"월", "每月"),  # Korean
            (r"/mes", "每月"),  # Spanish
            (r"par mois", "每月"),  # French
            (r"pro Monat", "每月"),  # German
            (r"/maand", "每月"),  # Dutch
            (r"per maand", "每月"),  # Dutch
            # Yearly patterns
            (r"/year", "每年"),
            (r"per year", "每年"),
            (r"\byear\b", "每年"),
            (r"yıllık", "每年"),  # Turkish
            (r"年額", "每年"),  # Japanese
            (r"연", "每年"),  # Korean
            (r"/año", "每年"),  # Spanish
            (r"par an", "每年"),  # French
            (r"pro Jahr", "每年"),  # German
            (r"/jaar", "每年"),  # Dutch
            (r"per jaar", "每年"),  # Dutch
        ]

        for pattern, replacement in period_replacements:
            normalized_text = re.sub(
                pattern, replacement, normalized_text, flags=re.IGNORECASE
            )

        # Clean up extra whitespace
        normalized_text = re.sub(r"\s+", " ", normalized_text).strip()

        return normalized_text

    async def convert_price_to_cny(
        self, price: str, country_code: str, currency_hint: str = ""
    ) -> str:
        """Converts a price string from a given country's currency to CNY.

        Args:
            price: 原始价格文本（如 "$0.99"）
            country_code: 国家代码（如 "SR"）
            currency_hint: 解析器从页面标题提取的中文货币名（如 "美元"）
        """
        if not self.rate_converter:
            return " (汇率转换器未初始化)"

        country_info = SUPPORTED_COUNTRIES.get(country_code)
        if not country_info:
            return " (不支持的国家)"

        detected_currency, price_value = extract_currency_and_price(
            price, country_code=country_code, service="apple_services"
        )
        if price_value is None or price_value <= 0:
            return ""

        currency = resolve_icloud_currency(
            currency_hint, detected_currency, country_code
        )

        cny_price = await self.rate_converter.convert(price_value, currency, "CNY")
        if cny_price is not None:
            return f" ≈ ¥{cny_price:.2f} CNY"
        else:
            return " (汇率获取失败)"

    @staticmethod
    def parse_countries_from_args(args: list[str]) -> list[str]:
        """
        解析国家参数，支持代码、中文名称和英文全名

        支持输入:
        - 国家代码: US, TR, CN
        - 中文名称: 美国, 土耳其, 中国
        - 英文全名: USA, Turkey, China

        Args:
            args: 用户输入的参数列表

        Returns:
            list[str]: 国家代码列表（大写），如果为空则返回默认国家
        """
        from utils.country_mapper import get_country_code

        countries = []
        for arg in args:
            resolved_code = get_country_code(arg)
            if resolved_code and resolved_code not in countries:
                countries.append(resolved_code)
        return countries if countries else DEFAULT_COUNTRIES

    async def get_service_info(self, url: str, country_code: str, service: str) -> str:
        """Fetches and parses Apple service price information with caching."""
        cache_key = f"apple_services:{service}:{country_code}"
        cached_result = await self.cache_manager.load_cache(
            cache_key,
            max_age_seconds=self.redis_cache_duration,
            subdirectory="apple_services",
        )
        if cached_result:
            return cached_result

        country_info = SUPPORTED_COUNTRIES.get(country_code)
        if not country_info:
            return "不支持的国家/地区"

        flag_emoji = get_country_flag(country_code)
        service_display_name = {
            "icloud": "iCloud",
            "appleone": "Apple One",
            "applemusic": "Apple Music",
        }.get(service, service)

        logger.info(
            f"Processing request for {country_info['name']} ({country_code}), URL: {url}, Service: {service})"
        )

        # Fetch content
        content = await self._fetch_content(
            url, country_code, service, flag_emoji, country_info, service_display_name
        )
        if content is None:
            return f"📍 国家/地区: {flag_emoji} {country_info['name']}\n{service_display_name} 服务在该国家/地区不可用。"
        if isinstance(content, str) and content.startswith("📍"):
            # Error message returned
            return content

        try:
            result_lines = [f"📍 国家/地区: {flag_emoji} {country_info['name']}"]

            if service == "icloud":
                icloud_lines = await self._parse_icloud_service(
                    content, url, country_code, country_info, service_display_name
                )
                result_lines.extend(icloud_lines)
            elif service == "appleone":
                apple_one_lines = await parse_apple_one_prices(
                    content, country_code, self
                )
                result_lines.extend(apple_one_lines)
            elif service == "applemusic":
                apple_music_lines = await parse_apple_music_prices(
                    content, country_code, self
                )
                result_lines.extend(apple_music_lines)

            # Only join if there are actual price details beyond the header
            if len(result_lines) > 1:
                final_result_str = "\n".join(result_lines)
                await self.cache_manager.save_cache(
                    cache_key,
                    final_result_str,
                    subdirectory="apple_services",
                    ttl=self.redis_cache_duration,
                )
                return final_result_str
            else:
                # Return the single line message (e.g., "Not Available") without caching
                return result_lines[0]

        except Exception as e:
            logger.error(
                f"Error parsing content for {country_code}, service {service}: {e}"
            )
            return f"📍 国家/地区: {flag_emoji} {country_info['name']}\n获取价格信息失败: {e!s}."

    async def _fetch_content(
        self,
        url: str,
        country_code: str,
        service: str,
        flag_emoji: str,
        country_info: dict,
        service_display_name: str,
    ) -> str | None:
        """Fetch HTML content from URL with fallback for iCloud."""
        try:
            response = await self.httpx_client.get(url, timeout=HTTP_TIMEOUT_MEDIUM)

            if response.status_code == 404:
                logger.info(f"{service} not available in {country_code} (404).")
                if service == "icloud":
                    return await self._fetch_icloud_fallback(country_code)
                return None
            else:
                response.raise_for_status()
                return response.text

        except httpx.HTTPStatusError as e:
            logger.error(f"Network error for {url}: {e}")
            if e.response.status_code == 404 and service == "icloud":
                return await self._fetch_icloud_fallback(country_code)
            if e.response.status_code == 404:
                return None
            return f"📍 国家/地区: {flag_emoji} {country_info['name']}\n获取价格信息失败: 网络错误或请求超时 (HTTP {e.response.status_code})。"
        except httpx.RequestError as e:
            logger.error(f"Unexpected error fetching {url}: {e}")
            return f"📍 国家/地区: {flag_emoji} {country_info['name']}\n获取价格信息失败: 网络错误或请求超时。"
        except Exception as e:
            logger.error(f"Fatal error for {country_code}, service {service}: {e}")
            return f"📍 国家/地区: {flag_emoji} {country_info['name']}\n获取价格信息失败: {e!s}."

    async def _fetch_icloud_fallback(self, country_code: str) -> str | None:
        """Fetch iCloud prices from Apple Support page as fallback."""
        logger.info(
            f"Attempting iCloud fallback to Apple Support page for {country_code}"
        )
        support_url = "https://support.apple.com/zh-cn/108047"
        try:
            fallback_response = await self.httpx_client.get(
                support_url, timeout=HTTP_TIMEOUT_MEDIUM
            )
            if fallback_response.status_code == 200:
                logger.info(f"Successfully fetched fallback URL: {support_url}")
                return fallback_response.text
            return None
        except Exception as fallback_error:
            logger.error(f"Fallback request failed: {fallback_error}")
            return None

    async def _parse_icloud_service(
        self,
        content: str,
        url: str,
        country_code: str,
        country_info: dict,
        service_display_name: str,
    ) -> list[str]:
        """Parse iCloud prices from content."""
        result_lines = []

        # Try to parse as Apple website first (for country-specific URLs)
        prices = get_icloud_prices_from_apple_website(content, country_code)

        # Fallback to legacy Apple Support page format if no prices found
        if not prices:
            prices = get_icloud_prices_from_html(content)

        # If still no prices and we're not already using Apple Support, try fallback
        if not prices and "support.apple.com" not in url:
            logger.info(
                f"No prices found, attempting Apple Support fallback for {country_code}"
            )
            fallback_content = await self._fetch_icloud_fallback(country_code)
            if fallback_content:
                prices = get_icloud_prices_from_html(fallback_content)

        country_name = country_info["name"]

        # Find matching country data
        matched_country = self._find_matching_country(prices, country_name)

        if not matched_country:
            # Final fallback: try Apple Support page if we haven't already
            if "support.apple.com" not in url:
                logger.info(
                    f"Final fallback attempt: fetching Apple Support page for {country_code}"
                )
                fallback_content = await self._fetch_icloud_fallback(country_code)
                if fallback_content:
                    support_prices = get_icloud_prices_from_html(fallback_content)
                    if support_prices:
                        prices = support_prices
                        matched_country = self._find_matching_country(
                            prices, country_name
                        )

            if not matched_country:
                result_lines.append(f"{service_display_name} 服务在该国家/地区不可用。")
                return result_lines

        # Parse prices for matched country
        size_order = ["5GB", "50GB", "200GB", "2TB", "6TB", "12TB"]
        country_prices = prices[matched_country]["prices"]

        # 从解析结果中的货币名（如 "美元"）确定实际计价货币
        currency_hint = prices[matched_country].get("currency", "")

        for size in size_order:
            if size in country_prices:
                price = country_prices[size]
                # Normalize pricing text to Chinese for consistent display
                normalized_price = self.normalize_pricing_text(price)
                line = f"{size}: {normalized_price}"

                # Don't convert free plans or CNY prices
                if country_code != "CN" and normalized_price != "免费":
                    cny_price_str = await self.convert_price_to_cny(
                        price, country_code, currency_hint=currency_hint
                    )
                    line += cny_price_str
                result_lines.append(line)
            else:
                logger.warning(f"{size} plan not found for {country_name}")

        return result_lines

    @staticmethod
    def _find_matching_country(prices: dict, country_name: str) -> str | None:
        """Find matching country name in prices dict."""
        for name in prices.keys():
            # Remove footnote numbers and superscript for better matching
            clean_name = re.sub(r"[0-9,\s]+$", "", name).strip()
            # Use exact matching first, then fallback to substring matching
            if country_name == clean_name or clean_name == country_name:
                logger.info(f"Exact matched country: '{country_name}' -> '{name}'")
                return name
            elif (
                country_name in name
                and len(country_name)
                > 2  # Avoid short matches like "美" matching "美国"
                and not any(
                    other_clean
                    for other_clean in [
                        re.sub(r"[0-9,\s]+$", "", other_name).strip()
                        for other_name in prices.keys()
                        if other_name != name
                    ]
                    if country_name in other_clean and other_clean != clean_name
                )
            ):
                logger.info(f"Substring matched country: '{country_name}' -> '{name}'")
                return name
        return None

    async def command_handler(self, update, context):
        """统一的命令处理器，兼容委托模式"""
        import asyncio

        from utils.config_manager import get_config
        from utils.formatter import foldable_text_v2, foldable_text_with_markdown_v2
        from utils.message_manager import (
            _schedule_deletion,
            delete_user_command,
            send_error,
            send_help,
        )

        if not update.message or not update.effective_chat:
            return

        args = context.args
        if not args:
            help_message = (
                "🍎 *Apple 服务价格查询*\n\n"
                "**使用方法:**\n"
                "`/aps <服务类型> [国家/地区...]`\n\n"
                "**支持的服务类型:**\n"
                "• `icloud` - iCloud 存储价格\n"
                "• `appleone` - Apple One 套餐价格\n"
                "• `applemusic` - Apple Music 订阅价格\n\n"
                "**使用示例:**\n"
                "`/aps icloud` - 查询默认地区 iCloud 价格\n"
                "`/aps applemusic US JP CN` - 查询美国、日本、中国的 Apple Music 价格\n"
                "`/aps appleone 中国 美国` - 支持中文国家名称\n\n"
                "💡 不指定国家时使用默认地区：中国、尼日利亚、土耳其、日本、印度、马来西亚"
            )
            await send_help(
                context,
                update.effective_chat.id,
                foldable_text_with_markdown_v2(help_message),
                parse_mode="MarkdownV2",
            )
            await delete_user_command(
                context, update.effective_chat.id, update.message.message_id
            )
            return

        loading_message = "🔍 正在查询中... ⏳"
        message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=foldable_text_v2(loading_message),
            parse_mode="MarkdownV2",
        )

        service_type = args[0].lower()
        if service_type not in ["icloud", "appleone", "applemusic"]:
            invalid_service_message = (
                "无效的服务类型，请使用 iCloud, Apple One 或 AppleMusic"
            )
            await message.delete()
            await send_error(
                context,
                update.effective_chat.id,
                foldable_text_v2(invalid_service_message),
                parse_mode="MarkdownV2",
            )
            await delete_user_command(
                context, update.effective_chat.id, update.message.message_id
            )
            return

        try:
            countries = self.parse_countries_from_args(args[1:])

            display_name = ""
            if service_type == "icloud":
                display_name = "iCloud"
            elif service_type == "appleone":
                display_name = "Apple One"
            else:  # service_type == "applemusic"
                display_name = "Apple Music"

            tasks = []
            for country in countries:
                url = ""
                # Apple 官网使用 /uk/ 而非 /gb/
                url_cc = _APPLE_URL_CC.get(country, country).lower()
                if service_type == "icloud":
                    if country == "US":
                        url = "https://www.apple.com/icloud/"
                    elif country == "CN":
                        url = "https://www.apple.com.cn/icloud/"
                    else:
                        url = f"https://www.apple.com/{url_cc}/icloud/"
                elif country == "US":
                    url = f"https://www.apple.com/{service_type}/"
                elif country == "CN" and service_type == "appleone":
                    url = "https://www.apple.com.cn/apple-one/"
                elif country == "CN" and service_type == "applemusic":
                    url = "https://www.apple.com.cn/apple-music/"
                else:
                    url = f"https://www.apple.com/{url_cc}/{service_type}/"
                tasks.append(self.get_service_info(url, country, service_type))

            country_results = await asyncio.gather(*tasks)

            # 组装原始文本消息
            raw_message_parts = []
            raw_message_parts.append(f"*📱 {display_name} 价格信息*")
            raw_message_parts.append("")

            valid_results = [result for result in country_results if result]
            if valid_results:
                for i, result in enumerate(valid_results):
                    raw_message_parts.append(result)
                    if i < len(valid_results) - 1:
                        raw_message_parts.append("")
            else:
                raw_message_parts.append("所有查询地区均无此服务。")

            raw_final_message = "\n".join(raw_message_parts).strip()

            await message.edit_text(
                foldable_text_with_markdown_v2(raw_final_message),
                parse_mode="MarkdownV2",
                disable_web_page_preview=True,
            )

            config = get_config()
            await _schedule_deletion(
                context,
                update.effective_chat.id,
                message.message_id,
                delay=config.auto_delete_delay,
            )
            await delete_user_command(
                context, update.effective_chat.id, update.message.message_id
            )

        except Exception as e:
            logger.error(
                f"Unexpected error in apple_services_command: {e}", exc_info=True
            )
            error_message = f"处理请求时发生错误: {e!s}"
            try:
                await message.edit_text(
                    foldable_text_v2(error_message), parse_mode="MarkdownV2"
                )
            except Exception as edit_error:
                logger.error(f"Error editing message: {edit_error}")
                await message.delete()
                await send_error(
                    context,
                    update.effective_chat.id,
                    foldable_text_v2(error_message),
                    parse_mode="MarkdownV2",
                )
            await delete_user_command(
                context, update.effective_chat.id, update.message.message_id
            )

    async def clean_cache_command(self, update, context):
        """统一的缓存清理命令处理器"""
        from utils.formatter import foldable_text_v2
        from utils.message_manager import delete_user_command, send_error, send_success

        if not update.message or not update.effective_chat:
            return

        try:
            self.cache_manager.clear_cache(subdirectory="apple_services")
            success_message = "✅ Apple 服务价格缓存已清理。"
            await send_success(
                context,
                update.effective_chat.id,
                foldable_text_v2(success_message),
                parse_mode="MarkdownV2",
            )
            await delete_user_command(
                context, update.effective_chat.id, update.message.message_id
            )
        except Exception as e:
            logger.error(f"Error clearing Apple Services cache: {e}")
            error_message = f"❌ 清理Apple Services缓存时发生错误: {e!s}"
            await send_error(
                context,
                update.effective_chat.id,
                foldable_text_v2(error_message),
                parse_mode="MarkdownV2",
            )
            await delete_user_command(
                context, update.effective_chat.id, update.message.message_id
            )
