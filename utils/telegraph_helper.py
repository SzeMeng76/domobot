"""
Telegraph 发布辅助工具
用于将长图文内容发布到 Telegraph
"""

import logging
from typing import Optional
import httpx

logger = logging.getLogger(__name__)


class TelegraphPublisher:
    """Telegraph 发布器"""

    def __init__(self, access_token: Optional[str] = None, author_name: str = "DomoBot"):
        """
        初始化 Telegraph 发布器

        Args:
            access_token: Telegraph 访问令牌（留空则自动创建）
            author_name: 作者名称
        """
        self.access_token = access_token
        self.author_name = author_name
        self.api_url = "https://api.telegra.ph"

    async def ensure_account(self) -> bool:
        """确保有有效的账户，如果没有则创建"""
        if self.access_token:
            return True

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.api_url}/createAccount",
                    json={
                        "short_name": self.author_name,
                        "author_name": self.author_name,
                    }
                )
                response.raise_for_status()

                result = response.json()
                if result.get("ok"):
                    self.access_token = result["result"]["access_token"]
                    logger.info(f"✅ Telegraph账户创建成功")
                    return True
                else:
                    logger.error(f"创建Telegraph账户失败: {result}")
                    return False

        except Exception as e:
            logger.error(f"创建Telegraph账户失败: {e}")
            return False

    def _html_to_nodes(self, html_content: str) -> list:
        """
        将HTML转换为Telegraph Node格式

        Telegraph API需要Node数组，不是纯HTML字符串
        简单实现：将HTML包装成一个<p>标签的Node
        """
        # 替换换行符为<br>标签
        html_content = html_content.replace('\n', '<br>')

        # 返回Node数组格式
        return [{"tag": "p", "children": [html_content]}]

    async def create_page(
        self,
        title: str,
        content: str,
        author_name: Optional[str] = None,
        author_url: Optional[str] = None
    ) -> Optional[str]:
        """
        创建 Telegraph 页面

        Args:
            title: 页面标题
            content: 页面内容（HTML格式或纯文本）
            author_name: 作者名称
            author_url: 作者链接

        Returns:
            页面URL，失败返回None
        """
        # 确保有账户
        if not await self.ensure_account():
            return None

        try:
            # 将HTML转换为Telegraph Node格式
            content_nodes = self._html_to_nodes(content)

            async with httpx.AsyncClient(timeout=30.0) as client:
                data = {
                    "access_token": self.access_token,
                    "title": title,
                    "content": content_nodes,  # 使用Node数组
                    "author_name": author_name or self.author_name,
                    "return_content": False
                }

                if author_url:
                    data["author_url"] = author_url

                response = await client.post(
                    f"{self.api_url}/createPage",
                    json=data
                )
                response.raise_for_status()

                result = response.json()
                if result.get("ok"):
                    url = result["result"]["url"]
                    logger.info(f"✅ Telegraph页面创建成功: {url}")
                    return url
                else:
                    logger.error(f"创建Telegraph页面失败: {result}")
                    return None

        except Exception as e:
            logger.error(f"创建Telegraph页面失败: {e}")
            return None


async def publish_to_telegraph(
    title: str,
    content: str,
    author_name: str = "DomoBot",
    access_token: Optional[str] = None
) -> Optional[str]:
    """
    便捷函数：发布内容到 Telegraph

    Args:
        title: 标题
        content: 内容（HTML格式）
        author_name: 作者名称
        access_token: 访问令牌（可选）

    Returns:
        页面URL，失败返回None
    """
    publisher = TelegraphPublisher(access_token, author_name)
    return await publisher.create_page(title, content)
