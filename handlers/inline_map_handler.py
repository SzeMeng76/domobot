#!/usr/bin/env python3
"""
Inline Map Handler
处理地图相关的 inline query
"""

import logging
from telegram import InlineQueryResultArticle, InlineQueryResultPhoto, InputTextMessageContent, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from uuid import uuid4

from utils.language_detector import detect_user_language
from utils.map_services import MapServiceManager
from utils.config_manager import get_config

logger = logging.getLogger(__name__)

# 价格等级映射
PRICE_LEVEL_MAP = {
    '$': '💵 便宜',
    '$$': '💵💵 中等',
    '$$$': '💵💵💵 较贵',
    '$$$$': '💵💵💵💵 很贵'
}

# 全局变量
httpx_client = None
map_service_manager = None


def set_dependencies(hc):
    """设置依赖项"""
    global httpx_client, map_service_manager
    httpx_client = hc

    # 初始化地图服务管理器
    config = get_config()
    map_service_manager = MapServiceManager(
        google_api_key=config.google_maps_api_key,
        amap_api_key=config.amap_api_key
    )


async def handle_inline_map_search(query: str, context: ContextTypes.DEFAULT_TYPE, user_locale: str = None) -> list:
    """
    处理地图搜索 inline query

    Args:
        query: 搜索关键词
        context: Telegram context
        user_locale: 用户语言代码

    Returns:
        list: InlineQueryResult 列表
    """
    if not query or not query.strip():
        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="🗺️ 地图服务",
                description="搜索地点、附近服务、路线规划",
                input_message_content=InputTextMessageContent(
                    message_text="💡 **地图服务使用方法**:\n\n"
                                 "🔍 **搜索地点**:\n"
                                 "`@botname map 地点名称$`\n"
                                 "例如: `map 埃菲尔铁塔$`\n\n"
                                 "🔍 **附近搜索**:\n"
                                 "`@botname map nearby 类型 地点$`\n"
                                 "例如: `map nearby restaurant 埃菲尔铁塔$`\n\n"
                                 "🚗 **路线规划**:\n"
                                 "`@botname map 起点 to 终点$`\n"
                                 "`@botname map 起点 到 终点$`\n"
                                 "例如: `map 北京站 到 天安门$`",
                    parse_mode="Markdown"
                ),
            )
        ]

    try:
        # 检测语言
        language = detect_user_language(query, user_locale)

        # 获取地图服务
        service = map_service_manager.get_service(language)
        if not service:
            return [
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title="❌ 地图服务不可用",
                    description="请稍后重试",
                    input_message_content=InputTextMessageContent(
                        message_text="❌ 地图服务暂时不可用"
                    ),
                )
            ]

        service_type = "amap" if language == "zh" else "google_maps"
        service_name = "高德地图" if language == "zh" else "Google Maps"

        # 搜索位置
        location_data = await service.search_location(query, httpx_client)

        if not location_data:
            return [
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title=f"❌ 未找到: {query}",
                    description=f"在 {service_name} 中未找到该地点",
                    input_message_content=InputTextMessageContent(
                        message_text=f"❌ 未找到地点: {query}\n\n数据来源: {service_name}"
                    ),
                )
            ]

        # 构建结果文本
        name = location_data.get('name', 'Unknown')
        address = location_data.get('address', '')
        lat = location_data.get('lat')
        lng = location_data.get('lng')

        result_text = f"📍 **{name}**\n\n"
        result_text += f"📮 地址: {address}\n"
        result_text += f"🌐 坐标: `{lat:.6f}, {lng:.6f}`\n"

        # 评分
        if location_data.get('rating'):
            rating = location_data['rating']
            stars = "⭐" * int(rating)
            result_text += f"⭐ 评分: {stars} `{rating}`"
            if location_data.get('user_ratings_total'):
                result_text += f" ({location_data['user_ratings_total']} 条评价)"
            result_text += "\n"

        # 价格等级
        if location_data.get('price_level'):
            price_text = PRICE_LEVEL_MAP.get(location_data['price_level'], location_data['price_level'])
            result_text += f"💰 价格: {price_text}\n"

        # 营业状态
        if location_data.get('business_status'):
            status = location_data['business_status']
            if status == 'OPERATIONAL':
                status_text = "✅ 营业中"
            elif status == 'CLOSED_TEMPORARILY':
                status_text = "⏸️ 暂停营业"
            elif status == 'CLOSED_PERMANENTLY':
                status_text = "❌ 已关闭"
            else:
                status_text = status
            result_text += f"🏪 状态: {status_text}\n"

        # 营业时间
        if location_data.get('opening_hours'):
            hours = location_data['opening_hours']
            if 'open_now' in hours:
                open_status = "🟢 营业中" if hours['open_now'] else "🔴 已打烊"
                result_text += f"🕐 营业: {open_status}\n"

        # 电话
        if location_data.get('phone'):
            result_text += f"📞 电话: {location_data['phone']}\n"

        # 网站
        if location_data.get('website'):
            result_text += f"🌐 网站: {location_data['website']}\n"

        # 简介
        if location_data.get('editorial_summary'):
            summary = location_data['editorial_summary']
            if len(summary) > 100:
                summary = summary[:100] + "..."
            result_text += f"\n📝 简介: _{summary}_\n"

        # 地图链接
        map_url = service.get_map_url(lat, lng)
        result_text += f"\n🗺️ [查看地图]({map_url})"

        result_text += f"\n\n_数据来源: {service_name}_"

        # 创建按钮
        keyboard = [
            [
                InlineKeyboardButton("🗺️ 查看地图", url=map_url),
                InlineKeyboardButton("🔍 附近搜索", switch_inline_query_current_chat=f"map nearby restaurant {name}$")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # 如果有照片，返回照片结果
        if location_data.get('photos') and len(location_data['photos']) > 0:
            photo_url = location_data['photos'][0]

            return [
                InlineQueryResultPhoto(
                    id=str(uuid4()),
                    photo_url=photo_url,
                    thumbnail_url=photo_url,
                    title=f"📍 {name}",
                    description=f"{address}\n⭐ {location_data.get('rating', 'N/A')} | {service_name}",
                    caption=result_text,
                    parse_mode="Markdown",
                    reply_markup=reply_markup
                )
            ]
        else:
            # 没有照片，返回文本结果
            return [
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title=f"📍 {name}",
                    description=f"{address}\n⭐ {location_data.get('rating', 'N/A')} | {service_name}",
                    input_message_content=InputTextMessageContent(
                        message_text=result_text,
                        parse_mode="Markdown"
                    ),
                    reply_markup=reply_markup
                )
            ]

    except Exception as e:
        logger.error(f"Inline map search 失败: {e}", exc_info=True)
        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="❌ 搜索失败",
                description=str(e)[:100],
                input_message_content=InputTextMessageContent(
                    message_text=f"❌ 地图搜索失败\n\n错误: {str(e)}"
                ),
            )
        ]


async def handle_inline_map_nearby(query: str, context: ContextTypes.DEFAULT_TYPE, user_locale: str = None) -> list:
    """
    处理附近搜索 inline query

    Args:
        query: 搜索关键词，格式: "type location" 或 "location"
        context: Telegram context
        user_locale: 用户语言代码

    Returns:
        list: InlineQueryResult 列表
    """
    if not query or not query.strip():
        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="🔍 附近搜索",
                description="请输入: 类型 地点，例如: nearby restaurant 埃菲尔铁塔$",
                input_message_content=InputTextMessageContent(
                    message_text="💡 使用方法:\n\n`@botname map nearby 类型 地点$`\n\n例如:\n• `map nearby restaurant 埃菲尔铁塔$`\n• `map nearby 餐厅 天安门$`\n• `map nearby cafe Times Square$`",
                    parse_mode="Markdown"
                ),
            )
        ]

    try:
        # 解析查询: "type location" 或 "location"
        parts = query.strip().split(maxsplit=1)
        if len(parts) == 1:
            # 只有地点，没有类型
            location_query = parts[0]
            place_type = ""
        else:
            # 有类型和地点
            place_type = parts[0]
            location_query = parts[1]

        # 检测语言
        language = detect_user_language(location_query, user_locale)

        # 获取地图服务
        service = map_service_manager.get_service(language)
        if not service:
            return [
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title="❌ 地图服务不可用",
                    description="请稍后重试",
                    input_message_content=InputTextMessageContent(
                        message_text="❌ 地图服务暂时不可用"
                    ),
                )
            ]

        service_name = "高德地图" if language == "zh" else "Google Maps"

        # 先搜索位置
        location_data = await service.search_location(location_query, httpx_client)
        if not location_data:
            return [
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title=f"❌ 未找到: {location_query}",
                    description=f"在 {service_name} 中未找到该地点",
                    input_message_content=InputTextMessageContent(
                        message_text=f"❌ 未找到地点: {location_query}\n\n数据来源: {service_name}"
                    ),
                )
            ]

        lat = location_data.get('lat')
        lng = location_data.get('lng')

        # 搜索附近地点
        nearby_places = await service.search_nearby(lat, lng, place_type, 1000, httpx_client)

        if not nearby_places:
            return [
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title=f"❌ 未找到附近的{place_type or '地点'}",
                    description=f"在 {location_data.get('name')} 附近未找到结果",
                    input_message_content=InputTextMessageContent(
                        message_text=f"❌ 在 {location_data.get('name')} 附近未找到{place_type or '地点'}\n\n数据来源: {service_name}"
                    ),
                )
            ]

        # 构建结果列表
        results = []
        for place in nearby_places[:10]:  # 最多返回10个结果
            name = place.get('name', 'Unknown')
            address = place.get('address', '')
            place_lat = place.get('lat')
            place_lng = place.get('lng')

            result_text = f"📍 **{name}**\n\n"
            result_text += f"📮 地址: {address}\n"
            result_text += f"🌐 坐标: `{place_lat:.6f}, {place_lng:.6f}`\n"

            # 评分
            if place.get('rating'):
                rating = place['rating']
                stars = "⭐" * int(rating)
                result_text += f"⭐ 评分: {stars} `{rating}`"
                if place.get('user_ratings_total'):
                    result_text += f" ({place['user_ratings_total']} 条评价)"
                result_text += "\n"

            # 价格等级
            if place.get('price_level'):
                price_text = PRICE_LEVEL_MAP.get(place['price_level'], place['price_level'])
                result_text += f"💰 价格: {price_text}\n"

            # 营业状态
            if place.get('is_open') is not None:
                open_status = "🟢 营业中" if place['is_open'] else "🔴 已打烊"
                result_text += f"🕐 营业: {open_status}\n"

            # 地图链接
            map_url = service.get_map_url(place_lat, place_lng)
            result_text += f"\n🗺️ [查看地图]({map_url})"

            result_text += f"\n\n_数据来源: {service_name}_"

            # 创建按钮
            keyboard = [[InlineKeyboardButton("🗺️ 查看地图", url=map_url)]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            # 描述文本
            desc_parts = []
            if address:
                desc_parts.append(address[:50])
            if place.get('rating'):
                desc_parts.append(f"⭐ {place['rating']}")
            description = " | ".join(desc_parts) if desc_parts else "查看详情"

            # 如果有照片，返回照片结果
            if place.get('photos') and len(place['photos']) > 0:
                photo_url = place['photos'][0]
                results.append(
                    InlineQueryResultPhoto(
                        id=str(uuid4()),
                        photo_url=photo_url,
                        thumbnail_url=photo_url,
                        title=f"📍 {name}",
                        description=description,
                        caption=result_text,
                        parse_mode="Markdown",
                        reply_markup=reply_markup
                    )
                )
            else:
                # 没有照片，返回文本结果
                results.append(
                    InlineQueryResultArticle(
                        id=str(uuid4()),
                        title=f"📍 {name}",
                        description=description,
                        input_message_content=InputTextMessageContent(
                            message_text=result_text,
                            parse_mode="Markdown"
                        ),
                        reply_markup=reply_markup
                    )
                )

        return results

    except Exception as e:
        logger.error(f"Inline nearby search 失败: {e}", exc_info=True)
        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="❌ 搜索失败",
                description=str(e)[:100],
                input_message_content=InputTextMessageContent(
                    message_text=f"❌ 附近搜索失败\n\n错误: {str(e)}"
                ),
            )
        ]


async def handle_inline_map_directions(query: str, context: ContextTypes.DEFAULT_TYPE, user_locale: str = None) -> list:
    """
    处理路线规划 inline query

    Args:
        query: 搜索关键词，格式: "origin to destination"
        context: Telegram context
        user_locale: 用户语言代码

    Returns:
        list: InlineQueryResult 列表
    """
    if not query or not query.strip():
        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="🚗 路线规划",
                description="请输入: 起点 to 终点，例如: route 北京站 to 天安门$",
                input_message_content=InputTextMessageContent(
                    message_text="💡 使用方法:\n\n`@botname map route 起点 to 终点$`\n\n例如:\n• `map route 北京站 to 天安门$`\n• `map route LA to SF$`\n• `map directions Eiffel Tower to Louvre$`",
                    parse_mode="Markdown"
                ),
            )
        ]

    try:
        # 解析查询: "origin to destination" 或 "origin 到 destination"
        if ' to ' in query.lower():
            parts = query.lower().split(' to ', 1)
            origin_query = query[:len(parts[0])].strip()
            destination_query = query[len(parts[0])+4:].strip()
        elif ' 到 ' in query:
            parts = query.split(' 到 ', 1)
            origin_query = parts[0].strip()
            destination_query = parts[1].strip()
        else:
            return [
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title="❌ 格式错误",
                    description="请使用格式: 起点 to 终点 或 起点 到 终点",
                    input_message_content=InputTextMessageContent(
                        message_text="❌ 格式错误\n\n请使用格式: `起点 to 终点` 或 `起点 到 终点`\n\n例如:\n• `北京站 到 天安门`\n• `LA to SF`"
                    ),
                )
            ]

        # 检测语言
        language = detect_user_language(origin_query + " " + destination_query, user_locale)

        # 获取地图服务
        service = map_service_manager.get_service(language)
        if not service:
            return [
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title="❌ 地图服务不可用",
                    description="请稍后重试",
                    input_message_content=InputTextMessageContent(
                        message_text="❌ 地图服务暂时不可用"
                    ),
                )
            ]

        service_name = "高德地图" if language == "zh" else "Google Maps"

        # 搜索起点
        origin_data = await service.search_location(origin_query, httpx_client)
        if not origin_data:
            return [
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title=f"❌ 未找到起点: {origin_query}",
                    description=f"在 {service_name} 中未找到该地点",
                    input_message_content=InputTextMessageContent(
                        message_text=f"❌ 未找到起点: {origin_query}\n\n数据来源: {service_name}"
                    ),
                )
            ]

        # 搜索终点
        destination_data = await service.search_location(destination_query, httpx_client)
        if not destination_data:
            return [
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title=f"❌ 未找到终点: {destination_query}",
                    description=f"在 {service_name} 中未找到该地点",
                    input_message_content=InputTextMessageContent(
                        message_text=f"❌ 未找到终点: {destination_query}\n\n数据来源: {service_name}"
                    ),
                )
            ]

        # 获取路线
        origin_lat = origin_data.get('lat')
        origin_lng = origin_data.get('lng')
        dest_lat = destination_data.get('lat')
        dest_lng = destination_data.get('lng')

        directions = await service.get_directions(origin_lat, origin_lng, dest_lat, dest_lng, httpx_client)

        if not directions:
            return [
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title="❌ 未找到路线",
                    description=f"从 {origin_data.get('name')} 到 {destination_data.get('name')}",
                    input_message_content=InputTextMessageContent(
                        message_text=f"❌ 未找到路线\n\n从: {origin_data.get('name')}\n到: {destination_data.get('name')}\n\n数据来源: {service_name}"
                    ),
                )
            ]

        # 构建结果文本
        result_text = f"🚗 **路线规划**\n\n"
        result_text += f"📍 起点: {origin_data.get('name')}\n"
        result_text += f"📍 终点: {destination_data.get('name')}\n\n"

        # 距离和时间
        distance_km = directions.get('distance', 0) / 1000
        duration_min = directions.get('duration', 0) / 60
        result_text += f"📏 距离: {distance_km:.1f} km\n"
        result_text += f"⏱️ 时间: {int(duration_min)} 分钟\n"

        # 生态友好标识
        if directions.get('is_eco_friendly'):
            result_text += f"🌱 生态友好路线\n"

        # 燃油消耗
        if directions.get('fuel_consumption_liters'):
            fuel = directions['fuel_consumption_liters']
            result_text += f"⛽ 燃油: {fuel:.2f} L\n"

        # 过路费
        if directions.get('tolls'):
            tolls = directions['tolls']
            if tolls.get('estimatedPrice'):
                price = tolls['estimatedPrice']
                currency = price.get('currencyCode', 'USD')
                amount = price.get('units', 0)
                nanos = price.get('nanos', 0)
                total = amount + nanos / 1_000_000_000
                result_text += f"💰 过路费: {total:.2f} {currency}\n"

        # 地图链接 - 构建路线规划 URL
        if language == "zh":
            # 高德地图路线规划
            map_url = f"https://uri.amap.com/navigation?from={origin_lng},{origin_lat}&to={dest_lng},{dest_lat}"
        else:
            # Google Maps 路线规划
            map_url = f"https://maps.google.com/maps?saddr={origin_lat},{origin_lng}&daddr={dest_lat},{dest_lng}"

        result_text += f"\n🗺️ [查看地图]({map_url})"

        result_text += f"\n\n_数据来源: {service_name}_"

        # 创建按钮
        keyboard = [[InlineKeyboardButton("🗺️ 查看路线", url=map_url)]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # 描述文本
        description = f"{distance_km:.1f}km | {int(duration_min)}分钟"
        if directions.get('is_eco_friendly'):
            description += " | 🌱"

        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title=f"🚗 {origin_data.get('name')} → {destination_data.get('name')}",
                description=description,
                input_message_content=InputTextMessageContent(
                    message_text=result_text,
                    parse_mode="Markdown"
                ),
                reply_markup=reply_markup
            )
        ]

    except Exception as e:
        logger.error(f"Inline directions 失败: {e}", exc_info=True)
        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="❌ 路线规划失败",
                description=str(e)[:100],
                input_message_content=InputTextMessageContent(
                    message_text=f"❌ 路线规划失败\n\n错误: {str(e)}"
                ),
            )
        ]
