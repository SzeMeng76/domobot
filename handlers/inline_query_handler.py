#!/usr/bin/env python3
"""
Telegram Inline Query 处理器（完整版）

允许用户在任何对话中通过 @botname 的方式调用机器人命令
完整支持所有已注册命令，直接返回结果（无需点击按钮）
"""

import logging
from telegram import (
    Update,
    InlineQueryResultArticle,
    InputTextMessageContent,
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
        - @botname https://douyin.com/... -> 解析社交媒体链接
        """
        query = update.inline_query.query
        # 清理查询字符串：去除不可见字符和标准化空格
        query = query.strip()
        # 移除零宽字符和其他不可见字符
        query = ''.join(char for char in query if char.isprintable() or char.isspace())
        # 标准化空格
        query = ' '.join(query.split())

        user_id = update.inline_query.from_user.id

        # ========================================
        # 检查是否是网易云音乐链接
        # ========================================
        from utils.netease_api import contains_music_link
        if contains_music_link(query):
            from handlers.inline_music_handler import handle_inline_music_link
            try:
                results = await handle_inline_music_link(query, update.inline_query, context)
                await update.inline_query.answer(results, cache_time=60)
            except Exception as e:
                logger.error(f"[Inline Music] 处理失败: {e}", exc_info=True)
                await update.inline_query.answer([
                    InlineQueryResultArticle(
                        id=str(uuid4()),
                        title="❌ 音乐链接解析失败",
                        description=str(e)[:100],
                        input_message_content=InputTextMessageContent(
                            message_text=f"❌ 音乐链接解析失败: {str(e)}"
                        ),
                    )
                ])
            return

        # ========================================
        # 检查是否是 YouTube / YouTube Music 链接
        # ========================================
        from utils.ytmusic_api import contains_ytmusic_link
        if contains_ytmusic_link(query):
            from handlers.inline_ytmusic_handler import handle_inline_ytmusic_link
            try:
                results = await handle_inline_ytmusic_link(query, context)
                await update.inline_query.answer(results, cache_time=60)
            except Exception as e:
                logger.error(f"[Inline YTMusic] 处理失败: {e}", exc_info=True)
                await update.inline_query.answer([
                    InlineQueryResultArticle(
                        id=str(uuid4()),
                        title="❌ YouTube 链接解析失败",
                        description=str(e)[:100],
                        input_message_content=InputTextMessageContent(
                            message_text=f"❌ YouTube 链接解析失败: {str(e)}"
                        ),
                    )
                ])
            return

        # ========================================
        # 检查是否是 URL（社交媒体解析 或 Reddit）
        # ========================================
        if query.startswith('http://') or query.startswith('https://'):
            # 检查是否是 Reddit URL
            if 'reddit.com' in query:
                # Reddit inline handler
                from handlers.inline_reddit_handler import handle_inline_reddit_query
                try:
                    results = await handle_inline_reddit_query(update, context, query)
                    logger.info(f"[Inline Reddit] 返回 {len(results)} 个结果, query={query[:50]}")
                    await update.inline_query.answer(results, cache_time=10)
                except Exception as e:
                    logger.error(f"[Inline Reddit] answer_inline_query 失败: {e}", exc_info=True)
                    await update.inline_query.answer([
                        InlineQueryResultArticle(
                            id=str(uuid4()),
                            title="❌ Reddit 解析失败",
                            description=str(e)[:100],
                            input_message_content=InputTextMessageContent(
                                message_text=f"**❌ Reddit 解析失败:**\n```\n{str(e)}\n```"
                            ),
                        )
                    ])
                return

            # 检查权限后，调用 parse handler
            user_manager = context.bot_data.get("user_cache_manager")
            if user_manager:
                try:
                    is_whitelisted = await user_manager.is_whitelisted(user_id)
                    is_admin = await user_manager.is_admin(user_id)

                    from utils.config_manager import get_config
                    config = get_config()
                    is_super_admin = user_id == config.super_admin_id

                    if not (is_whitelisted or is_admin or is_super_admin):
                        logger.warning(f"⚠️ Inline Parse 被拒绝：用户 {user_id} 不在白名单中")
                        await update.inline_query.answer([
                            InlineQueryResultArticle(
                                id=str(uuid4()),
                                title="❌ 权限不足",
                                description="您不在白名单中，无法使用 Inline Parse",
                                input_message_content=InputTextMessageContent(
                                    message_text="❌ 您不在白名单中，无法使用此功能\n\n请联系管理员添加白名单"
                                ),
                            )
                        ])
                        return
                except Exception as e:
                    logger.error(f"权限检查失败: {e}", exc_info=True)
                    await update.inline_query.answer([
                        InlineQueryResultArticle(
                            id=str(uuid4()),
                            title="❌ 权限检查失败",
                            description="请稍后重试或联系管理员",
                            input_message_content=InputTextMessageContent(
                                message_text=f"**❌ 权限检查失败:**\n```\n{str(e)}\n```"
                            ),
                        )
                    ])
                    return

            # 调用 parse handler
            from handlers.inline_parse_handler import handle_inline_parse_query
            try:
                results = await handle_inline_parse_query(update, context, query)
                logger.info(f"[Inline Parse] 返回 {len(results)} 个结果, query={query[:50]}")
                await update.inline_query.answer(results, cache_time=10)
            except Exception as e:
                logger.error(f"[Inline Parse] answer_inline_query 失败: {e}", exc_info=True)
                await update.inline_query.answer([
                    InlineQueryResultArticle(
                        id=str(uuid4()),
                        title="❌ 解析结果返回失败",
                        description=str(e)[:100],
                        input_message_content=InputTextMessageContent(
                            message_text=f"**❌ 解析结果返回失败:**\n```\n{str(e)}\n```"
                        ),
                    )
                ])
            return

        # ========================================
        # 权限检查
        # ========================================
        user_manager = context.bot_data.get("user_cache_manager")
        if user_manager:
            try:
                is_whitelisted = await user_manager.is_whitelisted(user_id)
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

        # 获取 bot username
        bot_username = context.bot.username or "bot"

        # 如果查询为空，显示帮助信息
        if not query:
            results = self._get_help_results(bot_username)
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

        # 音乐搜索单独处理：返回多条结果（参考 Go processInlineSearch）
        parts = command_text.split(None, 1)
        if parts and parts[0].lower() in ("netease",):
            keyword = parts[1].strip() if len(parts) > 1 else ""
            from handlers.inline_music_handler import handle_inline_music_search
            results = await handle_inline_music_search(keyword, context)
            await update.inline_query.answer(results, cache_time=60)
            return

        # YouTube Music 搜索单独处理
        if parts and parts[0].lower() in ("yt", "ytmusic"):
            keyword = parts[1].strip() if len(parts) > 1 else ""
            from handlers.inline_ytmusic_handler import handle_inline_ytmusic_search
            results = await handle_inline_ytmusic_search(keyword, context)
            await update.inline_query.answer(results, cache_time=60)
            return

        # App Store 搜索单独处理：返回多条结果
        if parts and parts[0].lower() in ("appstore", "app"):
            keyword = parts[1].strip() if len(parts) > 1 else ""
            from commands.app_store import handle_inline_appstore_search
            results = await handle_inline_appstore_search(keyword, context)
            await update.inline_query.answer(results, cache_time=60)
            return

        # Finance 搜索单独处理：返回多条结果
        if parts and parts[0].lower() in ("finance", "stock"):
            keyword = parts[1].strip() if len(parts) > 1 else ""
            from commands.finance import handle_inline_finance_search
            results = await handle_inline_finance_search(keyword, context)
            await update.inline_query.answer(results, cache_time=60)
            return

        # Movie 搜索单独处理：返回多条结果
        if parts and parts[0].lower() in ("movie",):
            keyword = parts[1].strip() if len(parts) > 1 else ""
            from commands.movie import handle_inline_movie_search
            results = await handle_inline_movie_search(keyword, context)
            await update.inline_query.answer(results, cache_time=60)
            return

        # Reddit hot/top/new 列表单独处理：返回多条结果
        if parts and parts[0].lower() in ("reddit", "reddit_hot", "reddit_top", "reddit_new"):
            # 格式: reddit hot/top/new [subreddit] [time]
            from handlers.inline_reddit_handler import handle_inline_reddit_list
            results = await handle_inline_reddit_list(command_text, context)
            await update.inline_query.answer(results, cache_time=60)
            return

        # TV 搜索单独处理：返回多条结果
        if parts and parts[0].lower() in ("tv",):
            keyword = parts[1].strip() if len(parts) > 1 else ""
            from commands.movie import handle_inline_tv_search
            results = await handle_inline_tv_search(keyword, context)
            await update.inline_query.answer(results, cache_time=60)
            return

        # Steam 搜索单独处理：返回多条结果
        if parts and parts[0].lower() in ("steam",):
            keyword = parts[1].strip() if len(parts) > 1 else ""
            from commands.steam import handle_inline_steam_search
            results = await handle_inline_steam_search(keyword, context)
            await update.inline_query.answer(results, cache_time=60)
            return

        # Google Play 搜索单独处理：返回多条结果
        if parts and parts[0].lower() in ("gp", "googleplay"):
            keyword = parts[1].strip() if len(parts) > 1 else ""
            from commands.google_play import handle_inline_googleplay_search
            results = await handle_inline_googleplay_search(keyword, context)
            await update.inline_query.answer(results, cache_time=60)
            return

        # When 用户查询单独处理
        if parts and parts[0].lower() in ("when",):
            from commands.system_commands import handle_inline_when_query
            results = await handle_inline_when_query(command_text, context)
            await update.inline_query.answer(results, cache_time=60)
            return

        # 直接执行命令并返回结果
        results = await self._execute_and_create_results(command_text, user_id, context)

        # 返回结果
        try:
            await update.inline_query.answer(results, cache_time=10)
        except Exception as e:
            logger.error(f"[Inline] answer 失败，尝试去除格式重试: {e}")
            # parse entities 失败，重建结果（去掉 parse_mode）
            try:
                plain_results = []
                for r in results:
                    if hasattr(r, 'input_message_content') and r.input_message_content:
                        plain_results.append(
                            InlineQueryResultArticle(
                                id=str(uuid4()),
                                title=r.title if hasattr(r, 'title') else "查询结果",
                                description=r.description if hasattr(r, 'description') else None,
                                input_message_content=InputTextMessageContent(
                                    message_text=r.input_message_content.message_text
                                ),
                            )
                        )
                    else:
                        plain_results.append(r)
                await update.inline_query.answer(plain_results, cache_time=10)
            except Exception as e2:
                logger.error(f"[Inline] 去除格式后仍然失败: {e2}")
                await update.inline_query.answer([
                    InlineQueryResultArticle(
                        id=str(uuid4()),
                        title="❌ 结果格式错误",
                        description=str(e)[:100],
                        input_message_content=InputTextMessageContent(
                            message_text=f"❌ 结果格式错误\n\n错误: {str(e)}\n\n💡 请在私聊中使用 /{command_text} 重试"
                        ),
                    )
                ])

    def _get_help_results(self, bot_username: str) -> list:
        """返回帮助信息"""
        help_text = f"""
🤖 **Inline Mode 使用说明**

在任何对话中输入:
`@{bot_username} 命令 参数$`

**💰 金融查询:**
• `rate usd 100$` - 汇率转换
• `crypto btc$` - 加密货币价格
• `finance AAPL$` - 股票查询（精确代码）
• `finance apple$` - 股票搜索（模糊搜索，返回10个结果）
• `bin 123456$` - BIN卡头查询

**🎮 游戏价格:**
• `steam elden ring$` - Steam游戏搜索（返回10个结果）
• `steam 双人成行$` - Steam中文游戏搜索
• `steam CS2 us ru tr ar$` - 多国价格对比

**📱 应用商店:**
• `appstore 微信$` - App Store搜索（返回10个结果）
• `appstore Photoshop -mac$` - 搜索macOS应用
• `appstore id363590051$` - 查询多国价格
• `gp youtube$` - Google Play搜索（返回10个结果）
• `gp chatgpt us ng tr$` - 多国价格对比

**🎬 流媒体价格:**
• `netflix$` - Netflix全球价格排名
• `spotify$` - Spotify全球价格排名
• `disney$` - Disney+全球价格排名
• `max$` - HBO Max全球价格排名
• `appleservices icloud$` - Apple服务价格

**🛢️ 油价查询:**
• `fuel$` - 全球汽油价格排名
• `fuel my$` - 马来西亚油价
• `fuel china$` - 中国油价排名
• `fuel diesel$` - 全球柴油价格排名

**🎬 影视查询:**
• `movie Inception$` - 电影搜索（模糊搜索，返回10个结果）
• `movie 盗梦空间$` - 中文电影搜索
• `tv Breaking Bad$` - 电视剧搜索（模糊搜索，返回10个结果）
• `tv 绝命毒师$` - 中文电视剧搜索
• `chart movie$` - 影视排行榜

**🌐 实用工具:**
• `weather 北京$` - 天气查询（点按钮生成AI日报）
• `time tokyo$` - 时区查询
• `news$` - 热门新闻汇总
• `whois google.com$` - WHOIS/DNS查询
• `cooking$` - 随机菜谱推荐
• `chart movie$` - 影视排行榜
• `when 123456789$` - 查询用户信息
• `when @username$` - 查询用户信息

**🎵 音乐:**
• `netease 晴天$` - 搜索网易云音乐
• `yt 晴天$` - 搜索YouTube Music
• `yt chart$` - YouTube Music排行榜
• 直接输入网易云链接(无需$) - 解析网易云音乐
• 直接输入YouTube链接(无需$) - 下载YouTube音乐

**📱 社交媒体解析:**
• 直接输入链接(无需$符号) - 解析视频/图片/图文
• 支持抖音、B站、YouTube、TikTok、小红书、Twitter等20+平台
• 视频/图片会直接显示在聊天中

**🔴 Reddit:**
• 直接输入Reddit链接(无需$) - 解析帖子（支持图片/视频/图集）
• `reddit hot$` - 全站热门帖子
• `reddit hot python$` - r/python热门帖子
• `reddit top week$` - 全站本周Top
• `reddit top python week$` - r/python本周Top

**注意:**
• 命令末尾必须加 `$` 符号才会执行
• 社交媒体链接无需 `$` 符号
• 点击结果后会直接显示查询结果
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
            "crypto": "₿ 加密货币 - 添加 $ 执行查询",
            "finance": "📈 股票查询/搜索 - 添加 $ 执行查询",
            "stock": "📈 股票搜索 - 添加 $ 执行查询",
            "steam": "🎮 Steam游戏搜索 - 添加 $ 执行查询",
            "gp": "📱 Google Play搜索 - 添加 $ 执行查询",
            "googleplay": "📱 Google Play搜索 - 添加 $ 执行查询",
            "bin": "💳 BIN查询 - 添加 $ 执行查询",
            "netflix": "🎬 Netflix - 添加 $ 执行查询",
            "spotify": "🎵 Spotify - 添加 $ 执行查询",
            "disney": "🎪 Disney+ - 添加 $ 执行查询",
            "max": "📺 HBO Max - 添加 $ 执行查询",
            "appleservices": "🍎 Apple服务 - 添加 $ 执行查询",
            "appstore": "📱 App Store - 添加 $ 执行查询",
            "app": "📱 App Store - 添加 $ 执行查询",
            "fuel": "🛢️ 油价查询 - 添加 $ 执行查询",
            "weather": "🌤️ 天气查询 - 添加 $ 执行查询（点按钮生成AI日报）",
            "tq": "🌤️ 天气查询 - 添加 $ 执行查询（点按钮生成AI日报）",
            "time": "🕐 时区查询 - 添加 $ 执行查询",
            "news": "📰 新闻 - 添加 $ 执行查询",
            "whois": "🌐 域名查询 - 添加 $ 执行查询",
            "cooking": "👨‍🍳 菜谱 - 添加 $ 执行查询",
            "netease": "🎵 网易云音乐 - 添加 $ 搜索歌曲",
            "yt": "🎵 YouTube Music - 添加 $ 搜索歌曲",
            "chart": "📊 排行榜 - 添加 $ 执行查询",
            "movie": "🎬 电影搜索 - 添加 $ 执行查询（支持中英文）",
            "tv": "📺 电视剧搜索 - 添加 $ 执行查询（支持中英文）",
            "reddit": "🔴 Reddit - 添加 $ 执行查询（hot/top列表）",
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

    async def _execute_and_create_results(self, command_text: str, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> list:
        """
        直接执行命令并创建结果列表（不需要点击按钮）
        """
        # 分割命令和参数
        parts = command_text.split(None, 1)
        if not parts:
            return self._get_help_results(context.bot.username or "bot")

        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        # 命令映射表（图标 + 标题 + 描述）
        command_info = {
            "rate": {"icon": "💱", "title": "汇率转换", "desc": "实时汇率查询"},
            "crypto": {"icon": "₿", "title": "加密货币", "desc": "实时币价"},
            "finance": {"icon": "📈", "title": "股票查询", "desc": "股票信息"},
            "bin": {"icon": "💳", "title": "BIN查询", "desc": "银行卡信息"},
            "netflix": {"icon": "🎬", "title": "Netflix", "desc": "订阅价格"},
            "spotify": {"icon": "🎵", "title": "Spotify", "desc": "订阅价格"},
            "disney": {"icon": "🎪", "title": "Disney+", "desc": "订阅价格"},
            "max": {"icon": "📺", "title": "HBO Max", "desc": "订阅价格"},
            "appleservices": {"icon": "🍎", "title": "Apple服务", "desc": "订阅价格"},
            "appstore": {"icon": "📱", "title": "App Store", "desc": "应用价格"},
            "fuel": {"icon": "🛢️", "title": "油价查询", "desc": "全球油价"},
            "weather": {"icon": "🌤️", "title": "天气查询", "desc": "天气预报和预警"},
            "time": {"icon": "🕐", "title": "时区查询", "desc": "世界时间"},
            "news": {"icon": "📰", "title": "新闻", "desc": "最新资讯"},
            "whois": {"icon": "🌐", "title": "域名查询", "desc": "WHOIS信息"},
            "cooking": {"icon": "👨‍🍳", "title": "菜谱", "desc": "烹饪指南"},
            "chart": {"icon": "📊", "title": "排行榜", "desc": "影视排行"},
            "netease": {"icon": "🎵", "title": "网易云音乐", "desc": "搜索歌曲"},
            "yt": {"icon": "🎵", "title": "YouTube Music", "desc": "搜索歌曲"},
            "ytmusic": {"icon": "🎵", "title": "YouTube Music", "desc": "搜索歌曲"},
        }

        info = command_info.get(command, {"icon": "🔍", "title": command.upper(), "desc": "执行命令"})

        try:
            # 使用命令适配器执行命令
            from utils.inline_command_adapter import InlineCommandAdapter

            adapter = InlineCommandAdapter(context)
            result_text, parse_mode, reply_markup = await adapter.execute_command(command, args)

            # 特殊处理：weather 命令显示提示
            if command in ("weather", "tq"):
                desc = f"✅ 天气资讯已生成，点按钮生成AI日报 - {args}" if args else "✅ 天气资讯已生成，点按钮生成AI日报"
            else:
                desc = f"{info['desc']} - {args[:50]}..." if len(args) > 50 else (f"{info['desc']} - {args}" if args else info['desc'])

            # 创建结果
            results = [
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title=f"{info['icon']} {info['title']}",
                    description=desc,
                    thumbnail_url=f"https://img.icons8.com/color/96/000000/checkmark.png",
                    input_message_content=InputTextMessageContent(
                        message_text=result_text,
                        parse_mode=parse_mode
                    ),
                    reply_markup=reply_markup
                )
            ]

            return results

        except Exception as e:
            logger.error(f"执行 inline 命令 {command} 失败: {e}", exc_info=True)
            # 返回错误结果
            return [
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title=f"❌ 执行失败",
                    description=f"命令: {command} {args}",
                    thumbnail_url=f"https://img.icons8.com/color/96/000000/error.png",
                    input_message_content=InputTextMessageContent(
                        message_text=f"❌ 执行命令时出错\n\n错误: {str(e)}\n\n💡 请在私聊中使用 /{command} {args} 重试",
                    ),
                )
            ]


async def setup_inline_query_handler(application) -> None:
    """设置 inline query 处理器"""
    from telegram.ext import InlineQueryHandler as TelegramInlineQueryHandler
    from telegram.ext import ChosenInlineResultHandler

    handler = InlineQueryHandler()

    # 注册 inline query 处理器
    application.add_handler(
        TelegramInlineQueryHandler(handler.handle_inline_query)
    )

    # 注册 chosen inline result 处理器（parse + music + reddit）
    from handlers.inline_parse_handler import handle_inline_parse_chosen
    from handlers.inline_music_handler import handle_inline_music_chosen
    from handlers.inline_ytmusic_handler import handle_inline_ytmusic_chosen
    from handlers.inline_reddit_handler import handle_inline_reddit_chosen

    async def _chosen_inline_dispatcher(update, context):
        """分发 chosen inline result 到对应处理器"""
        result_id = update.chosen_inline_result.result_id
        if result_id.startswith("music_dl_"):
            await handle_inline_music_chosen(update, context)
        elif result_id.startswith("ytm_dl_"):
            await handle_inline_ytmusic_chosen(update, context)
        elif result_id.startswith("parse_"):
            await handle_inline_parse_chosen(update, context)
        elif result_id.startswith("reddit_video_") or result_id.startswith("reddit_image_"):
            await handle_inline_reddit_chosen(update, context)

    application.add_handler(
        ChosenInlineResultHandler(_chosen_inline_dispatcher)
    )

    logger.info("✅ Inline Query 处理器已注册（含 Parse + Music + YTMusic + Reddit 支持）")
