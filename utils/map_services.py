#!/usr/bin/env python3
"""
地图服务核心模块
提供Google Maps和高德地图API的统一接口
"""

import logging
import urllib.parse
from typing import Dict, List, Optional, Tuple, Any
import json

from utils.language_detector import detect_user_language, get_map_service

logger = logging.getLogger(__name__)

class MapService:
    """地图服务基类"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        
    async def search_location(self, query: str) -> Optional[Dict]:
        """搜索位置"""
        raise NotImplementedError
        
    async def geocode(self, address: str) -> Optional[Dict]:
        """地理编码：地址转坐标"""
        raise NotImplementedError
        
    async def reverse_geocode(self, lat: float, lng: float) -> Optional[Dict]:
        """逆地理编码：坐标转地址"""
        raise NotImplementedError
        
    async def search_nearby(self, lat: float, lng: float, place_type: str, radius: int = 1000) -> List[Dict]:
        """搜索附近"""
        raise NotImplementedError
        
    async def get_directions(self, origin: str, destination: str, mode: str = "driving") -> Optional[Dict]:
        """路线规划"""
        raise NotImplementedError
        
    def get_map_url(self, lat: float, lng: float, zoom: int = 15) -> str:
        """生成地图链接"""
        raise NotImplementedError
        
    def get_navigation_url(self, destination: str) -> str:
        """生成导航链接"""
        raise NotImplementedError


class GoogleMapsService(MapService):
    """Google Maps服务"""
    
    BASE_URL = "https://maps.googleapis.com/maps/api"
    
    async def search_location(self, query: str, httpx_client=None) -> Optional[Dict]:
        """使用Google Places API搜索位置"""
        try:
            params = {
                'query': query,
                'key': self.api_key,
                'language': 'en'
            }
            
            url = f"{self.BASE_URL}/place/textsearch/json"
            response = await httpx_client.get(url, params=params, timeout=20)
            response.raise_for_status()
            
            data = response.json()
            if data['status'] == 'OK' and data['results']:
                place = data['results'][0]
                return {
                    'name': place['name'],
                    'address': place['formatted_address'],
                    'lat': place['geometry']['location']['lat'],
                    'lng': place['geometry']['location']['lng'],
                    'place_id': place['place_id'],
                    'rating': place.get('rating'),
                    'types': place.get('types', [])
                }
            return None
            
        except Exception as e:
            logger.error(f"Google Maps搜索失败: {e}")
            return None
    
    async def geocode(self, address: str, httpx_client=None) -> Optional[Dict]:
        """Google地理编码"""
        try:
            params = {
                'address': address,
                'key': self.api_key,
                'language': 'en'
            }
            
            url = f"{self.BASE_URL}/geocode/json"
            response = await httpx_client.get(url, params=params, timeout=20)
            response.raise_for_status()
            
            data = response.json()
            if data['status'] == 'OK' and data['results']:
                result = data['results'][0]
                return {
                    'address': result['formatted_address'],
                    'lat': result['geometry']['location']['lat'],
                    'lng': result['geometry']['location']['lng'],
                    'components': result.get('address_components', [])
                }
            return None
            
        except Exception as e:
            logger.error(f"Google地理编码失败: {e}")
            return None
    
    async def reverse_geocode(self, lat: float, lng: float, httpx_client=None) -> Optional[Dict]:
        """Google逆地理编码"""
        try:
            params = {
                'latlng': f"{lat},{lng}",
                'key': self.api_key,
                'language': 'en'
            }
            
            url = f"{self.BASE_URL}/geocode/json"
            response = await httpx_client.get(url, params=params, timeout=20)
            response.raise_for_status()
            
            data = response.json()
            if data['status'] == 'OK' and data['results']:
                result = data['results'][0]
                return {
                    'address': result['formatted_address'],
                    'components': result.get('address_components', [])
                }
            return None
            
        except Exception as e:
            logger.error(f"Google逆地理编码失败: {e}")
            return None
    
    async def search_nearby(self, lat: float, lng: float, place_type: str, radius: int = 1000, httpx_client=None) -> List[Dict]:
        """Google附近搜索"""
        try:
            params = {
                'location': f"{lat},{lng}",
                'radius': radius,
                'type': place_type,
                'key': self.api_key,
                'language': 'en'
            }
            
            url = f"{self.BASE_URL}/place/nearbysearch/json"
            response = await httpx_client.get(url, params=params, timeout=20)
            response.raise_for_status()
            
            data = response.json()
            results = []
            
            if data['status'] == 'OK':
                for place in data['results'][:10]:  # 限制前10个结果
                    results.append({
                        'name': place['name'],
                        'address': place.get('vicinity', ''),
                        'lat': place['geometry']['location']['lat'],
                        'lng': place['geometry']['location']['lng'],
                        'rating': place.get('rating'),
                        'types': place.get('types', []),
                        'price_level': place.get('price_level')
                    })
            
            return results
            
        except Exception as e:
            logger.error(f"Google附近搜索失败: {e}")
            return []
    
    async def get_directions(self, origin: str, destination: str, mode: str = "driving", httpx_client=None) -> Optional[Dict]:
        """Google路线规划"""
        try:
            params = {
                'origin': origin,
                'destination': destination,
                'mode': mode,
                'key': self.api_key,
                'language': 'en'
            }
            
            url = f"{self.BASE_URL}/directions/json"
            response = await httpx_client.get(url, params=params, timeout=20)
            response.raise_for_status()
            
            data = response.json()
            if data['status'] == 'OK' and data['routes']:
                route = data['routes'][0]
                leg = route['legs'][0]
                
                return {
                    'distance': leg['distance']['text'],
                    'duration': leg['duration']['text'],
                    'start_address': leg['start_address'],
                    'end_address': leg['end_address'],
                    'steps': [step['html_instructions'] for step in leg['steps'][:5]]  # 前5步
                }
            return None
            
        except Exception as e:
            logger.error(f"Google路线规划失败: {e}")
            return None
    
    def get_map_url(self, lat: float, lng: float, zoom: int = 15) -> str:
        """生成Google Maps链接"""
        return f"https://maps.google.com/?q={lat},{lng}&z={zoom}"
    
    def get_navigation_url(self, destination: str) -> str:
        """生成Google Maps导航链接"""
        encoded_dest = urllib.parse.quote(destination)
        return f"https://maps.google.com/maps?daddr={encoded_dest}"


class AmapService(MapService):
    """高德地图服务"""
    
    BASE_URL = "https://restapi.amap.com/v3"
    
    async def search_location(self, query: str, httpx_client=None) -> Optional[Dict]:
        """使用高德API搜索位置"""
        try:
            params = {
                'keywords': query,
                'key': self.api_key,
                'city': '',  # 全国搜索
                'output': 'json'
            }
            
            url = f"{self.BASE_URL}/place/text"
            response = await httpx_client.get(url, params=params, timeout=20)
            response.raise_for_status()
            
            data = response.json()
            if data['status'] == '1' and data['pois']:
                poi = data['pois'][0]
                location = poi['location'].split(',')
                
                return {
                    'name': poi['name'],
                    'address': poi['address'],
                    'lat': float(location[1]),
                    'lng': float(location[0]),
                    'id': poi['id'],
                    'type': poi.get('type'),
                    'cityname': poi.get('cityname')
                }
            return None
            
        except Exception as e:
            logger.error(f"高德地图搜索失败: {e}")
            return None
    
    async def geocode(self, address: str, httpx_client=None) -> Optional[Dict]:
        """高德地理编码"""
        try:
            params = {
                'address': address,
                'key': self.api_key,
                'output': 'json'
            }
            
            url = f"{self.BASE_URL}/geocode/geo"
            response = await httpx_client.get(url, params=params, timeout=20)
            response.raise_for_status()
            
            data = response.json()
            if data['status'] == '1' and data['geocodes']:
                geocode = data['geocodes'][0]
                location = geocode['location'].split(',')
                
                return {
                    'address': geocode['formatted_address'],
                    'lat': float(location[1]),
                    'lng': float(location[0]),
                    'province': geocode.get('province'),
                    'city': geocode.get('city'),
                    'district': geocode.get('district')
                }
            return None
            
        except Exception as e:
            logger.error(f"高德地理编码失败: {e}")
            return None
    
    async def reverse_geocode(self, lat: float, lng: float, httpx_client=None) -> Optional[Dict]:
        """高德逆地理编码"""
        try:
            params = {
                'location': f"{lng},{lat}",  # 高德使用lng,lat顺序
                'key': self.api_key,
                'output': 'json'
            }
            
            url = f"{self.BASE_URL}/geocode/regeo"
            response = await httpx_client.get(url, params=params, timeout=20)
            response.raise_for_status()
            
            data = response.json()
            if data['status'] == '1' and data['regeocode']:
                regeocode = data['regeocode']
                return {
                    'address': regeocode['formatted_address'],
                    'province': regeocode['addressComponent'].get('province'),
                    'city': regeocode['addressComponent'].get('city'),
                    'district': regeocode['addressComponent'].get('district')
                }
            return None
            
        except Exception as e:
            logger.error(f"高德逆地理编码失败: {e}")
            return None
    
    async def search_nearby(self, lat: float, lng: float, place_type: str, radius: int = 1000, httpx_client=None) -> List[Dict]:
        """高德附近搜索"""
        try:
            # 高德的分类码映射
            type_mapping = {
                'restaurant': '050000',  # 餐饮服务
                'hospital': '090000',    # 医疗保健
                'bank': '160000',        # 金融保险
                'gas_station': '010000', # 汽车服务
                'supermarket': '060000', # 购物服务
                'school': '140000',      # 科教文化
                'hotel': '100000'        # 住宿服务
            }
            
            params = {
                'location': f"{lng},{lat}",
                'keywords': '',
                'types': type_mapping.get(place_type, ''),
                'radius': radius,
                'key': self.api_key,
                'output': 'json'
            }
            
            url = f"{self.BASE_URL}/place/around"
            response = await httpx_client.get(url, params=params, timeout=20)
            response.raise_for_status()
            
            data = response.json()
            results = []
            
            if data['status'] == '1' and data['pois']:
                for poi in data['pois'][:10]:  # 限制前10个结果
                    location = poi['location'].split(',')
                    results.append({
                        'name': poi['name'],
                        'address': poi['address'],
                        'lat': float(location[1]),
                        'lng': float(location[0]),
                        'type': poi.get('type'),
                        'distance': poi.get('distance')
                    })
            
            return results
            
        except Exception as e:
            logger.error(f"高德附近搜索失败: {e}")
            return []
    
    async def get_directions(self, origin: str, destination: str, mode: str = "driving", httpx_client=None) -> Optional[Dict]:
        """高德路线规划"""
        try:
            # 先对起点和终点进行地理编码
            origin_geo = await self.geocode(origin, httpx_client)
            dest_geo = await self.geocode(destination, httpx_client)
            
            if not origin_geo or not dest_geo:
                return None
            
            params = {
                'origin': f"{origin_geo['lng']},{origin_geo['lat']}",
                'destination': f"{dest_geo['lng']},{dest_geo['lat']}",
                'key': self.api_key,
                'output': 'json'
            }
            
            # 根据出行方式选择API
            if mode == "walking":
                url = f"{self.BASE_URL}/direction/walking"
            elif mode == "transit":
                url = f"{self.BASE_URL}/direction/transit/integrated"
            else:  # driving
                url = f"{self.BASE_URL}/direction/driving"
            
            response = await httpx_client.get(url, params=params, timeout=20)
            response.raise_for_status()
            
            data = response.json()
            if data['status'] == '1':
                if mode == "walking" and data['route']['paths']:
                    path = data['route']['paths'][0]
                    return {
                        'distance': f"{float(path['distance'])/1000:.1f}公里",
                        'duration': f"{int(path['duration'])//60}分钟",
                        'start_address': origin,
                        'end_address': destination,
                        'steps': [step['instruction'] for step in path['steps'][:5]]
                    }
                elif mode != "walking" and data['route']['paths']:
                    path = data['route']['paths'][0]
                    return {
                        'distance': f"{float(path['distance'])/1000:.1f}公里",
                        'duration': f"{int(path['duration'])//60}分钟",
                        'start_address': origin,
                        'end_address': destination,
                        'steps': [step['instruction'] for step in path['steps'][:5]]
                    }
            return None
            
        except Exception as e:
            logger.error(f"高德路线规划失败: {e}")
            return None
    
    def get_map_url(self, lat: float, lng: float, zoom: int = 15) -> str:
        """生成高德地图链接"""
        return f"https://uri.amap.com/marker?position={lng},{lat}&zoom={zoom}"
    
    def get_navigation_url(self, destination: str) -> str:
        """生成高德地图导航链接"""
        encoded_dest = urllib.parse.quote(destination)
        return f"https://uri.amap.com/navigation?to={encoded_dest}"


class MapServiceManager:
    """地图服务管理器"""
    
    def __init__(self, google_api_key: Optional[str] = None, amap_api_key: Optional[str] = None):
        self.google_service = GoogleMapsService(google_api_key) if google_api_key else None
        self.amap_service = AmapService(amap_api_key) if amap_api_key else None
    
    def get_service(self, language: str) -> Optional[MapService]:
        """根据语言获取对应的地图服务"""
        service_type = get_map_service(language)
        
        if service_type == 'amap' and self.amap_service:
            return self.amap_service
        elif service_type == 'google_maps' and self.google_service:
            return self.google_service
        
        # 如果首选服务不可用，尝试备用服务
        if language == 'zh' and self.google_service:
            logger.warning("高德地图服务不可用，使用Google Maps作为备用")
            return self.google_service
        elif language == 'en' and self.amap_service:
            logger.warning("Google Maps服务不可用，使用高德地图作为备用")
            return self.amap_service
        
        return None
    
    def is_service_available(self, language: str) -> bool:
        """检查指定语言的地图服务是否可用"""
        return self.get_service(language) is not None