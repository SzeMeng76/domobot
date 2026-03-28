#!/usr/bin/env python3
"""
FlareSolverr 客户端 - 用于绕过 Cloudflare 验证
"""
import logging
import requests
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class FlareSolverrClient:
    """FlareSolverr 客户端"""

    def __init__(self, base_url: str = "http://flaresolverr:8191"):
        """
        初始化 FlareSolverr 客户端

        Args:
            base_url: FlareSolverr 服务地址，Docker 环境中使用服务名 "flaresolverr"
        """
        self.base_url = base_url
        self.endpoint = f"{base_url}/v1"

    def get(self, url: str, max_timeout: int = 60000, **kwargs) -> Optional[Dict[str, Any]]:
        """
        通过 FlareSolverr 获取页面内容

        Args:
            url: 目标 URL
            max_timeout: 最大超时时间（毫秒），默认 60 秒
            **kwargs: 其他参数
                - session: 会话 ID
                - cookies: Cookie 列表
                - proxy: 代理配置
                - returnOnlyCookies: 只返回 cookies
                - disableMedia: 禁用媒体资源加载

        Returns:
            包含响应数据的字典，失败返回 None
        """
        payload = {
            "cmd": "request.get",
            "url": url,
            "maxTimeout": max_timeout,
            **kwargs
        }

        try:
            logger.debug(f"FlareSolverr 请求: {url}")
            response = requests.post(
                self.endpoint,
                json=payload,
                timeout=max_timeout / 1000 + 10  # 额外 10 秒缓冲
            )
            response.raise_for_status()
            result = response.json()

            if result.get("status") == "ok":
                solution = result.get("solution", {})
                logger.debug(f"FlareSolverr 成功: {url}")
                return {
                    "html": solution.get("response", ""),
                    "cookies": solution.get("cookies", []),
                    "user_agent": solution.get("userAgent", ""),
                    "url": solution.get("url", url)
                }
            else:
                error_msg = result.get("message", "Unknown error")
                logger.error(f"FlareSolverr 错误: {error_msg}")
                return None

        except requests.exceptions.ConnectionError:
            logger.error(f"无法连接到 FlareSolverr ({self.base_url})")
            return None
        except Exception as e:
            logger.error(f"FlareSolverr 请求失败: {e}", exc_info=True)
            return None

    def create_session(self, session_id: Optional[str] = None, proxy: Optional[Dict] = None) -> Optional[str]:
        """
        创建持久会话

        Args:
            session_id: 可选的会话 ID，不指定则自动生成
            proxy: 代理配置

        Returns:
            会话 ID，失败返回 None
        """
        payload = {
            "cmd": "sessions.create"
        }
        if session_id:
            payload["session"] = session_id
        if proxy:
            payload["proxy"] = proxy

        try:
            response = requests.post(self.endpoint, json=payload, timeout=30)
            response.raise_for_status()
            result = response.json()

            if result.get("status") == "ok":
                session = result.get("session")
                logger.info(f"FlareSolverr 会话创建成功: {session}")
                return session
            else:
                logger.error(f"创建会话失败: {result.get('message')}")
                return None

        except Exception as e:
            logger.error(f"创建会话异常: {e}", exc_info=True)
            return None

    def destroy_session(self, session_id: str) -> bool:
        """
        销毁会话

        Args:
            session_id: 会话 ID

        Returns:
            是否成功
        """
        payload = {
            "cmd": "sessions.destroy",
            "session": session_id
        }

        try:
            response = requests.post(self.endpoint, json=payload, timeout=30)
            response.raise_for_status()
            result = response.json()

            if result.get("status") == "ok":
                logger.info(f"FlareSolverr 会话销毁成功: {session_id}")
                return True
            else:
                logger.error(f"销毁会话失败: {result.get('message')}")
                return False

        except Exception as e:
            logger.error(f"销毁会话异常: {e}", exc_info=True)
            return False


# 全局实例
_flaresolverr_client: Optional[FlareSolverrClient] = None


def get_flaresolverr_client() -> FlareSolverrClient:
    """获取全局 FlareSolverr 客户端实例"""
    global _flaresolverr_client
    if _flaresolverr_client is None:
        _flaresolverr_client = FlareSolverrClient()
    return _flaresolverr_client
