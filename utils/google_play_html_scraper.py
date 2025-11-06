#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Play Scraper - 基于 HTML 解析（更可靠）
直接解析搜索页面的 HTML，提取应用链接
"""

import re
import logging
from typing import List, Dict, Any
from urllib.parse import quote
import requests

logger = logging.getLogger(__name__)


class GooglePlayHTMLScraper:
    """基于 HTML 解析的 Google Play 爬虫（比 JSON 解析更可靠）"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        })

    def search(
        self,
        query: str,
        lang: str = 'en',
        country: str = 'us',
        n_hits: int = 5
    ) -> List[Dict[str, Any]]:
        """
        搜索 Google Play 应用（HTML 解析版本）

        Args:
            query: 搜索关键词
            lang: 语言代码
            country: 国家代码
            n_hits: 返回结果数量

        Returns:
            搜索结果列表，每个元素包含 appId 和 title

        Example:
            >>> scraper = GooglePlayHTMLScraper()
            >>> results = scraper.search("Tasker", lang="en", country="us")
            >>> print(results[0]['appId'])
            'net.dinglisch.android.taskerm'
        """
        url = f"https://play.google.com/store/search?q={quote(query)}&c=apps&hl={lang}&gl={country}"

        logger.info(f"Searching: {query} (lang={lang}, country={country})")

        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            html = response.text

            # 提取所有应用链接
            # 格式: href="/store/apps/details?id=com.example.app"
            app_links = re.findall(r'href="/store/apps/details\?id=([^"&]+)"', html)

            # 去重（保持顺序）
            seen = set()
            unique_links = []
            for link in app_links:
                if link not in seen:
                    seen.add(link)
                    unique_links.append(link)

            # 限制数量
            unique_links = unique_links[:n_hits]

            # 构建结果
            results = []
            for app_id in unique_links:
                results.append({
                    'appId': app_id,
                    'title': None,  # HTML 解析版本不提取标题，需要的话再调用 app() 获取
                })

            logger.info(f"Found {len(results)} results")
            return results

        except Exception as e:
            logger.error(f"Search failed: {e}")
            raise


# 导入原来的 app() 函数（获取应用详情）
# 这部分仍然使用 google-play-scraper 库，因为它能正确提取应用详情
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'google-play-scraper-master'))

from google_play_scraper import app as gp_app_original


def app(app_id: str, lang: str = 'en', country: str = 'us') -> Dict[str, Any]:
    """
    获取应用详情（使用原库）

    Args:
        app_id: 应用包名
        lang: 语言代码
        country: 国家代码

    Returns:
        应用详细信息字典
    """
    return gp_app_original(app_id, lang=lang, country=country)


def search(query: str, lang: str = 'en', country: str = 'us', n_hits: int = 5) -> List[Dict[str, Any]]:
    """
    搜索应用（兼容旧 API）

    Args:
        query: 搜索关键词
        lang: 语言代码
        country: 国家代码
        n_hits: 返回结果数量

    Returns:
        搜索结果列表
    """
    scraper = GooglePlayHTMLScraper()
    return scraper.search(query, lang, country, n_hits)


if __name__ == "__main__":
    # 测试代码
    logging.basicConfig(level=logging.INFO)

    print("=" * 80)
    print("测试 Google Play HTML Scraper")
    print("=" * 80)

    # 测试搜索
    print("\n[测试 1] 搜索 'Tasker'")
    results = search("Tasker", lang="en", country="us", n_hits=5)

    for i, result in enumerate(results):
        app_id = result['appId']
        print(f"  {i+1}. {app_id}")

        # 获取详情
        try:
            details = app(app_id, lang="en", country="us")
            print(f"      标题: {details.get('title')}")
            print(f"      开发者: {details.get('developer')}")
        except Exception as e:
            print(f"      获取详情失败: {e}")

    print("\n" + "=" * 80)
    print("测试完成！")
    print("=" * 80)
