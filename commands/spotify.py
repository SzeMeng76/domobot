# commands/spotify.py

import logging
from datetime import datetime
from typing import Any

import httpx
from telegram import Update
from telegram.ext import ContextTypes

# Note: CacheManager import removed - now uses injected Redis cache manager from main.py
from utils.command_factory import command_factory
from utils.country_data import COUNTRY_NAME_TO_CODE, SUPPORTED_COUNTRIES, get_country_flag
from utils.formatter import foldable_text_v2, foldable_text_with_markdown_v2
from utils.message_manager import delete_user_command, send_error, send_search_result
from utils.permissions import Permission
from utils.price_query_service import PriceQueryService
from utils.rate_converter import RateConverter


logger = logging.getLogger(__name__)

# Static country code to English name mapping for better reliability
COUNTRY_CODES = {
    # Africa
    "AO": "Angola",
    "BJ": "Benin",
    "BW": "Botswana",
    "BF": "Burkina Faso",
    "BI": "Burundi",
    "CV": "Cabo Verde",
    "CM": "Cameroon",
    "TD": "Chad",
    "KM": "Comoros",
    "CI": "Côte d'Ivoire",
    "CD": "Democratic Republic of the Congo",
    "DJ": "Djibouti",
    "EG": "Egypt",
    "GQ": "Equatorial Guinea",
    "SZ": "Eswatini",
    "ET": "Ethiopia",
    "GA": "Gabon",
    "GM": "The Gambia",
    "GH": "Ghana",
    "GN": "Guinea",
    "GW": "Guinea-Bissau",
    "KE": "Kenya",
    "LS": "Lesotho",
    "LR": "Liberia",
    "LY": "Libya",
    "MG": "Madagascar",
    "MW": "Malawi",
    "ML": "Mali",
    "MR": "Mauritania",
    "MU": "Mauritius",
    "MA": "Morocco",
    "MZ": "Mozambique",
    "NA": "Namibia",
    "NE": "Niger",
    "NG": "Nigeria",
    "CG": "Republic of the Congo",
    "RW": "Rwanda",
    "ST": "Sao Tome and Principe",
    "SN": "Senegal",
    "SC": "Seychelles",
    "SL": "Sierra Leone",
    "ZA": "South Africa",
    "TZ": "Tanzania",
    "TG": "Togo",
    "TN": "Tunisia",
    "UG": "Uganda",
    "ZM": "Zambia",
    "ZW": "Zimbabwe",
    # Asia
    "AM": "Armenia",
    "AZ": "Azerbaijan",
    "BH": "Bahrain",
    "BD": "Bangladesh",
    "BT": "Bhutan",
    "BN": "Brunei Darussalam",
    "KH": "Cambodia",
    "CY": "Cyprus",
    "GE": "Georgia",
    "HK": "Hong Kong",
    "IN": "India",
    "ID": "Indonesia",
    "IQ": "Iraq",
    "IL": "Israel",
    "JP": "Japan",
    "JO": "Jordan",
    "KZ": "Kazakhstan",
    "KW": "Kuwait",
    "KG": "Kyrgyz Republic",
    "LA": "Laos",
    "LB": "Lebanon",
    "MO": "Macao",
    "MY": "Malaysia",
    "MV": "Maldives",
    "MN": "Mongolia",
    "NP": "Nepal",
    "OM": "Oman",
    "PK": "Pakistan",
    "PS": "Palestine",
    "PH": "Philippines",
    "QA": "Qatar",
    "SA": "Saudi Arabia",
    "SG": "Singapore",
    "KR": "South Korea",
    "LK": "Sri Lanka",
    "TW": "Taiwan",
    "TJ": "Tajikistan",
    "TH": "Thailand",
    "TL": "Timor-Leste",
    "TR": "Turkey",
    "AE": "United Arab Emirates",
    "UZ": "Uzbekistan",
    "VN": "Vietnam",
    # Europe
    "AL": "Albania",
    "AD": "Andorra",
    "AT": "Austria",
    "BY": "Belarus",
    "BE": "Belgium",
    "BA": "Bosnia and Herzegovina",
    "BG": "Bulgaria",
    "HR": "Croatia",
    "CZ": "Czech Republic",
    "DK": "Denmark",
    "EE": "Estonia",
    "FI": "Finland",
    "FR": "France",
    "DE": "Germany",
    "GR": "Greece",
    "HU": "Hungary",
    "IS": "Iceland",
    "IE": "Ireland",
    "IT": "Italy",
    "XK": "Kosovo",
    "LV": "Latvia",
    "LI": "Liechtenstein",
    "LT": "Lithuania",
    "LU": "Luxembourg",
    "MT": "Malta",
    "MD": "Moldova",
    "MC": "Monaco",
    "ME": "Montenegro",
    "NL": "Netherlands",
    "MK": "North Macedonia",
    "NO": "Norway",
    "PL": "Poland",
    "PT": "Portugal",
    "RO": "Romania",
    "SM": "San Marino",
    "RS": "Serbia",
    "SK": "Slovakia",
    "SI": "Slovenia",
    "ES": "Spain",
    "SE": "Sweden",
    "CH": "Switzerland",
    "UA": "Ukraine",
    "GB": "United Kingdom",
    # Latin America and the Caribbean
    "AG": "Antigua and Barbuda",
    "AR": "Argentina",
    "BS": "The Bahamas",
    "BB": "Barbados",
    "BZ": "Belize",
    "BO": "Bolivia",
    "BR": "Brazil",
    "CL": "Chile",
    "CO": "Colombia",
    "CR": "Costa Rica",
    "CW": "Curacao",
    "DM": "Dominica",
    "DO": "Dominican Republic",
    "EC": "Ecuador",
    "SV": "El Salvador",
    "GD": "Grenada",
    "GT": "Guatemala",
    "GY": "Guyana",
    "HT": "Haiti",
    "HN": "Honduras",
    "JM": "Jamaica",
    "MX": "Mexico",
    "NI": "Nicaragua",
    "PA": "Panama",
    "PY": "Paraguay",
    "PE": "Peru",
    "KN": "St. Kitts and Nevis",
    "LC": "St. Lucia",
    "VC": "St. Vincent and the Grenadines",
    "SR": "Suriname",
    "TT": "Trinidad and Tobago",
    "UY": "Uruguay",
    "VE": "Venezuela",
    # Northern America
    "CA": "Canada",
    "US": "USA",
    # Oceania
    "AU": "Australia",
    "FJ": "Fiji",
    "KI": "Kiribati",
    "MH": "Marshall Islands",
    "FM": "Micronesia",
    "NR": "Nauru",
    "NZ": "New Zealand",
    "PW": "Palau",
    "PG": "Papua New Guinea",
    "WS": "Samoa",
    "SB": "Solomon Islands",
    "TO": "Tonga",
    "TV": "Tuvalu",
    "VU": "Vanuatu",
}

# Static country code to Chinese name mapping
COUNTRY_CODES_CN = {
    # Africa
    "AO": "安哥拉",
    "BJ": "贝宁",
    "BW": "博茨瓦纳",
    "BF": "布基纳法索",
    "BI": "布隆迪",
    "CV": "佛得角",
    "CM": "喀麦隆",
    "TD": "乍得",
    "KM": "科摩罗",
    "CI": "科特迪瓦",
    "CD": "刚果民主共和国",
    "DJ": "吉布提",
    "EG": "埃及",
    "GQ": "赤道几内亚",
    "SZ": "斯威士兰",
    "ET": "埃塞俄比亚",
    "GA": "加蓬",
    "GM": "冈比亚",
    "GH": "加纳",
    "GN": "几内亚",
    "GW": "几内亚比绍",
    "KE": "肯尼亚",
    "LS": "莱索托",
    "LR": "利比里亚",
    "LY": "利比亚",
    "MG": "马达加斯加",
    "MW": "马拉维",
    "ML": "马里",
    "MR": "毛里塔尼亚",
    "MU": "毛里求斯",
    "MA": "摩洛哥",
    "MZ": "莫桑比克",
    "NA": "纳米比亚",
    "NE": "尼日尔",
    "NG": "尼日利亚",
    "CG": "刚果共和国",
    "RW": "卢旺达",
    "ST": "圣多美和普林西比",
    "SN": "塞内加尔",
    "SC": "塞舌尔",
    "SL": "塞拉利昂",
    "ZA": "南非",
    "TZ": "坦桑尼亚",
    "TG": "多哥",
    "TN": "突尼斯",
    "UG": "乌干达",
    "ZM": "赞比亚",
    "ZW": "津巴布韦",
    # Asia
    "AM": "亚美尼亚",
    "AZ": "阿塞拜疆",
    "BH": "巴林",
    "BD": "孟加拉国",
    "BT": "不丹",
    "BN": "文莱",
    "KH": "柬埔寨",
    "CY": "塞浦路斯",
    "GE": "格鲁吉亚",
    "HK": "香港",
    "IN": "印度",
    "ID": "印度尼西亚",
    "IQ": "伊拉克",
    "IL": "以色列",
    "JP": "日本",
    "JO": "约旦",
    "KZ": "哈萨克斯坦",
    "KW": "科威特",
    "KG": "吉尔吉斯斯坦",
    "LA": "老挝",
    "LB": "黎巴嫩",
    "MO": "澳门",
    "MY": "马来西亚",
    "MV": "马尔代夫",
    "MN": "蒙古",
    "NP": "尼泊尔",
    "OM": "阿曼",
    "PK": "巴基斯坦",
    "PS": "巴勒斯坦",
    "PH": "菲律宾",
    "QA": "卡塔尔",
    "SA": "沙特阿拉伯",
    "SG": "新加坡",
    "KR": "韩国",
    "LK": "斯里兰卡",
    "TW": "台湾",
    "TJ": "塔吉克斯坦",
    "TH": "泰国",
    "TL": "东帝汶",
    "TR": "土耳其",
    "AE": "阿联酋",
    "UZ": "乌兹别克斯坦",
    "VN": "越南",
    # Europe
    "AL": "阿尔巴尼亚",
    "AD": "安道尔",
    "AT": "奥地利",
    "BY": "白俄罗斯",
    "BE": "比利时",
    "BA": "波黑",
    "BG": "保加利亚",
    "HR": "克罗地亚",
    "CZ": "捷克",
    "DK": "丹麦",
    "EE": "爱沙尼亚",
    "FI": "芬兰",
    "FR": "法国",
    "DE": "德国",
    "GR": "希腊",
    "HU": "匈牙利",
    "IS": "冰岛",
    "IE": "爱尔兰",
    "IT": "意大利",
    "XK": "科索沃",
    "LV": "拉脱维亚",
    "LI": "列支敦士登",
    "LT": "立陶宛",
    "LU": "卢森堡",
    "MT": "马耳他",
    "MD": "摩尔多瓦",
    "MC": "摩纳哥",
    "ME": "黑山",
    "NL": "荷兰",
    "MK": "北马其顿",
    "NO": "挪威",
    "PL": "波兰",
    "PT": "葡萄牙",
    "RO": "罗马尼亚",
    "SM": "圣马力诺",
    "RS": "塞尔维亚",
    "SK": "斯洛伐克",
    "SI": "斯洛文尼亚",
    "ES": "西班牙",
    "SE": "瑞典",
    "CH": "瑞士",
    "UA": "乌克兰",
    "GB": "英国",
    # Latin America and the Caribbean
    "AG": "安提瓜和巴布达",
    "AR": "阿根廷",
    "BS": "巴哈马",
    "BB": "巴巴多斯",
    "BZ": "伯利兹",
    "BO": "玻利维亚",
    "BR": "巴西",
    "CL": "智利",
    "CO": "哥伦比亚",
    "CR": "哥斯达黎加",
    "CW": "库拉索",
    "DM": "多米尼克",
    "DO": "多米尼加",
    "EC": "厄瓜多尔",
    "SV": "萨尔瓦多",
    "GD": "格林纳达",
    "GT": "危地马拉",
    "GY": "圭亚那",
    "HT": "海地",
    "HN": "洪都拉斯",
    "JM": "牙买加",
    "MX": "墨西哥",
    "NI": "尼加拉瓜",
    "PA": "巴拿马",
    "PY": "巴拉圭",
    "PE": "秘鲁",
    "KN": "圣基茨和尼维斯",
    "LC": "圣卢西亚",
    "VC": "圣文森特和格林纳丁斯",
    "SR": "苏里南",
    "TT": "特立尼达和多巴哥",
    "UY": "乌拉圭",
    "VE": "委内瑞拉",
    # Northern America
    "CA": "加拿大",
    "US": "美国",
    # Oceania
    "AU": "澳大利亚",
    "FJ": "斐济",
    "KI": "基里巴斯",
    "MH": "马绍尔群岛",
    "FM": "密克罗尼西亚",
    "NR": "瑙鲁",
    "NZ": "新西兰",
    "PW": "帕劳",
    "PG": "巴布亚新几内亚",
    "WS": "萨摩亚",
    "SB": "所罗门群岛",
    "TO": "汤加",
    "TV": "图瓦卢",
    "VU": "瓦努阿图",
}


class SpotifyPriceBot(PriceQueryService):
    PRICE_URL = (
        "https://raw.githubusercontent.com/SzeMeng76/spotify-prices/refs/heads/main/spotify_prices_cny_sorted.json"
    )

    async def _fetch_data(self, context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any] | None:
        """Fetches Spotify price data from the specified URL."""
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
            logger.error(f"Failed to fetch Spotify price data: {e}")
            return None
        except Exception as e:
            logger.error(f"An unexpected error occurred while fetching Spotify data: {e}")
            return None

    def _init_country_mapping(self) -> dict[str, Any]:
        """Initializes country name and code to data mapping."""
        mapping = {}
        if not self.data:
            return mapping

        # Skip the metadata entries and only process country data
        for key, value in self.data.items():
            if key.startswith("_"):  # Skip metadata entries like _top_10_cheapest_premium_family
                continue

            country_code = key.upper()
            mapping[country_code] = value

            # 1. Map by Chinese name from SUPPORTED_COUNTRIES (highest priority)
            if country_code in SUPPORTED_COUNTRIES:
                country_info = SUPPORTED_COUNTRIES[country_code]
                if "name_cn" in country_info:
                    mapping[country_info["name_cn"]] = value
                if "name" in country_info:
                    mapping[country_info["name"]] = value

            # 2. Map by English name from our static COUNTRY_CODES mapping
            if country_code in COUNTRY_CODES:
                mapping[COUNTRY_CODES[country_code]] = value

            # 3. Map by Chinese name from our static COUNTRY_CODES_CN mapping
            if country_code in COUNTRY_CODES_CN:
                mapping[COUNTRY_CODES_CN[country_code]] = value

            # 3. Map by country name from the JSON data (fallback)
            if "country_name" in value:
                mapping[value["country_name"]] = value

            # 4. Map from COUNTRY_NAME_TO_CODE for Chinese input support
            for chinese_name, code in COUNTRY_NAME_TO_CODE.items():
                if code.upper() == country_code:
                    mapping[chinese_name] = value

        return mapping

    async def _format_price_message(self, country_code: str, price_info: dict) -> str:
        """Formats the price information for a single country."""
        country_info = SUPPORTED_COUNTRIES.get(country_code.upper(), {})

        # Try to get Chinese name in this order:
        # 1. From SUPPORTED_COUNTRIES (our central config with Chinese names)
        # 2. From our static COUNTRY_CODES_CN mapping (comprehensive Chinese names)
        # 3. From price_info if it has country_name_cn (from top 10 data)
        # 4. From our static COUNTRY_CODES mapping (reliable English names)
        # 5. From price_info country_name as fallback
        # 6. Use country_code as last resort
        country_name_cn = (
            country_info.get("name_cn")
            or COUNTRY_CODES_CN.get(country_code.upper())
            or price_info.get("country_name_cn")
            or COUNTRY_CODES.get(country_code.upper())
            or price_info.get("country_name", country_code)
        )

        country_flag = get_country_flag(country_code)

        lines = [f"📍 国家/地区： {country_name_cn} ({country_code.upper()}) {country_flag}"]

        plans = price_info.get("plans", [])
        if not plans:
            return f"📍 国家/地区: {country_name_cn} ({country_code.upper()}) {country_flag}\n❌ 未找到价格信息"

        # Plan name translation mapping - 包含预付费套餐
        plan_names = {
            # 月付套餐
            "Premium Individual": "个人版 (Premium Individual)",
            "Premium Student": "学生版 (Premium Student)", 
            "Premium Duo": "双人版 (Premium Duo)",
            "Premium Family": "家庭版 (Premium Family)",
            "Premium Basic": "基础版 (Premium Basic)",
            "Premium Lite": "轻量版 (Premium Lite)",
            
            # 预付费套餐 - Individual (使用标准化后的英文格式)
            "Premium Individual 1 Year Prepaid": "个人版 [1年预付费]",
            "Premium Individual 6 Months Prepaid": "个人版 [6个月预付费]", 
            "Premium Individual 3 Months Prepaid": "个人版 [3个月预付费]",
            "Premium Individual 1 Month Prepaid": "个人版 [1个月预付费]",
            
            # 预付费套餐 - Duo
            "Premium Duo 1 Year Prepaid": "双人版 [1年预付费]",
            "Premium Duo 6 Months Prepaid": "双人版 [6个月预付费]",
            "Premium Duo 3 Months Prepaid": "双人版 [3个月预付费]",
            "Premium Duo 1 Month Prepaid": "双人版 [1个月预付费]",
            
            # 预付费套餐 - Family
            "Premium Family 1 Year Prepaid": "家庭版 [1年预付费]",
            "Premium Family 6 Months Prepaid": "家庭版 [6个月预付费]",
            "Premium Family 3 Months Prepaid": "家庭版 [3个月预付费]",
            "Premium Family 1 Month Prepaid": "家庭版 [1个月预付费]",
            
            # 预付费套餐 - Student (通常没有预付费，但以防万一)
            "Premium Student 1 Year Prepaid": "学生版 [1年预付费]",
            "Premium Student 6 Months Prepaid": "学生版 [6个月预付费]",
            "Premium Student 3 Months Prepaid": "学生版 [3个月预付费]",
            "Premium Student 1 Month Prepaid": "学生版 [1个月预付费]",
        }

        for i, plan in enumerate(plans):
            plan_name = plan.get("plan", "未知套餐")
            plan_name_cn = plan_names.get(plan_name, plan_name)

            # Extract currency, price_number and price_cny
            currency = plan.get("currency", "")
            price_number = plan.get("price_number", "")
            price_cny = plan.get("price_cny", 0)
            original_price = plan.get("price", "价格未知")

            # Determine the connector
            is_last_plan = i == len(plans) - 1
            connector = "" if is_last_plan else ""

            # 检查是否为预付费套餐，如果是则显示实际总价格
            total_price_number = plan.get("total_price_number", "")
            total_price_cny = plan.get("total_price_cny", 0)
            
            # Format price display - 预付费套餐优先显示总价格
            if total_price_number and total_price_cny > 0:
                # 预付费套餐显示总价格 + 等效月费
                if currency and price_number and price_cny > 0:
                    price_display = f"{currency} {total_price_number} ≈ ¥{total_price_cny:.2f} (等效月费 ¥{price_cny:.2f})"
                else:
                    price_display = f"{currency} {total_price_number} ≈ ¥{total_price_cny:.2f}"
            elif currency and price_number and price_cny > 0:
                # 月付套餐显示月费
                price_display = f"{currency} {price_number} ≈ ¥{price_cny:.2f}"
            elif price_cny > 0:
                price_display = f"{original_price} ≈ ¥{price_cny:.2f}"
            else:
                price_display = original_price

            lines.append(f"{connector}💰 {plan_name_cn}：{price_display}")

        # Add scraped time if available
        if "scraped_at" in price_info:
            lines.append(f"  📅 数据时间：{price_info['scraped_at']}")

        return "\n".join(lines)

    def _extract_comparison_price(self, item: dict) -> float | None:
        """Extracts the Premium Family plan's CNY price for ranking."""
        plans = item.get("plans", [])
        for plan in plans:
            if plan.get("plan") == "Premium Family":
                price_cny = plan.get("price_cny")
                if price_cny and price_cny > 0:
                    return float(price_cny)
        return None

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
            price_info = self.country_mapping.get(query.upper()) or self.country_mapping.get(query)

            if not price_info:
                not_found.append(query)
                continue

            country_code = price_info.get("country_code")
            if country_code:
                formatted_message = await self._format_price_message(country_code, price_info)
                if formatted_message:
                    result_messages.append(formatted_message)
                else:
                    not_found.append(query)
            else:
                not_found.append(query)

        # 组装原始文本消息
        raw_message_parts = []
        raw_message_parts.append(f"*🎵 {self.service_name} 订阅价格查询*")
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

    async def get_top_cheapest(self, top_n: int = 10) -> str:
        """Gets the top 10 cheapest countries for the Premium Family plan."""
        if not self.data:
            error_msg = f"❌ 错误：未能加载 {self.service_name} 价格数据。"
            return foldable_text_v2(error_msg)

        # Use the pre-calculated top 10 data if available
        top_10_data = self.data.get("_top_10_cheapest_premium_family", {}).get("data", [])

        if top_10_data:
            # 组装原始文本，不转义
            message_lines = [f"*🏆 {self.service_name} 全球最低价格排名 (家庭版)*"]
            message_lines.append("")  # Empty line after header

            for item in top_10_data[:top_n]:
                rank = item.get("rank", 0)
                country_code = item.get("country_code", "N/A").upper()

                # Try to get Chinese name in this order:
                # 1. From the item itself (country_name_cn)
                # 2. From SUPPORTED_COUNTRIES (Chinese names)
                # 3. From our static COUNTRY_CODES_CN mapping (comprehensive Chinese names)
                # 4. From our static COUNTRY_CODES mapping (reliable English names)
                # 5. From the item's country_name as fallback
                country_name_cn = (
                    item.get("country_name_cn")
                    or SUPPORTED_COUNTRIES.get(country_code, {}).get("name_cn")
                    or COUNTRY_CODES_CN.get(country_code)
                    or COUNTRY_CODES.get(country_code)
                    or item.get("country_name", country_code)
                )

                country_flag = get_country_flag(country_code)

                # Extract currency, price_number and price_cny
                currency = item.get("currency", "")
                price_number = item.get("price_number", "")
                price_cny = item.get("price_cny", 0)
                original_price = item.get("original_price", "价格未知")

                # Format price display with currency, price_number, and CNY
                if currency and price_number and price_cny > 0:
                    price_display = f"{currency} {price_number} ≈ ¥{price_cny:.2f}"
                elif price_cny > 0:
                    price_display = f"{original_price} ≈ ¥{price_cny:.2f}"
                else:
                    price_display = original_price

                # Rank emoji
                rank_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
                if rank == 1:
                    rank_emoji = "🥇"
                elif rank == 2:
                    rank_emoji = "🥈"
                elif rank == 3:
                    rank_emoji = "🥉"
                elif rank <= 10:
                    rank_emoji = rank_emojis[rank - 1]
                else:
                    rank_emoji = f"{rank}."

                message_lines.append(f"{rank_emoji} {country_name_cn} ({country_code}) {country_flag}")
                message_lines.append(f"💰 家庭版: {price_display}")

                # Add blank line between countries (except for the last one)
                if rank < len(top_10_data[:top_n]):
                    message_lines.append("")

            # Use update time from metadata, or cache timestamp as fallback
            updated_at = self.data.get("_top_10_cheapest_premium_family", {}).get("updated_at", "")
            if updated_at:
                message_lines.append("")  # Empty line before timestamp
                message_lines.append(f"⏱ 数据更新时间：{updated_at}")
            elif self.cache_timestamp:
                update_time_str = datetime.fromtimestamp(self.cache_timestamp).strftime("%Y-%m-%d %H:%M:%S")
                message_lines.append("")  # Empty line before timestamp
                message_lines.append(f"⏱ 数据更新时间 (缓存)：{update_time_str}")

        else:
            # Fallback: calculate from individual country data
            countries_with_prices = []
            for key, item in self.data.items():
                if key.startswith("_"):  # Skip metadata
                    continue
                price_cny = self._extract_comparison_price(item)
                if price_cny is not None:
                    countries_with_prices.append({"data": item, "price": price_cny})

            if not countries_with_prices:
                error_msg = f"未能找到足够的可比较 {self.service_name} 家庭版价格信息。"
                return foldable_text_v2(error_msg)

            countries_with_prices.sort(key=lambda x: x["price"])
            top_countries = countries_with_prices[:top_n]

            # 组装原始文本，不转义
            message_lines = [f"*🎵 {self.service_name} 全球最低价格排名 (家庭版)*"]
            message_lines.append("")  # Empty line after header

            for idx, country_data in enumerate(top_countries, 1):
                item = country_data["data"]
                country_code = item.get("country_code", "N/A").upper()
                country_info = SUPPORTED_COUNTRIES.get(country_code, {})

                # Try to get Chinese name in this order:
                # 1. From SUPPORTED_COUNTRIES (Chinese names)
                # 2. From our static COUNTRY_CODES_CN mapping (comprehensive Chinese names)
                # 3. From our static COUNTRY_CODES mapping (reliable English names)
                # 4. From the item's country_name as fallback
                country_name_cn = (
                    country_info.get("name_cn")
                    or COUNTRY_CODES_CN.get(country_code)
                    or COUNTRY_CODES.get(country_code)
                    or item.get("country_name", country_code)
                )

                country_flag = get_country_flag(country_code)
                price_cny = country_data["price"]

                # Find the Premium Family plan for original price and details
                currency = ""
                price_number = ""
                original_price = "价格未知"
                plans = item.get("plans", [])
                for plan in plans:
                    if plan.get("plan") == "Premium Family":
                        currency = plan.get("currency", "")
                        price_number = plan.get("price_number", "")
                        original_price = plan.get("price", "价格未知")
                        break

                # Format price display with currency, price_number, and CNY
                if currency and price_number and price_cny > 0:
                    price_display = f"{currency} {price_number} ≈ ¥{price_cny:.2f}"
                elif price_cny > 0:
                    price_display = f"{original_price} ≈ ¥{price_cny:.2f}"
                else:
                    price_display = original_price

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

                message_lines.append(f"{rank_emoji} {country_name_cn} ({country_code}) {country_flag}")
                message_lines.append(f"💰 家庭版: {price_display}")

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

    async def get_top_prepaid_individual(self, top_n: int = 10) -> str:
        """获取最便宜的个人1年预付费套餐排行榜"""
        if not self.data:
            error_msg = f"❌ 错误：未能加载 {self.service_name} 价格数据。"
            return foldable_text_v2(error_msg)

        # 使用预先计算的个人1年预付费数据
        top_10_data = self.data.get("_top_10_cheapest_individual_1year_prepaid", {}).get("data", [])

        if not top_10_data:
            error_msg = f"❌ 未找到 {self.service_name} 个人1年预付费价格信息。"
            return foldable_text_v2(error_msg)

        # 组装原始文本
        message_lines = [f"*🎯 {self.service_name} 全球最低价格排名 (个人1年预付费)*"]
        message_lines.append("")

        for item in top_10_data[:top_n]:
            rank = item.get("rank", 0)
            country_code = item.get("country_code", "N/A").upper()

            # 获取中文国家名
            country_name_cn = (
                item.get("country_name_cn")
                or SUPPORTED_COUNTRIES.get(country_code, {}).get("name_cn")
                or COUNTRY_CODES_CN.get(country_code)
                or COUNTRY_CODES.get(country_code)
                or item.get("country_name", country_code)
            )

            country_flag = get_country_flag(country_code)

            # 提取价格信息
            currency = item.get("currency", "")
            price_number = item.get("price_number", "")
            price_cny = item.get("price_cny", 0)
            original_price = item.get("original_price", "价格未知")
            
            # 检查是否有实际总价格信息
            total_price_number = item.get("total_price_number", "")
            total_price_cny = item.get("total_price_cny", 0)

            # 格式化价格显示 - 预付费排行榜优先显示总价格
            if total_price_number and total_price_cny > 0:
                # 预付费排行榜显示总价格 + 等效月费
                if currency and price_number and price_cny > 0:
                    price_display = f"{currency} {total_price_number} ≈ ¥{total_price_cny:.2f} (等效月费 ¥{price_cny:.2f})"
                else:
                    price_display = f"{currency} {total_price_number} ≈ ¥{total_price_cny:.2f}"
            elif currency and price_number and price_cny > 0:
                price_display = f"{currency} {price_number} ≈ ¥{price_cny:.2f}"
            elif price_cny > 0:
                price_display = f"{original_price} ≈ ¥{price_cny:.2f}"
            else:
                price_display = original_price

            # 排名表情符号
            if rank == 1:
                rank_emoji = "🥇"
            elif rank == 2:
                rank_emoji = "🥈"
            elif rank == 3:
                rank_emoji = "🥉"
            elif rank <= 10:
                rank_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
                rank_emoji = rank_emojis[rank - 1]
            else:
                rank_emoji = f"{rank}."

            message_lines.append(f"{rank_emoji} {country_name_cn} ({country_code}) {country_flag}")
            message_lines.append(f"🎯 个人1年预付费: {price_display}")

            # 添加空行（除了最后一个）
            if rank < len(top_10_data[:top_n]):
                message_lines.append("")

        # 添加更新时间
        updated_at = self.data.get("_top_10_cheapest_individual_1year_prepaid", {}).get("updated_at", "")
        if updated_at:
            message_lines.append("")
            message_lines.append(f"⏱ 数据更新时间：{updated_at}")
        elif self.cache_timestamp:
            update_time_str = datetime.fromtimestamp(self.cache_timestamp).strftime("%Y-%m-%d %H:%M:%S")
            message_lines.append("")
            message_lines.append(f"⏱ 数据更新时间 (缓存)：{update_time_str}")

        body_text = "\n".join(message_lines).strip()
        return foldable_text_with_markdown_v2(body_text)

    async def get_top_prepaid_family(self, top_n: int = 10) -> str:
        """获取最便宜的家庭1年预付费套餐排行榜"""
        if not self.data:
            error_msg = f"❌ 错误：未能加载 {self.service_name} 价格数据。"
            return foldable_text_v2(error_msg)

        # 使用预先计算的家庭1年预付费数据
        top_10_data = self.data.get("_top_10_cheapest_family_1year_prepaid", {}).get("data", [])

        if not top_10_data:
            error_msg = f"❌ 未找到 {self.service_name} 家庭1年预付费价格信息。"
            return foldable_text_v2(error_msg)

        # 组装原始文本
        message_lines = [f"*👨‍👩‍👧‍👦 {self.service_name} 全球最低价格排名 (家庭1年预付费)*"]
        message_lines.append("")

        for item in top_10_data[:top_n]:
            rank = item.get("rank", 0)
            country_code = item.get("country_code", "N/A").upper()

            # 获取中文国家名
            country_name_cn = (
                item.get("country_name_cn")
                or SUPPORTED_COUNTRIES.get(country_code, {}).get("name_cn")
                or COUNTRY_CODES_CN.get(country_code)
                or COUNTRY_CODES.get(country_code)
                or item.get("country_name", country_code)
            )

            country_flag = get_country_flag(country_code)

            # 提取价格信息
            currency = item.get("currency", "")
            price_number = item.get("price_number", "")
            price_cny = item.get("price_cny", 0)
            original_price = item.get("original_price", "价格未知")
            
            # 检查是否有实际总价格信息
            total_price_number = item.get("total_price_number", "")
            total_price_cny = item.get("total_price_cny", 0)

            # 格式化价格显示 - 预付费排行榜优先显示总价格
            if total_price_number and total_price_cny > 0:
                # 预付费排行榜显示总价格 + 等效月费
                if currency and price_number and price_cny > 0:
                    price_display = f"{currency} {total_price_number} ≈ ¥{total_price_cny:.2f} (等效月费 ¥{price_cny:.2f})"
                else:
                    price_display = f"{currency} {total_price_number} ≈ ¥{total_price_cny:.2f}"
            elif currency and price_number and price_cny > 0:
                price_display = f"{currency} {price_number} ≈ ¥{price_cny:.2f}"
            elif price_cny > 0:
                price_display = f"{original_price} ≈ ¥{price_cny:.2f}"
            else:
                price_display = original_price

            # 排名表情符号
            if rank == 1:
                rank_emoji = "🥇"
            elif rank == 2:
                rank_emoji = "🥈"
            elif rank == 3:
                rank_emoji = "🥉"
            elif rank <= 10:
                rank_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
                rank_emoji = rank_emojis[rank - 1]
            else:
                rank_emoji = f"{rank}."

            message_lines.append(f"{rank_emoji} {country_name_cn} ({country_code}) {country_flag}")
            message_lines.append(f"👨‍👩‍👧‍👦 家庭1年预付费: {price_display}")

            # 添加空行（除了最后一个）
            if rank < len(top_10_data[:top_n]):
                message_lines.append("")

        # 添加更新时间
        updated_at = self.data.get("_top_10_cheapest_family_1year_prepaid", {}).get("updated_at", "")
        if updated_at:
            message_lines.append("")
            message_lines.append(f"⏱ 数据更新时间：{updated_at}")
        elif self.cache_timestamp:
            update_time_str = datetime.fromtimestamp(self.cache_timestamp).strftime("%Y-%m-%d %H:%M:%S")
            message_lines.append("")
            message_lines.append(f"⏱ 数据更新时间 (缓存)：{update_time_str}")

        body_text = "\n".join(message_lines).strip()
        return foldable_text_with_markdown_v2(body_text)


# --- Command Handler Setup ---
spotify_price_bot: SpotifyPriceBot | None = None


def set_dependencies(cm, rc: RateConverter):
    """Initializes the SpotifyPriceBot service."""
    global spotify_price_bot
    spotify_price_bot = SpotifyPriceBot(
        service_name="Spotify",
        cache_manager=cm,
        rate_converter=rc,
        cache_duration_seconds=365 * 24 * 3600,  # 1年，通过定时任务清理而非过期
        subdirectory="spotify",
    )


async def spotify_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /sp command."""
    if not spotify_price_bot:
        if update.message:
            error_message = "❌ 错误：Spotify 查询服务未初始化。"
            await send_error(context, update.message.chat_id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        return

    # If no arguments provided, show top 10 cheapest
    if not context.args:
        if not update.message:
            return
        loading_message = "🔍 正在查询 Spotify Premium 全球最低价格排名... ⏳"
        message = await context.bot.send_message(
            chat_id=update.message.chat_id, text=foldable_text_v2(loading_message), parse_mode="MarkdownV2"
        )
        try:
            await spotify_price_bot.load_or_fetch_data(context)
            result = await spotify_price_bot.get_top_cheapest()
            await message.edit_text(result, parse_mode="MarkdownV2", disable_web_page_preview=True)

            # 使用新的消息管理API调度删除任务
            chat_id = update.message.chat_id
            user_command_id = update.message.message_id

            # 对于已经编辑的消息，直接调度删除，使用配置的延迟时间
            from utils.message_manager import _schedule_deletion
            from utils.config_manager import get_config
            config = get_config()
            await _schedule_deletion(context, chat_id, message.message_id, config.auto_delete_delay)  # 使用配置的延迟时间
            await delete_user_command(context, chat_id, user_command_id)

            logger.info(
                f"🔧 Scheduled deletion for Spotify messages - Bot: {message.message_id}, User: {user_command_id}"
            )

        except Exception as e:
            logger.error(f"Error getting top cheapest Spotify prices: {e}", exc_info=True)
            error_message = f"❌ 查询时发生错误: {e}"
            await message.edit_text(foldable_text_v2(error_message), parse_mode="MarkdownV2")
    else:
        await spotify_price_bot.command_handler(update, context)


async def spotify_clean_cache_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /sp_cleancache command."""
    if not spotify_price_bot:
        if update.message:
            error_message = "❌ 错误：Spotify 查询服务未初始化。"
            await send_error(context, update.message.chat_id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        return
    return await spotify_price_bot.clean_cache_command(update, context)


async def spotify_prepaid_individual_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /spi command for individual 1-year prepaid plans."""
    if not spotify_price_bot:
        if update.message:
            error_message = "❌ 错误：Spotify 查询服务未初始化。"
            await send_error(context, update.message.chat_id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        return

    if not update.message:
        return

    loading_message = "🔍 正在查询 Spotify Premium 个人1年预付费全球最低价格排名... ⏳"
    message = await context.bot.send_message(
        chat_id=update.message.chat_id, text=foldable_text_v2(loading_message), parse_mode="MarkdownV2"
    )

    try:
        await spotify_price_bot.load_or_fetch_data(context)
        result = await spotify_price_bot.get_top_prepaid_individual()
        await message.edit_text(result, parse_mode="MarkdownV2", disable_web_page_preview=True)

        # 使用消息管理API调度删除任务
        chat_id = update.message.chat_id
        user_command_id = update.message.message_id

        from utils.message_manager import _schedule_deletion
        from utils.config_manager import get_config
        config = get_config()
        await _schedule_deletion(context, chat_id, message.message_id, config.auto_delete_delay)
        await delete_user_command(context, chat_id, user_command_id)

        logger.info(f"🔧 Scheduled deletion for Spotify prepaid individual messages - Bot: {message.message_id}, User: {user_command_id}")

    except Exception as e:
        logger.error(f"Error getting top prepaid individual Spotify prices: {e}", exc_info=True)
        error_message = f"❌ 查询时发生错误: {e}"
        await message.edit_text(foldable_text_v2(error_message), parse_mode="MarkdownV2")


async def spotify_prepaid_family_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /spf command for family 1-year prepaid plans.""" 
    if not spotify_price_bot:
        if update.message:
            error_message = "❌ 错误：Spotify 查询服务未初始化。"
            await send_error(context, update.message.chat_id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        return

    if not update.message:
        return

    loading_message = "🔍 正在查询 Spotify Premium 家庭1年预付费全球最低价格排名... ⏳"
    message = await context.bot.send_message(
        chat_id=update.message.chat_id, text=foldable_text_v2(loading_message), parse_mode="MarkdownV2"
    )

    try:
        await spotify_price_bot.load_or_fetch_data(context)
        result = await spotify_price_bot.get_top_prepaid_family()
        await message.edit_text(result, parse_mode="MarkdownV2", disable_web_page_preview=True)

        # 使用消息管理API调度删除任务
        chat_id = update.message.chat_id
        user_command_id = update.message.message_id

        from utils.message_manager import _schedule_deletion
        from utils.config_manager import get_config
        config = get_config()
        await _schedule_deletion(context, chat_id, message.message_id, config.auto_delete_delay)
        await delete_user_command(context, chat_id, user_command_id)

        logger.info(f"🔧 Scheduled deletion for Spotify prepaid family messages - Bot: {message.message_id}, User: {user_command_id}")

    except Exception as e:
        logger.error(f"Error getting top prepaid family Spotify prices: {e}", exc_info=True)
        error_message = f"❌ 查询时发生错误: {e}"
        await message.edit_text(foldable_text_v2(error_message), parse_mode="MarkdownV2")


# Alias for the command
sp_command = spotify_command

# Register commands
command_factory.register_command("sp", sp_command, permission=Permission.NONE, description="Spotify订阅价格查询")
command_factory.register_command("spi", spotify_prepaid_individual_command, permission=Permission.NONE, description="Spotify个人1年预付费排行榜")
command_factory.register_command("spf", spotify_prepaid_family_command, permission=Permission.NONE, description="Spotify家庭1年预付费排行榜")
command_factory.register_command(
    "sp_cleancache", spotify_clean_cache_command, permission=Permission.ADMIN, description="清理Spotify缓存"
)
