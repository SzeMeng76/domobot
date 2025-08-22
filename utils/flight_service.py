#!/usr/bin/env python3
"""
机票查询服务模块
基于fast-flights包装，提供机票查询、价格监控等功能
"""

import asyncio
import logging
from datetime import datetime, date
from typing import Dict, List, Optional, Union, Tuple, Any
import re

# fast-flights相关导入
try:
    from fast_flights import FlightData, Passengers, get_flights, Airport, search_airport
    from fast_flights.schema import Result, Flight
    FAST_FLIGHTS_AVAILABLE = True
except ImportError as e:
    logging.warning(f"fast-flights未安装: {e}")
    FAST_FLIGHTS_AVAILABLE = False
    # 创建mock类防止导入错误
    class FlightData:
        pass
    class Passengers:
        pass
    class Result:
        pass
    class Flight:
        pass

logger = logging.getLogger(__name__)

# 全局变量 - 将在main.py中初始化
cache_manager = None
rate_converter = None

class FlightService:
    """机票查询服务类"""
    
    def __init__(self, cache_manager=None, rate_converter=None):
        """
        初始化机票服务
        
        Args:
            cache_manager: Redis缓存管理器
            rate_converter: 汇率转换器
        """
        self.cache_manager = cache_manager
        self.rate_converter = rate_converter
        
        if not FAST_FLIGHTS_AVAILABLE:
            logger.error("fast-flights包未正确安装，机票查询功能不可用")
    
    async def convert_currency(self, amount: float, from_currency: str, to_currency: str) -> Optional[float]:
        """汇率转换"""
        if not self.rate_converter:
            return None
        try:
            return await self.rate_converter.convert(amount, from_currency, to_currency)
        except Exception as e:
            logger.error(f"汇率转换失败: {e}")
            return None
    
    def _validate_date(self, date_str: str) -> bool:
        """验证日期格式"""
        try:
            date.fromisoformat(date_str)
            return True
        except ValueError:
            return False
    
    def _parse_airport_input(self, airport_input: str) -> Optional[str]:
        """
        解析机场输入，支持机场代码、城市名、国家名等
        
        Args:
            airport_input: 用户输入的机场信息
            
        Returns:
            标准化的机场代码或None
        """
        if not airport_input:
            return None
            
        # 清理输入
        airport_input = airport_input.strip().upper()
        
        # 如果是3字符IATA代码，直接返回
        if len(airport_input) == 3 and airport_input.isalpha():
            return airport_input
            
        # 如果是4字符ICAO代码，暂时返回（可能需要转换）
        if len(airport_input) == 4 and airport_input.isalpha():
            return airport_input
            
        return None
    
    async def search_airports(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        搜索机场
        
        Args:
            query: 搜索关键词（机场名、城市名、国家名等）
            limit: 返回结果数量限制
            
        Returns:
            机场列表，包含代码、名称、城市、国家等信息
        """
        if not FAST_FLIGHTS_AVAILABLE:
            logger.error("fast-flights不可用，无法搜索机场")
            return []
        
        try:
            # 使用缓存 - 参考map.py的实现
            from utils.config_manager import get_config
            config = get_config()
            
            cache_key = f"airport_search_{query.lower().replace(' ', '_')}"
            if self.cache_manager:
                cached_data = await self.cache_manager.load_cache(
                    cache_key,
                    max_age_seconds=config.flights_airport_cache_duration,
                    subdirectory="flights"
                )
                if cached_data:
                    logger.info(f"使用缓存的机场搜索数据: {query}")
                    return cached_data[:limit]
            
            # 调用fast-flights搜索
            airports = search_airport(query)
            
            # 转换为标准格式
            result = []
            for airport in airports[:limit]:
                airport_info = {
                    "code": airport.value if hasattr(airport, 'value') else str(airport),
                    "name": airport.name if hasattr(airport, 'name') else str(airport),
                    "city": getattr(airport, 'city', ''),
                    "country": getattr(airport, 'country', ''),
                    "full_name": f"{airport.name if hasattr(airport, 'name') else str(airport)}"
                }
                result.append(airport_info)
            
            # 缓存结果
            if self.cache_manager and result:
                await self.cache_manager.save_cache(cache_key, result, subdirectory="flights")
                logger.info(f"已缓存机场搜索数据: {query}")
            
            return result
            
        except Exception as e:
            logger.error(f"搜索机场失败: {e}")
            return []
    
    async def get_flight_prices(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: Optional[str] = None,
        adults: int = 1,
        children: int = 0,
        infants_in_seat: int = 0,
        infants_on_lap: int = 0,
        seat_class: str = "economy",
        max_stops: Optional[int] = None,
        preferred_airlines: Optional[List[str]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        查询机票价格
        
        Args:
            origin: 出发机场代码
            destination: 到达机场代码
            departure_date: 出发日期 (YYYY-MM-DD)
            return_date: 返程日期 (YYYY-MM-DD，单程时为None)
            adults: 成人数量
            children: 儿童数量
            infants_in_seat: 婴儿占座数量
            infants_on_lap: 婴儿不占座数量
            seat_class: 舱位等级 ("economy", "premium-economy", "business", "first")
            max_stops: 最大中转次数
            preferred_airlines: 偏好航空公司列表
            
        Returns:
            包含航班信息的字典或None
        """
        if not FAST_FLIGHTS_AVAILABLE:
            logger.error("fast-flights不可用，无法查询机票")
            return None
        
        try:
            # 验证输入
            if not self._validate_date(departure_date):
                raise ValueError(f"无效的出发日期格式: {departure_date}")
            
            if return_date and not self._validate_date(return_date):
                raise ValueError(f"无效的返程日期格式: {return_date}")
            
            # 解析机场代码
            origin_code = self._parse_airport_input(origin)
            destination_code = self._parse_airport_input(destination)
            
            if not origin_code or not destination_code:
                raise ValueError("无效的机场代码")
            
            # 生成缓存键
            cache_params = f"{origin_code}_{destination_code}_{departure_date}_{return_date or 'oneway'}_{adults}_{children}_{infants_in_seat}_{infants_on_lap}_{seat_class}_{max_stops or 'any'}"
            cache_key = f"flight_search_{cache_params}"
            
            # 尝试从缓存获取
            if self.cache_manager:
                from utils.config_manager import get_config
                config = get_config()
                cached_data = await self.cache_manager.load_cache(
                    cache_key,
                    max_age_seconds=config.flights_price_cache_duration,
                    subdirectory="flights"
                )
                if cached_data:
                    logger.info(f"使用缓存的航班数据: {origin_code} -> {destination_code}")
                    return cached_data
            
            # 构建航班数据
            flight_data = [
                FlightData(
                    date=departure_date,
                    from_airport=origin_code,
                    to_airport=destination_code,
                    max_stops=max_stops,
                    airlines=preferred_airlines
                )
            ]
            
            # 如果是往返，添加返程
            trip_type = "one-way"
            if return_date:
                flight_data.append(
                    FlightData(
                        date=return_date,
                        from_airport=destination_code,
                        to_airport=origin_code,
                        max_stops=max_stops,
                        airlines=preferred_airlines
                    )
                )
                trip_type = "round-trip"
            
            # 创建乘客信息
            passengers = Passengers(
                adults=adults,
                children=children,
                infants_in_seat=infants_in_seat,
                infants_on_lap=infants_on_lap
            )
            
            # 查询航班
            logger.info(f"查询航班: {origin_code} -> {destination_code}, {departure_date}")
            result = get_flights(
                flight_data=flight_data,
                trip=trip_type,
                seat=seat_class,
                passengers=passengers,
                fetch_mode="fallback",  # 使用fallback模式提高成功率
                max_stops=max_stops
            )
            
            if not result:
                logger.warning(f"未找到航班: {origin_code} -> {destination_code}")
                return None
            
            # 转换结果格式
            flight_result = self._format_flight_result(result, origin_code, destination_code, departure_date, return_date, trip_type)
            
            # 缓存结果
            if self.cache_manager and flight_result:
                await self.cache_manager.save_cache(cache_key, flight_result, subdirectory="flights")
                logger.info(f"已缓存航班数据: {origin_code} -> {destination_code}")
            
            return flight_result
            
        except Exception as e:
            logger.error(f"查询航班失败: {e}")
            return None
    
    def _format_flight_result(self, result: Result, origin: str, destination: str, 
                            departure_date: str, return_date: Optional[str], trip_type: str) -> Dict[str, Any]:
        """格式化航班查询结果"""
        try:
            formatted_result = {
                "search_info": {
                    "origin": origin,
                    "destination": destination,
                    "departure_date": departure_date,
                    "return_date": return_date,
                    "trip_type": trip_type,
                    "search_time": datetime.now().isoformat()
                },
                "price_trend": result.current_price if hasattr(result, 'current_price') else "unknown",
                "flights": []
            }
            
            # 处理航班列表
            if hasattr(result, 'flights') and result.flights:
                for flight in result.flights:
                    flight_info = {
                        "is_best": getattr(flight, 'is_best', False),
                        "airline": getattr(flight, 'name', ''),
                        "departure_time": getattr(flight, 'departure', ''),
                        "arrival_time": getattr(flight, 'arrival', ''),
                        "arrival_time_ahead": getattr(flight, 'arrival_time_ahead', ''),
                        "duration": getattr(flight, 'duration', ''),
                        "stops": getattr(flight, 'stops', 0),
                        "delay": getattr(flight, 'delay', None),
                        "price": getattr(flight, 'price', ''),
                        "price_numeric": self._extract_price_number(getattr(flight, 'price', ''))
                    }
                    formatted_result["flights"].append(flight_info)
                
                # 按价格排序
                formatted_result["flights"].sort(key=lambda x: x.get("price_numeric", float('inf')))
            
            return formatted_result
            
        except Exception as e:
            logger.error(f"格式化航班结果失败: {e}")
            return None
    
    def _extract_price_number(self, price_str: str) -> float:
        """从价格字符串中提取数字"""
        try:
            # 移除货币符号和逗号，提取数字
            price_clean = re.sub(r'[^\d.]', '', str(price_str))
            return float(price_clean) if price_clean else float('inf')
        except:
            return float('inf')
    
    async def get_price_history(self, origin: str, destination: str, date_range: int = 30) -> List[Dict[str, Any]]:
        """
        获取价格历史趋势（基于缓存数据）
        
        Args:
            origin: 出发机场
            destination: 目的地机场
            date_range: 日期范围（天数）
            
        Returns:
            价格历史数据列表
        """
        if not self.cache_manager:
            return []
        
        try:
            # 查找相关的缓存键
            cache_pattern = f"flight_search_{origin}_{destination}_*"
            # 这里需要实现缓存管理器的模式搜索功能
            # 暂时返回空列表
            return []
            
        except Exception as e:
            logger.error(f"获取价格历史失败: {e}")
            return []
    
    async def monitor_price_changes(self, search_params: Dict[str, Any], target_price: Optional[float] = None) -> Dict[str, Any]:
        """
        监控价格变化
        
        Args:
            search_params: 搜索参数
            target_price: 目标价格（可选）
            
        Returns:
            监控结果
        """
        try:
            # 获取当前价格
            current_result = await self.get_flight_prices(**search_params)
            
            if not current_result or not current_result.get("flights"):
                return {"status": "error", "message": "无法获取当前价格"}
            
            best_flight = current_result["flights"][0]
            current_price = best_flight.get("price_numeric", float('inf'))
            
            monitor_result = {
                "status": "success",
                "current_price": current_price,
                "price_trend": current_result.get("price_trend", "unknown"),
                "search_time": datetime.now().isoformat(),
                "best_flight": best_flight
            }
            
            # 如果设置了目标价格，检查是否达到
            if target_price and current_price <= target_price:
                monitor_result["price_alert"] = True
                monitor_result["message"] = f"价格已降至目标价格 {target_price} 以下"
            else:
                monitor_result["price_alert"] = False
            
            return monitor_result
            
        except Exception as e:
            logger.error(f"价格监控失败: {e}")
            return {"status": "error", "message": str(e)}

# 全局服务实例
flight_service = None

def get_flight_service() -> FlightService:
    """获取全局机票服务实例"""
    global flight_service
    return flight_service

def set_dependencies(cache_manager_instance, rate_converter_instance):
    """设置依赖项 - 参考steam.py的模式"""
    global flight_service, cache_manager, rate_converter
    cache_manager = cache_manager_instance
    rate_converter = rate_converter_instance
    flight_service = FlightService(cache_manager, rate_converter)

def set_rate_converter(rate_converter_instance):
    """设置汇率转换器 - 参考steam.py的模式"""
    global rate_converter
    rate_converter = rate_converter_instance
    if flight_service:
        flight_service.rate_converter = rate_converter_instance

def init_flight_service(cache_manager=None, rate_converter=None) -> FlightService:
    """初始化机票服务"""
    global flight_service
    flight_service = FlightService(cache_manager, rate_converter)
    return flight_service