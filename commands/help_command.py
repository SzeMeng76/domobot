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


    admin_help_text = """

🔧 *管理员*
核心: `/admin` `/add <ID>` `/addgroup`
缓存: `/movie_cleancache` `/rate_cleancache` `/crypto_cleancache` 等
用户: `/cache` `/cleanid` `/addpoint` `/removepoint`"""

    super_admin_help_text = """
🔐 *超管* 完整系统权限"""

    # 根据用户权限显示不同的帮助内容
    if user_permission == Permission.NONE:
        # 为非白名单用户显示限制性帮助信息
        help_text = """🤖 *多功能价格查询机器人*

🎆 *公开功能 (无需白名单):*

📺 *流媒体价格*
`/nf` `/ds` `/sp` `/max` - Netflix、Disney+、Spotify、HBO Max全球价格

👤 *用户信息*
`/when <ID/@用户名>` - 查询注册日期
`/id` - 获取用户/群组ID

⚡ *快速开始*
`/nf` `/ds` `/sp` `/max` `/when 123456789` `/id`

🔒 *白名单功能预览*
💱汇率 🪙加密货币 💳BIN查询 🌦️天气 🎬影视 🎮Steam 📱应用

💡 支持40+国家，自动转CNY，智能缓存
🔄 消息自动删除保持整洁
📞 白名单暂不开放，期待付费服务"""
    else:
        # 为白名单用户显示完整的帮助信息
        help_text = """🤖 *多功能价格查询机器人*

💱 *汇率* `/rate <币种> [数量]` - 实时汇率，支持表达式

🪙 *加密货币* `/crypto <币种> [数量]` - 加密货币价格

💳 *BIN查询* `/bin <6-8位>` - 信用卡信息

🌦️ *天气* `/tq <城市> [天数]` - 天气预报

🎬 *影视*
搜索: `/movie <名称>` `/tv <名称>` `/person <姓名>`
排行: `/charts` `/chart_compare <标题>`
热门: `/movie_hot` `/tv_hot` `/trending`

🎮 *Steam* `/steam <游戏> [国家]` `/steamb <包名>`

📺 *流媒体* `/nf` `/ds` `/sp` `/max` - 全球价格对比

📱 *应用* `/app <名称>` `/gp <名称>` `/aps <服务>`

👤 *用户* `/when <ID/@用户名>` `/id` - 注册日期和ID

⚡ *快速体验*
`/rate USD 100` `/crypto btc` `/tq 北京` `/movie 阿凡达` `/charts` `/nf`

💡 40+国家 | 自动转CNY | 智能缓存 | 数学表达式
🔄 消息自动删除保持整洁"""
        
        # 添加管理员功能说明（如果用户有相应权限）
        if user_permission and user_permission.value >= Permission.ADMIN.value:
            help_text += admin_help_text

        if user_permission and user_permission.value >= Permission.SUPER_ADMIN.value:
            help_text += super_admin_help_text

    # 根据用户权限添加不同的联系信息
    if user_permission == Permission.NONE:
        # 非白名单用户已经在上面包含了申请白名单的信息
        pass
    else:
        help_text += """

📞 *联系我们:*
如需申请使用权限或遇到问题，请联系机器人管理员。"""

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
        welcome_text = f"""👋 *欢迎 {user.first_name}!*

🎯 *免费功能:*
📺 流媒体价格 - Netflix、Disney+、Spotify、HBO Max
👤 用户信息 - 注册日期、账号年龄、ID查询

🚀 *快速开始:*
`/nf` `/ds` `/sp` `/max` `/id` `/when` `/help`

✅ 40+国家 | 自动转CNY | 智能缓存 | 中文支持

🔒 白名单用户还可使用汇率、加密货币、天气、影视等高级功能

开始探索吧! 🎉"""
    else:
        # 白名单用户 - 显示完整功能
        welcome_text = f"""👋 *欢迎 {user.first_name}!*

🎯 *全功能访问:*
💱汇率 🪙加密货币 💳BIN查询 🌦️天气 🎬影视 🎮Steam 📺流媒体 📱应用 👤用户信息

🚀 *快速体验:*
`/rate USD 100` `/crypto btc` `/tq 北京` `/movie 阿凡达` `/charts` `/steam 赛博朋克` `/nf` `/help`

✅ 40+国家 | 自动转CNY | 智能缓存 | 数学表达式 | 中文支持

开始探索吧! 🎉"""

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
