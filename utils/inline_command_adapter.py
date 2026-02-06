#!/usr/bin/env python3
"""
Inline 命令适配器

统一处理所有命令在 inline mode 中的执行
将命令逻辑从消息处理中分离，使其可以在任何场景下调用
"""

import logging
from typing import Optional, Dict, Any, Tuple
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)


class InlineCommandAdapter:
    """Inline 命令适配器 - 执行命令并返回格式化结果"""

    def __init__(self, context: ContextTypes.DEFAULT_TYPE):
        self.context = context
        self.cache_manager = context.bot_data.get("cache_manager")
        self.rate_converter = context.bot_data.get("rate_converter")
        self.httpx_client = context.bot_data.get("httpx_client")
        self.user_cache_manager = context.bot_data.get("user_cache_manager")

    async def execute_command(self, command: str, args: str) -> Tuple[str, Optional[ParseMode], Optional[Any]]:
        """
        执行命令并返回结果

        Args:
            command: 命令名称
            args: 命令参数字符串

        Returns:
            (结果文本, 解析模式, 按钮markup)
        """
        # 命令路由
        command_handlers = {
            "rate": self._handle_rate,
            "weather": self._handle_weather,
            "steam": self._handle_steam,
            "netflix": self._handle_netflix,
            "disney": self._handle_disney,
            "spotify": self._handle_spotify,
            "max": self._handle_max,
            "crypto": self._handle_crypto,
            "time": self._handle_time,
            "news": self._handle_news,
            "movie": self._handle_movie,
            "appstore": self._handle_appstore,
            "googleplay": self._handle_googleplay,
            "appleservices": self._handle_appleservices,
            "cooking": self._handle_cooking,
            "bin": self._handle_bin,
            "whois": self._handle_whois,
            "map": self._handle_map,
            "flight": self._handle_flight,
            "hotel": self._handle_hotel,
        }

        handler = command_handlers.get(command)
        if not handler:
            return self._default_handler(command, args)

        try:
            return await handler(args)
        except Exception as e:
            logger.error(f"执行 inline 命令 {command} 失败: {e}", exc_info=True)
            return (
                f"❌ 执行命令时出错\n\n错误信息: {str(e)}\n\n💡 请在私聊中使用 `/{command} {args}` 获取完整功能",
                ParseMode.MARKDOWN,
                None
            )

    # ============================================================================
    # 💱 汇率转换
    # ============================================================================

    async def _handle_rate(self, args: str) -> Tuple[str, ParseMode, None]:
        """处理汇率转换命令 - 调用完整的 rate 功能"""
        from commands.rate_command import rate_inline_execute
        from utils.formatter import foldable_text_with_markdown_v2

        # 调用完整的 rate 功能
        result = await rate_inline_execute(args)

        if result["success"]:
            # 使用 foldable_text_with_markdown_v2 处理格式
            return (foldable_text_with_markdown_v2(result["message"]), ParseMode.MARKDOWN_V2, None)
        else:
            # 错误信息
            error_message = (
                f"❌ *{result['title']}*\n\n"
                f"{result['message']}"
            )
            return (foldable_text_with_markdown_v2(error_message), ParseMode.MARKDOWN_V2, None)

    # ============================================================================
    # 🌤️ 天气查询
    # ============================================================================

    async def _handle_weather(self, args: str) -> Tuple[str, ParseMode, None]:
        """处理天气查询命令"""
        if not args:
            return (
                "❌ *天气查询*\n\n"
                "请提供城市名称\n\n"
                "*使用方法:*\n"
                "`weather beijing`\n"
                "`weather tokyo`\n"
                "`weather new york`",
                ParseMode.MARKDOWN_V2,
                None
            )

        # 简化版：返回提示信息
        # 完整实现需要调用天气API
        from utils.formatter import escape_v2

        return (
            f"🌤️ *天气查询*\n\n"
            f"查询城市: {escape_v2(args)}\n\n"
            f"💡 天气查询功能需要完整API支持\n"
            f"请在私聊中使用 `/weather {escape_v2(args)}` 获取详细天气信息",
            ParseMode.MARKDOWN_V2,
            None
        )

    # ============================================================================
    # 🎮 Steam 游戏价格
    # ============================================================================

    async def _handle_steam(self, args: str) -> Tuple[str, ParseMode, None]:
        """处理 Steam 游戏价格查询"""
        if not args:
            return (
                "❌ *Steam 游戏价格查询*\n\n"
                "请提供游戏名称\n\n"
                "*使用方法:*\n"
                "`steam elden ring`\n"
                "`steam cyberpunk`",
                ParseMode.MARKDOWN_V2,
                None
            )

        from utils.formatter import escape_v2

        return (
            f"🎮 *Steam 游戏价格*\n\n"
            f"搜索: {escape_v2(args)}\n\n"
            f"💡 游戏价格查询需要完整数据库支持\n"
            f"请在私聊中使用 `/steam {escape_v2(args)}` 获取详细价格对比",
            ParseMode.MARKDOWN_V2,
            None
        )

    # ============================================================================
    # 🎬 流媒体服务价格
    # ============================================================================

    async def _handle_netflix(self, args: str) -> Tuple[str, ParseMode, None]:
        """处理 Netflix 价格查询"""
        from commands.netflix import get_netflix_prices_text

        try:
            result = await get_netflix_prices_text(self.cache_manager, self.rate_converter)
            return (result, ParseMode.MARKDOWN_V2, None)
        except:
            return (
                "🎬 *Netflix 订阅价格*\n\n"
                "💡 请在私聊中使用 `/netflix` 获取详细价格信息",
                ParseMode.MARKDOWN_V2,
                None
            )

    async def _handle_disney(self, args: str) -> Tuple[str, ParseMode, None]:
        """处理 Disney+ 价格查询"""
        return (
            "🎪 *Disney\\+ 订阅价格*\n\n"
            "💡 请在私聊中使用 `/disney` 获取详细价格信息",
            ParseMode.MARKDOWN_V2,
            None
        )

    async def _handle_spotify(self, args: str) -> Tuple[str, ParseMode, None]:
        """处理 Spotify 价格查询"""
        return (
            "🎵 *Spotify 订阅价格*\n\n"
            "💡 请在私聊中使用 `/spotify` 获取详细价格信息",
            ParseMode.MARKDOWN_V2,
            None
        )

    async def _handle_max(self, args: str) -> Tuple[str, ParseMode, None]:
        """处理 HBO Max 价格查询"""
        return (
            "📺 *HBO Max 订阅价格*\n\n"
            "💡 请在私聊中使用 `/max` 获取详细价格信息",
            ParseMode.MARKDOWN_V2,
            None
        )

    # ============================================================================
    # ₿ 加密货币价格
    # ============================================================================

    async def _handle_crypto(self, args: str) -> Tuple[str, ParseMode, None]:
        """处理加密货币价格查询 - 调用完整的 crypto 功能"""
        from commands.crypto import crypto_inline_execute
        from utils.formatter import foldable_text_with_markdown_v2

        if not args:
            args = "btc"  # 默认查询比特币

        result = await crypto_inline_execute(args)

        if result["success"]:
            return (foldable_text_with_markdown_v2(result["message"]), ParseMode.MARKDOWN_V2, None)
        else:
            error_message = f"❌ *{result['title']}*\n\n{result['message']}"
            return (foldable_text_with_markdown_v2(error_message), ParseMode.MARKDOWN_V2, None)

    # ============================================================================
    # 🕐 时区查询
    # ============================================================================

    async def _handle_time(self, args: str) -> Tuple[str, ParseMode, None]:
        """处理时区查询 - 调用完整的 time 功能"""
        from commands.time_command import time_inline_execute

        result = await time_inline_execute(args)

        if result["success"]:
            return (result["message"], ParseMode.MARKDOWN_V2, None)
        else:
            error_message = f"❌ *{result['title']}*\n\n{result['message']}"
            return (error_message, ParseMode.MARKDOWN_V2, None)

    # ============================================================================
    # 📰 新闻查询
    # ============================================================================

    async def _handle_news(self, args: str) -> Tuple[str, ParseMode, None]:
        """处理新闻查询"""
        from utils.formatter import escape_v2

        keyword = args if args else "科技"

        return (
            f"📰 *新闻查询*\n\n"
            f"关键词: {escape_v2(keyword)}\n\n"
            f"💡 请在私聊中使用 `/news {escape_v2(keyword)}` 获取最新新闻",
            ParseMode.MARKDOWN_V2,
            None
        )

    # ============================================================================
    # 🎬 影视信息
    # ============================================================================

    async def _handle_movie(self, args: str) -> Tuple[str, ParseMode, None]:
        """处理影视信息查询"""
        if not args:
            return (
                "❌ *影视信息查询*\n\n"
                "请提供影片名称\n\n"
                "*使用方法:*\n"
                "`movie avengers`\n"
                "`movie inception`",
                ParseMode.MARKDOWN_V2,
                None
            )

        from utils.formatter import escape_v2

        return (
            f"🎬 *影视信息*\n\n"
            f"搜索: {escape_v2(args)}\n\n"
            f"💡 请在私聊中使用 `/movie {escape_v2(args)}` 获取详细信息",
            ParseMode.MARKDOWN_V2,
            None
        )

    # ============================================================================
    # 📱 应用商店价格
    # ============================================================================

    async def _handle_appstore(self, args: str) -> Tuple[str, ParseMode, None]:
        """处理 App Store 价格查询"""
        if not args:
            return (
                "❌ *App Store 价格查询*\n\n"
                "请提供应用名称\n\n"
                "*使用方法:*\n"
                "`appstore minecraft`",
                ParseMode.MARKDOWN_V2,
                None
            )

        from utils.formatter import escape_v2

        return (
            f"📱 *App Store 价格*\n\n"
            f"搜索: {escape_v2(args)}\n\n"
            f"💡 请在私聊中使用 `/appstore {escape_v2(args)}` 获取价格对比",
            ParseMode.MARKDOWN_V2,
            None
        )

    async def _handle_googleplay(self, args: str) -> Tuple[str, ParseMode, None]:
        """处理 Google Play 价格查询"""
        if not args:
            return (
                "❌ *Google Play 价格查询*\n\n"
                "请提供应用名称\n\n"
                "*使用方法:*\n"
                "`googleplay minecraft`",
                ParseMode.MARKDOWN_V2,
                None
            )

        from utils.formatter import escape_v2

        return (
            f"🤖 *Google Play 价格*\n\n"
            f"搜索: {escape_v2(args)}\n\n"
            f"💡 请在私聊中使用 `/googleplay {escape_v2(args)}` 获取价格对比",
            ParseMode.MARKDOWN_V2,
            None
        )

    async def _handle_appleservices(self, args: str) -> Tuple[str, ParseMode, None]:
        """处理 Apple 服务价格查询"""
        return (
            "🍎 *Apple 服务价格*\n\n"
            "💡 请在私聊中使用 `/appleservices` 获取 iCloud、Apple Music 等服务价格",
            ParseMode.MARKDOWN_V2,
            None
        )

    # ============================================================================
    # 👨‍🍳 其他功能
    # ============================================================================

    async def _handle_cooking(self, args: str) -> Tuple[str, ParseMode, None]:
        """处理菜谱查询"""
        if not args:
            return (
                "❌ *菜谱查询*\n\n"
                "请提供菜名\n\n"
                "*使用方法:*\n"
                "`cooking 宫保鸡丁`\n"
                "`cooking 红烧肉`",
                ParseMode.MARKDOWN_V2,
                None
            )

        from utils.formatter import escape_v2

        return (
            f"👨‍🍳 *菜谱查询*\n\n"
            f"搜索: {escape_v2(args)}\n\n"
            f"💡 请在私聊中使用 `/cooking {escape_v2(args)}` 获取详细菜谱",
            ParseMode.MARKDOWN_V2,
            None
        )

    async def _handle_bin(self, args: str) -> Tuple[str, ParseMode, None]:
        """处理 BIN 查询 - 调用完整的 bin 功能"""
        from commands.bin import bin_inline_execute
        from utils.formatter import foldable_text_with_markdown_v2

        result = await bin_inline_execute(args)

        if result["success"]:
            return (foldable_text_with_markdown_v2(result["message"]), ParseMode.MARKDOWN_V2, None)
        else:
            error_message = f"❌ *{result['title']}*\n\n{result['message']}"
            return (foldable_text_with_markdown_v2(error_message), ParseMode.MARKDOWN_V2, None)

    async def _handle_whois(self, args: str) -> Tuple[str, ParseMode, None]:
        """处理 WHOIS 查询"""
        if not args:
            return (
                "❌ *域名查询*\n\n"
                "请提供域名\n\n"
                "*使用方法:*\n"
                "`whois google.com`",
                ParseMode.MARKDOWN_V2,
                None
            )

        from utils.formatter import escape_v2

        return (
            f"🌐 *域名查询*\n\n"
            f"域名: {escape_v2(args)}\n\n"
            f"💡 请在私聊中使用 `/whois {escape_v2(args)}` 获取详细信息",
            ParseMode.MARKDOWN_V2,
            None
        )

    async def _handle_map(self, args: str) -> Tuple[str, ParseMode, None]:
        """处理地图查询"""
        if not args:
            return (
                "❌ *地图查询*\n\n"
                "请提供地点\n\n"
                "*使用方法:*\n"
                "`map beijing`",
                ParseMode.MARKDOWN_V2,
                None
            )

        from utils.formatter import escape_v2

        return (
            f"🗺️ *地图查询*\n\n"
            f"地点: {escape_v2(args)}\n\n"
            f"💡 请在私聊中使用 `/map {escape_v2(args)}` 获取地图信息",
            ParseMode.MARKDOWN_V2,
            None
        )

    async def _handle_flight(self, args: str) -> Tuple[str, ParseMode, None]:
        """处理航班查询"""
        if not args:
            return (
                "❌ *航班查询*\n\n"
                "请提供航班号\n\n"
                "*使用方法:*\n"
                "`flight CA1234`",
                ParseMode.MARKDOWN_V2,
                None
            )

        from utils.formatter import escape_v2

        return (
            f"✈️ *航班查询*\n\n"
            f"航班号: {escape_v2(args)}\n\n"
            f"💡 请在私聊中使用 `/flight {escape_v2(args)}` 获取详细信息",
            ParseMode.MARKDOWN_V2,
            None
        )

    async def _handle_hotel(self, args: str) -> Tuple[str, ParseMode, None]:
        """处理酒店查询"""
        if not args:
            return (
                "❌ *酒店查询*\n\n"
                "请提供城市或酒店名\n\n"
                "*使用方法:*\n"
                "`hotel beijing`",
                ParseMode.MARKDOWN_V2,
                None
            )

        from utils.formatter import escape_v2

        return (
            f"🏨 *酒店查询*\n\n"
            f"搜索: {escape_v2(args)}\n\n"
            f"💡 请在私聊中使用 `/hotel {escape_v2(args)}` 获取详细信息",
            ParseMode.MARKDOWN_V2,
            None
        )

    # ============================================================================
    # 默认处理器
    # ============================================================================

    def _default_handler(self, command: str, args: str) -> Tuple[str, ParseMode, None]:
        """默认处理器 - 命令未实现"""
        from utils.formatter import escape_v2

        return (
            f"🔍 *{escape_v2(command.upper())}*\n\n"
            f"该命令的 inline mode 支持正在开发中\n\n"
            f"💡 请在私聊中使用 `/{escape_v2(command)} {escape_v2(args)}` 获取完整功能",
            ParseMode.MARKDOWN_V2,
            None
        )
