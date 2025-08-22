#!/usr/bin/env python3
"""
航班相关工具函数
提供智能搜索、城市代码转换等功能
"""

import re
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta


class FlightSearchHelper:
    """航班搜索助手"""
    
    # 中英文城市名称到IATA代码的映射
    CITY_AIRPORT_MAPPING = {
        # 中国主要城市
        "北京": ["BJS", "PEK", "PKX"],  # [城市代码, 主机场, 其他机场]
        "beijing": ["BJS", "PEK", "PKX"],
        "上海": ["SHA", "SHA", "PVG"],
        "shanghai": ["SHA", "SHA", "PVG"],
        "广州": ["CAN", "CAN"],
        "guangzhou": ["CAN", "CAN"],
        "深圳": ["SZX", "SZX"],
        "shenzhen": ["SZX", "SZX"],
        "杭州": ["HGH", "HGH"],
        "hangzhou": ["HGH", "HGH"],
        "成都": ["CTU", "CTU"],
        "chengdu": ["CTU", "CTU"],
        "重庆": ["CKG", "CKG"],
        "chongqing": ["CKG", "CKG"],
        "西安": ["XIY", "XIY"],
        "xian": ["XIY", "XIY"],
        "南京": ["NKG", "NKG"],
        "nanjing": ["NKG", "NKG"],
        "青岛": ["TAO", "TAO"],
        "qingdao": ["TAO", "TAO"],
        "大连": ["DLC", "DLC"],
        "dalian": ["DLC", "DLC"],
        "厦门": ["XMN", "XMN"],
        "xiamen": ["XMN", "XMN"],
        "武汉": ["WUH", "WUH"],
        "wuhan": ["WUH", "WUH"],
        "长沙": ["CSX", "CSX"],
        "changsha": ["CSX", "CSX"],
        "南宁": ["NNG", "NNG"],
        "nanning": ["NNG", "NNG"],
        "昆明": ["KMG", "KMG"],
        "kunming": ["KMG", "KMG"],
        "合肥": ["HFE", "HFE"],
        "hefei": ["HFE", "HFE"],
        "郑州": ["CGO", "CGO"],
        "zhengzhou": ["CGO", "CGO"],
        "济南": ["TNA", "TNA"],
        "jinan": ["TNA", "TNA"],
        "沈阳": ["SHE", "SHE"],
        "shenyang": ["SHE", "SHE"],
        "天津": ["TSN", "TSN"],
        "tianjin": ["TSN", "TSN"],
        "石家庄": ["SJW", "SJW"],
        "shijiazhuang": ["SJW", "SJW"],
        "太原": ["TYN", "TYN"],
        "taiyuan": ["TYN", "TYN"],
        "哈尔滨": ["HRB", "HRB"],
        "harbin": ["HRB", "HRB"],
        "长春": ["CGQ", "CGQ"],
        "changchun": ["CGQ", "CGQ"],
        "乌鲁木齐": ["URC", "URC"],
        "urumqi": ["URC", "URC"],
        "兰州": ["LHW", "LHW"],
        "lanzhou": ["LHW", "LHW"],
        "银川": ["INC", "INC"],
        "yinchuan": ["INC", "INC"],
        "海口": ["HAK", "HAK"],
        "haikou": ["HAK", "HAK"],
        "三亚": ["SYX", "SYX"],
        "sanya": ["SYX", "SYX"],
        "拉萨": ["LXA", "LXA"],
        "lhasa": ["LXA", "LXA"],
        
        # 港澳台
        "香港": ["HKG", "HKG"],
        "hong kong": ["HKG", "HKG"],
        "hongkong": ["HKG", "HKG"],
        "澳门": ["MFM", "MFM"],
        "macao": ["MFM", "MFM"],
        "macau": ["MFM", "MFM"],
        "台北": ["TPE", "TPE", "TSA"],
        "taipei": ["TPE", "TPE", "TSA"],
        "高雄": ["KHH", "KHH"],
        "kaohsiung": ["KHH", "KHH"],
        
        # 国际主要城市
        "东京": ["TYO", "NRT", "HND"],
        "tokyo": ["TYO", "NRT", "HND"],
        "大阪": ["OSA", "KIX", "ITM"],
        "osaka": ["OSA", "KIX", "ITM"],
        "首尔": ["SEL", "ICN", "GMP"],
        "seoul": ["SEL", "ICN", "GMP"],
        "釜山": ["PUS", "PUS"],
        "busan": ["PUS", "PUS"],
        "新加坡": ["SIN", "SIN"],
        "singapore": ["SIN", "SIN"],
        "吉隆坡": ["KUL", "KUL"],
        "kuala lumpur": ["KUL", "KUL"],
        "曼谷": ["BKK", "BKK", "DMK"],
        "bangkok": ["BKK", "BKK", "DMK"],
        "雅加达": ["JKT", "CGK"],
        "jakarta": ["JKT", "CGK"],
        "马尼拉": ["MNL", "MNL"],
        "manila": ["MNL", "MNL"],
        "河内": ["HAN", "HAN"],
        "hanoi": ["HAN", "HAN"],
        "胡志明": ["SGN", "SGN"],
        "ho chi minh": ["SGN", "SGN"],
        "金边": ["PNH", "PNH"],
        "phnom penh": ["PNH", "PNH"],
        "仰光": ["RGN", "RGN"],
        "yangon": ["RGN", "RGN"],
        "达卡": ["DAC", "DAC"],
        "dhaka": ["DAC", "DAC"],
        "孟买": ["BOM", "BOM"],
        "mumbai": ["BOM", "BOM"],
        "新德里": ["DEL", "DEL"],
        "new delhi": ["DEL", "DEL"],
        "班加罗尔": ["BLR", "BLR"],
        "bangalore": ["BLR", "BLR"],
        "迪拜": ["DXB", "DXB"],
        "dubai": ["DXB", "DXB"],
        "多哈": ["DOH", "DOH"],
        "doha": ["DOH", "DOH"],
        "阿布扎比": ["AUH", "AUH"],
        "abu dhabi": ["AUH", "AUH"],
        "伊斯坦布尔": ["IST", "IST"],
        "istanbul": ["IST", "IST"],
        "莫斯科": ["MOW", "SVO", "DME"],
        "moscow": ["MOW", "SVO", "DME"],
        "伦敦": ["LON", "LHR", "LGW"],
        "london": ["LON", "LHR", "LGW"],
        "巴黎": ["PAR", "CDG", "ORY"],
        "paris": ["PAR", "CDG", "ORY"],
        "法兰克福": ["FRA", "FRA"],
        "frankfurt": ["FRA", "FRA"],
        "阿姆斯特丹": ["AMS", "AMS"],
        "amsterdam": ["AMS", "AMS"],
        "罗马": ["ROM", "FCO"],
        "rome": ["ROM", "FCO"],
        "米兰": ["MIL", "MXP"],
        "milan": ["MIL", "MXP"],
        "苏黎世": ["ZUR", "ZUR"],
        "zurich": ["ZUR", "ZUR"],
        "维也纳": ["VIE", "VIE"],
        "vienna": ["VIE", "VIE"],
        "纽约": ["NYC", "JFK", "LGA"],
        "new york": ["NYC", "JFK", "LGA"],
        "洛杉矶": ["LAX", "LAX"],
        "los angeles": ["LAX", "LAX"],
        "旧金山": ["SFO", "SFO"],
        "san francisco": ["SFO", "SFO"],
        "芝加哥": ["CHI", "ORD"],
        "chicago": ["CHI", "ORD"],
        "西雅图": ["SEA", "SEA"],
        "seattle": ["SEA", "SEA"],
        "温哥华": ["YVR", "YVR"],
        "vancouver": ["YVR", "YVR"],
        "多伦多": ["YTO", "YYZ"],
        "toronto": ["YTO", "YYZ"],
        "悉尼": ["SYD", "SYD"],
        "sydney": ["SYD", "SYD"],
        "墨尔本": ["MEL", "MEL"],
        "melbourne": ["MEL", "MEL"],
        "奥克兰": ["AKL", "AKL"],
        "auckland": ["AKL", "AKL"]
    }
    
    @classmethod
    def smart_convert_to_airport_code(cls, input_str: str) -> Tuple[str, str]:
        """
        智能转换输入为机场代码
        
        Args:
            input_str: 用户输入（可能是城市名、机场代码、国家名等）
            
        Returns:
            Tuple[机场代码, 识别类型]: 如 ("PEK", "city") 或 ("PEK", "airport")
        """
        input_clean = input_str.strip().lower()
        
        # 1. 检查是否已经是3位IATA机场代码
        if re.match(r'^[A-Z]{3}$', input_str.upper()):
            return input_str.upper(), "airport"
        
        # 2. 检查城市名称映射
        if input_clean in cls.CITY_AIRPORT_MAPPING:
            codes = cls.CITY_AIRPORT_MAPPING[input_clean]
            return codes[1], "city"  # 返回主机场代码
        
        # 3. 模糊匹配城市名称
        for city_name, codes in cls.CITY_AIRPORT_MAPPING.items():
            if input_clean in city_name or city_name in input_clean:
                return codes[1], "city_fuzzy"
        
        # 4. 无法识别，返回原输入（大写）
        return input_str.upper(), "unknown"
    
    @classmethod
    def get_city_display_name(cls, airport_code: str) -> str:
        """根据机场代码获取显示用的城市名称"""
        code_upper = airport_code.upper()
        
        # 反向查找城市名称
        for city_name, codes in cls.CITY_AIRPORT_MAPPING.items():
            if code_upper in codes:
                # 返回中文名称（如果存在）
                if any('\u4e00' <= char <= '\u9fff' for char in city_name):
                    return city_name
        
        # 如果找不到，返回机场代码
        return airport_code
    
    @classmethod
    def parse_smart_date(cls, date_str: str) -> str:
        """
        智能解析日期输入
        
        支持格式：
        - 今天/今日/today
        - 明天/tomorrow  
        - 后天/day after tomorrow
        - 12-25, 1225
        - 2024-12-25
        - 12/25
        - Dec 25, 2024-12-25
        """
        if not date_str:
            return datetime.now().strftime("%Y-%m-%d")
        
        date_str = date_str.lower().strip()
        today = datetime.now()
        
        # 相对日期
        if date_str in ["今天", "今日", "today"]:
            return today.strftime("%Y-%m-%d")
        elif date_str in ["明天", "明日", "tomorrow"]:
            return (today + timedelta(days=1)).strftime("%Y-%m-%d")
        elif date_str in ["后天", "day after tomorrow", "overmorrow"]:
            return (today + timedelta(days=2)).strftime("%Y-%m-%d")
        
        # 标准格式 YYYY-MM-DD
        if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
            return date_str
        
        # MM-DD 格式
        if re.match(r'^\d{1,2}-\d{1,2}$', date_str):
            try:
                month, day = map(int, date_str.split('-'))
                parsed_date = today.replace(month=month, day=day)
                # 如果日期已过，则设为明年
                if parsed_date < today:
                    parsed_date = parsed_date.replace(year=today.year + 1)
                return parsed_date.strftime("%Y-%m-%d")
            except ValueError:
                pass
        
        # MMDD 格式 (如：1225)
        if re.match(r'^\d{4}$', date_str) and not date_str.startswith('20'):
            try:
                month = int(date_str[:2])
                day = int(date_str[2:])
                parsed_date = today.replace(month=month, day=day)
                if parsed_date < today:
                    parsed_date = parsed_date.replace(year=today.year + 1)
                return parsed_date.strftime("%Y-%m-%d")
            except ValueError:
                pass
        
        # MM/DD 格式
        if re.match(r'^\d{1,2}/\d{1,2}$', date_str):
            try:
                month, day = map(int, date_str.split('/'))
                parsed_date = today.replace(month=month, day=day)
                if parsed_date < today:
                    parsed_date = parsed_date.replace(year=today.year + 1)
                return parsed_date.strftime("%Y-%m-%d")
            except ValueError:
                pass
        
        # 相对日期（数字 + 天后）
        if re.match(r'^\d+[天后]', date_str):
            try:
                days = int(re.findall(r'\d+', date_str)[0])
                return (today + timedelta(days=days)).strftime("%Y-%m-%d")
            except (ValueError, IndexError):
                pass
        
        # 英文月份格式 (如: Dec 25)
        month_mapping = {
            'jan': 1, 'january': 1,
            'feb': 2, 'february': 2, 
            'mar': 3, 'march': 3,
            'apr': 4, 'april': 4,
            'may': 5,
            'jun': 6, 'june': 6,
            'jul': 7, 'july': 7,
            'aug': 8, 'august': 8,
            'sep': 9, 'september': 9,
            'oct': 10, 'october': 10,
            'nov': 11, 'november': 11,
            'dec': 12, 'december': 12
        }
        
        for month_name, month_num in month_mapping.items():
            if month_name in date_str:
                try:
                    # 提取日期数字
                    day_match = re.search(r'\d+', date_str.replace(month_name, ''))
                    if day_match:
                        day = int(day_match.group())
                        parsed_date = today.replace(month=month_num, day=day)
                        if parsed_date < today:
                            parsed_date = parsed_date.replace(year=today.year + 1)
                        return parsed_date.strftime("%Y-%m-%d")
                except ValueError:
                    pass
        
        # 如果都无法解析，返回今天
        return today.strftime("%Y-%m-%d")
    
    @classmethod
    def parse_route_input(cls, input_str: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        智能解析路线输入
        
        支持格式：
        - "北京 上海"
        - "北京 上海 明天"
        - "PEK SHA 12-25"
        - "Beijing Shanghai tomorrow"
        
        Returns:
            Tuple[出发地机场代码, 目的地机场代码, 日期]: 如 ("PEK", "SHA", "2024-12-25")
        """
        parts = input_str.split()
        
        if len(parts) < 2:
            return None, None, None
        
        # 转换出发地和目的地
        dep_code, _ = cls.smart_convert_to_airport_code(parts[0])
        arr_code, _ = cls.smart_convert_to_airport_code(parts[1])
        
        # 解析日期
        date_str = ""
        if len(parts) > 2:
            date_str = " ".join(parts[2:])
        
        parsed_date = cls.parse_smart_date(date_str)
        
        return dep_code, arr_code, parsed_date
    
    @classmethod
    def parse_flight_input(cls, input_str: str) -> Tuple[Optional[str], Optional[str]]:
        """
        智能解析航班号输入
        
        支持格式：
        - "MU2157"
        - "MU2157 明天"
        - "MU2157 12-25"
        
        Returns:
            Tuple[航班号, 日期]: 如 ("MU2157", "2024-12-25")
        """
        parts = input_str.split()
        
        if len(parts) < 1:
            return None, None
        
        flight_num = parts[0].upper()
        
        # 检查航班号格式
        if not re.match(r'^[A-Z0-9]{2,3}[0-9]{1,4}$', flight_num):
            return None, None
        
        # 解析日期
        date_str = ""
        if len(parts) > 1:
            date_str = " ".join(parts[1:])
        
        parsed_date = cls.parse_smart_date(date_str)
        
        return flight_num, parsed_date


def format_price_info(price_data: dict) -> str:
    """格式化价格信息"""
    if not price_data or not price_data.get("data"):
        return "❌ 未找到价格信息"
    
    data = price_data["data"]
    if isinstance(data, list):
        if not data:
            return "❌ 未找到价格信息"
        data = data[0]  # 取第一个结果
    
    # 提取价格信息
    dep_city = data.get("depCityName", "")
    arr_city = data.get("arrCityName", "")
    dep_date = data.get("depDate", "")
    
    formatted = f"💰 **{dep_city} → {arr_city} 机票价格**\n\n"
    formatted += f"📅 **出发日期**: {dep_date}\n\n"
    
    # 解析航班选项
    if "flights" in data and data["flights"]:
        flights = data["flights"][:5]  # 显示前5个最便宜的选项
        
        formatted += "✈️ **可选航班** (按价格排序):\n\n"
        
        for i, flight in enumerate(flights, 1):
            airline = flight.get("airline", "")
            flight_num = flight.get("flightNum", "")
            dep_time = flight.get("depTime", "")
            arr_time = flight.get("arrTime", "")
            price = flight.get("price", "")
            
            formatted += f"**{i}\\. {airline} {flight_num}**\n"
            formatted += f"🕐 `{dep_time}` \\- `{arr_time}`\n"
            formatted += f"💰 价格: **¥{price}**\n\n"
        
        # 如果有更多选项，显示提示
        if len(data["flights"]) > 5:
            formatted += f"\\.\\.\\. 还有 {len(data['flights']) - 5} 个选项\n"
    
    # 显示最低价格
    if "minPrice" in data:
        formatted += f"🎯 **最低价格**: ¥{data['minPrice']}\n"
    
    formatted += f"\n_数据来源: Variflight_"
    formatted += f"\n_更新时间: {datetime.now().strftime('%H:%M:%S')}_"
    
    return formatted