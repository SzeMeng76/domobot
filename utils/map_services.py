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
        """使用 Places API (New) 搜索位置 - 优先使用新版，失败时 fallback 到 Legacy"""
        # 先尝试 Places API (New)
        result = await self._search_location_new(query, httpx_client)
        if result:
            return result

        # 新版失败，fallback 到 Legacy
        logger.info(f"Places API (New) 失败，fallback 到 Legacy: {query}")
        return await self._search_location_legacy(query, httpx_client)

    async def _search_location_new(self, query: str, httpx_client=None) -> Optional[Dict]:
        """使用 Places API (New) 搜索位置"""
        try:
            url = "https://places.googleapis.com/v1/places:searchText"

            request_body = {
                "textQuery": query,
                "languageCode": "en"
            }

            headers = {
                'Content-Type': 'application/json',
                'X-Goog-Api-Key': self.api_key,
                # 请求所有有用的字段
                'X-Goog-FieldMask': 'places.id,places.displayName,places.formattedAddress,places.location,places.rating,places.userRatingCount,places.types,places.priceLevel,places.businessStatus,places.currentOpeningHours,places.photos,places.websiteUri,places.internationalPhoneNumber,places.editorialSummary'
            }

            response = await httpx_client.post(url, json=request_body, headers=headers, timeout=20)
            response.raise_for_status()

            data = response.json()

            if 'places' in data and data['places']:
                place = data['places'][0]

                # 提取基本信息
                display_name = place.get('displayName', {})
                name = display_name.get('text', 'Unknown') if isinstance(display_name, dict) else str(display_name)

                location = place.get('location', {})
                lat = location.get('latitude', 0)
                lng = location.get('longitude', 0)

                # 提取照片
                photos = []
                if 'photos' in place and place['photos']:
                    for photo in place['photos'][:5]:  # 最多5张
                        photo_name = photo.get('name', '')
                        if photo_name:
                            # 构建照片 URL
                            photo_url = f"https://places.googleapis.com/v1/{photo_name}/media?key={self.api_key}&maxHeightPx=400&maxWidthPx=400"
                            photos.append(photo_url)

                # 提取营业状态
                business_status = place.get('businessStatus', 'OPERATIONAL')

                # 提取营业时间
                opening_hours = None
                if 'currentOpeningHours' in place:
                    hours_data = place['currentOpeningHours']
                    opening_hours = {
                        'open_now': hours_data.get('openNow', False),
                        'weekday_text': hours_data.get('weekdayDescriptions', [])
                    }

                # 提取价格等级
                price_level = place.get('priceLevel')
                price_text = None
                if price_level:
                    price_map = {
                        'PRICE_LEVEL_FREE': 'Free',
                        'PRICE_LEVEL_INEXPENSIVE': '$',
                        'PRICE_LEVEL_MODERATE': '$$',
                        'PRICE_LEVEL_EXPENSIVE': '$$$',
                        'PRICE_LEVEL_VERY_EXPENSIVE': '$$$$'
                    }
                    price_text = price_map.get(price_level, price_level)

                # 提取简介
                editorial_summary = None
                if 'editorialSummary' in place:
                    summary_data = place['editorialSummary']
                    if isinstance(summary_data, dict):
                        editorial_summary = summary_data.get('text')

                return {
                    'name': name,
                    'address': place.get('formattedAddress', ''),
                    'lat': lat,
                    'lng': lng,
                    'place_id': place.get('id', ''),
                    'rating': place.get('rating'),
                    'user_ratings_total': place.get('userRatingCount'),
                    'types': place.get('types', []),
                    'price_level': price_text,
                    'business_status': business_status,
                    'opening_hours': opening_hours,
                    'photos': photos,
                    'website': place.get('websiteUri'),
                    'phone': place.get('internationalPhoneNumber'),
                    'editorial_summary': editorial_summary,
                    'api_version': 'places_new'
                }

            return None

        except Exception as e:
            logger.warning(f"Places API (New) 失败: {e}")
            return None

    async def _search_location_legacy(self, query: str, httpx_client=None) -> Optional[Dict]:
        """使用 Places API (Legacy) 搜索位置"""
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
                    'types': place.get('types', []),
                    'api_version': 'places_legacy'
                }
            return None

        except Exception as e:
            logger.error(f"Places API (Legacy) 失败: {e}")
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
        """Google附近搜索 - 优先使用 Places API (New)，失败时 fallback 到 Legacy"""
        # 先尝试 Places API (New)
        result = await self._search_nearby_new(lat, lng, place_type, radius, httpx_client)
        if result:
            return result

        # 新版失败，fallback 到 Legacy
        logger.info(f"Nearby Search (New) 失败，fallback 到 Legacy: {place_type} at {lat},{lng}")
        return await self._search_nearby_legacy(lat, lng, place_type, radius, httpx_client)

    async def _search_nearby_new(self, lat: float, lng: float, place_type: str, radius: int = 1000, httpx_client=None) -> List[Dict]:
        """使用 Places API (New) 附近搜索"""
        try:
            url = "https://places.googleapis.com/v1/places:searchNearby"

            request_body = {
                "includedTypes": [place_type],
                "maxResultCount": 10,
                "locationRestriction": {
                    "circle": {
                        "center": {
                            "latitude": lat,
                            "longitude": lng
                        },
                        "radius": float(radius)
                    }
                },
                "rankPreference": "DISTANCE"  # 按距离排序
            }

            headers = {
                'Content-Type': 'application/json',
                'X-Goog-Api-Key': self.api_key,
                'X-Goog-FieldMask': 'places.id,places.displayName,places.formattedAddress,places.location,places.rating,places.userRatingCount,places.types,places.priceLevel,places.businessStatus,places.currentOpeningHours,places.photos'
            }

            response = await httpx_client.post(url, json=request_body, headers=headers, timeout=20)
            response.raise_for_status()

            data = response.json()
            results = []

            if 'places' in data and data['places']:
                for place in data['places']:
                    display_name = place.get('displayName', {})
                    name = display_name.get('text', 'Unknown') if isinstance(display_name, dict) else str(display_name)

                    location = place.get('location', {})
                    place_lat = location.get('latitude', 0)
                    place_lng = location.get('longitude', 0)

                    # 提取价格等级
                    price_level = place.get('priceLevel')
                    price_text = None
                    if price_level:
                        price_map = {
                            'PRICE_LEVEL_FREE': 'Free',
                            'PRICE_LEVEL_INEXPENSIVE': '$',
                            'PRICE_LEVEL_MODERATE': '$$',
                            'PRICE_LEVEL_EXPENSIVE': '$$$',
                            'PRICE_LEVEL_VERY_EXPENSIVE': '$$$$'
                        }
                        price_text = price_map.get(price_level, price_level)

                    # 提取营业状态
                    business_status = place.get('businessStatus', 'OPERATIONAL')
                    is_open = None
                    if 'currentOpeningHours' in place:
                        is_open = place['currentOpeningHours'].get('openNow', False)

                    # 提取照片
                    photos = []
                    if 'photos' in place and place['photos']:
                        for photo in place['photos'][:1]:  # 只取第一张
                            photo_name = photo.get('name', '')
                            if photo_name:
                                photo_url = f"https://places.googleapis.com/v1/{photo_name}/media?key={self.api_key}&maxHeightPx=200&maxWidthPx=200"
                                photos.append(photo_url)

                    results.append({
                        'name': name,
                        'address': place.get('formattedAddress', ''),
                        'lat': place_lat,
                        'lng': place_lng,
                        'rating': place.get('rating'),
                        'user_ratings_total': place.get('userRatingCount'),
                        'types': place.get('types', []),
                        'price_level': price_text,
                        'business_status': business_status,
                        'is_open': is_open,
                        'photos': photos,
                        'api_version': 'places_new'
                    })

            return results

        except Exception as e:
            logger.warning(f"Nearby Search (New) 失败: {e}")
            return []

    async def _search_nearby_legacy(self, lat: float, lng: float, place_type: str, radius: int = 1000, httpx_client=None) -> List[Dict]:
        """使用 Places API (Legacy) 附近搜索"""
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
                        'price_level': place.get('price_level'),
                        'api_version': 'places_legacy'
                    })

            return results

        except Exception as e:
            logger.error(f"Nearby Search (Legacy) 失败: {e}")
            return []
    
    async def get_directions(self, origin: str, destination: str, mode: str = "driving", httpx_client=None) -> Optional[Dict]:
        """Google路线规划 - 优先使用 Routes API，失败时 fallback 到 Directions API"""
        # 先尝试 Routes API
        result = await self._get_directions_routes_api(origin, destination, mode, httpx_client)
        if result:
            return result

        # Routes API 失败，fallback 到 Directions API
        logger.info(f"Routes API 失败，fallback 到 Directions API: {origin} → {destination}")
        return await self._get_directions_legacy(origin, destination, mode, httpx_client)

    async def _get_directions_routes_api(self, origin: str, destination: str, mode: str = "driving", httpx_client=None) -> Optional[Dict]:
        """使用 Routes API 获取路线（新版）- 支持环保路线、过路费、备选路线、实时交通"""
        try:
            # Routes API 使用 POST 请求
            url = "https://routes.googleapis.com/directions/v2:computeRoutes"

            # 转换 mode 到 Routes API 格式
            travel_mode_map = {
                'driving': 'DRIVE',
                'walking': 'WALK',
                'bicycling': 'BICYCLE',
                'transit': 'TRANSIT',
                'two_wheeler': 'TWO_WHEELER'  # 摩托车/电动车
            }
            travel_mode = travel_mode_map.get(mode, 'DRIVE')

            # 先尝试完整功能（包括环保路线）
            request_body_full = {
                "origin": {
                    "address": origin
                },
                "destination": {
                    "address": destination
                },
                "travelMode": travel_mode,
                "routingPreference": "TRAFFIC_AWARE_OPTIMAL",  # 实时交通优化（环保路线必需）
                "languageCode": "en",
                "units": "METRIC",
                "computeAlternativeRoutes": True,  # 计算备选路线
                "routeModifiers": {
                    "avoidTolls": False,  # 不避开收费路段（需要显示过路费）
                    "avoidHighways": False,
                    "avoidFerries": False
                },
                "extraComputations": [
                    "TOLLS",  # 过路费信息
                    "FUEL_CONSUMPTION",  # 油耗估算
                    "TRAFFIC_ON_POLYLINE"  # 实时交通
                ],
                "requestedReferenceRoutes": ["FUEL_EFFICIENT"],  # 环保路线
                "polylineQuality": "HIGH_QUALITY",  # 高质量路线点
                "polylineEncoding": "ENCODED_POLYLINE"  # 编码格式
            }

            # 如果是驾车模式，添加车辆信息以优化环保路线
            if travel_mode == 'DRIVE':
                request_body_full["routeModifiers"]["vehicleInfo"] = {
                    "emissionType": "GASOLINE"  # 默认汽油车，可以是 DIESEL, ELECTRIC, HYBRID
                }

            headers = {
                'Content-Type': 'application/json',
                'X-Goog-Api-Key': self.api_key,
                # 正确的 FieldMask：fuelConsumptionMicroliters 在 routes.travelAdvisory 下
                'X-Goog-FieldMask': 'routes.duration,routes.distanceMeters,routes.polyline,routes.legs.steps.navigationInstruction,routes.legs.travelAdvisory.tollInfo,routes.travelAdvisory.fuelConsumptionMicroliters,routes.travelAdvisory,routes.routeLabels'
            }

            # 先尝试完整功能
            response = await httpx_client.post(url, json=request_body_full, headers=headers, timeout=30)

            # 如果返回 400 且错误是 FUEL_EFFICIENT 不支持，降级到基础功能
            if response.status_code == 400:
                error_data = response.json()
                error_message = error_data.get('error', {}).get('message', '')

                if 'FUEL_EFFICIENT' in error_message or 'not supported' in error_message:
                    logger.info(f"Routes API: 该地区不支持环保路线功能，降级到基础功能")

                    # 降级请求：移除环保路线相关功能
                    request_body_basic = {
                        "origin": {
                            "address": origin
                        },
                        "destination": {
                            "address": destination
                        },
                        "travelMode": travel_mode,
                        "languageCode": "en",
                        "units": "METRIC",
                        "computeAlternativeRoutes": False,
                        "routeModifiers": {
                            "avoidTolls": False,
                            "avoidHighways": False,
                            "avoidFerries": False
                        },
                        "extraComputations": [
                            "TOLLS",
                            "FUEL_CONSUMPTION"
                        ],
                        "polylineQuality": "HIGH_QUALITY",
                        "polylineEncoding": "ENCODED_POLYLINE"
                    }

                    if travel_mode == 'DRIVE':
                        request_body_basic["routeModifiers"]["vehicleInfo"] = {
                            "emissionType": "GASOLINE"
                        }

                    # 重新请求
                    response = await httpx_client.post(url, json=request_body_basic, headers=headers, timeout=30)

            response.raise_for_status()

            data = response.json()

            if 'routes' in data and data['routes']:
                # 主路线（第一条）
                route = data['routes'][0]

                # 提取距离和时间
                distance_meters = route.get('distanceMeters', 0)
                distance_km = distance_meters / 1000
                distance_text = f"{distance_km:.1f} km" if distance_km >= 1 else f"{distance_meters} m"

                duration_seconds = int(route.get('duration', '0s').rstrip('s'))
                duration_minutes = duration_seconds // 60
                duration_text = f"{duration_minutes} mins" if duration_minutes > 0 else f"{duration_seconds} secs"

                # 提取步骤
                steps = []
                if 'legs' in route and route['legs']:
                    for leg in route['legs']:
                        if 'steps' in leg:
                            for step in leg['steps']:
                                if 'navigationInstruction' in step:
                                    instruction = step['navigationInstruction'].get('instructions', '')
                                    if instruction:
                                        steps.append(instruction)

                # 提取路线标签（是否为环保路线）
                route_labels = route.get('routeLabels', [])
                is_eco_friendly = 'FUEL_EFFICIENT' in route_labels

                # 提取过路费信息和燃油消耗
                toll_info = None
                fuel_consumption = None

                # 过路费在 legs.travelAdvisory.tollInfo
                if 'legs' in route and route['legs']:
                    for leg in route['legs']:
                        if 'travelAdvisory' in leg:
                            advisory = leg['travelAdvisory']

                            # 过路费
                            if 'tollInfo' in advisory and advisory['tollInfo']:
                                toll_info = advisory['tollInfo']
                                # estimatedPrice 是数组，取第一个
                                if 'estimatedPrice' in toll_info and toll_info['estimatedPrice']:
                                    toll_info['estimatedPrice'] = toll_info['estimatedPrice'][0]

                # 燃油消耗在 routes.travelAdvisory.fuelConsumptionMicroliters
                if 'travelAdvisory' in route:
                    route_advisory = route['travelAdvisory']
                    if 'fuelConsumptionMicroliters' in route_advisory:
                        fuel_microliters = int(route_advisory['fuelConsumptionMicroliters'])
                        fuel_liters = fuel_microliters / 1_000_000
                        fuel_consumption = fuel_liters  # 返回数字，不是字符串

                # 提取实时交通信息
                traffic_info = None
                if 'travelAdvisory' in route:
                    traffic_info = route['travelAdvisory']

                # 提取备选路线
                alternative_routes = []
                if len(data['routes']) > 1:
                    for alt_route in data['routes'][1:]:
                        alt_distance_meters = alt_route.get('distanceMeters', 0)
                        alt_distance_km = alt_distance_meters / 1000
                        alt_distance_text = f"{alt_distance_km:.1f} km" if alt_distance_km >= 1 else f"{alt_distance_meters} m"

                        alt_duration_seconds = int(alt_route.get('duration', '0s').rstrip('s'))
                        alt_duration_minutes = alt_duration_seconds // 60
                        alt_duration_text = f"{alt_duration_minutes} mins" if alt_duration_minutes > 0 else f"{alt_duration_seconds} secs"

                        alt_labels = alt_route.get('routeLabels', [])

                        alternative_routes.append({
                            'distance': alt_distance_text,
                            'duration': alt_duration_text,
                            'is_eco_friendly': 'FUEL_EFFICIENT' in alt_labels
                        })

                result = {
                    'distance': distance_text,
                    'duration': duration_text,
                    'start_address': origin,
                    'end_address': destination,
                    'steps': steps,
                    'api_version': 'routes_v2',
                    'is_eco_friendly': is_eco_friendly,
                    'toll_info': toll_info,
                    'fuel_consumption': fuel_consumption,
                    'traffic_info': traffic_info,
                    'alternative_routes': alternative_routes
                }

                return result
            else:
                logger.warning(f"Routes API 无结果: {origin} → {destination}")
                return None

        except Exception as e:
            logger.warning(f"Routes API 失败: {e}")
            return None

    async def _get_directions_legacy(self, origin: str, destination: str, mode: str = "driving", httpx_client=None) -> Optional[Dict]:
        """使用 Directions API 获取路线（Legacy fallback）"""
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
                    'steps': [step['html_instructions'] for step in leg['steps']],
                    'api_version': 'directions_v1'
                }
            else:
                # 处理不同的错误状态
                status = data.get('status', 'UNKNOWN_ERROR')
                if status == 'NOT_FOUND':
                    logger.warning(f"Directions API: 无法找到起点或终点 - {origin} → {destination}")
                elif status == 'ZERO_RESULTS':
                    logger.warning(f"Directions API: 无可用路线 - {origin} → {destination}")
                else:
                    logger.warning(f"Directions API 失败: {status} - {origin} → {destination}")
                return None

        except Exception as e:
            logger.error(f"Directions API 失败: {e}")
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
                        'steps': [step['instruction'] for step in path['steps']]  # 返回所有步骤
                    }
                elif mode != "walking" and data['route']['paths']:
                    path = data['route']['paths'][0]
                    return {
                        'distance': f"{float(path['distance'])/1000:.1f}公里",
                        'duration': f"{int(path['duration'])//60}分钟",
                        'start_address': origin,
                        'end_address': destination,
                        'steps': [step['instruction'] for step in path['steps']]  # 返回所有步骤
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