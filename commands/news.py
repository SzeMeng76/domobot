#!/usr/bin/env python3
"""
新闻聚合命令模块
集成 NewsNow API 获取各平台热门新闻
"""

import asyncio
import logging
import feedparser
from datetime import datetime
from typing import Dict, List, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from telegram.ext import ContextTypes, CallbackQueryHandler

from utils.command_factory import command_factory
from utils.config_manager import get_config
from utils.error_handling import with_error_handling
from utils.http_client import get_http_client
from utils.message_manager import (
    send_message_with_auto_delete,
    delete_user_command,
    send_info,
    send_error,
    send_success,
    send_help
)
from utils.permissions import Permission

logger = logging.getLogger(__name__)

# 翻译功能
try:
    from googletrans import Translator
    translator = Translator()
    TRANSLATION_AVAILABLE = True
except ImportError:
    logger.warning("Google Translate not available. English news will not be translated.")
    translator = None
    TRANSLATION_AVAILABLE = False

# The Verge RSS URL
VERGE_RSS_URL = "https://www.theverge.com/rss/index.xml"

# 新闻源配置（使用API实际支持的源名称）
NEWS_SOURCES = {
    'zhihu': '知乎热榜',
    'github-trending-today': 'GitHub趋势',
    'weibo': '微博热搜',
    'v2ex-share': 'V2EX最新',
    'ithome': 'IT之家',
    'juejin': '稀土掘金',
    'hackernews': 'Hacker News',
    'solidot': 'Solidot',
    'sspai': '少数派',
    'bilibili-hot-search': '哔哩哔哩热搜',
    'douyin': '抖音热点',
    'producthunt': 'Product Hunt',
    'jin10': '金十数据',
    'wallstreetcn-quick': '华尔街见闻快讯',
    'gelonghui': '格隆汇',
    'xueqiu-hotstock': '雪球热门股票',
    'smzdm': '什么值得买',
    'coolapk': '酷安',
    'tieba': '百度贴吧',
    'toutiao': '今日头条',
    'thepaper': '澎湃新闻',
    'ifeng': '凤凰网',
    'hupu': '虎扑',
    'nowcoder': '牛客网',
    'chongbuluo-latest': '虫部落最新',
    'linuxdo': 'Linux.do',
    'pcbeta-windows11': '远景论坛Win11',
    'kaopu': '靠谱新闻',
    'kuaishou': '快手',
    'fastbull-express': '法布财经快讯',
    'ghxi': '极客公园',
    'cankaoxiaoxi': '参考消息',
    'zaobao': '联合早报',
    'sputniknewscn': '卫星通讯社',
    'mktnews-flash': 'MKTNews快讯',
    'baidu': '百度热搜',
    '36kr-quick': '36氪快讯',
    '36kr-renqi': '36氪人气榜',
    'cls-telegraph': '财联社电报',
    'cls-depth': '财联社深度',
    'cls-hot': '财联社热榜',
    'freebuf': 'FreeBuf网络安全',
    'verge': 'The Verge (英文科技)',
    'douban': '豆瓣电影',
    'steam': 'Steam游戏排行',
    'tencent-hot': '腾讯新闻综合早报',
    'qqvideo-tv-hotsearch': '腾讯视频电视剧热搜榜',
    'iqiyi-hot-ranklist': '爱奇艺热播榜',
    'aihot': 'AIHOT',
    'dongqiudi': '懂球帝',
    # 兼容性别名（保持原有源名称可用）
    'github': 'GitHub趋势',
    'v2ex': 'V2EX最新',
    'bilibili': '哔哩哔哩热搜',
    'wallstreetcn': '华尔街见闻快讯',
    'xueqiu': '雪球热门股票',
    'chongbuluo': '虫部落最新',
    'pcbeta': '远景论坛Win11',
    'fastbull': '法布财经快讯',
    'mktnews': 'MKTNews快讯',
    '36kr': '36氪快讯',
}

# 源名称映射（兼容性处理）
SOURCE_MAPPING = {
    'github': 'github-trending-today',
    'v2ex': 'v2ex-share',
    'bilibili': 'bilibili-hot-search',
    'wallstreetcn': 'wallstreetcn-quick',
    'xueqiu': 'xueqiu-hotstock',
    'chongbuluo': 'chongbuluo-latest',
    'pcbeta': 'pcbeta-windows11',
    'fastbull': 'fastbull-express',
    'mktnews': 'mktnews-flash',
    '36kr': '36kr-quick',
}

def get_actual_source_name(source: str) -> str:
    """获取实际的API源名称"""
    return SOURCE_MAPPING.get(source, source)

async def translate_text(text: str, target_language: str = 'zh-cn') -> str:
    """翻译文本到目标语言"""
    if not TRANSLATION_AVAILABLE or not translator:
        return text
    
    # 限制文本长度避免超过API限制
    if len(text) > 5000:  # 限制长度，避免超过15k字符限制
        text = text[:5000] + "..."
    
    try:
        # 在线程池中执行翻译，避免阻塞事件循环
        import asyncio
        loop = asyncio.get_event_loop()
        
        def sync_translate():
            return translator.translate(text, dest=target_language, src='auto')
        
        result = await loop.run_in_executor(None, sync_translate)
        
        # 检查结果是否是协程
        if asyncio.iscoroutine(result):
            result = await result
            
        return result.text
    except Exception as e:
        logger.warning(f"Translation failed for text '{text[:50]}...': {e}")
        return text

async def get_verge_news(count: int = 10) -> List[Dict]:
    """获取The Verge RSS新闻"""
    try:
        httpx_client = get_http_client()
        logger.info("从 The Verge RSS 获取新闻")

        # 获取RSS数据
        response = await httpx_client.get(VERGE_RSS_URL, timeout=10.0)
        response.raise_for_status()

        # 解析RSS
        feed = feedparser.parse(response.text)
        items = []

        for entry in feed.entries[:count]:
            # 提取新闻内容
            title = entry.get('title', '无标题')
            url = entry.get('link', '')
            pub_date = entry.get('published', '')
            summary = entry.get('summary', '')

            # 如果启用翻译，翻译标题和摘要
            if TRANSLATION_AVAILABLE:
                try:
                    translated_title = await translate_text(title)
                    # 翻译摘要，限制长度避免API超限，但比之前更合理
                    translation_text = summary[:500] if len(summary) > 500 else summary
                    translated_summary = await translate_text(translation_text)
                except Exception as e:
                    logger.warning(f"翻译失败: {e}")
                    translated_title = f"[英文] {title}"
                    # 翻译失败时也应用相同的长度限制
                    limited_summary = summary[:500] if len(summary) > 500 else summary
                    translated_summary = f"[英文] {limited_summary}"
            else:
                translated_title = f"[英文] {title}"
                # 没有翻译功能时也应用长度限制
                limited_summary = summary[:500] if len(summary) > 500 else summary
                translated_summary = f"[英文] {limited_summary}"

            items.append({
                'title': translated_title,
                'url': url,
                'summary': translated_summary,
                'original_summary_length': len(summary),  # 保存原始摘要长度用于判断
                'extra': {'info': pub_date}
            })

        logger.info(f"成功获取 {len(items)} 条 Verge 新闻")
        return items

    except Exception as e:
        logger.error(f"获取 Verge 新闻失败: {e}")
        return []

# 全局变量
_cache_manager = None

def set_dependencies(cache_manager):
    """设置依赖"""
    global _cache_manager
    _cache_manager = cache_manager


def create_news_sources_keyboard() -> InlineKeyboardMarkup:
    """创建新闻源选择键盘"""
    keyboard = []
    
    # 按类别分组显示新闻源（使用兼容名称，便于用户识别）
    categories = [
        ("🔧 科技类", ['github', 'ithome', 'juejin', 'hackernews', 'solidot', 'sspai', 'ghxi', 'linuxdo', 'chongbuluo', 'freebuf', 'verge', 'aihot']),
        ("💬 社交类", ['zhihu', 'weibo', 'v2ex', 'bilibili', 'douyin', 'tieba', 'kuaishou', 'coolapk']),
        ("⚽ 体育类", ['hupu', 'dongqiudi']),
        ("💰 财经类", ['jin10', 'wallstreetcn', 'gelonghui', 'xueqiu', '36kr', '36kr-renqi', 'fastbull', 'mktnews', 'cls-telegraph', 'cls-depth', 'cls-hot']),
        ("📰 新闻类", ['toutiao', 'thepaper', 'ifeng', 'baidu', 'tencent-hot', 'cankaoxiaoxi', 'zaobao', 'sputniknewscn', 'kaopu']),
        ("📺 影视类", ['qqvideo-tv-hotsearch', 'iqiyi-hot-ranklist', 'douban']),
        ("🛍️ 其他", ['smzdm', 'producthunt', 'nowcoder', 'pcbeta', 'steam'])
    ]
    
    for category_name, sources in categories:
        # 添加类别标题（仅显示用）
        keyboard.append([InlineKeyboardButton(f"📂 {category_name}", callback_data="news_category_info")])
        
        # 每行显示2个新闻源
        for i in range(0, len(sources), 2):
            row = []
            for j in range(2):
                if i + j < len(sources):
                    source = sources[i + j]
                    source_name = NEWS_SOURCES.get(source, source)
                    row.append(InlineKeyboardButton(source_name, callback_data=f"news_source_{source}"))
            keyboard.append(row)
    
    # 添加操作按钮
    keyboard.append([
        InlineKeyboardButton("🔥 热门新闻", callback_data="news_hot"),
        InlineKeyboardButton("❌ 关闭", callback_data="news_close")
    ])
    
    return InlineKeyboardMarkup(keyboard)


def create_news_settings_keyboard(source: str) -> InlineKeyboardMarkup:
    """创建新闻数量选择键盘"""
    keyboard = []
    
    # 数量选择按钮
    counts = [5, 10, 15, 20]
    row = []
    for count in counts:
        row.append(InlineKeyboardButton(f"{count}条", callback_data=f"news_get_{source}_{count}"))
    keyboard.append(row)
    
    # 返回和关闭按钮
    keyboard.append([
        InlineKeyboardButton("🔙 返回", callback_data="news_back"),
        InlineKeyboardButton("❌ 关闭", callback_data="news_close")
    ])
    
    return InlineKeyboardMarkup(keyboard)


async def get_news(source_id: str, count: int = 10) -> List[Dict]:
    """
    获取指定源的新闻
    
    Args:
        source_id: 新闻源ID
        count: 获取数量，默认10条
        
    Returns:
        新闻列表
    """
    # 如果是Verge源，使用RSS解析
    if source_id.lower() == 'verge':
        # 检查缓存
        cache_key = f"verge_{count}"
        if _cache_manager:
            try:
                cached_data = await _cache_manager.load_cache(cache_key, subdirectory="news")
                if cached_data:
                    logger.info(f"使用缓存获取 Verge 新闻")
                    return cached_data
            except Exception as e:
                logger.warning(f"缓存读取失败: {e}")
        
        # 获取Verge新闻
        items = await get_verge_news(count)
        
        # 缓存结果（5分钟有效期）
        if _cache_manager and items:
            try:
                await _cache_manager.save_cache(cache_key, items, subdirectory="news")
            except Exception as e:
                logger.warning(f"缓存写入失败: {e}")
        
        return items
    
    # 原有的NewsNow API逻辑
    # 映射到实际的API源名称
    actual_source_id = get_actual_source_name(source_id)
    
    httpx_client = get_http_client()
    base_url = "https://news.smone.us"
    url = f"{base_url}/api/s?id={actual_source_id}"
    
    # 检查缓存
    cache_key = f"{source_id}_{count}"
    if _cache_manager:
        try:
            cached_data = await _cache_manager.load_cache(cache_key, subdirectory="news")
            if cached_data:
                logger.info(f"使用缓存获取 {source_id} 新闻")
                return cached_data
        except Exception as e:
            logger.warning(f"缓存读取失败: {e}")
    
    try:
        logger.info(f"从 NewsNow API 获取 {source_id} 新闻")
        # Vercel优化：减少超时时间，避免冷启动影响
        response = await httpx_client.get(url, timeout=8.0)
        response.raise_for_status()
        data = response.json()
        
        if data.get('status') in ['success', 'cache']:
            items = data.get('items', [])[:count]
            
            # 缓存结果（5分钟有效期）
            if _cache_manager and items:
                try:
                    await _cache_manager.save_cache(cache_key, items, subdirectory="news")
                except Exception as e:
                    logger.warning(f"缓存写入失败: {e}")
            
            return items
        else:
            logger.warning(f"API 返回状态异常: {data.get('status')}")
            return []
            
    except Exception as e:
        logger.error(f"获取新闻失败 {source_id}: {e}")
        return []


def format_time_for_display(time_str: str, source: str = '') -> str:
    """
    格式化时间显示
    
    Args:
        time_str: 原始时间字符串
        source: 新闻源，用于确定时间格式处理方式
        
    Returns:
        格式化后的时间字符串
    """
    if not time_str:
        return time_str
        
    try:
        # 针对 Verge 等英文源的 ISO 时间格式进行优化
        if source.lower() == 'verge' and 'T' in time_str:
            # 解析 ISO 格式时间: 2025-08-21T20:00:00-04:00
            timezone_info = ""
            
            # 提取时区信息
            if '-04:00' in time_str:
                timezone_info = " (EDT)"  # Eastern Daylight Time
            elif '-05:00' in time_str:
                timezone_info = " (EST)"  # Eastern Standard Time
            elif '+' in time_str:
                # 处理正时区
                tz_part = time_str.split('+')[1]
                if tz_part.startswith('00:00'):
                    timezone_info = " (UTC)"
                else:
                    timezone_info = f" (+{tz_part.split(':')[0]})"
            elif time_str.count('-') > 2:
                # 处理负时区
                parts = time_str.split('-')
                if len(parts) >= 4 and ':' in parts[-1]:
                    tz_offset = parts[-1].split(':')[0]
                    timezone_info = f" (-{tz_offset})"
            
            # 解析时间部分
            time_part = time_str.split('+')[0].split('-04:')[0].split('-05:')[0]
            if 'T' in time_part:
                date_part, time_part = time_part.split('T')
                year, month, day = date_part.split('-')
                hour, minute = time_part.split(':')[:2]
                
                # 转换为更友好的中文格式，包含时区
                return f"{month}-{day} {hour}:{minute}{timezone_info}"
            
        # 对于其他格式，直接返回原始时间
        return time_str
        
    except Exception as e:
        # 如果解析失败，返回原始时间
        return time_str


def smart_truncate_summary(text: str, max_length: int = 200) -> str:
    """
    智能截断摘要，优先在自然断点处截断
    
    Args:
        text: 原始文本
        max_length: 最大长度
        
    Returns:
        智能截断后的文本
    """
    if not text or len(text) <= max_length:
        return text
    
    # 如果文本长度超过限制，寻找最佳截断点
    truncated = text[:max_length]
    
    # 定义断点优先级：句号 > 其他标点 > 空格
    breakpoints = [
        (['。', '！', '？'], 1),  # 中文句号优先级最高
        (['.', '!', '?'], 1),     # 英文句号优先级最高
        (['，', '；', '：'], 2),   # 中文标点
        ([',', ';', ':'], 2),     # 英文标点
        ([' '], 3)                # 空格
    ]
    
    best_cut = -1
    best_priority = 999
    
    # 从后向前搜索，找到最好的截断点
    search_start = max(0, max_length - 80)  # 确保不会出现负数
    for i in range(len(truncated) - 1, search_start, -1):
        char = truncated[i]
        
        for chars, priority in breakpoints:
            if char in chars:
                # 对于句号，确保不是数字后的小数点
                if char in ['.'] and i > 0 and truncated[i-1].isdigit():
                    continue
                
                # 找到更好的断点
                if priority < best_priority:
                    best_cut = i + 1 if char in ['。', '！', '？', '.', '!', '?'] else i
                    best_priority = priority
                    break
        
        # 如果找到句号级别的断点就不用继续找了
        if best_priority == 1:
            break
    
    # 如果找到了合适的截断点
    if best_cut > 0:
        result = truncated[:best_cut].rstrip()
        # 如果截断点不是句号结尾，添加省略号
        if not result.endswith(('。', '！', '？', '.', '!', '?')):
            result += "..."
        return result
    
    # 没找到合适断点，在最后一个空格处截断
    last_space = truncated.rfind(' ')
    if last_space > max_length * 0.8:
        return truncated[:last_space] + "..."
    
    # 实在找不到，只能硬截断
    return truncated.rstrip() + "..."


def format_news_message(source: str, news_items: List[Dict], max_length: int = 4000) -> str:
    """
    格式化新闻消息
    
    Args:
        source: 新闻源
        news_items: 新闻列表
        max_length: 消息最大长度
        
    Returns:
        格式化后的消息
    """
    if not news_items:
        return f"❌ 未获取到 {NEWS_SOURCES.get(source, source)} 的新闻"
    
    # 消息头部
    source_name = NEWS_SOURCES.get(source, source)
    message_lines = [f"📰 {source_name} (共{len(news_items)}条)\n"]
    
    current_length = len(message_lines[0])
    
    for i, item in enumerate(news_items, 1):
        title = item.get('title', '无标题').strip()
        url = item.get('url', '')
        summary = item.get('summary', '').strip()
        extra_info = item.get('extra', {}).get('info', '')
        
        # 构建单条新闻
        if url:
            news_line = f"{i}. [{title}]({url})"
        else:
            news_line = f"{i}. {title}"
            
        # 如果有摘要且是 Verge 源，添加摘要显示
        if summary and source.lower() == 'verge':
            # 获取原始摘要长度
            original_length = item.get('original_summary_length', len(summary))
            # 使用智能截断，限制到200字符以保持可读性
            display_summary = smart_truncate_summary(summary, 200)
            news_line += f"\n   📝 {display_summary}"
            
            # 如果原始摘要长度超过200字符，或显示的摘要比翻译后的短，则显示提示
            if original_length > 200 or len(display_summary) < len(summary):
                news_line += f"\n   💡 点击标题链接查看完整内容"
            
        if extra_info:
            # 格式化时间显示
            formatted_time = format_time_for_display(extra_info, source)
            news_line += f"\n   📊 {formatted_time}"
        
        news_line += "\n"
        
        # 检查长度限制
        if current_length + len(news_line) > max_length:
            message_lines.append(f"\n📝 由于消息长度限制，仅显示前 {i-1} 条新闻")
            break
            
        message_lines.append(news_line)
        current_length += len(news_line)
    
    return "".join(message_lines)


@with_error_handling
async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """新闻命令处理器"""
    config = get_config()
    args = context.args or []
    
    if not args:
        # 显示新闻源选择界面
        keyboard = create_news_sources_keyboard()
        message = (
            "📰 **新闻聚合中心**\n\n"
            "🎯 请选择要查看的新闻源：\n\n"
            "💡 数据来源: NewsNow API\n"
            "🔄 支持缓存，响应迅速"
        )
        
        # 发送带按钮的消息
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=message,
            parse_mode='Markdown',
            reply_markup=keyboard
        )
        
        # 删除用户命令
        if update.message:
            await delete_user_command(context, update.effective_chat.id, update.message.message_id)
        return
    
    # 解析参数
    source = args[0].lower()
    count = 10  # 默认获取10条
    
    if len(args) > 1 and args[1].isdigit():
        count = int(args[1])
        count = max(1, min(count, 30))  # 限制在1-30之间
    
    if source not in NEWS_SOURCES:
        available_sources = ", ".join(list(NEWS_SOURCES.keys())[:10])
        await send_error(
            context, 
            update.effective_chat.id, 
            f"❌ 不支持的新闻源: `{source}`\n\n部分可用源: {available_sources}\n\n使用 `/news` 查看完整列表",
            parse_mode='Markdown'
        )
        
        # 删除用户命令
        if update.message:
            await delete_user_command(context, update.effective_chat.id, update.message.message_id)
        return
    
    # 发送加载提示
    loading_message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🔄 正在获取 {NEWS_SOURCES[source]} 新闻...",
        parse_mode='Markdown'
    )
    
    try:
        # 获取新闻
        news_items = await get_news(source, count)
        
        # 删除加载提示
        await loading_message.delete()
        
        # 格式化并发送消息
        message = format_news_message(source, news_items)
        
        await send_success(
            context,
            update.effective_chat.id,
            message,
            parse_mode='Markdown'
        )
        
        # 删除用户命令
        if update.message:
            await delete_user_command(context, update.effective_chat.id, update.message.message_id)
        
        logger.info(f"成功获取 {source} 新闻 {len(news_items)} 条")
        
    except Exception as e:
        # 删除加载提示
        try:
            await loading_message.delete()
        except:
            pass
        
        logger.error(f"新闻命令执行失败: {e}")
        await send_error(
            context,
            update.effective_chat.id,
            f"❌ 获取 {NEWS_SOURCES[source]} 新闻失败\n\n请稍后重试或联系管理员"
        )
        
        # 删除用户命令
        if update.message:
            await delete_user_command(context, update.effective_chat.id, update.message.message_id)


@with_error_handling
async def newslist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """新闻源列表和直接查询命令"""
    config = get_config()
    args = context.args or []
    
    if not args:
        # 显示所有新闻源列表
        help_lines = [
            "📰 **NewsNow 新闻源列表**\n",
            "🔧 **科技类:**"
        ]
        
        # 按类别分组显示（使用兼容名称）
        categories = [
            ("🔧 科技类", ['github', 'ithome', 'juejin', 'hackernews', 'solidot', 'sspai', 'ghxi', 'linuxdo', 'chongbuluo', 'freebuf', 'verge', 'aihot']),
            ("💬 社交类", ['zhihu', 'weibo', 'v2ex', 'bilibili', 'douyin', 'tieba', 'kuaishou', 'coolapk']),
            ("⚽ 体育类", ['hupu', 'dongqiudi']),
            ("💰 财经类", ['jin10', 'wallstreetcn', 'gelonghui', 'xueqiu', '36kr', '36kr-renqi', 'fastbull', 'mktnews', 'cls-telegraph', 'cls-depth', 'cls-hot']),
            ("📰 新闻类", ['toutiao', 'thepaper', 'ifeng', 'baidu', 'tencent-hot', 'cankaoxiaoxi', 'zaobao', 'sputniknewscn', 'kaopu']),
            ("📺 影视类", ['qqvideo-tv-hotsearch', 'iqiyi-hot-ranklist', 'douban']),
            ("🛍️ 其他", ['smzdm', 'producthunt', 'nowcoder', 'pcbeta', 'steam'])
        ]
        
        help_lines = ["📰 **NewsNow 新闻源列表**\n"]
        
        for category_name, sources in categories:
            help_lines.append(f"**{category_name}**")
            for source in sources:
                source_name = NEWS_SOURCES.get(source, source)
                help_lines.append(f"• `{source}` - {source_name}")
            help_lines.append("")  # 空行分隔
        
        help_lines.extend([
            "**使用方法:**",
            "`/newslist [源名称] [数量]` - 直接查询新闻",
            "",
            "**示例:**",
            "• `/newslist zhihu` - 获取知乎热榜 (默认10条)",
            "• `/newslist zhihu 5` - 获取知乎热榜前5条",
            "• `/newslist github 15` - 获取GitHub趋势前15条",
            "",
            "💡 也可使用 `/news` 进入交互式选择界面"
        ])
        
        message = "\n".join(help_lines)
        await send_help(
            context,
            update.effective_chat.id,
            message,
            parse_mode='Markdown'
        )
        
        # 删除用户命令
        if update.message:
            await delete_user_command(context, update.effective_chat.id, update.message.message_id)
        return
    
    # 解析参数进行直接查询
    source = args[0].lower()
    count = 10  # 默认获取10条
    
    if len(args) > 1 and args[1].isdigit():
        count = int(args[1])
        count = max(1, min(count, 30))  # 限制在1-30之间
    
    if source not in NEWS_SOURCES:
        available_sources = ", ".join(list(NEWS_SOURCES.keys())[:10])
        await send_error(
            context, 
            update.effective_chat.id, 
            f"❌ 不支持的新闻源: `{source}`\n\n部分可用源: {available_sources}\n\n使用 `/newslist` 查看完整列表",
            parse_mode='Markdown'
        )
        
        # 删除用户命令
        if update.message:
            await delete_user_command(context, update.effective_chat.id, update.message.message_id)
        return
    
    # 发送加载提示
    loading_message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🔄 正在获取 {NEWS_SOURCES[source]} 新闻...",
        parse_mode='Markdown'
    )
    
    try:
        # 获取新闻
        news_items = await get_news(source, count)
        
        # 删除加载提示
        await loading_message.delete()
        
        # 格式化并发送消息
        message = format_news_message(source, news_items)
        
        await send_message_with_auto_delete(
            context,
            update.effective_chat.id,
            message,
            parse_mode='Markdown'
        )
        
        # 删除用户命令
        if update.message:
            await delete_user_command(context, update.effective_chat.id, update.message.message_id)
        
        logger.info(f"成功通过newslist获取 {source} 新闻 {len(news_items)} 条")
        
    except Exception as e:
        # 删除加载提示
        try:
            await loading_message.delete()
        except:
            pass
        
        logger.error(f"newslist命令执行失败: {e}")
        await send_error(
            context,
            update.effective_chat.id,
            f"❌ 获取 {NEWS_SOURCES[source]} 新闻失败\n\n请稍后重试或联系管理员"
        )
        
        # 删除用户命令
        if update.message:
            await delete_user_command(context, update.effective_chat.id, update.message.message_id)


# 热门新闻源配置（针对Vercel优化：稳定性优先）
HOT_NEWS_SOURCES = {
    # 按稳定性和响应速度排序，不易被反爬的源在前
    'social': ['weibo', 'bilibili', 'zhihu', 'tieba', 'douyin'],  # 微博最稳定，放第一
    'tech': ['ithome', 'github', 'juejin', 'sspai'],    # IT之家很稳定
    'finance': ['jin10', 'wallstreetcn', 'gelonghui'],  # 金十数据稳定
    'news': ['tencent-hot', 'toutiao', 'baidu', 'thepaper'],  # 腾讯新闻综合早报优先
    'video': ['qqvideo-tv-hotsearch', 'iqiyi-hot-ranklist']  # 影视热搜榜
}

def get_balanced_hot_sources() -> List[str]:
    """获取平衡的热门源列表（Vercel优化版）"""
    sources = []

    # Vercel优化策略：减少并发，优选稳定源
    # 控制在5个源以内，避免Vercel并发限制
    social_sources = HOT_NEWS_SOURCES['social'][:1]  # 只取最稳定的1个：weibo
    tech_sources = HOT_NEWS_SOURCES['tech'][:1]      # 只取最稳定的1个：ithome
    finance_sources = HOT_NEWS_SOURCES['finance'][:1] # 只取最稳定的1个：jin10
    news_sources = HOT_NEWS_SOURCES['news'][:1]       # 取1个：toutiao
    video_sources = HOT_NEWS_SOURCES['video'][:1]     # 取1个：qqvideo-tv-hotsearch

    sources.extend(social_sources)   # 1个社交源
    sources.extend(tech_sources)     # 1个科技源
    sources.extend(finance_sources)  # 1个财经源
    sources.extend(news_sources)     # 1个新闻源
    sources.extend(video_sources)    # 1个影视源

    # 总共5个源，既保证内容丰富又避免Vercel限制
    logger.info(f"Vercel优化热门源: 社交{social_sources} + 科技{tech_sources} + 财经{finance_sources} + 新闻{news_sources} + 影视{video_sources} = 总计{sources} (共{len(sources)}个源)")
    return sources

@with_error_handling  
async def hot_news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """热门新闻快捷命令"""
    # 使用平衡的热门源选择
    hot_sources = get_balanced_hot_sources()
    config = get_config()
    
    loading_message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="🔥 正在获取热门新闻..."
    )
    
    try:
        results = []
        
        # 并发获取多个源的新闻
        tasks = [get_news(source, 5) for source in hot_sources]
        news_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        successful_sources = 0
        failed_sources = []
        
        for i, (source, news_items) in enumerate(zip(hot_sources, news_results)):
            if isinstance(news_items, Exception):
                failed_sources.append(source)
                logger.warning(f"热门新闻获取失败 {source}: {news_items}")
                continue
                
            if news_items:
                successful_sources += 1
                source_name = NEWS_SOURCES.get(source, source)
                results.append(f"📰 **{source_name}** (前5条)")
                
                for j, item in enumerate(news_items[:5], 1):
                    title = item.get('title', '无标题').strip()
                    url = item.get('url', '')
                    
                    if url:
                        results.append(f"{j}. [{title}]({url})")
                    else:
                        results.append(f"{j}. {title}")
                
                results.append("")  # 空行分隔
            else:
                failed_sources.append(source)
                logger.warning(f"热门新闻源 {source} 返回空数据")
        
        await loading_message.delete()
        
        if results:
            message = f"🔥 **今日热门新闻** (成功获取 {successful_sources} 个源)\n\n" + "\n".join(results)
            message += "\n💡 使用 `/news [源名称]` 获取更多新闻"
            if failed_sources:
                message += f"\n\n⚠️ 部分源暂时不可用: {', '.join(failed_sources)}"
        else:
            message = f"❌ 暂时无法获取热门新闻，所有源都不可用\n失败源: {', '.join(failed_sources)}\n请稍后重试"
        
        logger.info(f"热门新闻获取完成：成功 {successful_sources} 个源，失败 {len(failed_sources)} 个源")
        
        await send_success(
            context,
            update.effective_chat.id,
            message,
            parse_mode='Markdown'
        )
        
        # 删除用户命令
        if update.message:
            await delete_user_command(context, update.effective_chat.id, update.message.message_id)
        
    except Exception as e:
        try:
            await loading_message.delete()
        except:
            pass
        
        logger.error(f"热门新闻命令执行失败: {e}")
        await send_error(
            context,
            update.effective_chat.id,
            "❌ 获取热门新闻失败，请稍后重试"
        )
        
        # 删除用户命令
        if update.message:
            await delete_user_command(context, update.effective_chat.id, update.message.message_id)


@with_error_handling
async def news_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理新闻相关的回调查询"""
    query = update.callback_query
    await query.answer()
    
    config = get_config()
    data = query.data
    
    try:
        if data == "news_close":
            # 关闭消息
            await query.message.delete()
            return
            
        elif data == "news_back":
            # 返回新闻源选择界面
            keyboard = create_news_sources_keyboard()
            message = (
                "📰 **新闻聚合中心**\n\n"
                "🎯 请选择要查看的新闻源：\n\n"
                "💡 数据来源: NewsNow API\n"
                "🔄 支持缓存，响应迅速"
            )
            
            await query.edit_message_text(
                text=message,
                parse_mode='Markdown',
                reply_markup=keyboard
            )
            return
            
        elif data == "news_hot":
            # 获取热门新闻汇总
            await query.edit_message_text("🔥 正在获取热门新闻...")
            
            hot_sources = get_balanced_hot_sources()
            results = []
            
            # 并发获取多个源的新闻
            tasks = [get_news(source, 3) for source in hot_sources]
            news_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            successful_sources = 0
            failed_sources = []
            
            for i, (source, news_items) in enumerate(zip(hot_sources, news_results)):
                if isinstance(news_items, Exception):
                    failed_sources.append(source)
                    logger.warning(f"回调热门新闻获取失败 {source}: {news_items}")
                    continue
                    
                if news_items:
                    successful_sources += 1
                    source_name = NEWS_SOURCES.get(source, source)
                    results.append(f"📰 **{source_name}** (前3条)")
                    
                    for j, item in enumerate(news_items[:3], 1):
                        title = item.get('title', '无标题').strip()
                        url = item.get('url', '')
                        
                        if url:
                            results.append(f"{j}. [{title[:50]}...]({url})")
                        else:
                            results.append(f"{j}. {title[:50]}...")
                    
                    results.append("")  # 空行分隔
                else:
                    failed_sources.append(source)
                    logger.warning(f"回调热门新闻源 {source} 返回空数据")
            
            if results:
                message = f"🔥 **今日热门新闻** (成功获取 {successful_sources} 个源)\n\n" + "\n".join(results)
                if failed_sources:
                    message += f"\n⚠️ 部分源不可用: {', '.join(failed_sources)}"
            else:
                message = f"❌ 暂时无法获取热门新闻，所有源都不可用\n失败源: {', '.join(failed_sources)}\n请稍后重试"
            
            logger.info(f"回调热门新闻获取完成：成功 {successful_sources} 个源，失败 {len(failed_sources)} 个源")
            
            # 删除带按钮的消息
            await query.message.delete()
            
            # 发送最终结果作为自动删除的文本消息（无按钮）
            await send_message_with_auto_delete(
                context,
                (query.message.chat_id if query.message else None),
                message,
                parse_mode='Markdown'
            )
            return
            
        elif data.startswith("news_source_"):
            # 选择了新闻源，显示数量选择
            source = data.replace("news_source_", "")
            source_name = NEWS_SOURCES.get(source, source)
            
            keyboard = create_news_settings_keyboard(source)
            message = f"📰 **{source_name}**\n\n🔢 请选择要获取的新闻数量："
            
            await query.edit_message_text(
                text=message,
                parse_mode='Markdown',
                reply_markup=keyboard
            )
            return
            
        elif data.startswith("news_get_"):
            # 获取指定数量的新闻
            parts = data.replace("news_get_", "").split("_")
            if len(parts) == 2:
                source, count_str = parts
                count = int(count_str)
                
                source_name = NEWS_SOURCES.get(source, source)
                await query.edit_message_text(f"🔄 正在获取 {source_name} 新闻...")
                
                # 获取新闻
                news_items = await get_news(source, count)
                
                # 格式化消息
                message = format_news_message(source, news_items)
                
                # 删除带按钮的消息
                await query.message.delete()
                
                # 发送最终结果作为自动删除的文本消息（无按钮）
                await send_message_with_auto_delete(
                    context,
                    (query.message.chat_id if query.message else None),
                    message,
                    parse_mode='Markdown'
                )
                
                logger.info(f"通过回调获取 {source} 新闻 {len(news_items)} 条")
            return
            
        elif data == "news_category_info":
            # 类别标题点击（无操作）
            await query.answer("这是分类标题，请选择下方的新闻源")
            return
            
    except Exception as e:
        logger.error(f"新闻回调处理失败: {e}")
        await query.edit_message_text(
            "❌ 处理请求时发生错误，请稍后重试",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 返回", callback_data="news_back"),
                InlineKeyboardButton("❌ 关闭", callback_data="news_close")
            ]])
        )


# 注册命令和回调处理器
command_factory.register_command(
    "news",
    news_command,
    permission=Permission.NONE,
    description="获取各平台热门新闻"
)

command_factory.register_command(
    "hotnews", 
    hot_news_command,
    permission=Permission.NONE,
    description="获取今日热门新闻汇总"
)

command_factory.register_command(
    "newslist",
    newslist_command,
    permission=Permission.NONE,
    description="显示新闻源列表和直接查询"
)

# 注册回调处理器
command_factory.register_callback(
    "^news_", 
    news_callback_handler, 
    permission=Permission.NONE, 
    description="新闻功能回调处理器"
)

@with_error_handling
async def news_clean_cache_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """清理新闻缓存命令"""
    if not update.message:
        return

    config = get_config()
    
    try:
        if _cache_manager:
            await _cache_manager.clear_cache(subdirectory="news")
            message = "✅ 新闻缓存已清理完成"
            logger.info("新闻缓存手动清理完成")
        else:
            message = "❌ 缓存管理器不可用"
            
        await send_success(
            context,
            update.effective_chat.id,
            message
        )
        
        # 删除用户命令
        if update.message:
            await delete_user_command(context, update.effective_chat.id, update.message.message_id)
            
    except Exception as e:
        logger.error(f"清理新闻缓存时发生错误: {e}")
        await send_error(
            context,
            update.effective_chat.id,
            f"❌ 清理新闻缓存时发生错误: {e}"
        )
        
        # 删除用户命令
        if update.message:
            await delete_user_command(context, update.effective_chat.id, update.message.message_id)


# 已迁移到统一缓存管理命令 /cleancache
# 注册缓存清理命令
# command_factory.register_command(
#     "news_cleancache",
#     news_clean_cache_command,
#     permission=Permission.ADMIN,
#     description="清理新闻缓存"
# )


# =============================================================================
# Inline 执行入口
# =============================================================================

async def news_inline_execute(args: str) -> dict:
    """
    Inline Query 执行入口 - 提供完整的新闻查询功能

    Args:
        args: 用户输入的参数字符串，如 "zhihu" 或 "github"，为空则返回热门新闻

    Returns:
        dict: {
            "success": bool,
            "title": str,
            "message": str,
            "description": str,
            "error": str | None
        }
    """
    try:
        if not args or not args.strip():
            # 无参数：返回热门新闻汇总
            hot_sources = get_balanced_hot_sources()
            results = []

            # 并发获取多个源的新闻
            import asyncio
            tasks = [get_news(source, 3) for source in hot_sources]
            news_results = await asyncio.gather(*tasks, return_exceptions=True)

            successful_sources = 0
            failed_sources = []

            for source, news_items in zip(hot_sources, news_results):
                if isinstance(news_items, Exception):
                    failed_sources.append(source)
                    continue

                if news_items:
                    successful_sources += 1
                    source_name = NEWS_SOURCES.get(source, source)
                    results.append(f"📰 **{source_name}** (前3条)")

                    for j, item in enumerate(news_items[:3], 1):
                        title = item.get('title', '无标题').strip()
                        url = item.get('url', '')

                        if url:
                            results.append(f"{j}. [{title[:40]}...]({url})")
                        else:
                            results.append(f"{j}. {title[:40]}...")

                    results.append("")  # 空行分隔
                else:
                    failed_sources.append(source)

            if results:
                message = f"🔥 **今日热门新闻** (成功获取 {successful_sources} 个源)\n\n" + "\n".join(results)
                message += "\n💡 使用 `news 源名称` 获取更多新闻"
                if failed_sources:
                    message += f"\n\n⚠️ 部分源暂时不可用: {', '.join(failed_sources)}"

                return {
                    "success": True,
                    "title": "🔥 今日热门新闻",
                    "message": message,
                    "description": f"来自 {successful_sources} 个平台的热门资讯",
                    "error": None
                }
            else:
                return {
                    "success": False,
                    "title": "❌ 获取新闻失败",
                    "message": "暂时无法获取热门新闻，所有源都不可用",
                    "description": "新闻源不可用",
                    "error": "所有新闻源不可用"
                }

        else:
            # 有参数：查询指定新闻源
            source = args.strip().split()[0].lower()
            count = 10  # 默认10条

            # 尝试解析数量参数
            parts = args.strip().split()
            if len(parts) > 1 and parts[1].isdigit():
                count = min(int(parts[1]), 20)  # 最多20条

            if source not in NEWS_SOURCES:
                # 提供可用源列表
                available_sources = list(NEWS_SOURCES.keys())[:15]
                return {
                    "success": False,
                    "title": f"❌ 不支持的新闻源: {source}",
                    "message": f"不支持的新闻源: `{source}`\n\n**部分可用源:**\n" + ", ".join(available_sources),
                    "description": f"不支持的新闻源: {source}",
                    "error": "新闻源不存在"
                }

            # 获取新闻
            news_items = await get_news(source, count)

            if not news_items:
                return {
                    "success": False,
                    "title": f"❌ 获取 {NEWS_SOURCES[source]} 失败",
                    "message": f"未能获取 {NEWS_SOURCES[source]} 的新闻，请稍后重试",
                    "description": "获取新闻失败",
                    "error": "API 返回空数据"
                }

            # 格式化消息
            message = format_news_message(source, news_items)

            return {
                "success": True,
                "title": f"📰 {NEWS_SOURCES[source]}",
                "message": message,
                "description": f"{NEWS_SOURCES[source]} 最新 {len(news_items)} 条",
                "error": None
            }

    except Exception as e:
        logger.error(f"Inline news query failed: {e}")
        return {
            "success": False,
            "title": "❌ 查询失败",
            "message": f"查询新闻失败: {str(e)}",
            "description": "查询失败",
            "error": str(e)
        }


logger.info("新闻命令模块已加载")