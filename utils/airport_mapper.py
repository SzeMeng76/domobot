"""
机场映射工具
参考 timezone_mapper.py 架构，提供智能机场代码解析和城市到机场的映射
主要用于优化用户输入体验，将自然语言输入转换为IATA机场代码
"""

import re
from typing import Dict, List, Tuple, Optional
from .country_data import SUPPORTED_COUNTRIES, get_country_flag

# 主要国际机场城市映射 - 重点支持常用航线
MAJOR_CITIES_AIRPORTS = {
    # 中国大陆主要城市
    "北京": {
        "primary": "PEK", 
        "secondary": ["PKX"], 
        "airports": [
            {"code": "PEK", "name": "北京首都国际机场", "name_en": "Beijing Capital International Airport", "note": "T1/T2/T3航站楼"},
            {"code": "PKX", "name": "北京大兴国际机场", "name_en": "Beijing Daxing International Airport", "note": "新机场,距市区较远"}
        ]
    },
    "上海": {
        "primary": "PVG", 
        "secondary": ["SHA"], 
        "airports": [
            {"code": "PVG", "name": "上海浦东国际机场", "name_en": "Shanghai Pudong International Airport", "note": "国际航班主要机场"},
            {"code": "SHA", "name": "上海虹桥国际机场", "name_en": "Shanghai Hongqiao International Airport", "note": "国内及少量国际航班"}
        ]
    },
    "广州": {
        "primary": "CAN", 
        "secondary": [], 
        "airports": [
            {"code": "CAN", "name": "广州白云国际机场", "name_en": "Guangzhou Baiyun International Airport", "note": "华南地区枢纽"}
        ]
    },
    "深圳": {
        "primary": "SZX", 
        "secondary": [], 
        "airports": [
            {"code": "SZX", "name": "深圳宝安国际机场", "name_en": "Shenzhen Bao'an International Airport", "note": "毗邻香港"}
        ]
    },
    "成都": {
        "primary": "CTU", 
        "secondary": ["TFU"], 
        "airports": [
            {"code": "CTU", "name": "成都双流国际机场", "name_en": "Chengdu Shuangliu International Airport", "note": "西南地区枢纽"},
            {"code": "TFU", "name": "成都天府国际机场", "name_en": "Chengdu Tianfu International Airport", "note": "新建机场"}
        ]
    },
    "重庆": {
        "primary": "CKG", 
        "secondary": [], 
        "airports": [
            {"code": "CKG", "name": "重庆江北国际机场", "name_en": "Chongqing Jiangbei International Airport", "note": "西南重要枢纽"}
        ]
    },
    "杭州": {
        "primary": "HGH", 
        "secondary": [], 
        "airports": [
            {"code": "HGH", "name": "杭州萧山国际机场", "name_en": "Hangzhou Xiaoshan International Airport", "note": "长三角重要机场"}
        ]
    },
    "南京": {
        "primary": "NKG", 
        "secondary": [], 
        "airports": [
            {"code": "NKG", "name": "南京禄口国际机场", "name_en": "Nanjing Lukou International Airport", "note": "江苏省主要机场"}
        ]
    },
    "西安": {
        "primary": "XIY", 
        "secondary": [], 
        "airports": [
            {"code": "XIY", "name": "西安咸阳国际机场", "name_en": "Xi'an Xianyang International Airport", "note": "西北地区枢纽"}
        ]
    },
    "厦门": {
        "primary": "XMN", 
        "secondary": [], 
        "airports": [
            {"code": "XMN", "name": "厦门高崎国际机场", "name_en": "Xiamen Gaoqi International Airport", "note": "对台重要门户"}
        ]
    },
    "昆明": {
        "primary": "KMG", 
        "secondary": [], 
        "airports": [
            {"code": "KMG", "name": "昆明长水国际机场", "name_en": "Kunming Changshui International Airport", "note": "面向南亚东南亚枢纽"}
        ]
    },
    
    # 港澳台
    "香港": {
        "primary": "HKG", 
        "secondary": [], 
        "airports": [
            {"code": "HKG", "name": "香港国际机场", "name_en": "Hong Kong International Airport", "note": "亚太重要枢纽"}
        ]
    },
    "澳门": {
        "primary": "MFM", 
        "secondary": [], 
        "airports": [
            {"code": "MFM", "name": "澳门国际机场", "name_en": "Macau International Airport", "note": "珠三角门户"}
        ]
    },
    "台北": {
        "primary": "TPE", 
        "secondary": ["TSA"], 
        "airports": [
            {"code": "TPE", "name": "台湾桃园国际机场", "name_en": "Taiwan Taoyuan International Airport", "note": "台湾主要国际机场"},
            {"code": "TSA", "name": "台北松山机场", "name_en": "Taipei Songshan Airport", "note": "市区机场,少量国际航班"}
        ]
    },
    
    # 日本主要城市
    "东京": {
        "primary": "NRT", 
        "secondary": ["HND"], 
        "airports": [
            {"code": "NRT", "name": "成田国际机场", "name_en": "Narita International Airport", "note": "主要国际航班"},
            {"code": "HND", "name": "羽田机场", "name_en": "Haneda Airport", "note": "国内及亚洲航班,距市区近"}
        ]
    },
    "大阪": {
        "primary": "KIX", 
        "secondary": ["ITM"], 
        "airports": [
            {"code": "KIX", "name": "关西国际机场", "name_en": "Kansai International Airport", "note": "国际航班主要机场"},
            {"code": "ITM", "name": "大阪伊丹机场", "name_en": "Osaka International Airport", "note": "主要服务国内航班"}
        ]
    },
    "名古屋": {
        "primary": "NGO", 
        "secondary": [], 
        "airports": [
            {"code": "NGO", "name": "中部国际机场", "name_en": "Chubu Centrair International Airport", "note": "中部地区主要国际机场"}
        ]
    },
    
    # 韩国主要城市  
    "首尔": {
        "primary": "ICN", 
        "secondary": ["GMP"], 
        "airports": [
            {"code": "ICN", "name": "仁川国际机场", "name_en": "Incheon International Airport", "note": "韩国主要国际机场"},
            {"code": "GMP", "name": "金浦机场", "name_en": "Gimpo International Airport", "note": "国内及东北亚航班"}
        ]
    },
    "釜山": {
        "primary": "PUS", 
        "secondary": [], 
        "airports": [
            {"code": "PUS", "name": "釜山金海国际机场", "name_en": "Busan Gimhae International Airport", "note": "韩国第二大机场"}
        ]
    },
    
    # 东南亚主要城市
    "新加坡": {
        "primary": "SIN", 
        "secondary": [], 
        "airports": [
            {"code": "SIN", "name": "新加坡樟宜机场", "name_en": "Singapore Changi Airport", "note": "世界顶级机场,东南亚枢纽"}
        ]
    },
    "吉隆坡": {
        "primary": "KUL", 
        "secondary": [], 
        "airports": [
            {"code": "KUL", "name": "吉隆坡国际机场", "name_en": "Kuala Lumpur International Airport", "note": "马来西亚主要国际机场"}
        ]
    },
    "曼谷": {
        "primary": "BKK", 
        "secondary": ["DMK"], 
        "airports": [
            {"code": "BKK", "name": "素万那普机场", "name_en": "Suvarnabhumi Airport", "note": "泰国主要国际机场"},
            {"code": "DMK", "name": "廊曼机场", "name_en": "Don Mueang International Airport", "note": "廉价航空主要基地"}
        ]
    },
    "雅加达": {
        "primary": "CGK", 
        "secondary": [], 
        "airports": [
            {"code": "CGK", "name": "苏加诺-哈达国际机场", "name_en": "Soekarno-Hatta International Airport", "note": "印尼主要国际机场"}
        ]
    },
    "马尼拉": {
        "primary": "MNL", 
        "secondary": [], 
        "airports": [
            {"code": "MNL", "name": "尼诺·阿基诺国际机场", "name_en": "Ninoy Aquino International Airport", "note": "菲律宾主要国际机场"}
        ]
    },
    "胡志明市": {
        "primary": "SGN", 
        "secondary": [], 
        "airports": [
            {"code": "SGN", "name": "新山一国际机场", "name_en": "Tan Son Nhat International Airport", "note": "越南南部主要机场"}
        ]
    },
    "河内": {
        "primary": "HAN", 
        "secondary": [], 
        "airports": [
            {"code": "HAN", "name": "内排国际机场", "name_en": "Noi Bai International Airport", "note": "越南北部主要机场"}
        ]
    },
    
    # 美国主要城市
    "纽约": {
        "primary": "JFK", 
        "secondary": ["LGA", "EWR"], 
        "airports": [
            {"code": "JFK", "name": "约翰·肯尼迪国际机场", "name_en": "John F. Kennedy International Airport", "note": "主要国际航班"},
            {"code": "LGA", "name": "拉瓜迪亚机场", "name_en": "LaGuardia Airport", "note": "主要服务国内航班"},
            {"code": "EWR", "name": "纽瓦克自由国际机场", "name_en": "Newark Liberty International Airport", "note": "国际航班,位于新泽西"}
        ]
    },
    "洛杉矶": {
        "primary": "LAX", 
        "secondary": [], 
        "airports": [
            {"code": "LAX", "name": "洛杉矶国际机场", "name_en": "Los Angeles International Airport", "note": "美西最大机场"}
        ]
    },
    "旧金山": {
        "primary": "SFO", 
        "secondary": [], 
        "airports": [
            {"code": "SFO", "name": "旧金山国际机场", "name_en": "San Francisco International Airport", "note": "湾区主要国际机场"}
        ]
    },
    "芝加哥": {
        "primary": "ORD", 
        "secondary": ["MDW"], 
        "airports": [
            {"code": "ORD", "name": "奥黑尔国际机场", "name_en": "O'Hare International Airport", "note": "美国中部重要枢纽"},
            {"code": "MDW", "name": "中途机场", "name_en": "Midway International Airport", "note": "廉价航空基地"}
        ]
    },
    "西雅图": {
        "primary": "SEA", 
        "secondary": [], 
        "airports": [
            {"code": "SEA", "name": "西雅图-塔科马国际机场", "name_en": "Seattle-Tacoma International Airport", "note": "太平洋西北地区枢纽"}
        ]
    },
    "华盛顿": {
        "primary": "IAD", 
        "secondary": ["DCA"], 
        "airports": [
            {"code": "IAD", "name": "华盛顿杜勒斯国际机场", "name_en": "Washington Dulles International Airport", "note": "主要国际航班"},
            {"code": "DCA", "name": "罗纳德·里根华盛顿国家机场", "name_en": "Ronald Reagan Washington National Airport", "note": "国内航班,距市区近"}
        ]
    },
    "迈阿密": {
        "primary": "MIA", 
        "secondary": [], 
        "airports": [
            {"code": "MIA", "name": "迈阿密国际机场", "name_en": "Miami International Airport", "note": "通往拉美的门户"}
        ]
    },
    
    # 加拿大主要城市
    "多伦多": {
        "primary": "YYZ", 
        "secondary": [], 
        "airports": [
            {"code": "YYZ", "name": "皮尔逊国际机场", "name_en": "Toronto Pearson International Airport", "note": "加拿大最大机场"}
        ]
    },
    "温哥华": {
        "primary": "YVR", 
        "secondary": [], 
        "airports": [
            {"code": "YVR", "name": "温哥华国际机场", "name_en": "Vancouver International Airport", "note": "通往亚洲的门户"}
        ]
    },
    
    # 欧洲主要城市
    "伦敦": {
        "primary": "LHR", 
        "secondary": ["LGW", "STN", "LTN"], 
        "airports": [
            {"code": "LHR", "name": "希思罗机场", "name_en": "Heathrow Airport", "note": "欧洲最繁忙机场"},
            {"code": "LGW", "name": "盖特威克机场", "name_en": "Gatwick Airport", "note": "第二大机场"},
            {"code": "STN", "name": "斯坦斯特德机场", "name_en": "Stansted Airport", "note": "廉价航空基地"},
            {"code": "LTN", "name": "卢顿机场", "name_en": "Luton Airport", "note": "廉价航空基地"}
        ]
    },
    "巴黎": {
        "primary": "CDG", 
        "secondary": ["ORY"], 
        "airports": [
            {"code": "CDG", "name": "夏尔·戴高乐机场", "name_en": "Charles de Gaulle Airport", "note": "欧洲主要枢纽"},
            {"code": "ORY", "name": "奥利机场", "name_en": "Orly Airport", "note": "主要服务欧洲及国内航班"}
        ]
    },
    "法兰克福": {
        "primary": "FRA", 
        "secondary": [], 
        "airports": [
            {"code": "FRA", "name": "法兰克福机场", "name_en": "Frankfurt Airport", "note": "欧洲重要货运及客运枢纽"}
        ]
    },
    "阿姆斯特丹": {
        "primary": "AMS", 
        "secondary": [], 
        "airports": [
            {"code": "AMS", "name": "史基浦机场", "name_en": "Amsterdam Airport Schiphol", "note": "荷兰皇家航空枢纽"}
        ]
    },
    "罗马": {
        "primary": "FCO", 
        "secondary": [], 
        "airports": [
            {"code": "FCO", "name": "菲乌米奇诺机场", "name_en": "Leonardo da Vinci International Airport", "note": "意大利最大机场"}
        ]
    },
    "马德里": {
        "primary": "MAD", 
        "secondary": [], 
        "airports": [
            {"code": "MAD", "name": "阿道弗·苏亚雷斯马德里-巴拉哈斯机场", "name_en": "Adolfo Suárez Madrid-Barajas Airport", "note": "西班牙最大机场"}
        ]
    },
    "苏黎世": {
        "primary": "ZUR", 
        "secondary": [], 
        "airports": [
            {"code": "ZUR", "name": "苏黎世机场", "name_en": "Zurich Airport", "note": "瑞士最大机场"}
        ]
    },
    
    # 澳洲主要城市
    "悉尼": {
        "primary": "SYD", 
        "secondary": [], 
        "airports": [
            {"code": "SYD", "name": "悉尼金斯福德·史密斯机场", "name_en": "Sydney Kingsford Smith Airport", "note": "澳洲最繁忙机场"}
        ]
    },
    "墨尔本": {
        "primary": "MEL", 
        "secondary": [], 
        "airports": [
            {"code": "MEL", "name": "墨尔本机场", "name_en": "Melbourne Airport", "note": "澳洲第二大机场"}
        ]
    },
    "珀斯": {
        "primary": "PER", 
        "secondary": [], 
        "airports": [
            {"code": "PER", "name": "珀斯机场", "name_en": "Perth Airport", "note": "西澳主要机场"}
        ]
    },
    "奥克兰": {
        "primary": "AKL", 
        "secondary": [], 
        "airports": [
            {"code": "AKL", "name": "奥克兰机场", "name_en": "Auckland Airport", "note": "新西兰最大机场"}
        ]
    },
    
    # 中东主要城市
    "迪拜": {
        "primary": "DXB", 
        "secondary": [], 
        "airports": [
            {"code": "DXB", "name": "迪拜国际机场", "name_en": "Dubai International Airport", "note": "中东最重要枢纽"}
        ]
    },
    "多哈": {
        "primary": "DOH", 
        "secondary": [], 
        "airports": [
            {"code": "DOH", "name": "哈马德国际机场", "name_en": "Hamad International Airport", "note": "卡塔尔航空枢纽"}
        ]
    },
}

# 英文城市名映射（小写匹配）
ENGLISH_CITIES_AIRPORTS = {
    "beijing": "北京",
    "shanghai": "上海", 
    "guangzhou": "广州",
    "shenzhen": "深圳",
    "hong kong": "香港",
    "hongkong": "香港",
    "tokyo": "东京",
    "seoul": "首尔",
    "singapore": "新加坡",
    "bangkok": "曼谷",
    "kuala lumpur": "吉隆坡",
    "new york": "纽约",
    "los angeles": "洛杉矶",
    "san francisco": "旧金山",
    "chicago": "芝加哥",
    "seattle": "西雅图",
    "toronto": "多伦多",
    "vancouver": "温哥华",
    "london": "伦敦",
    "paris": "巴黎",
    "frankfurt": "法兰克福",
    "amsterdam": "阿姆斯特丹",
    "dubai": "迪拜",
    "sydney": "悉尼",
    "melbourne": "墨尔本",
}

# 常见输入错误和别名映射
CITY_ALIASES = {
    # 中文别名
    "北平": "北京",
    "京城": "北京",
    "申城": "上海",
    "魔都": "上海", 
    "沪": "上海",
    "羊城": "广州",
    "穗": "广州",
    "鹏城": "深圳",
    "圳": "深圳",
    "港": "香港",
    "澳": "澳门",
    
    # 英文别名
    "nyc": "纽约",
    "la": "洛杉矶",
    "sf": "旧金山",
    "chi": "芝加哥",
    "dc": "华盛顿",
    "hk": "香港",
    
    # 国家/地区映射到主要城市
    "中国": "北京",
    "美国": "纽约", 
    "日本": "东京",
    "韩国": "首尔",
    "英国": "伦敦",
    "法国": "巴黎",
    "德国": "法兰克福",
    "澳大利亚": "悉尼",
    "新加坡": "新加坡",
    "泰国": "曼谷",
}

# 无国际机场城市的建议映射
CITY_SUGGESTIONS = {
    "杭州": {
        "suggestions": [
            {"airport": "SHA", "city": "上海虹桥", "transport": "高铁1小时,同站换乘", "note": "推荐"},
            {"airport": "PVG", "city": "上海浦东", "transport": "高铁1小时+磁悬浮8分钟", "note": "国际航班多"},
            {"airport": "NKG", "city": "南京禄口", "transport": "高铁2小时", "note": "备选"}
        ]
    },
    "苏州": {
        "suggestions": [
            {"airport": "SHA", "city": "上海虹桥", "transport": "高铁30分钟", "note": "推荐"},
            {"airport": "PVG", "city": "上海浦东", "transport": "高铁30分钟+磁悬浮8分钟", "note": "国际航班"}
        ]
    },
    "无锡": {
        "suggestions": [
            {"airport": "SHA", "city": "上海虹桥", "transport": "高铁45分钟", "note": "推荐"},
            {"airport": "NKG", "city": "南京禄口", "transport": "高铁1小时", "note": "备选"}
        ]
    },
    "宁波": {
        "suggestions": [
            {"airport": "SHA", "city": "上海虹桥", "transport": "高铁2小时", "note": "推荐"},
            {"airport": "PVG", "city": "上海浦东", "transport": "高铁2小时+磁悬浮", "note": "国际航班"},
            {"airport": "HGH", "city": "杭州萧山", "transport": "高铁1小时", "note": "就近选择"}
        ]
    }
}

def normalize_city_input(city_input: str) -> str:
    """规范化城市输入"""
    if not city_input:
        return ""
    
    # 去除空格并转为小写（用于英文匹配）
    normalized = city_input.strip()
    
    # 检查别名映射
    if normalized in CITY_ALIASES:
        return CITY_ALIASES[normalized]
    
    # 检查英文城市名映射
    normalized_lower = normalized.lower()
    if normalized_lower in ENGLISH_CITIES_AIRPORTS:
        return ENGLISH_CITIES_AIRPORTS[normalized_lower]
    
    return normalized

def resolve_airport_codes(city_input: str) -> Dict:
    """
    解析城市输入到机场代码
    返回: {
        "status": "success/multiple/not_found/suggestion_needed",
        "primary": "主要机场代码", 
        "secondary": ["备选机场代码"],
        "airports": [机场详细信息],
        "suggestions": [建议信息] (仅当需要建议时)
    }
    """
    if not city_input:
        return {"status": "not_found"}
    
    # 检查是否已经是IATA代码
    if len(city_input) == 3 and city_input.isupper() and city_input.isalpha():
        return {
            "status": "success",
            "primary": city_input,
            "secondary": [],
            "airports": [{"code": city_input, "name": "机场代码", "note": "请确认代码正确"}]
        }
    
    # 规范化输入
    normalized_city = normalize_city_input(city_input)
    
    # 检查主要城市映射
    if normalized_city in MAJOR_CITIES_AIRPORTS:
        city_info = MAJOR_CITIES_AIRPORTS[normalized_city]
        
        # 判断是单机场还是多机场城市
        if len(city_info["airports"]) == 1:
            return {
                "status": "success",
                "primary": city_info["primary"],
                "secondary": city_info["secondary"],
                "airports": city_info["airports"],
                "city": normalized_city
            }
        else:
            return {
                "status": "multiple",
                "primary": city_info["primary"],
                "secondary": city_info["secondary"], 
                "airports": city_info["airports"],
                "city": normalized_city
            }
    
    # 检查是否需要建议
    if normalized_city in CITY_SUGGESTIONS:
        return {
            "status": "suggestion_needed",
            "city": normalized_city,
            "suggestions": CITY_SUGGESTIONS[normalized_city]["suggestions"]
        }
    
    return {
        "status": "not_found",
        "input": city_input,
        "normalized": normalized_city
    }

def resolve_flight_airports(departure_input: str, arrival_input: str) -> Dict:
    """
    智能解析航班出发和到达机场
    返回完整的解析结果和建议
    """
    departure_result = resolve_airport_codes(departure_input)
    arrival_result = resolve_airport_codes(arrival_input)
    
    return {
        "departure": departure_result,
        "arrival": arrival_result,
        "status": _determine_overall_status(departure_result, arrival_result)
    }

def _determine_overall_status(departure_result: Dict, arrival_result: Dict) -> str:
    """确定整体解析状态"""
    dep_status = departure_result.get("status")
    arr_status = arrival_result.get("status")
    
    # 如果任一方需要建议，优先处理
    if dep_status == "suggestion_needed" or arr_status == "suggestion_needed":
        return "suggestion_needed"
    
    # 如果任一方未找到
    if dep_status == "not_found" or arr_status == "not_found":
        return "not_found"
    
    # 如果任一方有多个选择
    if dep_status == "multiple" or arr_status == "multiple":
        return "multiple_choice"
    
    # 都成功解析
    if dep_status == "success" and arr_status == "success":
        return "ready"
    
    return "unknown"

def format_airport_selection_message(departure_result: Dict, arrival_result: Dict) -> str:
    """格式化机场选择消息"""
    from telegram.helpers import escape_markdown
    
    message_parts = ["🛫 *机场选择确认*\n"]
    
    # 处理出发机场
    dep_status = departure_result.get("status")
    if dep_status == "multiple":
        city = departure_result.get("city", "")
        airports = departure_result.get("airports", [])
        safe_city = escape_markdown(city, version=2)
        message_parts.append(f"📍 *出发* {safe_city} 有{len(airports)}个机场:")
        
        for i, airport in enumerate(airports):
            code = airport.get("code", "")
            name = airport.get("name", "")
            note = airport.get("note", "")
            safe_name = escape_markdown(name, version=2)
            safe_note = escape_markdown(note, version=2)
            
            icon = "🔸" if i == 0 else "🔹"  # 主要机场用实心，次要用空心
            message_parts.append(f"{icon} *{code}* \\- {safe_name}")
            if note:
                message_parts.append(f"   💡 {safe_note}")
        message_parts.append("")
    elif dep_status == "suggestion_needed":
        city = departure_result.get("city", "")
        suggestions = departure_result.get("suggestions", [])
        safe_city = escape_markdown(city, version=2)
        message_parts.append(f"❓ *{safe_city}* 暂无国际机场\n")
        message_parts.append("🔍 *建议方案*:")
        
        for suggestion in suggestions:
            airport = suggestion.get("airport", "")
            airport_city = suggestion.get("city", "")
            transport = suggestion.get("transport", "")
            note = suggestion.get("note", "")
            
            safe_airport_city = escape_markdown(airport_city, version=2)
            safe_transport = escape_markdown(transport, version=2)
            
            note_icon = "⭐" if note == "推荐" else "🚄"
            message_parts.append(f"{note_icon} *{airport}* \\- {safe_airport_city}")
            message_parts.append(f"   🚅 {safe_transport}")
        message_parts.append("")
    
    # 处理到达机场
    arr_status = arrival_result.get("status")
    if arr_status == "multiple":
        city = arrival_result.get("city", "")
        airports = arrival_result.get("airports", [])
        safe_city = escape_markdown(city, version=2)
        message_parts.append(f"📍 *到达* {safe_city} 有{len(airports)}个机场:")
        
        for i, airport in enumerate(airports):
            code = airport.get("code", "")
            name = airport.get("name", "")
            note = airport.get("note", "")
            safe_name = escape_markdown(name, version=2)
            safe_note = escape_markdown(note, version=2)
            
            icon = "🔸" if i == 0 else "🔹"
            message_parts.append(f"{icon} *{code}* \\- {safe_name}")
            if note:
                message_parts.append(f"   💡 {safe_note}")
        message_parts.append("")
    elif arr_status == "suggestion_needed":
        city = arrival_result.get("city", "")
        suggestions = arrival_result.get("suggestions", [])
        safe_city = escape_markdown(city, version=2)
        message_parts.append(f"❓ *{safe_city}* 暂无国际机场\n")
        message_parts.append("🔍 *建议方案*:")
        
        for suggestion in suggestions:
            airport = suggestion.get("airport", "")
            airport_city = suggestion.get("city", "")
            transport = suggestion.get("transport", "")
            note = suggestion.get("note", "")
            
            safe_airport_city = escape_markdown(airport_city, version=2)
            safe_transport = escape_markdown(transport, version=2)
            
            note_icon = "⭐" if note == "推荐" else "🚄"
            message_parts.append(f"{note_icon} *{airport}* \\- {safe_airport_city}")
            message_parts.append(f"   🚅 {safe_transport}")
        message_parts.append("")
    
    return "\n".join(message_parts)

def get_recommended_airport_pair(departure_result: Dict, arrival_result: Dict) -> Tuple[str, str]:
    """获取推荐的机场对"""
    dep_primary = departure_result.get("primary", "")
    arr_primary = arrival_result.get("primary", "")
    return dep_primary, arr_primary

def format_airport_info(airport_code: str) -> str:
    """格式化单个机场信息显示"""
    from telegram.helpers import escape_markdown
    
    # 从映射中查找机场信息
    for city, city_info in MAJOR_CITIES_AIRPORTS.items():
        for airport in city_info["airports"]:
            if airport["code"] == airport_code:
                name = airport.get("name", "")
                name_en = airport.get("name_en", "")
                note = airport.get("note", "")
                
                safe_name = escape_markdown(name, version=2)
                safe_name_en = escape_markdown(name_en, version=2)
                safe_note = escape_markdown(note, version=2)
                safe_city = escape_markdown(city, version=2)
                
                result = f"✈️ *{safe_name}* \\({airport_code}\\)\n"
                result += f"📍 {safe_city}\n"
                if name_en and name_en != name:
                    result += f"🔤 {safe_name_en}\n"
                if note:
                    result += f"💡 {safe_note}\n"
                
                return result
    
    # 如果未找到详细信息，返回基本信息
    safe_code = escape_markdown(airport_code, version=2)
    return f"✈️ 机场代码: {safe_code}"

def get_all_supported_cities() -> List[str]:
    """获取所有支持的城市列表"""
    cities = list(MAJOR_CITIES_AIRPORTS.keys())
    cities.extend(CITY_ALIASES.keys())
    cities.extend(ENGLISH_CITIES_AIRPORTS.values())
    return sorted(set(cities))

def search_airports_by_partial_name(partial_name: str) -> List[Dict]:
    """根据部分名称搜索机场"""
    results = []
    partial_lower = partial_name.lower()
    
    for city, city_info in MAJOR_CITIES_AIRPORTS.items():
        # 检查城市名匹配
        if partial_lower in city.lower():
            results.extend([{
                "city": city,
                "code": airport["code"],
                "name": airport["name"],
                "match_type": "city"
            } for airport in city_info["airports"]])
        else:
            # 检查机场名匹配
            for airport in city_info["airports"]:
                if (partial_lower in airport["name"].lower() or 
                    partial_lower in airport.get("name_en", "").lower() or
                    partial_lower in airport["code"].lower()):
                    results.append({
                        "city": city,
                        "code": airport["code"],
                        "name": airport["name"],
                        "match_type": "airport"
                    })
    
    return results[:10]  # 返回前10个匹配结果