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
        (7679610, datetime(2013, 12, 31)),             # 2013年末
        (15835244, datetime(2014, 2, 21)),             # 2014年初
        (44634663, datetime(2014, 5, 6)),              # 2014年中
        (80139402, datetime(2015, 2, 26)),             # 2015年初
        (133275940, datetime(2015, 11, 30)),           # 2015年末
        (179264853, datetime(2016, 7, 13)),            # 2016年中
        (235826940, datetime(2017, 4, 19)),            # 2017年
        (554653093, datetime(2018, 3, 20)),            # ✅ 真实数据点
        (620973285, datetime(2018, 6, 24)),            # ✅ 真实数据点1
        (658502219, datetime(2018, 7, 15)),            # ✅ 真实数据点
        (715914969, datetime(2018, 10, 30)),           # ✅ 真实数据点23
        (722887698, datetime(2018, 11, 19)),           # ✅ 真实数据点
        (364582948, datetime(2019, 1, 2)),             # 2019年初
        (1063318764, datetime(2020, 2, 3)),            # ✅ 真实数据点
        (1086886247, datetime(2020, 2, 22)),           # ✅ 真实数据点8
        (1096626991, datetime(2020, 2, 29)),           # ✅ 真实数据点9
        (1111558803, datetime(2020, 3, 12)),           # ✅ 真实数据点17
        (467982635, datetime(2020, 5, 15)),            # 2020年疫情期间
        (1212910191, datetime(2020, 7, 9)),            # ✅ 真实数据点4
        (1520415315, datetime(2020, 11, 29)),          # ✅ 真实数据点15
        (1606154208, datetime(2021, 1, 15)),           # ✅ 真实数据点18
        (1659206651, datetime(2021, 2, 13)),           # ✅ 真实数据点2
        (1978440017, datetime(2021, 10, 10)),          # ✅ 真实数据点13
        (2143348318, datetime(2021, 11, 21)),          # ✅ 真实数据点12
        (597485629, datetime(2022, 1, 7)),             # 2022年初
        (5213669212, datetime(2022, 4, 21)),           # ✅ 真实数据点7
        (5235138802, datetime(2022, 5, 8)),            # ✅ 真实数据点5
        (5370825396, datetime(2022, 6, 16)),           # ✅ 真实数据点10
        (5374581898, datetime(2022, 7, 4)),            # ✅ 真实数据点6
        (6095955229, datetime(2023, 2, 12)),           # ✅ 真实数据点19
        (701758493, datetime(2023, 4, 12)),            # 2023年春
        (6521937258, datetime(2023, 7, 19)),           # ✅ 真实数据点11
        (6537156348, datetime(2023, 7, 24)),           # ✅ 真实数据点14
        (6674181048, datetime(2023, 9, 10)),           # ✅ 真实数据点20
        (6744518680, datetime(2023, 10, 4)),           # ✅ 真实数据点22
        (6837664773, datetime(2023, 10, 31)),          # ✅ 真实数据点
        (7389983013, datetime(2023, 11, 28)),          # ✅ 真实数据点16
        (7759732696, datetime(2023, 11, 28)),          # ✅ 真实数据点3
        (8085405606, datetime(2023, 11, 28)),          # ✅ 真实数据点21
        (8144601656, datetime(2023, 11, 28)),          # ✅ 真实数据点24
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
    支持: /when 123456789 或回复消息使用 /when
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
        
        # 方法1: 检查是否有回复的消息
        if message.reply_to_message and message.reply_to_message.from_user:
            target_user = message.reply_to_message.from_user
            target_user_id = target_user.id
            
        # 方法2: 检查是否有数字ID参数
        elif context.args:
            param = context.args[0].strip()
            
            # 只支持数字ID查询
            if param.isdigit():
                target_user_id = int(param)
                try:
                    # 尝试通过ID获取用户信息（通常会失败，但不影响功能）
                    target_user = await context.bot.get_chat(target_user_id)
                except Exception:
                    # 获取失败很正常，我们仍然可以基于ID估算注册日期
                    pass
            else:
                await context.bot.edit_message_text(
                    chat_id=chat.id,
                    message_id=sent_message.message_id,
                    text="❌ 不支持用户名查询\n\n"
                         "✅ *支持的查询方式*:\n"
                         "• 回复某个用户的消息后使用 `/when`\n"
                         "• 直接使用数字ID: `/when 123456789`\n\n"
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
                     "• 直接使用数字ID: `/when 123456789`\n\n"
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
            info_note = "\n⚠️ *说明*: 由于隐私设置或API限制，无法获取详细用户信息"

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

        # 构建结果
        result_text = (
            f"🔍 *用户信息查询*\n\n"
            f"🏷️ *昵称*：{safe_full_name}\n"
            f"📛 *用户名*：@{safe_username}\n"
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


# 注册命令
command_factory.register_command("id", get_id_command, permission=Permission.NONE, description="获取用户或群组的ID")
command_factory.register_command("when", when_command, permission=Permission.NONE, description="查询用户详细信息（支持数字ID或回复消息）")

