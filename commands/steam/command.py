# Description: Steam 模块的命令处理器
# 从原 steam.py 拆分

import logging

from telegram import Update
from telegram.ext import ContextTypes

from utils.command_factory import command_factory
from utils.formatter import foldable_text_v2, foldable_text_with_markdown_v2
from utils.message_manager import (
    delete_user_command,
    send_error,
    send_help,
    send_success,
)
from utils.permissions import Permission
from utils.session_manager import steam_search_sessions

from .models import Config, ErrorHandler
from .parser import get_country_code
from .search import search_game
from .ui import (
    create_steam_search_keyboard,
    format_steam_search_results,
)

logger = logging.getLogger(__name__)
config = Config()
error_handler = ErrorHandler()


async def steam_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /steam 命令进行游戏价格查询（带交互式搜索）"""
    if not update.message:
        return

    if not context.args:
        help_message = (
            "*🎮 Steam游戏价格查询*\n"
            "_Author:_ Domo\n\n"
            "*指令列表：*\n"
            "`/steam` [游戏名称/ID] [国家代码] - 查询游戏价格\n"
            "`/steamcc` - 清理缓存\n\n"
            "*功能说明：*\n"
            "• 支持跨区价格对比,可同时查询多个地区,用空格分隔\n"
            "• 自动转换为人民币显示价格参考\n"
            "• 智能解析价格格式，支持多种货币符号\n"
            "• 支持查询捆绑包价格和内容\n"
            "• 使用OpenExchangeRate免费API进行汇率转换\n"
            "• 价格数据缓存3天,汇率每小时更新\n"
            "• 游戏ID永久缓存,无需重复获取\n\n"
            "*使用示例：*\n"
            "• `/steam 双人成行` - 查询国区价格\n"
            "• `/steam CS2 US RU TR AR` - 查询多区价格\n\n"
            "*提示：* 默认使用中国区(CN)查询"
        )
        await send_help(
            context,
            update.message.chat_id,
            foldable_text_with_markdown_v2(help_message),
            parse_mode="MarkdownV2",
        )
        await delete_user_command(
            context, update.message.chat_id, update.message.message_id
        )
        return

    user_id = update.effective_user.id

    loading_message = "🔍 正在搜索游戏... ⏳"
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=foldable_text_v2(loading_message),
        parse_mode="MarkdownV2",
    )

    args = context.args
    # 解析参数：分离游戏名称和国家代码
    country_inputs = []
    game_name_parts = []

    for arg in reversed(args):
        country_code = get_country_code(arg)
        if country_code:
            country_inputs.insert(0, arg)
        else:
            game_name_parts = args[: len(args) - len(country_inputs)]
            break

    query = " ".join(game_name_parts)
    if not country_inputs:
        country_inputs = [config.DEFAULT_CC]

    try:
        # 搜索游戏 (不使用缓存，确保每次都显示完整搜索结果)
        search_results = await search_game(query, country_inputs[0], use_cache=False)

        if not search_results:
            error_message = f"🔍 没有找到关键词 '{query}' 的相关内容"
            await message.edit_text(
                foldable_text_v2(error_message), parse_mode="MarkdownV2"
            )
            return

        # 始终显示交互式搜索界面
        per_page = 5
        total_results = len(search_results)
        total_pages = (
            min(10, (total_results + per_page - 1) // per_page)
            if total_results > 0
            else 1
        )

        page_results = search_results[0:per_page]

        search_data_for_session = {
            "query": query,
            "country_inputs": country_inputs,
            "all_results": search_results,
            "current_page": 1,
            "total_pages": total_pages,
            "total_results": total_results,
            "per_page": per_page,
            "results": page_results,
        }

        # 存储用户搜索会话
        steam_search_sessions[user_id] = {
            "query": query,
            "search_data": search_data_for_session,
            "message_id": message.message_id,
            "country_inputs": country_inputs,
        }

        # 格式化并显示结果
        result_text = format_steam_search_results(search_data_for_session)
        keyboard = create_steam_search_keyboard(search_data_for_session)

        await message.edit_text(
            foldable_text_v2(result_text),
            reply_markup=keyboard,
            parse_mode="MarkdownV2",
            disable_web_page_preview=True,
        )

        # 计划自动删除消息
        await delete_user_command(
            context, update.effective_chat.id, update.message.message_id
        )

    except Exception as e:
        error_msg = error_handler.log_error(e, "搜索游戏")
        await message.delete()
        await send_error(
            context,
            update.effective_chat.id,
            foldable_text_v2(error_msg),
            parse_mode="MarkdownV2",
        )
        await delete_user_command(
            context, update.effective_chat.id, update.message.message_id
        )


async def steam_clean_cache_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /steamcc 命令清理 Steam 缓存"""
    if not update.message:
        return

    try:
        cache_mgr = context.bot_data.get("cache_manager")
        if cache_mgr is not None:
            await cache_mgr.clear_cache(subdirectory="steam")
            success_message = "✅ Steam 缓存已清理。"
            await send_success(
                context,
                update.message.chat_id,
                foldable_text_v2(success_message),
                parse_mode="MarkdownV2",
            )
            await delete_user_command(
                context, update.message.chat_id, update.message.message_id
            )
        else:
            error_message = "❌ 缓存管理器未初始化。"
            await send_error(
                context,
                update.message.chat_id,
                foldable_text_v2(error_message),
                parse_mode="MarkdownV2",
            )
            await delete_user_command(
                context, update.message.chat_id, update.message.message_id
            )
    except Exception as e:
        logger.error(f"Error clearing Steam cache: {e}")
        error_msg = f"❌ 清理 Steam 缓存时发生错误: {e}"
        await send_error(
            context,
            update.message.chat_id,
            foldable_text_v2(error_msg),
            parse_mode="MarkdownV2",
        )
        await delete_user_command(
            context, update.message.chat_id, update.message.message_id
        )


async def steam_clear_item_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """清理指定 Steam 条目（游戏或捆绑包）的缓存（Redis+MySQL）。

    用法:
      /steam_clearitem <AppID|bundle_捆绑ID> [国家...]
      例如: /steam_clearitem 730 US CN
            /steam_clearitem bundle_216938 US
    """
    if not update.message:
        return

    # 权限校验
    user_manager = context.bot_data.get("user_cache_manager")
    if not user_manager or not update.effective_user:
        return
    user_id = update.effective_user.id
    if not (
        await user_manager.is_super_admin(user_id)
        or await user_manager.is_admin(user_id)
    ):
        await send_error(
            context,
            update.message.chat_id,
            foldable_text_v2("❌ 你没有缓存管理权限。"),
            parse_mode="MarkdownV2",
        )
        return

    # 删除用户命令消息
    await delete_user_command(
        context, update.message.chat_id, update.message.message_id
    )

    if not context.args:
        await send_error(
            context,
            update.message.chat_id,
            foldable_text_v2(
                "❌ 用法: /steam_clearitem <AppID|bundle_捆绑ID> [国家...]"
            ),
            parse_mode="MarkdownV2",
        )
        return

    target = context.args[0].strip().lower()
    is_bundle = False
    bundle_id = None
    app_id = None

    if target.startswith("bundle_"):
        is_bundle = True
        bundle_id = target.split("_", 1)[1]
        if not bundle_id.isdigit():
            await send_error(
                context,
                update.message.chat_id,
                foldable_text_v2("❌ 捆绑包ID格式不正确，应为 bundle_<数字>"),
                parse_mode="MarkdownV2",
            )
            return
    else:
        if not target.isdigit():
            await send_error(
                context,
                update.message.chat_id,
                foldable_text_v2("❌ AppID 格式不正确，应为数字，或使用 bundle_<ID>"),
                parse_mode="MarkdownV2",
            )
            return
        app_id = target

    # 解析可选国家
    from .parser import get_country_code

    countries = []
    for p in context.args[1:]:
        code = get_country_code(p)
        if code and code not in countries:
            countries.append(code)

    cache_mgr = context.bot_data.get("cache_manager")
    db_mgr = context.bot_data.get("price_history_manager")

    # 清理 Redis
    try:
        if cache_mgr:
            if is_bundle:
                if countries:
                    for c in countries:
                        prefix = f"steam:bundle:{bundle_id}:{c.upper()}"
                        await cache_mgr.clear_cache(
                            key_prefix=prefix, subdirectory="steam"
                        )
                else:
                    prefix = f"steam:bundle:{bundle_id}:"
                    await cache_mgr.clear_cache(key_prefix=prefix, subdirectory="steam")
            else:
                if countries:
                    for c in countries:
                        prefix = f"steam:game:{app_id}:{c.upper()}"
                        await cache_mgr.clear_cache(
                            key_prefix=prefix, subdirectory="steam"
                        )
                else:
                    prefix = f"steam:game:{app_id}:"
                    await cache_mgr.clear_cache(key_prefix=prefix, subdirectory="steam")
    except Exception as e:
        await send_error(
            context,
            update.message.chat_id,
            foldable_text_v2(f"❌ 清理 Redis 失败: {e!s}"),
            parse_mode="MarkdownV2",
        )
        return

    # 清理 MySQL
    deleted_db = 0
    try:
        if db_mgr:
            if is_bundle:
                item_id = f"bundle_{bundle_id}"
            else:
                item_id = app_id

            if countries:
                for c in countries:
                    deleted_db += await db_mgr.delete_item(
                        service="steam", item_id=item_id, country_code=c
                    )
            else:
                deleted_db += await db_mgr.delete_item(service="steam", item_id=item_id)
    except Exception as e:
        await send_error(
            context,
            update.message.chat_id,
            foldable_text_v2(f"❌ 清理 MySQL 失败: {e!s}"),
            parse_mode="MarkdownV2",
        )
        return

    scope_text = ", ".join([c.upper() for c in countries]) if countries else "所有国家"
    target_text = f"bundle_{bundle_id}" if is_bundle else app_id
    await send_success(
        context,
        update.message.chat_id,
        foldable_text_v2(
            f"✅ 已清理 Steam 缓存\n• 目标: {target_text}\n• 范围: {scope_text}\n• MySQL 删除记录: {deleted_db}"
        ),
        parse_mode="MarkdownV2",
    )


# 注册命令
command_factory.register_command(
    "steam", steam_command, permission=Permission.USER, description="Steam游戏价格查询"
)
command_factory.register_command(
    "steamcc",
    steam_clean_cache_command,
    permission=Permission.ADMIN,
    description="清理Steam缓存",
)
command_factory.register_command(
    "steam_clearitem",
    steam_clear_item_command,
    permission=Permission.ADMIN,
    description="清理Steam指定条目缓存（Redis+MySQL）",
)
async def steam_bundle_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /steamb command for bundle price lookup with interactive search."""
    # 检查update.message是否存在
    if not update.message:
        return

    # 检查steam_checker是否已初始化
    if steam_checker is None:
        error_message = "❌ Steam功能未初始化，请稍后重试。"
        # 生成会话ID用于消息管理
        import time
        user_id = update.effective_user.id
        session_id = f"steam_init_error_{user_id}_{int(time.time())}"
        
        await send_message_with_auto_delete(
            context,
            update.message.chat_id,
            foldable_text_v2(error_message),
            MessageType.ERROR,
            session_id=session_id,
            parse_mode="MarkdownV2"
        )
        await delete_user_command(context, update.message.chat_id, update.message.message_id, session_id=session_id)
        return

    if not context.args:
        error_message = "请提供捆绑包名称或ID。"
        # 生成会话ID用于消息管理
        import time
        user_id = update.effective_user.id
        session_id = f"steamb_error_{user_id}_{int(time.time())}"
        
        await send_message_with_auto_delete(
            context,
            update.message.chat_id,
            foldable_text_v2(error_message),
            MessageType.ERROR,
            session_id=session_id,
            parse_mode="MarkdownV2"
        )
        await delete_user_command(context, update.message.chat_id, update.message.message_id, session_id=session_id)
        return

    user_id = update.effective_user.id

    loading_message = "🔍 正在搜索捆绑包... ⏳"
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
            text=foldable_text_v2(loading_message),
        parse_mode="MarkdownV2"
    )

    args = context.args
    if len(args) >= 2 and steam_checker.get_country_code(args[-1]):
        query = ' '.join(args[:-1])
        cc = steam_checker.get_country_code(args[-1]) or steam_checker.config.DEFAULT_CC
    else:
        query = ' '.join(args)
        cc = steam_checker.config.DEFAULT_CC

    try:
        # 搜索捆绑包
        search_results = []

        if query.isdigit():
            # 通过ID搜索
            bundle_details = await steam_checker.search_bundle_by_id(query, cc)
            if bundle_details:
                search_results = [{
                    'id': query,
                    'name': bundle_details.get('name', '未知捆绑包'),
                    'url': bundle_details.get('url', ''),
                    'score': 100
                }]
        else:
            # 通过名称搜索
            search_results = await steam_checker.search_bundle(query, cc)

        if not search_results:
            error_lines = [
                "❌ 未找到相关捆绑包",
                f"搜索词: `{query}`"
            ]
            error_text = "\n".join(error_lines)
            await message.edit_text(
                foldable_text_v2(error_text),
                parse_mode="MarkdownV2"
            )
            return

        # 总是显示交互式列表选择，即使只有一个结果
        per_page = 5
        total_results = len(search_results)
        total_pages = min(10, (total_results + per_page - 1) // per_page) if total_results > 0 else 1

        page_results = search_results[0:per_page]

        search_data_for_session = {
            "query": query,
            "cc": cc,
            "all_results": search_results,
            "current_page": 1,
            "total_pages": total_pages,
            "total_results": total_results,
            "per_page": per_page,
            "results": page_results
        }

        # 生成会话ID用于消息管理
        import time
        session_id = f"steam_bundle_{user_id}_{int(time.time())}"

        # 存储用户搜索会话
        bundle_search_sessions[user_id] = {
            "query": query,
            "search_data": search_data_for_session,
            "message_id": message.message_id,
            "cc": cc,
            "session_id": session_id
        }

        # 格式化并显示结果
        result_text = format_bundle_search_results(search_data_for_session)
        keyboard = create_bundle_search_keyboard(search_data_for_session)

        # 删除搜索进度消息，然后发送新的搜索结果消息
        await message.delete()
        
        # 使用统一的消息发送API发送搜索结果
        new_message = await send_message_with_auto_delete(
            context,
            update.effective_chat.id,
            foldable_text_v2(result_text),
            MessageType.SEARCH_RESULT,
            session_id=session_id,
            reply_markup=keyboard,
            parse_mode="MarkdownV2",
            disable_web_page_preview=True
        )
        
        # 更新会话中的消息ID
        if new_message:
            bundle_search_sessions[user_id]["message_id"] = new_message.message_id

        # 删除用户命令消息
        await delete_user_command(context, update.effective_chat.id, update.message.message_id, session_id=session_id)

    except Exception as e:
        error_msg = f"❌ 查询捆绑包出错: {e}"
        await message.delete()
        
        # 生成会话ID用于消息管理
        import time
        session_id = f"steamb_error_{user_id}_{int(time.time())}"
        
        await send_message_with_auto_delete(
            context,
            update.effective_chat.id,
            foldable_text_v2(error_msg),
            MessageType.ERROR,
            session_id=session_id,
            parse_mode="MarkdownV2"
        )
        await delete_user_command(context, update.effective_chat.id, update.message.message_id, session_id=session_id)



async def steam_search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /steams command for comprehensive search."""
    # 检查update.message是否存在
    if not update.message:
        return

    # 检查steam_checker是否已初始化
    if steam_checker is None:
        error_message = "❌ Steam功能未初始化，请稍后重试。"
        # 生成会话ID用于消息管理
        import time
        user_id = update.effective_user.id
        session_id = f"steam_init_error_{user_id}_{int(time.time())}"
        
        await send_message_with_auto_delete(
            context,
            update.message.chat_id,
            foldable_text_v2(error_message),
            MessageType.ERROR,
            session_id=session_id,
            parse_mode="MarkdownV2"
        )
        await delete_user_command(context, update.message.chat_id, update.message.message_id, session_id=session_id)
        return

    if not context.args:
        error_message = "请提供搜索关键词。"
        # 生成会话ID用于消息管理
        import time
        user_id = update.effective_user.id
        session_id = f"steams_error_{user_id}_{int(time.time())}"
        
        await send_message_with_auto_delete(
            context,
            update.message.chat_id,
            foldable_text_v2(error_message),
            MessageType.ERROR,
            session_id=session_id,
            parse_mode="MarkdownV2"
        )
        await delete_user_command(context, update.message.chat_id, update.message.message_id, session_id=session_id)
        return

    loading_message = "🔍 正在查询中... ⏳"
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
            text=foldable_text_v2(loading_message),
        parse_mode="MarkdownV2"
    )

    query = ' '.join(context.args)
    cc = steam_checker.config.DEFAULT_CC
    
    # 生成会话ID用于消息管理
    import time
    user_id = update.effective_user.id
    session_id = f"steam_search_all_{user_id}_{int(time.time())}"
    
    try:
        result = await steam_checker.search_and_format_all(query, cc)
        await message.delete()
        
        # 使用统一的消息发送API
        await send_message_with_auto_delete(
            context,
            update.effective_chat.id,
            foldable_text_with_markdown_v2(result),
            MessageType.SEARCH_RESULT,
            session_id=session_id,
            parse_mode="MarkdownV2"
        )
        await delete_user_command(context, update.effective_chat.id, update.message.message_id, session_id=session_id)
    except Exception as e:
        error_msg = f"❌ 综合搜索出错: {e}"
        await message.delete()
        
        # 生成会话ID用于消息管理
        import time
        session_id = f"steams_error_{user_id}_{int(time.time())}"
        
        await send_message_with_auto_delete(
            context,
            update.effective_chat.id,
            foldable_text_v2(error_msg),
            MessageType.ERROR,
            session_id=session_id,
            parse_mode="MarkdownV2"
        )
        await delete_user_command(context, update.effective_chat.id, update.message.message_id, session_id=session_id)

async def steam_clean_cache_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /steamcc command to clear Steam cache."""
    if not update.message:
        return

    if steam_checker is None:
        error_message = "❌ Steam功能未初始化，请稍后重试。"
        # 生成会话ID用于消息管理
        import time
        user_id = update.effective_user.id
        session_id = f"steamcc_init_error_{user_id}_{int(time.time())}"
        
        await send_message_with_auto_delete(
            context,
            update.message.chat_id,
            foldable_text_v2(error_message),
            MessageType.ERROR,
            session_id=session_id,
            parse_mode="MarkdownV2"
        )
        await delete_user_command(context, update.message.chat_id, update.message.message_id, session_id=session_id)
        return

    try:
        # 从 context 获取缓存管理器
        cache_mgr = context.bot_data.get("cache_manager")
        if cache_mgr is not None:
            await cache_mgr.clear_cache(subdirectory="steam")
            success_message = "✅ Steam 缓存已清理。"
            # 生成会话ID用于消息管理
            import time
            user_id = update.effective_user.id
            session_id = f"steamcc_success_{user_id}_{int(time.time())}"
            
            await send_message_with_auto_delete(
                context,
                update.message.chat_id,
                foldable_text_v2(success_message),
                MessageType.SUCCESS,
                session_id=session_id,
                parse_mode="MarkdownV2"
            )
            await delete_user_command(context, update.message.chat_id, update.message.message_id, session_id=session_id)
        else:
            error_message = "❌ 缓存管理器未初始化。"
            # 生成会话ID用于消息管理
            import time
            user_id = update.effective_user.id
            session_id = f"steamcc_error_{user_id}_{int(time.time())}"
            
            await send_message_with_auto_delete(
                context,
                update.message.chat_id,
                foldable_text_v2(error_message),
                MessageType.ERROR,
                session_id=session_id,
                parse_mode="MarkdownV2"
            )
            await delete_user_command(context, update.message.chat_id, update.message.message_id, session_id=session_id)
    except Exception as e:
        logger.error(f"Error clearing Steam cache: {e}")
        error_msg = f"❌ 清理 Steam 缓存时发生错误: {e}"
        # 生成会话ID用于消息管理
        import time
        user_id = update.effective_user.id
        session_id = f"steamcc_error_{user_id}_{int(time.time())}"
        
        await send_message_with_auto_delete(
            context,
            update.message.chat_id,
            foldable_text_v2(error_msg),
            MessageType.ERROR,
            session_id=session_id,
            parse_mode="MarkdownV2"
        )
        await delete_user_command(context, update.message.chat_id, update.message.message_id, session_id=session_id)

async def steam_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理Steam搜索结果的内联键盘回调"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    callback_data = query.data

    # 检查用户是否有活跃的搜索会话
    if user_id not in user_search_sessions:
        await query.edit_message_text(
            foldable_text_v2("❌ 搜索会话已过期，请重新搜索"),
            parse_mode="MarkdownV2"
        )

        # 注：使用 query.edit_message_text 无需额外调度删除
        return

    session = user_search_sessions[user_id]
    search_data = session["search_data"]

    try:
        if callback_data.startswith("steam_select_"):
            # 用户选择了一个游戏
            parts = callback_data.split("_")
            game_index = int(parts[2])
            page = int(parts[3])

            # 计算实际的游戏索引
            actual_index = (page - 1) * search_data["per_page"] + game_index

            if actual_index < len(search_data["all_results"]):
                selected_item = search_data["all_results"][actual_index]
                item_id = selected_item.get('id')
                item_type = selected_item.get('type', 'game')

                if item_id:
                    # 显示加载消息
                    await query.edit_message_text(
                        foldable_text_v2("🔍 正在获取详细信息... ⏳"),
                        parse_mode="MarkdownV2"
                    )

                    # 根据类型处理不同的内容
                    if item_type == 'bundle':
                        # 处理捆绑包
                        country_inputs = session["country_inputs"]
                        cc = steam_checker.get_country_code(country_inputs[0]) or steam_checker.config.DEFAULT_CC
                        bundle_details = await steam_checker.get_bundle_details(str(item_id), cc)

                        if bundle_details:
                            result = await steam_checker.format_bundle_info(bundle_details, cc)
                        else:
                            result = "❌ 无法获取捆绑包信息"
                    else:
                        # 处理游戏和DLC
                        country_inputs = session["country_inputs"]
                        result = await steam_checker.search_multiple_countries(str(item_id), country_inputs)

                    await query.edit_message_text(
                        foldable_text_with_markdown_v2(result),
                        parse_mode="MarkdownV2"
                    )

                    # 清理用户会话
                    if user_id in user_search_sessions:
                        del user_search_sessions[user_id]
                else:
                    await query.edit_message_text(
                        foldable_text_v2("❌ 无法获取内容ID"),
                        parse_mode="MarkdownV2"
                    )
            else:
                await query.edit_message_text(
                    foldable_text_v2("❌ 选择的内容索引无效"),
                    parse_mode="MarkdownV2"
                )

        elif callback_data.startswith("steam_page_"):
            # 分页操作
            if callback_data == "steam_page_info":
                # 页面信息，不执行任何操作
                return

            page_num = int(callback_data.split("_")[2])
            current_page = search_data["current_page"]
            total_pages = search_data["total_pages"]

            if 1 <= page_num <= total_pages and page_num != current_page:
                # 更新页面数据
                per_page = search_data["per_page"]
                start_index = (page_num - 1) * per_page
                end_index = start_index + per_page
                page_results = search_data["all_results"][start_index:end_index]

                search_data["current_page"] = page_num
                search_data["results"] = page_results

                # 更新键盘和消息
                result_text = format_steam_search_results(search_data)
                keyboard = create_steam_search_keyboard(search_data)

                await query.edit_message_text(
                    foldable_text_v2(result_text),
                    reply_markup=keyboard,
                    parse_mode="MarkdownV2"
                )

        elif callback_data == "steam_new_search":
            # 新搜索
            await query.edit_message_text(
                foldable_text_v2("🔍 请使用 /steam [游戏名称] 开始新的搜索"),
                parse_mode="MarkdownV2"
            )

            # 清理用户会话
            if user_id in user_search_sessions:
                del user_search_sessions[user_id]

        elif callback_data == "steam_change_region":
            # 更改搜索地区
            change_region_text = "请选择新的搜索地区："

            # 定义地区按钮
            region_buttons = [
                InlineKeyboardButton("🇨🇳 中国", callback_data="steam_region_CN"),
                InlineKeyboardButton("🇭🇰 香港", callback_data="steam_region_HK"),
                InlineKeyboardButton("🇹🇼 台湾", callback_data="steam_region_TW"),
                InlineKeyboardButton("🇯🇵 日本", callback_data="steam_region_JP"),
                InlineKeyboardButton("🇺🇸 美国", callback_data="steam_region_US"),
                InlineKeyboardButton("🇬🇧 英国", callback_data="steam_region_GB"),
                InlineKeyboardButton("🇷🇺 俄罗斯", callback_data="steam_region_RU"),
                InlineKeyboardButton("🇹🇷 土耳其", callback_data="steam_region_TR"),
                InlineKeyboardButton("🇦🇷 阿根廷", callback_data="steam_region_AR"),
                InlineKeyboardButton("❌ 关闭", callback_data="steam_close")
            ]

            # 每行2个按钮
            keyboard = [region_buttons[i:i+2] for i in range(0, len(region_buttons), 2)]

            await query.edit_message_text(
                foldable_text_v2(change_region_text),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="MarkdownV2"
            )

        elif callback_data.startswith("steam_region_"):
            # 用户选择了新的搜索地区
            country_code = callback_data.split("_")[2]

            # 更新会话中的国家输入
            session["country_inputs"] = [country_code]
            search_data["country_inputs"] = [country_code]

            # 显示重新搜索消息
            query_text = search_data["query"]
            loading_message = f"🔍 正在在 {country_code.upper()} 区域重新搜索 '{query_text}'..."
            await query.edit_message_text(foldable_text_v2(loading_message), parse_mode="MarkdownV2")

            # 重新搜索游戏
            try:
                search_results = await steam_checker.search_game(query_text, country_code, use_cache=False)

                if not search_results:
                    error_message = f"🔍 在 {country_code.upper()} 区域没有找到关键词 '{query_text}' 的相关内容"
                    await query.edit_message_text(
                        foldable_text_v2(error_message),
                        parse_mode="MarkdownV2"
                    )
                    return

                # 更新搜索数据
                per_page = 5
                total_results = len(search_results)
                total_pages = min(10, (total_results + per_page - 1) // per_page) if total_results > 0 else 1
                page_results = search_results[0:per_page]

                search_data.update({
                    "all_results": search_results,
                    "current_page": 1,
                    "total_pages": total_pages,
                    "total_results": total_results,
                    "per_page": per_page,
                    "results": page_results
                })

                # 显示新的搜索结果
                result_text = format_steam_search_results(search_data)
                keyboard = create_steam_search_keyboard(search_data)

                await query.edit_message_text(
                    foldable_text_v2(result_text),
                    reply_markup=keyboard,
                    parse_mode="MarkdownV2",
                    disable_web_page_preview=True
                )

            except Exception as e:
                error_message = f"❌ 重新搜索失败: {e!s}"
                await query.edit_message_text(
                    foldable_text_v2(error_message),
                    parse_mode="MarkdownV2"
                )

        elif callback_data == "steam_close":
            # 关闭搜索
            await query.edit_message_text(
                foldable_text_v2("🎮 Steam搜索已关闭"),
                parse_mode="MarkdownV2"
            )

            # 注：使用 query.edit_message_text 无需额外调度删除

            # 清理用户会话
            if user_id in user_search_sessions:
                del user_search_sessions[user_id]

    except Exception as e:
        logger.error(f"Error in steam callback handler: {e}")
        await query.edit_message_text(
            foldable_text_v2(f"❌ 处理请求时发生错误: {e!s}"),
            parse_mode="MarkdownV2"
        )

        # 注：使用 query.edit_message_text 无需额外调度删除

# steamb 内联键盘回调处理
def format_bundle_search_results(search_data: dict) -> str:
    if search_data.get("error"):
        return f"❌ 搜索失败: {search_data['error']}"

    results = search_data["results"]
    query = search_data["query"]
    cc = search_data.get("cc", "CN")

    if not results:
        return f"🔍 在 {cc.upper()} 区域没有找到关键词 '{query}' 的相关捆绑包"

    # 获取国家标志和名称
    country_flag = get_country_flag(cc)
    country_info = SUPPORTED_COUNTRIES.get(cc, {"name": cc})
    country_name = country_info.get("name", cc)

    total_results = search_data.get("total_results", len(results))
    current_page = search_data.get("current_page", 1)
    total_pages = search_data.get("total_pages", 1)

    header_parts = [
        "🛍 Steam捆绑包搜索结果",
        f"🔍 关键词: {query}",
        f"🌍 搜索地区: {country_flag} {country_name} ({cc.upper()})",
        f"📊 找到 {total_results} 个结果 (第 {current_page}/{total_pages} 页)",
        "",
        "请从下方选择您要查询的捆绑包："
    ]

    return "\n".join(header_parts)

def create_bundle_search_keyboard(search_data: dict) -> InlineKeyboardMarkup:
    keyboard = []
    results = search_data["results"]
    for i in range(min(len(results), 5)):
        bundle = results[i]
        bundle_name = bundle.get("name", "未知捆绑包")
        if len(bundle_name) > 37:
            bundle_name = bundle_name[:34] + "..."
        callback_data = f"steamb_select_{i}_{search_data.get('current_page', 1)}"
        display_name = f"{i + 1}. 🛍 {bundle_name}"
        keyboard.append([InlineKeyboardButton(display_name, callback_data=callback_data)])
    current_page = search_data.get("current_page", 1)
    total_pages = search_data.get("total_pages", 1)
    nav_row = []
    if current_page > 1:
        nav_row.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"steamb_page_{current_page - 1}"))
    nav_row.append(InlineKeyboardButton(f"📄 {current_page}/{total_pages}", callback_data="steamb_page_info"))
    if current_page < total_pages:
        nav_row.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"steamb_page_{current_page + 1}"))
    if nav_row:
        keyboard.append(nav_row)
    action_row = [
        InlineKeyboardButton("🌍 更改搜索地区", callback_data="steamb_change_region"),
        InlineKeyboardButton("❌ 关闭", callback_data="steamb_close")
    ]
    keyboard.append(action_row)
    return InlineKeyboardMarkup(keyboard)

# 使用统一的会话管理器替代全局字典

async def steamb_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    callback_data = query.data
    if user_id not in bundle_search_sessions:
        await query.edit_message_text(
            foldable_text_v2("❌ 搜索会话已过期，请重新搜索"),
            parse_mode="MarkdownV2"
        )

        # 注：使用 query.edit_message_text 无需额外调度删除
        return
    session = bundle_search_sessions[user_id]
    search_data = session["search_data"]
    cc = search_data.get("cc") or "CN"
    try:
        if callback_data.startswith("steamb_select_"):
            parts = callback_data.split("_")
            bundle_index = int(parts[2])
            page = int(parts[3])
            actual_index = (page - 1) * search_data["per_page"] + bundle_index
            if actual_index < len(search_data["all_results"]):
                selected_bundle = search_data["all_results"][actual_index]
                bundle_id = selected_bundle.get('id')
                if bundle_id:
                    await query.edit_message_text(
                        foldable_text_v2("🔍 正在获取捆绑包详细信息... ⏳"),
                        parse_mode="MarkdownV2"
                    )
                    bundle_details = await steam_checker.get_bundle_details(str(bundle_id), cc)
                    if bundle_details:
                        result = await steam_checker.format_bundle_info(bundle_details, cc)
                    else:
                        result = "❌ 无法获取捆绑包信息"
                    await query.edit_message_text(
                        foldable_text_with_markdown_v2(result),
                        parse_mode="MarkdownV2"
                    )
                    if user_id in bundle_search_sessions:
                        del bundle_search_sessions[user_id]
                else:
                    await query.edit_message_text(
                        foldable_text_v2("❌ 无法获取捆绑包ID"),
                        parse_mode="MarkdownV2"
                    )
            else:
                await query.edit_message_text(
                    foldable_text_v2("❌ 选择的捆绑包索引无效"),
                    parse_mode="MarkdownV2"
                )
        elif callback_data.startswith("steamb_page_"):
            if callback_data == "steamb_page_info":
                return
            page_num = int(callback_data.split("_")[2])
            current_page = search_data["current_page"]
            total_pages = search_data["total_pages"]
            if 1 <= page_num <= total_pages and page_num != current_page:
                per_page = search_data["per_page"]
                start_index = (page_num - 1) * per_page
                end_index = start_index + per_page
                page_results = search_data["all_results"][start_index:end_index]
                search_data["current_page"] = page_num
                search_data["results"] = page_results
                result_text = format_bundle_search_results(search_data)
                keyboard = create_bundle_search_keyboard(search_data)
                await query.edit_message_text(
                    foldable_text_v2(result_text),
                    reply_markup=keyboard,
                    parse_mode="MarkdownV2"
                )
        elif callback_data == "steamb_new_search":
            await query.edit_message_text(
                foldable_text_v2("🔍 请使用 /steamb [捆绑包名称] 开始新的搜索"),
                parse_mode="MarkdownV2"
            )
            if user_id in bundle_search_sessions:
                del bundle_search_sessions[user_id]
        elif callback_data == "steamb_change_region":
            # 更改搜索地区
            change_region_text = "请选择新的搜索地区："

            # 定义地区按钮
            region_buttons = [
                InlineKeyboardButton("🇨🇳 中国", callback_data="steamb_region_CN"),
                InlineKeyboardButton("🇭🇰 香港", callback_data="steamb_region_HK"),
                InlineKeyboardButton("🇹🇼 台湾", callback_data="steamb_region_TW"),
                InlineKeyboardButton("🇯🇵 日本", callback_data="steamb_region_JP"),
                InlineKeyboardButton("🇺🇸 美国", callback_data="steamb_region_US"),
                InlineKeyboardButton("🇬🇧 英国", callback_data="steamb_region_GB"),
                InlineKeyboardButton("🇷🇺 俄罗斯", callback_data="steamb_region_RU"),
                InlineKeyboardButton("🇹🇷 土耳其", callback_data="steamb_region_TR"),
                InlineKeyboardButton("🇦🇷 阿根廷", callback_data="steamb_region_AR"),
                InlineKeyboardButton("❌ 关闭", callback_data="steamb_close")
            ]

            # 每行2个按钮
            keyboard = [region_buttons[i:i+2] for i in range(0, len(region_buttons), 2)]

            await query.edit_message_text(
                foldable_text_v2(change_region_text),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="MarkdownV2"
            )

        elif callback_data.startswith("steamb_region_"):
            # 用户选择了新的搜索地区
            country_code = callback_data.split("_")[2]

            # 更新会话中的地区信息
            session["cc"] = country_code
            search_data["cc"] = country_code

            # 显示重新搜索消息
            query_text = search_data["query"]
            loading_message = f"🔍 正在在 {country_code.upper()} 区域重新搜索捆绑包 '{query_text}'..."
            await query.edit_message_text(foldable_text_v2(loading_message), parse_mode="MarkdownV2")

            # 重新搜索捆绑包
            try:
                if query_text.isdigit():
                    # 通过ID搜索
                    bundle_details = await steam_checker.search_bundle_by_id(query_text, country_code)
                    if bundle_details:
                        search_results = [{
                            'id': query_text,
                            'name': bundle_details.get('name', '未知捆绑包'),
                            'url': bundle_details.get('url', ''),
                            'score': 100
                        }]
                    else:
                        search_results = []
                else:
                    # 通过名称搜索
                    search_results = await steam_checker.search_bundle(query_text, country_code)

                if not search_results:
                    error_message = f"🔍 在 {country_code.upper()} 区域没有找到关键词 '{query_text}' 的相关捆绑包"
                    await query.edit_message_text(
                        foldable_text_v2(error_message),
                        parse_mode="MarkdownV2"
                    )
                    return

                # 更新搜索数据
                per_page = 5
                total_results = len(search_results)
                total_pages = min(10, (total_results + per_page - 1) // per_page) if total_results > 0 else 1
                page_results = search_results[0:per_page]

                search_data.update({
                    "all_results": search_results,
                    "current_page": 1,
                    "total_pages": total_pages,
                    "total_results": total_results,
                    "per_page": per_page,
                    "results": page_results
                })

                # 显示新的搜索结果
                result_text = format_bundle_search_results(search_data)
                keyboard = create_bundle_search_keyboard(search_data)

                await query.edit_message_text(
                    foldable_text_v2(result_text),
                    reply_markup=keyboard,
                    parse_mode="MarkdownV2",
                    disable_web_page_preview=True
                )

            except Exception as e:
                error_message = f"❌ 重新搜索失败: {e!s}"
                await query.edit_message_text(
                    foldable_text_v2(error_message),
                    parse_mode="MarkdownV2"
                )

        elif callback_data == "steamb_close":
            await query.edit_message_text(
                foldable_text_v2("🛍 捆绑包搜索已关闭"),
                parse_mode="MarkdownV2"
            )

            # 注：使用 query.edit_message_text 无需额外调度删除

            if user_id in bundle_search_sessions:
                del bundle_search_sessions[user_id]
    except Exception as e:
        logger.error(f"Error in steamb callback handler: {e}")
        await query.edit_message_text(
            foldable_text_v2(f"❌ 处理请求时发生错误: {e!s}"),
            parse_mode="MarkdownV2"
        )

        # 注：使用 query.edit_message_text 无需额外调度删除

# Register callback handler
command_factory.register_callback("^steam_", steam_callback_handler, permission=Permission.USER, description="Steam搜索回调处理")
# Register callback handler
command_factory.register_callback("^steamb_", steamb_callback_handler, permission=Permission.USER, description="Steam捆绑包搜索回调处理")

# Register commands
command_factory.register_command("steam", steam_command, permission=Permission.USER, description="Steam游戏价格查询")
command_factory.register_command("steamb", steam_bundle_command, permission=Permission.USER, description="查询捆绑包价格")
# 已迁移到统一缓存管理命令 /cleancache
# command_factory.register_command("steamcc", steam_clean_cache_command, permission=Permission.ADMIN, description="清理Steam缓存")
command_factory.register_command("steams", steam_search_command, permission=Permission.USER, description="综合搜索游戏和捆绑包")


# =============================================================================
# Inline 搜索入口（返回多个结果）
# =============================================================================

async def handle_inline_steam_search(
    keyword: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> list:
    """
    Inline 搜索 Steam 游戏（参考 appstore 的 handle_inline_appstore_search）
    返回多个搜索结果供用户选择

    Args:
        keyword: 搜索关键词，格式为 "游戏名称" 或 "游戏名称 US RU TR"
        context: Telegram context

    Returns:
        list: InlineQueryResult 列表
    """
    from telegram import InlineQueryResultArticle, InputTextMessageContent
    from uuid import uuid4

    if not keyword.strip():
        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="🔍 请输入搜索关键词",
                description="例如: steam elden ring$ 或 steam 双人成行 us ru tr$",
                input_message_content=InputTextMessageContent(
                    message_text="🔍 请输入游戏名称搜索 Steam\n\n"
                    "支持格式:\n"
                    "• steam elden ring$\n"
                    "• steam 双人成行$\n"
                    "• steam CS2 us ru tr$ (多国价格)"
                ),
            )
        ]

    if not steam_checker:
        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="❌ Steam功能未初始化",
                description="请稍后重试",
                input_message_content=InputTextMessageContent(
                    message_text="❌ Steam功能未初始化，请稍后重试"
                ),
            )
        ]

    try:
        # 解析游戏名称和国家参数
        all_params = keyword.strip().split()

        # 分离游戏名称和国家代码
        game_name_parts = []
        country_inputs = []

        for param in all_params:
            country_code = steam_checker.get_country_code(param)
            if country_code:
                country_inputs.append(param)
            else:
                # 如果已经开始收集国家代码，后面的都当作国家代码
                if country_inputs:
                    country_inputs.append(param)
                else:
                    game_name_parts.append(param)

        if not game_name_parts:
            return [
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title="❌ 请输入游戏名称",
                    description="搜索关键词不能为空",
                    input_message_content=InputTextMessageContent(
                        message_text="❌ 请输入游戏名称"
                    ),
                )
            ]

        game_query = " ".join(game_name_parts)

        # 确定要查询的国家列表（默认只查中国区）
        if not country_inputs:
            country_inputs = ["CN"]

        # 默认在第一个国家搜索
        search_country = steam_checker.get_country_code(country_inputs[0]) or "CN"

        # 执行搜索
        logger.info(f"Inline Steam 搜索: '{game_query}' in {search_country}, countries: {country_inputs}")
        search_results = await steam_checker.search_game(game_query, search_country, use_cache=False)

        if not search_results:
            return [
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title="❌ 未找到结果",
                    description=f"关键词: {game_query}",
                    input_message_content=InputTextMessageContent(
                        message_text=f"❌ 未找到与 \"{game_query}\" 相关的游戏"
                    ),
                )
            ]

        # 构建搜索结果列表（最多10个）
        results = []
        for i, game in enumerate(search_results[:10]):
            game_name = game.get("name", "未知游戏")
            game_id = game.get("id")
            game_type = game.get("type", "game")

            if not game_id:
                continue

            # 根据类型添加图标
            if game_type == "bundle":
                type_icon = "🛍"
            elif game_type == "dlc":
                type_icon = "📦"
            else:
                type_icon = "🎮"

            # 获取游戏详细信息（支持多国价格）
            try:
                if game_type == "bundle":
                    # 捆绑包：只查询第一个国家
                    bundle_details = await steam_checker.get_bundle_details(str(game_id), search_country)
                    if bundle_details:
                        result_text = await steam_checker.format_bundle_info(bundle_details, search_country)
                        message_text = foldable_text_with_markdown_v2(result_text)
                        parse_mode = "MarkdownV2"

                        # 构建描述
                        final_price = bundle_details.get('final_price', '未知')
                        description = f"捆绑包 | {final_price}"
                    else:
                        message_text = f"🛍 *{game_name}*\n\n❌ 获取捆绑包信息失败\n\n💡 请使用 `/steamb {game_id}` 重试"
                        parse_mode = "Markdown"
                        description = "捆绑包 | 点击查看详情"
                else:
                    # 游戏和DLC：支持多国价格查询
                    if len(country_inputs) > 1:
                        # 多国价格查询
                        result_text = await steam_checker.search_multiple_countries(str(game_id), country_inputs)
                        message_text = foldable_text_with_markdown_v2(result_text)
                        parse_mode = "MarkdownV2"

                        # 构建描述：显示查询的国家
                        countries_str = ", ".join([c.upper() for c in country_inputs[:3]])
                        if len(country_inputs) > 3:
                            countries_str += f" +{len(country_inputs) - 3}"
                        description = f"多国价格: {countries_str}"
                    else:
                        # 单国价格查询
                        game_details = await steam_checker.get_game_details(str(game_id), search_country)
                        if game_details and game_details.get('success'):
                            result_text = await steam_checker.format_game_info(game_details, search_country)
                            message_text = foldable_text_with_markdown_v2(result_text)
                            parse_mode = "MarkdownV2"

                            # 构建描述
                            data = game_details.get('data', {})
                            price_info = data.get('price_overview', {})
                            if price_info:
                                if price_info.get('is_free'):
                                    description = "免费游戏"
                                else:
                                    final_price = price_info.get('final_formatted', '未知')
                                    discount = price_info.get('discount_percent', 0)
                                    if discount > 0:
                                        description = f"{final_price} (-{discount}%)"
                                    else:
                                        description = final_price
                            else:
                                description = "点击查看详情"
                        else:
                            message_text = f"{type_icon} *{game_name}*\n\n❌ 获取游戏信息失败\n\n💡 请使用 `/steam {game_id}` 重试"
                            parse_mode = "Markdown"
                            description = "点击查看详情"

            except Exception as e:
                logger.warning(f"获取游戏 {game_id} 详情失败: {e}")
                message_text = f"{type_icon} *{game_name}*\n\n❌ 获取详细信息失败\n\n💡 请使用 `/steam {game_name}` 重试"
                parse_mode = "Markdown"
                description = "点击查看详情"

            results.append(
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title=f"{type_icon} {game_name}",
                    description=description,
                    input_message_content=InputTextMessageContent(
                        message_text=message_text,
                        parse_mode=parse_mode,
                    ),
                )
            )

        return results

    except Exception as e:
        logger.error(f"Inline Steam 搜索失败: {e}", exc_info=True)
        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="❌ 搜索失败",
                description=str(e)[:100],
                input_message_content=InputTextMessageContent(
                    message_text=f"❌ 搜索失败: {str(e)}"
                ),
            )
        ]
