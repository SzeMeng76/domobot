#!/usr/bin/env python3
"""
Inline Map Handler
处理地图相关的 inline query
"""

import logging
import json
import re
import time
from datetime import datetime
from typing import Optional, Dict
from telegram import InlineQueryResultArticle, InlineQueryResultPhoto, InputTextMessageContent, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from uuid import uuid4

from utils.language_detector import detect_user_language
from utils.map_services import MapServiceManager
from utils.config_manager import get_config

logger = logging.getLogger(__name__)

# Telegraph 相关配置
TELEGRAPH_API_URL = "https://api.telegra.ph"

# 全局缓存：存储地图图片信息（5分钟TTL）
_map_photo_cache: Dict[str, Dict] = {}
_cache_timestamps: Dict[str, float] = {}
CACHE_TTL = 300  # 5分钟

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


async def create_telegraph_page(title: str, content: str) -> Optional[str]:
    """创建Telegraph页面用于显示长内容"""
    try:
        # 创建Telegraph账户
        account_data = {
            "short_name": "MapBot",
            "author_name": "MengBot Map Service",
            "author_url": "https://t.me/mengpricebot"
        }

        response = await httpx_client.post(f"{TELEGRAPH_API_URL}/createAccount", data=account_data)
        if response.status_code != 200:
            logger.warning(f"创建Telegraph账户失败: {response.status_code}")
            return None

        account_info = response.json()
        if not account_info.get("ok"):
            logger.warning(f"Telegraph账户创建响应错误: {account_info}")
            return None

        access_token = account_info["result"]["access_token"]

        # 创建页面内容
        page_content = [
            {
                "tag": "p",
                "children": [content]
            }
        ]

        page_data = {
            "access_token": access_token,
            "title": title,
            "content": json.dumps(page_content),
            "return_content": "true"
        }

        response = await httpx_client.post(f"{TELEGRAPH_API_URL}/createPage", data=page_data)
        if response.status_code != 200:
            logger.warning(f"创建Telegraph页面失败: {response.status_code}")
            return None

        page_info = response.json()
        if not page_info.get("ok"):
            logger.warning(f"Telegraph页面创建响应错误: {page_info}")
            return None

        logger.info(f"成功创建Telegraph页面: {page_info['result']['url']}")
        return page_info["result"]["url"]
    except Exception as e:
        logger.error(f"创建Telegraph页面失败: {e}")
        return None


def format_directions_for_telegraph(directions: Dict, service_type: str) -> str:
    """将路线规划格式化为Telegraph友好的格式"""
    distance = directions.get('distance', '未知')
    duration = directions.get('duration', '未知')
    start = directions.get('start_address', '')
    end = directions.get('end_address', '')

    content = f"""路线规划详情

📍 起点: {start}
📍 终点: {end}

📊 路线信息:"""

    # 检查主路线是否有toll
    main_has_tolls = False
    if 'steps' in directions and directions['steps']:
        main_has_tolls = any('Toll road' in step for step in directions['steps'])

    toll_status = " 💰 有收费" if main_has_tolls else " 🆓 无收费"
    content += f"\n• 距离: {distance}{toll_status}"
    content += f"\n• 预计时间: {duration}\n"

    # Routes API v2 新功能
    api_version = directions.get('api_version', 'directions_v1')

    if api_version == 'routes_v2':
        # 环保路线标识
        if directions.get('is_eco_friendly'):
            content += "• 🌱 环保路线: 已优化油耗\n"

        # 燃油消耗
        if directions.get('fuel_consumption_liters'):
            fuel = directions['fuel_consumption_liters']
            content += f"• ⛽ 预计油耗: {fuel:.2f} L\n"

        # 过路费信息
        if directions.get('tolls'):
            tolls = directions['tolls']
            if tolls.get('estimatedPrice'):
                price = tolls['estimatedPrice']
                currency = price.get('currencyCode', 'USD')
                amount = price.get('units', 0)
                nanos = price.get('nanos', 0)
                total = amount + nanos / 1_000_000_000
                content += f"• 💰 过路费: {total:.2f} {currency}\n"

        content += f"\n_使用 Routes API v2_\n"

    content += "\n🛣️ 主路线详细指引:\n"

    # 添加主路线所有步骤
    if 'steps' in directions and directions['steps']:
        for i, step in enumerate(directions['steps'], 1):
            # 清理HTML标签
            step_clean = re.sub(r'<[^>]+>', ' ', step)
            step_clean = re.sub(r'\s+', ' ', step_clean)
            step_clean = step_clean.strip()

            # 如果包含 "Toll road"，添加收费标记
            if 'Toll road' in step_clean:
                step_clean = step_clean.replace('Toll road', '💰 收费路段')

            content += f"{i}. {step_clean}\n\n"
    else:
        content += "暂无详细指引信息\n\n"

    # 添加备选路线
    if directions.get('alternative_routes'):
        alt_routes = directions['alternative_routes']
        for route_num, alt in enumerate(alt_routes, 2):
            toll_tag = " 💰 有收费" if alt.get('has_tolls') else " 🆓 无收费"
            eco_tag = " 🌱 环保" if alt.get('is_eco_friendly') else ""

            content += f"\n{'='*60}\n"
            content += f"🔀 备选路线 {route_num}: {alt['distance']} · {alt['duration']}{toll_tag}{eco_tag}\n"

            if alt.get('description'):
                content += f"经由: {alt['description']}\n"

            if alt.get('toll_info') and alt['toll_info'].get('estimatedPrice'):
                toll_price = alt['toll_info']['estimatedPrice']
                currency = toll_price.get('currencyCode', 'USD')
                amount = toll_price.get('units', 0)
                nanos = toll_price.get('nanos', 0)
                total = amount + nanos / 1_000_000_000
                content += f"过路费: {total:.2f} {currency}\n"

            content += f"\n详细指引:\n"

            # 添加备选路线的步骤
            if alt.get('steps'):
                for i, step in enumerate(alt['steps'], 1):
                    # 清理HTML标签
                    step_clean = re.sub(r'<[^>]+>', ' ', step)
                    step_clean = re.sub(r'\s+', ' ', step_clean)
                    step_clean = step_clean.strip()

                    # 如果包含 "Toll road"，添加收费标记
                    if 'Toll road' in step_clean:
                        step_clean = step_clean.replace('Toll road', '💰 收费路段')

                    content += f"{i}. {step_clean}\n\n"
            else:
                content += "暂无详细指引信息\n\n"

    service_name = "Google Maps" if service_type == "google_maps" else "高德地图"
    content += f"""
---
数据来源: {service_name}
生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
来源: MengBot 地图服务"""

    return content


async def handle_chosen_map_result(update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理用户选择 inline 地图结果后的图片下载和上传

    Args:
        update: Telegram Update
        context: Context
    """
    chosen_result = update.chosen_inline_result
    inline_message_id = chosen_result.inline_message_id
    result_id = chosen_result.result_id

    logger.info(f"[Inline Map Chosen] result_id={result_id}, inline_message_id={inline_message_id}")

    # 从缓存中获取照片信息
    cached_data = _map_photo_cache.get(result_id, None)

    if not cached_data:
        # 没有缓存的照片，跳过
        logger.info(f"[Inline Map Chosen] 无缓存照片: {result_id}")
        return

    logger.info(f"[Inline Map Chosen] 找到缓存照片，开始下载上传")

    photo_url = cached_data["photo_url"]
    caption = cached_data["caption"]
    reply_markup = cached_data["reply_markup"]

    try:
        import tempfile
        from pathlib import Path

        # 更新状态
        await context.bot.edit_message_text(
            inline_message_id=inline_message_id,
            text="📥 下载图片中..."
        )

        # 下载图片
        temp_dir = Path(tempfile.gettempdir()) / "domobot_map"
        temp_dir.mkdir(exist_ok=True)

        async with httpx_client.stream('GET', photo_url) as response:
            response.raise_for_status()

            # 保存到临时文件
            temp_file = temp_dir / f"map_{result_id}.jpg"
            with open(temp_file, 'wb') as f:
                async for chunk in response.aiter_bytes():
                    f.write(chunk)

        photo_size_mb = temp_file.stat().st_size / (1024 * 1024)
        logger.info(f"[Inline Map] 图片下载完成: {photo_size_mb:.1f}MB")

        # 检查文件大小
        if photo_size_mb > 10:
            # 图片过大
            await context.bot.edit_message_text(
                inline_message_id=inline_message_id,
                text=f"{caption}\n\n⚠️ 图片过大 ({photo_size_mb:.1f}MB)，无法上传",
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
            _map_photo_cache.pop(result_id, None)
            _cache_timestamps.pop(result_id, None)
            temp_file.unlink(missing_ok=True)
            return

        # 更新状态
        await context.bot.edit_message_text(
            inline_message_id=inline_message_id,
            text=f"📤 上传图片中... ({photo_size_mb:.1f}MB)"
        )

        # 优先使用 Pyrogram 直接上传（支持大文件，无需临时频道）
        from commands.social_parser import _adapter as parse_adapter_instance
        pyrogram_helper = getattr(parse_adapter_instance, 'pyrogram_helper', None)

        if pyrogram_helper and pyrogram_helper.is_started and pyrogram_helper.client:
            from pyrogram.types import InputMediaPhoto as PyrogramInputMediaPhoto, InlineKeyboardMarkup as PyrogramInlineKeyboardMarkup, InlineKeyboardButton as PyrogramInlineKeyboardButton
            from pyrogram.enums import ParseMode as PyrogramParseMode

            # 转换 python-telegram-bot 的 InlineKeyboardMarkup 到 Pyrogram 格式
            pyrogram_reply_markup = None
            if reply_markup:
                pyrogram_buttons = []
                for row in reply_markup.inline_keyboard:
                    pyrogram_row = []
                    for button in row:
                        if button.url:
                            pyrogram_row.append(PyrogramInlineKeyboardButton(text=button.text, url=button.url))
                        elif button.callback_data:
                            pyrogram_row.append(PyrogramInlineKeyboardButton(text=button.text, callback_data=button.callback_data))
                    if pyrogram_row:
                        pyrogram_buttons.append(pyrogram_row)
                if pyrogram_buttons:
                    pyrogram_reply_markup = PyrogramInlineKeyboardMarkup(pyrogram_buttons)

            await pyrogram_helper.client.edit_inline_media(
                inline_message_id=inline_message_id,
                media=PyrogramInputMediaPhoto(
                    media=str(temp_file),
                    caption=caption,
                    parse_mode=PyrogramParseMode.MARKDOWN
                ),
                reply_markup=pyrogram_reply_markup
            )
            logger.info(f"[Inline Map] Pyrogram 图片上传成功: {photo_size_mb:.1f}MB")
        else:
            # Pyrogram 不可用，fallback 到临时频道方案
            from telegram import InputMediaPhoto
            from utils.config_manager import ConfigManager

            config_manager = ConfigManager()
            temp_channel_id = config_manager.config.inline_parse_temp_channel

            if not temp_channel_id:
                await context.bot.edit_message_text(
                    inline_message_id=inline_message_id,
                    text=f"{caption}\n\n❌ 配置错误：未设置临时存储频道且 Pyrogram 不可用",
                    parse_mode="Markdown",
                    reply_markup=reply_markup
                )
                temp_file.unlink(missing_ok=True)
                return

            # 先上传到临时频道获取 file_id
            with open(temp_file, 'rb') as photo_file:
                sent_message = await context.bot.send_photo(
                    chat_id=temp_channel_id,
                    photo=photo_file,
                    read_timeout=300,
                    write_timeout=300,
                    connect_timeout=30
                )
                file_id = sent_message.photo[-1].file_id

            # 使用 file_id 编辑 inline 消息
            input_media = InputMediaPhoto(
                media=file_id,
                caption=caption,
                parse_mode="Markdown"
            )

            await context.bot.edit_message_media(
                inline_message_id=inline_message_id,
                media=input_media,
                reply_markup=reply_markup
            )
            logger.info(f"[Inline Map] 临时频道图片上传成功: {photo_size_mb:.1f}MB")

        # 清理
        temp_file.unlink(missing_ok=True)
        _map_photo_cache.pop(result_id, None)
        _cache_timestamps.pop(result_id, None)

    except Exception as e:
        logger.error(f"[Inline Map] 图片处理失败: {e}", exc_info=True)
        try:
            await context.bot.edit_message_text(
                inline_message_id=inline_message_id,
                text=f"{caption}\n\n❌ 图片加载失败",
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
        except Exception:
            pass

        # 清理
        _map_photo_cache.pop(result_id, None)
        _cache_timestamps.pop(result_id, None)


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

        # 创建按钮 - 添加附近搜索category按钮
        keyboard = [
            [InlineKeyboardButton("🗺️ 查看地图", url=map_url)],
            [
                InlineKeyboardButton("🍽️ 餐厅", callback_data=f"map_nearby_restaurant_{lat}_{lng}"),
                InlineKeyboardButton("🏥 医院", callback_data=f"map_nearby_hospital_{lat}_{lng}"),
                InlineKeyboardButton("🏦 银行", callback_data=f"map_nearby_bank_{lat}_{lng}")
            ],
            [
                InlineKeyboardButton("⛽ 加油站", callback_data=f"map_nearby_gas_station_{lat}_{lng}"),
                InlineKeyboardButton("🏪 超市", callback_data=f"map_nearby_supermarket_{lat}_{lng}"),
                InlineKeyboardButton("🏨 酒店", callback_data=f"map_nearby_hotel_{lat}_{lng}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # 如果有照片，缓存照片信息用于 chosen handler
        result_id = str(uuid4())
        if location_data.get('photos') and len(location_data['photos']) > 0:
            photo_url = location_data['photos'][0]
            _map_photo_cache[result_id] = {
                "photo_url": photo_url,
                "caption": result_text,
                "reply_markup": reply_markup
            }
            _cache_timestamps[result_id] = time.time()
            logger.info(f"[Inline Map] 缓存照片信息: {result_id}")

        # 使用 Article 类型而不是 Photo，避免 thumbnail 访问问题
        # Google Places API 的照片 URL 可能有访问限制
        return [
            InlineQueryResultArticle(
                id=result_id,
                title=f"📍 {name}",
                description=f"{address[:80]}\n⭐ {location_data.get('rating', 'N/A')} | {service_name}",
                thumbnail_url="https://img.icons8.com/color/96/000000/marker.png",
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

        # 如果结果较多，添加一个"查看全部"选项（Telegraph汇总）
        if len(nearby_places) > 5:
            try:
                # 构建Telegraph内容
                type_names = {
                    'restaurant': '餐厅',
                    'hospital': '医院',
                    'bank': '银行',
                    'gas_station': '加油站',
                    'supermarket': '超市',
                    'school': '学校',
                    'hotel': '酒店'
                }
                type_name = type_names.get(place_type, place_type or '地点')

                telegraph_content = f"📍 附近的{type_name}\n\n"
                telegraph_content += f"位置: {location_data.get('name')}\n\n"
                telegraph_content += "="*60 + "\n\n"

                for i, place in enumerate(nearby_places[:20], 1):  # Telegraph显示前20个
                    telegraph_content += f"{i}. {place.get('name', 'Unknown')}\n"
                    if place.get('address'):
                        telegraph_content += f"   地址: {place['address']}\n"
                    if place.get('rating'):
                        telegraph_content += f"   评分: {'⭐' * int(place['rating'])} {place['rating']}"
                        if place.get('user_ratings_total'):
                            telegraph_content += f" ({place['user_ratings_total']}条)"
                        telegraph_content += "\n"
                    if place.get('is_open') is not None:
                        status = "🟢 营业中" if place['is_open'] else "🔴 已打烊"
                        telegraph_content += f"   状态: {status}\n"
                    telegraph_content += "\n"

                telegraph_content += f"\n数据来源: {service_name}"

                # 创建Telegraph页面
                telegraph_url = await create_telegraph_page(
                    f"附近的{type_name} - {location_data.get('name')}",
                    telegraph_content
                )

                if telegraph_url:
                    # 添加"查看全部"结果
                    summary_text = f"📍 **附近的{type_name}**\n\n"
                    summary_text += f"位置: {location_data.get('name')}\n"
                    summary_text += f"找到 {len(nearby_places)} 个结果\n\n"
                    summary_text += f"📄 [在Telegraph查看完整列表]({telegraph_url})\n\n"
                    summary_text += f"_数据来源: {service_name}_"

                    results.append(
                        InlineQueryResultArticle(
                            id=str(uuid4()),
                            title=f"📄 查看全部 ({len(nearby_places)} 个结果)",
                            description=f"在Telegraph查看完整列表",
                            thumbnail_url="https://img.icons8.com/color/96/000000/list.png",
                            input_message_content=InputTextMessageContent(
                                message_text=summary_text,
                                parse_mode="Markdown"
                            ),
                            reply_markup=InlineKeyboardMarkup([[
                                InlineKeyboardButton("📄 查看完整列表", url=telegraph_url)
                            ]])
                        )
                    )
            except Exception as e:
                logger.error(f"创建Telegraph汇总失败: {e}")

        # 添加各个地点的详细结果
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

            # 如果有照片，缓存照片信息用于 chosen handler
            result_id = str(uuid4())
            if place.get('photos') and len(place['photos']) > 0:
                photo_url = place['photos'][0]
                _map_photo_cache[result_id] = {
                    "photo_url": photo_url,
                    "caption": result_text,
                    "reply_markup": reply_markup
                }
                _cache_timestamps[result_id] = time.time()

            # 使用 Article 类型避免 thumbnail 访问问题
            results.append(
                InlineQueryResultArticle(
                    id=result_id,
                    title=f"📍 {name}",
                    description=description,
                    thumbnail_url="https://img.icons8.com/color/96/000000/marker.png",
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

        directions = await service.get_directions(origin_query, destination_query, "driving", httpx_client)

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
        distance = directions.get('distance', '未知')
        duration = directions.get('duration', '未知')

        # 检查主路线是否有toll
        main_has_tolls = False
        if 'steps' in directions and directions['steps']:
            main_has_tolls = any('Toll road' in step for step in directions['steps'])

        toll_status = " 💰" if main_has_tolls else " 🆓"
        result_text += f"📏 距离: {distance}{toll_status}\n"
        result_text += f"⏱️ 时间: {duration}\n"

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

        # 备选路线信息
        if directions.get('alternative_routes'):
            alt_count = len(directions['alternative_routes'])
            result_text += f"\n🔀 找到 {alt_count} 条备选路线\n"

        # 地图链接 - 构建路线规划 URL
        if language == "zh":
            # 高德地图路线规划
            map_url = f"https://uri.amap.com/navigation?from={origin_lng},{origin_lat}&to={dest_lng},{dest_lat}"
        else:
            # Google Maps 路线规划
            map_url = f"https://maps.google.com/maps?saddr={origin_lat},{origin_lng}&daddr={dest_lat},{dest_lng}"

        # 创建Telegraph页面显示详细路线
        service_type = "amap" if language == "zh" else "google_maps"
        telegraph_content = format_directions_for_telegraph(directions, service_type)
        telegraph_title = f"路线: {origin_data.get('name')} → {destination_data.get('name')}"
        telegraph_url = await create_telegraph_page(telegraph_title, telegraph_content)

        if telegraph_url:
            result_text += f"\n📄 [查看详细路线指引]({telegraph_url})"

        result_text += f"\n🗺️ [在地图中查看]({map_url})"
        result_text += f"\n\n_数据来源: {service_name}_"

        # 创建按钮
        keyboard = [[InlineKeyboardButton("🗺️ 查看路线", url=map_url)]]
        if telegraph_url:
            keyboard[0].append(InlineKeyboardButton("📄 详细指引", url=telegraph_url))
        reply_markup = InlineKeyboardMarkup(keyboard)

        # 描述文本
        description = f"{distance} | {duration}"
        if directions.get('is_eco_friendly'):
            description += " | 🌱"
        if directions.get('alternative_routes'):
            description += f" | {len(directions['alternative_routes'])} 条备选"

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
