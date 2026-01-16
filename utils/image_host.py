"""
图床上传工具
支持 Catbox、Litterbox、Zio.ooo 等图床
用于上传大文件，解决Telegram文件大小限制
"""

import logging
import asyncio
from pathlib import Path
from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_fixed

logger = logging.getLogger(__name__)


class ImageHostUploader:
    """图床上传器"""

    def __init__(self, service: str = "catbox", proxy: Optional[str] = None, **kwargs):
        """
        初始化上传器

        Args:
            service: 图床服务名称 (catbox, litterbox, zioooo)
            proxy: 代理地址
            **kwargs: 额外配置 (如 catbox_userhash, zioooo_storage_id)
        """
        self.service = service.lower()
        self.proxy = proxy
        self.config = kwargs
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    @property
    def client(self) -> httpx.AsyncClient:
        """获取HTTP客户端"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                proxy=self.proxy,
                timeout=120.0,  # 上传大文件需要更长超时
                follow_redirects=True
            )
        return self._client

    async def close(self):
        """关闭客户端"""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def upload(self, file_path: str | Path) -> Optional[str]:
        """
        上传文件到图床

        Args:
            file_path: 文件路径

        Returns:
            上传成功返回URL，失败返回None
        """
        file_path = Path(file_path)
        if not file_path.exists():
            logger.error(f"文件不存在: {file_path}")
            return None

        try:
            if self.service == "catbox":
                return await self._upload_catbox(file_path)
            elif self.service == "litterbox":
                return await self._upload_litterbox(file_path)
            elif self.service == "zioooo":
                return await self._upload_zioooo(file_path)
            else:
                logger.error(f"不支持的图床服务: {self.service}")
                return None
        except Exception as e:
            logger.error(f"上传到 {self.service} 失败: {e}")
            return None

    @retry(stop=stop_after_attempt(2), wait=wait_fixed(2))
    async def _upload_catbox(self, file_path: Path) -> Optional[str]:
        """上传到 Catbox.moe (永久存储)"""
        api_url = "https://catbox.moe/user/api.php"

        with open(file_path, 'rb') as f:
            data = {
                "reqtype": "fileupload",
                "userhash": self.config.get("catbox_userhash", ""),
            }
            files = {"fileToUpload": f}

            response = await self.client.post(api_url, data=data, files=files)
            response.raise_for_status()

            url = response.text.strip()
            logger.info(f"✅ Catbox上传成功: {url}")
            return url

    @retry(stop=stop_after_attempt(2), wait=wait_fixed(2))
    async def _upload_litterbox(self, file_path: Path) -> Optional[str]:
        """上传到 Litterbox (72小时临时存储)"""
        api_url = "https://litterbox.catbox.moe/resources/internals/api.php"

        with open(file_path, 'rb') as f:
            data = {
                "reqtype": "fileupload",
                "time": "72h",  # 72小时后自动删除
            }
            files = {"fileToUpload": f}

            response = await self.client.post(api_url, data=data, files=files)
            response.raise_for_status()

            url = response.text.strip()
            logger.info(f"✅ Litterbox上传成功 (72h): {url}")
            return url

    @retry(stop=stop_after_attempt(2), wait=wait_fixed(2))
    async def _upload_zioooo(self, file_path: Path) -> Optional[str]:
        """上传到 Zio.ooo"""
        api_url = "https://img.zio.ooo/api/v2"

        # 获取存储ID
        storage_id = self.config.get("zioooo_storage_id")
        if not storage_id:
            # 自动获取第一个存储
            group_response = await self.client.get(f"{api_url}/group")
            group_response.raise_for_status()
            storages = group_response.json()["data"]["storages"]
            if not storages:
                raise Exception("Zio.ooo: 没有可用的存储")
            storage_id = storages[0]["id"]

        # 上传文件
        with open(file_path, 'rb') as f:
            data = {"storage_id": storage_id}
            files = {"file": f}

            response = await self.client.post(f"{api_url}/upload", data=data, files=files)
            response.raise_for_status()

            result = response.json()
            if result["status"] != "success":
                raise Exception(f"Zio.ooo上传失败: {result.get('message', '未知错误')}")

            url = result["data"]["public_url"]
            logger.info(f"✅ Zio.ooo上传成功: {url}")
            return url


async def upload_to_host(
    file_path: str | Path,
    service: str = "catbox",
    proxy: Optional[str] = None,
    **kwargs
) -> Optional[str]:
    """
    便捷函数：上传文件到图床

    Args:
        file_path: 文件路径
        service: 图床服务 (catbox, litterbox, zioooo)
        proxy: 代理地址
        **kwargs: 额外配置

    Returns:
        上传成功返回URL，失败返回None
    """
    async with ImageHostUploader(service, proxy, **kwargs) as uploader:
        return await uploader.upload(file_path)
