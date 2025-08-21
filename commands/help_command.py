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
💱 `/rate USD 100` - 汇率换算 | 🪙 `/crypto btc` - 币价查询
💳 `/bin 123456` - BIN信息 | 🌦️ `/tq 北京` - 天气预报
🎬 `/movie 复仇者` - 影视信息 | 📺 `/nf` - 流媒体价格
🎮 `/steam 赛博朋克` - 游戏价格 | 👤 `/when 123` - 用户信息
⏰ `/time 北京` - 时间查询 | 📰 `/news` - 新闻聚合
🌐 `/whois google.com` - WHOIS查询 | 🔍 `/dns domain.com` - DNS记录
🍳 `/recipe 红烧肉` - 菜谱搜索 | 🎭 `/meme 3` - 表情包
📊 `/finance AAPL` - 股票查询 | 📈 `/finance` - 股市排行榜

💱 *汇率* `/rate [货币] [数额]` - 支持表达式计算
🪙 *加密货币* `/crypto <币种> [数量] [货币]` - 实时价格
💳 *BIN查询* `/bin <6-8位>` - 信用卡信息
🌦️ *天气* `/tq <城市> [天数]` - 天气&空气质量
⏰ *时间* `/time <时区>` - 时间查询 | `/convert_time <源> <时间> <目标>` - 时区转换
📰 *新闻* `/news` - 交互式选择 | `/newslist [源] [数量]` - 列表查询
🌐 *WHOIS&DNS* `/whois <查询>` - 域名/IP/ASN/TLD信息(含DNS) | `/dns <域名>` - 仅DNS记录
🍳 *烹饪助手* `/recipe <菜名>` - 菜谱搜索 | `/what_to_eat` - 今天吃什么 | `/meal_plan` - 智能膳食
📊 *股票金融* `/finance <代号/公司名>` - 实时股价查询 | `/finance` - 15类股票&基金排行榜

🎬 *影视查询*
搜索: `/movie <片名>` `/tv <剧名>` `/person <演员>`
热门: `/movie_hot` `/tv_hot` `/trending`
排行: `/streaming_movie_ranking` `/streaming_tv_ranking`
平台: TMDB+JustWatch+Trakt 三源整合

🎮 *Steam* `/steam <游戏> [国家]` | `/steamb <包名>`
📺 *流媒体* `/nf` `/ds` `/sp` `/max` - Netflix/Disney+/Spotify/HBO
📱 *应用商店* `/app <名称>` - 详细内购项目 | `/gp <名称>` - 内购价格范围 | `/aps <服务>`
👤 *用户* `/when <ID/@用户>` `/id` - 注册时间&ID信息
⏰ *时区* `/time <时区>` `/timezone` - 时间查询&时区列表
📰 *新闻* `/news` `/newslist` `/hotnews` - 40+源实时资讯

🌍 *支持地区* US CN TR IN MY JP GB DE 等40+国家
💡 *特色* 支持中文地名 | 自动CNY转换 | 智能缓存 | 表达式计算

⚡ 快速试用: `/nf` `/crypto btc` `/tq 北京` `/movie_hot` `/news` `/time 北京` `/whois google.com` `/dns github.com` `/recipe 红烧肉` `/what_to_eat` `/meme 3` `/finance AAPL`"""

    admin_help_text = """

🔧 *管理员*
权限: `/admin` `/add <ID>` `/addgroup`
缓存: `/cleancache` - 统一缓存管理菜单 | `/cleancache all` - 清理全部
用户: `/cache` `/cleanid [天数]`
数据: `/addpoint` `/removepoint` `/listpoints`"""

    super_admin_help_text = """

🔐 *超级管理员*
系统控制、安全配置、日志管理等完整权限"""

    # 根据用户权限显示不同的帮助内容
    if user_permission == Permission.NONE:
        # 为非白名单用户显示限制性帮助信息
        help_text = """🤖 *多功能价格查询机器人*

🎆 *公开功能*
📺 *流媒体价格* `/nf` `/ds` `/sp` `/max` - Netflix/Disney+/Spotify/HBO
👤 *用户信息* `/when <ID/@用户>` `/id` - 注册时间&ID查询
⏰ *时间查询* `/time <时区>` `/convert_time` `/timezone` - 时区转换
📰 *新闻聚合* `/news` `/newslist` `/hotnews` - 40+源实时资讯
🌐 *WHOIS&DNS查询* `/whois <查询>` - 域名/IP/ASN/TLD信息(含DNS) | `/dns <域名>` - 仅DNS记录
📊 *股票金融* `/finance <代号/公司名>` - 实时股价 | `/finance` - 15类排行榜

🍳 *烹饪助手*
搜索: `/recipe <菜名>` - 智能菜谱搜索 | `/recipe_category` - 分类浏览
推荐: `/what_to_eat` - 今天吃什么 | `/meal_plan` - 智能膳食规划
发现: `/recipe_random` - 随机菜谱 | 支持过敏&忌口设置

🎭 *表情包娱乐*
随机: `/meme <数量>` - 获取1-20个随机表情包 | 自动删除 | 智能缓存

🌍 *支持地区* US CN TR IN MY JP GB DE 等40+国家
💡 *特色* 支持中文地名 | 自动CNY转换 | 时区智能识别 | 新闻分类 | 1000+中文菜谱 | 多市场股票

⚡ *快速试用* `/nf` `/ds` `/sp` `/max` `/when` `/id` `/time 北京` `/news` `/recipe 红烧肉` `/what_to_eat` `/meme 3` `/finance AAPL`

🔧 *命令问题?* 如果新功能不显示，请使用 `/refresh` 刷新命令列表

🔒 *白名单专享*
💱 汇率换算 | 🪙 加密货币 | 💳 BIN查询 | 🌦️ 天气预报
🎬 影视信息 | 🎮 Steam游戏 | 📱 应用&内购价格 | 🍎 Apple服务

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
        welcome_text = f"""👋 *欢迎 {user.first_name}! 多功能价格查询机器人*

🎯 *公开功能*
📺 流媒体价格 `/nf` `/ds` `/sp` `/max`
👤 用户信息 `/when` `/id`
⏰ 时间查询 `/time` `/convert_time` `/timezone`
📰 新闻聚合 `/news` `/newslist` `/hotnews`
🌐 WHOIS&DNS查询 `/whois` `/dns` - 域名/IP/ASN/TLD+DNS记录
🍳 烹饪助手 `/recipe` `/what_to_eat` `/meal_plan`
🎭 表情包娱乐 `/meme` - 随机表情包获取
📊 股票金融 `/finance` - 实时股价&15类排行榜

🚀 *试试看*
`/nf` - Netflix全球价格
`/ds` - Disney+全球价格
`/sp` - Spotify全球价格
`/max` - HBO Max全球价格
`/meme 3` - 获取3个表情包
`/time 北京` - 北京时间
`/news` - 交互式新闻界面
`/newslist zhihu` - 知乎热榜
`/convert_time 中国 14:30 美国` - 时区转换
`/whois google.com` - WHOIS+DNS查询
`/dns github.com` - DNS记录查询
`/recipe 红烧肉` - 菜谱搜索
`/what_to_eat` - 今天吃什么
`/finance AAPL` - 苹果股票查询
`/finance Tesla` - 特斯拉股票搜索
`/help` - 查看详细功能

🌟 支持40+国家 | 自动CNY转换 | 中文地名 | 时区智能识别 | 新闻分类 | 1000+中文菜谱 | 随机表情包 | 多市场股票

🔧 命令不显示? 试试 `/refresh` 刷新命令列表"""
    else:
        # 白名单用户 - 显示完整功能
        welcome_text = f"""👋 *欢迎 {user.first_name}! 多功能价格查询机器人*

🎯 *全功能版本*
💱 汇率 🪙 币价 💳 BIN 🌦️ 天气 🎬 影视 🎮 游戏 📺 流媒体 📱 应用 ⏰ 时间 📰 新闻 🍳 烹饪 🎭 表情包 📊 股票金融

🚀 *快速开始*
`/rate USD 100` `/crypto btc` `/tq 北京` `/movie_hot`
`/steam 赛博朋克` `/nf` `/time 北京` `/whois google.com` `/dns github.com` `/news` `/recipe 红烧肉` `/meme 3` `/finance AAPL` `/help`

🌟 40+国家 | CNY转换 | 智能缓存 | 表达式计算 | 时区转换 | 新闻聚合 | 1000+中文菜谱 | 股市数据"""

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
