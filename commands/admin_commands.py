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
from telegram import BotCommand, BotCommandScopeChat
# 已移除 tasks、scripts、logs 命令（旧系统遗留功能）


async def update_user_command_menu(user_id: int, context: ContextTypes.DEFAULT_TYPE, is_whitelist: bool = False, is_admin: bool = False) -> None:
    """更新用户的命令菜单"""
    try:
        from utils.command_factory import command_factory
        from utils.config_manager import get_config
        
        config = get_config()
        
        # 获取不同权限级别的命令
        none_commands = command_factory.get_command_list(Permission.NONE)
        user_commands = command_factory.get_command_list(Permission.USER)
        admin_commands = command_factory.get_command_list(Permission.ADMIN)
        super_admin_commands = command_factory.get_command_list(Permission.SUPER_ADMIN)
        
        if is_admin or user_id == config.super_admin_id:
            # 管理员：显示所有命令
            all_commands = {}
            all_commands.update(none_commands)
            all_commands.update(user_commands)
            all_commands.update(admin_commands)
            all_commands.update(super_admin_commands)
            all_commands["admin"] = "打开管理员面板"
            bot_commands = [BotCommand(command, description) for command, description in all_commands.items()]
        elif is_whitelist:
            # 白名单用户：显示基础+用户命令
            user_level_commands = {}
            user_level_commands.update(none_commands)
            user_level_commands.update(user_commands)
            bot_commands = [BotCommand(command, description) for command, description in user_level_commands.items()]
        else:
            # 非白名单用户：只显示基础命令
            bot_commands = [BotCommand(command, description) for command, description in none_commands.items()]
        
        # 设置用户特定的命令菜单
        await context.bot.set_my_commands(
            bot_commands,
            scope=BotCommandScopeChat(chat_id=user_id)
        )
        
        logger.info(f"已更新用户 {user_id} 的命令菜单，权限：{'管理员' if is_admin else ('白名单' if is_whitelist else '基础')}")
        
    except Exception as e:
        logger.error(f"更新用户 {user_id} 命令菜单失败: {e}")


async def update_group_command_menu(group_id: int, context: ContextTypes.DEFAULT_TYPE, is_whitelisted: bool = False) -> None:
    """更新群组的命令菜单"""
    try:
        from utils.command_factory import command_factory
        from telegram import BotCommandScopeChat
        
        # 获取不同权限级别的命令
        none_commands = command_factory.get_command_list(Permission.NONE)
        user_commands = command_factory.get_command_list(Permission.USER)
        
        if is_whitelisted:
            # 白名单群组：显示基础+用户命令（但不包含管理员命令）
            group_commands = {}
            group_commands.update(none_commands)
            group_commands.update(user_commands)
            bot_commands = [BotCommand(command, description) for command, description in group_commands.items()]
        else:
            # 非白名单群组：只显示基础命令
            bot_commands = [BotCommand(command, description) for command, description in none_commands.items()]
        
        # 设置群组特定的命令菜单
        await context.bot.set_my_commands(
            bot_commands,
            scope=BotCommandScopeChat(chat_id=group_id)
        )
        
        logger.info(f"已更新群组 {group_id} 的命令菜单，状态：{'白名单' if is_whitelisted else '非白名单'}")
        
    except Exception as e:
        logger.error(f"更新群组 {group_id} 命令菜单失败: {e}")


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
        # 添加用户后更新命令菜单
        try:
            is_admin = await user_manager.is_admin(target_user_id)
            await update_user_command_menu(target_user_id, context, is_whitelist=True, is_admin=is_admin)
        except Exception as e:
            logger.warning(f"更新用户 {target_user_id} 命令菜单失败: {e}")
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
        # 添加群组后更新群组命令菜单
        try:
            await update_group_command_menu(target_group_id, context, is_whitelisted=True)
        except Exception as e:
            logger.warning(f"更新群组 {target_group_id} 命令菜单失败: {e}")
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
    ANTISPAM_PANEL,
    AWAITING_USER_ID_TO_ADD,
    AWAITING_USER_ID_TO_REMOVE,
    AWAITING_GROUP_ID_TO_ADD,
    AWAITING_GROUP_ID_TO_REMOVE,
    AWAITING_ADMIN_ID_TO_ADD,
    AWAITING_ADMIN_ID_TO_REMOVE,
    AWAITING_ANTISPAM_GROUP_ID,
) = range(12)


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
            [InlineKeyboardButton("🛡️ AI反垃圾管理", callback_data="manage_antispam")],
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

    async def show_antispam_panel(
        self, query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, status_message: str | None = None
    ) -> int:
        """显示AI反垃圾管理面板"""
        # 检查反垃圾功能是否可用
        anti_spam_handler = context.bot_data.get("anti_spam_handler")
        if not anti_spam_handler or not hasattr(anti_spam_handler, 'manager'):
            await self._show_panel(query, "❌ AI反垃圾功能未启用\n请检查 OPENAI_API_KEY 配置", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="back_to_main")]]))
            return ANTISPAM_PANEL

        manager = anti_spam_handler.manager

        # 获取当前选中的群组ID（从context中获取，如果没有则为None）
        selected_group_id = context.user_data.get("antispam_selected_group_id")

        if not selected_group_id:
            # 显示群组选择列表
            user_manager = get_user_manager(context)
            if not user_manager:
                await self._show_panel(query, "❌ 用户管理器未初始化", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="back_to_main")]]))
                return ANTISPAM_PANEL

            groups = await user_manager.get_whitelisted_groups()

            text = "🛡️ *AI反垃圾管理*\n\n"
            if status_message:
                text += f"{status_message}\n\n"

            text += "请选择要管理的群组：\n\n"
            if groups:
                text += "\n".join([f"• {g['group_name']} (`{g['group_id']}`)" for g in groups[:10]])
                text += f"\n\n共 {len(groups)} 个白名单群组"
            else:
                text += "📭 暂无白名单群组\n请先添加群组到白名单"

            keyboard = [
                [InlineKeyboardButton("🔍 输入群组ID", callback_data="antispam_input_group")],
                [InlineKeyboardButton("🔙 返回", callback_data="back_to_main")]
            ]

            await self._show_panel(query, text, InlineKeyboardMarkup(keyboard))
            return ANTISPAM_PANEL

        # 有选中的群组，显示该群组的反垃圾配置
        group_name = context.user_data.get("antispam_selected_group_name", f"群组 {selected_group_id}")

        # 获取配置
        config = await manager.get_group_config(selected_group_id)
        is_enabled = config.get('enabled', False) if config else False

        # 获取统计数据
        stats = await manager.get_group_stats(selected_group_id, days=7)
        total_checks = sum(s.get('total_checks', 0) for s in stats)
        spam_detected = sum(s.get('spam_detected', 0) for s in stats)
        users_banned = sum(s.get('users_banned', 0) for s in stats)
        false_positives = sum(s.get('false_positives', 0) for s in stats)

        # 构建面板文本
        status_text = "✅ 已启用" if is_enabled else "❌ 未启用"
        text = f"🛡️ *AI反垃圾管理*\n\n"
        if status_message:
            text += f"{status_message}\n\n"

        text += f"📊 状态: {status_text}\n"
        text += f"🏢 群组: {group_name}\n"
        text += f"🆔 ID: `{selected_group_id}`\n\n"
        text += f"📈 *最近7天统计:*\n"
        text += f"• 总检测: {total_checks}次\n"
        text += f"• 检测垃圾: {spam_detected}次\n"
        text += f"• 封禁用户: {users_banned}人\n"
        text += f"• 误报: {false_positives}次\n"

        if config and is_enabled:
            text += f"\n⚙️ *当前配置:*\n"
            text += f"• 分数阈值: {config.get('spam_score_threshold', 80)}\n"
            text += f"• 新用户天数: {config.get('joined_time_threshold', 3)}天\n"
            text += f"• 新用户发言数: {config.get('speech_count_threshold', 3)}次\n"
            text += f"• 检测文本: {'✅' if config.get('check_text', True) else '❌'}\n"
            text += f"• 检测图片: {'✅' if config.get('check_photo', True) else '❌'}\n"

        # 构建按钮
        keyboard = []
        if is_enabled:
            keyboard.append([InlineKeyboardButton("❌ 禁用", callback_data="antispam_disable")])
        else:
            keyboard.append([InlineKeyboardButton("✅ 启用", callback_data="antispam_enable")])

        keyboard.append([
            InlineKeyboardButton("⚙️ 配置", callback_data="antispam_config"),
            InlineKeyboardButton("📊 详细统计", callback_data="antispam_stats")
        ])
        keyboard.append([
            InlineKeyboardButton("🔄 切换群组", callback_data="antispam_change_group"),
            InlineKeyboardButton("🔙 返回", callback_data="back_to_main")
        ])

        await self._show_panel(query, text, InlineKeyboardMarkup(keyboard))
        return ANTISPAM_PANEL

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
            success = await user_manager.add_to_whitelist(user_id, u.effective_user.id)
            if success:
                # 添加用户后更新命令菜单
                is_admin = await user_manager.is_admin(user_id)
                await update_user_command_menu(user_id, c, is_whitelist=True, is_admin=is_admin)
            return success

        return await self._handle_modification(u, c, add_func, "成功添加", "添加失败", "用户")

    async def handle_remove_user(self, u, c):
        user_manager = get_user_manager(c)
        if not user_manager:
            return ConversationHandler.END

        async def remove_func(user_id):
            success = await user_manager.remove_from_whitelist(user_id)
            if success:
                # 移除用户后更新命令菜单
                is_admin = await user_manager.is_admin(user_id)
                await update_user_command_menu(user_id, c, is_whitelist=False, is_admin=is_admin)
            return success

        return await self._handle_modification(u, c, remove_func, "成功移除", "移除失败", "用户")

    async def handle_add_group(self, u, c):
        user_manager = get_user_manager(c)
        if not user_manager:
            return ConversationHandler.END

        async def add_func(group_id):
            success = await user_manager.add_group_to_whitelist(group_id, f"Group {group_id}", u.effective_user.id)
            if success:
                # 添加群组后更新群组命令菜单
                await update_group_command_menu(group_id, c, is_whitelisted=True)
            return success

        return await self._handle_modification(u, c, add_func, "成功添加", "添加失败", "群组")

    async def handle_remove_group(self, u, c):
        user_manager = get_user_manager(c)
        if not user_manager:
            return ConversationHandler.END

        async def remove_func(group_id):
            success = await user_manager.remove_group_from_whitelist(group_id)
            if success:
                # 移除群组后更新群组命令菜单
                await update_group_command_menu(group_id, c, is_whitelisted=False)
            return success

        return await self._handle_modification(u, c, remove_func, "成功移除", "移除失败", "群组")

    async def handle_add_admin(self, u, c):
        user_manager = get_user_manager(c)
        if not user_manager:
            return ConversationHandler.END

        async def add_func(admin_id):
            success = await user_manager.add_admin(admin_id, u.effective_user.id)
            if success:
                # 添加管理员后更新命令菜单
                is_whitelist = await user_manager.is_whitelisted(admin_id)
                await update_user_command_menu(admin_id, c, is_whitelist=is_whitelist, is_admin=True)
            return success

        return await self._handle_modification(u, c, add_func, "成功添加", "添加失败", "管理员")

    async def handle_remove_admin(self, u, c):
        user_manager = get_user_manager(c)
        if not user_manager:
            return ConversationHandler.END

        async def remove_func(admin_id):
            success = await user_manager.remove_admin(admin_id)
            if success:
                # 移除管理员后更新命令菜单
                is_whitelist = await user_manager.is_whitelisted(admin_id)
                await update_user_command_menu(admin_id, c, is_whitelist=is_whitelist, is_admin=False)
            return success

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

    async def _to_antispam_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data["current_panel"] = "antispam"
        return await self.show_antispam_panel(update.callback_query, context)

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

    # ==================== 反垃圾管理回调处理 ====================

    async def _prompt_antispam_input_group(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """提示输入群组ID"""
        return await self.prompt_for_input(update.callback_query, context, "请输入要管理的群组ID (负数，如 -1001234567890)", AWAITING_ANTISPAM_GROUP_ID)

    async def _handle_antispam_change_group(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """切换群组"""
        context.user_data.pop("antispam_selected_group_id", None)
        context.user_data.pop("antispam_selected_group_name", None)
        return await self.show_antispam_panel(update.callback_query, context)

    async def _handle_antispam_enable(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """启用反垃圾功能"""
        group_id = context.user_data.get("antispam_selected_group_id")
        if not group_id:
            return await self.show_antispam_panel(update.callback_query, context)
        anti_spam_handler = context.bot_data.get("anti_spam_handler")
        if not anti_spam_handler:
            return await self.show_antispam_panel(update.callback_query, context, "❌ 功能未启用")
        success = await anti_spam_handler.manager.enable_group(group_id)
        return await self.show_antispam_panel(update.callback_query, context, "✅ 已成功启用" if success else "❌ 启用失败")

    async def _handle_antispam_disable(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """禁用反垃圾功能"""
        group_id = context.user_data.get("antispam_selected_group_id")
        if not group_id:
            return await self.show_antispam_panel(update.callback_query, context)
        anti_spam_handler = context.bot_data.get("anti_spam_handler")
        if not anti_spam_handler:
            return await self.show_antispam_panel(update.callback_query, context, "❌ 功能未启用")
        success = await anti_spam_handler.manager.disable_group(group_id)
        return await self.show_antispam_panel(update.callback_query, context, "✅ 已成功禁用" if success else "❌ 禁用失败")

    async def _handle_antispam_config(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """显示配置选项"""
        query = update.callback_query
        text = "⚙️ *配置提示*\n\n当前版本的配置调整功能开发中\n\n你可以通过修改数据库中的 `anti_spam_config` 表来调整配置\n\n主要配置项:\n• spam\\_score\\_threshold: 垃圾分数阈值 (80\\-100)\n• joined\\_time\\_threshold: 新用户天数 (1\\-7)\n• speech\\_count\\_threshold: 新用户发言数 (1\\-10)\n• check\\_text/check\\_photo: 检测类型开关"
        await self._show_panel(query, text, InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="manage_antispam")]]))
        return ANTISPAM_PANEL

    async def _handle_antispam_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """显示详细统计"""
        query = update.callback_query
        group_id = context.user_data.get("antispam_selected_group_id")
        if not group_id:
            return await self.show_antispam_panel(query, context)
        anti_spam_handler = context.bot_data.get("anti_spam_handler")
        if not anti_spam_handler:
            return await self.show_antispam_panel(query, context)
        manager = anti_spam_handler.manager
        stats = await manager.get_group_stats(group_id, days=30)
        if not stats:
            text = "📊 *详细统计*\n\n暂无统计数据"
        else:
            total_checks = sum(s.get('total_checks', 0) for s in stats)
            total_spam = sum(s.get('spam_detected', 0) for s in stats)
            total_banned = sum(s.get('users_banned', 0) for s in stats)
            total_fp = sum(s.get('false_positives', 0) for s in stats)
            text = f"📊 *详细统计* (最近30天)\n\n📈 *总计:*\n• 总检测: {total_checks}次\n• 垃圾消息: {total_spam}条\n• 封禁用户: {total_banned}人\n• 误报: {total_fp}次\n"
            if total_spam > 0:
                accuracy = ((total_spam - total_fp) / total_spam * 100)
                text += f"• 准确率: {accuracy:.1f}%\n"
            text += "\n📅 *每日数据* (最近10天):\n"
            for stat in stats[:10]:
                date = str(stat.get('date', ''))
                checks = stat.get('total_checks', 0)
                spam = stat.get('spam_detected', 0)
                banned = stat.get('users_banned', 0)
                fp = stat.get('false_positives', 0)
                text += f"\n{date}\n  检测:{checks} | 垃圾:{spam} | 封禁:{banned} | 误报:{fp}\n"
        await self._show_panel(query, text, InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="manage_antispam")]]))
        return ANTISPAM_PANEL

    async def handle_antispam_group_id(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理输入的群组ID"""
        user_message = update.message
        if user_message:
            await _schedule_deletion(chat_id=user_message.chat_id, message_id=user_message.message_id, delay=0, context=context)
        try:
            group_id = int(update.message.text.strip())
            if group_id >= 0:
                raise ValueError("群组ID必须是负数")
            context.user_data["antispam_selected_group_id"] = group_id
            try:
                chat = await context.bot.get_chat(group_id)
                context.user_data["antispam_selected_group_name"] = chat.title
            except:
                context.user_data["antispam_selected_group_name"] = f"群组 {group_id}"
            query = context.user_data.get("admin_query")
            if query:
                return await self.show_antispam_panel(query, context, f"✅ 已选择群组 {group_id}")
            else:
                return ANTISPAM_PANEL
        except ValueError as e:
            query = context.user_data.get("admin_query")
            if query:
                await self._show_panel(query, f"❌ 输入错误: {str(e)}\n\n请重新输入群组ID", InlineKeyboardMarkup([[InlineKeyboardButton("❌ 取消", callback_data="cancel_input")]]))
            return AWAITING_ANTISPAM_GROUP_ID

    def get_conversation_handler(self) -> ConversationHandler:
        return ConversationHandler(
            entry_points=[CommandHandler("admin", self.show_main_panel)],
            states={
                MAIN_PANEL: [
                    CallbackQueryHandler(self._to_user_panel, pattern="^manage_users$"),
                    CallbackQueryHandler(self._to_group_panel, pattern="^manage_groups$"),
                    CallbackQueryHandler(self._to_admin_panel, pattern="^manage_admins$"),
                    CallbackQueryHandler(self._to_antispam_panel, pattern="^manage_antispam$"),
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
                ANTISPAM_PANEL: [
                    CallbackQueryHandler(self._prompt_antispam_input_group, pattern="^antispam_input_group$"),
                    CallbackQueryHandler(self._handle_antispam_change_group, pattern="^antispam_change_group$"),
                    CallbackQueryHandler(self._handle_antispam_enable, pattern="^antispam_enable$"),
                    CallbackQueryHandler(self._handle_antispam_disable, pattern="^antispam_disable$"),
                    CallbackQueryHandler(self._handle_antispam_config, pattern="^antispam_config$"),
                    CallbackQueryHandler(self._handle_antispam_stats, pattern="^antispam_stats$"),
                    CallbackQueryHandler(self._to_antispam_panel, pattern="^manage_antispam$"),
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
                AWAITING_ANTISPAM_GROUP_ID: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_antispam_group_id),
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

async def refresh_commands_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """管理员刷新所有用户的命令列表（解决新功能不显示问题）"""
    try:
        user_id = update.effective_user.id
        user_manager = get_user_manager(context)
        
        # 检查是否为管理员
        if not await is_admin(user_id, context):
            await send_error(
                context,
                update.effective_chat.id,
                "❌ 只有管理员可以执行此操作"
            )
            if update.message:
                await delete_user_command(context, update.effective_chat.id, update.message.message_id)
            return
        
        if not user_manager:
            await send_error(
                context,
                update.effective_chat.id,
                "❌ 用户管理器未初始化"
            )
            if update.message:
                await delete_user_command(context, update.effective_chat.id, update.message.message_id)
            return
        
        # 发送开始处理消息
        processing_msg = await send_info(
            context,
            update.effective_chat.id,
            "🔄 正在刷新全局和所有用户群组的命令列表..."
        )
        
        success_count = 0
        error_count = 0
        
        # 1. 首先更新全局默认命令（给所有普通用户）
        try:
            from telegram import BotCommand
            none_commands = command_factory.get_command_list(Permission.NONE)
            basic_bot_commands = [BotCommand(command, description) for command, description in none_commands.items()]
            await context.bot.set_my_commands(basic_bot_commands)
            success_count += 1
            logger.info("已更新全局默认命令列表")
        except Exception as e:
            logger.error(f"更新全局默认命令失败: {e}")
            error_count += 1
        
        # 刷新所有白名单用户
        whitelist_users = await user_manager.get_whitelisted_users()
        for whitelist_user_id in whitelist_users:
            try:
                is_admin_user = await is_admin(whitelist_user_id, context)
                await update_user_command_menu(whitelist_user_id, context, True, is_admin_user)
                success_count += 1
            except Exception as e:
                logger.error(f"刷新用户 {whitelist_user_id} 命令失败: {e}")
                error_count += 1
        
        # 刷新所有管理员（确保管理员都有完整命令）
        admin_users = await user_manager.get_all_admins()
        for admin_user_id in admin_users:
            try:
                await update_user_command_menu(admin_user_id, context, True, True)
                if admin_user_id not in whitelist_users:  # 避免重复计数
                    success_count += 1
            except Exception as e:
                logger.error(f"刷新管理员 {admin_user_id} 命令失败: {e}")
                error_count += 1
        
        # 刷新所有白名单群组
        whitelist_groups = await user_manager.get_whitelisted_groups()
        for group_data in whitelist_groups:
            try:
                group_id = group_data['group_id']  # 从字典中获取group_id
                await update_group_command_menu(group_id, context, True)
                success_count += 1
            except Exception as e:
                group_id = group_data.get('group_id', 'unknown')
                logger.error(f"刷新群组 {group_id} 命令失败: {e}")
                error_count += 1
        
        # 删除处理消息
        try:
            await processing_msg.delete()
        except:
            pass
        
        # 发送结果消息
        result_text = f"✅ 命令列表刷新完成！\n\n📊 统计信息：\n• 成功刷新：{success_count} 个\n• 失败：{error_count} 个\n\n📋 刷新范围：\n• 全局默认命令（所有用户）\n• 白名单用户个人命令\n• 管理员个人命令\n• 白名单群组命令"
        if error_count > 0:
            result_text += "\n\n⚠️ 部分项目刷新失败，请查看日志"
        
        await send_success(
            context,
            update.effective_chat.id,
            result_text
        )
        
        # 删除用户命令
        if update.message:
            await delete_user_command(context, update.effective_chat.id, update.message.message_id)
        
        logger.info(f"管理员 {user_id} 已刷新所有用户命令列表，成功：{success_count}，失败：{error_count}")
        
    except Exception as e:
        logger.error(f"批量刷新命令列表失败: {e}")
        await send_error(
            context,
            update.effective_chat.id,
            "❌ 批量刷新命令列表失败，请稍后重试"
        )
        
        if update.message:
            await delete_user_command(context, update.effective_chat.id, update.message.message_id)

async def refresh_my_commands_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """用户刷新自己的命令列表"""
    try:
        user_id = update.effective_user.id
        user_manager = get_user_manager(context)
        
        # 检查用户权限
        is_admin_user = await is_admin(user_id, context)
        is_whitelist_user = False
        
        if user_manager:
            is_whitelist_user = await user_manager.is_whitelisted(user_id)
        
        # 更新用户命令菜单
        await update_user_command_menu(user_id, context, is_whitelist_user, is_admin_user)
        
        # 发送成功消息
        status = "管理员" if is_admin_user else ("白名单用户" if is_whitelist_user else "普通用户")
        await send_success(
            context,
            update.effective_chat.id,
            f"✅ 你的命令列表已刷新！\n\n👤 权限等级：{status}\n💡 现在可以看到所有可用命令了"
        )
        
        # 删除用户命令
        if update.message:
            await delete_user_command(context, update.effective_chat.id, update.message.message_id)
        
        logger.info(f"用户 {user_id} 已刷新自己的命令列表，权限：{status}")
        
    except Exception as e:
        logger.error(f"刷新个人命令列表失败: {e}")
        await send_error(
            context,
            update.effective_chat.id,
            "❌ 刷新命令列表失败，请稍后重试"
        )
        
        if update.message:
            await delete_user_command(context, update.effective_chat.id, update.message.message_id)

# 注册刷新命令
command_factory.register_command("refresh_all", refresh_commands_command, permission=Permission.ADMIN, description="管理员刷新所有用户命令列表")
command_factory.register_command("refresh", refresh_my_commands_command, permission=Permission.NONE, description="刷新我的命令列表")

