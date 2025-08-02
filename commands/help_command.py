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

✨ *主要功能:*

💱 *汇率查询*
- `/rate`: 查看汇率查询帮助。
- `/rate USD`: 100美元(USD)兑换人民币(CNY)。
- `/rate USD JPY 50`: 50美元(USD)兑换日元(JPY)。
- `/rate USD 1+1`: 计算表达式并将结果从美元(USD)兑换为人民币(CNY)。

🪙 *加密货币查询*
- `/crypto <币种>`: 查询加密货币对CNY的价格。
- `/crypto <币种> <数量>`: 查询指定数量的加密货币价格。
- `/crypto <币种> <数量> <货币>`: 查询对指定货币的价格。

💳 *信用卡BIN查询*
- `/bin <BIN号码>`: 查询信用卡BIN信息 (卡头6\\-8位数字)。
- 支持查询卡片品牌、类型、发卡银行、国家等信息。
- 例如: `/bin 123456`, `/bin 12345678`。

🌦️ *天气查询*
- `/tq <城市>`: 查询城市的实时天气和空气质量。
- `/tq <城市> <天数>`: 查询未来多日天气 (最多7天)。
- `/tq <城市> <参数>`: 支持 `24h`, `降水`, `指数` 等高级查询。

🎬 *电影和电视剧查询*
- `/movie <电影名>`: 搜索电影信息。
- `/movie_hot`: 获取当前热门电影排行榜。
- `/movie_detail <电影ID>`: 获取电影详情 (演员、导演、票房等，含预告片链接)。
- `/movie_rec <电影ID>`: 获取基于指定电影的相似推荐。
- `/movie_videos <电影ID>`: 获取电影预告片和相关视频。
- `/movie_watch <电影ID>`: 获取电影在各平台的观看信息。
- `/tv <电视剧名>`: 搜索电视剧信息。
- `/tv_hot`: 获取当前热门电视剧排行榜。
- `/tv_detail <电视剧ID>`: 获取电视剧详情 (演员、季数、集数等，含预告片链接)。
- `/tv_rec <电视剧ID>`: 获取基于指定电视剧的相似推荐。
- `/tv_videos <电视剧ID>`: 获取电视剧预告片和相关视频。
- `/tv_watch <电视剧ID>`: 获取电视剧在各平台的观看信息。
- `/tv_season <电视剧ID> <季数>`: 获取指定季的详细信息和剧集列表。
- `/tv_episode <电视剧ID> <季数> <集数>`: 获取单集详情。

🔥 *热门趋势内容*
- `/trending`: 获取今日全球热门电影、电视剧和人物。
- `/trending_week`: 获取本周全球热门内容排行。
- `/now_playing`: 获取正在上映的电影列表。
- `/upcoming`: 获取即将上映的电影预告。
- `/tv_airing`: 获取今日播出的电视剧。
- `/tv_on_air`: 获取正在播出的电视剧。

👤 *人物信息查询*
- `/person <人物名>`: 搜索演员、导演等影视人物。
- `/person_detail <人物ID>`: 获取人物详情 (作品、简介等)。

🎮 *Steam 价格查询*
- `/steam <游戏名>`: 查询Steam游戏在默认地区的价格。
- `/steam <游戏名> [国家代码]`: 在指定的一个或多个国家/地区查询游戏价格。
- `/steamb <捆绑包名/ID>`: 查询Steam捆绑包的价格和内容。
- `/steams <关键词>`: 综合搜索游戏和捆绑包。

📺 *流媒体服务价格*
- `/nf [国家代码]`: 查询Netflix订阅价格 (默认查询热门地区)。
- `/ds [国家代码]`: 查询Disney+订阅价格 (默认查询热门地区)。
- `/sp [国家代码]`: 查询Spotify Premium价格 (默认查询热门地区)。
- `/max`: 查询HBO Max全球最低价格排名 (默认Ultimate年付套餐)。
- `/max [套餐类型]`: 按套餐类型查询排名 (支持: `all`, `monthly`, `yearly`, `ultimate`, `mobile`, `standard`)。
- `/max [套餐类型] <国家代码>`: 查询指定国家的HBO Max价格。
- 例如: `/max ultimate_yearly`, `/max monthly US CN`。

📱 *应用与服务价格*
- `/app <应用名>`: 搜索App Store应用。
- `/gp <应用名>`: 搜索Google Play应用。
- `/aps <服务> [国家代码]`: 查询Apple服务价格 (服务: `iCloud`, `AppleOne`, `AppleMusic`)。

👤 *用户信息查询*
- `/when <用户ID>`: 根据用户ID估算Telegram注册日期和账号年龄。
- `/when @username`: 通过用户名查询注册信息（支持缓存用户）。
- `/when` (回复消息): 查询被回复用户的注册信息。
- `/id`: 获取当前用户或群组的ID信息。
- `/id` (回复消息): 获取被回复用户的详细ID信息。

🌍 *支持的国家/地区示例:*
`US`(美国), `CN`(中国), `TR`(土耳其), `NG`(尼日利亚), `IN`(印度), `MY`(马来西亚), `JP`(日本), `GB`(英国), `DE`(德国) 等。

💡 *使用技巧:*
- 大部分命令支持中文国家名，如"美国"、"土耳其"。
- 不指定国家时，通常会查询多个热门或低价区。
- 所有价格会自动转换为人民币(CNY)以供参考。
- 数据具有智能缓存，提高响应速度且减少API调用。
- 支持数学表达式计算，如 `/rate USD 1+1*2`。

⚡ *快速开始:*
- `/rate USD 100`: 查询100美元兑人民币汇率。
- `/crypto btc`: 查询比特币价格。
- `/bin 123456`: 查询信用卡BIN信息。
- `/tq 北京`: 查询北京天气。
- `/movie 复仇者联盟`: 搜索电影信息。
- `/tv 权力的游戏`: 搜索电视剧信息。
- `/movie_videos 299534`: 查看电影预告片。
- `/trending`: 查看今日热门内容。
- `/person 汤姆·汉克斯`: 搜索影视人物。
- `/steam 赛博朋克`: 查询《赛博朋克2077》价格。
- `/nf`: 查看Netflix全球价格排名。
- `/ds`: 查看Disney+全球价格排名。
- `/sp`: 查看Spotify全球价格排名。
- `/max`: 查看HBO Max全球价格排名。
- `/app 微信`: 搜索App Store应用。
- `/gp WeChat`: 搜索Google Play应用。
- `/aps iCloud`: 查询iCloud全球价格。
- `/when 123456789`: 查询用户注册日期和账号年龄（支持用户名查询）。
- `/id`: 获取用户或群组的ID信息。

🔄 *消息管理:*
- 所有回复消息会自动删除以保持群聊整洁。
- 支持按钮交互，避免重复输入命令。"""

    admin_help_text = """

🔧 *管理员功能*

核心: `/admin` `/add <ID>` `/addgroup`
缓存清理: `/rate_cleancache` `/crypto_cleancache` `/bin_cleancache` `/tq_cleancache` `/tq_cleanlocation` `/tq_cleanforecast` `/tq_cleanrealtime` `/movie_cleancache` `/nf_cleancache` `/ds_cleancache` `/sp_cleancache` `/max_cleancache` `/gp_cleancache` `/app_cleancache` `/steamcc` `/aps_cleancache`
用户管理: `/cache [用户]` `/cleanid [天数]`
数据点: `/addpoint <ID> <日期>` `/removepoint <ID>` `/listpoints [数量]`"""

    super_admin_help_text = """

🔐 *超级管理员*
高级管理、系统控制、安全配置、日志管理、脚本控制等完整权限"""

    # 根据用户权限显示不同的帮助内容
    if user_permission == Permission.NONE:
        # 为非白名单用户显示限制性帮助信息
        help_text = """🤖 *多功能价格查询机器人*

🎆 *公开可用功能:*

以下功能不需要注册或白名单，所有用户都可以直接使用：

📺 *流媒体服务价格*
- `/nf [国家代码]`: 查询Netflix订阅价格 (默认查询热门地区)。
- `/ds [国家代码]`: 查询Disney+订阅价格 (默认查询热门地区)。
- `/sp [国家代码]`: 查询Spotify Premium价格 (默认查询热门地区)。
- `/max`: 查询HBO Max全球最低价格排名 (默认Ultimate年付套餐)。
- `/max [套餐类型]`: 按套餐类型查询排名 (支持: `all`, `monthly`, `yearly`, `ultimate`, `mobile`, `standard`)。
- `/max [套餐类型] <国家代码>`: 查询指定国家的HBO Max价格。
- 例如: `/max ultimate_yearly`, `/max monthly US CN`。

👤 *用户信息查询*
- `/when <用户ID>`: 根据用户ID估算Telegram注册日期和账号年龄。
- `/when @username`: 通过用户名查询注册信息（支持缓存用户）。
- `/when` (回复消息): 查询被回复用户的注册信息。
- `/id`: 获取当前用户或群组的ID信息。
- `/id` (回复消息): 获取被回复用户的详细ID信息。

🌍 *支持的国家/地区示例:*
`US`(美国), `CN`(中国), `TR`(土耳其), `NG`(尼日利亚), `IN`(印度), `MY`(马来西亚), `JP`(日本), `GB`(英国), `DE`(德国) 等。

💡 *使用技巧:*
- 大部分命令支持中文国家名，如"美国"、"土耳其"。
- 不指定国家时，通常会查询多个热门或低价区。
- 所有价格会自动转换为人民币(CNY)以供参考。

⚡ *快速开始:*
- `/nf`: 查看Netflix全球价格排名。
- `/ds`: 查看Disney+全球价格排名。
- `/sp`: 查看Spotify全球价格排名。
- `/max`: 查看HBO Max全球价格排名。
- `/when 123456789`: 查询用户注册日期和账号年龄（支持用户名查询）。
- `/id`: 获取用户或群组的ID信息。

🔒 *白名单专享功能预览:*
白名单用户还可以使用以下高级功能：
- 💱 实时汇率查询和货币转换
- 🪙 加密货币价格查询
- 💳 信用卡BIN信息查询
- 🌦️ 天气查询和预报
- 🎬 电影和电视剧信息查询
- 🎮 Steam游戏价格查询
- 📱 App Store和Google Play应用查询
- 🍎 Apple各项服务价格查询

🔄 *消息管理:*
- 所有回复消息会自动删除以保持群聊整洁。
- 支持按钮交互，避免重复输入命令。

📞 *关于白名单:*
白名单功能暂不开放申请，敬请期待后续付费服务计划。"""
    else:
        # 为白名单用户显示完整的帮助信息
        help_text = """🤖 *多功能价格查询机器人*

💱 *汇率查询*
- `/rate [货币]`: 汇率查询，支持表达式计算

🪙 *加密货币*
- `/crypto <币种> [数量] [货币]`: 加密货币价格查询

💳 *BIN查询*
- `/bin <6-8位数字>`: 信用卡BIN信息查询

🌦️ *天气查询*
- `/tq <城市> [天数/参数]`: 天气预报和空气质量

🎬 *影视查询*
电影: `/movie`, `/movie_hot`, `/movie_detail <ID>`, `/movie_rec <ID>`, `/movie_videos <ID>`, `/movie_watch <ID>`
电视: `/tv`, `/tv_hot`, `/tv_detail <ID>`, `/tv_rec <ID>`, `/tv_videos <ID>`, `/tv_watch <ID>`, `/tv_season <ID> <季数>`, `/tv_episode <ID> <季> <集>`
趋势: `/trending`, `/trending_week`, `/now_playing`, `/upcoming`, `/tv_airing`, `/tv_on_air`
人物: `/person <姓名>`, `/person_detail <ID>`

🎮 *Steam游戏*
- `/steam <游戏名> [国家]`: 游戏价格查询
- `/steamb <包名/ID>`: 捆绑包查询
- `/steams <关键词>`: 综合搜索

📺 *流媒体价格*
- `/nf [国家]`: Netflix价格
- `/ds [国家]`: Disney+价格
- `/sp [国家]`: Spotify价格
- `/max [类型] [国家]`: HBO Max价格

📱 *应用价格*
- `/app <名称>`: App Store应用
- `/gp <名称>`: Google Play应用
- `/aps <服务> [国家]`: Apple服务价格

👤 *用户信息*
- `/when <用户ID/@用户名>`: 注册日期查询
- `/id`: 获取ID信息

🌍 *支持地区*: US, CN, TR, NG, IN, MY, JP, GB, DE 等40+国家

💡 *使用提示*
- 支持中文国家名
- 自动转换为CNY
- 智能缓存加速
- 支持数学表达式

⚡ *快速开始*
`/rate USD 100` `/crypto btc` `/bin 123456` `/tq 北京` `/movie 复仇者联盟` `/steam 赛博朋克` `/nf` `/when 123456789`

🔄 消息会自动删除保持整洁"""
        
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
        welcome_text = f"""👋 *欢迎使用多功能价格查询机器人!*

你好 {user.first_name}!

🎯 *你可以使用这些功能:*
- 📺 查询Netflix、Disney+、Spotify、HBO Max等流媒体订阅价格
- 👤 查询Telegram用户注册日期和账号年龄
- 🆔 获取用户和群组的ID信息

💡 *快速开始:*
发送 `/help` 查看详细使用指南

🚀 *试试这些命令:*
- `/nf`: 查看Netflix全球价格
- `/ds`: 查看Disney+全球价格  
- `/sp`: 查看Spotify全球价格
- `/max`: 查看HBO Max全球价格
- `/id`: 获取你的用户ID
- `/when`: 查询账号注册时间

🌟 *功能亮点:*
✅ 支持40+国家和地区查询
✅ 实时汇率自动转换为人民币
✅ 智能缓存，查询速度快
✅ 支持中文国家名称输入

开始探索吧! 🎉"""
    else:
        # 白名单用户 - 显示完整功能
        welcome_text = f"""👋 *欢迎使用多功能价格查询机器人!*

你好 {user.first_name}!

🎯 *这个机器人可以帮你:*
- 💱 查询实时汇率并进行货币转换
- 🪙 查询加密货币价格和市场数据
- 💳 查询信用卡BIN信息和发卡银行
- 🌦️ 查询全球城市天气和空气质量
- 🎬 查询电影和电视剧信息、评分、演员阵容
- 🎮 查询Steam游戏在全球各国的价格
- 📺 查询Netflix、Disney+、Spotify、HBO Max等流媒体订阅价格
- 📱 查询App Store和Google Play应用价格
- 🍎 查询Apple各项服务的全球定价
- 👤 查询Telegram用户注册日期和账号年龄
- 🆔 获取用户和群组的ID信息

💡 *快速开始:*
发送 `/help` 查看详细使用指南

🚀 *试试这些命令:*
- `/rate USD 100`: 查询100美元兑人民币汇率
- `/crypto btc`: 查询比特币价格
- `/bin 123456`: 查询信用卡BIN信息
- `/tq 北京`: 查询北京天气
- `/movie 复仇者联盟`: 搜索电影信息
- `/tv 权力的游戏`: 搜索电视剧信息
- `/steam 赛博朋克`: 查询游戏价格
- `/steamb Half-Life`: 查询Steam捆绑包
- `/steams 动作`: 综合搜索游戏
- `/nf`: 查看Netflix全球价格
- `/ds`: 查看Disney+全球价格  
- `/sp`: 查看Spotify全球价格
- `/max`: 查看HBO Max全球价格
- `/app 微信`: 搜索App Store应用
- `/gp WeChat`: 搜索Google Play应用
- `/aps iCloud`: 查询Apple服务价格
- `/id`: 获取你的用户ID
- `/when`: 查询账号注册时间

🌟 *功能亮点:*
✅ 支持40+国家和地区查询
✅ 实时汇率自动转换为人民币
✅ 智能缓存，查询速度快
✅ 支持中文国家名称输入
✅ 信用卡BIN信息详细查询
✅ 加密货币实时价格和涨跌幅
✅ 多日天气预报和空气质量
✅ 数学表达式计算支持

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
