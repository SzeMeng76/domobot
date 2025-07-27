import logging
import re

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from utils.command_factory import command_factory
from utils.config_manager import get_config
from utils.formatter import foldable_text_v2, foldable_text_with_markdown_v2
from utils.message_manager import (
    send_message_with_auto_delete,
    send_error,
    send_success,
    send_info,
    delete_user_command,
    MessageType,
    _schedule_deletion,
)
from utils.permissions import Permission
# 已移除 tasks、scripts、logs 命令（旧系统遗留功能）


logger = logging.getLogger(__name__)

# 获取配置
config = get_config()


# 辅助函数
def get_user_manager(context: ContextTypes.DEFAULT_TYPE):
    """获取MySQL用户管理器"""
    return context.bot_data.get("user_cache_manager")


async def is_super_admin(user_id: int) -> bool:
    """检查是否为超级管理员"""
    return user_id == config.super_admin_id


async def is_admin(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """检查是否为管理员（包括超级管理员）"""
    if await is_super_admin(user_id):
        return True
    user_manager = get_user_manager(context)
    if not user_manager:
        return False
    return await user_manager.is_admin(user_id)


async def has_permission(user_id: int, permission: str, context: ContextTypes.DEFAULT_TYPE) -> bool:  # noqa: ARG001
    """检查用户是否有特定权限"""
    # 超级管理员拥有所有权限
    if await is_super_admin(user_id):
        return True
    # 目前所有管理员都有所有权限
    return await is_admin(user_id, context)


# --- Direct Command Handlers ---
async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Adds a user to the whitelist. Prioritizes replied-to user."""
    user_id = update.effective_user.id
    message = update.message

    if not await has_permission(user_id, "manage_users", context):
        await send_error(context, update.effective_chat.id, "❌ 你没有管理用户的权限。")
        return

    target_user_id = None
    if message.reply_to_message:
        target_user_id = message.reply_to_message.from_user.id
    elif context.args:
        try:
            target_user_id = int(context.args[0])
        except (IndexError, ValueError):
            sent_message = await context.bot.send_message(
                chat_id=update.effective_chat.id, text="❌ 无效的ID，请输入一个数字或回复一个用户的消息。"
            )
            await _schedule_deletion(
                chat_id=sent_message.chat_id, message_id=sent_message.message_id, delay=5, context=context
            )
            return

    if not target_user_id:
        help_text = "📝 *使用方法:*\n• 回复一个用户的消息并输入 `/add`\n• 或者使用 `/add <user_id>`"
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id, text=foldable_text_with_markdown_v2(help_text), parse_mode="MarkdownV2"
        )
        await _schedule_deletion(
            chat_id=sent_message.chat_id, message_id=sent_message.message_id, delay=10, context=context
        )
        return

    # 使用MySQL用户管理器
    user_manager = get_user_manager(context)
    if not user_manager:
        sent_message = await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ 用户管理器未初始化。")
        await _schedule_deletion(
            chat_id=sent_message.chat_id, message_id=sent_message.message_id, delay=5, context=context
        )
        return

    if await user_manager.add_to_whitelist(target_user_id, user_id):
        reply_text = f"✅ 用户 `{target_user_id}` 已成功添加到白名单。"
    else:
        reply_text = f"❌ 添加失败，用户 `{target_user_id}` 可能已在白名单中。"

    sent_message = await context.bot.send_message(
        chat_id=update.effective_chat.id, text=foldable_text_with_markdown_v2(reply_text), parse_mode="MarkdownV2"
    )
    await _schedule_deletion(
        chat_id=sent_message.chat_id, message_id=sent_message.message_id, delay=5, context=context
    )
    return


async def addgroup_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Adds a group to the whitelist. Prioritizes current chat if it's a group."""
    user_id = update.effective_user.id
    message = update.message

    if not await has_permission(user_id, "manage_groups", context):
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id, text="❌ 你没有管理群组的权限。"
        )
        await _schedule_deletion(
            chat_id=sent_message.chat_id, message_id=sent_message.message_id, delay=5, context=context
        )
        return

    target_group_id = None
    group_title = "未知群组"

    if message.chat.type in ["group", "supergroup"]:
        target_group_id = message.chat.id
        group_title = message.chat.title
    elif context.args:
        try:
            target_group_id = int(context.args[0])
            chat_info = await context.bot.get_chat(target_group_id)
            group_title = chat_info.title
        except (IndexError, ValueError):
            sent_message = await context.bot.send_message(
                chat_id=update.effective_chat.id, text="❌ 无效的ID，请输入一个数字。"
            )
            await _schedule_deletion(
                chat_id=sent_message.chat_id, message_id=sent_message.message_id, delay=5, context=context
            )
            return
        except Exception as e:
            logger.warning(f"Could not get chat title for {target_group_id}: {e}. Using default title.")
            group_title = f"群组 {target_group_id}"

    if not target_group_id:
        help_text = "📝 *使用方法:*\n• 在目标群组中发送 `/addgroup`\n• 或者使用 `/addgroup <group_id>`"
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id, text=foldable_text_with_markdown_v2(help_text), parse_mode="MarkdownV2"
        )
        await _schedule_deletion(
            chat_id=sent_message.chat_id, message_id=sent_message.message_id, delay=10, context=context
        )
        return

    # 使用MySQL用户管理器
    user_manager = get_user_manager(context)
    if not user_manager:
        sent_message = await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ 用户管理器未初始化。")
        await _schedule_deletion(
            chat_id=sent_message.chat_id, message_id=sent_message.message_id, delay=5, context=context
        )
        return

    if await user_manager.add_group_to_whitelist(target_group_id, group_title or f"群组 {target_group_id}", user_id):
        reply_text = f"✅ 群组 *{group_title or f'群组 {target_group_id}'}* (`{target_group_id}`) 已成功添加到白名单。"
    else:
        reply_text = f"❌ 添加失败，群组 `{target_group_id}` 可能已在白名单中。"

    sent_message = await context.bot.send_message(
        chat_id=update.effective_chat.id, text=foldable_text_with_markdown_v2(reply_text), parse_mode="MarkdownV2"
    )
    await _schedule_deletion(
        chat_id=sent_message.chat_id, message_id=sent_message.message_id, delay=5, context=context
    )
    return


# Conversation states
(
    MAIN_PANEL,
    USER_PANEL,
    GROUP_PANEL,
    ADMIN_PANEL,
    AWAITING_USER_ID_TO_ADD,
    AWAITING_USER_ID_TO_REMOVE,
    AWAITING_GROUP_ID_TO_ADD,
    AWAITING_GROUP_ID_TO_REMOVE,
    AWAITING_ADMIN_ID_TO_ADD,
    AWAITING_ADMIN_ID_TO_REMOVE,
) = range(10)


class AdminPanelHandler:
    def __init__(self):
        pass

    async def _show_panel(self, query: CallbackQuery, text: str, reply_markup: InlineKeyboardMarkup):
        """Helper to edit the message with new panel content."""
        try:
            await query.edit_message_text(
                foldable_text_with_markdown_v2(text), parse_mode="MarkdownV2", reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Error updating admin panel: {e}")

    async def show_main_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        # 权限检查
        if not update.effective_user or not update.effective_chat:
            return ConversationHandler.END

        user_id = update.effective_user.id

        # 检查用户是否有管理员权限
        if not await is_admin(user_id, context):
            sent_message = await context.bot.send_message(
                chat_id=update.effective_chat.id, text="❌ 你没有管理员权限。"
            )
            await _schedule_deletion(
                chat_id=sent_message.chat_id, message_id=sent_message.message_id, delay=5, context=context
            )
            return ConversationHandler.END

        keyboard = [
            [InlineKeyboardButton("👤 管理用户白名单", callback_data="manage_users")],
            [InlineKeyboardButton("👨‍👩‍👧‍👦 管理群组白名单", callback_data="manage_groups")],
        ]
        if await is_super_admin(user_id):
            keyboard.insert(0, [InlineKeyboardButton("👥 管理管理员", callback_data="manage_admins")])
        keyboard.append([InlineKeyboardButton("❌ 关闭", callback_data="close")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        admin_type = "超级管理员" if await is_super_admin(user_id) else "管理员"
        text = f"🛠️ *{admin_type}控制面板*\n\n请选择一项操作:"

        if update.callback_query:
            await self._show_panel(update.callback_query, text, reply_markup)
        else:
            # 保存用户的初始命令消息ID，用于后续删除
            if update.message:
                context.user_data["initial_command_message_id"] = update.message.message_id
                context.user_data["chat_id"] = update.effective_chat.id

            # 发送管理面板消息
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=foldable_text_with_markdown_v2(text),
                parse_mode="MarkdownV2",
                reply_markup=reply_markup,
            )

            # 删除用户的/admin命令消息
            if update.message:
                try:
                    await _schedule_deletion(
                        chat_id=update.effective_chat.id, message_id=update.message.message_id, delay=0, context=context
                    )
                except Exception as e:
                    logger.warning(f"无法安排删除用户命令消息: {e}")

        return MAIN_PANEL

    async def show_user_panel(
        self, query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, status_message: str | None = None
    ) -> int:
        user_manager = get_user_manager(context)
        if not user_manager:
            await self._show_panel(query, "❌ 用户管理器未初始化", InlineKeyboardMarkup([]))
            return ConversationHandler.END
        users = await user_manager.get_whitelisted_users()
        text = f"👤 *用户白名单* (共 {len(users)} 人)\n\n"
        if status_message:
            text = f"{status_message}\n\n" + text
        text += "\n".join([f"• `{uid}`" for uid in sorted(users)]) if users else "📭 暂无白名单用户"
        keyboard = [
            [
                InlineKeyboardButton("➕ 添加用户", callback_data="user_add"),
                InlineKeyboardButton("➖ 移除用户", callback_data="user_remove"),
            ],
            [
                InlineKeyboardButton("🔄 刷新", callback_data="refresh_users"),
                InlineKeyboardButton("🔙 返回", callback_data="back_to_main"),
            ],
        ]
        await self._show_panel(query, text, InlineKeyboardMarkup(keyboard))
        return USER_PANEL

    async def show_group_panel(
        self, query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, status_message: str | None = None
    ) -> int:
        user_manager = get_user_manager(context)
        if not user_manager:
            await self._show_panel(query, "❌ 用户管理器未初始化", InlineKeyboardMarkup([]))
            return ConversationHandler.END
        groups = await user_manager.get_whitelisted_groups()
        text = f"👨‍👩‍👧‍👦 *群组白名单* (共 {len(groups)} 个)\n\n"
        if status_message:
            text = f"{status_message}\n\n" + text
        # 修正排序与展示
        text += (
            "\n".join([f"• `{g['group_id']}`" for g in sorted(groups, key=lambda g: g["group_id"])])
            if groups
            else "📭 暂无白名单群组"
        )
        keyboard = [
            [
                InlineKeyboardButton("➕ 添加群组", callback_data="group_add"),
                InlineKeyboardButton("➖ 移除群组", callback_data="group_remove"),
            ],
            [
                InlineKeyboardButton("🔄 刷新", callback_data="refresh_groups"),
                InlineKeyboardButton("🔙 返回", callback_data="back_to_main"),
            ],
        ]
        await self._show_panel(query, text, InlineKeyboardMarkup(keyboard))
        return GROUP_PANEL

    async def show_admin_panel(
        self, query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, status_message: str | None = None
    ) -> int:
        user_manager = get_user_manager(context)
        if not user_manager:
            await self._show_panel(query, "❌ 用户管理器未初始化", InlineKeyboardMarkup([]))
            return ConversationHandler.END
        admin_ids = await user_manager.get_all_admins()
        # 转换为兼容格式
        admins = [{"user_id": admin_id} for admin_id in admin_ids]
        text = f"👥 *管理员列表* (共 {len(admins)} 人)\n\n"
        if status_message:
            text = f"{status_message}\n\n" + text
        # 修正排序与展示
        text += (
            "\n".join([f"• `{a['user_id']}`" for a in sorted(admins, key=lambda a: a["user_id"])])
            if admins
            else "📭 暂无管理员"
        )
        keyboard = [
            [
                InlineKeyboardButton("➕ 添加管理员", callback_data="admin_add"),
                InlineKeyboardButton("➖ 移除管理员", callback_data="admin_remove"),
            ],
            [
                InlineKeyboardButton("🔄 刷新", callback_data="refresh_admins"),
                InlineKeyboardButton("🔙 返回", callback_data="back_to_main"),
            ],
        ]
        await self._show_panel(query, text, InlineKeyboardMarkup(keyboard))
        return ADMIN_PANEL

    async def prompt_for_input(
        self, query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, prompt_text: str, next_state: int
    ) -> int:
        context.user_data["admin_query"] = query
        cancel_keyboard = [[InlineKeyboardButton("❌ 取消", callback_data="cancel_input")]]
        await self._show_panel(
            query, f"📝 {prompt_text}\n\n发送 /cancel 可取消。", InlineKeyboardMarkup(cancel_keyboard)
        )
        return next_state

    async def _handle_modification(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, action_func, success_msg, failure_msg, item_type
    ):
        # 保存用户命令消息以便稍后删除
        user_message = update.message

        if user_message:
            await _schedule_deletion(
                chat_id=user_message.chat_id, message_id=user_message.message_id, delay=0, context=context
            )

        if not user_message or not user_message.text:
            return ConversationHandler.END

        ids_to_process = re.split(r"[\s\n,]+", user_message.text.strip())
        processed, failed = [], []

        for item_id_str in ids_to_process:
            if not item_id_str:
                continue
            try:
                item_id = int(item_id_str)
                if await action_func(item_id):
                    processed.append(item_id_str)
                else:
                    failed.append(item_id_str)
            except ValueError:
                failed.append(item_id_str)
            except Exception as e:
                logger.error(f"处理 {item_type} {item_id_str} 时出错: {e}")
                failed.append(item_id_str)

        status_text = ""
        if processed:
            status_text += f"✅ {success_msg} {len(processed)} 个{item_type}: `{', '.join(processed)}`\n"
        if failed:
            status_text += f"❌ {failure_msg} {len(failed)} 个{item_type} (无效或状态未变): `{', '.join(failed)}`"

        # 显示操作结果，然后自动关闭面板
        query = context.user_data.get("admin_query") if context.user_data else None
        if query and status_text.strip():
            # 编辑消息显示操作结果
            await query.edit_message_text(
                foldable_text_with_markdown_v2(f"操作完成:\n\n{status_text.strip()}\n\n⏰ 面板将在3秒后自动关闭..."),
                parse_mode="MarkdownV2",
            )

            # 3秒后自动删除面板
            await _schedule_deletion(
                chat_id=query.message.chat_id, message_id=query.message.message_id, delay=3, context=context
            )

            # 删除用户的初始命令消息（如果存在）
            initial_msg_id = context.user_data.get("initial_command_message_id")
            chat_id = context.user_data.get("chat_id")
            if initial_msg_id and chat_id:
                await _schedule_deletion(
                    chat_id,
                    initial_msg_id,
                    delay=3,  # 也延迟3秒
                    context=context,
                )

        # 不要直接结束对话，让用户可以继续使用admin命令
        # 清理临时数据但保持ConversationHandler活跃
        context.user_data.pop("admin_query", None)
        return ConversationHandler.END

    async def handle_add_user(self, u, c):
        user_manager = get_user_manager(c)
        if not user_manager:
            return ConversationHandler.END

        async def add_func(user_id):
            return await user_manager.add_to_whitelist(user_id, u.effective_user.id)

        return await self._handle_modification(u, c, add_func, "成功添加", "添加失败", "用户")

    async def handle_remove_user(self, u, c):
        user_manager = get_user_manager(c)
        if not user_manager:
            return ConversationHandler.END

        async def remove_func(user_id):
            return await user_manager.remove_from_whitelist(user_id)

        return await self._handle_modification(u, c, remove_func, "成功移除", "移除失败", "用户")

    async def handle_add_group(self, u, c):
        user_manager = get_user_manager(c)
        if not user_manager:
            return ConversationHandler.END

        async def add_func(group_id):
            return await user_manager.add_group_to_whitelist(group_id, f"Group {group_id}", u.effective_user.id)

        return await self._handle_modification(u, c, add_func, "成功添加", "添加失败", "群组")

    async def handle_remove_group(self, u, c):
        user_manager = get_user_manager(c)
        if not user_manager:
            return ConversationHandler.END

        async def remove_func(group_id):
            return await user_manager.remove_group_from_whitelist(group_id)

        return await self._handle_modification(u, c, remove_func, "成功移除", "移除失败", "群组")

    async def handle_add_admin(self, u, c):
        user_manager = get_user_manager(c)
        if not user_manager:
            return ConversationHandler.END

        async def add_func(admin_id):
            return await user_manager.add_admin(admin_id, u.effective_user.id)

        return await self._handle_modification(u, c, add_func, "成功添加", "添加失败", "管理员")

    async def handle_remove_admin(self, u, c):
        user_manager = get_user_manager(c)
        if not user_manager:
            return ConversationHandler.END

        async def remove_func(admin_id):
            return await user_manager.remove_admin(admin_id)

        return await self._handle_modification(u, c, remove_func, "成功移除", "移除失败", "管理员")

    async def close_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        query = update.callback_query
        if query:
            await query.message.delete()

        # 删除用户的初始命令消息（如果存在）
        try:
            if context.user_data:
                initial_msg_id = context.user_data.get("initial_command_message_id")
                chat_id = context.user_data.get("chat_id")
                if initial_msg_id and chat_id:
                    await context.bot.delete_message(chat_id=chat_id, message_id=initial_msg_id)
        except Exception as e:
            logger.warning(f"无法删除初始命令消息: {e}")

        return ConversationHandler.END

    async def cancel_and_back(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Goes back to the correct panel when /cancel is used."""
        if update.message:
            await _schedule_deletion(
                chat_id=update.message.chat_id, message_id=update.message.message_id, delay=0, context=context
            )

        if not context.user_data:
            return ConversationHandler.END

        query = context.user_data.get("admin_query")
        if not query:
            return ConversationHandler.END

        current_panel = context.user_data.get("current_panel")
        if current_panel == "user" and query:
            return await self.show_user_panel(query, context)
        if current_panel == "group" and query:
            return await self.show_group_panel(query, context)
        if current_panel == "admin" and query:
            return await self.show_admin_panel(query, context)

        # Fallback to main panel if something is weird
        return await self.show_main_panel(update, context)

    async def cancel_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """处理按钮取消操作"""
        query = update.callback_query
        if not query:
            return ConversationHandler.END

        # 获取当前面板类型并返回对应面板
        current_panel = context.user_data.get("current_panel") if context.user_data else None

        if current_panel == "user":
            return await self.show_user_panel(query, context)
        elif current_panel == "group":
            return await self.show_group_panel(query, context)
        elif current_panel == "admin":
            return await self.show_admin_panel(query, context)
        else:
            # 默认返回主面板
            return await self.show_main_panel(update, context)

    # --- 刷新功能处理 ---
    async def _refresh_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """刷新用户白名单面板"""
        return await self.show_user_panel(update.callback_query, context)

    async def _refresh_groups(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """刷新群组白名单面板"""
        return await self.show_group_panel(update.callback_query, context)

    async def _refresh_admins(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """刷新管理员面板"""
        return await self.show_admin_panel(update.callback_query, context)

    # --- Callback Handlers for Conversation ---
    async def _to_user_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data["current_panel"] = "user"
        return await self.show_user_panel(update.callback_query, context)

    async def _to_group_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data["current_panel"] = "group"
        return await self.show_group_panel(update.callback_query, context)

    async def _to_admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data["current_panel"] = "admin"
        return await self.show_admin_panel(update.callback_query, context)

    async def _prompt_user_add(self, u, c):
        return await self.prompt_for_input(u.callback_query, c, "请输入要添加的用户ID", AWAITING_USER_ID_TO_ADD)

    async def _prompt_user_remove(self, u, c):
        return await self.prompt_for_input(u.callback_query, c, "请输入要移除的用户ID", AWAITING_USER_ID_TO_REMOVE)

    async def _prompt_group_add(self, u, c):
        return await self.prompt_for_input(u.callback_query, c, "请输入要添加的群组ID", AWAITING_GROUP_ID_TO_ADD)

    async def _prompt_group_remove(self, u, c):
        return await self.prompt_for_input(u.callback_query, c, "请输入要移除的群组ID", AWAITING_GROUP_ID_TO_REMOVE)

    async def _prompt_admin_add(self, u, c):
        return await self.prompt_for_input(u.callback_query, c, "请输入要添加的管理员ID", AWAITING_ADMIN_ID_TO_ADD)

    async def _prompt_admin_remove(self, u, c):
        return await self.prompt_for_input(u.callback_query, c, "请输入要移除的管理员ID", AWAITING_ADMIN_ID_TO_REMOVE)

    def get_conversation_handler(self) -> ConversationHandler:
        return ConversationHandler(
            entry_points=[CommandHandler("admin", self.show_main_panel)],
            states={
                MAIN_PANEL: [
                    CallbackQueryHandler(self._to_user_panel, pattern="^manage_users$"),
                    CallbackQueryHandler(self._to_group_panel, pattern="^manage_groups$"),
                    CallbackQueryHandler(self._to_admin_panel, pattern="^manage_admins$"),
                    CallbackQueryHandler(self.close_panel, pattern="^close$"),
                ],
                USER_PANEL: [
                    CallbackQueryHandler(self._prompt_user_add, pattern="^user_add$"),
                    CallbackQueryHandler(self._prompt_user_remove, pattern="^user_remove$"),
                    CallbackQueryHandler(self._refresh_users, pattern="^refresh_users$"),
                    CallbackQueryHandler(self.show_main_panel, pattern="^back_to_main$"),
                ],
                GROUP_PANEL: [
                    CallbackQueryHandler(self._prompt_group_add, pattern="^group_add$"),
                    CallbackQueryHandler(self._prompt_group_remove, pattern="^group_remove$"),
                    CallbackQueryHandler(self._refresh_groups, pattern="^refresh_groups$"),
                    CallbackQueryHandler(self.show_main_panel, pattern="^back_to_main$"),
                ],
                ADMIN_PANEL: [
                    CallbackQueryHandler(self._prompt_admin_add, pattern="^admin_add$"),
                    CallbackQueryHandler(self._prompt_admin_remove, pattern="^admin_remove$"),
                    CallbackQueryHandler(self._refresh_admins, pattern="^refresh_admins$"),
                    CallbackQueryHandler(self.show_main_panel, pattern="^back_to_main$"),
                ],
                AWAITING_USER_ID_TO_ADD: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_add_user),
                    CallbackQueryHandler(self.cancel_input, pattern="^cancel_input$"),
                    CommandHandler("admin", self.show_main_panel),  # 允许重新启动admin
                ],
                AWAITING_USER_ID_TO_REMOVE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_remove_user),
                    CallbackQueryHandler(self.cancel_input, pattern="^cancel_input$"),
                    CommandHandler("admin", self.show_main_panel),  # 允许重新启动admin
                ],
                AWAITING_GROUP_ID_TO_ADD: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_add_group),
                    CallbackQueryHandler(self.cancel_input, pattern="^cancel_input$"),
                    CommandHandler("admin", self.show_main_panel),  # 允许重新启动admin
                ],
                AWAITING_GROUP_ID_TO_REMOVE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_remove_group),
                    CallbackQueryHandler(self.cancel_input, pattern="^cancel_input$"),
                    CommandHandler("admin", self.show_main_panel),  # 允许重新启动admin
                ],
                AWAITING_ADMIN_ID_TO_ADD: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_add_admin),
                    CallbackQueryHandler(self.cancel_input, pattern="^cancel_input$"),
                    CommandHandler("admin", self.show_main_panel),  # 允许重新启动admin
                ],
                AWAITING_ADMIN_ID_TO_REMOVE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_remove_admin),
                    CallbackQueryHandler(self.cancel_input, pattern="^cancel_input$"),
                    CommandHandler("admin", self.show_main_panel),  # 允许重新启动admin
                ],
            },
            fallbacks=[CommandHandler("cancel", self.cancel_and_back)],
            per_message=False,
        )








# 用于命令菜单的admin命令处理器（实际处理由ConversationHandler完成）
async def admin_command_placeholder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """管理员面板命令占位符 - 此函数仅用于命令菜单注册，实际处理由ConversationHandler完成"""
    # 这个函数不会被调用，因为ConversationHandler会先拦截/admin命令
    pass


admin_panel_handler = AdminPanelHandler()

# Register commands (注意：admin命令不在这里注册，因为它由ConversationHandler处理)
command_factory.register_command("add", add_command, permission=Permission.ADMIN, description="添加用户到白名单")
command_factory.register_command(
    "addgroup", addgroup_command, permission=Permission.ADMIN, description="添加群组到白名单"
)
# admin命令由ConversationHandler处理，不需要在这里注册
# command_factory.register_command("admin", admin_command_placeholder, permission=Permission.ADMIN, description="打开管理员面板")
