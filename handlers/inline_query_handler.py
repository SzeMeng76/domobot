#!/usr/bin/env python3
"""
Telegram Inline Query 处理器（完整版）

允许用户在任何对话中通过 @botname 的方式调用机器人命令
完整支持所有已注册命令，包括按钮交互
"""

import logging
from telegram import (
    Update,
    InlineQueryResultArticle,
    InputTextMessageContent,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from uuid import uuid4

logger = logging.getLogger(__name__)


class InlineQueryHandler:
    """Inline Query 处理器 - 让 bot 可以在任何对话中被调用"""

    def __init__(self):
        self.trigger_suffix = "$"  # 触发后缀，用户输入以 $ 结尾才会真正执行

    async def handle_inline_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        处理 inline query 请求

        用法示例:
        - @botname rate 100 usd to cny$  -> 汇率转换
        - @botname weather beijing$      -> 天气查询
        - @botname steam elden ring$     -> Steam 游戏价格查询
        """
        query = update.inline_query.query
        user_id = update.inline_query.from_user.id

        # ========================================
        # 权限检查
        # ========================================
        user_manager = context.bot_data.get("user_cache_manager")
        if user_manager:
            try:
                is_whitelisted = await user_manager.is_user_whitelisted(user_id)
                is_admin = await user_manager.is_admin(user_id)

                from utils.config_manager import get_config
                config = get_config()
                is_super_admin = user_id == config.super_admin_id

                if not (is_whitelisted or is_admin or is_super_admin):
                    logger.warning(f"⚠️ Inline Query 被拒绝：用户 {user_id} 不在白名单中")
                    # 返回提示信息
                    await update.inline_query.answer([
                        InlineQueryResultArticle(
                            id=str(uuid4()),
                            title="❌ 权限不足",
                            description="您不在白名单中，无法使用 Inline Mode",
                            input_message_content=InputTextMessageContent(
                                message_text="❌ 您不在白名单中，无法使用此功能\n\n请联系管理员添加白名单"
                            ),
                        )
                    ])
                    return
            except Exception as e:
                logger.error(f"权限检查失败: {e}")
                await update.inline_query.answer([])
                return

        # ========================================
        # 处理查询
        # ========================================

        # 如果查询为空，显示帮助信息
        if not query:
            results = self._get_help_results()
            await update.inline_query.answer(results, cache_time=300)
            return

        # 检查是否以触发后缀结尾
        if not query.endswith(self.trigger_suffix):
            # 显示提示信息
            results = self._get_hint_results(query)
            await update.inline_query.answer(results, cache_time=0)
            return

        # 去掉触发后缀，准备执行命令
        command_text = query[:-len(self.trigger_suffix)].strip()

        # 解析并创建结果
        results = await self._create_command_results(command_text, user_id, context)

        # 返回结果
        await update.inline_query.answer(results, cache_time=10)

    def _get_help_results(self) -> list:
        """返回帮助信息"""
        help_text = """
🤖 **Inline Mode 使用说明**

在任何对话中输入:
`@你的botname 命令 参数$`

**常用命令示例:**
• `rate 100 usd to cny$` - 汇率转换
• `weather beijing$` - 天气查询
• `steam elden ring$` - Steam游戏价格
• `netflix$` - Netflix订阅价格
• `crypto btc$` - 加密货币价格
• `time tokyo$` - 时区查询
• `news tech$` - 新闻查询
• `movie avengers$` - 影视信息
• `cooking 宫保鸡丁$` - 菜谱查询
• `bin 123456$` - BIN查询
• `whois google.com$` - 域名查询

**支持全部命令:**
weather, steam, netflix, disney, spotify, max, appstore, googleplay, appleservices, crypto, time, news, movie, cooking, bin, whois, map, flight, hotel

**注意:**
• 命令末尾必须加 `$` 符号才会执行
• 点击结果后会发送到当前对话
• 点击"执行"按钮获取实时数据
        """.strip()

        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="📖 Inline Mode 使用指南",
                description="点击查看完整使用说明和示例",
                thumbnail_url="https://img.icons8.com/color/96/000000/info.png",
                input_message_content=InputTextMessageContent(
                    message_text=help_text,
                    parse_mode=ParseMode.MARKDOWN
                ),
            )
        ]

    def _get_hint_results(self, query: str) -> list:
        """显示提示信息（未加$符号时）"""
        # 分析用户输入，给出智能提示
        parts = query.split(None, 1)
        command = parts[0].lower() if parts else ""

        # 命令提示
        command_hints = {
            "rate": "💱 汇率转换 - 添加 $ 执行查询",
            "weather": "🌤️ 天气查询 - 添加 $ 执行查询",
            "steam": "🎮 Steam游戏 - 添加 $ 执行查询",
            "netflix": "🎬 Netflix - 添加 $ 执行查询",
            "crypto": "₿ 加密货币 - 添加 $ 执行查询",
            "time": "🕐 时区查询 - 添加 $ 执行查询",
            "news": "📰 新闻 - 添加 $ 执行查询",
            "movie": "🎬 影视 - 添加 $ 执行查询",
        }

        hint = command_hints.get(command, f"💡 添加 '{self.trigger_suffix}' 执行命令")

        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title=hint,
                description=f"当前输入: {query}",
                thumbnail_url="https://img.icons8.com/color/96/000000/light-on.png",
                input_message_content=InputTextMessageContent(
                    message_text=f"💡 提示：请在查询末尾添加 `{self.trigger_suffix}` 符号来执行命令\n\n当前输入: `{query}`\n\n完整输入: `{query}{self.trigger_suffix}`"
                ),
            )
        ]

    async def _create_command_results(self, command_text: str, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> list:
        """
        创建命令结果列表
        """
        # 分割命令和参数
        parts = command_text.split(None, 1)
        if not parts:
            return self._get_help_results()

        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        # 命令映射表（图标 + 标题 + 描述）
        command_info = {
            "rate": {"icon": "💱", "title": "汇率转换", "desc": "实时汇率查询"},
            "weather": {"icon": "🌤️", "title": "天气查询", "desc": "天气预报和预警"},
            "steam": {"icon": "🎮", "title": "Steam游戏", "desc": "游戏价格对比"},
            "netflix": {"icon": "🎬", "title": "Netflix", "desc": "订阅价格"},
            "disney": {"icon": "🎪", "title": "Disney+", "desc": "订阅价格"},
            "spotify": {"icon": "🎵", "title": "Spotify", "desc": "订阅价格"},
            "max": {"icon": "📺", "title": "HBO Max", "desc": "订阅价格"},
            "crypto": {"icon": "₿", "title": "加密货币", "desc": "实时币价"},
            "time": {"icon": "🕐", "title": "时区查询", "desc": "世界时间"},
            "news": {"icon": "📰", "title": "新闻", "desc": "最新资讯"},
            "movie": {"icon": "🎬", "title": "影视", "desc": "电影电视剧"},
            "appstore": {"icon": "📱", "title": "App Store", "desc": "应用价格"},
            "googleplay": {"icon": "🤖", "title": "Google Play", "desc": "应用价格"},
            "appleservices": {"icon": "🍎", "title": "Apple服务", "desc": "订阅价格"},
            "cooking": {"icon": "👨‍🍳", "title": "菜谱", "desc": "烹饪指南"},
            "bin": {"icon": "💳", "title": "BIN查询", "desc": "银行卡信息"},
            "whois": {"icon": "🌐", "title": "域名查询", "desc": "WHOIS信息"},
            "map": {"icon": "🗺️", "title": "地图", "desc": "地理位置"},
            "flight": {"icon": "✈️", "title": "航班", "desc": "航班信息"},
            "hotel": {"icon": "🏨", "title": "酒店", "desc": "酒店查询"},
        }

        info = command_info.get(command, {"icon": "🔍", "title": command.upper(), "desc": "执行命令"})

        # 构建 callback_data
        # 格式: inline:command:args
        callback_data = f"inline:{command}:{args}"

        # 如果 callback_data 太长（超过64字节限制），使用短格式
        if len(callback_data) > 64:
            # 使用哈希或截断
            import hashlib
            args_hash = hashlib.md5(args.encode()).hexdigest()[:8]
            callback_data = f"inline:{command}:{args_hash}"
            # 将完整参数存储到 bot_data 中
            context.bot_data[f"inline_args_{user_id}_{args_hash}"] = args

        # 创建结果
        results = [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title=f"{info['icon']} {info['title']}",
                description=f"{info['desc']} - {args[:50]}..." if len(args) > 50 else (f"{info['desc']} - {args}" if args else info['desc']),
                thumbnail_url=f"https://img.icons8.com/color/96/000000/search.png",
                input_message_content=InputTextMessageContent(
                    message_text=f"⏳ 正在查询 {info['icon']} {info['title']} {args}...\n\n请稍候...",
                ),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        text=f"🔄 执行查询",
                        callback_data=callback_data if len(callback_data) <= 64 else f"inline:{command}:_"
                    )]
                ])
            )
        ]

        return results


async def handle_inline_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    处理 inline query 回调按钮点击
    当用户点击"执行查询"按钮时，真正执行命令
    """
    query = update.callback_query
    await query.answer("正在处理...")

    # 解析 callback_data
    # 格式: inline:command:args
    data = query.data
    if not data.startswith("inline:"):
        return

    parts = data.split(":", 2)
    if len(parts) < 2:
        return

    command = parts[1]
    args = parts[2] if len(parts) >= 3 else ""

    # 如果 args 是 hash，从 bot_data 中恢复
    user_id = query.from_user.id
    if args.startswith("_") or (len(args) == 8 and args != args.lower()):
        stored_args = context.bot_data.get(f"inline_args_{user_id}_{args}")
        if stored_args:
            args = stored_args

    try:
        # 显示"正在处理"消息
        await query.edit_message_text(
            text=f"⏳ 正在执行命令: `/{command} {args}`\n\n请稍候...",
            parse_mode=ParseMode.MARKDOWN
        )

        # 使用命令适配器执行命令
        from utils.inline_command_adapter import InlineCommandAdapter

        adapter = InlineCommandAdapter(context)
        result_text, parse_mode, reply_markup = await adapter.execute_command(command, args)

        # 更新消息显示结果
        await query.edit_message_text(
            text=result_text,
            parse_mode=parse_mode,
            reply_markup=reply_markup
        )

        # 清理临时数据
        if args and len(args) == 8:
            context.bot_data.pop(f"inline_args_{user_id}_{args}", None)

    except Exception as e:
        logger.error(f"执行 inline callback 失败: {e}", exc_info=True)
        try:
            await query.edit_message_text(
                text=f"❌ 执行命令时出错\n\n错误: {str(e)}\n\n💡 请在私聊中使用 `/{command} {args}` 重试",
                parse_mode=ParseMode.MARKDOWN
            )
        except:
            pass


async def setup_inline_query_handler(application) -> None:
    """设置 inline query 处理器"""
    from telegram.ext import InlineQueryHandler as TelegramInlineQueryHandler

    handler = InlineQueryHandler()

    # 注册 inline query 处理器
    application.add_handler(
        TelegramInlineQueryHandler(handler.handle_inline_query)
    )

    # 注册 inline callback 处理器（处理用户点击"执行"按钮）
    from utils.command_factory import command_factory
    command_factory.register_callback(
        pattern="^inline:",
        handler=handle_inline_callback,
        description="Inline Query 回调处理"
    )

    logger.info("✅ Inline Query 处理器已注册")
