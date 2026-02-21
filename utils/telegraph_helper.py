"""
Telegraph 发布辅助工具
用于将长图文内容发布到 Telegraph
"""

import re
import logging
from typing import Optional
from telegraph.aio import Telegraph

logger = logging.getLogger(__name__)


def _sanitize_html_for_telegraph(html: str) -> str:
    """将 HTML 中 Telegraph 不支持的标签替换为允许的标签

    Telegraph 允许: a, aside, b, blockquote, br, code, em, figcaption,
    figure, h3, h4, hr, i, img, li, ol, p, pre, s, strong, u, ul
    """
    # h1/h2 → h3
    html = re.sub(r'<(/?)h[12](\s|>)', r'<\1h3\2', html)
    # h5/h6 → h4
    html = re.sub(r'<(/?)h[56](\s|>)', r'<\1h4\2', html)
    # div/section/article/span → p
    html = re.sub(r'<(/?)(?:div|section|article)(\s|>)', r'<\1p\2', html)
    html = re.sub(r'<(/?)span(\s|>)', r'<\1em\2', html)
    return html


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
        self.telegraph = Telegraph(access_token=access_token)

    async def ensure_account(self) -> bool:
        """确保有有效的账户，如果没有则创建"""
        # 如果已有token，先验证是否有效
        if self.access_token:
            try:
                account_info = await self.telegraph.get_account_info(["short_name"])
                if account_info:
                    logger.debug("✅ Telegraph token有效")
                    return True
            except Exception as e:
                logger.warning(f"Telegraph token无效: {e}，将创建新账户")
                self.access_token = None
                self.telegraph = Telegraph(access_token=None)

        try:
            account = await self.telegraph.create_account(
                short_name=self.author_name,
                author_name=self.author_name
            )
            self.access_token = self.telegraph.get_access_token()
            logger.info(f"✅ Telegraph账户创建成功")
            return True

        except Exception as e:
            logger.error(f"创建Telegraph账户失败: {e}")
            return False

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
            # 清理不支持的 HTML 标签
            content = _sanitize_html_for_telegraph(content)
            # 使用telegraph库的create_page，自动处理html_content转换
            response = await self.telegraph.create_page(
                title=title,
                html_content=content,
                author_name=author_name or self.author_name,
                author_url=author_url
            )

            url = response["url"]
            logger.info(f"✅ Telegraph页面创建成功: {url}")
            return url

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
