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

    def __init__(self, api_id: int, api_hash: str, bot_token: str, workdir: str = "sessions"):
        """
        初始化 Pyrogram 客户端

        Args:
            api_id: Telegram API ID (从 https://my.telegram.org 获取)
            api_hash: Telegram API Hash
            bot_token: Bot Token (与 python-telegram-bot 共用)
            workdir: session文件存储目录（默认sessions/，参考parse_hub_bot）
        """
        from pathlib import Path

        self.api_id = api_id
        self.api_hash = api_hash
        self.bot_token = bot_token
        self.client = None
        self.is_started = False

        # 创建session目录
        self.workdir = Path(workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)

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
                workdir=str(self.workdir),  # 保存session到目录（参考parse_hub_bot）
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
        获取用户完整信息（包括 DC ID、Bio、安全标志、在线状态）

        Args:
            user_id: Telegram 用户 ID

        Returns:
            用户信息字典，包含:
            - user_id: 用户 ID
            - dc_id: DC ID (可能为 None)
            - username: 用户名 (可能为 None)
            - first_name: 名字
            - last_name: 姓氏 (可能为 None)
            - is_premium: 是否为 Premium 用户
            - is_verified: 是否为认证账号（蓝V）
            - is_scam: 是否被标记为诈骗账号
            - is_fake: 是否被标记为虚假账号
            - is_frozen: 是否被冻结
            - bio: 个人简介 (可能为 None)
            - status: 在线状态 (可能为 None)
        """
        if not self.is_started or not self.client:
            logger.warning("Pyrogram client not started, cannot get user info")
            return None

        try:
            # 第一次调用：获取基本用户信息
            user = await self.client.get_users(user_id)

            # 第二次调用：获取完整信息（包括 bio）
            bio = None
            try:
                full_user = await self.client.get_chat(user_id)
                bio = getattr(full_user, 'bio', None)
            except Exception as e:
                logger.debug(f"Failed to get full user info (bio): {e}")

            user_info = {
                "user_id": user.id,
                "dc_id": getattr(user, "dc_id", None),
                "username": user.username,
                "first_name": user.first_name or "",
                "last_name": user.last_name or "",
                "is_premium": getattr(user, "is_premium", False),
                "is_verified": getattr(user, "is_verified", False),
                "is_scam": getattr(user, "is_scam", False),
                "is_fake": getattr(user, "is_fake", False),
                "is_frozen": getattr(user, "is_frozen", False),
                "bio": bio,
                "status": getattr(user, "status", None),
            }

            return user_info

        except Exception as e:
            logger.error(f"Failed to get user info for {user_id}: {e}")
            return None

    async def get_user_info_by_username(self, username: str) -> Optional[dict]:
        """
        通过用户名直接从 Telegram 获取用户信息（不依赖缓存）

        Args:
            username: 用户名（可以带或不带@符号）

        Returns:
            用户信息字典，包含:
            - user_id: 用户 ID
            - dc_id: DC ID (可能为 None)
            - username: 用户名 (可能为 None)
            - first_name: 名字
            - last_name: 姓氏 (可能为 None)
            - is_premium: 是否为 Premium 用户
            - is_verified: 是否为认证账号（蓝V）
            - is_scam: 是否被标记为诈骗账号
            - is_fake: 是否被标记为虚假账号
            - is_frozen: 是否被冻结
            - bio: 个人简介 (可能为 None)
            - status: 在线状态 (可能为 None)

        Note:
            - 使用 Pyrogram MTProto API 直接从 Telegram 服务器查询
            - 不依赖本地缓存，实时获取最新用户信息
            - 支持公开用户名的查询
        """
        if not self.is_started or not self.client:
            logger.warning("Pyrogram client not started, cannot get user info by username")
            return None

        try:
            # 移除可能的@符号
            clean_username = username.lstrip("@")

            # 第一次调用：获取基本用户信息
            user = await self.client.get_users(clean_username)

            # 第二次调用：获取完整信息（包括 bio）
            bio = None
            try:
                full_user = await self.client.get_chat(clean_username)
                bio = getattr(full_user, 'bio', None)
            except Exception as e:
                logger.debug(f"Failed to get full user info (bio) for @{clean_username}: {e}")

            user_info = {
                "user_id": user.id,
                "dc_id": getattr(user, "dc_id", None),
                "username": user.username,
                "first_name": user.first_name or "",
                "last_name": user.last_name or "",
                "is_premium": getattr(user, "is_premium", False),
                "is_verified": getattr(user, "is_verified", False),
                "is_scam": getattr(user, "is_scam", False),
                "is_fake": getattr(user, "is_fake", False),
                "is_frozen": getattr(user, "is_frozen", False),
                "bio": bio,
                "status": getattr(user, "status", None),
            }

            logger.info(f"✅ Successfully fetched user info for @{clean_username} via Pyrogram")
            return user_info

        except Exception as e:
            logger.debug(f"Failed to get user info by username @{username}: {e}")
            return None

    async def get_chat_info(self, chat_id) -> Optional[dict]:
        """
        获取群组/频道完整信息

        Args:
            chat_id: 群组/频道 ID 或用户名

        Returns:
            群组信息字典，包含:
            - chat_id: 群组 ID
            - type: 类型 (group/supergroup/channel)
            - title: 群组名称
            - username: 用户名 (可能为 None)
            - description: 简介 (可能为 None)
            - dc_id: DC ID (可能为 None)
            - members_count: 成员数 (可能为 None)
            - is_verified: 是否为认证群组
            - is_scam: 是否被标记为诈骗
            - is_fake: 是否被标记为虚假
            - is_restricted: 是否受限
            - is_frozen: 是否被冻结
            - join_link: 加入链接
        """
        if not self.is_started or not self.client:
            logger.warning("Pyrogram client not started, cannot get chat info")
            return None

        try:
            from pyrogram.enums import ChatType

            chat = await self.client.get_chat(chat_id)

            # 映射聊天类型
            chat_type_map = {
                ChatType.SUPERGROUP: "超级群组",
                ChatType.GROUP: "群组",
                ChatType.CHANNEL: "频道"
            }
            chat_type = chat_type_map.get(chat.type, "未知")

            # 生成加入链接
            if chat.username:
                # 公开群组/频道：使用用户名链接
                join_link = f"https://t.me/{chat.username}"
            else:
                # 私有群组/频道：需要通过邀请链接加入
                # 尝试获取邀请链接（需要管理员权限）
                try:
                    invite_link = await self.client.export_chat_invite_link(chat.id)
                    join_link = invite_link
                except Exception:
                    # 如果无法获取邀请链接，返回 None
                    join_link = None

            chat_info = {
                "chat_id": chat.id,
                "type": chat_type,
                "title": getattr(chat, 'title', None),
                "username": getattr(chat, 'username', None),
                "description": getattr(chat, 'description', None),
                "dc_id": getattr(chat, 'dc_id', None),
                "members_count": getattr(chat, 'members_count', None),
                "is_verified": getattr(chat, 'is_verified', False),
                "is_scam": getattr(chat, 'is_scam', False),
                "is_fake": getattr(chat, 'is_fake', False),
                "is_restricted": getattr(chat, 'is_restricted', False),
                "is_frozen": getattr(chat, 'is_frozen', False),
                "join_link": join_link,
            }

            logger.info(f"✅ Successfully fetched chat info for {chat_id}")
            return chat_info

        except Exception as e:
            logger.debug(f"Failed to get chat info for {chat_id}: {e}")
            return None

    async def send_large_video(
        self,
        chat_id: int,
        video_path: str,
        caption: str = "",
        reply_to_message_id: Optional[int] = None,
        width: int = 0,
        height: int = 0,
        duration: int = 0,
        thumb: Optional[str] = None,
        progress_callback = None,
        reply_markup = None,
        parse_mode: Optional[str] = None
    ):
        """
        使用 Pyrogram 发送大视频文件（支持最大2GB）

        适用场景：
        - 视频大小 > 50MB（python-telegram-bot限制）
        - 视频大小 ≤ 2GB（Pyrogram MTProto API限制）

        Args:
            chat_id: 聊天ID
            video_path: 视频文件路径
            caption: 视频说明文字
            reply_to_message_id: 回复的消息ID
            width: 视频宽度
            height: 视频高度
            duration: 视频时长（秒）
            thumb: 缩略图路径
            progress_callback: 上传进度回调函数
            reply_markup: InlineKeyboardMarkup 按钮
            parse_mode: 解析模式 (MarkdownV2, Markdown, HTML)

        Returns:
            发送的消息对象

        Note:
            使用 MTProto API 直连 Telegram，突破 Bot API 的 50MB 限制
        """
        if not self.is_started or not self.client:
            raise RuntimeError("Pyrogram client not started")

        try:
            logger.info(f"📤 使用 Pyrogram 上传大文件: {video_path}")

            # 处理缩略图：Pyrogram只接受本地文件路径，不接受URL
            # 如果thumb是URL，忽略它（让Pyrogram自动生成缩略图）
            thumb_path = None
            if thumb:
                # 检查是否是本地文件路径（不是URL）
                if not thumb.startswith(('http://', 'https://')):
                    from pathlib import Path
                    if Path(thumb).exists():
                        thumb_path = thumb
                    else:
                        logger.debug(f"缩略图路径不存在，忽略: {thumb}")
                else:
                    logger.debug(f"缩略图是URL，忽略（Pyrogram不支持URL）: {thumb}")

            # 转换reply_markup: python-telegram-bot → Pyrogram格式
            pyrogram_reply_markup = None
            if reply_markup:
                from pyrogram.types import InlineKeyboardMarkup as PyrogramInlineKeyboardMarkup
                from pyrogram.types import InlineKeyboardButton as PyrogramInlineKeyboardButton

                # 转换按钮格式
                keyboard = []
                for row in reply_markup.inline_keyboard:
                    button_row = []
                    for button in row:
                        if button.url:
                            button_row.append(PyrogramInlineKeyboardButton(button.text, url=button.url))
                        elif button.callback_data:
                            button_row.append(PyrogramInlineKeyboardButton(button.text, callback_data=button.callback_data))
                    if button_row:
                        keyboard.append(button_row)

                if keyboard:
                    pyrogram_reply_markup = PyrogramInlineKeyboardMarkup(keyboard)

            # 转换parse_mode: MarkdownV2 → markdown (Pyrogram不支持MarkdownV2)
            from pyrogram import enums

            pyrogram_parse_mode = None
            if parse_mode:
                if parse_mode.lower() == "markdownv2":
                    # MarkdownV2 → markdown: 需要移除转义符
                    caption = caption.replace(r'\|', '|').replace(r'\[', '[').replace(r'\]', ']').replace(r'\(', '(').replace(r'\)', ')').replace(r'\.', '.').replace(r'\-', '-').replace(r'\+', '+').replace(r'\=', '=').replace(r'\{', '{').replace(r'\}', '}').replace(r'\!', '!').replace(r'\#', '#')
                    pyrogram_parse_mode = enums.ParseMode.MARKDOWN
                elif parse_mode.lower() == "markdown":
                    pyrogram_parse_mode = enums.ParseMode.MARKDOWN
                elif parse_mode.lower() == "html":
                    pyrogram_parse_mode = enums.ParseMode.HTML

            message = await self.client.send_video(
                chat_id=chat_id,
                video=video_path,
                caption=caption,
                reply_to_message_id=reply_to_message_id,
                width=width,
                height=height,
                duration=duration,
                thumb=thumb_path,  # 使用处理后的缩略图路径
                supports_streaming=True,
                progress=progress_callback,
                reply_markup=pyrogram_reply_markup,
                parse_mode=pyrogram_parse_mode
            )

            logger.info(f"✅ 大文件上传成功: {video_path}")
            return message

        except Exception as e:
            logger.error(f"❌ Pyrogram上传失败: {e}")
            raise

    async def send_large_photo(
        self,
        chat_id: int,
        photo_path: str,
        caption: str = "",
        reply_to_message_id: Optional[int] = None
    ):
        """
        使用 Pyrogram 发送大图片文件

        Args:
            chat_id: 聊天ID
            photo_path: 图片文件路径
            caption: 图片说明文字
            reply_to_message_id: 回复的消息ID

        Returns:
            发送的消息对象
        """
        if not self.is_started or not self.client:
            raise RuntimeError("Pyrogram client not started")

        try:
            logger.info(f"📤 使用 Pyrogram 上传图片: {photo_path}")

            message = await self.client.send_photo(
                chat_id=chat_id,
                photo=photo_path,
                caption=caption,
                reply_to_message_id=reply_to_message_id
            )

            logger.info(f"✅ 图片上传成功: {photo_path}")
            return message

        except Exception as e:
            logger.error(f"❌ Pyrogram上传图片失败: {e}")
            raise
