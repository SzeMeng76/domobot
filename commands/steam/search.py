# Description: Steam API 搜索逻辑
# 从原 steam.py 拆分

import json
import logging
import re
from urllib.parse import quote

import httpx

from utils.constants import HTTP_TIMEOUT_DEFAULT
from utils.http_client import create_custom_client
from utils.task_manager import task_manager

from . import cache
from .cache import (
    cache_helper,
    save_bundle_to_mysql,
    save_game_to_mysql,
    smart_cache_manager,
)
from .models import Config

logger = logging.getLogger(__name__)
config = Config()


async def _search_games_from_store_page(query: str, cc: str) -> list[dict]:
    """通过 Steam 商店搜索页面搜索游戏（对中文支持更好）

    Steam 商店搜索页面 (/search/) 会搜索所有本地化名称，
    比 API (/api/storesearch/) 的中文匹配效果更好。

    例如：搜索 "文明6" 可以匹配到 "Sid Meier's Civilization® VI"
    """
    from bs4 import BeautifulSoup

    encoded_query = quote(query)
    # category1=998 = 游戏, l=schinese = 简体中文
    url = f"https://store.steampowered.com/search/?term={encoded_query}&category1=998&l={config.DEFAULT_LANG}&cc={cc}"

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Cookie": "Steam_Language=schinese; steamCountry=CN",
        }
        async with create_custom_client(headers=headers) as client:
            response = await client.get(url, timeout=HTTP_TIMEOUT_DEFAULT)
            response.raise_for_status()
            html = response.text

        soup = BeautifulSoup(html, "lxml")
        results = []

        # 解析搜索结果行
        # 结构: <a class="search_result_row" data-ds-appid="289070" href="...">
        #         <span class="title">Sid Meier's Civilization® VI</span>
        #       </a>
        for row in soup.find_all("a", class_="search_result_row"):
            app_id = row.get("data-ds-appid")
            if not app_id:
                # 尝试从 href 提取
                href = row.get("href", "")
                app_match = re.search(r"/app/(\d+)/", href)
                if app_match:
                    app_id = app_match.group(1)

            if app_id:
                title_elem = row.find("span", class_="title")
                name = (
                    title_elem.get_text(strip=True) if title_elem else f"App {app_id}"
                )
                results.append({"id": app_id, "name": name, "type": "game"})

        logger.debug(f"Store page search for '{query}' returned {len(results)} results")
        return results[:20]  # 限制返回数量

    except Exception as e:
        logger.warning(f"Store page search failed for '{query}': {e}")
        return []


async def search_game(query: str, cc: str, use_cache: bool = True) -> list[dict]:
    """搜索 Steam 游戏并返回结果列表"""
    await cache_helper.ensure_initialized()
    query_lower = query.lower()

    if use_cache and query_lower in cache_helper.game_id_cache:
        app_id = cache_helper.game_id_cache[query_lower]
        return [{"id": app_id, "name": query, "type": "game"}]

    encoded_query = quote(query)
    url = f"https://store.steampowered.com/api/storesearch/?term={encoded_query}&l={config.DEFAULT_LANG}&cc={cc}"

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        async with create_custom_client(headers=headers) as client:
            response = await client.get(url, timeout=HTTP_TIMEOUT_DEFAULT)
            response.raise_for_status()
            data = response.json()

        items = data.get("items", [])

        # 为每个项目添加类型信息
        for item in items:
            item_type = item.get("type", "game").lower()
            if "bundle" in item_type or "package" in item_type:
                item["type"] = "bundle"
            elif "dlc" in item_type or "downloadable content" in item_type:
                item["type"] = "dlc"
            else:
                item["type"] = "game"

        if items and use_cache:
            cache_helper.game_id_cache[query_lower] = items[0].get("id")
            await cache_helper.save_game_id_cache()

        return items
    except httpx.RequestError as e:
        logger.error(f"Error searching game: {e}")
        return []
    except json.JSONDecodeError:
        logger.error("JSON decode error during game search.")
        return []


async def get_game_details(app_id: str, cc: str) -> dict:
    """从 Steam API 获取游戏详情（带分层缓存）"""

    cache_key = f"steam:game:{app_id}:{cc}"

    # 第1层：Redis热缓存查询
    cached_data = await cache.cache_manager.load_cache(
        cache_key, max_age_seconds=config.steam_redis_cache, subdirectory="steam"
    )
    if cached_data:
        logger.debug(f"✅ Steam Redis缓存命中: {app_id}/{cc}")
        return cached_data

    # 第2层：MySQL持久化缓存查询
    if smart_cache_manager:
        try:
            db_data = await smart_cache_manager.db.get_latest_price(
                service="steam",
                item_id=app_id,
                country_code=cc,
                freshness_threshold=config.steam_db_freshness,
            )
            if db_data:
                logger.info(f"✅ Steam MySQL缓存命中: {app_id}/{cc}")
                # 回写Redis热缓存
                await cache.cache_manager.save_cache(
                    cache_key,
                    db_data,
                    subdirectory="steam",
                    ttl=config.steam_redis_cache,
                )
                return db_data
        except Exception as e:
            logger.warning(f"Steam MySQL查询失败: {e}")

    # 第3层：爬取新数据
    logger.info(f"🔄 Steam缓存未命中，开始爬取: {app_id}/{cc}")
    url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&cc={cc}&l={config.DEFAULT_LANG}"
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        async with create_custom_client(headers=headers) as client:
            response = await client.get(url, timeout=HTTP_TIMEOUT_DEFAULT)
            response.raise_for_status()
            data = response.json()

        result = data.get(str(app_id), {})

        if result.get("success"):
            # 保存到Redis热缓存
            await cache.cache_manager.save_cache(
                cache_key,
                result,
                subdirectory="steam",
                ttl=config.steam_redis_cache,
            )

            # 异步保存到MySQL持久化（性能优化）
            if smart_cache_manager:
                game_data = result.get("data", {})
                price_overview = game_data.get("price_overview", {})
                task_manager.create_task(
                    save_game_to_mysql(
                        app_id=app_id,
                        cc=cc,
                        game_name=game_data.get("name", ""),
                        price_overview=price_overview,
                        result=result,
                    ),
                    name=f"steam_save_game_{app_id}",
                    context="steam_mysql",
                )

        return result
    except httpx.RequestError as e:
        logger.error(f"Error getting game details: {e}")
        return {}
    except json.JSONDecodeError:
        logger.error("JSON decode error during game details fetch.")
        return {}


async def search_bundle(query: str, cc: str) -> list[dict]:
    """搜索 Steam 捆绑包（通过游戏详情页提取关联捆绑包）

    搜索流程：
    1. 使用商店搜索页面搜索游戏（对中文本地化名称支持更好）
    2. 从游戏详情页提取关联的捆绑包链接和名称

    Note: 商店搜索页面会搜索所有本地化名称，例如：
    - 搜索 "文明6" 可以找到 "Sid Meier's Civilization® VI"
    - 搜索 "三国志" 可以找到相关游戏
    """
    import asyncio

    from bs4 import BeautifulSoup

    await cache_helper.ensure_initialized()
    query_lower = query.lower()

    # 缓存命中检查
    if query_lower in cache_helper.bundle_id_cache:
        cached_bundle = cache_helper.bundle_id_cache[query_lower]
        return [
            {
                "id": cached_bundle["id"],
                "name": cached_bundle["name"],
                "url": f"https://store.steampowered.com/bundle/{cached_bundle['id']}",
            }
        ]

    # 1. 使用商店搜索页面搜索游戏（对中文支持更好），API 作为回退
    games = await _search_games_from_store_page(query, cc)
    if not games:
        games = await search_game(query, cc, use_cache=True)
    if not games:
        return []

    # 2. 从游戏详情页提取关联捆绑包（并行请求前5个游戏以获得更多结果）
    async def fetch_bundles_from_game(app_id: str) -> list[dict]:
        """从单个游戏详情页提取捆绑包（使用 BeautifulSoup 解析）"""
        url = f"https://store.steampowered.com/app/{app_id}/?cc={cc}&l={config.DEFAULT_LANG}"
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept-Language": "zh-CN,zh;q=0.9",
            }
            async with create_custom_client(headers=headers) as client:
                response = await client.get(url, timeout=HTTP_TIMEOUT_DEFAULT)
                response.raise_for_status()
                html = response.text

            soup = BeautifulSoup(html, "lxml")
            bundles = []
            seen_bundle_ids = set()

            # 方法1: 查找 tab_item 结构中的捆绑包（最常见）
            # 结构: <a class="tab_item" href="/bundle/ID/...">
            #         <div class="tab_item_name">Bundle Name</div>
            #       </a>
            for tab_item in soup.find_all("a", class_="tab_item"):
                href = tab_item.get("href", "")
                bundle_match = re.search(r"/bundle/(\d+)/", href)
                if bundle_match:
                    bundle_id = bundle_match.group(1)
                    if bundle_id in seen_bundle_ids:
                        continue
                    seen_bundle_ids.add(bundle_id)

                    # 从 tab_item_name 中提取名称
                    name_div = tab_item.find("div", class_="tab_item_name")
                    if name_div:
                        name = name_div.get_text(strip=True)
                    else:
                        # 回退: 从 URL slug 提取
                        slug_match = re.search(r"/bundle/\d+/([^/?]+)", href)
                        name = (
                            slug_match.group(1).replace("_", " ")
                            if slug_match
                            else f"Bundle {bundle_id}"
                        )

                    bundles.append({"id": bundle_id, "name": name})

            # 方法2: 查找其他捆绑包链接（如推荐区域）
            for link in soup.find_all("a", href=re.compile(r"/bundle/\d+")):
                href = link.get("href", "")
                bundle_match = re.search(r"/bundle/(\d+)/", href)
                if bundle_match:
                    bundle_id = bundle_match.group(1)
                    if bundle_id in seen_bundle_ids:
                        continue
                    seen_bundle_ids.add(bundle_id)

                    # 优先从 URL slug 提取名称（更可靠，避免捕获 "捆绑包信息" 等无效文本）
                    slug_match = re.search(r"/bundle/\d+/([^/?]+)", href)
                    if slug_match:
                        name = slug_match.group(1).replace("_", " ")
                    else:
                        # 回退：尝试链接文本，但过滤无效名称
                        name = link.get_text(strip=True)
                        invalid_names = {
                            "捆绑包信息",
                            "bundleinfo",
                            "bundle info",
                            "查看详情",
                            "view details",
                            "",
                        }
                        if not name or name.lower() in invalid_names or len(name) < 3:
                            name = f"Bundle {bundle_id}"

                    bundles.append({"id": bundle_id, "name": name})

            return bundles
        except Exception as e:
            logger.debug(f"Error fetching bundles from app {app_id}: {e}")
            return []

    # 并行获取前5个游戏的关联捆绑包
    app_ids = [str(g.get("id")) for g in games[:5] if g.get("id")]
    results = await asyncio.gather(*[fetch_bundles_from_game(aid) for aid in app_ids])

    # 去重合并
    seen_ids = set()
    unique_bundles = []
    for bundle_list in results:
        for bundle in bundle_list:
            if bundle["id"] not in seen_ids:
                seen_ids.add(bundle["id"])
                bundle["url"] = f"https://store.steampowered.com/bundle/{bundle['id']}"
                bundle["type"] = "bundle"  # 添加类型以便 UI 显示图标
                unique_bundles.append(bundle)
                # 缓存
                cache_helper.bundle_id_cache[bundle["name"].lower()] = {
                    "id": bundle["id"],
                    "name": bundle["name"],
                }

    if unique_bundles:
        await cache_helper.save_bundle_id_cache()

    return unique_bundles[: config.MAX_BUNDLE_RESULTS]


async def search_bundle_by_id(bundle_id: str, cc: str) -> dict | None:
    """通过 ID 搜索捆绑包并返回详情"""
    return await get_bundle_details(bundle_id, cc)


async def get_bundle_details(bundle_id: str, cc: str) -> dict | None:
    """从 Steam 商店页面获取捆绑包详情（带分层缓存）"""

    cache_key = f"steam:bundle:{bundle_id}:{cc}"

    # 第1层：Redis热缓存查询
    cached_data = await cache.cache_manager.load_cache(
        cache_key, max_age_seconds=config.steam_redis_cache, subdirectory="steam"
    )
    if cached_data:
        logger.debug(f"✅ Steam Bundle Redis缓存命中: {bundle_id}/{cc}")
        return cached_data

    # 第2层：MySQL持久化缓存查询
    if smart_cache_manager:
        try:
            db_data = await smart_cache_manager.db.get_latest_price(
                service="steam",
                item_id=f"bundle_{bundle_id}",
                country_code=cc,
                freshness_threshold=config.steam_db_freshness,
            )
            if db_data:
                logger.info(f"✅ Steam Bundle MySQL缓存命中: {bundle_id}/{cc}")
                await cache.cache_manager.save_cache(
                    cache_key,
                    db_data,
                    subdirectory="steam",
                    ttl=config.steam_redis_cache,
                )
                return db_data
        except Exception as e:
            logger.warning(f"Steam Bundle MySQL查询失败: {e}")

    # 第3层：爬取新数据
    logger.info(f"🔄 Steam Bundle缓存未命中，开始爬取: {bundle_id}/{cc}")
    url = f"https://store.steampowered.com/bundle/{bundle_id}?cc={cc}&l=schinese"
    headers = {
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Cookie": "steamCountry=CN%7C5a92c37537078a8cc660c6be649642b2; timezoneOffset=28800,0; birthtime=946656001; lastagecheckage=1-January-2000",
    }

    try:
        async with create_custom_client(headers=headers) as client:
            response = await client.get(
                url,
                timeout=HTTP_TIMEOUT_DEFAULT,
            )
            response.raise_for_status()
            content = response.text

        name_match = re.search(
            r'<h2[^>]*class="[^"]*pageheader[^"]*"[^>]*>(.*?)</h2>',
            content,
            re.DOTALL,
        )
        bundle_name = name_match.group(1).strip() if name_match else "未知捆绑包"

        games = []
        for game_match in re.finditer(
            r'<div class="tab_item.*?tab_item_name">(.*?)</div>.*?discount_final_price">(.*?)</div>',
            content,
            re.DOTALL,
        ):
            game_name = game_match.group(1).strip()
            game_price = game_match.group(2).strip()
            games.append({"name": game_name, "price": {"final_formatted": game_price}})

        price_info = {
            "original_price": "未知",
            "discount_pct": "0",
            "final_price": "未知",
            "savings": "0",
        }

        price_block = re.search(
            r'<div class="package_totals_area.*?</div>\s*</div>', content, re.DOTALL
        )
        if price_block:
            price_content = price_block.group(0)

            original_match = re.search(
                r'bundle_final_package_price">([^<]+)</div>', price_content
            )
            if original_match:
                price_info["original_price"] = original_match.group(1).strip()

            discount_match = re.search(r'bundle_discount">([^<]+)</div>', price_content)
            if discount_match:
                discount = (
                    discount_match.group(1).strip().replace("%", "").replace("-", "")
                )
                price_info["discount_pct"] = discount

            final_match = re.search(
                r'bundle_final_price_with_discount">([^<]+)</div>', price_content
            )
            if final_match:
                price_info["final_price"] = final_match.group(1).strip()

            savings_match = re.search(r'bundle_savings">([^<]+)</div>', price_content)
            if savings_match:
                price_info["savings"] = savings_match.group(1).strip()

        bundle_data = {
            "name": bundle_name,
            "url": url,
            "items": games,
            "original_price": price_info["original_price"],
            "discount_pct": price_info["discount_pct"],
            "final_price": price_info["final_price"],
            "savings": price_info["savings"],
        }

        # 保存到Redis热缓存
        await cache.cache_manager.save_cache(
            cache_key,
            bundle_data,
            subdirectory="steam",
            ttl=config.steam_redis_cache,
        )

        # 异步保存到MySQL
        if smart_cache_manager:
            task_manager.create_task(
                save_bundle_to_mysql(
                    bundle_id=bundle_id,
                    cc=cc,
                    bundle_name=bundle_name,
                    price_info=price_info,
                    bundle_data=bundle_data,
                ),
                name=f"steam_save_bundle_{bundle_id}",
                context="steam_mysql",
            )

        return bundle_data

    except httpx.RequestError as e:
        logger.error(f"Error getting bundle details: {e}")
        return None
    except Exception as e:
        logger.error(f"Unknown error getting bundle details: {e}")
        return None
