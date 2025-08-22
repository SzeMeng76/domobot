#!/usr/bin/env python3
"""
机场数据映射
支持城市名称、国家名称、机场代码的灵活搜索
"""

# 主要机场代码映射 - 支持中英文城市名称和国家名称
AIRPORT_MAPPINGS = {
    # 中国主要机场
    "北京": ["PEK", "PKX"],  # 首都国际机场, 大兴国际机场
    "beijing": ["PEK", "PKX"],
    "上海": ["PVG", "SHA"],  # 浦东国际机场, 虹桥机场  
    "shanghai": ["PVG", "SHA"],
    "广州": ["CAN"],  # 白云国际机场
    "guangzhou": ["CAN"],
    "深圳": ["SZX"],  # 宝安国际机场
    "shenzhen": ["SZX"],
    "成都": ["CTU", "TFU"],  # 双流国际机场, 天府国际机场
    "chengdu": ["CTU", "TFU"],
    "重庆": ["CKG"],  # 江北国际机场
    "chongqing": ["CKG"],
    "西安": ["XIY"],  # 咸阳国际机场
    "xian": ["XIY"],
    "杭州": ["HGH"],  # 萧山国际机场
    "hangzhou": ["HGH"],
    "南京": ["NKG"],  # 禄口国际机场
    "nanjing": ["NKG"],
    "青岛": ["TAO"],  # 胶东国际机场
    "qingdao": ["TAO"],
    
    # 香港、澳门、台湾
    "香港": ["HKG"],
    "hong kong": ["HKG"],
    "hongkong": ["HKG"],
    "澳门": ["MFM"],
    "macau": ["MFM"],
    "台北": ["TPE", "TSA"],  # 桃园国际机场, 松山机场
    "taipei": ["TPE", "TSA"],
    
    # 美国主要机场
    "纽约": ["JFK", "LGA", "EWR"],  # 肯尼迪, 拉瓜迪亚, 纽瓦克
    "new york": ["JFK", "LGA", "EWR"],
    "洛杉矶": ["LAX"],
    "los angeles": ["LAX"],
    "旧金山": ["SFO"],
    "san francisco": ["SFO"],
    "芝加哥": ["ORD", "MDW"],  # 奥黑尔, 中途岛
    "chicago": ["ORD", "MDW"],
    "西雅图": ["SEA"],
    "seattle": ["SEA"],
    "迈阿密": ["MIA"],
    "miami": ["MIA"],
    "拉斯维加斯": ["LAS"],
    "las vegas": ["LAS"],
    "波士顿": ["BOS"],
    "boston": ["BOS"],
    "华盛顿": ["DCA", "IAD", "BWI"],  # 里根, 杜勒斯, 巴尔的摩
    "washington": ["DCA", "IAD", "BWI"],
    
    # 欧洲主要机场
    "伦敦": ["LHR", "LGW", "STN", "LTN"],  # 希思罗, 盖特威克, 斯坦斯特德, 卢顿
    "london": ["LHR", "LGW", "STN", "LTN"],
    "巴黎": ["CDG", "ORY"],  # 戴高乐, 奥利
    "paris": ["CDG", "ORY"],
    "法兰克福": ["FRA"],
    "frankfurt": ["FRA"],
    "阿姆斯特丹": ["AMS"],
    "amsterdam": ["AMS"],
    "慕尼黑": ["MUC"],
    "munich": ["MUC"],
    "罗马": ["FCO", "CIA"],  # 菲乌米奇诺, 钱皮诺
    "rome": ["FCO", "CIA"],
    "马德里": ["MAD"],
    "madrid": ["MAD"],
    "巴塞罗那": ["BCN"],
    "barcelona": ["BCN"],
    "苏黎世": ["ZUR"],
    "zurich": ["ZUR"],
    "维也纳": ["VIE"],
    "vienna": ["VIE"],
    
    # 日本主要机场
    "东京": ["NRT", "HND"],  # 成田, 羽田
    "tokyo": ["NRT", "HND"],
    "大阪": ["KIX", "ITM"],  # 关西, 伊丹
    "osaka": ["KIX", "ITM"],
    "名古屋": ["NGO"],  # 中部国际机场
    "nagoya": ["NGO"],
    "福冈": ["FUK"],
    "fukuoka": ["FUK"],
    
    # 韩国主要机场
    "首尔": ["ICN", "GMP"],  # 仁川, 金浦
    "seoul": ["ICN", "GMP"],
    "釜山": ["PUS"],
    "busan": ["PUS"],
    
    # 东南亚主要机场
    "新加坡": ["SIN"],
    "singapore": ["SIN"],
    "曼谷": ["BKK", "DMK"],  # 素万那普, 廊曼
    "bangkok": ["BKK", "DMK"],
    "吉隆坡": ["KUL", "SZB"],  # 吉隆坡国际机场, 梳邦
    "kuala lumpur": ["KUL", "SZB"],
    "雅加达": ["CGK"],
    "jakarta": ["CGK"],
    "马尼拉": ["MNL"],
    "manila": ["MNL"],
    "胡志明市": ["SGN"],
    "ho chi minh": ["SGN"],
    
    # 澳洲主要机场
    "悉尼": ["SYD"],
    "sydney": ["SYD"],
    "墨尔本": ["MEL"],
    "melbourne": ["MEL"],
    "布里斯班": ["BNE"],
    "brisbane": ["BNE"],
    
    # 中东主要机场
    "迪拜": ["DXB", "DWC"],
    "dubai": ["DXB", "DWC"],
    "多哈": ["DOH"],
    "doha": ["DOH"],
    
    # 加拿大主要机场
    "温哥华": ["YVR"],
    "vancouver": ["YVR"],
    "多伦多": ["YYZ"],
    "toronto": ["YYZ"],
    "蒙特利尔": ["YUL"],
    "montreal": ["YUL"],
}

# 国家到主要机场代码的映射
COUNTRY_TO_AIRPORTS = {
    # 使用country_data中的国家代码
    "CN": ["PEK", "PVG", "CAN", "CTU", "SZX"],  # 中国主要机场
    "US": ["JFK", "LAX", "ORD", "DFW", "ATL"],  # 美国主要机场
    "UK": ["LHR", "LGW", "MAN", "EDI", "BHX"],  # 英国主要机场
    "JP": ["NRT", "HND", "KIX", "NGO", "FUK"],  # 日本主要机场
    "KR": ["ICN", "GMP", "PUS", "CJU"],         # 韩国主要机场
    "DE": ["FRA", "MUC", "DUS", "BER", "HAM"],  # 德国主要机场
    "FR": ["CDG", "ORY", "NCE", "LYS", "MRS"],  # 法国主要机场
    "IT": ["FCO", "MXP", "LIN", "NAP", "VCE"],  # 意大利主要机场
    "ES": ["MAD", "BCN", "PMI", "LPA", "SVQ"],  # 西班牙主要机场
    "NL": ["AMS", "RTM", "EIN"],                # 荷兰主要机场
    "CH": ["ZUR", "GVA", "BSL"],                # 瑞士主要机场
    "AT": ["VIE", "SZG", "INN"],                # 奥地利主要机场
    "SG": ["SIN"],                              # 新加坡
    "TH": ["BKK", "DMK", "CNX", "HKT"],        # 泰国主要机场
    "MY": ["KUL", "SZB", "PEN", "JHB"],        # 马来西亚主要机场
    "ID": ["CGK", "DPS", "SUB", "MLG"],        # 印度尼西亚主要机场
    "PH": ["MNL", "CEB", "CRK", "ILO"],        # 菲律宾主要机场
    "VN": ["SGN", "HAN", "DAD"],               # 越南主要机场
    "AU": ["SYD", "MEL", "BNE", "PER", "ADL"], # 澳大利亚主要机场
    "NZ": ["AKL", "CHC", "WLG", "DUD"],        # 新西兰主要机场
    "CA": ["YYZ", "YVR", "YUL", "YYC", "YOW"], # 加拿大主要机场
    "AE": ["DXB", "DWC", "AUH", "SHJ"],        # 阿联酋主要机场
    "QA": ["DOH"],                              # 卡塔尔
    "TR": ["IST", "SAW", "ADB", "AYT"],        # 土耳其主要机场
    "RU": ["SVO", "DME", "VKO", "LED", "KZN"], # 俄罗斯主要机场
    "IN": ["DEL", "BOM", "MAA", "CCU", "BLR"], # 印度主要机场
    "BR": ["GRU", "GIG", "BSB", "CGH", "REC"], # 巴西主要机场
    "MX": ["MEX", "CUN", "GDL", "MTY", "TIJ"], # 墨西哥主要机场
    "AR": ["EZE", "AEP", "COR", "MDZ", "IGR"], # 阿根廷主要机场
}

# 常用机场代码的详细信息
AIRPORT_DETAILS = {
    # 中国机场
    "PEK": {"name": "北京首都国际机场", "city": "北京", "country": "CN"},
    "PKX": {"name": "北京大兴国际机场", "city": "北京", "country": "CN"},
    "PVG": {"name": "上海浦东国际机场", "city": "上海", "country": "CN"},
    "SHA": {"name": "上海虹桥国际机场", "city": "上海", "country": "CN"},
    "CAN": {"name": "广州白云国际机场", "city": "广州", "country": "CN"},
    "SZX": {"name": "深圳宝安国际机场", "city": "深圳", "country": "CN"},
    "CTU": {"name": "成都双流国际机场", "city": "成都", "country": "CN"},
    "TFU": {"name": "成都天府国际机场", "city": "成都", "country": "CN"},
    "CKG": {"name": "重庆江北国际机场", "city": "重庆", "country": "CN"},
    
    # 香港、澳门、台湾
    "HKG": {"name": "香港国际机场", "city": "香港", "country": "HK"},
    "MFM": {"name": "澳门国际机场", "city": "澳门", "country": "MO"},
    "TPE": {"name": "台北桃园国际机场", "city": "台北", "country": "TW"},
    "TSA": {"name": "台北松山机场", "city": "台北", "country": "TW"},
    
    # 美国机场
    "JFK": {"name": "肯尼迪国际机场", "city": "纽约", "country": "US"},
    "LGA": {"name": "拉瓜迪亚机场", "city": "纽约", "country": "US"},
    "EWR": {"name": "纽瓦克自由国际机场", "city": "纽约", "country": "US"},
    "LAX": {"name": "洛杉矶国际机场", "city": "洛杉矶", "country": "US"},
    "SFO": {"name": "旧金山国际机场", "city": "旧金山", "country": "US"},
    "ORD": {"name": "芝加哥奥黑尔国际机场", "city": "芝加哥", "country": "US"},
    "SEA": {"name": "西雅图塔科马国际机场", "city": "西雅图", "country": "US"},
    "MIA": {"name": "迈阿密国际机场", "city": "迈阿密", "country": "US"},
    "LAS": {"name": "麦卡伦国际机场", "city": "拉斯维加斯", "country": "US"},
    "DFW": {"name": "达拉斯沃斯堡国际机场", "city": "达拉斯", "country": "US"},
    
    # 欧洲机场
    "LHR": {"name": "伦敦希思罗机场", "city": "伦敦", "country": "UK"},
    "LGW": {"name": "伦敦盖特威克机场", "city": "伦敦", "country": "UK"},
    "CDG": {"name": "巴黎戴高乐机场", "city": "巴黎", "country": "FR"},
    "ORY": {"name": "巴黎奥利机场", "city": "巴黎", "country": "FR"},
    "FRA": {"name": "法兰克福国际机场", "city": "法兰克福", "country": "DE"},
    "MUC": {"name": "慕尼黑国际机场", "city": "慕尼黑", "country": "DE"},
    "AMS": {"name": "阿姆斯特丹史基浦机场", "city": "阿姆斯特丹", "country": "NL"},
    "FCO": {"name": "罗马菲乌米奇诺机场", "city": "罗马", "country": "IT"},
    "MAD": {"name": "马德里巴拉哈斯机场", "city": "马德里", "country": "ES"},
    "BCN": {"name": "巴塞罗那机场", "city": "巴塞罗那", "country": "ES"},
    "ZUR": {"name": "苏黎世机场", "city": "苏黎世", "country": "CH"},
    "VIE": {"name": "维也纳国际机场", "city": "维也纳", "country": "AT"},
    
    # 日本机场
    "NRT": {"name": "东京成田国际机场", "city": "东京", "country": "JP"},
    "HND": {"name": "东京羽田机场", "city": "东京", "country": "JP"},
    "KIX": {"name": "大阪关西国际机场", "city": "大阪", "country": "JP"},
    "ITM": {"name": "大阪伊丹机场", "city": "大阪", "country": "JP"},
    "NGO": {"name": "名古屋中部国际机场", "city": "名古屋", "country": "JP"},
    "FUK": {"name": "福冈机场", "city": "福冈", "country": "JP"},
    
    # 韩国机场
    "ICN": {"name": "首尔仁川国际机场", "city": "首尔", "country": "KR"},
    "GMP": {"name": "首尔金浦国际机场", "city": "首尔", "country": "KR"},
    "PUS": {"name": "釜山金海国际机场", "city": "釜山", "country": "KR"},
    
    # 东南亚机场
    "SIN": {"name": "新加坡樟宜机场", "city": "新加坡", "country": "SG"},
    "BKK": {"name": "曼谷素万那普国际机场", "city": "曼谷", "country": "TH"},
    "DMK": {"name": "曼谷廊曼国际机场", "city": "曼谷", "country": "TH"},
    "KUL": {"name": "吉隆坡国际机场", "city": "吉隆坡", "country": "MY"},
    "CGK": {"name": "雅加达苏加诺-哈达国际机场", "city": "雅加达", "country": "ID"},
    "MNL": {"name": "马尼拉尼诺·阿基诺国际机场", "city": "马尼拉", "country": "PH"},
    "SGN": {"name": "胡志明市新山一国际机场", "city": "胡志明市", "country": "VN"},
    
    # 澳洲机场
    "SYD": {"name": "悉尼金斯福德·史密斯机场", "city": "悉尼", "country": "AU"},
    "MEL": {"name": "墨尔本机场", "city": "墨尔本", "country": "AU"},
    "BNE": {"name": "布里斯班机场", "city": "布里斯班", "country": "AU"},
    
    # 中东机场
    "DXB": {"name": "迪拜国际机场", "city": "迪拜", "country": "AE"},
    "DWC": {"name": "迪拜世界中心机场", "city": "迪拜", "country": "AE"},
    "DOH": {"name": "多哈哈马德国际机场", "city": "多哈", "country": "QA"},
    
    # 加拿大机场
    "YVR": {"name": "温哥华国际机场", "city": "温哥华", "country": "CA"},
    "YYZ": {"name": "多伦多皮尔逊国际机场", "city": "多伦多", "country": "CA"},
    "YUL": {"name": "蒙特利尔皮埃尔·埃利奥特·特鲁多国际机场", "city": "蒙特利尔", "country": "CA"},
}

def find_airports_by_query(query: str) -> list:
    """
    根据查询字符串查找匹配的机场代码
    支持：
    - 直接机场代码 (如 PEK, LAX)
    - 城市名称 (如 北京, 纽约, Beijing, New York)
    - 国家代码 (如 CN, US, UK)
    - 国家名称 (通过country_data查找)
    """
    query = query.strip().upper()
    
    # 如果是3位机场代码且在详细信息中，直接返回
    if len(query) == 3 and query in AIRPORT_DETAILS:
        return [query]
    
    # 搜索城市名称映射
    for city_name, airports in AIRPORT_MAPPINGS.items():
        if query.lower() == city_name.lower():
            return airports
    
    # 搜索国家代码映射
    if query in COUNTRY_TO_AIRPORTS:
        return COUNTRY_TO_AIRPORTS[query]
    
    # 尝试通过country_data查找国家名称
    from utils.country_data import SUPPORTED_COUNTRIES
    for country_code, country_info in SUPPORTED_COUNTRIES.items():
        if query == country_info["name"] or query == country_code:
            if country_code in COUNTRY_TO_AIRPORTS:
                return COUNTRY_TO_AIRPORTS[country_code]
    
    # 模糊搜索城市名称
    matches = []
    query_lower = query.lower()
    for city_name, airports in AIRPORT_MAPPINGS.items():
        if query_lower in city_name.lower() or city_name.lower() in query_lower:
            matches.extend(airports)
    
    # 去重并返回
    return list(set(matches))

def get_airport_info(airport_code: str) -> dict:
    """获取机场详细信息"""
    airport_code = airport_code.upper()
    if airport_code in AIRPORT_DETAILS:
        return AIRPORT_DETAILS[airport_code]
    return {"name": f"机场 {airport_code}", "city": "未知", "country": "未知"}

def format_airport_suggestions(query: str, limit: int = 5) -> str:
    """格式化机场建议列表"""
    airports = find_airports_by_query(query)
    if not airports:
        return f"❌ 未找到与 '{query}' 匹配的机场"
    
    # 限制显示数量
    airports = airports[:limit]
    
    suggestions = []
    for airport_code in airports:
        info = get_airport_info(airport_code)
        from utils.country_data import get_country_flag
        flag = get_country_flag(info["country"])
        suggestions.append(f"• **{airport_code}** {flag} {info['name']} ({info['city']})")
    
    return "🏢 **找到以下机场:**\\n\\n" + "\\n".join(suggestions)