#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Play Scraper 封装模块
提供 Google Play 应用搜索和详情查询功能
"""

import asyncio
import logging
from typing import Optional

from utils.google_play_html_scraper import search as gp_search, app as gp_app

logger = logging.getLogger(__name__)


class SensorTowerAPI:
    """
    Google Play Scraper 客户端

    提供应用搜索和详情查询功能
    """

    def __init__(self):
        """初始化客户端"""
        pass

    async def search_apps(
        self, keyword: str, top_n: int = 5, os: str = "android"
    ) -> list[dict]:
        """
        搜索应用（使用自定义 HTML scraper）

        Args:
            keyword: 搜索关键词
            top_n: 返回结果数量（默认 5）
            os: 操作系统（android 或 ios，目前仅支持 android）

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
        if os.lower() != "android":
            raise Exception(f"不支持的操作系统: {os}，目前仅支持 android")

        try:
            logger.info(f"搜索应用: {keyword}, limit={top_n}")

            # 使用自定义 HTML scraper 搜索
            search_results = await asyncio.to_thread(
                gp_search, keyword, n_hits=top_n, lang="en", country="us"
            )

            # 获取每个应用的详细信息
            results = []
            for item in search_results:
                app_id = item.get("appId", "")
                if not app_id:
                    continue

                try:
                    # 获取应用详情
                    details = await asyncio.to_thread(
                        gp_app, app_id, lang="en", country="us"
                    )

                    app_data = {
                        "appId": app_id,
                        "title": details.get("title", ""),
                        "publisher": details.get("developer", ""),
                        "icon": details.get("icon", ""),
                        "categories": [details.get("genre", "")] if details.get("genre") else [],
                        "downloads": details.get("installs", ""),
                        "active": True,
                    }
                    results.append(app_data)
                except Exception as e:
                    logger.warning(f"获取应用 {app_id} 详情失败: {e}")
                    # 即使获取详情失败，也添加基本信息
                    results.append({
                        "appId": app_id,
                        "title": app_id,
                        "publisher": "",
                        "icon": "",
                        "categories": [],
                        "downloads": "",
                        "active": True,
                    })

            logger.info(f"搜索成功，找到 {len(results)} 个结果")
            return results

        except Exception as e:
            logger.error(f"搜索时发生错误: {e}")
            raise

    async def get_app_details(
        self, package_name: str, country: str = "US"
    ) -> Optional[dict]:
        """
        获取应用详情（使用自定义 scraper）

        Args:
            package_name: 应用包名
            country: 国家代码（2字母，如 US, CN）

        Returns:
            应用详情字典，如果应用不存在或查询失败，返回 None
        """
        try:
            logger.info(f"查询应用详情: {package_name}, country={country}")

            # 使用自定义 scraper 获取详情
            details = await asyncio.to_thread(
                gp_app, package_name, lang="en", country=country.lower()
            )

            logger.info(f"查询成功: {package_name}")
            return details

        except Exception as e:
            logger.warning(f"查询详情时发生错误: {e}")
            return None

    async def close(self):
        """关闭客户端（兼容性方法）"""
        pass

    async def __aenter__(self):
        """异步上下文管理器支持"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器支持"""
        await self.close()
