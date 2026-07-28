import logging
from typing import Any

import httpx
from telegram.ext import ContextTypes

from utils.country_data import COUNTRY_NAME_TO_CODE, SUPPORTED_COUNTRIES, get_country_flag
from utils.formatter import foldable_text_v2, foldable_text_with_markdown_v2
from utils.price_formatter import get_rank_emoji, format_cache_timestamp
from utils.price_query_service import PriceQueryService


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
class MaxPriceBot(PriceQueryService):
    PRICE_URL = (
        "https://raw.githubusercontent.com/SzeMeng76/hbo-max-global-prices/refs/heads/main/max_prices_cny_sorted.json"
    )

    async def _fetch_data(self, context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any] | None:
        """Fetches HBO Max price data from the specified URL."""
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
            logger.error(f"Failed to fetch HBO Max price data: {e}")
            return None
        except Exception as e:
            logger.error(f"An unexpected error occurred while fetching HBO Max data: {e}")
            return None

    def _init_country_mapping(self) -> dict[str, Any]:
        """Initializes country name and code to data mapping."""
        mapping = {}
        if not self.data:
            return mapping

        # Skip the metadata entries and only process country data
        for key, value in self.data.items():
            if key.startswith("_"):  # Skip metadata entries like _top_10_cheapest_all
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

        # Plan name translation mapping for HBO Max
        plan_names = {
            # Basic HBO Max plans
            "HBO Max Basic": "基础版 (HBO Max Basic)",
            "HBO Max Ultimate": "旗舰版 (HBO Max Ultimate)",
            "HBO Max (With Ads)": "含广告版 (HBO Max With Ads)",
            "HBO Max (Ad-Free)": "无广告版 (HBO Max Ad-Free)",
            
            # Standard plan types (统一后的标准名称)
            "Mobile": "手机版 (Mobile)",
            "Standard": "标准版 (Standard)", 
            "Ultimate": "至尊版 (Ultimate)",  # Platino映射后的统一名称
            "Premium": "高级版 (Premium)",
            "Basic": "基础版 (Basic)",
            
            # Legacy names (向后兼容)
            "Ponsel": "手机版 (Ponsel)",
            "Standar": "标准版 (Standar)",
            "Platinum": "白金版 (Platinum)",
            
            # Spanish/Latin America plans (原始名称显示)
            "Básico con Anuncios": "基础版含广告 (Básico con Anuncios)",
            "Estándar": "标准版 (Estándar)",
            "Platino": "至尊版 (Platino → Ultimate)",  # 显示映射关系
            
            # 繁体中文套餐名（台湾、香港）
            "標準": "标准版 (標準 → Standard)",
            "高級": "至尊版 (高級 → Ultimate)",
            "手機": "手机版 (手機 → Mobile)",
            "基礎": "基础版 (基礎 → Basic)",
            
            # Bundle plans
            "HBO Max + TNT Sports Basic": "HBO Max + TNT Sports 基础版",
            "HBO Max + TNT Sports Standard": "HBO Max + TNT Sports 标准版",
            "HBO Max + TNT Sports Premium": "HBO Max + TNT Sports 高级版",
        }

        # Group plans by billing cycle for better organization
        monthly_plans = []
        yearly_plans = []
        other_plans = []

        for plan in plans:
            plan_group = plan.get("plan_group", "unknown")
            if plan_group == "monthly":
                monthly_plans.append(plan)
            elif plan_group == "yearly":
                yearly_plans.append(plan)
            else:
                other_plans.append(plan)

        # Display monthly plans first, then yearly, then others
        sorted_plans = monthly_plans + yearly_plans + other_plans

        for i, plan in enumerate(sorted_plans):
            plan_name = plan.get("plan_name", "未知套餐")
            plan_group = plan.get("plan_group", "unknown")
            
            # For bundle plans, use original_name or name instead of translated plan_name
            if plan_group == "bundle":
                bundle_name = plan.get("original_name") or plan.get("name", plan_name)
                plan_name_cn = f"套餐包 ({bundle_name})"
            else:
                plan_name_cn = plan_names.get(plan_name, plan_name)

            # Extract currency, price_number and price_cny
            original_currency = plan.get("original_currency", "")
            original_price_number = plan.get("original_price_number", "")
            monthly_price = plan.get("monthly_price", original_price_number)  # 获取月价格用于显示
            price_cny = plan.get("price_cny", 0)
            original_price = plan.get("original_price", "价格未知")
            billing_cycle = plan.get("billing_cycle", "")

            # Determine the connector
            is_last_plan = i == len(sorted_plans) - 1
            connector = "" if is_last_plan else ""

            # Format price display with currency, price_number, and CNY
            # 对于年付套餐，显示月价格但标注是年付
            if original_currency and price_cny > 0:
                if billing_cycle and "年" in billing_cycle:
                    # 年付套餐：显示月价格 × 12 = 年价格
                    if monthly_price and float(monthly_price) != float(original_price_number):
                        price_display = f"{original_currency} {monthly_price}/月 × 12 = {original_currency} {original_price_number}/年 ≈ ¥{price_cny:.2f}"
                    else:
                        price_display = f"{original_currency} {original_price_number} ({billing_cycle}) ≈ ¥{price_cny:.2f}"
                elif billing_cycle:
                    price_display = f"{original_currency} {original_price_number} ({billing_cycle}) ≈ ¥{price_cny:.2f}"
                else:
                    price_display = f"{original_currency} {original_price_number} ≈ ¥{price_cny:.2f}"
            elif price_cny > 0:
                if billing_cycle:
                    price_display = f"{original_price} ({billing_cycle}) ≈ ¥{price_cny:.2f}"
                else:
                    price_display = f"{original_price} ≈ ¥{price_cny:.2f}"
            else:
                price_display = original_price

            lines.append(f"{connector}💰 {plan_name_cn}：{price_display}")

        return "\n".join(lines)

    def _extract_comparison_price(self, item: dict) -> float | None:
        """Extracts the cheapest plan's CNY price for ranking."""
        plans = item.get("plans", [])
        if not plans:
            return None
        
        # Find the cheapest plan among all available plans
        min_price = None
        for plan in plans:
            price_cny = plan.get("price_cny")
            if price_cny and price_cny > 0:
                if min_price is None or price_cny < min_price:
                    min_price = float(price_cny)
        
        return min_price

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

            country_code = None
            # Extract country code from price_info
            if "plans" in price_info and price_info["plans"]:
                country_code = price_info["plans"][0].get("country_code")
            
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
        raw_message_parts.append(f"*📺 {self.service_name} 订阅价格查询*")
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
            raw_message_parts.append("")  # Empty line before timestamp
            raw_message_parts.append(format_cache_timestamp(self.cache_timestamp))

        # Join and apply formatting
        raw_final_message = "\n".join(raw_message_parts).strip()
        return foldable_text_with_markdown_v2(raw_final_message)

    async def get_top_cheapest(self, top_n: int = 10, category: str = "ultimate_yearly") -> str:
        """Gets the top cheapest countries by category."""
        if not self.data:
            error_msg = f"❌ 错误：未能加载 {self.service_name} 价格数据。"
            return foldable_text_v2(error_msg)

        # Map categories to data keys - 新增ultimate年付分类
        category_mapping = {
            "all": "_top_10_cheapest_all",
            "monthly": "_top_10_cheapest_monthly", 
            "yearly": "_top_10_cheapest_yearly",
            "ultimate": "_top_10_cheapest_ultimate",
            "ultimate_yearly": "_top_10_cheapest_ultimate_yearly",  # 新增
            "mobile": "_top_10_cheapest_mobile",
            "standard": "_top_10_cheapest_standard"
        }
        
        category_names = {
            "all": "全部套餐",
            "monthly": "月付套餐",
            "yearly": "年付套餐", 
            "ultimate": "Ultimate套餐",
            "ultimate_yearly": "Ultimate年付套餐",  # 新增
            "mobile": "Mobile套餐",
            "standard": "Standard套餐"
        }

        data_key = category_mapping.get(category, "_top_10_cheapest_ultimate_yearly")  # 默认改为ultimate年付
        category_name = category_names.get(category, "Ultimate年付套餐")

        # Use the pre-calculated top 10 data if available
        top_10_data = self.data.get(data_key, {}).get("data", [])

        if top_10_data:
            # 组装原始文本，不转义
            message_lines = [f"*🏆 {self.service_name} 全球最低价格排名 ({category_name})*"]
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
                original_currency = item.get("original_currency", "")
                original_price_number = item.get("original_price_number", "")
                monthly_price = item.get("monthly_price", original_price_number)  # 获取月价格用于显示
                price_cny = item.get("price_cny", 0)
                original_price = item.get("original_price", "价格未知")
                plan_name = item.get("plan_name", "未知套餐")
                billing_cycle = item.get("billing_cycle", "")

                # Format price display with currency, price_number, and CNY
                # 对于年付套餐，显示更清晰的价格格式
                if original_currency and price_cny > 0:
                    if billing_cycle and "年" in billing_cycle:
                        # 年付套餐：显示月价格 × 12 = 年价格
                        if monthly_price and float(monthly_price) != float(original_price_number):
                            price_display = f"{original_currency} {monthly_price}/月 × 12 = {original_currency} {original_price_number}/年 ≈ ¥{price_cny:.2f}"
                        else:
                            price_display = f"{original_currency} {original_price_number} ({billing_cycle}) ≈ ¥{price_cny:.2f}"
                    elif billing_cycle:
                        price_display = f"{original_currency} {original_price_number} ({billing_cycle}) ≈ ¥{price_cny:.2f}"
                    else:
                        price_display = f"{original_currency} {original_price_number} ≈ ¥{price_cny:.2f}"
                elif price_cny > 0:
                    if billing_cycle:
                        price_display = f"{original_price} ({billing_cycle}) ≈ ¥{price_cny:.2f}"
                    else:
                        price_display = f"{original_price} ≈ ¥{price_cny:.2f}"
                else:
                    price_display = original_price

                # Rank emoji
                rank_emoji = get_rank_emoji(rank)

                message_lines.append(f"{rank_emoji} {country_name_cn} ({country_code}) {country_flag}")
                message_lines.append(f"💰 {plan_name}: {price_display}")

                # Add blank line between countries (except for the last one)
                if rank < len(top_10_data[:top_n]):
                    message_lines.append("")

            # Use update time from metadata, or cache timestamp as fallback
            updated_at = self.data.get(data_key, {}).get("updated_at", "")
            if updated_at:
                message_lines.append("")  # Empty line before timestamp
                message_lines.append(f"⏱ 数据更新时间：{updated_at}")
            elif self.cache_timestamp:
                message_lines.append("")  # Empty line before timestamp
                message_lines.append(format_cache_timestamp(self.cache_timestamp))

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
                error_msg = f"未能找到足够的可比较 {self.service_name} 价格信息。"
                return foldable_text_v2(error_msg)

            countries_with_prices.sort(key=lambda x: x["price"])
            top_countries = countries_with_prices[:top_n]

            # 组装原始文本，不转义
            message_lines = [f"*📺 {self.service_name} 全球最低价格排名 ({category_name})*"]
            message_lines.append("")  # Empty line after header

            for idx, country_data in enumerate(top_countries, 1):
                item = country_data["data"]
                plans = item.get("plans", [])
                if not plans:
                    continue
                    
                country_code = plans[0].get("country_code", "N/A").upper()
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

                # Find the cheapest plan details
                cheapest_plan = None
                for plan in plans:
                    plan_price = plan.get("price_cny", 0)
                    if plan_price == price_cny:
                        cheapest_plan = plan
                        break

                if cheapest_plan:
                    original_currency = cheapest_plan.get("original_currency", "")
                    original_price_number = cheapest_plan.get("original_price_number", "")
                    original_price = cheapest_plan.get("original_price", "价格未知")
                    plan_name = cheapest_plan.get("plan_name", "未知套餐")
                    billing_cycle = cheapest_plan.get("billing_cycle", "")

                    # Format price display
                    if original_currency and original_price_number and price_cny > 0:
                        if billing_cycle:
                            price_display = f"{original_currency} {original_price_number} ({billing_cycle}) ≈ ¥{price_cny:.2f}"
                        else:
                            price_display = f"{original_currency} {original_price_number} ≈ ¥{price_cny:.2f}"
                    elif price_cny > 0:
                        if billing_cycle:
                            price_display = f"{original_price} ({billing_cycle}) ≈ ¥{price_cny:.2f}"
                        else:
                            price_display = f"{original_price} ≈ ¥{price_cny:.2f}"
                    else:
                        price_display = original_price
                else:
                    plan_name = "最低价格套餐"
                    price_display = f"≈ ¥{price_cny:.2f}"

                # Rank emoji
                rank_emoji = get_rank_emoji(idx)

                message_lines.append(f"{rank_emoji} {country_name_cn} ({country_code}) {country_flag}")
                message_lines.append(f"💰 {plan_name}: {price_display}")

                # Add blank line between countries (except for the last one)
                if idx < len(top_countries):
                    message_lines.append("")

            if self.cache_timestamp:
                message_lines.append("")  # Empty line before timestamp
                message_lines.append(format_cache_timestamp(self.cache_timestamp))

        # 组装完整文本，使用 foldable_text_with_markdown_v2 处理MarkdownV2格式
        body_text = "\n".join(message_lines).strip()
        return foldable_text_with_markdown_v2(body_text)
