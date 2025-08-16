"""
时区映射工具
基于 country_data.py 的国家数据，提供国家到时区的映射
"""

from .country_data import SUPPORTED_COUNTRIES, COUNTRY_NAME_TO_CODE, get_country_flag

# 国家代码到主要时区的映射
COUNTRY_TO_TIMEZONE = {
    "AD": "Europe/Andorra",
    "AE": "Asia/Dubai",
    "AG": "America/Antigua",
    "AI": "America/Anguilla",
    "AL": "Europe/Tirane",
    "AM": "Asia/Yerevan",
    "AO": "Africa/Luanda",
    "AR": "America/Argentina/Buenos_Aires",
    "AT": "Europe/Vienna",
    "AU": "Australia/Sydney",  # 注意：澳大利亚有多个时区
    "AZ": "Asia/Baku",
    "BB": "America/Barbados",
    "BE": "Europe/Brussels",
    "BF": "Africa/Ouagadougou",
    "BG": "Europe/Sofia",
    "BH": "Asia/Bahrain",
    "BJ": "Africa/Porto-Novo",
    "BM": "Atlantic/Bermuda",
    "BN": "Asia/Brunei",
    "BO": "America/La_Paz",
    "BR": "America/Sao_Paulo",  # 注意：巴西有多个时区
    "BS": "America/Nassau",
    "BW": "Africa/Gaborone",
    "BY": "Europe/Minsk",
    "BZ": "America/Belize",
    "CA": "America/Toronto",  # 注意：加拿大有多个时区
    "CH": "Europe/Zurich",
    "CL": "America/Santiago",
    "CN": "Asia/Shanghai",
    "CO": "America/Bogota",
    "CR": "America/Costa_Rica",
    "CU": "America/Havana",
    "CV": "Atlantic/Cape_Verde",
    "CY": "Asia/Nicosia",
    "CZ": "Europe/Prague",
    "DE": "Europe/Berlin",
    "DK": "Europe/Copenhagen",
    "DM": "America/Dominica",
    "DO": "America/Santo_Domingo",
    "DZ": "Africa/Algiers",
    "EC": "America/Guayaquil",
    "EE": "Europe/Tallinn",
    "EG": "Africa/Cairo",
    "ES": "Europe/Madrid",
    "FI": "Europe/Helsinki",
    "FJ": "Pacific/Fiji",
    "FM": "Pacific/Chuuk",
    "FR": "Europe/Paris",
    "GB": "Europe/London",
    "GD": "America/Grenada",
    "GH": "Africa/Accra",
    "GM": "Africa/Banjul",
    "GR": "Europe/Athens",
    "GT": "America/Guatemala",
    "GW": "Africa/Bissau",
    "GY": "America/Guyana",
    "HK": "Asia/Hong_Kong",
    "HN": "America/Tegucigalpa",
    "HR": "Europe/Zagreb",
    "HT": "America/Port-au-Prince",
    "HU": "Europe/Budapest",
    "ID": "Asia/Jakarta",  # 注意：印尼有多个时区
    "IE": "Europe/Dublin",
    "IL": "Asia/Jerusalem",
    "IN": "Asia/Kolkata",
    "IS": "Atlantic/Reykjavik",
    "IT": "Europe/Rome",
    "JM": "America/Jamaica",
    "JO": "Asia/Amman",
    "JP": "Asia/Tokyo",
    "KE": "Africa/Nairobi",
    "KG": "Asia/Bishkek",
    "KH": "Asia/Phnom_Penh",
    "KN": "America/St_Kitts",
    "KR": "Asia/Seoul",
    "KW": "Asia/Kuwait",
    "KY": "America/Cayman",
    "KZ": "Asia/Almaty",  # 注意：哈萨克斯坦有多个时区
    "LA": "Asia/Vientiane",
    "LB": "Asia/Beirut",
    "LC": "America/St_Lucia",
    "LI": "Europe/Vaduz",
    "LK": "Asia/Colombo",
    "LT": "Europe/Vilnius",
    "LU": "Europe/Luxembourg",
    "LV": "Europe/Riga",
    "MA": "Africa/Casablanca",
    "MD": "Europe/Chisinau",
    "MG": "Indian/Antananarivo",
    "MK": "Europe/Skopje",
    "ML": "Africa/Bamako",
    "MM": "Asia/Yangon",
    "MN": "Asia/Ulaanbaatar",
    "MO": "Asia/Macau",
    "MS": "America/Montserrat",
    "MT": "Europe/Malta",
    "MU": "Indian/Mauritius",
    "MW": "Africa/Blantyre",
    "MX": "America/Mexico_City",
    "MY": "Asia/Kuala_Lumpur",
    "MZ": "Africa/Maputo",
    "NA": "Africa/Windhoek",
    "NE": "Africa/Niamey",
    "NG": "Africa/Lagos",
    "NI": "America/Managua",
    "NL": "Europe/Amsterdam",
    "NO": "Europe/Oslo",
    "NP": "Asia/Kathmandu",
    "NZ": "Pacific/Auckland",
    "OM": "Asia/Muscat",
    "PA": "America/Panama",
    "PE": "America/Lima",
    "PG": "Pacific/Port_Moresby",
    "PH": "Asia/Manila",
    "PK": "Asia/Karachi",
    "PL": "Europe/Warsaw",
    "PT": "Europe/Lisbon",
    "PY": "America/Asuncion",
    "QA": "Asia/Qatar",
    "RO": "Europe/Bucharest",
    "RS": "Europe/Belgrade",
    "RU": "Europe/Moscow",  # 注意：俄罗斯有多个时区
    "RW": "Africa/Kigali",
    "SA": "Asia/Riyadh",
    "SB": "Pacific/Guadalcanal",
    "SC": "Indian/Mahe",
    "SE": "Europe/Stockholm",
    "SG": "Asia/Singapore",
    "SI": "Europe/Ljubljana",
    "SK": "Europe/Bratislava",
    "SL": "Africa/Freetown",
    "SN": "Africa/Dakar",
    "SR": "America/Paramaribo",
    "ST": "Africa/Sao_Tome",
    "SV": "America/El_Salvador",
    "SZ": "Africa/Mbabane",
    "TC": "America/Grand_Turk",
    "TD": "Africa/Ndjamena",
    "TH": "Asia/Bangkok",
    "TJ": "Asia/Dushanbe",
    "TM": "Asia/Ashgabat",
    "TN": "Africa/Tunis",
    "TO": "Pacific/Tongatapu",
    "TR": "Europe/Istanbul",
    "TT": "America/Port_of_Spain",
    "TW": "Asia/Taipei",
    "TZ": "Africa/Dar_es_Salaam",
    "UA": "Europe/Kiev",
    "UG": "Africa/Kampala",
    "US": "America/New_York",  # 注意：美国有多个时区
    "UY": "America/Montevideo",
    "UZ": "Asia/Tashkent",
    "VC": "America/St_Vincent",
    "VE": "America/Caracas",
    "VG": "America/Tortola",
    "VN": "Asia/Ho_Chi_Minh",
    "WS": "Pacific/Apia",
    "YE": "Asia/Aden",
    "ZA": "Africa/Johannesburg",
    "ZM": "Africa/Lusaka",
}

# 城市名称到时区的映射（中文）
CITY_TO_TIMEZONE = {
    "北京": "Asia/Shanghai",
    "上海": "Asia/Shanghai",
    "广州": "Asia/Shanghai",
    "深圳": "Asia/Shanghai",
    "香港": "Asia/Hong_Kong",
    "澳门": "Asia/Macau",
    "台北": "Asia/Taipei",
    "东京": "Asia/Tokyo",
    "大阪": "Asia/Tokyo",
    "首尔": "Asia/Seoul",
    "釜山": "Asia/Seoul",
    "新加坡": "Asia/Singapore",
    "吉隆坡": "Asia/Kuala_Lumpur",
    "曼谷": "Asia/Bangkok",
    "雅加达": "Asia/Jakarta",
    "马尼拉": "Asia/Manila",
    "胡志明市": "Asia/Ho_Chi_Minh",
    "河内": "Asia/Ho_Chi_Minh",
    "悉尼": "Australia/Sydney",
    "墨尔本": "Australia/Melbourne",
    "珀斯": "Australia/Perth",
    "奥克兰": "Pacific/Auckland",
    "纽约": "America/New_York",
    "洛杉矶": "America/Los_Angeles",
    "芝加哥": "America/Chicago",
    "丹佛": "America/Denver",
    "拉斯维加斯": "America/Los_Angeles",
    "旧金山": "America/Los_Angeles",
    "西雅图": "America/Los_Angeles",
    "迈阿密": "America/New_York",
    "伦敦": "Europe/London",
    "巴黎": "Europe/Paris",
    "柏林": "Europe/Berlin",
    "罗马": "Europe/Rome",
    "马德里": "Europe/Madrid",
    "阿姆斯特丹": "Europe/Amsterdam",
    "苏黎世": "Europe/Zurich",
    "维也纳": "Europe/Vienna",
    "莫斯科": "Europe/Moscow",
    "圣彼得堡": "Europe/Moscow",
    "迪拜": "Asia/Dubai",
    "多哈": "Asia/Qatar",
    "利雅得": "Asia/Riyadh",
    "开罗": "Africa/Cairo",
    "约翰内斯堡": "Africa/Johannesburg",
    "拉各斯": "Africa/Lagos",
    "内罗毕": "Africa/Nairobi",
    "孟买": "Asia/Kolkata",
    "新德里": "Asia/Kolkata",
    "班加罗尔": "Asia/Kolkata",
    "卡拉奇": "Asia/Karachi",
    "伊斯坦布尔": "Europe/Istanbul",
    "德黑兰": "Asia/Tehran",
}

def resolve_timezone_with_country_data(user_input: str) -> tuple[str, dict]:
    """
    使用国家数据解析时区
    返回: (timezone, country_info)
    """
    if not user_input:
        return "UTC", {}
    
    normalized_input = user_input.strip()
    
    # 1. 检查是否是城市名
    if normalized_input in CITY_TO_TIMEZONE:
        timezone = CITY_TO_TIMEZONE[normalized_input]
        # 尝试从时区推断国家
        country_info = get_country_from_timezone(timezone)
        return timezone, country_info
    
    # 2. 检查是否是国家名（中文）
    if normalized_input in COUNTRY_NAME_TO_CODE:
        country_code = COUNTRY_NAME_TO_CODE[normalized_input]
        if country_code in COUNTRY_TO_TIMEZONE:
            timezone = COUNTRY_TO_TIMEZONE[country_code]
            country_info = {
                "code": country_code,
                "name": SUPPORTED_COUNTRIES[country_code]["name"],
                "flag": get_country_flag(country_code),
                "currency": SUPPORTED_COUNTRIES[country_code]["currency"],
                "symbol": SUPPORTED_COUNTRIES[country_code]["symbol"]
            }
            return timezone, country_info
    
    # 3. 检查是否是国家代码
    country_code_upper = normalized_input.upper()
    if country_code_upper in SUPPORTED_COUNTRIES and country_code_upper in COUNTRY_TO_TIMEZONE:
        timezone = COUNTRY_TO_TIMEZONE[country_code_upper]
        country_info = {
            "code": country_code_upper,
            "name": SUPPORTED_COUNTRIES[country_code_upper]["name"],
            "flag": get_country_flag(country_code_upper),
            "currency": SUPPORTED_COUNTRIES[country_code_upper]["currency"],
            "symbol": SUPPORTED_COUNTRIES[country_code_upper]["symbol"]
        }
        return timezone, country_info
    
    # 4. 假设是IANA时区名，直接返回
    return normalized_input, {}

def get_country_from_timezone(timezone: str) -> dict:
    """从时区推断国家信息"""
    for country_code, tz in COUNTRY_TO_TIMEZONE.items():
        if tz == timezone:
            return {
                "code": country_code,
                "name": SUPPORTED_COUNTRIES[country_code]["name"],
                "flag": get_country_flag(country_code),
                "currency": SUPPORTED_COUNTRIES[country_code]["currency"],
                "symbol": SUPPORTED_COUNTRIES[country_code]["symbol"]
            }
    return {}

def get_supported_countries_for_timezone():
    """获取支持时区查询的国家列表"""
    supported = []
    for country_code in sorted(COUNTRY_TO_TIMEZONE.keys()):
        if country_code in SUPPORTED_COUNTRIES:
            country_info = SUPPORTED_COUNTRIES[country_code]
            supported.append({
                "code": country_code,
                "name": country_info["name"],
                "flag": get_country_flag(country_code),
                "timezone": COUNTRY_TO_TIMEZONE[country_code]
            })
    return supported

def get_supported_cities():
    """获取支持的城市列表"""
    return list(CITY_TO_TIMEZONE.keys())