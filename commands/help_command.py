# type: ignore
import logging

from telegram import Update
from telegram.ext import ContextTypes

from utils.command_factory import command_factory
from utils.formatter import foldable_text_with_markdown_v2
from utils.message_manager import delete_user_command, send_help

# 导入权限相关模块
from utils.permissions import Permission, get_user_permission


logger = logging.getLogger(__name__)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """显示机器人帮助信息"""

    # 添加 null 检查
    if not update.message:
        return

    # 立即删除用户命令（与其他命令保持一致）
    await delete_user_command(context, update.message.chat_id, update.message.message_id)

    # 获取用户权限，如果没有权限就默认为NONE
    user_permission = await get_user_permission(update, context)
    if user_permission is None:
        user_permission = Permission.NONE

    help_text = """🤖 *多功能价格查询机器人*

🔹 *功能概览*
💱 `/rate USD 100` \\\\- 汇率换算 \\\\| 🪙 `/crypto btc` \\\\- 币价查询
💳 `/bin 123456` \\\\- BIN信息 \\\\| 🌦️ `/tq 北京` \\\\- 天气预报
🎬 `/movie 复仇者` \\\\- 影视信息 \\\\| 📺 `/nf` \\\\- 流媒体价格
🎮 `/steam 赛博朋克` \\\\- 游戏价格 \\\\| 👤 `/when 123` \\\\- 用户信息

💱 *汇率* `/rate \\[货币\\] \\[数额\\]` \\\\- 支持表达式计算
🪙 *加密货币* `/crypto <币种> \\[数量\\] \\[货币\\]` \\\\- 实时价格
💳 *BIN查询* `/bin <6\\\\-8位>` \\\\- 信用卡信息
🌦️ *天气* `/tq <城市> \\[天数\\]` \\\\- 天气\\\\&空气质量

🎬 *影视查询*
搜索: `/movie <片名>` `/tv <剧名>` `/person <演员>`
热门: `/movie_hot` `/tv_hot` `/trending`
平台: TMDB\\\+JustWatch\\\+Trakt 三源整合

🎮 *Steam* `/steam <游戏> \\[国家\\]` \\\\| `/steamb <包名>`
📺 *流媒体* `/nf` `/ds` `/sp` `/max` \\\\- Netflix/Disney\\\+/Spotify/HBO
📱 *应用* `/app <名称>` `/gp <名称>` \\\\| `/aps <服务>`
👤 *用户* `/when <ID/@用户>` `/id` \\\\- 注册时间\\\\&ID信息

🌍 *支持地区* US CN TR IN MY JP GB DE 等40\\\+国家
💡 *特色* 支持中文地名 \\\\| 自动CNY转换 \\\\| 智能缓存 \\\\| 表达式计算

⚡ 快速试用: `/nf` `/crypto btc` `/tq 北京` `/movie_hot`"""

    admin_help_text = """

🔧 *管理员*
权限: `/admin` `/add <ID>` `/addgroup`
缓存: `/rate_cleancache` `/crypto_cleancache` 等
用户: `/cache` `/cleanid \\[天数\\]`
数据: `/addpoint` `/removepoint` `/listpoints`"""

    super_admin_help_text = """

🔐 *超级管理员*
系统控制、安全配置、日志管理等完整权限"""

    # 根据用户权限显示不同的帮助内容
    if user_permission == Permission.NONE:
        # 为非白名单用户显示限制性帮助信息
        help_text = """🤖 *多功能价格查询机器人*

🎆 *公开功能*
📺 *流媒体价格* `/nf` `/ds` `/sp` `/max` \\\\- Netflix/Disney\\\+/Spotify/HBO
👤 *用户信息* `/when <ID/@用户>` `/id` \\\\- 注册时间\\\\&ID查询

🌍 *支持地区* US CN TR IN MY JP GB DE 等40\\\+国家
💡 *特色* 支持中文地名 \\\\| 自动CNY转换

⚡ *快速试用* `/nf` `/ds` `/sp` `/max` `/when` `/id`

🔒 *白名单专享*
💱 汇率换算 \\\\| 🪙 加密货币 \\\\| 💳 BIN查询 \\\\| 🌦️ 天气预报
🎬 影视信息 \\\\| 🎮 Steam游戏 \\\\| 📱 应用查询 \\\\| 🍎 Apple服务

📞 白名单功能暂不开放申请，敬请期待付费服务"""
    else:
        # 为白名单用户显示完整的帮助信息  
        pass  # 使用上面定义的简约版help_text
        
        # 添加管理员功能说明（如果用户有相应权限）
        if user_permission and user_permission.value >= Permission.ADMIN.value:
            help_text += admin_help_text

        if user_permission and user_permission.value >= Permission.SUPER_ADMIN.value:
            help_text += super_admin_help_text

    # 根据用户权限添加不同的联系信息
    if user_permission != Permission.NONE:
        help_text += """

📞 如有问题请联系管理员"""

    await send_help(context, update.message.chat_id, foldable_text_with_markdown_v2(help_text), parse_mode="MarkdownV2")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理/start命令"""
    # 添加 null 检查
    if not update.message or not update.effective_user:
        return

    # 立即删除用户命令（与其他命令保持一致）
    await delete_user_command(context, update.message.chat_id, update.message.message_id)

    user = update.effective_user
    
    # 获取用户权限
    user_permission = await get_user_permission(update, context)
    if user_permission is None:
        user_permission = Permission.NONE

    # 根据用户权限显示不同的欢迎信息
    if user_permission == Permission.NONE:
        # 非白名单用户 - 只显示可用功能
        welcome_text = f"""👋 *欢迎 {user.first_name}\\! 多功能价格查询机器人*

🎯 *公开功能*
📺 流媒体价格 `/nf` `/ds` `/sp` `/max`
👤 用户信息 `/when` `/id`

🚀 *试试看*
`/nf` \\\\- Netflix全球价格
`/ds` \\\\- Disney\\\+全球价格
`/sp` \\\\- Spotify全球价格
`/max` \\\\- HBO Max全球价格
`/help` \\\\- 查看详细功能

🌟 支持40\\\+国家 \\\\| 自动CNY转换 \\\\| 中文地名"""
    else:
        # 白名单用户 - 显示完整功能
        welcome_text = f"""👋 *欢迎 {user.first_name}\\! 多功能价格查询机器人*

🎯 *全功能版本*
💱 汇率 🪙 币价 💳 BIN 🌦️ 天气 🎬 影视 🎮 游戏 📺 流媒体 📱 应用

🚀 *快速开始*
`/rate USD 100` `/crypto btc` `/tq 北京` `/movie_hot`
`/steam 赛博朋克` `/nf` `/help`

🌟 40\\\+国家 \\\\| CNY转换 \\\\| 智能缓存 \\\\| 表达式计算"""

    await send_help(context, update.message.chat_id, foldable_text_with_markdown_v2(welcome_text), parse_mode="MarkdownV2")


# Register commands
command_factory.register_command(
    "start",
    start_command,
    permission=Permission.NONE,
    description="开始使用机器人",
    use_retry=False,
    use_rate_limit=False,
)
command_factory.register_command(
    "help", help_command, permission=Permission.NONE, description="显示帮助信息", use_retry=False, use_rate_limit=False
)
