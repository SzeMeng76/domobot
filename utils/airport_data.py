#!/usr/bin/env python3
"""
机场数据管理模块
提供智能机场搜索功能，支持多语言查询（中英文城市名、国家名、机场代码等）
结合country_data.py实现国际化支持
"""

import logging
import re
from typing import Dict, List, Optional, Tuple, Any
from difflib import SequenceMatcher

# 导入国家数据
from utils.country_data import SUPPORTED_COUNTRIES, COUNTRY_NAME_TO_CODE, get_country_flag

logger = logging.getLogger(__name__)

class AirportData:
    """机场数据管理类"""
    
    def __init__(self):
        """初始化机场数据"""
        self.airports = self._load_airport_data()
        self.city_mappings = self._build_city_mappings()
        self.country_mappings = self._build_country_mappings()
        
    def _load_airport_data(self) -> Dict[str, Dict[str, Any]]:
        """
        加载机场数据
        包含全球主要机场的IATA代码、名称、城市、国家等信息
        """
        # 全球主要机场数据（按地区分类）
        airports = {
            # 中国大陆
            "PEK": {"name": "Beijing Capital International Airport", "name_cn": "北京首都国际机场", "city": "Beijing", "city_cn": "北京", "country": "CN", "timezone": "Asia/Shanghai"},
            "PVG": {"name": "Shanghai Pudong International Airport", "name_cn": "上海浦东国际机场", "city": "Shanghai", "city_cn": "上海", "country": "CN", "timezone": "Asia/Shanghai"},
            "SHA": {"name": "Shanghai Hongqiao International Airport", "name_cn": "上海虹桥国际机场", "city": "Shanghai", "city_cn": "上海", "country": "CN", "timezone": "Asia/Shanghai"},
            "CAN": {"name": "Guangzhou Baiyun International Airport", "name_cn": "广州白云国际机场", "city": "Guangzhou", "city_cn": "广州", "country": "CN", "timezone": "Asia/Shanghai"},
            "SZX": {"name": "Shenzhen Bao'an International Airport", "name_cn": "深圳宝安国际机场", "city": "Shenzhen", "city_cn": "深圳", "country": "CN", "timezone": "Asia/Shanghai"},
            "CTU": {"name": "Chengdu Tianfu International Airport", "name_cn": "成都天府国际机场", "city": "Chengdu", "city_cn": "成都", "country": "CN", "timezone": "Asia/Shanghai"},
            "XIY": {"name": "Xi'an Xianyang International Airport", "name_cn": "西安咸阳国际机场", "city": "Xi'an", "city_cn": "西安", "country": "CN", "timezone": "Asia/Shanghai"},
            "KMG": {"name": "Kunming Changshui International Airport", "name_cn": "昆明长水国际机场", "city": "Kunming", "city_cn": "昆明", "country": "CN", "timezone": "Asia/Shanghai"},
            "HGH": {"name": "Hangzhou Xiaoshan International Airport", "name_cn": "杭州萧山国际机场", "city": "Hangzhou", "city_cn": "杭州", "country": "CN", "timezone": "Asia/Shanghai"},
            "NKG": {"name": "Nanjing Lukou International Airport", "name_cn": "南京禄口国际机场", "city": "Nanjing", "city_cn": "南京", "country": "CN", "timezone": "Asia/Shanghai"},
            
            # 港澳台
            "HKG": {"name": "Hong Kong International Airport", "name_cn": "香港国际机场", "city": "Hong Kong", "city_cn": "香港", "country": "HK", "timezone": "Asia/Hong_Kong"},
            "MFM": {"name": "Macau International Airport", "name_cn": "澳门国际机场", "city": "Macau", "city_cn": "澳门", "country": "MO", "timezone": "Asia/Macau"},
            "TPE": {"name": "Taiwan Taoyuan International Airport", "name_cn": "台湾桃园国际机场", "city": "Taipei", "city_cn": "台北", "country": "TW", "timezone": "Asia/Taipei"},
            "TSA": {"name": "Taipei Songshan Airport", "name_cn": "台北松山机场", "city": "Taipei", "city_cn": "台北", "country": "TW", "timezone": "Asia/Taipei"},
            
            # 日本
            "NRT": {"name": "Narita International Airport", "name_cn": "成田国际机场", "city": "Tokyo", "city_cn": "东京", "country": "JP", "timezone": "Asia/Tokyo"},
            "HND": {"name": "Tokyo Haneda Airport", "name_cn": "东京羽田机场", "city": "Tokyo", "city_cn": "东京", "country": "JP", "timezone": "Asia/Tokyo"},
            "KIX": {"name": "Kansai International Airport", "name_cn": "关西国际机场", "city": "Osaka", "city_cn": "大阪", "country": "JP", "timezone": "Asia/Tokyo"},
            "ITM": {"name": "Itami Airport", "name_cn": "伊丹机场", "city": "Osaka", "city_cn": "大阪", "country": "JP", "timezone": "Asia/Tokyo"},
            "NGO": {"name": "Chubu Centrair International Airport", "name_cn": "中部国际机场", "city": "Nagoya", "city_cn": "名古屋", "country": "JP", "timezone": "Asia/Tokyo"},
            
            # 韩国
            "ICN": {"name": "Incheon International Airport", "name_cn": "仁川国际机场", "city": "Seoul", "city_cn": "首尔", "country": "KR", "timezone": "Asia/Seoul"},
            "GMP": {"name": "Gimpo International Airport", "name_cn": "金浦国际机场", "city": "Seoul", "city_cn": "首尔", "country": "KR", "timezone": "Asia/Seoul"},
            "PUS": {"name": "Busan Gimhae International Airport", "name_cn": "釜山金海国际机场", "city": "Busan", "city_cn": "釜山", "country": "KR", "timezone": "Asia/Seoul"},
            
            # 东南亚
            "SIN": {"name": "Singapore Changi Airport", "name_cn": "新加坡樟宜机场", "city": "Singapore", "city_cn": "新加坡", "country": "SG", "timezone": "Asia/Singapore"},
            "KUL": {"name": "Kuala Lumpur International Airport", "name_cn": "吉隆坡国际机场", "city": "Kuala Lumpur", "city_cn": "吉隆坡", "country": "MY", "timezone": "Asia/Kuala_Lumpur"},
            "BKK": {"name": "Suvarnabhumi Airport", "name_cn": "苏凡纳布米机场", "city": "Bangkok", "city_cn": "曼谷", "country": "TH", "timezone": "Asia/Bangkok"},
            "DMK": {"name": "Don Mueang International Airport", "name_cn": "廊曼国际机场", "city": "Bangkok", "city_cn": "曼谷", "country": "TH", "timezone": "Asia/Bangkok"},
            "CGK": {"name": "Soekarno-Hatta International Airport", "name_cn": "苏加诺-哈达国际机场", "city": "Jakarta", "city_cn": "雅加达", "country": "ID", "timezone": "Asia/Jakarta"},
            "MNL": {"name": "Ninoy Aquino International Airport", "name_cn": "尼诺伊·阿基诺国际机场", "city": "Manila", "city_cn": "马尼拉", "country": "PH", "timezone": "Asia/Manila"},
            
            # 美国
            "LAX": {"name": "Los Angeles International Airport", "name_cn": "洛杉矶国际机场", "city": "Los Angeles", "city_cn": "洛杉矶", "country": "US", "timezone": "America/Los_Angeles"},
            "JFK": {"name": "John F. Kennedy International Airport", "name_cn": "肯尼迪国际机场", "city": "New York", "city_cn": "纽约", "country": "US", "timezone": "America/New_York"},
            "LGA": {"name": "LaGuardia Airport", "name_cn": "拉瓜迪亚机场", "city": "New York", "city_cn": "纽约", "country": "US", "timezone": "America/New_York"},
            "ORD": {"name": "O'Hare International Airport", "name_cn": "奥黑尔国际机场", "city": "Chicago", "city_cn": "芝加哥", "country": "US", "timezone": "America/Chicago"},
            "SFO": {"name": "San Francisco International Airport", "name_cn": "旧金山国际机场", "city": "San Francisco", "city_cn": "旧金山", "country": "US", "timezone": "America/Los_Angeles"},
            "SEA": {"name": "Seattle-Tacoma International Airport", "name_cn": "西雅图-塔科马国际机场", "city": "Seattle", "city_cn": "西雅图", "country": "US", "timezone": "America/Los_Angeles"},
            "MIA": {"name": "Miami International Airport", "name_cn": "迈阿密国际机场", "city": "Miami", "city_cn": "迈阿密", "country": "US", "timezone": "America/New_York"},
            
            # 加拿大
            "YVR": {"name": "Vancouver International Airport", "name_cn": "温哥华国际机场", "city": "Vancouver", "city_cn": "温哥华", "country": "CA", "timezone": "America/Vancouver"},
            "YYZ": {"name": "Toronto Pearson International Airport", "name_cn": "多伦多皮尔逊国际机场", "city": "Toronto", "city_cn": "多伦多", "country": "CA", "timezone": "America/Toronto"},
            
            # 欧洲
            "LHR": {"name": "London Heathrow Airport", "name_cn": "伦敦希思罗机场", "city": "London", "city_cn": "伦敦", "country": "GB", "timezone": "Europe/London"},
            "LGW": {"name": "London Gatwick Airport", "name_cn": "伦敦盖特威克机场", "city": "London", "city_cn": "伦敦", "country": "GB", "timezone": "Europe/London"},
            "CDG": {"name": "Charles de Gaulle Airport", "name_cn": "戴高乐机场", "city": "Paris", "city_cn": "巴黎", "country": "FR", "timezone": "Europe/Paris"},
            "FRA": {"name": "Frankfurt Airport", "name_cn": "法兰克福机场", "city": "Frankfurt", "city_cn": "法兰克福", "country": "DE", "timezone": "Europe/Berlin"},
            "AMS": {"name": "Amsterdam Airport Schiphol", "name_cn": "阿姆斯特丹史基浦机场", "city": "Amsterdam", "city_cn": "阿姆斯特丹", "country": "NL", "timezone": "Europe/Amsterdam"},
            "FCO": {"name": "Rome Fiumicino Airport", "name_cn": "罗马菲乌米奇诺机场", "city": "Rome", "city_cn": "罗马", "country": "IT", "timezone": "Europe/Rome"},
            "MAD": {"name": "Madrid-Barajas Airport", "name_cn": "马德里-巴拉哈斯机场", "city": "Madrid", "city_cn": "马德里", "country": "ES", "timezone": "Europe/Madrid"},
            "ZUR": {"name": "Zurich Airport", "name_cn": "苏黎世机场", "city": "Zurich", "city_cn": "苏黎世", "country": "CH", "timezone": "Europe/Zurich"},
            
            # 中东
            "DXB": {"name": "Dubai International Airport", "name_cn": "迪拜国际机场", "city": "Dubai", "city_cn": "迪拜", "country": "AE", "timezone": "Asia/Dubai"},
            "DOH": {"name": "Hamad International Airport", "name_cn": "哈马德国际机场", "city": "Doha", "city_cn": "多哈", "country": "QA", "timezone": "Asia/Qatar"},
            
            # 澳洲
            "SYD": {"name": "Sydney Kingsford Smith Airport", "name_cn": "悉尼金斯福德·史密斯机场", "city": "Sydney", "city_cn": "悉尼", "country": "AU", "timezone": "Australia/Sydney"},
            "MEL": {"name": "Melbourne Airport", "name_cn": "墨尔本机场", "city": "Melbourne", "city_cn": "墨尔本", "country": "AU", "timezone": "Australia/Melbourne"},
            
            # 印度
            "DEL": {"name": "Indira Gandhi International Airport", "name_cn": "英迪拉·甘地国际机场", "city": "New Delhi", "city_cn": "新德里", "country": "IN", "timezone": "Asia/Kolkata"},
            "BOM": {"name": "Chhatrapati Shivaji Maharaj International Airport", "name_cn": "贾特拉帕蒂·希瓦吉国际机场", "city": "Mumbai", "city_cn": "孟买", "country": "IN", "timezone": "Asia/Kolkata"},
        }
        
        return airports
    
    def _build_city_mappings(self) -> Dict[str, List[str]]:
        """构建城市名称到机场代码的映射"""
        city_mappings = {}
        
        for code, info in self.airports.items():
            # 英文城市名
            city_en = info["city"].lower()
            if city_en not in city_mappings:
                city_mappings[city_en] = []
            city_mappings[city_en].append(code)
            
            # 中文城市名
            city_cn = info["city_cn"].lower()
            if city_cn not in city_mappings:
                city_mappings[city_cn] = []
            city_mappings[city_cn].append(code)
        
        return city_mappings
    
    def _build_country_mappings(self) -> Dict[str, List[str]]:
        """构建国家到机场代码的映射"""
        country_mappings = {}
        
        for code, info in self.airports.items():
            country_code = info["country"]
            if country_code not in country_mappings:
                country_mappings[country_code] = []
            country_mappings[country_code].append(code)
        
        return country_mappings
    
    def _calculate_similarity(self, s1: str, s2: str) -> float:
        """计算字符串相似度"""
        return SequenceMatcher(None, s1.lower(), s2.lower()).ratio()
    
    def search_airports(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        智能机场搜索
        支持多种查询方式：
        1. 机场代码 (PEK, LAX等)
        2. 英文城市名 (Beijing, New York等)
        3. 中文城市名 (北京, 纽约等)
        4. 英文国家名 (China, United States等)
        5. 中文国家名 (中国, 美国等)
        6. 国家代码 (CN, US等)
        7. 机场名称 (partial match)
        
        Args:
            query: 查询字符串
            limit: 返回结果数量限制
            
        Returns:
            匹配的机场列表，按相关性排序
        """
        if not query:
            return []
        
        query = query.strip()
        results = []
        
        # 1. 精确匹配机场代码
        if len(query) == 3 and query.upper() in self.airports:
            airport_code = query.upper()
            airport_info = self.airports[airport_code]
            results.append(self._format_airport_result(airport_code, airport_info, 1.0))
            return results
        
        # 2. 城市名查询（中英文）
        city_matches = self._search_by_city(query)
        results.extend(city_matches)
        
        # 3. 国家查询（代码、中英文名称）
        country_matches = self._search_by_country(query)
        results.extend(country_matches)
        
        # 4. 机场名称模糊匹配
        name_matches = self._search_by_airport_name(query)
        results.extend(name_matches)
        
        # 去重并按相关性排序
        seen = set()
        unique_results = []
        for result in results:
            code = result["code"]
            if code not in seen:
                seen.add(code)
                unique_results.append(result)
        
        # 按相关性分数排序
        unique_results.sort(key=lambda x: x["relevance"], reverse=True)
        
        return unique_results[:limit]
    
    def _search_by_city(self, query: str) -> List[Dict[str, Any]]:
        """按城市名搜索"""
        results = []
        query_lower = query.lower()
        
        # 精确匹配
        if query_lower in self.city_mappings:
            for code in self.city_mappings[query_lower]:
                airport_info = self.airports[code]
                results.append(self._format_airport_result(code, airport_info, 0.9))
        
        # 模糊匹配城市名
        for city_name, codes in self.city_mappings.items():
            similarity = self._calculate_similarity(query_lower, city_name)
            if similarity > 0.6 and query_lower != city_name:  # 避免重复添加精确匹配
                for code in codes:
                    airport_info = self.airports[code]
                    results.append(self._format_airport_result(code, airport_info, similarity * 0.8))
        
        return results
    
    def _search_by_country(self, query: str) -> List[Dict[str, Any]]:
        """按国家搜索"""
        results = []
        query_upper = query.upper()
        query_lower = query.lower()
        
        # 1. 国家代码精确匹配
        if query_upper in self.country_mappings:
            for code in self.country_mappings[query_upper]:
                airport_info = self.airports[code]
                results.append(self._format_airport_result(code, airport_info, 0.7))
        
        # 2. 国家中文名称匹配
        if query in COUNTRY_NAME_TO_CODE:
            country_code = COUNTRY_NAME_TO_CODE[query]
            if country_code in self.country_mappings:
                for code in self.country_mappings[country_code]:
                    airport_info = self.airports[code]
                    results.append(self._format_airport_result(code, airport_info, 0.8))
        
        # 3. 国家英文名称模糊匹配
        for country_code, country_info in SUPPORTED_COUNTRIES.items():
            # 这里可以扩展英文国家名称匹配
            # 当前版本主要支持中文名称
            pass
        
        return results
    
    def _search_by_airport_name(self, query: str) -> List[Dict[str, Any]]:
        """按机场名称搜索"""
        results = []
        query_lower = query.lower()
        
        for code, info in self.airports.items():
            # 英文名称匹配
            name_en = info["name"].lower()
            if query_lower in name_en:
                similarity = len(query_lower) / len(name_en)  # 简单的相关性计算
                results.append(self._format_airport_result(code, info, similarity * 0.6))
            
            # 中文名称匹配
            name_cn = info["name_cn"].lower()
            if query_lower in name_cn:
                similarity = len(query_lower) / len(name_cn)
                results.append(self._format_airport_result(code, info, similarity * 0.6))
        
        return results
    
    def _format_airport_result(self, code: str, info: Dict[str, Any], relevance: float) -> Dict[str, Any]:
        """格式化机场搜索结果"""
        country_code = info["country"]
        country_info = SUPPORTED_COUNTRIES.get(country_code, {})
        country_name = country_info.get("name", info["country"])
        country_flag = get_country_flag(country_code)
        
        return {
            "code": code,
            "name": info["name"],
            "name_cn": info["name_cn"],
            "city": info["city"],
            "city_cn": info["city_cn"],
            "country": country_code,
            "country_name": country_name,
            "country_flag": country_flag,
            "timezone": info.get("timezone", ""),
            "relevance": relevance,
            "display_name": f"{info['city_cn']} ({info['city']}) - {code}",
            "full_info": f"{country_flag} {info['name_cn']} ({info['name']})"
        }
    
    def get_airport_info(self, code: str) -> Optional[Dict[str, Any]]:
        """获取指定机场的详细信息"""
        code = code.upper()
        if code in self.airports:
            return self._format_airport_result(code, self.airports[code], 1.0)
        return None
    
    def get_airports_by_country(self, country_code: str) -> List[Dict[str, Any]]:
        """获取指定国家的所有机场"""
        country_code = country_code.upper()
        if country_code in self.country_mappings:
            results = []
            for airport_code in self.country_mappings[country_code]:
                airport_info = self.airports[airport_code]
                results.append(self._format_airport_result(airport_code, airport_info, 1.0))
            return results
        return []
    
    def validate_airport_code(self, code: str) -> bool:
        """验证机场代码是否有效"""
        return code.upper() in self.airports
    
    def get_popular_routes(self, from_country: Optional[str] = None) -> List[Tuple[str, str, str]]:
        """
        获取热门航线推荐
        
        Args:
            from_country: 起始国家代码，None表示全球
            
        Returns:
            (起始机场代码, 目标机场代码, 航线描述) 的列表
        """
        # 定义一些热门航线
        popular_routes = [
            ("PEK", "LAX", "北京 → 洛杉矶"),
            ("PVG", "NRT", "上海 → 东京"),
            ("HKG", "SIN", "香港 → 新加坡"),
            ("ICN", "JFK", "首尔 → 纽约"),
            ("LHR", "JFK", "伦敦 → 纽约"),
            ("CDG", "DXB", "巴黎 → 迪拜"),
            ("SIN", "SYD", "新加坡 → 悉尼"),
            ("NRT", "LAX", "东京 → 洛杉矶"),
            ("FRA", "PEK", "法兰克福 → 北京"),
            ("DXB", "BOM", "迪拜 → 孟买"),
        ]
        
        if from_country:
            # 筛选指定国家出发的航线
            filtered_routes = []
            for origin, dest, desc in popular_routes:
                if origin in self.airports and self.airports[origin]["country"] == from_country.upper():
                    filtered_routes.append((origin, dest, desc))
            return filtered_routes
        
        return popular_routes

# 全局机场数据实例
airport_data = None

def get_airport_data() -> AirportData:
    """获取全局机场数据实例"""
    global airport_data
    if airport_data is None:
        airport_data = AirportData()
    return airport_data

def init_airport_data() -> AirportData:
    """初始化机场数据"""
    global airport_data
    airport_data = AirportData()
    logger.info(f"已初始化机场数据，包含 {len(airport_data.airports)} 个机场")
    return airport_data