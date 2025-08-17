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
    "AU": "Australia/Sydney",  # 注意：澳大利亚有多个时区，默认东部时间
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
    "BR": "America/Sao_Paulo",  # 注意：巴西有多个时区，默认巴西利亚时间
    "BS": "America/Nassau",
    "BW": "Africa/Gaborone",
    "BY": "Europe/Minsk",
    "BZ": "America/Belize",
    "CA": "America/Toronto",  # 注意：加拿大有多个时区，默认东部时间
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
    "RU": "Europe/Moscow",  # 注意：俄罗斯有多个时区，默认莫斯科时间
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
    "US": "America/New_York",  # 注意：美国有多个时区，默认东部时间
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

# 美国各时区映射
US_TIMEZONES = {
    "America/New_York": ["纽约", "华盛顿", "波士顿", "亚特兰大", "迈阿密", "费城", "巴尔的摩", "底特律", "匹兹堡", "夏洛特"],
    "America/Chicago": ["芝加哥", "达拉斯", "休斯顿", "明尼阿波利斯", "新奥尔良", "堪萨斯城", "圣安东尼奥", "奥斯汀", "孟菲斯"],
    "America/Denver": ["丹佛", "盐湖城", "阿尔伯克基", "博伊西", "夏延", "比林斯"],
    "America/Los_Angeles": ["洛杉矶", "旧金山", "西雅图", "波特兰", "拉斯维加斯", "圣地亚哥", "萨克拉门托", "弗雷斯诺"],
    "America/Phoenix": ["凤凰城", "图森"],  # 亚利桑那州大部分不使用夏时制
    "America/Anchorage": ["安克雷奇", "费尔班克斯"],
    "America/Honolulu": ["檀香山", "希洛"],
    "America/Adak": ["阿达克"],  # 阿留申群岛
}

# 加拿大各时区映射
CANADA_TIMEZONES = {
    "America/St_Johns": ["圣约翰斯"],  # 纽芬兰时间
    "America/Halifax": ["哈利法克斯", "弗雷德里克顿", "夏洛特敦"],  # 大西洋时间
    "America/Toronto": ["多伦多", "渥太华", "蒙特利尔", "魁北克城", "哈密尔顿"],  # 东部时间
    "America/Winnipeg": ["温尼伯", "里贾纳", "萨斯卡通"],  # 中部时间
    "America/Edmonton": ["埃德蒙顿", "卡尔加里"],  # 山地时间
    "America/Vancouver": ["温哥华", "维多利亚"],  # 太平洋时间
    "America/Whitehorse": ["白马市"],  # 育空时间
    "America/Yellowknife": ["黄刀镇"],  # 西北地区时间
    "America/Iqaluit": ["伊魁特"],  # 努纳武特东部时间
}

# 澳大利亚各时区映射
AUSTRALIA_TIMEZONES = {
    "Australia/Perth": ["珀斯"],  # 西澳时间
    "Australia/Darwin": ["达尔文"],  # 中澳时间
    "Australia/Adelaide": ["阿德莱德"],  # 中澳时间（夏时制）
    "Australia/Brisbane": ["布里斯班"],  # 东澳时间
    "Australia/Sydney": ["悉尼", "墨尔本", "堪培拉"],  # 东澳时间（夏时制）
    "Australia/Hobart": ["霍巴特"],  # 塔斯马尼亚时间
    "Australia/Lord_Howe": ["豪勋爵岛"],  # 豪勋爵岛时间
}

# 俄罗斯主要时区映射
RUSSIA_TIMEZONES = {
    "Europe/Moscow": ["莫斯科", "圣彼得堡", "下诺夫哥罗德", "喀山", "萨马拉"],  # 莫斯科时间
    "Asia/Yekaterinburg": ["叶卡捷琳堡", "车里雅宾斯克", "彼尔姆"],  # 叶卡捷琳堡时间
    "Asia/Omsk": ["鄂木斯克"],  # 鄂木斯克时间
    "Asia/Krasnoyarsk": ["克拉斯诺亚尔斯克", "新西伯利亚"],  # 克拉斯诺亚尔斯克时间
    "Asia/Irkutsk": ["伊尔库茨克"],  # 伊尔库茨克时间
    "Asia/Yakutsk": ["雅库茨克"],  # 雅库茨克时间
    "Asia/Vladivostok": ["符拉迪沃斯托克", "哈巴罗夫斯克"],  # 符拉迪沃斯托克时间
    "Asia/Magadan": ["马加丹"],  # 马加丹时间
    "Asia/Kamchatka": ["彼得罗巴甫洛夫斯克"],  # 堪察加时间
}

# 巴西各时区映射
BRAZIL_TIMEZONES = {
    "America/Sao_Paulo": ["圣保罗", "里约热内卢", "贝洛奥里藏特", "萨尔瓦多", "库里提巴"],  # 巴西利亚时间
    "America/Manaus": ["马瑙斯", "波多韦柳"],  # 亚马逊时间
    "America/Fortaleza": ["福塔莱萨", "累西腓", "纳塔尔"],  # 巴西东北时间
    "America/Noronha": ["费尔南多·迪诺罗尼亚"],  # 费尔南多时间
    "America/Rio_Branco": ["里奥布兰科"],  # 阿克里时间
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
    # 美国城市
    "纽约": "America/New_York",
    "华盛顿": "America/New_York",
    "波士顿": "America/New_York",
    "亚特兰大": "America/New_York",
    "迈阿密": "America/New_York",
    "费城": "America/New_York",
    "巴尔的摩": "America/New_York",
    "底特律": "America/New_York",
    "匹兹堡": "America/New_York",
    "夏洛特": "America/New_York",
    "芝加哥": "America/Chicago",
    "达拉斯": "America/Chicago",
    "休斯顿": "America/Chicago",
    "明尼阿波利斯": "America/Chicago",
    "新奥尔良": "America/Chicago",
    "堪萨斯城": "America/Chicago",
    "圣安东尼奥": "America/Chicago",
    "奥斯汀": "America/Chicago",
    "孟菲斯": "America/Chicago",
    "丹佛": "America/Denver",
    "盐湖城": "America/Denver",
    "阿尔伯克基": "America/Denver",
    "博伊西": "America/Denver",
    "夏延": "America/Denver",
    "比林斯": "America/Denver",
    "洛杉矶": "America/Los_Angeles",
    "旧金山": "America/Los_Angeles",
    "西雅图": "America/Los_Angeles",
    "波特兰": "America/Los_Angeles",
    "拉斯维加斯": "America/Los_Angeles",
    "圣地亚哥": "America/Los_Angeles",
    "萨克拉门托": "America/Los_Angeles",
    "弗雷斯诺": "America/Los_Angeles",
    "凤凰城": "America/Phoenix",
    "图森": "America/Phoenix",
    "安克雷奇": "America/Anchorage",
    "费尔班克斯": "America/Anchorage",
    "檀香山": "America/Honolulu",
    "希洛": "America/Honolulu",
    "阿达克": "America/Adak",
    # 加拿大城市
    "圣约翰斯": "America/St_Johns",
    "哈利法克斯": "America/Halifax",
    "弗雷德里克顿": "America/Halifax",
    "夏洛特敦": "America/Halifax",
    "多伦多": "America/Toronto",
    "渥太华": "America/Toronto",
    "蒙特利尔": "America/Toronto",
    "魁北克城": "America/Toronto",
    "哈密尔顿": "America/Toronto",
    "温尼伯": "America/Winnipeg",
    "里贾纳": "America/Winnipeg",
    "萨斯卡通": "America/Winnipeg",
    "埃德蒙顿": "America/Edmonton",
    "卡尔加里": "America/Edmonton",
    "温哥华": "America/Vancouver",
    "维多利亚": "America/Vancouver",
    "白马市": "America/Whitehorse",
    "黄刀镇": "America/Yellowknife",
    "伊魁特": "America/Iqaluit",
    # 澳大利亚城市
    # "珀斯": "Australia/Perth",  # 重复，已在上面定义
    "达尔文": "Australia/Darwin",
    "阿德莱德": "Australia/Adelaide",
    "布里斯班": "Australia/Brisbane",
    "堪培拉": "Australia/Sydney",
    "霍巴特": "Australia/Hobart",
    "豪勋爵岛": "Australia/Lord_Howe",
    # 俄罗斯城市
    "圣彼得堡": "Europe/Moscow",
    "下诺夫哥罗德": "Europe/Moscow",
    "喀山": "Europe/Moscow",
    "萨马拉": "Europe/Moscow",
    "叶卡捷琳堡": "Asia/Yekaterinburg",
    "车里雅宾斯克": "Asia/Yekaterinburg",
    "彼尔姆": "Asia/Yekaterinburg",
    "鄂木斯克": "Asia/Omsk",
    "克拉斯诺亚尔斯克": "Asia/Krasnoyarsk",
    "新西伯利亚": "Asia/Krasnoyarsk",
    "伊尔库茨克": "Asia/Irkutsk",
    "雅库茨克": "Asia/Yakutsk",
    "符拉迪沃斯托克": "Asia/Vladivostok",
    "哈巴罗夫斯克": "Asia/Vladivostok",
    "马加丹": "Asia/Magadan",
    "彼得罗巴甫洛夫斯克": "Asia/Kamchatka",
    # 巴西城市
    "里约热内卢": "America/Sao_Paulo",
    "贝洛奥里藏特": "America/Sao_Paulo",
    "萨尔瓦多": "America/Sao_Paulo",
    "库里提巴": "America/Sao_Paulo",
    "马瑙斯": "America/Manaus",
    "波多韦柳": "America/Manaus",
    "福塔莱萨": "America/Fortaleza",
    "累西腓": "America/Fortaleza",
    "纳塔尔": "America/Fortaleza",
    "费尔南多·迪诺罗尼亚": "America/Noronha",
    "里奥布兰科": "America/Rio_Branco",
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
    # 1. 先检查单时区国家
    for country_code, tz in COUNTRY_TO_TIMEZONE.items():
        if tz == timezone:
            return {
                "code": country_code,
                "name": SUPPORTED_COUNTRIES[country_code]["name"],
                "flag": get_country_flag(country_code),
                "currency": SUPPORTED_COUNTRIES[country_code]["currency"],
                "symbol": SUPPORTED_COUNTRIES[country_code]["symbol"]
            }
    
    # 2. 检查多时区国家
    multi_timezone_countries = {
        "US": US_TIMEZONES,
        "CA": CANADA_TIMEZONES,
        "AU": AUSTRALIA_TIMEZONES,
        "RU": RUSSIA_TIMEZONES,
        "BR": BRAZIL_TIMEZONES,
    }
    
    for country_code, timezones in multi_timezone_countries.items():
        if timezone in timezones.keys():
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

def get_country_timezones(country_code: str) -> dict:
    """获取指定国家的所有时区信息"""
    country_code = country_code.upper()
    
    # 多时区国家的特殊处理
    if country_code == "US":
        return US_TIMEZONES
    elif country_code == "CA":
        return CANADA_TIMEZONES
    elif country_code == "AU":
        return AUSTRALIA_TIMEZONES
    elif country_code == "RU":
        return RUSSIA_TIMEZONES
    elif country_code == "BR":
        return BRAZIL_TIMEZONES
    else:
        # 单时区国家
        if country_code in COUNTRY_TO_TIMEZONE:
            return {COUNTRY_TO_TIMEZONE[country_code]: []}
        return {}

def get_all_supported_timezones():
    """获取所有支持的时区列表"""
    timezones = set()
    
    # 添加单时区国家的时区
    for tz in COUNTRY_TO_TIMEZONE.values():
        timezones.add(tz)
    
    # 添加多时区国家的时区
    for tz_dict in [US_TIMEZONES, CANADA_TIMEZONES, AUSTRALIA_TIMEZONES, RUSSIA_TIMEZONES, BRAZIL_TIMEZONES]:
        timezones.update(tz_dict.keys())
    
    # 添加城市映射中的时区
    timezones.update(CITY_TO_TIMEZONE.values())
    
    return sorted(list(timezones))