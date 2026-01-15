"""
AI反垃圾消息处理器
处理群组消息并进行垃圾检测
"""
import logging
import asyncio
from telegram import Update, ChatMember
from telegram.ext import ContextTypes
from telegram.constants import ChatMemberStatus

logger = logging.getLogger(__name__)


class AntiSpamHandler:
    """反垃圾消息处理器"""

    def __init__(self, spam_manager, spam_detector):
        """
        初始化处理器

        Args:
            spam_manager: AntiSpamManager实例
            spam_detector: AntiSpamDetector实例
        """
        self.manager = spam_manager
        self.detector = spam_detector
        logger.info("AntiSpamHandler initialized")

    async def is_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """检查用户是否为管理员"""
        try:
            user_id = update.effective_user.id
            chat_id = update.effective_chat.id
            member = await context.bot.get_chat_member(chat_id, user_id)
            return member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
        except Exception as e:
            logger.error(f"Failed to check admin status: {e}")
            return False

    async def handle_new_member(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理新成员加入"""
        try:
            for member in update.message.new_chat_members:
                if member.is_bot:
                    continue

                user_id = member.id
                group_id = update.effective_chat.id
                username = member.username
                first_name = member.first_name

                # 创建用户记录
                await self.manager.get_or_create_user_info(
                    user_id, group_id, username, first_name
                )
                logger.info(f"New member {user_id} joined group {group_id}")

        except Exception as e:
            logger.error(f"Failed to handle new member: {e}")

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理群组消息"""
        try:
            # 基本检查
            if not update.effective_chat or not update.effective_user:
                return

            group_id = update.effective_chat.id
            user_id = update.effective_user.id

            # 检查群组是否启用反垃圾功能
            if not await self.manager.is_group_enabled(group_id):
                return

            # 跳过管理员消息
            if await self.is_admin(update, context):
                return

            # 获取或创建用户信息
            user_info = await self.manager.get_or_create_user_info(
                user_id, group_id,
                update.effective_user.username,
                update.effective_user.first_name
            )

            # 增加发言次数
            await self.manager.increment_speech_count(user_id, group_id)

            # 获取群组配置
            config = await self.manager.get_group_config(group_id)
            if not config:
                return

            # 判断是否需要检测
            if not await self.manager.should_check_user(user_info, config):
                return

            # 异步执行检测
            asyncio.create_task(self._detect_and_process(update, context, user_info, config))

        except Exception as e:
            logger.error(f"Failed to handle message: {e}")

    async def _detect_and_process(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                                  user_info: dict, config: dict):
        """执行检测并处理结果"""
        try:
            message = update.message
            user_id = update.effective_user.id
            group_id = update.effective_chat.id
            username = update.effective_user.username or update.effective_user.first_name

            # 确定消息类型和内容
            message_type = None
            message_text = None
            detection_result = None
            detection_time_ms = 0

            # 文本消息检测
            if message.text and config.get('check_text', True):
                message_type = 'text'
                message_text = message.text
                detection_result, detection_time_ms = await self.detector.detect_text(
                    message_text, user_info
                )

            # 图片消息检测
            elif message.photo and config.get('check_photo', True):
                message_type = 'photo'
                # 获取最大尺寸的图片
                photo = message.photo[-1]
                photo_file = await context.bot.get_file(photo.file_id)
                photo_url = photo_file.file_path
                caption = message.caption or ''
                message_text = f"[图片] {caption}"

                detection_result, detection_time_ms = await self.detector.detect_photo(
                    photo_url, user_info, caption
                )

            # 检测失败
            if not detection_result:
                logger.error("Detection failed, skipping")
                return

            # 记录日志
            await self.manager.log_detection(
                user_id, group_id, username, message_type, message_text or '',
                detection_result.spam_score, detection_result.spam_reason,
                detection_result.spam_mock_text, detection_result.is_spam,
                detection_result.is_spam, detection_time_ms
            )

            # 更新统计
            await self.manager.update_stats(
                group_id,
                spam_detected=detection_result.is_spam,
                user_banned=detection_result.is_spam
            )

            # 如果不是垃圾，标记用户已验证
            if not detection_result.is_spam:
                await self.manager.mark_user_verified(user_id, group_id)
                logger.info(f"User {user_id} passed verification")
                return

            # 是垃圾，执行处理
            spam_score = detection_result.spam_score
            threshold = config.get('spam_score_threshold', 80)

            if spam_score >= threshold:
                # 删除原始消息
                message_deleted = False
                try:
                    await message.delete()
                    message_deleted = True
                    logger.info(f"Deleted spam message from user {user_id} in group {group_id}")
                except Exception as e:
                    logger.error(f"Failed to delete message: {e}")

                # 尝试封禁用户
                user_banned = False
                ban_error_msg = None
                try:
                    await context.bot.ban_chat_member(group_id, user_id)
                    user_banned = True
                    logger.info(f"Banned user {user_id} in group {group_id}")
                except Exception as e:
                    ban_error_msg = str(e)
                    logger.warning(f"Failed to ban user {user_id}: {e} (bot may lack ban permission)")

                # 发送通知消息
                if user_banned:
                    notification_text = (
                        f"🚫 检测到垃圾广告并已封禁\n\n"
                        f"👤 用户: {username}\n"
                        f"📊 垃圾分数: {spam_score}/100\n"
                        f"📝 原因: {detection_result.spam_reason}\n"
                        f"💬 评论: {detection_result.spam_mock_text}\n"
                        f"⏱️ 检测耗时: {detection_time_ms}ms"
                    )
                elif message_deleted:
                    notification_text = (
                        f"⚠️ 检测到垃圾广告，已删除消息\n\n"
                        f"👤 用户: {username}\n"
                        f"📊 垃圾分数: {spam_score}/100\n"
                        f"📝 原因: {detection_result.spam_reason}\n"
                        f"💬 评论: {detection_result.spam_mock_text}\n"
                        f"⏱️ 检测耗时: {detection_time_ms}ms\n\n"
                        f"❌ 无法封禁用户（可能缺少封禁权限）\n"
                        f"💡 请给予机器人封禁权限以完整保护群组"
                    )
                else:
                    # 既无法删除消息也无法封禁，只记录日志不发通知
                    logger.error(f"Failed to take any action against spam from user {user_id}")
                    return

                # 创建按钮（只在成功封禁时显示解禁按钮）
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                reply_markup = None
                if user_banned:
                    keyboard = [[
                        InlineKeyboardButton(
                            "✅ 解禁此用户",
                            callback_data=f"antispam_unban:{user_id}"
                        )
                    ]]
                    reply_markup = InlineKeyboardMarkup(keyboard)

                # 发送通知
                notification = await context.bot.send_message(
                    chat_id=group_id,
                    text=notification_text,
                    reply_markup=reply_markup
                )

                # 设置自动删除
                auto_delete_delay = config.get('auto_delete_delay', 120)
                await asyncio.sleep(auto_delete_delay)
                try:
                    await notification.delete()
                except Exception as e:
                    logger.error(f"Failed to delete notification: {e}")

        except Exception as e:
            logger.error(f"Failed in _detect_and_process: {e}")

    async def handle_unban_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理解禁按钮回调"""
        try:
            query = update.callback_query
            await query.answer()

            # 检查是否为管理员
            if not await self.is_admin(update, context):
                await query.answer("⚠️ 只有管理员可以执行此操作", show_alert=True)
                return

            # 解析回调数据
            callback_data = query.data
            if not callback_data.startswith("antispam_unban:"):
                return

            user_id = int(callback_data.split(":")[1])
            group_id = update.effective_chat.id

            # 解封用户
            try:
                await context.bot.unban_chat_member(group_id, user_id)
                logger.info(f"Unbanned user {user_id} in group {group_id}")
            except Exception as e:
                logger.error(f"Failed to unban user: {e}")
                await query.answer("❌ 解禁失败", show_alert=True)
                return

            # 更新误报统计
            from datetime import datetime
            today = datetime.now().date()
            async with self.manager.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """UPDATE anti_spam_stats
                           SET false_positives = false_positives + 1
                           WHERE group_id = %s AND date = %s""",
                        (group_id, today)
                    )
                    await conn.commit()

            # 更新通知消息
            admin_name = update.effective_user.first_name
            new_text = query.message.text + f"\n\n✅ 已被管理员 {admin_name} 解禁"
            await query.edit_message_text(text=new_text)
            await query.answer("✅ 用户已解禁", show_alert=True)

        except Exception as e:
            logger.error(f"Failed to handle unban callback: {e}")
