# Description: Telegram bot commands for Steam game and bundle price lookup.
# This module integrates functionality from the original steam.py script.
# type: ignore

import asyncio
import json
import logging
import re
from urllib.parse import quote

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

# Note: CacheManager import removed - now uses injected Redis cache manager from main.py
from utils.command_factory import command_factory
from utils.config_manager import config_manager
from utils.country_data import SUPPORTED_COUNTRIES, get_country_flag
from utils.formatter import foldable_text_v2, foldable_text_with_markdown_v2
from utils.message_manager import delete_user_command, send_error, send_help, send_search_result, send_success, send_message_with_auto_delete, MessageType
from utils.permissions import Permission
from utils.rate_converter import RateConverter
from utils.session_manager import steam_bundle_sessions as bundle_search_sessions
from utils.session_manager import steam_search_sessions as user_search_sessions


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def format_steam_search_results(search_data: dict) -> str:
    """格式化Steam搜索结果消息"""
    if search_data.get("error"):
        return f"❌ 搜索失败: {search_data['error']}"

    results = search_data["results"]
    query = search_data["query"]
    country_inputs = search_data.get("country_inputs", ["CN"])
    current_country = country_inputs[0] if country_inputs else "CN"

    if not results:
        return f"🔍 在 {current_country.upper()} 区域没有找到关键词 '{query}' 的相关内容"

    # 获取国家标志和名称
    country_flag = get_country_flag(current_country)
    country_info = SUPPORTED_COUNTRIES.get(current_country, {"name": current_country})
    country_name = country_info.get("name", current_country)

    total_results = search_data.get("total_results", len(results))
    current_page = search_data.get("current_page", 1)
    total_pages = search_data.get("total_pages", 1)

    header_parts = [
        "🎮 Steam搜索结果",
        f"🔍 关键词: {query}",
        f"🌍 搜索地区: {country_flag} {country_name} ({current_country.upper()})",
        f"📊 找到 {total_results} 个结果 (第 {current_page}/{total_pages} 页)",
        "",
        "请从下方选择您要查询的内容："
    ]

    return "\n".join(header_parts)

def create_steam_search_keyboard(search_data: dict) -> InlineKeyboardMarkup:
    """创建Steam搜索结果的内联键盘"""
    keyboard = []

    # 游戏选择按钮 (每行显示一个游戏)
    results = search_data["results"]
    # 只显示前5个结果
    for i in range(min(len(results), 5)):
        game = results[i]
        game_name = game.get("name", "未知游戏")
        game_type = game.get("type", "game")  # 获取类型信息

        # 根据类型添加前缀标识
        if game_type == "bundle":
            type_icon = "🛍"
        elif game_type == "dlc":
            type_icon = "📦"
        else:
            type_icon = "🎮"

        # 截断过长的游戏名称
        if len(game_name) > 37:  # 为类型图标留出空间
            game_name = game_name[:34] + "..."

        callback_data = f"steam_select_{i}_{search_data.get('current_page', 1)}"
        display_name = f"{i + 1}. {type_icon} {game_name}"
        keyboard.append([InlineKeyboardButton(display_name, callback_data=callback_data)])

    # 分页控制
    current_page = search_data.get("current_page", 1)
    total_pages = search_data.get("total_pages", 1)

    nav_row = []
    if current_page > 1:
        nav_row.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"steam_page_{current_page - 1}"))

    nav_row.append(InlineKeyboardButton(f"📄 {current_page}/{total_pages}", callback_data="steam_page_info"))

    if current_page < total_pages:
        nav_row.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"steam_page_{current_page + 1}"))

    if nav_row:
        keyboard.append(nav_row)

    # 操作按钮
    action_row = [
        InlineKeyboardButton("🌍 更改搜索地区", callback_data="steam_change_region"),
        InlineKeyboardButton("❌ 关闭", callback_data="steam_close")
    ]
    keyboard.append(action_row)

    return InlineKeyboardMarkup(keyboard)


def set_cache_manager(manager):
    global cache_manager
    cache_manager = manager
rate_converter = None # Will be initialized in main.py and passed via context

def set_rate_converter(converter: RateConverter):
    global rate_converter
    rate_converter = converter

class Config:
    """Configuration class for Steam module."""
    DEFAULT_CC = "CN"
    DEFAULT_LANG = "schinese"
    MAX_SEARCH_RESULTS = 20
    MAX_BUNDLE_RESULTS = 10
    MAX_SEARCH_ITEMS = 15
    REQUEST_DELAY = 1.0  # Delay between requests to avoid rate limiting

    @property
    def PRICE_CACHE_DURATION(self):
        return config_manager.config.steam_cache_duration

class ErrorHandler:
    """Handles errors and formats messages."""
    @staticmethod
    def log_error(error: Exception, context: str = "") -> str:
        logger.error(f"Error in {context}: {error}")
        return f"❌ {context}失败: {error!s}"

    @staticmethod
    def handle_network_error(error: Exception) -> str:
        if "timeout" in str(error).lower():
            return "❌ 请求超时，请稍后重试"
        elif "connection" in str(error).lower():
            return "❌ 网络连接失败，请检查网络"
        else:
            return f"❌ 网络请求失败: {error!s}"

class SteamPriceChecker:
    """Main class for Steam price checking functionality."""
    def __init__(self):
        self.config = Config()
        self.error_handler = ErrorHandler()

        # Currency symbol to code mapping (extended from original scripts)
        # Note: ¥ can be both JPY and CNY, handled separately in detect_currency_from_context
        self.currency_symbol_to_code = {
            "$": "USD", "USD": "USD", "€": "EUR", "£": "GBP", "₩": "KRW",
            "₺": "TRY", "₽": "RUB", "₹": "INR", "₫": "VND", "฿": "THB", "₱": "PHP",
            "₦": "NGN", "₴": "UAH", "₲": "PYG", "₪": "ILS", "₡": "CRC", "₸": "KZT",
            "₮": "MNT", "៛": "KHR", "CFA": "XOF", "FCFA": "XAF", "S/": "PEN",
            "Rs": "LKR", "NZ$": "NZD", "A$": "AUD", "C$": "CAD", "HK$": "HKD",
            "NT$": "TWD", "R$": "BRL", "RM": "MYR", "Rp": "IDR", "Bs.": "VES",
            "лв": "BGN", "S$": "SGD", "kr": "NOK", "₼": "AZN", "￥": "CNY",
            "Ft": "HUF", "zł": "PLN", "Kč": "CZK", "лев": "BGN", "lei": "RON"
        }

        # Currency multipliers
        self.currency_multipliers = {'ribu': 1000, 'juta': 1000000, 'k': 1000, 'thousand': 1000}

        # 延迟初始化缓存
        self.game_id_cache = None
        self.bundle_id_cache = None
        self._cache_initialized = False

    async def _ensure_cache_initialized(self):
        """确保缓存已初始化"""
        if not self._cache_initialized:
            self.game_id_cache = await cache_manager.load_cache("steam_game_ids", subdirectory="steam") or {}
            self.bundle_id_cache = await cache_manager.load_cache("steam_bundle_ids", subdirectory="steam") or {}
            self._cache_initialized = True

    async def _save_game_id_cache(self):
        await cache_manager.save_cache("steam_game_ids", self.game_id_cache, subdirectory="steam")

    async def _save_bundle_id_cache(self):
        await cache_manager.save_cache("steam_bundle_ids", self.bundle_id_cache, subdirectory="steam")

    def detect_currency_from_context(self, currency_symbol: str, price_str: str, country_code: str = None) -> str:
        """智能检测货币代码，特别处理¥符号的JPY/CNY冲突"""
        if currency_symbol == "¥":
            # 优先级1: 根据国家代码判断
            if country_code:
                if country_code in ["CN", "HK", "TW", "MO"]:  # 中国相关地区
                    return "CNY"
                elif country_code == "JP":  # 日本
                    return "JPY"

            # 优先级2: 根据价格文本内容判断
            price_lower = price_str.lower()

            # 中文相关关键词倾向CNY
            if any(keyword in price_lower for keyword in ["人民币", "元", "rmb", "cny", "中国", "cn"]):
                return "CNY"

            # 日文相关关键词倾向JPY
            if any(keyword in price_lower for keyword in ["円", "yen", "jpy", "日本", "jp"]):
                return "JPY"

            # 优先级3: 根据价格数值范围启发式判断
            # 提取数值进行分析
            import re
            numbers = re.findall(r'\d+', price_str)
            if numbers:
                max_num = max(int(num) for num in numbers)
                # 日元通常数值较大（比如：¥1980），人民币相对较小（比如：¥29.8）
                if max_num >= 500:
                    return "JPY"  # 大数值倾向日元
                elif max_num <= 100:
                    return "CNY"  # 小数值倾向人民币

            # 默认情况：由于Steam主要面向中国用户，默认CNY
            return "CNY"

        # 其他货币符号直接查表
        return self.currency_symbol_to_code.get(currency_symbol, "USD")

    def extract_currency_and_price(self, price_str: str, country_code: str = None) -> tuple[str, float]:
        """Extracts currency code and numerical price from a price string."""
        if not price_str or price_str == '未知' or price_str.lower() == 'free' or '免费' in price_str:
            return "USD", 0.0

        price_str = price_str.replace('\xa0', ' ').strip()

        currency_symbols_and_codes = set(self.currency_symbol_to_code.keys())
        # 添加¥符号用于检测
        currency_symbols_and_codes.add("¥")
        currency_patterns = sorted(currency_symbols_and_codes, key=len, reverse=True)
        currency_patterns_escaped = [re.escape(cp) for cp in currency_patterns]
        currency_pattern_str = '|'.join(currency_patterns_escaped)

        patterns = [
            rf"^(?P<currency>{currency_pattern_str})\s*(?P<amount>.*?)$",
            rf"^(?P<amount>.*?)\s*(?P<currency>{currency_pattern_str})$",
        ]

        currency_part = None
        amount_part = price_str

        for p_str in patterns:
            match = re.match(p_str, price_str)
            if match:
                potential_amount = match.group('amount').strip()
                if re.search(r'\d', potential_amount):
                    currency_part = match.group('currency')
                    amount_part = potential_amount
                    break

        if currency_part:
            # 使用智能检测处理¥符号冲突
            detected_currency_code = self.detect_currency_from_context(currency_part, price_str, country_code)
        else:
            detected_currency_code = "USD"

        multiplier = 1
        for key, value in sorted(self.currency_multipliers.items(), key=lambda x: len(x[0]), reverse=True):
            if amount_part.lower().endswith(key):
                multiplier = value
                amount_part = amount_part[:-len(key)].strip()
                break

        price_value = None
        if amount_part:
            amount_cleaned = re.sub(r'[^\d.,]', '', amount_part)
            decimal_match = re.search(r'[.,](\d{1,2})$', amount_cleaned)
            if decimal_match:
                decimal_part = decimal_match.group(1)
                integer_part = amount_cleaned[:decimal_match.start()].replace(',', '').replace('.', '')
                final_num_str = f"{integer_part}.{decimal_part}"
            else:
                final_num_str = amount_cleaned.replace(',', '').replace('.', '')

            try:
                price_value = float(final_num_str) * multiplier
            except ValueError:
                logger.warning(f"Price parsing failed: '{price_str}' -> '{final_num_str}'")
                price_value = 0.0
        else:
            price_value = 0.0

        return detected_currency_code, price_value

    def _escape_markdown(self, text: str) -> str:
        """Escapes markdown special characters in text for MarkdownV2."""
        # Use the same smart formatter as app_store.py
        from utils.formatter import escape_v2
        return escape_v2(text)

    def get_country_code(self, country_input: str) -> str | None:
        """Converts country input (Chinese name or code) to country code."""
        country = country_input.upper()
        if country in SUPPORTED_COUNTRIES:
            return country

        for code, info in SUPPORTED_COUNTRIES.items():
            if country_input == info["name"]:
                return code

        return None

    async def search_game(self, query: str, cc: str, use_cache: bool = True) -> list[dict]:
        """Searches for games on Steam and returns a list of results."""
        await self._ensure_cache_initialized()
        query_lower = query.lower()

        if use_cache and query_lower in self.game_id_cache:
            app_id = self.game_id_cache[query_lower]
            return [{'id': app_id, 'name': query, 'type': 'game'}]

        encoded_query = quote(query)
        url = f"https://store.steampowered.com/api/storesearch/?term={encoded_query}&l={self.config.DEFAULT_LANG}&cc={cc}"

        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
            async with httpx.AsyncClient(headers=headers) as client:
                response = await client.get(url, follow_redirects=True, timeout=10)
                response.raise_for_status()
                data = response.json()

            items = data.get('items', [])

            # 为每个项目添加类型信息
            for item in items:
                item_type = item.get('type', 'game').lower()
                if 'bundle' in item_type or 'package' in item_type:
                    item['type'] = 'bundle'
                elif 'dlc' in item_type or 'downloadable content' in item_type:
                    item['type'] = 'dlc'
                else:
                    item['type'] = 'game'

            if items and use_cache:
                self.game_id_cache[query_lower] = items[0].get('id')
                await self._save_game_id_cache()

            return items
        except httpx.RequestError as e:
            logger.error(f"Error searching game: {e}")
            return []
        except json.JSONDecodeError:
            logger.error("JSON decode error during game search.")
            return []

    async def get_game_details(self, app_id: str, cc: str) -> dict:
        """Fetches game details from Steam API."""
        cache_key = f"steam_game_details_{app_id}_{cc}"
        cached_data = await cache_manager.load_cache(cache_key, max_age_seconds=self.config.PRICE_CACHE_DURATION, subdirectory="steam")
        if cached_data:
            return cached_data

        url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&cc={cc}&l={self.config.DEFAULT_LANG}"
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
            async with httpx.AsyncClient(headers=headers) as client:
                response = await client.get(url, follow_redirects=True, timeout=10)
                response.raise_for_status()
                data = response.json()

            result = data.get(str(app_id), {})

            if result.get('success'):
                await cache_manager.save_cache(cache_key, result, subdirectory="steam")

            return result
        except httpx.RequestError as e:
            logger.error(f"Error getting game details: {e}")
            return {}
        except json.JSONDecodeError:
            logger.error("JSON decode error during game details fetch.")
            return {}

    async def search_bundle_by_id(self, bundle_id: str, cc: str) -> dict | None:
        """Searches for a bundle by ID and returns its details."""
        return await self.get_bundle_details(bundle_id, cc)

    async def search_bundle(self, query: str, cc: str) -> list[dict]:
        """Searches for bundles on Steam and returns a list of results."""
        await self._ensure_cache_initialized()
        query_lower = query.lower()

        if query_lower in self.bundle_id_cache:
            cached_bundle = self.bundle_id_cache[query_lower]
            return [{
                'id': cached_bundle['id'],
                'name': cached_bundle['name'],
                'url': f"https://store.steampowered.com/bundle/{cached_bundle['id']}",
                'score': 100
            }]

        encoded_query = quote(query)
        url = f"https://store.steampowered.com/search/results?term={encoded_query}&l={self.config.DEFAULT_LANG}&cc={cc}&category1=996&json=1"

        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
            async with httpx.AsyncClient(headers=headers) as client:
                response = await client.get(url, follow_redirects=True, timeout=10)
                response.raise_for_status()
                data = response.json()

            items = data.get('items', [])
            bundle_items = []

            for item in items:
                item_name = item.get('name', '').lower()

                if query_lower in item_name or item_name in query_lower:
                    logo_url = item.get('logo', '')
                    bundle_match = re.search(r'/bundles/(\d+)/', logo_url)
                    if bundle_match:
                        bundle_id = bundle_match.group(1)
                        name = item.get('name', '未知捆绑包')
                        bundle_items.append({
                            'id': bundle_id,
                            'name': name,
                            'url': f"https://store.steampowered.com/bundle/{bundle_id}",
                            'score': len(set(query_lower) & set(item_name))
                        })

                        self.bundle_id_cache[item_name.lower()] = {
                            'id': bundle_id,
                            'name': name
                        }

            if bundle_items:
                await self._save_bundle_id_cache()

            bundle_items.sort(key=lambda x: x['score'], reverse=True)
            return bundle_items[:1] if bundle_items else []

        except httpx.RequestError as e:
            logger.error(f"Error searching bundle: {e}")
            return []
        except json.JSONDecodeError:
            logger.error("JSON decode error during bundle search.")
            return []

    async def get_bundle_details(self, bundle_id: str, cc: str) -> dict | None:
        """Fetches bundle details from Steam store page."""
        cache_key = f"steam_bundle_details_{bundle_id}_{cc}"
        cached_data = await cache_manager.load_cache(cache_key, max_age_seconds=self.config.PRICE_CACHE_DURATION, subdirectory="steam")
        if cached_data:
            return cached_data

        url = f"https://store.steampowered.com/bundle/{bundle_id}?cc={cc}&l=schinese"
        headers = {
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Cookie": "steamCountry=CN%7C5a92c37537078a8cc660c6be649642b2; timezoneOffset=28800,0; birthtime=946656001; lastagecheckage=1-January-2000"
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, follow_redirects=True, timeout=10)
                response.raise_for_status()
                content = response.text

            name_match = re.search(r'<h2[^>]*class="[^"]*pageheader[^"]*"[^>]*>(.*?)</h2>', content, re.DOTALL)
            bundle_name = name_match.group(1).strip() if name_match else "未知捆绑包"

            games = []
            for game_match in re.finditer(r'<div class="tab_item.*?tab_item_name">(.*?)</div>.*?discount_final_price">(.*?)</div>', content, re.DOTALL):
                game_name = game_match.group(1).strip()
                game_price = game_match.group(2).strip()
                games.append({
                    'name': game_name,
                    'price': {'final_formatted': game_price}
                })

            price_info = {
                'original_price': '未知',
                'discount_pct': '0',
                'final_price': '未知',
                'savings': '0'
            }

            price_block = re.search(r'<div class="package_totals_area.*?</div>\s*</div>', content, re.DOTALL)
            if price_block:
                price_content = price_block.group(0)

                original_match = re.search(r'bundle_final_package_price">([^<]+)</div>', price_content)
                if original_match:
                    price_info['original_price'] = original_match.group(1).strip()

                discount_match = re.search(r'bundle_discount">([^<]+)</div>', price_content)
                if discount_match:
                    discount = discount_match.group(1).strip().replace('%', '').replace('-', '')
                    price_info['discount_pct'] = discount

                final_match = re.search(r'bundle_final_price_with_discount">([^<]+)</div>', price_content)
                if final_match:
                    price_info['final_price'] = final_match.group(1).strip()

                savings_match = re.search(r'bundle_savings">([^<]+)</div>', price_content)
                if savings_match:
                    price_info['savings'] = savings_match.group(1).strip()

            bundle_data = {
                'name': bundle_name,
                'url': url,
                'items': games,
                'original_price': price_info['original_price'],
                'discount_pct': price_info['discount_pct'],
                'final_price': price_info['final_price'],
                'savings': price_info['savings']
            }

            await cache_manager.save_cache(cache_key, bundle_data, subdirectory="steam")

            return bundle_data

        except httpx.RequestError as e:
            logger.error(f"Error getting bundle details: {e}")
            return None
        except Exception as e:
            logger.error(f"Unknown error getting bundle details: {e}")
            return None

    async def format_bundle_info(self, bundle_data: dict, cc: str) -> str:
        """Formats bundle information, including price conversion to CNY."""
        if not bundle_data:
            return "❌ 无法获取捆绑包信息"

        # —— 国区不做任何额外换算 ——
        if cc.upper() == "CN":
            # 全部按照 API 原生的 final_price、original_price、savings 直接展示即可
            final = bundle_data.get('final_price', '未知')
            original = bundle_data.get('original_price', '未知')
            discount = bundle_data.get('discount_pct', '0')
            savings = bundle_data.get('savings', '0')
            text = [
                f"🎮 {bundle_data['name']}",
                f"🔗 链接：{bundle_data['url']}",
                f"💵 优惠价: {final}",
                f"💰 原价: {original}" if original and original != final else "",
                f"🛍 折扣: -{discount}%" if discount != "0" else "",
                f"📉 共节省: {savings}" if savings not in ("0", "未知") else ""
            ]
            # 包含内容直接附上，不做汇率转换
            if bundle_data.get('items'):
                text.append("\n🎮 包含内容:")
                for it in bundle_data['items']:
                    text.append(f"• {it['name']} - {it['price']['final_formatted']}")
            return "\n".join([t for t in text if t])

        if not rate_converter:
            return "❌ 汇率转换器未初始化，无法格式化价格。"

        result = []

        result.append(f"🎮 {bundle_data['name']}")
        result.append(f"🔗 链接：{bundle_data['url']}")
        result.append(f"🌍 查询地区: {get_country_flag(cc)} {cc}")

        final_price_str = bundle_data.get('final_price', '未知')
        original_price_str = bundle_data.get('original_price', '未知')
        savings_str = bundle_data.get('savings', '0')
        discount_pct = bundle_data.get('discount_pct', '0')

        final_currency_code, final_price_num = self.extract_currency_and_price(final_price_str, cc)
        final_price_display = final_price_str

        if final_price_num == 0.0:
            final_price_display = "🆓 免费"
        elif final_price_num > 0 and final_currency_code != 'CNY':
            final_cny = await rate_converter.convert(final_price_num, final_currency_code, "CNY")
            if final_cny is not None:
                final_price_display = f"{final_price_str} ( ≈ ¥{final_cny:.2f} CNY )"

        original_currency_code, original_price_num = self.extract_currency_and_price(original_price_str, cc)
        original_price_display = original_price_str
        if original_price_num > 0 and original_currency_code != 'CNY' and original_price_num != final_price_num:
            original_cny = await rate_converter.convert(original_price_num, original_currency_code, "CNY")
            if original_cny is not None:
                original_price_display = f"{original_price_str} ( ≈ ¥{original_cny:.2f} CNY )"

        savings_currency_code, savings_num = self.extract_currency_and_price(savings_str, cc)
        savings_display = savings_str
        if savings_num > 0 and savings_currency_code != 'CNY':
            savings_cny = await rate_converter.convert(savings_num, savings_currency_code, "CNY")
            if savings_cny is not None:
                savings_display = f"{savings_str} ( ≈ ¥{savings_cny:.2f} CNY )"

        if final_price_num == 0.0:
            result.append("\n🆓 免费")
        elif final_price_num > 0:
            result.append(f"\n💵 优惠价: {final_price_display}")
            if original_price_num > 0 and original_price_num != final_price_num and original_price_display != '未知':
                result.append(f"💰   原价: {original_price_display}")

        if discount_pct and discount_pct != '0':
            result.append(f"🛍 捆绑包额外折扣: -{discount_pct}%")

        if savings_num > 0 and savings_display != '未知' and savings_display != '0':
            result.append(f"📉 共节省: {savings_display}")

        if bundle_data.get('items'):
            result.append("\n🎮 包含内容:")
            for item in bundle_data['items']:
                price_item_str = item.get('price', {}).get('final_formatted', '未知价格')
                item_name = item.get('name', '未知项目')
                result.append(f"• 📄 {item_name} - {price_item_str}")

        from utils.formatter import foldable_text_with_markdown_v2
        full_message = "\n".join(result)
        # The calling function will apply proper formatting
        return full_message

    async def format_price_with_cny(self, price_info: dict, country_currency: str, country_code: str = None) -> str:
        """Formats price information and adds CNY conversion."""
        if not price_info:
            return "❓ 暂无价格信息"

        if price_info.get('is_free'):
            return "🆓 免费游戏"

        if not rate_converter:
            return "❌ 汇率转换器未初始化，无法格式化价格。"

        initial_price = price_info.get('initial_formatted', '未知原价')
        final_price = price_info.get('final_formatted', '未知价格')
        currency = price_info.get('currency', country_currency)

        initial_num = price_info.get('initial', 0) / 100.0
        final_num = price_info.get('final', 0) / 100.0

        # 获取当前地区代码，如果是中国地区则不显示汇率转换
        cc = country_code or country_currency

        # 智能格式化价格
        def format_currency_price(amount, curr_code, c_code):
            from utils.country_data import SUPPORTED_COUNTRIES
            country_data = SUPPORTED_COUNTRIES.get(c_code, {"currency": "USD", "symbol": "$"})
            if curr_code == country_data["currency"]:
                return f"{country_data['symbol']}{amount:.2f}"
            currency_symbols = {"USD": "$", "EUR": "€", "GBP": "£", "CNY": "¥", "JPY": "¥"}
            symbol = currency_symbols.get(curr_code, "$")
            return f"{symbol}{amount:.2f}"

        if currency != 'CNY' and cc != 'CN' and rate_converter and rate_converter.rates and currency in rate_converter.rates:
            initial_cny = await rate_converter.convert(initial_num, currency, "CNY")
            final_cny = await rate_converter.convert(final_num, currency, "CNY")

            if initial_cny is not None and final_cny is not None:
                initial_with_cny = f"{format_currency_price(initial_num, currency, cc)} - ¥{initial_cny:.2f}CNY"
                final_with_cny = f"{format_currency_price(final_num, currency, cc)} - ¥{final_cny:.2f}CNY"
            else:
                initial_with_cny = format_currency_price(initial_num, currency, cc)
                final_with_cny = format_currency_price(final_num, currency, cc)
        else:
            initial_with_cny = format_currency_price(initial_num, currency, cc)
            final_with_cny = format_currency_price(final_num, currency, cc)

        discount = price_info.get('discount_percent', 0)

        if discount > 0:
            return f"💵 价格: {final_with_cny} ⬇️ (-{discount}%)\n💰   原价: {initial_with_cny}"
        return f"💵 价格: {final_with_cny}"

    async def format_game_info(self, game_data: dict, cc: str) -> str:
        """Formats game information for display."""
        if not game_data.get('success'):
            return "❌ 无法获取游戏信息"

        data = game_data.get('data', {})
        name = data.get('name', '未知游戏')
        price_info = data.get('price_overview', {})
        app_id = data.get('steam_appid')

        country_info = SUPPORTED_COUNTRIES.get(cc, {"name": cc})

        store_url = f"https://store.steampowered.com/app/{app_id}/_/"

        currency = price_info.get('currency', cc)

        result = [
            f"🎮 {name} - [Store Page]({store_url})",
            f"🔑 Steam ID: `{app_id}`",
            f"🌍 国家/地区: {get_country_flag(cc)} {country_info['name']} ({cc})",
            await self.format_price_with_cny(price_info, currency, cc)
        ]

        package_groups = data.get('package_groups', [])
        purchase_options = []
        if package_groups:
            for group in package_groups:
                subs = group.get('subs', [])
                for package in subs:
                    option_text = re.sub(r'<.*?>', '', package.get('option_text', '未知包裹'))
                    is_free_license = package.get('is_free_license', False)
                    package_final_price_cents = package.get('price_in_cents_with_discount', 0)
                    main_final_price_cents = price_info.get('final', 0)

                    # 智能识别内容类型
                    option_text_lower = option_text.lower()
                    content_type = ""
                    if any(keyword in option_text_lower for keyword in ['dlc', 'downloadable content', '可下载内容']):
                        content_type = "📦"
                    elif any(keyword in option_text_lower for keyword in ['season pass', '季票', 'season']):
                        content_type = "🎫"
                    elif any(keyword in option_text_lower for keyword in ['bundle', 'pack', '捆绑包', '包装']):
                        content_type = "🛍"
                    elif any(keyword in option_text_lower for keyword in ['expansion', '扩展包', 'addon']):
                        content_type = "🎮"
                    elif any(keyword in option_text_lower for keyword in ['deluxe', 'premium', 'gold', 'ultimate', '豪华版', '黄金版']):
                        content_type = "💎"
                    elif any(keyword in option_text_lower for keyword in ['soundtrack', 'ost', '原声', '音轨']):
                        content_type = "🎵"
                    else:
                        content_type = "🎯"

                    # 显示所有非基础游戏的购买选项，除非是完全相同的内容
                    should_show = True

                    # 如果价格相同且是基础游戏名称，则跳过（避免重复显示主游戏）
                    if (package_final_price_cents == main_final_price_cents and
                        (option_text == data.get('name', '') or
                         '游戏本体' in option_text_lower or
                         'base game' in option_text_lower)):
                        should_show = False

                    if should_show:
                        if is_free_license:
                            purchase_options.append(f"• 🆓 {option_text} - 免费")
                        elif package_final_price_cents > 0:
                            package_price_num = package_final_price_cents / 100.0
                            package_currency = package.get('currency', currency)

                            # 清理option_text，移除HTML标签和内嵌的价格信息
                            clean_option_text = re.sub(r'<.*?>', '', option_text)
                            
                            # 移除各种可能的价格格式
                            clean_name = clean_option_text
                            
                            # 1. 移除尾部的单个价格: "Game Name - $19.99"
                            clean_name = re.sub(r'\s*-\s*[\$¥€£₹₽₩￥R][A-Z]*\s*[\d.,]+\s*$', '', clean_name)
                            
                            # 2. 移除多个价格（原价+现价）: "Game Name - $39.99 $19.99" 或 "Game Name RM61.00 RM15.25"
                            clean_name = re.sub(r'\s*[\$¥€£₹₽₩￥R][A-Z]*\s*[\d.,]+\s+[\$¥€£₹₽₩￥R][A-Z]*\s*[\d.,]+\s*$', '', clean_name)
                            
                            # 3. 移除单独的价格: "Game Name $19.99"
                            clean_name = re.sub(r'\s+[\$¥€£₹₽₩￥R][A-Z]*\s*[\d.,]+\s*$', '', clean_name)
                            
                            # 4. 移除括号内的价格: "Game Name ($19.99)"
                            clean_name = re.sub(r'\s*\(\s*[\$¥€£₹₽₩￥R][A-Z]*\s*[\d.,]+\s*\)\s*$', '', clean_name)
                            
                            # 5. 移除连续的多个价格格式（如Steam打折显示）
                            clean_name = re.sub(r'\s*[\$¥€£₹₽₩￥R][A-Z]*\s*[\d.,]+(?:\s+[\$¥€£₹₽₩￥R][A-Z]*\s*[\d.,]+)*\s*$', '', clean_name)
                            
                            clean_name = clean_name.strip()

                            # 智能价格格式化：根据地区使用正确的货币格式
                            def format_local_price(amount, currency_code, country_code):
                                """根据地区格式化价格"""
                                from utils.country_data import SUPPORTED_COUNTRIES
                                country_info = SUPPORTED_COUNTRIES.get(country_code, {"currency": "USD", "symbol": "$"})

                                # 如果包货币与地区货币匹配，使用地区符号
                                if currency_code == country_info["currency"]:
                                    return f"{country_info['symbol']}{amount:.2f}"

                                # 否则根据货币代码使用相应符号
                                currency_symbols = {"USD": "$", "EUR": "€", "GBP": "£", "CNY": "¥", "JPY": "¥"}
                                symbol = currency_symbols.get(currency_code, "$")
                                return f"{symbol}{amount:.2f}"

                            price_display = format_local_price(package_price_num, package_currency, cc)

                            # 如果不是中国地区且不是人民币，添加人民币汇率转换
                            if cc != 'CN' and package_currency != 'CNY' and rate_converter and rate_converter.rates and package_currency in rate_converter.rates:
                                cny_price = await rate_converter.convert(package_price_num, package_currency, "CNY")
                                if cny_price is not None:
                                    price_display += f" (约 ¥{cny_price:.2f} CNY)"

                            purchase_options.append(f"• {content_type} {clean_name} - {price_display}")
                        else:
                            # 价格为0但不是免费许证的情况
                            purchase_options.append(f"• {content_type} {option_text} (暂无价格信息)")

        if purchase_options:
            result.append("🛒 购买选项:")
            result.extend(purchase_options)

        from utils.formatter import foldable_text_with_markdown_v2
        full_message = "\n".join(result)
        # The calling function will apply proper formatting
        return full_message

    def _select_best_match(self, search_results: list[dict], query: str) -> dict:
        """智能选择最匹配的游戏结果"""
        if not search_results:
            return {}

        if len(search_results) == 1:
            return search_results[0]

        query_lower = query.lower()

        # 计算每个结果的匹配分数
        scored_results = []
        for result in search_results:
            name = result.get('name', '').lower()
            score = 0

            # 完全匹配得分最高
            if name == query_lower:
                score += 1000

            # 包含查询词得分
            if query_lower in name:
                score += 500

            # 查询词包含在名称中得分
            if name in query_lower:
                score += 300

            # 长度相似性得分 (越接近越好)
            length_diff = abs(len(name) - len(query_lower))
            score += max(0, 100 - length_diff * 5)

            # 避免选择DLC、Pass、Pack等附加内容
            penalty_keywords = ['dlc', 'pack', 'pass', 'bundle', 'edition', 'soundtrack', 'ost', 'friend\'s', 'season']
            for keyword in penalty_keywords:
                if keyword in name:
                    score -= 200

            # 如果有价格信息，优先选择有价格的
            if result.get('price'):
                score += 50

            scored_results.append((score, result))

        # 按分数排序，返回最高分的
        scored_results.sort(key=lambda x: x[0], reverse=True)
        return scored_results[0][1]

    async def search_multiple_countries(self, game_query: str, country_inputs: list[str]) -> str:
        """Searches game prices across multiple countries."""
        results = []
        valid_country_codes = []

        for country_input in country_inputs:
            country_code = self.get_country_code(country_input)
            if country_code:
                valid_country_codes.append(country_code)
            else:
                results.append(f"❌ 无效的国家/地区: {country_input}")

        if not valid_country_codes:
            valid_country_codes = [self.config.DEFAULT_CC]

        search_results = await self.search_game(game_query, valid_country_codes[0])
        if not search_results:
            return f"❌ 未找到相关游戏\n搜索词: `{game_query}`"

        # 智能选择最匹配的游戏
        game = self._select_best_match(search_results, game_query)
        app_id = str(game.get('id'))

        for cc in valid_country_codes:
            try:
                game_details = await self.get_game_details(app_id, cc)
                if game_details:
                    formatted_info = await self.format_game_info(game_details, cc)
                    results.append(formatted_info)
                await asyncio.sleep(self.config.REQUEST_DELAY)
            except Exception as e:
                error_msg = self.error_handler.handle_network_error(e)
                results.append(f"❌ {cc}区查询失败: {error_msg}")

        full_message = "\n\n".join(results)
        return full_message

    async def search_and_format_all(self, query: str, cc: str) -> str:
        """Performs a comprehensive search for games and bundles."""
        cache_key = f"steam_search_all_{query}_{cc}"
        cached_results = await cache_manager.load_cache(cache_key, max_age_seconds=self.config.PRICE_CACHE_DURATION, subdirectory="steam")
        if cached_results:
            items = cached_results
        else:
            encoded_query = quote(query)
            url = f"https://store.steampowered.com/search/results?term={encoded_query}&l={self.config.DEFAULT_LANG}&cc={cc}&category1=996,998&json=1"

            try:
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
                async with httpx.AsyncClient(headers=headers) as client:
                    response = await client.get(url, follow_redirects=True, timeout=10)
                    response.raise_for_status()
                    data = response.json()
                items = data.get('items', [])
                await cache_manager.save_cache(cache_key, items, subdirectory="steam")
            except httpx.RequestError as e:
                return self.error_handler.handle_network_error(e)
            except json.JSONDecodeError:
                return "❌ 搜索失败: JSON解码错误"

        if not items:
            return f"❌ 未找到相关内容\n搜索词: `{query}`"

        country_info = SUPPORTED_COUNTRIES.get(cc, {"name": cc})
        results = [
            "🔍 Steam搜索结果",
            f"关键词: `{query}`",
            f"🌍 搜索地区: {get_country_flag(cc)} {country_info['name']} ({cc})"
        ]

        apps = []
        bundles = []

        for item in items[:self.config.MAX_SEARCH_ITEMS]:
            name = item.get('name', '未知')
            logo_url = item.get('logo', '')

            if '/apps/' in logo_url:
                app_id_match = re.search(r'/apps/(\d+)/', logo_url)
                if app_id_match:
                    link = f"https://store.steampowered.com/app/{app_id_match.group(1)}"
                    apps.append(f"• 🎮 {name} - [Store Page]({link})\n  🔑 `{app_id_match.group(1)}`\n")
            elif '/bundles/' in logo_url:
                bundle_id_match = re.search(r'/bundles/(\d+)/', logo_url)
                if bundle_id_match:
                    link = f"https://store.steampowered.com/bundle/{bundle_id_match.group(1)}"
                    bundles.append(f"• 🛍 {name} - [Store Page]({link})\n  💎 `{bundle_id_match.group(1)}`\n")

        if apps:
            results.append("🎮 游戏:")
            results.extend(apps)

        if bundles:
            results.append("🛍 捆绑包:")
            results.extend(bundles)

        full_message = "\n".join(results)
        return full_message

steam_checker: SteamPriceChecker | None = None

def set_steam_checker(cache_manager_instance, rate_converter_instance: RateConverter):
    global steam_checker, cache_manager, rate_converter
    cache_manager = cache_manager_instance
    rate_converter = rate_converter_instance
    steam_checker = SteamPriceChecker()

async def steam_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /steam command for game price lookup with interactive search."""
    # 检查update.message是否存在
    if not update.message:
        return

    # 检查steam_checker是否已初始化
    if steam_checker is None:
        error_message = "❌ Steam功能未初始化，请稍后重试。"
        # 生成会话ID用于消息管理
        import time
        user_id = update.effective_user.id
        session_id = f"steam_init_error_{user_id}_{int(time.time())}"
        
        await send_message_with_auto_delete(
            context,
            update.message.chat_id,
            foldable_text_v2(error_message),
            MessageType.ERROR,
            session_id=session_id,
            parse_mode="MarkdownV2"
        )
        await delete_user_command(context, update.message.chat_id, update.message.message_id, session_id=session_id)
        return

    if not context.args:
        help_message = (
            "*🎮 Steam游戏价格查询*\n"
            "_Author:_ Domo/Meng\n\n"
            "*指令列表：*\n"
            "`/steam` [游戏名称/ID] [国家代码] - 查询游戏价格\n"
            "`/steamb` <捆绑包名称/ID> [国家代码] - 查询捆绑包价格\n"
            "`/steamcc` - 清理缓存\n"
            "`/steams` [关键词] - 综合搜索游戏和捆绑包\n\n"
            "*功能说明：*\n"
            "• 支持跨区价格对比,可同时查询多个地区,用空格分隔\n"
            "• 自动转换为人民币显示价格参考\n"
            "• 智能解析价格格式，支持多种货币符号\n"
            "• 支持查询捆绑包价格和内容\n"
            "• 使用OpenExchangeRate免费API进行汇率转换\n"
            "• 价格数据缓存3天,汇率每小时更新\n"
            "• 游戏ID永久缓存,无需重复获取\n\n"
            "*使用示例：*\n"
            "• `/steam 双人成行` - 查询国区价格\n"
            "• `/steam CS2 US RU TR AR` - 查询多区价格\n"
            "• `/steamb 赛博朋克` - 查询捆绑包\n"
            "• `/steamb 216938` - 通过ID查询捆绑包\n\n"
            "*提示：* 默认使用中国区(CN)查询"
        )
        # 生成会话ID用于消息管理
        import time
        user_id = update.effective_user.id
        session_id = f"steam_help_{user_id}_{int(time.time())}"
        
        await send_message_with_auto_delete(
            context,
            update.message.chat_id,
            foldable_text_with_markdown_v2(help_message),
            MessageType.HELP,
            session_id=session_id,
            parse_mode="MarkdownV2"
        )
        await delete_user_command(context, update.message.chat_id, update.message.message_id, session_id=session_id)
        return

    user_id = update.effective_user.id

    loading_message = "🔍 正在搜索游戏... ⏳"
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=foldable_text_v2(loading_message),
        parse_mode="MarkdownV2"
    )

    args = context.args
    # 解析参数：分离游戏名称和国家代码
    country_inputs = []
    game_name_parts = []

    for arg in reversed(args):
        country_code = steam_checker.get_country_code(arg)
        if country_code:
            country_inputs.insert(0, arg)
        else:
            game_name_parts = args[:len(args)-len(country_inputs)]
            break

    query = ' '.join(game_name_parts)
    if not country_inputs:
        country_inputs = [steam_checker.config.DEFAULT_CC]

    try:
        # 搜索游戏 (不使用缓存，确保每次都显示完整搜索结果)
        search_results = await steam_checker.search_game(query, country_inputs[0], use_cache=False)

        if not search_results:
            error_message = f"🔍 没有找到关键词 '{query}' 的相关内容"
            await message.edit_text(
                foldable_text_v2(error_message),
                parse_mode="MarkdownV2"
            )
            return

        # 始终显示交互式搜索界面，即使只有一个结果
        per_page = 5
        total_results = len(search_results)
        total_pages = min(10, (total_results + per_page - 1) // per_page) if total_results > 0 else 1

        page_results = search_results[0:per_page]

        search_data_for_session = {
            "query": query,
            "country_inputs": country_inputs,
            "all_results": search_results,
            "current_page": 1,
            "total_pages": total_pages,
            "total_results": total_results,
            "per_page": per_page,
            "results": page_results
        }

        # 生成会话ID用于消息管理
        import time
        session_id = f"steam_search_{user_id}_{int(time.time())}"

        # 存储用户搜索会话
        user_search_sessions[user_id] = {
            "query": query,
            "search_data": search_data_for_session,
            "message_id": message.message_id,
            "country_inputs": country_inputs,
            "session_id": session_id
        }

        # 格式化并显示结果
        result_text = format_steam_search_results(search_data_for_session)
        keyboard = create_steam_search_keyboard(search_data_for_session)

        # 删除搜索进度消息，然后发送新的搜索结果消息
        await message.delete()
        
        # 使用统一的消息发送API发送搜索结果
        new_message = await send_message_with_auto_delete(
            context,
            update.effective_chat.id,
            foldable_text_v2(result_text),
            MessageType.SEARCH_RESULT,
            session_id=session_id,
            reply_markup=keyboard,
            parse_mode="MarkdownV2",
            disable_web_page_preview=True
        )
        
        # 更新会话中的消息ID
        if new_message:
            user_search_sessions[user_id]["message_id"] = new_message.message_id

        # 删除用户命令消息
        await delete_user_command(context, update.effective_chat.id, update.message.message_id, session_id=session_id)

    except Exception as e:
        error_msg = steam_checker.error_handler.log_error(e, "搜索游戏")
        await message.delete()
        
        # 生成会话ID用于消息管理
        import time
        session_id = f"steam_error_{user_id}_{int(time.time())}"
        
        await send_message_with_auto_delete(
            context,
            update.effective_chat.id,
            foldable_text_v2(error_msg),
            MessageType.ERROR,
            session_id=session_id,
            parse_mode="MarkdownV2"
        )
        await delete_user_command(context, update.effective_chat.id, update.message.message_id, session_id=session_id)




async def steam_bundle_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /steamb command for bundle price lookup with interactive search."""
    # 检查update.message是否存在
    if not update.message:
        return

    # 检查steam_checker是否已初始化
    if steam_checker is None:
        error_message = "❌ Steam功能未初始化，请稍后重试。"
        # 生成会话ID用于消息管理
        import time
        user_id = update.effective_user.id
        session_id = f"steam_init_error_{user_id}_{int(time.time())}"
        
        await send_message_with_auto_delete(
            context,
            update.message.chat_id,
            foldable_text_v2(error_message),
            MessageType.ERROR,
            session_id=session_id,
            parse_mode="MarkdownV2"
        )
        await delete_user_command(context, update.message.chat_id, update.message.message_id, session_id=session_id)
        return

    if not context.args:
        error_message = "请提供捆绑包名称或ID。"
        # 生成会话ID用于消息管理
        import time
        user_id = update.effective_user.id
        session_id = f"steamb_error_{user_id}_{int(time.time())}"
        
        await send_message_with_auto_delete(
            context,
            update.message.chat_id,
            foldable_text_v2(error_message),
            MessageType.ERROR,
            session_id=session_id,
            parse_mode="MarkdownV2"
        )
        await delete_user_command(context, update.message.chat_id, update.message.message_id, session_id=session_id)
        return

    user_id = update.effective_user.id

    loading_message = "🔍 正在搜索捆绑包... ⏳"
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
            text=foldable_text_v2(loading_message),
        parse_mode="MarkdownV2"
    )

    args = context.args
    if len(args) >= 2 and steam_checker.get_country_code(args[-1]):
        query = ' '.join(args[:-1])
        cc = steam_checker.get_country_code(args[-1]) or steam_checker.config.DEFAULT_CC
    else:
        query = ' '.join(args)
        cc = steam_checker.config.DEFAULT_CC

    try:
        # 搜索捆绑包
        search_results = []

        if query.isdigit():
            # 通过ID搜索
            bundle_details = await steam_checker.search_bundle_by_id(query, cc)
            if bundle_details:
                search_results = [{
                    'id': query,
                    'name': bundle_details.get('name', '未知捆绑包'),
                    'url': bundle_details.get('url', ''),
                    'score': 100
                }]
        else:
            # 通过名称搜索
            search_results = await steam_checker.search_bundle(query, cc)

        if not search_results:
            error_lines = [
                "❌ 未找到相关捆绑包",
                f"搜索词: `{query}`"
            ]
            error_text = "\n".join(error_lines)
            await message.edit_text(
                foldable_text_v2(error_text),
                parse_mode="MarkdownV2"
            )
            return

        # 总是显示交互式列表选择，即使只有一个结果
        per_page = 5
        total_results = len(search_results)
        total_pages = min(10, (total_results + per_page - 1) // per_page) if total_results > 0 else 1

        page_results = search_results[0:per_page]

        search_data_for_session = {
            "query": query,
            "cc": cc,
            "all_results": search_results,
            "current_page": 1,
            "total_pages": total_pages,
            "total_results": total_results,
            "per_page": per_page,
            "results": page_results
        }

        # 生成会话ID用于消息管理
        import time
        session_id = f"steam_bundle_{user_id}_{int(time.time())}"

        # 存储用户搜索会话
        bundle_search_sessions[user_id] = {
            "query": query,
            "search_data": search_data_for_session,
            "message_id": message.message_id,
            "cc": cc,
            "session_id": session_id
        }

        # 格式化并显示结果
        result_text = format_bundle_search_results(search_data_for_session)
        keyboard = create_bundle_search_keyboard(search_data_for_session)

        # 删除搜索进度消息，然后发送新的搜索结果消息
        await message.delete()
        
        # 使用统一的消息发送API发送搜索结果
        new_message = await send_message_with_auto_delete(
            context,
            update.effective_chat.id,
            foldable_text_v2(result_text),
            MessageType.SEARCH_RESULT,
            session_id=session_id,
            reply_markup=keyboard,
            parse_mode="MarkdownV2",
            disable_web_page_preview=True
        )
        
        # 更新会话中的消息ID
        if new_message:
            bundle_search_sessions[user_id]["message_id"] = new_message.message_id

        # 删除用户命令消息
        await delete_user_command(context, update.effective_chat.id, update.message.message_id, session_id=session_id)

    except Exception as e:
        error_msg = f"❌ 查询捆绑包出错: {e}"
        await message.delete()
        
        # 生成会话ID用于消息管理
        import time
        session_id = f"steamb_error_{user_id}_{int(time.time())}"
        
        await send_message_with_auto_delete(
            context,
            update.effective_chat.id,
            foldable_text_v2(error_msg),
            MessageType.ERROR,
            session_id=session_id,
            parse_mode="MarkdownV2"
        )
        await delete_user_command(context, update.effective_chat.id, update.message.message_id, session_id=session_id)



async def steam_search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /steams command for comprehensive search."""
    # 检查update.message是否存在
    if not update.message:
        return

    # 检查steam_checker是否已初始化
    if steam_checker is None:
        error_message = "❌ Steam功能未初始化，请稍后重试。"
        # 生成会话ID用于消息管理
        import time
        user_id = update.effective_user.id
        session_id = f"steam_init_error_{user_id}_{int(time.time())}"
        
        await send_message_with_auto_delete(
            context,
            update.message.chat_id,
            foldable_text_v2(error_message),
            MessageType.ERROR,
            session_id=session_id,
            parse_mode="MarkdownV2"
        )
        await delete_user_command(context, update.message.chat_id, update.message.message_id, session_id=session_id)
        return

    if not context.args:
        error_message = "请提供搜索关键词。"
        # 生成会话ID用于消息管理
        import time
        user_id = update.effective_user.id
        session_id = f"steams_error_{user_id}_{int(time.time())}"
        
        await send_message_with_auto_delete(
            context,
            update.message.chat_id,
            foldable_text_v2(error_message),
            MessageType.ERROR,
            session_id=session_id,
            parse_mode="MarkdownV2"
        )
        await delete_user_command(context, update.message.chat_id, update.message.message_id, session_id=session_id)
        return

    loading_message = "🔍 正在查询中... ⏳"
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
            text=foldable_text_v2(loading_message),
        parse_mode="MarkdownV2"
    )

    query = ' '.join(context.args)
    cc = steam_checker.config.DEFAULT_CC
    
    # 生成会话ID用于消息管理
    import time
    user_id = update.effective_user.id
    session_id = f"steam_search_all_{user_id}_{int(time.time())}"
    
    try:
        result = await steam_checker.search_and_format_all(query, cc)
        await message.delete()
        
        # 使用统一的消息发送API
        await send_message_with_auto_delete(
            context,
            update.effective_chat.id,
            foldable_text_with_markdown_v2(result),
            MessageType.SEARCH_RESULT,
            session_id=session_id,
            parse_mode="MarkdownV2"
        )
        await delete_user_command(context, update.effective_chat.id, update.message.message_id, session_id=session_id)
    except Exception as e:
        error_msg = f"❌ 综合搜索出错: {e}"
        await message.delete()
        
        # 生成会话ID用于消息管理
        import time
        session_id = f"steams_error_{user_id}_{int(time.time())}"
        
        await send_message_with_auto_delete(
            context,
            update.effective_chat.id,
            foldable_text_v2(error_msg),
            MessageType.ERROR,
            session_id=session_id,
            parse_mode="MarkdownV2"
        )
        await delete_user_command(context, update.effective_chat.id, update.message.message_id, session_id=session_id)

async def steam_clean_cache_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /steamcc command to clear Steam cache."""
    if not update.message:
        return

    if steam_checker is None:
        error_message = "❌ Steam功能未初始化，请稍后重试。"
        # 生成会话ID用于消息管理
        import time
        user_id = update.effective_user.id
        session_id = f"steamcc_init_error_{user_id}_{int(time.time())}"
        
        await send_message_with_auto_delete(
            context,
            update.message.chat_id,
            foldable_text_v2(error_message),
            MessageType.ERROR,
            session_id=session_id,
            parse_mode="MarkdownV2"
        )
        await delete_user_command(context, update.message.chat_id, update.message.message_id, session_id=session_id)
        return

    try:
        # 从 context 获取缓存管理器
        cache_mgr = context.bot_data.get("cache_manager")
        if cache_mgr is not None:
            await cache_mgr.clear_cache(subdirectory="steam")
            success_message = "✅ Steam 缓存已清理。"
            # 生成会话ID用于消息管理
            import time
            user_id = update.effective_user.id
            session_id = f"steamcc_success_{user_id}_{int(time.time())}"
            
            await send_message_with_auto_delete(
                context,
                update.message.chat_id,
                foldable_text_v2(success_message),
                MessageType.SUCCESS,
                session_id=session_id,
                parse_mode="MarkdownV2"
            )
            await delete_user_command(context, update.message.chat_id, update.message.message_id, session_id=session_id)
        else:
            error_message = "❌ 缓存管理器未初始化。"
            # 生成会话ID用于消息管理
            import time
            user_id = update.effective_user.id
            session_id = f"steamcc_error_{user_id}_{int(time.time())}"
            
            await send_message_with_auto_delete(
                context,
                update.message.chat_id,
                foldable_text_v2(error_message),
                MessageType.ERROR,
                session_id=session_id,
                parse_mode="MarkdownV2"
            )
            await delete_user_command(context, update.message.chat_id, update.message.message_id, session_id=session_id)
    except Exception as e:
        logger.error(f"Error clearing Steam cache: {e}")
        error_msg = f"❌ 清理 Steam 缓存时发生错误: {e}"
        # 生成会话ID用于消息管理
        import time
        user_id = update.effective_user.id
        session_id = f"steamcc_error_{user_id}_{int(time.time())}"
        
        await send_message_with_auto_delete(
            context,
            update.message.chat_id,
            foldable_text_v2(error_msg),
            MessageType.ERROR,
            session_id=session_id,
            parse_mode="MarkdownV2"
        )
        await delete_user_command(context, update.message.chat_id, update.message.message_id, session_id=session_id)

async def steam_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理Steam搜索结果的内联键盘回调"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    callback_data = query.data

    # 检查用户是否有活跃的搜索会话
    if user_id not in user_search_sessions:
        await query.edit_message_text(
            foldable_text_v2("❌ 搜索会话已过期，请重新搜索"),
            parse_mode="MarkdownV2"
        )

        # 注：使用 query.edit_message_text 无需额外调度删除
        return

    session = user_search_sessions[user_id]
    search_data = session["search_data"]

    try:
        if callback_data.startswith("steam_select_"):
            # 用户选择了一个游戏
            parts = callback_data.split("_")
            game_index = int(parts[2])
            page = int(parts[3])

            # 计算实际的游戏索引
            actual_index = (page - 1) * search_data["per_page"] + game_index

            if actual_index < len(search_data["all_results"]):
                selected_item = search_data["all_results"][actual_index]
                item_id = selected_item.get('id')
                item_type = selected_item.get('type', 'game')

                if item_id:
                    # 显示加载消息
                    await query.edit_message_text(
                        foldable_text_v2("🔍 正在获取详细信息... ⏳"),
                        parse_mode="MarkdownV2"
                    )

                    # 根据类型处理不同的内容
                    if item_type == 'bundle':
                        # 处理捆绑包
                        country_inputs = session["country_inputs"]
                        cc = steam_checker.get_country_code(country_inputs[0]) or steam_checker.config.DEFAULT_CC
                        bundle_details = await steam_checker.get_bundle_details(str(item_id), cc)

                        if bundle_details:
                            result = await steam_checker.format_bundle_info(bundle_details, cc)
                        else:
                            result = "❌ 无法获取捆绑包信息"
                    else:
                        # 处理游戏和DLC
                        country_inputs = session["country_inputs"]
                        result = await steam_checker.search_multiple_countries(str(item_id), country_inputs)

                    await query.edit_message_text(
                        foldable_text_with_markdown_v2(result),
                        parse_mode="MarkdownV2"
                    )

                    # 清理用户会话
                    if user_id in user_search_sessions:
                        del user_search_sessions[user_id]
                else:
                    await query.edit_message_text(
                        foldable_text_v2("❌ 无法获取内容ID"),
                        parse_mode="MarkdownV2"
                    )
            else:
                await query.edit_message_text(
                    foldable_text_v2("❌ 选择的内容索引无效"),
                    parse_mode="MarkdownV2"
                )

        elif callback_data.startswith("steam_page_"):
            # 分页操作
            if callback_data == "steam_page_info":
                # 页面信息，不执行任何操作
                return

            page_num = int(callback_data.split("_")[2])
            current_page = search_data["current_page"]
            total_pages = search_data["total_pages"]

            if 1 <= page_num <= total_pages and page_num != current_page:
                # 更新页面数据
                per_page = search_data["per_page"]
                start_index = (page_num - 1) * per_page
                end_index = start_index + per_page
                page_results = search_data["all_results"][start_index:end_index]

                search_data["current_page"] = page_num
                search_data["results"] = page_results

                # 更新键盘和消息
                result_text = format_steam_search_results(search_data)
                keyboard = create_steam_search_keyboard(search_data)

                await query.edit_message_text(
                    foldable_text_v2(result_text),
                    reply_markup=keyboard,
                    parse_mode="MarkdownV2"
                )

        elif callback_data == "steam_new_search":
            # 新搜索
            await query.edit_message_text(
                foldable_text_v2("🔍 请使用 /steam [游戏名称] 开始新的搜索"),
                parse_mode="MarkdownV2"
            )

            # 清理用户会话
            if user_id in user_search_sessions:
                del user_search_sessions[user_id]

        elif callback_data == "steam_change_region":
            # 更改搜索地区
            change_region_text = "请选择新的搜索地区："

            # 定义地区按钮
            region_buttons = [
                InlineKeyboardButton("🇨🇳 中国", callback_data="steam_region_CN"),
                InlineKeyboardButton("🇭🇰 香港", callback_data="steam_region_HK"),
                InlineKeyboardButton("🇹🇼 台湾", callback_data="steam_region_TW"),
                InlineKeyboardButton("🇯🇵 日本", callback_data="steam_region_JP"),
                InlineKeyboardButton("🇺🇸 美国", callback_data="steam_region_US"),
                InlineKeyboardButton("🇬🇧 英国", callback_data="steam_region_GB"),
                InlineKeyboardButton("🇷🇺 俄罗斯", callback_data="steam_region_RU"),
                InlineKeyboardButton("🇹🇷 土耳其", callback_data="steam_region_TR"),
                InlineKeyboardButton("🇦🇷 阿根廷", callback_data="steam_region_AR"),
                InlineKeyboardButton("❌ 关闭", callback_data="steam_close")
            ]

            # 每行2个按钮
            keyboard = [region_buttons[i:i+2] for i in range(0, len(region_buttons), 2)]

            await query.edit_message_text(
                foldable_text_v2(change_region_text),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="MarkdownV2"
            )

        elif callback_data.startswith("steam_region_"):
            # 用户选择了新的搜索地区
            country_code = callback_data.split("_")[2]

            # 更新会话中的国家输入
            session["country_inputs"] = [country_code]
            search_data["country_inputs"] = [country_code]

            # 显示重新搜索消息
            query_text = search_data["query"]
            loading_message = f"🔍 正在在 {country_code.upper()} 区域重新搜索 '{query_text}'..."
            await query.edit_message_text(foldable_text_v2(loading_message), parse_mode="MarkdownV2")

            # 重新搜索游戏
            try:
                search_results = await steam_checker.search_game(query_text, country_code, use_cache=False)

                if not search_results:
                    error_message = f"🔍 在 {country_code.upper()} 区域没有找到关键词 '{query_text}' 的相关内容"
                    await query.edit_message_text(
                        foldable_text_v2(error_message),
                        parse_mode="MarkdownV2"
                    )
                    return

                # 更新搜索数据
                per_page = 5
                total_results = len(search_results)
                total_pages = min(10, (total_results + per_page - 1) // per_page) if total_results > 0 else 1
                page_results = search_results[0:per_page]

                search_data.update({
                    "all_results": search_results,
                    "current_page": 1,
                    "total_pages": total_pages,
                    "total_results": total_results,
                    "per_page": per_page,
                    "results": page_results
                })

                # 显示新的搜索结果
                result_text = format_steam_search_results(search_data)
                keyboard = create_steam_search_keyboard(search_data)

                await query.edit_message_text(
                    foldable_text_v2(result_text),
                    reply_markup=keyboard,
                    parse_mode="MarkdownV2",
                    disable_web_page_preview=True
                )

            except Exception as e:
                error_message = f"❌ 重新搜索失败: {e!s}"
                await query.edit_message_text(
                    foldable_text_v2(error_message),
                    parse_mode="MarkdownV2"
                )

        elif callback_data == "steam_close":
            # 关闭搜索
            await query.edit_message_text(
                foldable_text_v2("🎮 Steam搜索已关闭"),
                parse_mode="MarkdownV2"
            )

            # 注：使用 query.edit_message_text 无需额外调度删除

            # 清理用户会话
            if user_id in user_search_sessions:
                del user_search_sessions[user_id]

    except Exception as e:
        logger.error(f"Error in steam callback handler: {e}")
        await query.edit_message_text(
            foldable_text_v2(f"❌ 处理请求时发生错误: {e!s}"),
            parse_mode="MarkdownV2"
        )

        # 注：使用 query.edit_message_text 无需额外调度删除

# steamb 内联键盘回调处理
def format_bundle_search_results(search_data: dict) -> str:
    if search_data.get("error"):
        return f"❌ 搜索失败: {search_data['error']}"

    results = search_data["results"]
    query = search_data["query"]
    cc = search_data.get("cc", "CN")

    if not results:
        return f"🔍 在 {cc.upper()} 区域没有找到关键词 '{query}' 的相关捆绑包"

    # 获取国家标志和名称
    country_flag = get_country_flag(cc)
    country_info = SUPPORTED_COUNTRIES.get(cc, {"name": cc})
    country_name = country_info.get("name", cc)

    total_results = search_data.get("total_results", len(results))
    current_page = search_data.get("current_page", 1)
    total_pages = search_data.get("total_pages", 1)

    header_parts = [
        "🛍 Steam捆绑包搜索结果",
        f"🔍 关键词: {query}",
        f"🌍 搜索地区: {country_flag} {country_name} ({cc.upper()})",
        f"📊 找到 {total_results} 个结果 (第 {current_page}/{total_pages} 页)",
        "",
        "请从下方选择您要查询的捆绑包："
    ]

    return "\n".join(header_parts)

def create_bundle_search_keyboard(search_data: dict) -> InlineKeyboardMarkup:
    keyboard = []
    results = search_data["results"]
    for i in range(min(len(results), 5)):
        bundle = results[i]
        bundle_name = bundle.get("name", "未知捆绑包")
        if len(bundle_name) > 37:
            bundle_name = bundle_name[:34] + "..."
        callback_data = f"steamb_select_{i}_{search_data.get('current_page', 1)}"
        display_name = f"{i + 1}. 🛍 {bundle_name}"
        keyboard.append([InlineKeyboardButton(display_name, callback_data=callback_data)])
    current_page = search_data.get("current_page", 1)
    total_pages = search_data.get("total_pages", 1)
    nav_row = []
    if current_page > 1:
        nav_row.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"steamb_page_{current_page - 1}"))
    nav_row.append(InlineKeyboardButton(f"📄 {current_page}/{total_pages}", callback_data="steamb_page_info"))
    if current_page < total_pages:
        nav_row.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"steamb_page_{current_page + 1}"))
    if nav_row:
        keyboard.append(nav_row)
    action_row = [
        InlineKeyboardButton("🌍 更改搜索地区", callback_data="steamb_change_region"),
        InlineKeyboardButton("❌ 关闭", callback_data="steamb_close")
    ]
    keyboard.append(action_row)
    return InlineKeyboardMarkup(keyboard)

# 使用统一的会话管理器替代全局字典

async def steamb_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    callback_data = query.data
    if user_id not in bundle_search_sessions:
        await query.edit_message_text(
            foldable_text_v2("❌ 搜索会话已过期，请重新搜索"),
            parse_mode="MarkdownV2"
        )

        # 注：使用 query.edit_message_text 无需额外调度删除
        return
    session = bundle_search_sessions[user_id]
    search_data = session["search_data"]
    cc = search_data.get("cc") or "CN"
    try:
        if callback_data.startswith("steamb_select_"):
            parts = callback_data.split("_")
            bundle_index = int(parts[2])
            page = int(parts[3])
            actual_index = (page - 1) * search_data["per_page"] + bundle_index
            if actual_index < len(search_data["all_results"]):
                selected_bundle = search_data["all_results"][actual_index]
                bundle_id = selected_bundle.get('id')
                if bundle_id:
                    await query.edit_message_text(
                        foldable_text_v2("🔍 正在获取捆绑包详细信息... ⏳"),
                        parse_mode="MarkdownV2"
                    )
                    bundle_details = await steam_checker.get_bundle_details(str(bundle_id), cc)
                    if bundle_details:
                        result = await steam_checker.format_bundle_info(bundle_details, cc)
                    else:
                        result = "❌ 无法获取捆绑包信息"
                    await query.edit_message_text(
                        foldable_text_with_markdown_v2(result),
                        parse_mode="MarkdownV2"
                    )
                    if user_id in bundle_search_sessions:
                        del bundle_search_sessions[user_id]
                else:
                    await query.edit_message_text(
                        foldable_text_v2("❌ 无法获取捆绑包ID"),
                        parse_mode="MarkdownV2"
                    )
            else:
                await query.edit_message_text(
                    foldable_text_v2("❌ 选择的捆绑包索引无效"),
                    parse_mode="MarkdownV2"
                )
        elif callback_data.startswith("steamb_page_"):
            if callback_data == "steamb_page_info":
                return
            page_num = int(callback_data.split("_")[2])
            current_page = search_data["current_page"]
            total_pages = search_data["total_pages"]
            if 1 <= page_num <= total_pages and page_num != current_page:
                per_page = search_data["per_page"]
                start_index = (page_num - 1) * per_page
                end_index = start_index + per_page
                page_results = search_data["all_results"][start_index:end_index]
                search_data["current_page"] = page_num
                search_data["results"] = page_results
                result_text = format_bundle_search_results(search_data)
                keyboard = create_bundle_search_keyboard(search_data)
                await query.edit_message_text(
                    foldable_text_v2(result_text),
                    reply_markup=keyboard,
                    parse_mode="MarkdownV2"
                )
        elif callback_data == "steamb_new_search":
            await query.edit_message_text(
                foldable_text_v2("🔍 请使用 /steamb [捆绑包名称] 开始新的搜索"),
                parse_mode="MarkdownV2"
            )
            if user_id in bundle_search_sessions:
                del bundle_search_sessions[user_id]
        elif callback_data == "steamb_change_region":
            # 更改搜索地区
            change_region_text = "请选择新的搜索地区："

            # 定义地区按钮
            region_buttons = [
                InlineKeyboardButton("🇨🇳 中国", callback_data="steamb_region_CN"),
                InlineKeyboardButton("🇭🇰 香港", callback_data="steamb_region_HK"),
                InlineKeyboardButton("🇹🇼 台湾", callback_data="steamb_region_TW"),
                InlineKeyboardButton("🇯🇵 日本", callback_data="steamb_region_JP"),
                InlineKeyboardButton("🇺🇸 美国", callback_data="steamb_region_US"),
                InlineKeyboardButton("🇬🇧 英国", callback_data="steamb_region_GB"),
                InlineKeyboardButton("🇷🇺 俄罗斯", callback_data="steamb_region_RU"),
                InlineKeyboardButton("🇹🇷 土耳其", callback_data="steamb_region_TR"),
                InlineKeyboardButton("🇦🇷 阿根廷", callback_data="steamb_region_AR"),
                InlineKeyboardButton("❌ 关闭", callback_data="steamb_close")
            ]

            # 每行2个按钮
            keyboard = [region_buttons[i:i+2] for i in range(0, len(region_buttons), 2)]

            await query.edit_message_text(
                foldable_text_v2(change_region_text),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="MarkdownV2"
            )

        elif callback_data.startswith("steamb_region_"):
            # 用户选择了新的搜索地区
            country_code = callback_data.split("_")[2]

            # 更新会话中的地区信息
            session["cc"] = country_code
            search_data["cc"] = country_code

            # 显示重新搜索消息
            query_text = search_data["query"]
            loading_message = f"🔍 正在在 {country_code.upper()} 区域重新搜索捆绑包 '{query_text}'..."
            await query.edit_message_text(foldable_text_v2(loading_message), parse_mode="MarkdownV2")

            # 重新搜索捆绑包
            try:
                if query_text.isdigit():
                    # 通过ID搜索
                    bundle_details = await steam_checker.search_bundle_by_id(query_text, country_code)
                    if bundle_details:
                        search_results = [{
                            'id': query_text,
                            'name': bundle_details.get('name', '未知捆绑包'),
                            'url': bundle_details.get('url', ''),
                            'score': 100
                        }]
                    else:
                        search_results = []
                else:
                    # 通过名称搜索
                    search_results = await steam_checker.search_bundle(query_text, country_code)

                if not search_results:
                    error_message = f"🔍 在 {country_code.upper()} 区域没有找到关键词 '{query_text}' 的相关捆绑包"
                    await query.edit_message_text(
                        foldable_text_v2(error_message),
                        parse_mode="MarkdownV2"
                    )
                    return

                # 更新搜索数据
                per_page = 5
                total_results = len(search_results)
                total_pages = min(10, (total_results + per_page - 1) // per_page) if total_results > 0 else 1
                page_results = search_results[0:per_page]

                search_data.update({
                    "all_results": search_results,
                    "current_page": 1,
                    "total_pages": total_pages,
                    "total_results": total_results,
                    "per_page": per_page,
                    "results": page_results
                })

                # 显示新的搜索结果
                result_text = format_bundle_search_results(search_data)
                keyboard = create_bundle_search_keyboard(search_data)

                await query.edit_message_text(
                    foldable_text_v2(result_text),
                    reply_markup=keyboard,
                    parse_mode="MarkdownV2",
                    disable_web_page_preview=True
                )

            except Exception as e:
                error_message = f"❌ 重新搜索失败: {e!s}"
                await query.edit_message_text(
                    foldable_text_v2(error_message),
                    parse_mode="MarkdownV2"
                )

        elif callback_data == "steamb_close":
            await query.edit_message_text(
                foldable_text_v2("🛍 捆绑包搜索已关闭"),
                parse_mode="MarkdownV2"
            )

            # 注：使用 query.edit_message_text 无需额外调度删除

            if user_id in bundle_search_sessions:
                del bundle_search_sessions[user_id]
    except Exception as e:
        logger.error(f"Error in steamb callback handler: {e}")
        await query.edit_message_text(
            foldable_text_v2(f"❌ 处理请求时发生错误: {e!s}"),
            parse_mode="MarkdownV2"
        )

        # 注：使用 query.edit_message_text 无需额外调度删除

# Register callback handler
command_factory.register_callback("^steam_", steam_callback_handler, permission=Permission.USER, description="Steam搜索回调处理")
# Register callback handler
command_factory.register_callback("^steamb_", steamb_callback_handler, permission=Permission.USER, description="Steam捆绑包搜索回调处理")

# Register commands
command_factory.register_command("steam", steam_command, permission=Permission.USER, description="Steam游戏价格查询")
command_factory.register_command("steamb", steam_bundle_command, permission=Permission.USER, description="查询捆绑包价格")
command_factory.register_command("steamcc", steam_clean_cache_command, permission=Permission.ADMIN, description="清理Steam缓存")
command_factory.register_command("steams", steam_search_command, permission=Permission.USER, description="综合搜索游戏和捆绑包")
