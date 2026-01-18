"""
Pyrogram 客户端封装
用于获取用户 DC ID（数据中心 ID）
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class PyrogramHelper:
    """
    Pyrogram 辅助类
    仅用于查询用户 DC ID，不处理消息
    """

    def __init__(self, api_id: int, api_hash: str, bot_token: str):
        """
        初始化 Pyrogram 客户端

        Args:
            api_id: Telegram API ID (从 https://my.telegram.org 获取)
            api_hash: Telegram API Hash
            bot_token: Bot Token (与 python-telegram-bot 共用)
        """
        self.api_id = api_id
        self.api_hash = api_hash
        self.bot_token = bot_token
        self.client = None
        self.is_started = False

    async def start(self):
        """启动 Pyrogram 客户端"""
        if self.is_started:
            logger.debug("Pyrogram client already started")
            return

        try:
            from pyrogram import Client

            self.client = Client(
                name="dc_checker_bot",
                api_id=self.api_id,
                api_hash=self.api_hash,
                bot_token=self.bot_token,
                in_memory=True,  # 不保存会话到文件
            )

            await self.client.start()
            self.is_started = True
            logger.info("✅ Pyrogram client started for DC ID checking")

        except ImportError:
            logger.error("❌ Pyrogram not installed. Please run: pip install pyrogram tgcrypto")
            raise
        except Exception as e:
            logger.error(f"❌ Failed to start Pyrogram client: {e}")
            raise

    async def stop(self):
        """停止 Pyrogram 客户端"""
        if not self.is_started or not self.client:
            return

        try:
            await self.client.stop()
            self.is_started = False
            logger.info("Pyrogram client stopped")
        except Exception as e:
            logger.error(f"Failed to stop Pyrogram client: {e}")

    async def get_user_dc_id(self, user_id: int) -> Optional[int]:
        """
        获取用户的 DC ID

        Args:
            user_id: Telegram 用户 ID

        Returns:
            DC ID (1-5) 或 None

        注意:
            - DC ID 仅在用户有公开头像时可用
            - 返回 None 表示无法获取（无头像或隐私设置）
        """
        if not self.is_started or not self.client:
            logger.warning("Pyrogram client not started, cannot get DC ID")
            return None

        try:
            user = await self.client.get_users(user_id)

            # dc_id 仅在用户有公开头像时可用
            dc_id = getattr(user, "dc_id", None)

            if dc_id:
                logger.debug(f"User {user_id} is from DC{dc_id}")
                return dc_id
            else:
                logger.debug(f"User {user_id} has no dc_id (likely no profile photo)")
                return None

        except Exception as e:
            logger.debug(f"Failed to get DC ID for user {user_id}: {e}")
            return None

    async def get_user_info(self, user_id: int) -> Optional[dict]:
        """
        获取用户完整信息（包括 DC ID）

        Args:
            user_id: Telegram 用户 ID

        Returns:
            用户信息字典，包含:
            - dc_id: DC ID (可能为 None)
            - username: 用户名 (可能为 None)
            - first_name: 名字
            - last_name: 姓氏 (可能为 None)
            - is_premium: 是否为 Premium 用户
        """
        if not self.is_started or not self.client:
            logger.warning("Pyrogram client not started, cannot get user info")
            return None

        try:
            user = await self.client.get_users(user_id)

            user_info = {
                "dc_id": getattr(user, "dc_id", None),
                "username": user.username,
                "first_name": user.first_name or "",
                "last_name": user.last_name or "",
                "is_premium": getattr(user, "is_premium", False),
            }

            return user_info

        except Exception as e:
            logger.error(f"Failed to get user info for {user_id}: {e}")
            return None
