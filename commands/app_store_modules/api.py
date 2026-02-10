"""
App Store 网页搜索 API 封装

负责 App Store 网页搜索和应用详情页面获取
"""

import logging
import re
from typing import Dict, Optional

import httpx
from bs4 import BeautifulSoup

from .constants import MINIMAL_HEADERS, WEB_SEARCH_LIMIT

logger = logging.getLogger(__name__)


class AppStoreWebAPI:
    """App Store 网页 API 客户端"""

    @staticmethod
    async def fetch_app_page(app_id: int, country_code: str) -> Optional[str]:
        """
        获取应用详情页面的 HTML 内容

        Args:
            app_id: App ID
            country_code: 国家代码

        Returns:
            HTML 内容，失败返回 None
        """
        url = f"https://apps.apple.com/{country_code.lower()}/app/id{app_id}"

        try:
            # 增加超时时间，优化重定向处理
            async with httpx.AsyncClient(
                follow_redirects=True,
                verify=False,
                timeout=httpx.Timeout(20.0, connect=10.0)
            ) as client:
                logger.info(f"获取应用页面: {url}")
                response = await client.get(url, headers=MINIMAL_HEADERS)
                response.raise_for_status()

                # 记录重定向信息
                if response.history:
                    logger.info(f"经过 {len(response.history)} 次重定向，最终 URL: {response.url}")

                return response.text

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.info(f"App 'id{app_id}' 在 {country_code} 未上架 (404)")
            else:
                logger.error(f"HTTP 错误 {e.response.status_code}: {url}")
            return None

        except httpx.RequestError as e:
            logger.error(f"网络请求失败: {url} - {e}")
            return None

        except Exception as e:
            logger.error(f"未知错误: {url} - {e}")
            return None

    @staticmethod
    async def search_apps_by_web(
        query: str,
        country: str = "us",
        platform: str = "iphone",
        limit: int = WEB_SEARCH_LIMIT,
    ) -> Dict:
        """
        使用 App Store 网页搜索应用（覆盖率比 iTunes API 更高）

        Args:
            query: 搜索关键词
            country: 国家代码 (默认 us)
            platform: 平台类型 (iphone, ipad, mac, tv, watch, vision)
            limit: 返回结果数量（仅作参考，实际由网页返回数量决定）

        Returns:
            包含搜索结果的字典
        """
        url = f"https://apps.apple.com/{country}/{platform}/search"
        params = {"term": query}

        try:
            # 增加超时时间，优化重定向处理
            async with httpx.AsyncClient(
                follow_redirects=True,
                verify=False,
                timeout=httpx.Timeout(20.0, connect=10.0)
            ) as client:
                logger.info(
                    f"网页搜索: query='{query}', country={country}, platform={platform}"
                )

                response = await client.get(
                    url, params=params, headers=MINIMAL_HEADERS
                )
                response.raise_for_status()

                html_content = response.text
                soup = BeautifulSoup(html_content, "lxml")

                # 调试：记录 HTML 大小和链接数量
                logger.info(f"收到 HTML: {len(html_content)} 字节")

                # 调试：保存 HTML 到文件用于调试
                import os
                debug_file = "/tmp/appstore_search_debug.html"
                try:
                    with open(debug_file, "w", encoding="utf-8") as f:
                        f.write(html_content)
                    logger.info(f"已保存 HTML 到: {debug_file}")
                except Exception as e:
                    logger.warning(f"无法保存调试 HTML: {e}")

                # 提取应用链接
                results = []
                seen_ids = set()

                # 查找所有应用链接（格式：/us/app/{name}/id{number}）
                app_links = soup.select('a[href*="/app/"]')
                logger.info(f"找到 {len(app_links)} 个包含 /app/ 的链接")

                # 调试：如果没找到，尝试查看所有链接
                if not app_links:
                    all_links = soup.find_all("a", href=True)
                    logger.info(f"HTML 中共有 {len(all_links)} 个链接")
                    # 显示前 10 个链接作为样本
                    for i, link in enumerate(all_links[:10]):
                        logger.info(f"  样本链接 {i+1}: {link.get('href')[:100]}")

                for link in app_links:
                    href = link.get("href", "")

                    # 提取 App ID（匹配 /app/{name}/id{number} 或 /app/id{number} 格式）
                    match = re.search(r"/app/[^/]+/id(\d+)", href)
                    if not match:
                        # 尝试备用格式 /app/id{number}
                        match = re.search(r"/app/id(\d+)", href)
                        if not match:
                            continue

                    app_id = match.group(1)

                    # 去重
                    if app_id in seen_ids:
                        continue
                    seen_ids.add(app_id)

                    # 提取应用名称
                    # 优先从 aria-label 获取（格式: "View AppName"）
                    aria_label = link.get("aria-label", "")
                    if aria_label.startswith("View "):
                        app_name = aria_label[5:]  # 去掉 "View " 前缀
                    else:
                        # 备用: 从 h3 标签获取（不依赖 Svelte 类名）
                        h3_tag = link.find("h3")
                        if h3_tag:
                            app_name = h3_tag.get_text(strip=True)
                        else:
                            app_name = f"App {app_id}"

                    # 构建完整 URL
                    full_url = (
                        f"https://apps.apple.com{href}"
                        if href.startswith("/")
                        else href
                    )

                    # 构建结果（模拟 iTunes API 格式）
                    results.append(
                        {
                            "trackId": int(app_id),
                            "trackName": app_name,
                            "kind": "software",
                            "artistName": "",  # 网页搜索无法直接获取开发者
                            "trackViewUrl": full_url,
                            "source": "web_search",  # 标记数据来源
                        }
                    )

                    # 达到限制数量就停止
                    if len(results) >= limit:
                        break

                logger.info(f"网页搜索完成: 找到 {len(results)} 个应用")

                return {
                    "results": results,
                    "query": query,
                    "country": country,
                    "platform": platform,
                    "source": "web_search",
                }

        except Exception as e:
            logger.error(f"网页搜索失败: {e}")
            return {
                "results": [],
                "query": query,
                "country": country,
                "platform": platform,
                "source": "web_search",
                "error": str(e),
            }
