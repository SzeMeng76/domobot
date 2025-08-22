#!/usr/bin/env python3
"""
机场数据模块
提供全球主要机场的智能搜索功能
支持城市名、国家名、机场代码的中英文搜索
"""

import logging
from typing import List, Optional, Dict
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class Airport:
    """机场信息"""
    code: str
    name: str
    city: str
    country: str
    country_code: str = ""
    timezone: str = ""

class AirportDatabase:
    """机场数据库"""
    
    def __init__(self):
        self.airports = self._load_airport_data()
        self.city_mapping = self._build_city_mapping()
        self.country_mapping = self._build_country_mapping()
    
    def _load_airport_data(self) -> Dict[str, Airport]:
        """加载机场数据"""
        airports = {
            # 中国主要机场
            "PEK": Airport("PEK", "北京首都国际机场", "北京", "中国", "CN", "Asia/Shanghai"),
            "PKX": Airport("PKX", "北京大兴国际机场", "北京", "中国", "CN", "Asia/Shanghai"),
            "PVG": Airport("PVG", "上海浦东国际机场", "上海", "中国", "CN", "Asia/Shanghai"),
            "SHA": Airport("SHA", "上海虹桥国际机场", "上海", "中国", "CN", "Asia/Shanghai"),
            "CAN": Airport("CAN", "广州白云国际机场", "广州", "中国", "CN", "Asia/Shanghai"),
            "SZX": Airport("SZX", "深圳宝安国际机场", "深圳", "中国", "CN", "Asia/Shanghai"),
            "CTU": Airport("CTU", "成都双流国际机场", "成都", "中国", "CN", "Asia/Shanghai"),
            "CKG": Airport("CKG", "重庆江北国际机场", "重庆", "中国", "CN", "Asia/Shanghai"),
            "XIY": Airport("XIY", "西安咸阳国际机场", "西安", "中国", "CN", "Asia/Shanghai"),
            "KMG": Airport("KMG", "昆明长水国际机场", "昆明", "中国", "CN", "Asia/Shanghai"),
            "HGH": Airport("HGH", "杭州萧山国际机场", "杭州", "中国", "CN", "Asia/Shanghai"),
            "NKG": Airport("NKG", "南京禄口国际机场", "南京", "中国", "CN", "Asia/Shanghai"),
            "TAO": Airport("TAO", "青岛流亭国际机场", "青岛", "中国", "CN", "Asia/Shanghai"),
            "DLC": Airport("DLC", "大连周水子国际机场", "大连", "中国", "CN", "Asia/Shanghai"),
            "XMN": Airport("XMN", "厦门高崎国际机场", "厦门", "中国", "CN", "Asia/Shanghai"),
            "WUH": Airport("WUH", "武汉天河国际机场", "武汉", "中国", "CN", "Asia/Shanghai"),
            "CSX": Airport("CSX", "长沙黄花国际机场", "长沙", "中国", "CN", "Asia/Shanghai"),
            "SHE": Airport("SHE", "沈阳桃仙国际机场", "沈阳", "中国", "CN", "Asia/Shanghai"),
            "HRB": Airport("HRB", "哈尔滨太平国际机场", "哈尔滨", "中国", "CN", "Asia/Shanghai"),
            "URC": Airport("URC", "乌鲁木齐地窝堡国际机场", "乌鲁木齐", "中国", "CN", "Asia/Shanghai"),
            "SYX": Airport("SYX", "三亚凤凰国际机场", "三亚", "中国", "CN", "Asia/Shanghai"),
            "HAK": Airport("HAK", "海口美兰国际机场", "海口", "中国", "CN", "Asia/Shanghai"),
            
            # 美国主要机场
            "JFK": Airport("JFK", "John F. Kennedy International Airport", "New York", "United States", "US", "America/New_York"),
            "LGA": Airport("LGA", "LaGuardia Airport", "New York", "United States", "US", "America/New_York"),
            "EWR": Airport("EWR", "Newark Liberty International Airport", "New York", "United States", "US", "America/New_York"),
            "LAX": Airport("LAX", "Los Angeles International Airport", "Los Angeles", "United States", "US", "America/Los_Angeles"),
            "ORD": Airport("ORD", "O'Hare International Airport", "Chicago", "United States", "US", "America/Chicago"),
            "MDW": Airport("MDW", "Midway International Airport", "Chicago", "United States", "US", "America/Chicago"),
            "SFO": Airport("SFO", "San Francisco International Airport", "San Francisco", "United States", "US", "America/Los_Angeles"),
            "SEA": Airport("SEA", "Seattle-Tacoma International Airport", "Seattle", "United States", "US", "America/Los_Angeles"),
            "BOS": Airport("BOS", "Logan International Airport", "Boston", "United States", "US", "America/New_York"),
            "DCA": Airport("DCA", "Ronald Reagan Washington National Airport", "Washington", "United States", "US", "America/New_York"),
            "IAD": Airport("IAD", "Washington Dulles International Airport", "Washington", "United States", "US", "America/New_York"),
            "BWI": Airport("BWI", "Baltimore/Washington International Airport", "Washington", "United States", "US", "America/New_York"),
            "MIA": Airport("MIA", "Miami International Airport", "Miami", "United States", "US", "America/New_York"),
            "LAS": Airport("LAS", "McCarran International Airport", "Las Vegas", "United States", "US", "America/Los_Angeles"),
            "DEN": Airport("DEN", "Denver International Airport", "Denver", "United States", "US", "America/Denver"),
            "ATL": Airport("ATL", "Hartsfield-Jackson Atlanta International Airport", "Atlanta", "United States", "US", "America/New_York"),
            
            # 欧洲主要机场
            "LHR": Airport("LHR", "London Heathrow Airport", "London", "United Kingdom", "GB", "Europe/London"),
            "LGW": Airport("LGW", "London Gatwick Airport", "London", "United Kingdom", "GB", "Europe/London"),
            "STN": Airport("STN", "London Stansted Airport", "London", "United Kingdom", "GB", "Europe/London"),
            "CDG": Airport("CDG", "Charles de Gaulle Airport", "Paris", "France", "FR", "Europe/Paris"),
            "ORY": Airport("ORY", "Orly Airport", "Paris", "France", "FR", "Europe/Paris"),
            "FRA": Airport("FRA", "Frankfurt Airport", "Frankfurt", "Germany", "DE", "Europe/Berlin"),
            "MUC": Airport("MUC", "Munich Airport", "Munich", "Germany", "DE", "Europe/Berlin"),
            "AMS": Airport("AMS", "Amsterdam Airport Schiphol", "Amsterdam", "Netherlands", "NL", "Europe/Amsterdam"),
            "MAD": Airport("MAD", "Madrid-Barajas Airport", "Madrid", "Spain", "ES", "Europe/Madrid"),
            "FCO": Airport("FCO", "Rome Fiumicino Airport", "Rome", "Italy", "IT", "Europe/Rome"),
            "CIA": Airport("CIA", "Rome Ciampino Airport", "Rome", "Italy", "IT", "Europe/Rome"),
            "ZUR": Airport("ZUR", "Zurich Airport", "Zurich", "Switzerland", "CH", "Europe/Zurich"),
            "VIE": Airport("VIE", "Vienna International Airport", "Vienna", "Austria", "AT", "Europe/Vienna"),
            
            # 亚洲其他主要机场
            "NRT": Airport("NRT", "Narita International Airport", "Tokyo", "Japan", "JP", "Asia/Tokyo"),
            "HND": Airport("HND", "Tokyo Haneda Airport", "Tokyo", "Japan", "JP", "Asia/Tokyo"),
            "KIX": Airport("KIX", "Kansai International Airport", "Osaka", "Japan", "JP", "Asia/Tokyo"),
            "ITM": Airport("ITM", "Osaka International Airport", "Osaka", "Japan", "JP", "Asia/Tokyo"),
            "ICN": Airport("ICN", "Incheon International Airport", "Seoul", "South Korea", "KR", "Asia/Seoul"),
            "GMP": Airport("GMP", "Gimpo International Airport", "Seoul", "South Korea", "KR", "Asia/Seoul"),
            "SIN": Airport("SIN", "Singapore Changi Airport", "Singapore", "Singapore", "SG", "Asia/Singapore"),
            "BKK": Airport("BKK", "Suvarnabhumi Airport", "Bangkok", "Thailand", "TH", "Asia/Bangkok"),
            "KUL": Airport("KUL", "Kuala Lumpur International Airport", "Kuala Lumpur", "Malaysia", "MY", "Asia/Kuala_Lumpur"),
            "MNL": Airport("MNL", "Ninoy Aquino International Airport", "Manila", "Philippines", "PH", "Asia/Manila"),
            "CGK": Airport("CGK", "Soekarno-Hatta International Airport", "Jakarta", "Indonesia", "ID", "Asia/Jakarta"),
            "DEL": Airport("DEL", "Indira Gandhi International Airport", "Delhi", "India", "IN", "Asia/Kolkata"),
            "BOM": Airport("BOM", "Chhatrapati Shivaji Maharaj International Airport", "Mumbai", "India", "IN", "Asia/Kolkata"),
            "DXB": Airport("DXB", "Dubai International Airport", "Dubai", "United Arab Emirates", "AE", "Asia/Dubai"),
            "SYD": Airport("SYD", "Sydney Kingsford Smith Airport", "Sydney", "Australia", "AU", "Australia/Sydney"),
            "MEL": Airport("MEL", "Melbourne Airport", "Melbourne", "Australia", "AU", "Australia/Melbourne"),
            "YVR": Airport("YVR", "Vancouver International Airport", "Vancouver", "Canada", "CA", "America/Vancouver"),
            "YYZ": Airport("YYZ", "Toronto Pearson International Airport", "Toronto", "Canada", "CA", "America/Toronto"),
        }
        
        return airports
    
    def _build_city_mapping(self) -> Dict[str, List[str]]:
        """构建城市名到机场代码的映射"""
        mapping = {}
        
        # 中英文城市名映射
        city_names = {
            # 中国城市
            "北京": ["PEK", "PKX"],
            "beijing": ["PEK", "PKX"],
            "上海": ["PVG", "SHA"],
            "shanghai": ["PVG", "SHA"],
            "广州": ["CAN"],
            "guangzhou": ["CAN"],
            "深圳": ["SZX"],
            "shenzhen": ["SZX"],
            "成都": ["CTU"],
            "chengdu": ["CTU"],
            "重庆": ["CKG"],
            "chongqing": ["CKG"],
            "西安": ["XIY"],
            "xian": ["XIY"],
            "昆明": ["KMG"],
            "kunming": ["KMG"],
            "杭州": ["HGH"],
            "hangzhou": ["HGH"],
            "南京": ["NKG"],
            "nanjing": ["NKG"],
            "青岛": ["TAO"],
            "qingdao": ["TAO"],
            "大连": ["DLC"],
            "dalian": ["DLC"],
            "厦门": ["XMN"],
            "xiamen": ["XMN"],
            "武汉": ["WUH"],
            "wuhan": ["WUH"],
            "长沙": ["CSX"],
            "changsha": ["CSX"],
            "沈阳": ["SHE"],
            "shenyang": ["SHE"],
            "哈尔滨": ["HRB"],
            "harbin": ["HRB"],
            "乌鲁木齐": ["URC"],
            "urumqi": ["URC"],
            "三亚": ["SYX"],
            "sanya": ["SYX"],
            "海口": ["HAK"],
            "haikou": ["HAK"],
            
            # 美国城市
            "纽约": ["JFK", "LGA", "EWR"],
            "new york": ["JFK", "LGA", "EWR"],
            "洛杉矶": ["LAX"],
            "los angeles": ["LAX"],
            "芝加哥": ["ORD", "MDW"],
            "chicago": ["ORD", "MDW"],
            "旧金山": ["SFO"],
            "san francisco": ["SFO"],
            "西雅图": ["SEA"],
            "seattle": ["SEA"],
            "波士顿": ["BOS"],
            "boston": ["BOS"],
            "华盛顿": ["DCA", "IAD", "BWI"],
            "washington": ["DCA", "IAD", "BWI"],
            "迈阿密": ["MIA"],
            "miami": ["MIA"],
            "拉斯维加斯": ["LAS"],
            "las vegas": ["LAS"],
            "丹佛": ["DEN"],
            "denver": ["DEN"],
            "亚特兰大": ["ATL"],
            "atlanta": ["ATL"],
            
            # 欧洲城市
            "伦敦": ["LHR", "LGW", "STN"],
            "london": ["LHR", "LGW", "STN"],
            "巴黎": ["CDG", "ORY"],
            "paris": ["CDG", "ORY"],
            "法兰克福": ["FRA"],
            "frankfurt": ["FRA"],
            "慕尼黑": ["MUC"],
            "munich": ["MUC"],
            "阿姆斯特丹": ["AMS"],
            "amsterdam": ["AMS"],
            "马德里": ["MAD"],
            "madrid": ["MAD"],
            "罗马": ["FCO", "CIA"],
            "rome": ["FCO", "CIA"],
            "苏黎世": ["ZUR"],
            "zurich": ["ZUR"],
            "维也纳": ["VIE"],
            "vienna": ["VIE"],
            
            # 亚洲其他城市
            "东京": ["NRT", "HND"],
            "tokyo": ["NRT", "HND"],
            "大阪": ["KIX", "ITM"],
            "osaka": ["KIX", "ITM"],
            "首尔": ["ICN", "GMP"],
            "seoul": ["ICN", "GMP"],
            "新加坡": ["SIN"],
            "singapore": ["SIN"],
            "曼谷": ["BKK"],
            "bangkok": ["BKK"],
            "吉隆坡": ["KUL"],
            "kuala lumpur": ["KUL"],
            "马尼拉": ["MNL"],
            "manila": ["MNL"],
            "雅加达": ["CGK"],
            "jakarta": ["CGK"],
            "德里": ["DEL"],
            "delhi": ["DEL"],
            "孟买": ["BOM"],
            "mumbai": ["BOM"],
            "迪拜": ["DXB"],
            "dubai": ["DXB"],
            "悉尼": ["SYD"],
            "sydney": ["SYD"],
            "墨尔本": ["MEL"],
            "melbourne": ["MEL"],
            "温哥华": ["YVR"],
            "vancouver": ["YVR"],
            "多伦多": ["YYZ"],
            "toronto": ["YYZ"],
        }
        
        return city_names
    
    def _build_country_mapping(self) -> Dict[str, List[str]]:
        """构建国家名到主要机场代码的映射"""
        return {
            "中国": ["PEK", "PVG", "CAN", "SZX"],
            "china": ["PEK", "PVG", "CAN", "SZX"],
            "美国": ["JFK", "LAX", "ORD", "ATL"],
            "usa": ["JFK", "LAX", "ORD", "ATL"],
            "america": ["JFK", "LAX", "ORD", "ATL"],
            "united states": ["JFK", "LAX", "ORD", "ATL"],
            "英国": ["LHR", "LGW"],
            "uk": ["LHR", "LGW"],
            "britain": ["LHR", "LGW"],
            "england": ["LHR", "LGW"],
            "united kingdom": ["LHR", "LGW"],
            "日本": ["NRT", "HND", "KIX"],
            "japan": ["NRT", "HND", "KIX"],
            "法国": ["CDG", "ORY"],
            "france": ["CDG", "ORY"],
            "德国": ["FRA", "MUC"],
            "germany": ["FRA", "MUC"],
            "新加坡": ["SIN"],
            "singapore": ["SIN"],
            "韩国": ["ICN", "GMP"],
            "south korea": ["ICN", "GMP"],
            "泰国": ["BKK"],
            "thailand": ["BKK"],
            "马来西亚": ["KUL"],
            "malaysia": ["KUL"],
            "澳大利亚": ["SYD", "MEL"],
            "australia": ["SYD", "MEL"],
            "加拿大": ["YVR", "YYZ"],
            "canada": ["YVR", "YYZ"],
        }
    
    def search_airports(self, query: str) -> List[Airport]:
        """智能机场搜索"""
        query_lower = query.lower().strip()
        results = []
        
        # 1. 精确机场代码匹配
        if len(query) == 3 and query.upper() in self.airports:
            return [self.airports[query.upper()]]
        
        # 2. 城市名匹配
        if query_lower in self.city_mapping:
            airport_codes = self.city_mapping[query_lower]
            for code in airport_codes:
                if code in self.airports:
                    results.append(self.airports[code])
            return results
        
        # 3. 国家名匹配
        if query_lower in self.country_mapping:
            airport_codes = self.country_mapping[query_lower]
            for code in airport_codes:
                if code in self.airports:
                    results.append(self.airports[code])
            return results
        
        # 4. 模糊匹配城市名
        for city_name, airport_codes in self.city_mapping.items():
            if query_lower in city_name or city_name in query_lower:
                for code in airport_codes[:2]:  # 限制最多2个结果
                    if code in self.airports:
                        results.append(self.airports[code])
                if results:
                    break
        
        # 5. 模糊匹配机场名称
        if not results:
            for code, airport in self.airports.items():
                if (query_lower in airport.name.lower() or 
                    query_lower in airport.city.lower()):
                    results.append(airport)
                    if len(results) >= 5:  # 限制结果数量
                        break
        
        return results
    
    def get_airport_by_code(self, code: str) -> Optional[Airport]:
        """根据机场代码获取机场信息"""
        return self.airports.get(code.upper())
    
    def get_major_airports_by_country(self, country: str) -> List[Airport]:
        """获取某国家的主要机场"""
        country_lower = country.lower()
        if country_lower in self.country_mapping:
            airport_codes = self.country_mapping[country_lower]
            return [self.airports[code] for code in airport_codes if code in self.airports]
        return []

# 全局机场数据库实例
airport_db = AirportDatabase()

def search_airports(query: str) -> List[Airport]:
    """搜索机场 - 全局函数接口"""
    return airport_db.search_airports(query)

def get_airport_by_code(code: str) -> Optional[Airport]:
    """根据机场代码获取机场信息 - 全局函数接口"""
    return airport_db.get_airport_by_code(code)