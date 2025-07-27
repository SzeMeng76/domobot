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
    参考最新的用户增长数据和ID分布模式 (2024-2025)
    """
    from datetime import datetime, timedelta
    
    # Telegram在2013年8月14日发布
    telegram_launch = datetime(2013, 8, 14)
    
    # 基于最新的用户增长里程碑和观察到的ID分布进行插值
    # 数据来源：2024-2025年的用户增长统计和ID模式分析
    known_points = [
        (1, datetime(2013, 8, 14)),          # Telegram创始人
        (777000, datetime(2015, 6, 1)),      # 早期官方bot时期
        (50000000, datetime(2015, 12, 1)),   # 5000万用户里程碑
        (100000000, datetime(2016, 2, 1)),   # 1亿用户里程碑 (2016年2月)
        (200000000, datetime(2017, 8, 1)),   # 2亿用户里程碑
        (300000000, datetime(2018, 8, 1)),   # 3亿用户里程碑
        (400000000, datetime(2020, 4, 1)),   # 4亿用户里程碑 (疫情期间快速增长)
        (500000000, datetime(2021, 1, 1)),   # 5亿用户里程碑
        (700000000, datetime(2022, 4, 1)),   # 7亿用户里程碑
        (800000000, datetime(2023, 7, 1)),   # 8亿用户里程碑
        (900000000, datetime(2024, 3, 1)),   # 9亿用户里程碑
        (950000000, datetime(2024, 7, 1)),   # 9.5亿用户里程碑 (2024年7月)
        (1000000000, datetime(2024, 12, 1)), # 10亿用户里程碑 (预计2024年末)
        (1500000000, datetime(2025, 6, 1)),  # 15亿用户预测
        (2000000000, datetime(2026, 1, 1)),  # 20亿用户预测
        (5000000000, datetime(2027, 1, 1)),  # 当前ID上限估算
    ]
    
    # 线性插值估算
    for i in range(len(known_points) - 1):
        id1, date1 = known_points[i]
        id2, date2 = known_points[i + 1]
        
        if id1 <= user_id <= id2:
            # 线性插值计算
            ratio = (user_id - id1) / (id2 - id1)
            time_diff = date2 - date1
            estimated_date = date1 + timedelta(days=time_diff.days * ratio)
            return estimated_date
    
    # 如果ID超出范围，返回最近的估算
    if user_id > known_points[-1][0]:
        # 对于超高ID，假设是最近注册的
        return datetime.now() - timedelta(days=30)
    else:
        return telegram_launch


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

    reply_text = "请稍等，正在查询用户信息..."
    sent_message = await context.bot.send_message(chat_id=chat.id, text=reply_text)

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

        # 估算注册日期
        estimated_date = estimate_account_creation_date(target_user_id)
        formatted_date = estimated_date.strftime("%Y年%m月%d日")
        
        # 计算账号年龄
        from datetime import datetime
        now = datetime.now()
        age_days = (now - estimated_date).days
        years = age_days // 365
        months = (age_days % 365) // 30
        
        if years > 0:
            age_str = f"{years}年{months}月"
        else:
            age_str = f"{months}月"

        # 确定级别
        level = determine_level_by_date(estimated_date)

        # 构建结果
        result_text = (
            f"🔍 *用户信息查询*\n\n"
            f"🏷️ *昵称*：{full_name}\n"
            f"📛 *用户名*：@{username}\n"
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

    except Exception as e:
        await context.bot.edit_message_text(
            chat_id=chat.id,
            message_id=sent_message.message_id,
            text=f"查询失败: {str(e)}"
        )

    await delete_user_command(context, chat.id, message.message_id)


# 注册命令
command_factory.register_command("id", get_id_command, permission=Permission.USER, description="获取用户或群组的ID")
command_factory.register_command("when", when_command, permission=Permission.USER, description="查询用户详细信息（支持数字ID或回复消息）")
