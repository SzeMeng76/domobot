# type: ignore
import re
import asyncio
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes

from utils.command_factory import command_factory
from utils.formatter import foldable_text_with_markdown_v2
from utils.message_manager import delete_user_command, send_search_result
from utils.permissions import Permission


class CachedUser:
    """用于构建缓存用户对象的辅助类"""
    def __init__(self, data):
        self.id = data.get("user_id")
        self.username = data.get("username")
        self.first_name = data.get("first_name", "")
        self.last_name = data.get("last_name", "")


async def get_id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    获取用户、群组或回复目标的ID。
    """
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    # 添加 null 检查
    if not message or not chat or not user:
        return

    reply_text = ""

    # 检查是否有回复的消息
    if message.reply_to_message:
        replied_user = message.reply_to_message.from_user
        replied_chat = message.reply_to_message.chat

        if replied_user:
            reply_text += f"👤 *被回复用户ID*: `{replied_user.id}`\n"

            # 添加用户名信息 - 改进显示逻辑
            username = replied_user.username
            first_name = replied_user.first_name or ""
            last_name = replied_user.last_name or ""

            # 优先显示用户名，其次显示完整姓名
            if username:
                reply_text += f"📛 *被回复用户名*: @{username}\n"
            else:
                full_name = f"{first_name} {last_name}".strip()
                if full_name:
                    reply_text += f"📛 *被回复昵称*: {full_name}\n"

            # 显示是否为机器人
            if replied_user.is_bot:
                reply_text += "🤖 *用户类型*: 机器人\n"

        if replied_chat and replied_chat.id != chat.id:
            reply_text += f"➡️ *来源对话ID*: `{replied_chat.id}`\n"

        reply_text += "\n"  # 添加分隔

    # 显示当前对话和用户的ID
    reply_text += f"👤 *您的用户ID*: `{user.id}`\n"
    if chat.type != "private":
        reply_text += f"👨‍👩‍👧‍👦 *当前群组ID*: `{chat.id}`"

    await send_search_result(context, chat.id, foldable_text_with_markdown_v2(reply_text), parse_mode="MarkdownV2")
    await delete_user_command(context, chat.id, message.message_id)


def escape_markdown(text):
    """转义Markdown特殊字符"""
    if not text:
        return text
    
    # Telegram Markdown特殊字符
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    
    return text


def extract_field(text, field_name):
    """从文本中提取特定字段的值，处理富文本和emoji字符"""
    if not text:
        return None
        
    pattern = rf"\s*-\s*{field_name}:\s*(.*?)(?:\n|$)"
    match = re.search(pattern, text)
    
    if match:
        value = match.group(1).strip()
        return value
    
    return None


def format_date(date_str):
    """将英文日期格式转换为中文格式"""
    if not date_str:
        return "未知"
        
    try:
        formats = ["%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y"]
        
        for fmt in formats:
            try:
                date_obj = datetime.strptime(date_str, fmt)
                return f"{date_obj.year}年{date_obj.month}月{date_obj.day}日"
            except ValueError:
                continue
                
        return date_str
    except Exception:
        return date_str


def format_age(age_str):
    """将英文年龄格式转换为中文格式，并返回年数"""
    if not age_str:
        return "未知", 0
    
    try:
        years_match = re.search(r"(\d+)\s+years?", age_str)
        months_match = re.search(r"(\d+)\s+months?", age_str)
        days_match = re.search(r"(\d+)\s+days?", age_str)
        
        years = int(years_match.group(1)) if years_match else 0
        months = int(months_match.group(1)) if months_match else 0
        days = int(days_match.group(1)) if days_match else 0
        
        formatted_age = ""
        if years > 0:
            formatted_age += f"{years}年"
        if months > 0:
            formatted_age += f"{months}月"
        if days > 0 and not years and not months:
            formatted_age += f"{days}天"
        
        return formatted_age or "未知", years
    except Exception:
        return age_str, 0


def determine_level(years):
    """根据账号年龄确定用户级别"""
    if years >= 10:
        return "十年老逼登"
    elif years >= 3:
        return "老兵"
    elif years > 1:
        return "不如老兵"
    else:
        return "新兵蛋子"


def estimate_account_creation_date(user_id):
    """
    基于用户ID估算Telegram账号创建日期
    使用真实用户数据校准的算法
    """
    from datetime import datetime, timedelta
    
    # 基于真实SmartUtilBot查询结果的已知数据点
    # 这些是经过验证的准确映射
    known_points = [
        (1, datetime(2013, 8, 14)),                    # Telegram创始人
        (39, datetime(2013, 8, 14)),                   # 早期用户
        (777000, datetime(2015, 7, 1)),                # 早期bot时期
        (2768409, datetime(2013, 11, 1)),              # 2013年末用户
        (3957805, datetime(2013, 11, 15)),             # ✅ 真实数据点
        (7679610, datetime(2013, 12, 31)),             # 2013年末
        (10858037, datetime(2014, 1, 26)),             # ✅ 真实数据点
        (15835244, datetime(2014, 2, 21)),             # 2014年初
        (39525684, datetime(2014, 3, 16)),             # ✅ 真实数据点
        (44634663, datetime(2014, 5, 6)),              # 2014年中
        (54135846, datetime(2014, 9, 10)),             # ✅ 真实数据点
        (75053905, datetime(2014, 12, 7)),             # ✅ 真实数据点
        (80139402, datetime(2015, 2, 26)),             # 2015年初
        (133275940, datetime(2015, 11, 30)),           # 2015年末
        (234886189, datetime(2016, 7, 3)),             # ✅ 真实数据点
        (278683524, datetime(2016, 9, 9)),             # ✅ 真实数据点
        (309232988, datetime(2016, 12, 20)),           # ✅ 真实数据点
        (334215373, datetime(2017, 1, 31)),            # ✅ 真实数据点
        (446378169, datetime(2017, 10, 8)),            # ✅ 真实数据点
        (462075301, datetime(2017, 11, 1)),            # ✅ 真实数据点
        (474530520, datetime(2017, 11, 19)),           # ✅ 真实数据点
        (480648715, datetime(2017, 11, 29)),           # ✅ 真实数据点
        (554653093, datetime(2018, 3, 20)),            # ✅ 真实数据点
        (620973285, datetime(2018, 6, 24)),            # ✅ 真实数据点1
        (626524659, datetime(2018, 6, 27)),            # ✅ 真实数据点
        (658502219, datetime(2018, 7, 15)),            # ✅ 真实数据点
        (693772643, datetime(2018, 8, 30)),            # ✅ 真实数据点
        (694669879, datetime(2018, 9, 2)),             # ✅ 真实数据点
        (715914969, datetime(2018, 10, 30)),           # ✅ 真实数据点23
        (722887698, datetime(2018, 11, 19)),           # ✅ 真实数据点
        (729200182, datetime(2018, 12, 1)),            # ✅ 真实数据点
        (723490460, datetime(2018, 11, 20)),           # ✅ 真实数据点
        (829504754, datetime(2019, 1, 9)),             # ✅ 真实数据点
        (893199737, datetime(2019, 5, 14)),            # ✅ 真实数据点
        (927869116, datetime(2019, 12, 29)),           # ✅ 真实数据点
        (937572116, datetime(2020, 2, 15)),            # ✅ 真实数据点
        (1086886247, datetime(2020, 2, 22)),           # ✅ 真实数据点8
        (1096626991, datetime(2020, 2, 29)),           # ✅ 真实数据点9
        (1111558803, datetime(2020, 3, 12)),           # ✅ 真实数据点17
        (1157119153, datetime(2020, 4, 23)),           # ✅ 真实数据点
        (1183889270, datetime(2020, 5, 30)),           # ✅ 真实数据点
        (1212910191, datetime(2020, 7, 9)),            # ✅ 真实数据点
        (1229365969, datetime(2020, 7, 31)),           # ✅ 真实数据点
        (1262948436, datetime(2020, 8, 10)),           # ✅ 真实数据点
        (1266389330, datetime(2020, 8, 11)),           # ✅ 真实数据点
        (1285142377, datetime(2020, 8, 17)),           # ✅ 真实数据点
        (1293446607, datetime(2020, 8, 19)),           # ✅ 真实数据点
        (1310788969, datetime(2020, 8, 24)),           # ✅ 真实数据点
        (1364368401, datetime(2020, 9, 10)),           # ✅ 真实数据点4
        (1476361738, datetime(2020, 11, 5)),           # ✅ 真实数据点
        (1493092549, datetime(2020, 11, 14)),          # ✅ 真实数据点
        (1520415315, datetime(2020, 11, 29)),          # ✅ 真实数据点15
        (1523368916, datetime(2020, 12, 1)),           # ✅ 真实数据点
        (1606154208, datetime(2021, 1, 15)),           # ✅ 真实数据点18
        (1659206651, datetime(2021, 2, 13)),           # ✅ 真实数据点
        (1791306977, datetime(2021, 5, 22)),           # ✅ 真实数据点2
        (1918002642, datetime(2021, 6, 30)),           # ✅ 真实数据点
        (1955860134, datetime(2021, 8, 22)),           # ✅ 真实数据点
        (1978440017, datetime(2021, 10, 10)),          # ✅ 真实数据点13
        (2143348318, datetime(2021, 11, 21)),          # ✅ 真实数据点12
        (597485629, datetime(2022, 1, 7)),             # 2022年初
        (5189189426, datetime(2022, 4, 2)),            # ✅ 真实数据点
        (5200884983, datetime(2022, 4, 11)),           # ✅ 真实数据点
        (5213669212, datetime(2022, 4, 21)),           # ✅ 真实数据点7
        (5235138802, datetime(2022, 5, 8)),            # ✅ 真实数据点5
        (5274132863, datetime(2022, 6, 7)),            # ✅ 真实数据点
        (5370825396, datetime(2022, 6, 16)),           # ✅ 真实数据点10
        (5374581898, datetime(2022, 7, 4)),            # ✅ 真实数据点6
        (5734051339, datetime(2022, 10, 20)),          # ✅ 真实数据点
        (5851203976, datetime(2022, 11, 29)),          # ✅ 真实数据点
        (5895507833, datetime(2022, 12, 14)),          # ✅ 真实数据点
        (5912906831, datetime(2022, 12, 20)),          # ✅ 真实数据点
        (5993720903, datetime(2023, 1, 17)),           # ✅ 真实数据点
        (6095955229, datetime(2023, 2, 12)),           # ✅ 真实数据点19
        (6194878274, datetime(2023, 3, 28)),           # ✅ 真实数据点
        (6319592207, datetime(2023, 5, 10)),           # ✅ 真实数据点
        (6339365540, datetime(2023, 5, 17)),           # ✅ 真实数据点
        (6401621907, datetime(2023, 6, 8)),            # ✅ 真实数据点
        (6415978351, datetime(2023, 6, 13)),           # ✅ 真实数据点
        (6447125502, datetime(2023, 6, 23)),           # ✅ 真实数据点
        (6521937258, datetime(2023, 7, 19)),           # ✅ 真实数据点11
        (6537156348, datetime(2023, 7, 24)),           # ✅ 真实数据点14
        (6674181048, datetime(2023, 9, 10)),           # ✅ 真实数据点20
        (6682531113, datetime(2023, 9, 13)),           # ✅ 真实数据点
        (6730424291, datetime(2023, 9, 29)),           # ✅ 真实数据点
        (6735663275, datetime(2023, 10, 1)),           # ✅ 真实数据点
        (6744518680, datetime(2023, 10, 4)),           # ✅ 真实数据点22
        (6837664773, datetime(2023, 10, 31)),          # ✅ 真实数据点
        (6866965606, datetime(2023, 11, 4)),           # ✅ 真实数据点
        (6909981199, datetime(2023, 11, 22)),          # ✅ 真实数据点
        (6922417356, datetime(2023, 11, 27)),          # ✅ 真实数据点
        (6955835113, datetime(2023, 11, 28)),          # ✅ 真实数据点
        (7012919391, datetime(2023, 11, 28)),          # ✅ 真实数据点
        (7389983013, datetime(2023, 11, 28)),          # ✅ 真实数据点16
        (7759732696, datetime(2023, 11, 28)),          # ✅ 真实数据点3
        (8085405606, datetime(2023, 11, 28)),          # ✅ 真实数据点21
        (8144601656, datetime(2023, 11, 28)),          # ✅ 真实数据点24
        (8157605095, datetime(2023, 11, 28)),          # ✅ 真实数据点
        (8234513817, datetime(2023, 11, 28)),          # ✅ 真实数据点
        (820674839, datetime(2024, 9, 2)),             # 2024年秋
        (9000000000, datetime(2024, 12, 1)),           # 预估高ID
    ]
    
    # 按ID排序确保正确的插值
    known_points.sort(key=lambda x: x[0])
    
    # 线性插值估算
    for i in range(len(known_points) - 1):
        id1, date1 = known_points[i]
        id2, date2 = known_points[i + 1]
        
        if id1 <= user_id <= id2:
            # 线性插值计算
            ratio = (user_id - id1) / (id2 - id1)
            time_diff = date2 - date1
            estimated_date = date1 + timedelta(seconds=time_diff.total_seconds() * ratio)
            return estimated_date
    
    # 处理边界情况
    if user_id < known_points[0][0]:
        # ID太小，返回Telegram启动时间
        return datetime(2013, 8, 14)
    else:
        # 超出范围，根据趋势估算
        # 使用最后两个点的斜率推断
        id1, date1 = known_points[-2]
        id2, date2 = known_points[-1]
        
        # 计算每个ID对应的时间增长率
        id_diff = id2 - id1
        time_diff = (date2 - date1).total_seconds()
        rate = time_diff / id_diff  # 每个ID对应的秒数
        
        # 基于趋势推算
        id_beyond = user_id - id2
        estimated_seconds = rate * id_beyond
        estimated_date = date2 + timedelta(seconds=estimated_seconds)
        
        # 限制在合理范围内
        max_date = datetime.now() + timedelta(days=30)
        if estimated_date > max_date:
            estimated_date = max_date
            
        return estimated_date


def determine_level_by_date(creation_date):
    """根据注册日期确定用户级别"""
    from datetime import datetime
    
    now = datetime.now()
    years = (now - creation_date).days / 365.25
    
    if years >= 10:
        return "十年老逼登"
    elif years >= 7:
        return "七年老兵"
    elif years >= 5:
        return "五年老兵"
    elif years >= 3:
        return "老兵"
    elif years >= 1:
        return "不如老兵"
    else:
        return "新兵蛋子"


async def when_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    查询用户的详细信息（基于ID估算注册日期）
    支持: /when 123456789 或 /when @username 或回复消息使用 /when
    """
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if not message or not chat or not user:
        return

    # 立即删除用户命令（与其他命令保持一致）
    await delete_user_command(context, chat.id, message.message_id)

    reply_text = "请稍等，正在查询用户信息..."
    sent_message = await send_search_result(context, chat.id, reply_text)

    try:
        target_user = None
        target_user_id = None
        
        # 获取用户缓存管理器
        user_cache_manager = context.bot_data.get("user_cache_manager")
        
        # 方法1: 检查是否有回复的消息
        if message.reply_to_message and message.reply_to_message.from_user:
            target_user = message.reply_to_message.from_user
            target_user_id = target_user.id
            
        # 方法2: 检查是否有参数
        elif context.args:
            param = context.args[0].strip()
            
            # 处理数字ID
            if param.isdigit():
                target_user_id = int(param)
                try:
                    # 尝试通过ID获取用户信息（通常会失败，但不影响功能）
                    target_user = await context.bot.get_chat(target_user_id)
                except Exception:
                    # 获取失败很正常，我们仍然可以基于ID估算注册日期
                    pass
            # 处理@用户名
            elif param.startswith("@"):
                username = param[1:]  # 去掉@符号
                if user_cache_manager:
                    cached_user = await user_cache_manager.get_user_by_username(username)
                    if cached_user:
                        target_user_id = cached_user.get("user_id")
                        # 从缓存中构建用户对象信息
                        target_user = CachedUser(cached_user)
                    else:
                        await context.bot.edit_message_text(
                            chat_id=chat.id,
                            message_id=sent_message.message_id,
                            text=f"❌ 缓存中未找到用户 @{username}\n\n"
                                 "💡 *可能原因*:\n"
                                 "• 用户未在监控群组中发过消息\n"
                                 "• 用户名拼写错误\n"
                                 "• 用户缓存中暂无此用户信息\n\n"
                                 "✅ *建议*:\n"
                                 "• 让用户在群内发一条消息后再试\n"
                                 "• 使用数字ID查询: `/when 123456789`\n"
                                 "• 回复用户消息后使用 `/when`",
                            parse_mode="Markdown"
                        )
                        # 调度删除机器人回复消息
                        from utils.message_manager import _schedule_deletion
                        await _schedule_deletion(context, chat.id, sent_message.message_id, 180)
                        return
                else:
                    await context.bot.edit_message_text(
                        chat_id=chat.id,
                        message_id=sent_message.message_id,
                        text="❌ 用户缓存管理器未启用\n\n"
                             "无法使用用户名查询功能，请使用数字ID查询",
                        parse_mode="Markdown"
                    )
                    # 调度删除机器人回复消息
                    from utils.message_manager import _schedule_deletion
                    await _schedule_deletion(context, chat.id, sent_message.message_id, 180)
                    return
            # 处理纯用户名（不带@）
            elif not param.isdigit() and param.isalnum():
                if user_cache_manager:
                    cached_user = await user_cache_manager.get_user_by_username(param)
                    if cached_user:
                        target_user_id = cached_user.get("user_id")
                        # 从缓存中构建用户对象信息
                        target_user = CachedUser(cached_user)
                    else:
                        await context.bot.edit_message_text(
                            chat_id=chat.id,
                            message_id=sent_message.message_id,
                            text=f"❌ 缓存中未找到用户 {param}\n\n"
                                 "💡 *提示*: 用户名查询支持以下格式:\n"
                                 "• `/when @username`\n"
                                 "• `/when username`\n"
                                 "• `/when 123456789` (数字ID)\n\n"
                                 "如果用户名查询失败，建议使用数字ID查询",
                            parse_mode="Markdown"
                        )
                        # 调度删除机器人回复消息
                        from utils.message_manager import _schedule_deletion
                        await _schedule_deletion(context, chat.id, sent_message.message_id, 180)
                        return
                else:
                    await context.bot.edit_message_text(
                        chat_id=chat.id,
                        message_id=sent_message.message_id,
                        text="❌ 用户缓存管理器未启用\n\n"
                             "无法使用用户名查询功能，请使用数字ID查询",
                        parse_mode="Markdown"
                    )
                    # 调度删除机器人回复消息
                    from utils.message_manager import _schedule_deletion
                    await _schedule_deletion(context, chat.id, sent_message.message_id, 180)
                    return
            else:
                await context.bot.edit_message_text(
                    chat_id=chat.id,
                    message_id=sent_message.message_id,
                    text="❌ 不支持的查询格式\n\n"
                         "✅ *支持的查询方式*:\n"
                         "• 回复某个用户的消息后使用 `/when`\n"
                         "• 使用数字ID: `/when 123456789`\n"
                         "• 使用用户名: `/when @username` 或 `/when username`\n\n"
                         "💡 *获取用户ID方法*:\n"
                         "• 让用户私聊机器人发送 `/id`\n"
                         "• 回复用户消息后发送 `/id`",
                    parse_mode="Markdown"
                )
                # 调度删除机器人回复消息
                from utils.message_manager import _schedule_deletion
                await _schedule_deletion(context, chat.id, sent_message.message_id, 180)
                return

        # 如果没有获取到任何用户信息
        if not target_user_id:
            await context.bot.edit_message_text(
                chat_id=chat.id,
                message_id=sent_message.message_id,
                text="请使用以下方式查询用户信息：\n"
                     "• 回复某个用户的消息后使用 `/when`\n"
                     "• 使用数字ID: `/when 123456789`\n"
                     "• 使用用户名: `/when @username` 或 `/when username`\n\n"
                     "💡 如需获取用户ID，可使用 `/id` 命令"
            )
            # 调度删除机器人回复消息
            from utils.message_manager import _schedule_deletion
            await _schedule_deletion(context, chat.id, sent_message.message_id, 180)
            return

        # 获取用户信息（如果有的话）
        if target_user:
            username = target_user.username or "无法获取"
            first_name = getattr(target_user, 'first_name', '') or ""
            last_name = getattr(target_user, 'last_name', '') or ""
            full_name = f"{first_name} {last_name}".strip() or "无法获取"
            info_note = ""
        else:
            # 只有ID的情况
            username = "无法获取"
            full_name = "无法获取"
            info_note = "\n⚠️ *说明*: 由于用户隐私设置或非Premium会员限制，无法通过ID获取用户名和昵称信息。只有Premium会员或与机器人有过交互的用户才能显示详细信息。"

        # 转义Markdown特殊字符
        safe_username = escape_markdown(username)
        safe_full_name = escape_markdown(full_name)

        # 估算注册日期
        estimated_date = estimate_account_creation_date(target_user_id)
        formatted_date = estimated_date.strftime("%Y年%m月%d日")
        
        # 计算账号年龄
        from datetime import datetime
        now = datetime.now()
        
        # 计算年月差
        years = now.year - estimated_date.year
        months = now.month - estimated_date.month
        
        # 如果当前日期小于注册日期，月份需要减1
        if now.day < estimated_date.day:
            months -= 1
        
        # 如果月份为负，从年份借位
        if months < 0:
            years -= 1
            months += 12
        
        # 格式化年龄显示
        if years > 0:
            age_str = f"{years}年{months}月"
        else:
            age_str = f"{months}月"

        # 确定级别
        level = determine_level_by_date(estimated_date)

        # 构建结果 - 根据是否能获取到用户信息调整显示格式
        if target_user and username != "无法获取":
            # 能获取到用户信息的完整显示
            result_text = (
                f"🔍 *用户信息查询*\n\n"
                f"🏷️ *昵称*：{safe_full_name}\n"
                f"📛 *用户名*：@{safe_username}\n"
                f"👤 *用户ID*: `{target_user_id}`\n"
                f"📅 *估算注册日期*：{formatted_date}\n"
                f"⏰ *账号年龄*：{age_str}\n"
                f"🏆 *级别*：{level}\n\n"
                f"⚠️ *注意*: 注册日期为基于用户ID的估算值，仅供参考"
            )
        else:
            # 无法获取用户信息的简化显示
            result_text = (
                f"🔍 *用户信息查询*\n\n"
                f"👤 *用户ID*: `{target_user_id}`\n"
                f"📅 *估算注册日期*：{formatted_date}\n"
                f"⏰ *账号年龄*：{age_str}\n"
                f"🏆 *级别*：{level}"
                f"{info_note}\n\n"
                f"⚠️ *注意*: 注册日期为基于用户ID的估算值，仅供参考"
            )

        await context.bot.edit_message_text(
            chat_id=chat.id,
            message_id=sent_message.message_id,
            text=result_text,
            parse_mode="Markdown"
        )

        # 调度删除机器人回复消息
        from utils.message_manager import _schedule_deletion
        await _schedule_deletion(context, chat.id, sent_message.message_id, 180)  # 3分钟后删除结果

    except Exception as e:
        await context.bot.edit_message_text(
            chat_id=chat.id,
            message_id=sent_message.message_id,
            text=f"查询失败: {str(e)}"
        )
        # 调度删除错误消息
        from utils.message_manager import _schedule_deletion
        await _schedule_deletion(context, chat.id, sent_message.message_id, 5)  # 5秒后删除错误


async def cache_debug_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    查看用户缓存状态和内容（调试用）
    支持: /cache 或 /cache username 或 /cache 123456789
    """
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if not message or not chat or not user:
        return

    # 立即删除用户命令
    await delete_user_command(context, chat.id, message.message_id)

    reply_text = "正在查询缓存信息..."
    sent_message = await send_search_result(context, chat.id, reply_text)

    try:
        # 获取用户缓存管理器
        user_cache_manager = context.bot_data.get("user_cache_manager")
        
        if not user_cache_manager:
            await context.bot.edit_message_text(
                chat_id=chat.id,
                message_id=sent_message.message_id,
                text="❌ 用户缓存管理器未启用"
            )
            return

        # 如果有参数，查询特定用户
        if context.args:
            param = context.args[0].strip()
            result_text = f"🔍 *缓存查询结果*\n\n"
            
            if param.isdigit():
                # 通过ID查询
                user_id = int(param)
                cached_user = await user_cache_manager.get_user_by_id(user_id) if hasattr(user_cache_manager, 'get_user_by_id') else None
                
                if cached_user:
                    username = cached_user.get("username", "无")
                    first_name = cached_user.get("first_name", "")
                    last_name = cached_user.get("last_name", "")
                    full_name = f"{first_name} {last_name}".strip() or "无"
                    
                    result_text += f"👤 *用户ID*: `{user_id}`\n"
                    result_text += f"📛 *用户名*: {username}\n"
                    result_text += f"🏷️ *昵称*: {escape_markdown(full_name)}\n"
                    result_text += f"✅ *缓存状态*: 已缓存"
                else:
                    result_text += f"👤 *用户ID*: `{user_id}`\n"
                    result_text += f"❌ *缓存状态*: 未找到"
            else:
                # 通过用户名查询
                username = param.lstrip("@")  # 去掉可能的@符号
                cached_user = await user_cache_manager.get_user_by_username(username)
                
                if cached_user:
                    user_id = cached_user.get("user_id")
                    first_name = cached_user.get("first_name", "")
                    last_name = cached_user.get("last_name", "")
                    full_name = f"{first_name} {last_name}".strip() or "无"
                    
                    result_text += f"📛 *用户名*: @{username}\n"
                    result_text += f"👤 *用户ID*: `{user_id}`\n"
                    result_text += f"🏷️ *昵称*: {escape_markdown(full_name)}\n"
                    result_text += f"✅ *缓存状态*: 已缓存"
                else:
                    result_text += f"📛 *用户名*: @{username}\n"
                    result_text += f"❌ *缓存状态*: 未找到"
        else:
            # 显示缓存概览和配置信息
            try:
                result_text = f"📊 *用户缓存概览*\n\n"
                
                # 检查缓存管理器类型
                cache_type = type(user_cache_manager).__name__
                result_text += f"• *缓存类型*: {cache_type}\n"
                
                # 检查连接状态
                if hasattr(user_cache_manager, '_connected'):
                    connection_status = "已连接" if user_cache_manager._connected else "未连接"
                    result_text += f"• *连接状态*: {connection_status}\n"
                
                # 尝试获取缓存统计信息
                if hasattr(user_cache_manager, 'get_cursor'):
                    try:
                        async with user_cache_manager.get_cursor() as cursor:
                            # 优化：使用一个查询获取多个统计信息，并处理空值
                            await cursor.execute("""
                                SELECT 
                                    COUNT(*) as total_users,
                                    SUM(CASE WHEN username IS NOT NULL AND username != '' THEN 1 ELSE 0 END) as with_username
                                FROM users
                            """)
                            stats_result = await cursor.fetchone()
                            
                            if stats_result:
                                total_users = stats_result['total_users'] or 0
                                with_username = stats_result['with_username'] or 0
                                
                                result_text += f"• *总用户数*: {total_users}\n"
                                result_text += f"• *有用户名用户*: {with_username}\n"
                                result_text += f"• *无用户名用户*: {max(0, total_users - with_username)}\n"
                            else:
                                result_text += f"• *总用户数*: 0\n"
                                result_text += f"• *有用户名用户*: 0\n"
                                result_text += f"• *无用户名用户*: 0\n"
                            
                            # 显示最近的几个用户名（用于测试）
                            if stats_result and (stats_result['total_users'] or 0) > 0:
                                await cursor.execute("SELECT username FROM users WHERE username IS NOT NULL AND username != '' ORDER BY last_seen DESC LIMIT 5")
                                recent_users = await cursor.fetchall()
                                if recent_users:
                                    usernames = [user['username'] for user in recent_users]
                                    result_text += f"• *最近用户名*: {', '.join(usernames)}\n"
                                else:
                                    result_text += f"• *最近用户名*: 暂无有用户名的用户\n"
                            else:
                                result_text += f"• *最近用户名*: 缓存为空\n"
                    except Exception as db_e:
                        result_text += f"• *数据库查询错误*: {str(db_e)}\n"
                else:
                    result_text += "• *状态*: 缓存管理器已启用\n"
                    result_text += "• *详情*: 无法获取详细统计信息\n"
                
                # 显示配置信息
                try:
                    from utils.config_manager import get_config
                    config = get_config()
                    result_text += f"\n⚙️ *缓存配置*:\n"
                    result_text += f"• *启用状态*: {'是' if config.enable_user_cache else '否'}\n"
                    if hasattr(config, 'user_cache_group_ids') and config.user_cache_group_ids:
                        result_text += f"• *监听群组*: {len(config.user_cache_group_ids)} 个\n"
                        result_text += f"• *群组ID*: {config.user_cache_group_ids}\n"
                    else:
                        result_text += f"• *监听群组*: 未配置 ❌\n"
                except Exception as config_e:
                    result_text += f"\n⚙️ *配置错误*: {str(config_e)}\n"
                
                result_text += f"\n💡 *使用方法*:\n"
                result_text += f"• `/cache username` - 查询特定用户名\n"
                result_text += f"• `/cache @username` - 查询特定用户名\n"
                result_text += f"• `/cache 123456789` - 查询特定ID\n"
                
                result_text += f"\n📝 *缓存说明*:\n"
                result_text += f"• 只有在配置的监听群组中发过消息的用户才会被缓存\n"
                result_text += f"• 如果监听群组未配置，缓存功能将不工作\n"
                
            except Exception as e:
                result_text = f"📊 *用户缓存概览*\n\n"
                result_text += f"• *状态*: 缓存管理器已启用\n"
                result_text += f"• *错误*: 无法获取详细信息 ({str(e)})\n"

        await context.bot.edit_message_text(
            chat_id=chat.id,
            message_id=sent_message.message_id,
            text=result_text,
            parse_mode="Markdown"
        )

        # 调度删除机器人回复消息
        from utils.message_manager import _schedule_deletion
        await _schedule_deletion(context, chat.id, sent_message.message_id, 180)

    except Exception as e:
        await context.bot.edit_message_text(
            chat_id=chat.id,
            message_id=sent_message.message_id,
            text=f"查询缓存失败: {str(e)}"
        )
        # 调度删除错误消息
        from utils.message_manager import _schedule_deletion
        await _schedule_deletion(context, chat.id, sent_message.message_id, 5)


async def clean_id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    清理用户ID缓存命令（管理员专用）
    支持: /cleanid 或 /cleanid 30 (清理30天前的数据)
    """
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if not message or not chat or not user:
        return

    # 立即删除用户命令
    await delete_user_command(context, chat.id, message.message_id)

    reply_text = "正在执行缓存清理..."
    sent_message = await send_search_result(context, chat.id, reply_text)

    try:
        # 获取用户缓存管理器
        user_cache_manager = context.bot_data.get("user_cache_manager")
        
        if not user_cache_manager:
            await context.bot.edit_message_text(
                chat_id=chat.id,
                message_id=sent_message.message_id,
                text="❌ 用户缓存管理器未启用"
            )
            return

        if not hasattr(user_cache_manager, 'get_cursor'):
            await context.bot.edit_message_text(
                chat_id=chat.id,
                message_id=sent_message.message_id,
                text="❌ 缓存管理器不支持清理操作"
            )
            return

        # 解析参数
        days_ago = None
        if context.args:
            try:
                days_ago = int(context.args[0])
                if days_ago <= 0:
                    await context.bot.edit_message_text(
                        chat_id=chat.id,
                        message_id=sent_message.message_id,
                        text="❌ 天数必须为正整数\n\n"
                             "用法示例：\n"
                             "• `/cleanid` - 清理所有ID缓存\n"
                             "• `/cleanid 30` - 清理30天前的数据"
                    )
                    return
            except ValueError:
                await context.bot.edit_message_text(
                    chat_id=chat.id,
                    message_id=sent_message.message_id,
                    text="❌ 参数格式错误，请输入数字\n\n"
                         "用法示例：\n"
                         "• `/cleanid` - 清理所有ID缓存\n"
                         "• `/cleanid 30` - 清理30天前的数据"
                )
                return

        # 执行清理操作
        async with user_cache_manager.get_cursor() as cursor:
            # 先获取清理前的统计
            await cursor.execute("SELECT COUNT(*) as total FROM users")
            before_result = await cursor.fetchone()
            before_count = (before_result['total'] if before_result else 0) or 0
            
            if days_ago:
                # 按时间清理
                await cursor.execute(
                    "SELECT COUNT(*) as old_count FROM users WHERE last_seen < DATE_SUB(NOW(), INTERVAL %s DAY)",
                    (days_ago,)
                )
                old_result = await cursor.fetchone()
                old_count = (old_result['old_count'] if old_result else 0) or 0
                
                if old_count == 0:
                    await context.bot.edit_message_text(
                        chat_id=chat.id,
                        message_id=sent_message.message_id,
                        text=f"ℹ️ 没有找到 {days_ago} 天前的数据需要清理\n\n"
                             f"当前缓存用户数：{before_count}"
                    )
                    return
                
                # 执行按时间清理
                await cursor.execute(
                    "DELETE FROM users WHERE last_seen < DATE_SUB(NOW(), INTERVAL %s DAY)",
                    (days_ago,)
                )
                affected_rows = cursor.rowcount or 0
                remaining_count = max(0, before_count - affected_rows)
                
                result_text = (
                    f"✅ **ID缓存清理完成**\n\n"
                    f"📊 **清理结果**：\n"
                    f"• 清理前：{before_count} 个用户\n"
                    f"• 已清理：{affected_rows} 个用户（{days_ago}天前）\n"
                    f"• 剩余：{remaining_count} 个用户\n\n"
                    f"🎯 **操作类型**：按时间清理"
                )
            else:
                # 全部清理
                if before_count == 0:
                    await context.bot.edit_message_text(
                        chat_id=chat.id,
                        message_id=sent_message.message_id,
                        text="ℹ️ 用户缓存已经是空的，无需清理"
                    )
                    return
                
                # 执行全部清理
                await cursor.execute("DELETE FROM users")
                affected_rows = cursor.rowcount or 0
                
                result_text = (
                    f"✅ **ID缓存清理完成**\n\n"
                    f"📊 **清理结果**：\n"
                    f"• 清理前：{before_count} 个用户\n"
                    f"• 已清理：{affected_rows} 个用户\n"
                    f"• 剩余：0 个用户\n\n"
                    f"🎯 **操作类型**：全部清理"
                )

        await context.bot.edit_message_text(
            chat_id=chat.id,
            message_id=sent_message.message_id,
            text=result_text,
            parse_mode="Markdown"
        )

        # 调度删除结果消息
        from utils.message_manager import _schedule_deletion
        await _schedule_deletion(context, chat.id, sent_message.message_id, 60)

    except Exception as e:
        await context.bot.edit_message_text(
            chat_id=chat.id,
            message_id=sent_message.message_id,
            text=f"缓存清理失败: {str(e)}"
        )
        # 调度删除错误消息
        from utils.message_manager import _schedule_deletion
        await _schedule_deletion(context, chat.id, sent_message.message_id, 10)


# 注册命令
command_factory.register_command("id", get_id_command, permission=Permission.NONE, description="获取用户或群组的ID")
command_factory.register_command("when", when_command, permission=Permission.NONE, description="查询用户详细信息（支持数字ID、用户名或回复消息）")
command_factory.register_command("cache", cache_debug_command, permission=Permission.ADMIN, description="查看用户缓存状态（管理员专用）")
command_factory.register_command("cleanid", clean_id_command, permission=Permission.ADMIN, description="清理用户ID缓存（管理员专用）")

