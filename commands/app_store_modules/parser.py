"""
App Store HTML/JSON-LD 解析器

负责解析 App Store 页面的 HTML 和 JSON-LD 结构化数据
优先使用 JSON-LD 中的 priceCurrency 字段
"""

import json
import logging
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from utils.country_data import SUPPORTED_COUNTRIES

from .constants import JSON_LD_SCRIPT_TYPE, JSON_LD_SOFTWARE_TYPE, SELECTORS

logger = logging.getLogger(__name__)


class AppStoreParser:
    """App Store 页面解析器"""

    @staticmethod
    def parse_json_ld_offers(html_content: str, country_code: str) -> Optional[Dict]:
        """
        从 HTML 中提取 JSON-LD 的 offers 信息

        Args:
            html_content: HTML 内容
            country_code: 国家代码

        Returns:
            包含价格、货币、类别等信息的字典，解析失败返回 None
        """
        try:
            soup = BeautifulSoup(html_content, "lxml")
        except Exception:
            soup = BeautifulSoup(html_content, "html.parser")

        script_tags = soup.find_all("script", type=JSON_LD_SCRIPT_TYPE)

        for script in script_tags:
            if not script.string:
                continue

            try:
                json_data = json.loads(script.string)

                # 检查是否是 SoftwareApplication 类型
                if not isinstance(json_data, dict) or json_data.get("@type") != JSON_LD_SOFTWARE_TYPE:
                    continue

                # 提取应用名称
                app_name = json_data.get("name", "").strip()

                # 提取 offers 信息
                offers = json_data.get("offers", {})
                if not offers:
                    logger.warning(f"JSON-LD 中未找到 offers 信息 (国家: {country_code})")
                    return {
                        "app_name": app_name,
                        "currency": SUPPORTED_COUNTRIES.get(country_code, {}).get("currency", "USD"),
                        "price": 0,
                        "category": "free",
                        "source": "default",
                    }

                # 处理 offers 可能为列表的情况
                if isinstance(offers, list):
                    if not offers:
                        logger.warning(f"offers 列表为空 (国家: {country_code})")
                        return None
                    offers = offers[0]  # 取第一个 offer

                # 提取关键字段
                currency = offers.get("priceCurrency", "USD")
                price = float(offers.get("price", 0))
                category = offers.get("category", "free").lower()

                logger.info(
                    f"✓ JSON-LD 解析成功: app='{app_name}', currency={currency}, price={price}, category={category}"
                )

                return {
                    "app_name": app_name,
                    "currency": currency,
                    "price": price,
                    "category": category,
                    "source": "json_ld",
                }

            except (json.JSONDecodeError, TypeError, ValueError) as e:
                logger.debug(f"解析 JSON-LD 失败: {e}")
                continue

        logger.warning(f"未找到有效的 JSON-LD 数据 (国家: {country_code})")
        return None

    @staticmethod
    def parse_in_app_purchases_html(html_content: str) -> List[Dict]:
        """
        从 HTML 中提取内购项目（适配 Apple 新的 Svelte 组件结构）

        Args:
            html_content: HTML 内容

        Returns:
            内购项目列表，每个元素包含 name, price_str
        """
        try:
            soup = BeautifulSoup(html_content, "lxml")
        except Exception:
            soup = BeautifulSoup(html_content, "html.parser")

        # 使用新的 Svelte 选择器
        in_app_items = soup.select(SELECTORS["in_app_items"])
        unique_items = set()
        in_app_purchases = []

        if not in_app_items:
            logger.info("未找到内购项目（可能是免费应用或无内购）")
            return []

        for item in in_app_items:
            # 查找 text-pair 容器
            text_pair = item.find("div", class_="text-pair")

            if not text_pair:
                continue

            # 提取所有 span 标签
            spans = text_pair.find_all("span")

            if len(spans) < 2:
                continue

            # 第一个 span 是名称，第二个 span 是价格
            name = spans[0].text.strip()
            price_str = spans[1].text.strip()

            # 基本验证
            if not name or not price_str:
                continue

            # 去重
            item_tuple = (name, price_str)
            if item_tuple in unique_items:
                continue

            unique_items.add(item_tuple)
            in_app_purchases.append({"name": name, "price_str": price_str})

        logger.info(f"解析到 {len(in_app_purchases)} 个内购项目")
        return in_app_purchases

    @staticmethod
    def extract_metadata(html_content: str) -> Dict:
        """
        提取应用的元数据（评分、分类、开发者等）

        Args:
            html_content: HTML 内容

        Returns:
            元数据字典
        """
        try:
            soup = BeautifulSoup(html_content, "lxml")
        except Exception:
            soup = BeautifulSoup(html_content, "html.parser")

        metadata = {}

        script_tags = soup.find_all("script", type=JSON_LD_SCRIPT_TYPE)

        for script in script_tags:
            if not script.string:
                continue

            try:
                json_data = json.loads(script.string)

                if not isinstance(json_data, dict) or json_data.get("@type") != JSON_LD_SOFTWARE_TYPE:
                    continue

                # 提取元数据
                metadata["name"] = json_data.get("name", "").strip()

                # 评分信息
                aggregate_rating = json_data.get("aggregateRating", {})
                if aggregate_rating:
                    metadata["rating_value"] = aggregate_rating.get("ratingValue")
                    metadata["review_count"] = aggregate_rating.get("reviewCount")

                # 分类
                metadata["category"] = json_data.get("applicationCategory")

                # 开发者信息
                author = json_data.get("author", {})
                if author:
                    metadata["developer_name"] = author.get("name")
                    metadata["developer_url"] = author.get("url")

                # 系统要求
                metadata["operating_system"] = json_data.get("operatingSystem")

                break

            except (json.JSONDecodeError, TypeError) as e:
                logger.debug(f"提取元数据失败: {e}")
                continue

        return metadata
