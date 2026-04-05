#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sensor Tower API 封装模块
提供 Google Play 应用搜索和详情查询功能
"""

import asyncio
import logging
import time
from typing import Optional

import httpx

from utils.constants import HTTP_TIMEOUT_DEFAULT

logger = logging.getLogger(__name__)


class SensorTowerAPI:
    """
    Sensor Tower API 客户端

    提供应用搜索和详情查询功能，支持请求限流和错误处理
    """

    # API 端点
    SEARCH_URL = "https://app.sensortower.com/api/autocomplete_search"
    APP_DETAILS_URL = "https://app.sensortower.com/api/android/apps/{pkg}"

    # 请求间隔（秒）
    REQUEST_INTERVAL = 0.5

    # 请求超时（秒）
    TIMEOUT = HTTP_TIMEOUT_DEFAULT

    # User-Agent
    USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    def __init__(self):
        """初始化 API 客户端"""
        self._last_request_time = 0
        self._client = httpx.AsyncClient(
            headers={"User-Agent": self.USER_AGENT},
            timeout=self.TIMEOUT,
            follow_redirects=True,
        )

    async def _rate_limit(self):
        """请求限流控制"""
        current_time = time.time()
        elapsed = current_time - self._last_request_time

        if elapsed < self.REQUEST_INTERVAL:
            wait_time = self.REQUEST_INTERVAL - elapsed
            await asyncio.sleep(wait_time)

        self._last_request_time = time.time()

    async def search_apps(
        self, keyword: str, top_n: int = 5, os: str = "android"
    ) -> list[dict]:
        """
        搜索应用（全球搜索，不限国家）

        Args:
            keyword: 搜索关键词
            top_n: 返回结果数量（默认 5）
            os: 操作系统（android 或 ios）

        Returns:
            应用列表，每个应用包含：
            - appId: 应用包名
            - title: 应用名称
            - publisher: 开发者名称
            - icon: 图标URL
            - categories: 分类列表
            - downloads: 下载量（字符串）
            - active: 是否在架

        Raises:
            Exception: 搜索失败时抛出异常
        """
        params = {
            "entity_type": "app",
            "limit": top_n,
            "os": os.lower(),
            "term": keyword,
        }

        # 请求限流
        await self._rate_limit()

        try:
            logger.info(f"搜索应用: {keyword}, limit={top_n}, os={os}")
            response = await self._client.get(self.SEARCH_URL, params=params)
            response.raise_for_status()
            data = response.json()

            # 解析响应数据
            entities = data.get("data", {}).get("entities", [])

            results = []
            for item in entities:
                app_data = {
                    "appId": item.get("app_id", ""),
                    "title": item.get("name", ""),
                    "publisher": item.get("publisher_name", ""),
                    "icon": item.get("icon_url", ""),
                    "categories": item.get("categories", []),
                    "downloads": item.get(
                        "humanized_worldwide_last_month_downloads", {}
                    ).get("string", ""),
                    "active": item.get("active", True),
                }
                results.append(app_data)

            logger.info(f"搜索成功，找到 {len(results)} 个结果")
            return results

        except httpx.HTTPStatusError as e:
            logger.error(f"搜索请求失败: {e}")
            raise Exception(f"Sensor Tower 搜索失败: {str(e)}")
        except Exception as e:
            logger.error(f"搜索时发生错误: {e}")
            raise

    async def get_app_details(
        self, package_name: str, country: str = "US"
    ) -> Optional[dict]:
        """
        获取应用详情

        Args:
            package_name: 应用包名
            country: 国家代码（2字母，如 US, CN）

        Returns:
            应用详情字典，包含：
            - name: 应用名称
            - publisher_name: 开发者名称
            - price: 价格信息 {value, currency, string_value}
            - top_in_app_purchases: 内购信息
            - 其他详情字段

            如果应用不存在或查询失败，返回 None

        Raises:
            Exception: 查询失败时抛出异常
        """
        url = self.APP_DETAILS_URL.format(pkg=package_name)
        params = {"country": country.upper()}

        # 请求限流
        await self._rate_limit()

        try:
            logger.info(f"查询应用详情: {package_name}, country={country}")
            response = await self._client.get(url, params=params)

            # 如果应用不存在，返回 None
            if response.status_code == 404:
                logger.warning(f"应用不存在: {package_name} (country={country})")
                return None

            response.raise_for_status()
            data = response.json()

            logger.info(f"查询成功: {package_name}")
            return data

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning(f"应用不存在: {package_name} (country={country})")
                return None
            logger.error(f"详情查询失败: {e}")
            raise Exception(f"Sensor Tower 详情查询失败: {str(e)}")
        except Exception as e:
            logger.error(f"查询详情时发生错误: {e}")
            raise

    async def close(self):
        """关闭 HTTP 客户端"""
        if self._client:
            await self._client.aclose()

    async def __aenter__(self):
        """异步上下文管理器支持"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器支持"""
        await self.close()
