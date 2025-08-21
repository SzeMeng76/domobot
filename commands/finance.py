# commands/finance.py

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import yfinance as yf
import pandas as pd
from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown

from utils.command_factory import command_factory
from utils.config_manager import get_config, config_manager
from utils.formatter import foldable_text_v2, foldable_text_with_markdown_v2
from utils.message_manager import delete_user_command, send_error, send_success, send_message_with_auto_delete
from utils.permissions import Permission

logger = logging.getLogger(__name__)

# 全局变量
cache_manager = None
httpx_client = None

# 股票ID映射缓存
stock_id_mapping = {}
mapping_counter = 0

def set_dependencies(cm, hc=None):
    """初始化依赖"""
    global cache_manager, httpx_client
    cache_manager = cm
    if hc:
        httpx_client = hc
    else:
        from utils.http_client import get_http_client
        httpx_client = get_http_client()

async def _schedule_auto_delete(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, delay: int):
    """调度自动删除消息"""
    try:
        if context and hasattr(context, "bot_data"):
            scheduler = context.bot_data.get("message_delete_scheduler")
            if scheduler and hasattr(scheduler, "schedule_deletion"):
                await scheduler.schedule_deletion(chat_id, message_id, delay, None)
                logger.info(f"已调度金融消息删除: chat_id={chat_id}, message_id={message_id}, delay={delay}s")
            else:
                logger.warning(f"消息删除调度器未正确初始化: scheduler={scheduler}")
        else:
            logger.warning("无法获取bot_data或context")
    except Exception as e:
        logger.error(f"调度自动删除失败: {e}")

def get_short_stock_id(full_stock_id: str) -> str:
    """获取短股票ID用于callback_data"""
    global stock_id_mapping, mapping_counter
    
    for short_id, full_id in stock_id_mapping.items():
        if full_id == full_stock_id:
            return short_id
    
    mapping_counter += 1
    short_id = str(mapping_counter)
    stock_id_mapping[short_id] = full_stock_id
    
    if len(stock_id_mapping) > 1000:
        old_keys = list(stock_id_mapping.keys())[:100]
        for key in old_keys:
            del stock_id_mapping[key]
    
    return short_id

def get_full_stock_id(short_stock_id: str) -> Optional[str]:
    """根据短ID获取完整股票ID"""
    return stock_id_mapping.get(short_stock_id)

class FinanceService:
    """金融服务类"""
    
    def __init__(self):
        pass
        
    async def get_stock_info(self, symbol: str) -> Optional[Dict]:
        """获取单只股票信息"""
        cache_key = f"stock_info_{symbol.upper()}"
        
        if cache_manager:
            config = get_config()
            cached_data = await cache_manager.load_cache(
                cache_key, 
                max_age_seconds=config.finance_cache_duration,
                subdirectory="finance"
            )
            if cached_data:
                logger.info(f"使用缓存的股票数据: {symbol}")
                return cached_data
        
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            history = ticker.history(period="1d")
            
            if info and not history.empty:
                # 获取最新价格
                current_price = history['Close'].iloc[-1] if len(history) > 0 else info.get('currentPrice', 0)
                previous_close = info.get('previousClose', current_price)
                
                data = {
                    'symbol': symbol.upper(),
                    'name': info.get('longName', info.get('shortName', symbol.upper())),
                    'current_price': float(current_price),
                    'previous_close': float(previous_close),
                    'change': float(current_price - previous_close),
                    'change_percent': float((current_price - previous_close) / previous_close * 100) if previous_close != 0 else 0,
                    'volume': int(info.get('volume', 0)),
                    'market_cap': info.get('marketCap', 0),
                    'pe_ratio': info.get('trailingPE', 0),
                    'dividend_yield': info.get('dividendYield', 0),
                    'currency': info.get('currency', 'USD'),
                    'exchange': info.get('exchange', ''),
                    'timestamp': datetime.now().isoformat()
                }
                
                if cache_manager:
                    await cache_manager.save_cache(cache_key, data, subdirectory="finance")
                
                return data
                
        except Exception as e:
            logger.error(f"获取股票信息失败 {symbol}: {e}")
            return None
        
        return None
    
    async def get_trending_stocks(self, screener_type: str) -> List[Dict]:
        """获取趋势股票（排行榜）"""
        cache_key = f"trending_{screener_type}"
        
        if cache_manager:
            config = get_config()
            cached_data = await cache_manager.load_cache(
                cache_key, 
                max_age_seconds=config.finance_ranking_cache_duration,
                subdirectory="finance"
            )
            if cached_data:
                logger.info(f"使用缓存的排行榜数据: {screener_type}")
                return cached_data
        
        try:
            # 使用yfinance的预定义筛选器
            from yfinance.screener.screener import PREDEFINED_SCREENER_QUERIES, screen
            
            if screener_type not in PREDEFINED_SCREENER_QUERIES:
                return []
            
            # 获取筛选结果
            screener_data = screen(screener_type, count=10)
            results = []
            
            if screener_data and 'quotes' in screener_data:
                for quote in screener_data['quotes'][:10]:
                    try:
                        symbol = quote.get('symbol', '')
                        if symbol:
                            data = {
                                'symbol': symbol,
                                'name': quote.get('longName', quote.get('shortName', symbol)),
                                'current_price': float(quote.get('regularMarketPrice', 0)),
                                'change': float(quote.get('regularMarketChange', 0)),
                                'change_percent': float(quote.get('regularMarketChangePercent', 0)),
                                'volume': int(quote.get('regularMarketVolume', 0)),
                                'market_cap': quote.get('marketCap', 0)
                            }
                            results.append(data)
                    except (ValueError, TypeError) as e:
                        logger.warning(f"解析股票数据失败: {e}")
                        continue
            
            if cache_manager and results:
                await cache_manager.save_cache(cache_key, results, subdirectory="finance")
            
            return results
            
        except Exception as e:
            logger.error(f"获取排行榜失败 {screener_type}: {e}")
            return []
    
    async def search_stocks(self, query: str, limit: int = 10) -> List[Dict]:
        """搜索股票"""
        cache_key = f"search_{query.lower()}"
        
        if cache_manager:
            config = get_config()
            cached_data = await cache_manager.load_cache(
                cache_key, 
                max_age_seconds=config.finance_search_cache_duration,
                subdirectory="finance"
            )
            if cached_data:
                return cached_data
        
        try:
            from yfinance import Search
            search_obj = Search(query, max_results=limit)
            quotes = search_obj.quotes
            
            results = []
            for quote in quotes[:limit]:
                try:
                    data = {
                        'symbol': quote.get('symbol', ''),
                        'name': quote.get('longname', quote.get('shortname', '')),
                        'exchange': quote.get('exchange', ''),
                        'type': quote.get('quoteType', ''),
                    }
                    if data['symbol']:
                        results.append(data)
                except Exception as e:
                    logger.warning(f"解析搜索结果失败: {e}")
                    continue
            
            if cache_manager and results:
                await cache_manager.save_cache(cache_key, results, subdirectory="finance")
            
            return results
            
        except Exception as e:
            logger.error(f"搜索股票失败 {query}: {e}")
            return []

# 初始化服务实例
finance_service = FinanceService()

def format_stock_info(stock_data: Dict) -> str:
    """格式化股票信息"""
    name = stock_data.get('name', stock_data['symbol'])
    symbol = stock_data['symbol']
    price = stock_data['current_price']
    change = stock_data['change']
    change_percent = stock_data['change_percent']
    volume = stock_data['volume']
    currency = stock_data.get('currency', 'USD')
    exchange = stock_data.get('exchange', '')
    
    # 涨跌emoji
    trend_emoji = "📈" if change >= 0 else "📉"
    change_sign = "+" if change >= 0 else ""
    
    result = f"""📊 *{escape_markdown(symbol, version=2)} - {escape_markdown(name, version=2)}*

💰 当前价格: `{price:.2f} {currency}`
{trend_emoji} 涨跌: `{change_sign}{change:.2f} ({change_percent:+.2f}%)`
📊 成交量: `{volume:,}`"""

    if exchange:
        result += f"\n🏛️ 交易所: `{exchange}`"
    
    # 添加市值等信息
    if stock_data.get('market_cap'):
        market_cap = stock_data['market_cap']
        if market_cap > 1e12:
            cap_str = f"{market_cap/1e12:.1f}T"
        elif market_cap > 1e9:
            cap_str = f"{market_cap/1e9:.1f}B"
        elif market_cap > 1e6:
            cap_str = f"{market_cap/1e6:.1f}M"
        else:
            cap_str = f"{market_cap:,.0f}"
        result += f"\n💎 市值: `{cap_str} {currency}`"
    
    if stock_data.get('pe_ratio') and stock_data['pe_ratio'] > 0:
        result += f"\n📈 市盈率: `{stock_data['pe_ratio']:.2f}`"
    
    result += f"\n\n_更新时间: {datetime.now().strftime('%H:%M:%S')}_"
    
    return result

def format_ranking_list(stocks: List[Dict], title: str) -> str:
    """格式化排行榜"""
    if not stocks:
        return f"❌ {title} 数据获取失败"
    
    result = f"📋 *{escape_markdown(title, version=2)}*\n\n"
    
    for i, stock in enumerate(stocks[:10], 1):
        symbol = stock['symbol']
        name = stock.get('name', symbol)
        price = stock['current_price']
        change_percent = stock['change_percent']
        
        trend_emoji = "📈" if change_percent >= 0 else "📉"
        change_sign = "+" if change_percent >= 0 else ""
        
        # 截断过长的名称
        if len(name) > 20:
            name = name[:17] + "..."
        
        result += f"`{i:2d}.` {trend_emoji} *{escape_markdown(symbol, version=2)}* - {escape_markdown(name, version=2)}\n"
        result += f"     `${price:.2f}` `({change_sign}{change_percent:.2f}%)`\n\n"
    
    result += f"_更新时间: {datetime.now().strftime('%H:%M:%S')}_"
    return result

async def finance_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """金融数据主命令 /finance"""
    if not update.message:
        return
        
    # 如果有参数，直接搜索股票
    if context.args:
        query = " ".join(context.args)
        await _execute_stock_search(update, context, query)
        return
    
    # 没有参数，显示主菜单
    keyboard = [
        [
            InlineKeyboardButton("📊 查询股票", callback_data="finance_search"),
            InlineKeyboardButton("🔍 搜索股票", callback_data="finance_search_menu")
        ],
        [
            InlineKeyboardButton("📈 日涨幅榜", callback_data="finance_gainers"),
            InlineKeyboardButton("📉 日跌幅榜", callback_data="finance_losers")
        ],
        [
            InlineKeyboardButton("🔥 最活跃", callback_data="finance_actives"),
            InlineKeyboardButton("💎 小盘股涨幅", callback_data="finance_small_cap_gainers")
        ],
        [
            InlineKeyboardButton("🚀 成长科技股", callback_data="finance_growth_tech"),
            InlineKeyboardButton("💰 低估值大盘股", callback_data="finance_undervalued_large")
        ],
        [
            InlineKeyboardButton("❌ 关闭", callback_data="finance_close")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    help_text = """📊 金融数据查询

🔍 功能介绍:
• **查询股票**: 输入股票代码查看详细信息
• **搜索股票**: 按公司名称搜索
• **各种排行榜**: 涨幅榜、活跃股等

💡 快速使用:
`/finance AAPL` - 查询苹果股票
`/finance Tesla` - 搜索特斯拉

请选择功能:"""
    
    await send_message_with_auto_delete(
        context=context,
        chat_id=update.message.chat_id,
        text=foldable_text_with_markdown_v2(help_text),
        parse_mode="MarkdownV2",
        reply_markup=reply_markup
    )
    
    await delete_user_command(context, update.message.chat_id, update.message.message_id)

async def _execute_stock_search(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str, callback_query: CallbackQuery = None) -> None:
    """执行股票查询"""
    loading_message = f"🔍 正在查询 {query}... ⏳"
    
    if callback_query:
        await callback_query.edit_message_text(
            text=foldable_text_v2(loading_message),
            parse_mode="MarkdownV2"
        )
        message = callback_query.message
    else:
        message = await context.bot.send_message(
            chat_id=update.message.chat_id,
            text=foldable_text_v2(loading_message),
            parse_mode="MarkdownV2"
        )
    
    try:
        # 先尝试作为股票代码查询
        stock_data = await finance_service.get_stock_info(query)
        
        if stock_data:
            # 找到股票信息，直接显示
            result_text = format_stock_info(stock_data)
            
            # 添加返回主菜单按钮
            keyboard = [[InlineKeyboardButton("🔙 返回主菜单", callback_data="finance_main_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if callback_query:
                await callback_query.edit_message_text(
                    text=foldable_text_with_markdown_v2(result_text),
                    parse_mode="MarkdownV2",
                    reply_markup=reply_markup
                )
            else:
                await message.edit_text(
                    text=foldable_text_with_markdown_v2(result_text),
                    parse_mode="MarkdownV2",
                    reply_markup=reply_markup
                )
            
            # 调度自动删除
            config = get_config()
            await _schedule_auto_delete(context, message.chat_id, message.message_id, config.auto_delete_delay)
        else:
            # 没找到股票，尝试搜索
            search_results = await finance_service.search_stocks(query, limit=8)
            
            if search_results:
                # 显示搜索结果
                keyboard = []
                for result in search_results:
                    symbol = result['symbol']
                    name = result['name']
                    exchange = result.get('exchange', '')
                    
                    button_text = f"📊 {symbol}"
                    if name and name != symbol:
                        button_text += f" - {name[:20]}"
                    if exchange:
                        button_text += f" ({exchange})"
                    
                    short_id = get_short_stock_id(symbol)
                    keyboard.append([InlineKeyboardButton(button_text, callback_data=f"finance_stock_detail:{short_id}")])
                
                keyboard.append([InlineKeyboardButton("🔙 返回主菜单", callback_data="finance_main_menu")])
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                search_text = f"🔍 搜索结果: {query}\n\n请选择要查看的股票:"
                
                if callback_query:
                    await callback_query.edit_message_text(
                        text=foldable_text_with_markdown_v2(search_text),
                        parse_mode="MarkdownV2",
                        reply_markup=reply_markup
                    )
                else:
                    await message.edit_text(
                        text=foldable_text_with_markdown_v2(search_text),
                        parse_mode="MarkdownV2",
                        reply_markup=reply_markup
                    )
            else:
                # 没有找到任何结果
                error_text = f"❌ 未找到 '{query}' 相关的股票信息"
                keyboard = [[InlineKeyboardButton("🔙 返回主菜单", callback_data="finance_main_menu")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                if callback_query:
                    await callback_query.edit_message_text(
                        text=foldable_text_v2(error_text),
                        parse_mode="MarkdownV2",
                        reply_markup=reply_markup
                    )
                else:
                    await message.edit_text(
                        text=foldable_text_v2(error_text),
                        parse_mode="MarkdownV2",
                        reply_markup=reply_markup
                    )
                
                # 错误消息5秒后删除
                await _schedule_auto_delete(context, message.chat_id, message.message_id, 5)
                
    except Exception as e:
        logger.error(f"股票查询时发生错误: {e}", exc_info=True)
        error_text = f"❌ 查询时发生错误: {str(e)}"
        
        if callback_query:
            await callback_query.edit_message_text(
                text=foldable_text_v2(error_text),
                parse_mode="MarkdownV2"
            )
        else:
            await message.edit_text(
                text=foldable_text_v2(error_text),
                parse_mode="MarkdownV2"
            )

async def _execute_ranking(update: Update, context: ContextTypes.DEFAULT_TYPE, ranking_type: str, title: str, callback_query: CallbackQuery) -> None:
    """执行排行榜查询"""
    loading_message = f"📊 正在获取{title}... ⏳"
    await callback_query.edit_message_text(
        text=foldable_text_v2(loading_message),
        parse_mode="MarkdownV2"
    )
    
    try:
        stocks = await finance_service.get_trending_stocks(ranking_type)
        
        if stocks:
            result_text = format_ranking_list(stocks, title)
            
            # 创建按钮 - 允许查看个股详情和返回
            keyboard = []
            for i, stock in enumerate(stocks[:5]):  # 只显示前5个的详情按钮
                symbol = stock['symbol']
                short_id = get_short_stock_id(symbol)
                keyboard.append([InlineKeyboardButton(f"📊 {symbol} 详情", callback_data=f"finance_stock_detail:{short_id}")])
            
            # 添加刷新和返回按钮
            keyboard.append([
                InlineKeyboardButton("🔄 刷新", callback_data=f"finance_{ranking_type}"),
                InlineKeyboardButton("🔙 返回", callback_data="finance_main_menu")
            ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await callback_query.edit_message_text(
                text=foldable_text_with_markdown_v2(result_text),
                parse_mode="MarkdownV2",
                reply_markup=reply_markup
            )
        else:
            error_text = f"❌ 获取{title}失败，请稍后重试"
            keyboard = [[InlineKeyboardButton("🔙 返回主菜单", callback_data="finance_main_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await callback_query.edit_message_text(
                text=foldable_text_v2(error_text),
                parse_mode="MarkdownV2",
                reply_markup=reply_markup
            )
            
            # 错误消息5秒后删除
            await _schedule_auto_delete(context, callback_query.message.chat_id, callback_query.message.message_id, 5)
            
    except Exception as e:
        logger.error(f"获取{title}时发生错误: {e}", exc_info=True)
        error_text = f"❌ 获取{title}时发生错误: {str(e)}"
        
        await callback_query.edit_message_text(
            text=foldable_text_v2(error_text),
            parse_mode="MarkdownV2"
        )

# =============================================================================
# Callback 处理器
# =============================================================================

async def finance_main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """返回主菜单"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [
            InlineKeyboardButton("📊 查询股票", callback_data="finance_search"),
            InlineKeyboardButton("🔍 搜索股票", callback_data="finance_search_menu")
        ],
        [
            InlineKeyboardButton("📈 日涨幅榜", callback_data="finance_gainers"),
            InlineKeyboardButton("📉 日跌幅榜", callback_data="finance_losers")
        ],
        [
            InlineKeyboardButton("🔥 最活跃", callback_data="finance_actives"),
            InlineKeyboardButton("💎 小盘股涨幅", callback_data="finance_small_cap_gainers")
        ],
        [
            InlineKeyboardButton("🚀 成长科技股", callback_data="finance_growth_tech"),
            InlineKeyboardButton("💰 低估值大盘股", callback_data="finance_undervalued_large")
        ],
        [
            InlineKeyboardButton("❌ 关闭", callback_data="finance_close")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    help_text = """📊 金融数据查询

🔍 功能介绍:
• **查询股票**: 输入股票代码查看详细信息
• **搜索股票**: 按公司名称搜索
• **各种排行榜**: 涨幅榜、活跃股等

💡 快速使用:
`/finance AAPL` - 查询苹果股票
`/finance Tesla` - 搜索特斯拉

请选择功能:"""
    
    await query.edit_message_text(
        text=foldable_text_with_markdown_v2(help_text),
        parse_mode="MarkdownV2",
        reply_markup=reply_markup
    )

async def finance_search_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理查询股票按钮"""
    query = update.callback_query
    await query.answer("请在命令后输入股票代码，如: /finance AAPL")
    
    help_text = """🔍 股票查询说明

请使用以下格式查询股票:
`/finance [股票代码]`

**示例:**
• `/finance AAPL` - 查询苹果公司
• `/finance TSLA` - 查询特斯拉
• `/finance GOOGL` - 查询谷歌
• `/finance BABA` - 查询阿里巴巴

**支持的市场:**
• 美股 (NASDAQ, NYSE)
• 港股 (如 0700.HK)  
• A股 (如 000001.SZ)

请发送新消息进行查询"""

    keyboard = [[InlineKeyboardButton("🔙 返回主菜单", callback_data="finance_main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text=foldable_text_with_markdown_v2(help_text),
        parse_mode="MarkdownV2",
        reply_markup=reply_markup
    )

async def finance_stock_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理股票详情按钮点击"""
    query = update.callback_query
    await query.answer()
    
    if not query or not query.data:
        return
        
    try:
        callback_data = query.data
        if callback_data.startswith("finance_stock_detail:"):
            short_id = callback_data.replace("finance_stock_detail:", "")
            symbol = get_full_stock_id(short_id)
            if not symbol:
                await query.edit_message_text(
                    foldable_text_v2("❌ 股票信息已过期，请重新查询"),
                    parse_mode="MarkdownV2"
                )
                await _schedule_auto_delete(context, query.message.chat_id, query.message.message_id, 5)
                return
            
            # 执行股票查询
            await _execute_stock_search(update, context, symbol, query)
            
    except Exception as e:
        logger.error(f"处理股票详情回调时发生错误: {e}", exc_info=True)
        try:
            await query.edit_message_text(
                foldable_text_v2(f"❌ 处理请求时发生错误: {str(e)}"),
                parse_mode="MarkdownV2"
            )
        except:
            pass

# 排行榜回调处理器
async def finance_gainers_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """日涨幅榜"""
    query = update.callback_query
    await query.answer("正在获取日涨幅榜...")
    await _execute_ranking(update, context, "day_gainers", "日涨幅榜", query)

async def finance_losers_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """日跌幅榜"""
    query = update.callback_query
    await query.answer("正在获取日跌幅榜...")
    await _execute_ranking(update, context, "day_losers", "日跌幅榜", query)

async def finance_actives_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """最活跃股票"""
    query = update.callback_query
    await query.answer("正在获取最活跃股票...")
    await _execute_ranking(update, context, "most_actives", "最活跃股票", query)

async def finance_small_cap_gainers_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """小盘股涨幅榜"""
    query = update.callback_query
    await query.answer("正在获取小盘股涨幅榜...")
    await _execute_ranking(update, context, "small_cap_gainers", "小盘股涨幅榜", query)

async def finance_growth_tech_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """成长科技股"""
    query = update.callback_query
    await query.answer("正在获取成长科技股...")
    await _execute_ranking(update, context, "growth_technology_stocks", "成长科技股", query)

async def finance_undervalued_large_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """低估值大盘股"""
    query = update.callback_query
    await query.answer("正在获取低估值大盘股...")
    await _execute_ranking(update, context, "undervalued_large_caps", "低估值大盘股", query)

async def finance_close_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理关闭按钮点击"""
    query = update.callback_query
    await query.answer("消息已关闭")
    
    if not query:
        return
        
    try:
        await query.delete_message()
    except Exception as e:
        logger.error(f"删除消息时发生错误: {e}")
        try:
            await query.edit_message_text(
                text=foldable_text_v2("✅ 消息已关闭"),
                parse_mode="MarkdownV2"
            )
        except:
            pass

async def finance_clean_cache_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """清理金融模块缓存 /finance_cleancache"""
    if not update.message:
        return
        
    try:
        if cache_manager:
            await cache_manager.clear_cache(subdirectory="finance", key_prefix="stock_")
            await cache_manager.clear_cache(subdirectory="finance", key_prefix="trending_")
            await cache_manager.clear_cache(subdirectory="finance", key_prefix="search_")
            
        success_message = "✅ 金融模块缓存已清理"
        await send_success(context, update.message.chat_id, foldable_text_v2(success_message))
        
    except Exception as e:
        logger.error(f"清理金融缓存时发生错误: {e}", exc_info=True)
        error_message = f"❌ 清理金融缓存失败: {str(e)}"
        await send_error(context, update.message.chat_id, foldable_text_v2(error_message))
        
    await delete_user_command(context, update.message.chat_id, update.message.message_id)

# =============================================================================
# 注册命令和回调
# =============================================================================

# 注册主命令
command_factory.register_command(
    "finance",
    finance_command,
    permission=Permission.USER,
    description="金融数据查询 - 股票信息、排行榜等"
)

# 注册回调处理器
command_factory.register_callback(r"^finance_main_menu$", finance_main_menu_callback, permission=Permission.USER, description="金融主菜单")
command_factory.register_callback(r"^finance_search$", finance_search_callback, permission=Permission.USER, description="股票查询说明")
command_factory.register_callback(r"^finance_stock_detail:", finance_stock_detail_callback, permission=Permission.USER, description="股票详情")
command_factory.register_callback(r"^finance_gainers$", finance_gainers_callback, permission=Permission.USER, description="日涨幅榜")
command_factory.register_callback(r"^finance_losers$", finance_losers_callback, permission=Permission.USER, description="日跌幅榜")
command_factory.register_callback(r"^finance_actives$", finance_actives_callback, permission=Permission.USER, description="最活跃股票")
command_factory.register_callback(r"^finance_small_cap_gainers$", finance_small_cap_gainers_callback, permission=Permission.USER, description="小盘股涨幅榜")
command_factory.register_callback(r"^finance_growth_tech$", finance_growth_tech_callback, permission=Permission.USER, description="成长科技股")
command_factory.register_callback(r"^finance_undervalued_large$", finance_undervalued_large_callback, permission=Permission.USER, description="低估值大盘股")
command_factory.register_callback(r"^finance_close$", finance_close_callback, permission=Permission.USER, description="关闭金融消息")

# 已迁移到统一缓存管理命令 /cleancache
# command_factory.register_command("finance_cleancache", finance_clean_cache_command, permission=Permission.ADMIN, description="清理金融模块缓存")