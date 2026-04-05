# Description: Steam 模块的缓存管理
# 从原 steam.py 拆分

import logging

logger = logging.getLogger(__name__)

# 模块级缓存管理器（由外部注入）
cache_manager = None
smart_cache_manager = None
rate_converter = None


def set_cache_manager(manager):
    """设置缓存管理器"""
    global cache_manager
    cache_manager = manager


def set_smart_cache_manager(manager):
    """设置智能缓存管理器（方案C: Redis热缓存 + MySQL持久化）"""
    global smart_cache_manager
    smart_cache_manager = manager


def set_rate_converter(converter):
    """设置汇率转换器"""
    global rate_converter
    rate_converter = converter


async def save_game_to_mysql(
    app_id: str, cc: str, game_name: str, price_overview: dict, result: dict
):
    """异步保存游戏价格数据到MySQL"""
    if not smart_cache_manager:
        return

    try:
        # 构造价格数据
        game_data = result.get("data", {})
        price_data = {
            "currency": price_overview.get("currency"),
            "original_price": (
                price_overview.get("initial", 0) / 100
                if price_overview.get("initial")
                else None
            ),
            "current_price": (
                price_overview.get("final", 0) / 100
                if price_overview.get("final")
                else None
            ),
            "discount_percent": price_overview.get("discount_percent", 0),
            "price_cny": None,  # 会在转换后设置
            # 额外数据（基础）
            "is_free": game_data.get("is_free", False),
            "type": game_data.get("type", "game"),
            # Web 端增强元数据
            "developers": game_data.get("developers", []),
            "publishers": game_data.get("publishers", []),
            "genres": [g.get("description", "") for g in game_data.get("genres", [])],
            "categories": [
                c.get("description", "") for c in game_data.get("categories", [])
            ],
            "short_description": game_data.get("short_description", ""),
            "header_image": game_data.get("header_image", ""),
            "release_date": game_data.get("release_date", {}).get("date", ""),
            "platforms": game_data.get("platforms", {}),
            "metacritic_score": game_data.get("metacritic", {}).get("score"),
            "recommendations_total": game_data.get("recommendations", {}).get("total"),
        }

        # 如果有汇率转换器，计算CNY价格
        if rate_converter and price_data.get("current_price"):
            try:
                currency = price_data.get("currency", "USD")
                cny_price = await rate_converter.convert(
                    price_data["current_price"], currency, "CNY"
                )
                price_data["price_cny"] = cny_price
            except Exception as e:
                logger.warning(f"汇率转换失败: {e}")

        await smart_cache_manager.db.save_price(
            service="steam",
            item_id=app_id,
            item_name=game_name,
            country_code=cc,
            price_data=price_data,
        )
        logger.debug(f"Steam价格已保存到MySQL: {app_id}/{cc}")
    except Exception as e:
        logger.error(f"保存Steam价格到MySQL失败: {e}")


async def save_bundle_to_mysql(
    bundle_id: str, cc: str, bundle_name: str, price_info: dict, bundle_data: dict
):
    """异步保存捆绑包价格数据到MySQL"""
    if not smart_cache_manager:
        return

    try:
        from .parser import parse_bundle_price

        price_data = {
            "currency": "CNY" if cc.upper() == "CN" else None,
            "original_price": parse_bundle_price(price_info.get("original_price")),
            "current_price": parse_bundle_price(price_info.get("final_price")),
            "discount_percent": (
                int(price_info.get("discount_pct", 0))
                if price_info.get("discount_pct")
                else 0
            ),
            "price_cny": (
                parse_bundle_price(price_info.get("final_price"))
                if cc.upper() == "CN"
                else None
            ),
            "type": "bundle",
            "items_count": len(bundle_data.get("items", [])),
        }

        await smart_cache_manager.db.save_price(
            service="steam",
            item_id=f"bundle_{bundle_id}",
            item_name=bundle_name,
            country_code=cc,
            price_data=price_data,
        )
        logger.debug(f"Steam Bundle价格已保存到MySQL: {bundle_id}/{cc}")
    except Exception as e:
        logger.error(f"保存Steam Bundle价格到MySQL失败: {e}")


class CacheHelper:
    """缓存辅助类，管理游戏和捆绑包ID缓存"""

    def __init__(self):
        self.game_id_cache = None
        self.bundle_id_cache = None
        self._cache_initialized = False

    async def ensure_initialized(self):
        """确保缓存已初始化"""
        if not self._cache_initialized:
            self.game_id_cache = (
                await cache_manager.load_cache("steam:ids:games", subdirectory="steam")
                or {}
            )
            self.bundle_id_cache = (
                await cache_manager.load_cache("steam:ids:bundles", subdirectory="steam")
                or {}
            )
            self._cache_initialized = True

    async def save_game_id_cache(self):
        """保存游戏ID缓存"""
        await cache_manager.save_cache(
            "steam:ids:games", self.game_id_cache, subdirectory="steam"
        )

    async def save_bundle_id_cache(self):
        """保存捆绑包ID缓存"""
        await cache_manager.save_cache(
            "steam:ids:bundles", self.bundle_id_cache, subdirectory="steam"
        )


# 全局缓存辅助实例
cache_helper = CacheHelper()
