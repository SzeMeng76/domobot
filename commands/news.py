#!/usr/bin/env python3
"""
新闻聚合命令模块
集成 NewsNow API 获取各平台热门新闻
"""

import asyncio
import logging
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
    send_success
)
from utils.permissions import Permission

logger = logging.getLogger(__name__)

# 新闻源配置
NEWS_SOURCES = {
    'zhihu': '知乎热榜',
    'github': 'GitHub趋势',
    'weibo': '微博热搜', 
    'v2ex': 'V2EX最新',
    'ithome': 'IT之家',
    'juejin': '掘金热门',
    'hackernews': 'Hacker News',
    'solidot': 'Solidot',
    'sspai': '少数派',
    'bilibili': '哔哩哔哩热门',
    'douyin': '抖音热点',
    'weread': '微信读书',
    'producthunt': 'Product Hunt',
    'jin10': '金十数据',
    'wallstreetcn': '华尔街见闻',
    'gelonghui': '格隆汇',
    'xueqiu': '雪球',
    'smzdm': '什么值得买',
    'coolapk': '酷安',
    'tieba': '百度贴吧',
    'toutiao': '今日头条',
    'thepaper': '澎湃新闻',
    'ifeng': '凤凰网',
    'hupu': '虎扑',
    'nowcoder': '牛客网',
    'chongbuluo': '虫部落',
    'linuxdo': 'Linux.do',
    'pcbeta': '远景论坛',
    'kaopu': '靠谱新闻',
    'kuaishou': '快手',
    'fastbull': '快讯通财经',
    'ghxi': '极客公园',
    'cankaoxiaoxi': '参考消息',
    'zaobao': '联合早报',
    'sputniknewscn': '俄罗斯卫星通讯社',
    'mktnews': 'MKT新闻',
    'baidu': '百度热搜',
    '36kr': '36氪',
}

# 全局变量
_cache_manager = None

def set_dependencies(cache_manager):
    """设置依赖"""
    global _cache_manager
    _cache_manager = cache_manager


def create_news_sources_keyboard() -> InlineKeyboardMarkup:
    """创建新闻源选择键盘"""
    keyboard = []
    
    # 按类别分组显示新闻源
    categories = [
        ("🔧 科技类", ['github', 'ithome', 'juejin', 'hackernews', 'solidot', 'sspai']),
        ("💬 社交类", ['zhihu', 'weibo', 'v2ex', 'bilibili', 'douyin', 'tieba']),
        ("💰 财经类", ['jin10', 'wallstreetcn', 'gelonghui', 'xueqiu', '36kr']),
        ("📰 新闻类", ['toutiao', 'thepaper', 'ifeng', 'baidu']),
        ("🛍️ 其他", ['smzdm', 'producthunt', 'weread'])
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
    httpx_client = get_http_client()
    base_url = "https://newsnow.busiyi.world"
    url = f"{base_url}/api/s?id={source_id}"
    
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
        response = await httpx_client.get(url, timeout=10.0)
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
        extra_info = item.get('extra', {}).get('info', '')
        
        # 构建单条新闻
        if url:
            news_line = f"{i}. [{title}]({url})"
        else:
            news_line = f"{i}. {title}"
            
        if extra_info:
            news_line += f"\n   📊 {extra_info}"
        
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
async def hot_news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """热门新闻快捷命令"""
    # 获取多个热门源的新闻
    hot_sources = ['zhihu', 'weibo', 'github', 'ithome']
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
        
        for i, (source, news_items) in enumerate(zip(hot_sources, news_results)):
            if isinstance(news_items, Exception):
                continue
                
            if news_items:
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
        
        await loading_message.delete()
        
        if results:
            message = "🔥 **今日热门新闻**\n\n" + "\n".join(results)
            message += "\n💡 使用 `/news [源名称]` 获取更多新闻"
        else:
            message = "❌ 暂时无法获取热门新闻，请稍后重试"
        
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
            await query.edit_message_text("🔄 正在获取热门新闻...")
            
            hot_sources = ['zhihu', 'weibo', 'github', 'ithome']
            results = []
            
            # 并发获取多个源的新闻
            tasks = [get_news(source, 3) for source in hot_sources]
            news_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for i, (source, news_items) in enumerate(zip(hot_sources, news_results)):
                if isinstance(news_items, Exception):
                    continue
                    
                if news_items:
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
            
            if results:
                message = "🔥 **今日热门新闻**\n\n" + "\n".join(results)
                message += "\n💡 点击返回选择其他新闻源"
            else:
                message = "❌ 暂时无法获取热门新闻，请稍后重试"
            
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 返回", callback_data="news_back"),
                InlineKeyboardButton("❌ 关闭", callback_data="news_close")
            ]])
            
            await query.edit_message_text(
                text=message,
                parse_mode='Markdown',
                reply_markup=keyboard
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
                
                # 格式化并发送消息
                message = format_news_message(source, news_items)
                
                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 返回", callback_data="news_back"),
                    InlineKeyboardButton("❌ 关闭", callback_data="news_close")
                ]])
                
                await query.edit_message_text(
                    text=message,
                    parse_mode='Markdown',
                    reply_markup=keyboard
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
    command="news",
    handler=news_command,
    description="获取各平台热门新闻",
    permission=Permission.NONE,
    args_description="[平台] [数量] - 如: /news zhihu 5"
)

command_factory.register_command(
    command="hotnews", 
    handler=hot_news_command,
    description="获取今日热门新闻汇总",
    permission=Permission.NONE,
    args_description="无需参数"
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


# 注册缓存清理命令
command_factory.register_command(
    "news_cleancache", 
    news_clean_cache_command, 
    permission=Permission.ADMIN, 
    description="清理新闻缓存"
)

logger.info("新闻命令模块已加载")