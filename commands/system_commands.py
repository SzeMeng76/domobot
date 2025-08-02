# type: ignore
import re
import asyncio
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes
import httpx
import json

from utils.command_factory import command_factory
from utils.formatter import foldable_text_with_markdown_v2
from utils.message_manager import delete_user_command, send_search_result
from utils.permissions import Permission


# Telegraph 相关配置和函数
TELEGRAPH_API_URL = "https://api.telegra.ph"
TELEGRAM_MESSAGE_LIMIT = 4096  # Telegram消息长度限制


async def create_telegraph_page(title, content):
    """
    创建Telegraph页面
    """
    try:
        async with httpx.AsyncClient() as client:
            # 创建Telegraph账户（每次都创建新的，避免token管理问题）
            account_data = {
                "short_name": "MengBot",
                "author_name": "MengBot",
                "author_url": "https://t.me/mengpricebot"
            }
            
            response = await client.post(f"{TELEGRAPH_API_URL}/createAccount", data=account_data)
            if response.status_code != 200:
                return None
                
            account_info = response.json()
            if not account_info.get("ok"):
                return None
                
            access_token = account_info["result"]["access_token"]
            
            # 创建页面内容
            page_content = [
                {
                    "tag": "p",
                    "children": [content]
                }
            ]
            
            page_data = {
                "access_token": access_token,
                "title": title,
                "content": json.dumps(page_content),
                "return_content": "true"
            }
            
            response = await client.post(f"{TELEGRAPH_API_URL}/createPage", data=page_data)
            if response.status_code != 200:
                return None
                
            page_info = response.json()
            if not page_info.get("ok"):
                return None
                
            return page_info["result"]["url"]
        
    except Exception as e:
        print(f"创建Telegraph页面失败: {e}")
        return None


def format_points_for_telegraph(points):
    """
    将数据点格式化为Telegraph友好的格式
    """
    content = "已知数据点列表\n\n"
    
    # 统计信息
    total_points = len(points)
    verified_count = sum(1 for p in points if "✅" in p.get("note", ""))
    content += f"统计: 总数 {total_points} | 已验证 {verified_count} | 估算 {total_points - verified_count}\n\n"
    
    # 数据点列表
    for i, point in enumerate(points, 1):
        user_id = point["user_id"]
        date = point["date"]
        note = point.get("note", "无备注")
        content += f"{i:>3}. {user_id:<11} {date} {note}\n"
    
    content += f"\n\n管理命令:\n"
    content += f"• /addpoint <id> <date> [note] - 添加数据点\n"
    content += f"• /removepoint <id> - 删除数据点"
    
    return content


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
    """转义Markdown特殊字符，安全处理Unicode字符"""
    if not text:
        return ""
    
    # 确保输入是字符串
    text = str(text)
    
    # Telegram Markdown特殊字符
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    
    return text


def escape_markdown_v2(text):
    """转义MarkdownV2特殊字符，安全处理Unicode字符"""
    if not text:
        return ""
    
    # 确保输入是字符串
    text = str(text)
    
    # MarkdownV2需要转义的字符
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!', '\\']
    
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    
    return text


def safe_format_username(username):
    """安全格式化用户名，避免Markdown解析错误"""
    if not username or username == "无法获取":
        return "无法获取"
    
    # 移除或替换可能引起问题的字符
    safe_username = str(username)
    
    # 如果包含非ASCII字符，使用代码块格式
    try:
        safe_username.encode('ascii')
        # 纯ASCII，可以安全转义
        return escape_markdown(safe_username)
    except UnicodeEncodeError:
        # 包含非ASCII字符，使用代码块避免解析问题
        return f"`{username}`"


async def send_message_with_fallback(context, chat_id, text, parse_mode="Markdown", fallback_text=None):
    """
    发送消息，如果失败则使用简化的纯文本fallback
    增强了对Unicode字符的处理
    """
    from utils.message_manager import send_search_result
    
    # 第一次尝试：发送原始消息
    try:
        sent_message = await send_search_result(context, chat_id, text, parse_mode=parse_mode)
        if sent_message:
            return sent_message
    except Exception as e:
        logger.debug(f"第一次发送失败: {e}")
    
    # 第二次尝试：如果是MarkdownV2，改用Markdown
    if parse_mode == "MarkdownV2":
        try:
            # 简化MarkdownV2为普通Markdown
            simplified_text = text.replace('\\', '')  # 移除转义符
            sent_message = await send_search_result(context, chat_id, simplified_text, parse_mode="Markdown")
            if sent_message:
                return sent_message
        except Exception as e:
            logger.debug(f"Markdown降级发送失败: {e}")
    
    # 第三次尝试：使用fallback文本或创建简化版本
    if not fallback_text:
        # 移除所有Markdown格式，创建简化版本
        fallback_text = text
        # 移除Markdown格式字符
        import re
        fallback_text = re.sub(r'\*\*(.*?)\*\*', r'\1', fallback_text)  # 移除粗体
        fallback_text = re.sub(r'\*(.*?)\*', r'\1', fallback_text)      # 移除斜体
        fallback_text = re.sub(r'`(.*?)`', r'\1', fallback_text)        # 移除代码格式
        fallback_text = re.sub(r'\\(.)', r'\1', fallback_text)          # 移除转义字符
    
    # 第四次尝试：发送纯文本版本
    try:
        fallback_message = await context.bot.send_message(
            chat_id=chat_id,
            text=fallback_text
        )
        return fallback_message
    except Exception as e:
        logger.debug(f"纯文本发送失败: {e}")
        
        # 最后的fallback：发送通用错误消息
        try:
            error_message = await context.bot.send_message(
                chat_id=chat_id,
                text="❌ 消息发送失败，用户名包含特殊字符"
            )
            return error_message
        except Exception:
            logger.error("所有发送尝试均失败")
            return None


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


def get_user_level_by_years(years):
    """根据账号年龄确定Telegram用户级别 - 价格猎人主题"""
    if years >= 10:
        return "🏆 传奇价格大师"
    elif years >= 7:
        return "💎 钻石级猎手"
    elif years >= 5:
        return "🥇 黄金级探员"
    elif years >= 3:
        return "🥈 白银级侦探"
    elif years >= 1:
        return "🥉 青铜级新手"
    else:
        return "🔰 见习价格猎人"


def estimate_account_creation_date(user_id):
    """
    基于用户ID估算Telegram账号创建日期
    使用从JSON文件加载的真实用户数据校准的算法
    """
    from datetime import datetime, timedelta
    from utils.known_points_loader import load_known_points
    
    # 从JSON文件加载已知数据点
    known_points = load_known_points()
    
    # 线性插值估算
    for i in range(len(known_points) - 1):
        id1, date1 = known_points[i]
        id2, date2 = known_points[i + 1]
        
        if id1 <= user_id <= id2:
            # 调试输出 - 保留这个很重要，能发现排序问题
            print(f"🔍 调试: ID {user_id} 在区间 [{id1}, {id2}] 内")
            print(f"🔍 调试: 日期区间 [{date1}, {date2}]")
            
            # 检查日期顺序是否正确
            if date1 > date2:
                print(f"⚠️ 警告: 日期顺序错误! {date1} > {date2}")
            
            # 线性插值计算
            ratio = (user_id - id1) / (id2 - id1)
            time_diff = date2 - date1
            estimated_date = date1 + timedelta(seconds=time_diff.total_seconds() * ratio)
            
            print(f"🔍 调试: 插值比例 {ratio:.4f}, 估算日期 {estimated_date}")
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


def get_user_level_by_date(creation_date):
    """根据注册日期确定Telegram用户级别（推荐使用）"""
    from datetime import datetime
    
    now = datetime.now()
    years = (now - creation_date).days / 365.25
    
    return get_user_level_by_years(years)


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
                        safe_username = safe_format_username(username)
                        try:
                            await context.bot.edit_message_text(
                                chat_id=chat.id,
                                message_id=sent_message.message_id,
                                text=f"❌ 缓存中未找到用户 @{safe_username}\n\n"
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
                        except Exception:
                            # 如果Markdown失败，使用纯文本
                            await context.bot.edit_message_text(
                                chat_id=chat.id,
                                message_id=sent_message.message_id,
                                text=f"❌ 缓存中未找到用户 @{username}\n\n"
                                     "建议:\n"
                                     "• 让用户在群内发一条消息后再试\n"
                                     "• 使用数字ID查询\n"
                                     "• 回复用户消息后使用 /when"
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
            elif not param.isdigit() and re.match(r'^[a-zA-Z0-9_]+$', param):
                if user_cache_manager:
                    cached_user = await user_cache_manager.get_user_by_username(param)
                    if cached_user:
                        target_user_id = cached_user.get("user_id")
                        # 从缓存中构建用户对象信息
                        target_user = CachedUser(cached_user)
                    else:
                        safe_param = safe_format_username(param)
                        try:
                            await context.bot.edit_message_text(
                                chat_id=chat.id,
                                message_id=sent_message.message_id,
                                text=f"❌ 缓存中未找到用户 {safe_param}\n\n"
                                     "💡 *提示*: 用户名查询支持以下格式:\n"
                                     "• `/when @username`\n"
                                     "• `/when username`\n"
                                     "• `/when 123456789` (数字ID)\n\n"
                                     "如果用户名查询失败，建议使用数字ID查询",
                                parse_mode="Markdown"
                            )
                        except Exception:
                            # 如果Markdown失败，使用纯文本
                            await context.bot.edit_message_text(
                                chat_id=chat.id,
                                message_id=sent_message.message_id,
                                text=f"❌ 缓存中未找到用户 {param}\n\n"
                                     "提示: 用户名查询支持以下格式:\n"
                                     "• /when @username\n"
                                     "• /when username\n"
                                     "• /when 123456789 (数字ID)\n\n"
                                     "如果用户名查询失败，建议使用数字ID查询"
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
        safe_username = safe_format_username(username)
        safe_full_name = safe_format_username(full_name)

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
        level = get_user_level_by_date(estimated_date)

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
                    result_text += f"📛 *用户名*: {safe_format_username(username)}\n"
                    result_text += f"🏷️ *昵称*: {safe_format_username(full_name)}\n"
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
                    
                    result_text += f"📛 *用户名*: @{safe_format_username(username)}\n"
                    result_text += f"👤 *用户ID*: `{user_id}`\n"
                    result_text += f"🏷️ *昵称*: {safe_format_username(full_name)}\n"
                    result_text += f"✅ *缓存状态*: 已缓存"
                else:
                    result_text += f"📛 *用户名*: @{safe_format_username(username)}\n"
                    result_text += f"❌ *缓存状态*: 未找到"
        else:
            # 显示缓存概览和配置信息
            try:
                result_text = f"📊 *用户缓存概览*\n\n"
                
                # 检查缓存管理器类型
                cache_type = type(user_cache_manager).__name__
                result_text += f"• *缓存类型*: {cache_type}\n"
                
                # 检查连接状态和连接池信息
                if hasattr(user_cache_manager, '_connected'):
                    connection_status = "已连接" if user_cache_manager._connected else "未连接"
                    result_text += f"• *连接状态*: {connection_status}\n"
                    
                    # 添加连接池监控信息
                    if user_cache_manager._connected and hasattr(user_cache_manager, 'pool'):
                        pool = user_cache_manager.pool
                        if pool:
                            result_text += f"• *连接池状态*: {pool.size}/{pool.maxsize} 连接"
                            if pool.freesize < pool.minsize:
                                result_text += " ⚠️"
                            result_text += f" (空闲: {pool.freesize})\n"
                
                # 尝试获取缓存统计信息
                if hasattr(user_cache_manager, 'get_cursor'):
                    try:
                        async with user_cache_manager.get_cursor() as cursor:
                            # 更新表统计信息确保准确性
                            await cursor.execute("ANALYZE TABLE users")
                            
                            # 优化：使用一个查询获取多个统计信息，并处理空值
                            await cursor.execute("""
                                SELECT 
                                    COUNT(*) as total_users,
                                    SUM(CASE WHEN username IS NOT NULL AND username != '' THEN 1 ELSE 0 END) as with_username
                                FROM users
                            """)
                            stats_result = await cursor.fetchone()
                            
                            # 获取用户表大小信息 - 修正查询确保获取准确大小
                            await cursor.execute("""
                                SELECT 
                                    ROUND((data_length + index_length) / 1024, 3) as size_kb,
                                    ROUND((data_length + index_length) / 1024 / 1024, 3) as size_mb,
                                    ROUND(data_length / 1024, 3) as data_kb,
                                    ROUND(index_length / 1024, 3) as index_kb,
                                    table_rows
                                FROM information_schema.tables 
                                WHERE table_schema = DATABASE()
                                AND table_name = 'users'
                            """)
                            size_result = await cursor.fetchone()
                            
                            if stats_result:
                                total_users = stats_result['total_users'] or 0
                                with_username = stats_result['with_username'] or 0
                                
                                result_text += f"• *总用户数*: {total_users}\n"
                                result_text += f"• *有用户名用户*: {with_username}\n"
                                result_text += f"• *无用户名用户*: {max(0, total_users - with_username)}\n"
                                
                                # 添加用户表大小信息 - 显示详细的大小分解
                                if size_result and size_result['size_kb']:
                                    size_kb = size_result['size_kb'] or 0
                                    size_mb = size_result['size_mb'] or 0
                                    data_kb = size_result['data_kb'] or 0
                                    index_kb = size_result['index_kb'] or 0
                                    
                                    if size_mb >= 1:
                                        result_text += f"• *用户表大小*: {size_mb} MB"
                                    else:
                                        result_text += f"• *用户表大小*: {size_kb} KB"
                                    
                                    # 添加详细分解
                                    result_text += f" (数据: {data_kb}KB + 索引: {index_kb}KB)"
                                    
                                    # 添加平均每用户数据量
                                    if total_users > 0:
                                        avg_kb_per_user = size_kb / total_users
                                        result_text += f" (平均 {avg_kb_per_user:.1f} KB/用户)\n"
                                    else:
                                        result_text += "\n"
                                    
                                    # 添加表大小告警
                                    if size_mb >= 10:
                                        result_text += f"⚠️ *告警*: 用户表已超过10MB，建议使用 `/cleanid 30` 清理旧数据\n"
                                    elif size_mb >= 5:
                                        result_text += f"💡 *提示*: 用户表接近5MB，可考虑定期清理\n"
                                        
                                    # 添加统计信息对比（用于调试）
                                    table_rows = size_result.get('table_rows', 0) or 0
                                    if table_rows != total_users:
                                        result_text += f"• *统计信息*: MySQL表统计 {table_rows}，实际计数 {total_users}\n"
                                else:
                                    result_text += f"• *用户表大小*: < 1 KB\n"
                            else:
                                result_text += f"• *总用户数*: 0\n"
                                result_text += f"• *有用户名用户*: 0\n"
                                result_text += f"• *无用户名用户*: 0\n"
                                result_text += f"• *用户表大小*: < 1 KB\n"
                            
                            # 显示最近的几个用户名（用于测试）
                            if stats_result and (stats_result['total_users'] or 0) > 0:
                                await cursor.execute("SELECT username FROM users WHERE username IS NOT NULL AND username != '' ORDER BY last_seen DESC LIMIT 5")
                                recent_users = await cursor.fetchall()
                                if recent_users:
                                    usernames = [safe_format_username(user['username']) for user in recent_users]
                                    result_text += f"• *最近用户名*: {', '.join(usernames)}\n"
                                else:
                                    result_text += f"• *最近用户名*: 暂无有用户名的用户\n"
                            else:
                                result_text += f"• *最近用户名*: 缓存为空\n"
                    except Exception as db_e:
                        result_text += f"• *数据库查询错误*: {safe_format_username(str(db_e))}\n"
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
                        result_text += f"• *监听模式*: 指定群组 ({len(config.user_cache_group_ids)} 个)\n"
                    else:
                        result_text += f"• *监听模式*: 所有群组 (已启用)\n"
                except Exception as config_e:
                    result_text += f"\n⚙️ *配置错误*: {safe_format_username(str(config_e))}\n"
                
                result_text += f"\n💡 *使用方法*:\n"
                result_text += f"• `/cache username` - 查询特定用户名\n"
                result_text += f"• `/cache @username` - 查询特定用户名\n"
                result_text += f"• `/cache 123456789` - 查询特定ID\n"
                
                result_text += f"\n📝 *缓存说明*:\n"
                result_text += f"• 机器人加入的所有群组中发消息的用户都会被缓存\n"
                result_text += f"• 可通过配置文件指定特定群组进行监听\n"
                result_text += f"• 当数据大小超过 10MB 时建议使用 `/cleanid` 清理缓存\n"
                result_text += f"• 使用 `/cleanid 30` 可清理30天前的旧数据\n"
                
            except Exception as e:
                result_text = f"📊 *用户缓存概览*\n\n"
                result_text += f"• *状态*: 缓存管理器已启用\n"
                result_text += f"• *错误*: 无法获取详细信息 ({safe_format_username(str(e))})\n"

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
            text=f"查询缓存失败: {safe_format_username(str(e))}"
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


async def add_point_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    添加已知数据点命令（管理员专用）
    使用方法: /addpoint <user_id> <date> [note]
    示例: /addpoint 123456789 2024-01-15 新验证用户
    """
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    
    if not message or not chat or not user:
        return
        
    # 立即删除用户命令
    await delete_user_command(context, chat.id, message.message_id)
    
    # 检查参数
    if not context.args or len(context.args) < 2:
        reply_text = (
            "❌ **参数不足**\n\n"
            "**使用方法:**\n"
            "`/addpoint <user_id> <date> [note]`\n\n"
            "**示例:**\n"
            "• `/addpoint 123456789 2024-01-15`\n"
            "• `/addpoint 123456789 2024-01-15 新验证用户`\n\n"
            "**说明:**\n"
            "• user_id: 用户的数字ID\n"
            "• date: 日期格式 YYYY-MM-DD\n" 
            "• note: 可选备注信息"
        )
        sent_message = await send_message_with_fallback(
            context, chat.id, reply_text, 
            parse_mode="Markdown",
            fallback_text="❌ 参数不足，请使用: /addpoint <user_id> <date> [note]"
        )
        from utils.message_manager import _schedule_deletion
        if sent_message:
            await _schedule_deletion(context, chat.id, sent_message.message_id, 30)
        return
        
    try:
        user_id_str = context.args[0]
        date_str = context.args[1]
        note = " ".join(context.args[2:]) if len(context.args) > 2 else "✅ 真实数据点"
        
        # 验证用户ID
        try:
            user_id = int(user_id_str)
        except ValueError:
            sent_message = await send_search_result(
                context, chat.id, 
                "❌ 用户ID必须是数字", 
                parse_mode="Markdown"
            )
            from utils.message_manager import _schedule_deletion
            if sent_message:
                await _schedule_deletion(context, chat.id, sent_message.message_id, 10)
            return
            
        # 验证日期格式
        try:
            from datetime import datetime
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            sent_message = await send_search_result(
                context, chat.id,
                "❌ 日期格式错误，请使用 YYYY-MM-DD 格式\n\n例如: 2024-01-15",
                parse_mode="Markdown"
            )
            from utils.message_manager import _schedule_deletion
            if sent_message:
                await _schedule_deletion(context, chat.id, sent_message.message_id, 10)
            return
            
        # 加载现有数据
        import json
        from pathlib import Path
        from utils.known_points_loader import get_known_points_loader
        
        loader = get_known_points_loader()
        data_file = Path("data/known_points.json")
        
        if data_file.exists():
            with open(data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        else:
            data = {
                "version": "1.0",
                "description": "基于真实SmartUtilBot查询结果的已知数据点映射表",
                "last_updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "known_points": []
            }
            
        points = data.get("known_points", [])
        
        # 检查是否已存在
        for point in points:
            if point["user_id"] == user_id:
                sent_message = await send_search_result(
                    context, chat.id,
                    f"❌ 用户ID `{user_id}` 已存在\n\n"
                    f"现有记录: {point['date']} - {point.get('note', '无备注')}",
                    parse_mode="Markdown"
                )
                from utils.message_manager import _schedule_deletion
                if sent_message:
                    await _schedule_deletion(context, chat.id, sent_message.message_id, 15)
                return
                
        # 添加新数据点
        new_point = {
            "user_id": user_id,
            "date": date_str,
            "note": note
        }
        
        points.append(new_point)
        data["known_points"] = points
        data["last_updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
        
        # 确保目录存在
        data_file.parent.mkdir(exist_ok=True)
        
        # 保存数据
        with open(data_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
            
        # 强制重新加载数据
        loader.reload()
        
        reply_text = (
            f"✅ **数据点添加成功**\n\n"
            f"👤 **用户ID**: `{user_id}`\n"
            f"📅 **日期**: {date_str}\n"
            f"📝 **备注**: {escape_markdown(note)}\n\n"
            f"📊 **当前总数据点**: {len(points)}"
        )
        
        sent_message = await send_search_result(context, chat.id, reply_text, parse_mode="Markdown")
        from utils.message_manager import _schedule_deletion
        if sent_message:
            await _schedule_deletion(context, chat.id, sent_message.message_id, 60)
        
    except Exception as e:
        sent_message = await send_search_result(
            context, chat.id,
            f"❌ 添加数据点失败: {str(e)}",
            parse_mode="Markdown"
        )
        from utils.message_manager import _schedule_deletion
        if sent_message:
            await _schedule_deletion(context, chat.id, sent_message.message_id, 10)


async def remove_point_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    删除已知数据点命令（管理员专用）
    使用方法: /removepoint <user_id>
    """
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    
    if not message or not chat or not user:
        return
        
    # 立即删除用户命令
    await delete_user_command(context, chat.id, message.message_id)
    
    # 检查参数
    if not context.args:
        reply_text = (
            "❌ **参数不足**\n\n"
            "**使用方法:**\n"
            "`/removepoint <user_id>`\n\n"
            "**示例:**\n"
            "`/removepoint 123456789`"
        )
        sent_message = await send_search_result(context, chat.id, reply_text, parse_mode="Markdown")
        from utils.message_manager import _schedule_deletion
        if sent_message:
            await _schedule_deletion(context, chat.id, sent_message.message_id, 20)
        return
        
    try:
        user_id_str = context.args[0]
        
        # 验证用户ID
        try:
            user_id = int(user_id_str)
        except ValueError:
            sent_message = await send_search_result(
                context, chat.id,
                "❌ 用户ID必须是数字",
                parse_mode="Markdown"
            )
            from utils.message_manager import _schedule_deletion
            if sent_message:
                await _schedule_deletion(context, chat.id, sent_message.message_id, 10)
            return
            
        # 加载现有数据
        import json
        from pathlib import Path
        from utils.known_points_loader import get_known_points_loader
        
        loader = get_known_points_loader()
        data_file = Path("data/known_points.json")
        
        if not data_file.exists():
            sent_message = await send_search_result(
                context, chat.id,
                "❌ 数据文件不存在，无数据点可删除",
                parse_mode="Markdown"
            )
            from utils.message_manager import _schedule_deletion
            if sent_message:
                await _schedule_deletion(context, chat.id, sent_message.message_id, 10)
            return
            
        with open(data_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        points = data.get("known_points", [])
        original_length = len(points)
        
        # 找到要删除的点
        removed_point = None
        for point in points:
            if point["user_id"] == user_id:
                removed_point = point
                break
                
        if not removed_point:
            sent_message = await send_search_result(
                context, chat.id,
                f"❌ 未找到用户ID `{user_id}` 的数据点",
                parse_mode="Markdown"
            )
            from utils.message_manager import _schedule_deletion
            if sent_message:
                await _schedule_deletion(context, chat.id, sent_message.message_id, 10)
            return
            
        # 删除数据点
        points = [p for p in points if p["user_id"] != user_id]
        data["known_points"] = points
        
        from datetime import datetime
        data["last_updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
        
        # 保存数据
        with open(data_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
            
        # 强制重新加载数据
        loader.reload()
        
        reply_text = (
            f"✅ **数据点删除成功**\n\n"
            f"👤 **用户ID**: `{user_id}`\n"
            f"📅 **原日期**: {removed_point['date']}\n"
            f"📝 **原备注**: {escape_markdown(removed_point.get('note', '无'))}\n\n"
            f"📊 **剩余数据点**: {len(points)}"
        )
        
        sent_message = await send_search_result(context, chat.id, reply_text, parse_mode="Markdown")
        from utils.message_manager import _schedule_deletion
        if sent_message:
            await _schedule_deletion(context, chat.id, sent_message.message_id, 60)
        
    except Exception as e:
        sent_message = await send_search_result(
            context, chat.id,
            f"❌ 删除数据点失败: {str(e)}",
            parse_mode="Markdown"
        )
        from utils.message_manager import _schedule_deletion
        if sent_message:
            await _schedule_deletion(context, chat.id, sent_message.message_id, 10)


async def list_points_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    列出已知数据点命令（管理员专用）
    使用方法: /listpoints [limit]
    现在支持Telegraph: 当内容过长时自动发布到Telegraph
    """
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    
    if not message or not chat or not user:
        return
        
    # 立即删除用户命令
    await delete_user_command(context, chat.id, message.message_id)
    
    try:
        # 解析限制参数
        use_telegraph = False
        limit = 10  # 默认显示10个
        
        if context.args:
            try:
                limit = int(context.args[0])
                if limit <= 0:
                    limit = 10
                # 移除50个限制，改为支持更大数量
                elif limit > 200:  # 设置一个合理的上限
                    limit = 200
            except ValueError:
                pass
                
        # 加载数据
        import json
        from pathlib import Path
        
        data_file = Path("data/known_points.json")
        
        if not data_file.exists():
            sent_message = await send_search_result(
                context, chat.id,
                "❌ 数据文件不存在，暂无数据点",
                parse_mode="Markdown"
            )
            from utils.message_manager import _schedule_deletion
            if sent_message:
                await _schedule_deletion(context, chat.id, sent_message.message_id, 10)
            return
            
        with open(data_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        points = data.get("known_points", [])
        
        if not points:
            sent_message = await send_search_result(
                context, chat.id,
                "📝 暂无数据点",
                parse_mode="Markdown"
            )
            from utils.message_manager import _schedule_deletion
            if sent_message:
                await _schedule_deletion(context, chat.id, sent_message.message_id, 10)
            return
            
        # 按user_id排序
        points.sort(key=lambda x: x["user_id"])
        
        # 统计信息
        total_points = len(points)
        verified_count = sum(1 for p in points if "✅" in p.get("note", ""))
        
        # 构建完整的回复文本
        reply_text = f"📊 **已知数据点列表**\n\n"
        reply_text += f"📈 **统计**: 总数 {total_points} \\| 已验证 {verified_count} \\| 估算 {total_points - verified_count}\n\n"
        
        display_points = points[:limit]
        
        for i, point in enumerate(display_points, 1):
            user_id = point["user_id"]
            date = point["date"] 
            note = point.get("note", "无备注")
            
            # 截断过长的备注
            if len(note) > 15:
                note = note[:15] + "..."
            
            # 简单转义MarkdownV2特殊字符
            def escape_markdown_v2(text):
                chars_to_escape = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
                for char in chars_to_escape:
                    text = text.replace(char, f'\\{char}')
                return text
                
            reply_text += f"{i:>2}\\. `{user_id:<11}` {escape_markdown_v2(date)} *{escape_markdown_v2(note)}*\n"
            
        if total_points > limit:
            reply_text += f"\n\\.\\.\\. 还有 {total_points - limit} 个数据点\n"
            
        reply_text += f"\n\n💡 **管理命令**:\n"
        reply_text += f"• `/addpoint \\<id\\> \\<date\\> \\[note\\]` \\- 添加数据点\n"
        reply_text += f"• `/removepoint \\<id\\>` \\- 删除数据点"
        
        # 检查消息长度是否超过Telegram限制
        if len(reply_text) > TELEGRAM_MESSAGE_LIMIT:
            # 尝试发布到Telegraph
            telegraph_content = format_points_for_telegraph(display_points)
            telegraph_url = await create_telegraph_page(f"数据点列表 ({total_points}个)", telegraph_content)
            
            if telegraph_url:
                # 发送简化消息，包含Telegraph链接
                short_reply = (
                    f"📊 **已知数据点列表**\n\n"
                    f"📈 **统计**: 总数 {total_points} \\| 已验证 {verified_count} \\| 估算 {total_points - verified_count}\n\n"
                    f"📄 **完整列表**: 由于内容较长，已发布到Telegraph\n"
                    f"🔗 **查看链接**: {telegraph_url}\n\n"
                    f"💡 **管理命令**:\n"
                    f"• `/addpoint \\<id\\> \\<date\\> \\[note\\]` \\- 添加数据点\n"
                    f"• `/removepoint \\<id\\>` \\- 删除数据点"
                )
                
                sent_message = await send_message_with_fallback(
                    context, chat.id, short_reply,
                    parse_mode="MarkdownV2",
                    fallback_text=f"📊 数据点列表 (总数: {total_points})\n\n完整列表已发布到Telegraph: {telegraph_url}\n\n管理命令:\n• /addpoint <id> <date> [note] - 添加数据点\n• /removepoint <id> - 删除数据点"
                )
            else:
                # Telegraph发布失败，发送截断的消息
                fallback_text = (
                    f"📊 数据点列表 (总数: {total_points})\n\n"
                    f"⚠️ 由于内容过长且Telegraph发布失败，仅显示前{min(limit, 10)}个数据点\n"
                    f"请使用较小的数字参数查看，如: /listpoints 10\n\n"
                    f"管理命令:\n"
                    f"• /addpoint <id> <date> [note] - 添加数据点\n"
                    f"• /removepoint <id> - 删除数据点"
                )
                
                sent_message = await send_search_result(context, chat.id, fallback_text)
        else:
            # 正常发送消息
            sent_message = await send_message_with_fallback(
                context, chat.id, reply_text,
                parse_mode="MarkdownV2",
                fallback_text=f"📊 已知数据点列表\n统计: 总数 {total_points} | 已验证 {verified_count} | 估算 {total_points - verified_count}\n\n管理命令:\n• /addpoint <id> <date> [note] - 添加数据点\n• /removepoint <id> - 删除数据点"
            )
        
        from utils.message_manager import _schedule_deletion
        if sent_message:
            await _schedule_deletion(context, chat.id, sent_message.message_id, 120)
        
    except Exception as e:
        sent_message = await send_search_result(
            context, chat.id,
            f"❌ 获取数据点列表失败: {str(e)}",
            parse_mode="Markdown"
        )
        from utils.message_manager import _schedule_deletion
        if sent_message:
            await _schedule_deletion(context, chat.id, sent_message.message_id, 10)


# 注册命令
command_factory.register_command("id", get_id_command, permission=Permission.NONE, description="获取用户或群组的ID")
command_factory.register_command("when", when_command, permission=Permission.NONE, description="查询用户详细信息（支持数字ID、用户名或回复消息）")
command_factory.register_command("cache", cache_debug_command, permission=Permission.ADMIN, description="查看用户缓存状态（管理员专用）")
command_factory.register_command("cleanid", clean_id_command, permission=Permission.ADMIN, description="清理用户ID缓存（管理员专用）")
command_factory.register_command("addpoint", add_point_command, permission=Permission.ADMIN, description="添加已知数据点（管理员专用）")
command_factory.register_command("removepoint", remove_point_command, permission=Permission.ADMIN, description="删除已知数据点（管理员专用）")
command_factory.register_command("listpoints", list_points_command, permission=Permission.ADMIN, description="列出已知数据点（管理员专用）")
