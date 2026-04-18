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
from utils.formatter import foldable_text_v2, foldable_text_with_markdown_v2, format_with_markdown_v2
from utils.message_manager import delete_user_command, send_error, send_success, send_message_with_auto_delete
from utils.permissions import Permission
from utils.country_data import SUPPORTED_COUNTRIES

logger = logging.getLogger(__name__)

# 全局变量
cache_manager = None
httpx_client = None

# 股票ID映射缓存
stock_id_mapping = {}
mapping_counter = 0

def get_currency_symbol(currency_code: str) -> str:
    """根据货币代码获取货币符号"""
    # 先从country_data中查找
    for country_data in SUPPORTED_COUNTRIES.values():
        if country_data["currency"] == currency_code:
            return country_data["symbol"]
    
    # 常用货币符号映射
    currency_symbols = {
        'USD': '$', 'CNY': '¥', 'JPY': '¥', 'EUR': '€', 'GBP': '£',
        'HKD': 'HK$', 'MYR': 'RM', 'SGD': 'S$', 'TWD': 'NT$',
        'KRW': '₩', 'THB': '฿', 'CAD': 'C$', 'AUD': 'A$',
        'CHF': 'CHF', 'SEK': 'kr', 'NOK': 'kr', 'DKK': 'kr',
        'RUB': '₽', 'INR': '₹', 'BRL': 'R$', 'ZAR': 'R'
    }
    
    return currency_symbols.get(currency_code, currency_code)

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

def align_timezone(target_time: pd.Timestamp, reference_index: pd.DatetimeIndex) -> pd.Timestamp:
    """统一时区处理函数，避免时区比较错误"""
    try:
        if reference_index.tz is not None:
            # 如果参考索引有时区信息，将目标时间转换为相同时区
            if target_time.tz is None:
                target_time = target_time.tz_localize(reference_index.tz)
            else:
                target_time = target_time.tz_convert(reference_index.tz)
        else:
            # 如果参考索引没有时区信息，确保目标时间也没有时区
            if target_time.tz is not None:
                target_time = target_time.tz_localize(None)
        return target_time
    except Exception as e:
        logger.warning(f"时区处理失败，使用原始时间: {e}")
        # 如果时区处理失败，尝试去除时区信息
        try:
            return target_time.tz_localize(None) if target_time.tz is not None else target_time
        except:
            return target_time

class FinanceService:
    """金融服务类"""

    def __init__(self):
        pass

    async def get_earnings_calendar(self, days: int = 7, limit: int = 50) -> Optional[List[Dict]]:
        """获取财报日历 - 批量查看未来N天的公司财报"""
        cache_key = f"calendar_earnings_{days}_{limit}"

        if cache_manager:
            config = get_config()
            cached_data = await cache_manager.load_cache(
                cache_key,
                max_age_seconds=config.finance_cache_duration * 2,  # 财报日历缓存10分钟
                subdirectory="finance"
            )
            if cached_data:
                logger.info(f"使用缓存的财报日历数据: {days}天")
                return cached_data

        try:
            from yfinance import Calendars
            from datetime import timedelta

            start = datetime.now()
            end = start + timedelta(days=days)

            calendars = Calendars(start=start, end=end)
            df = calendars.get_earnings_calendar(limit=limit, filter_most_active=True)

            if df is None or df.empty:
                return None

            results = []
            for idx, row in df.iterrows():
                try:
                    event_date = row.get('Event Start Date')
                    if pd.notna(event_date):
                        data = {
                            'symbol': str(idx),
                            'company': str(row.get('Company', idx))[:30],  # 限制长度
                            'date': event_date.strftime('%Y-%m-%d') if hasattr(event_date, 'strftime') else str(event_date),
                            'time': str(row.get('Timing', '')) if pd.notna(row.get('Timing')) else '',
                            'eps_estimate': float(row.get('EPS Estimate')) if pd.notna(row.get('EPS Estimate')) else None,
                            'eps_actual': float(row.get('Reported EPS')) if pd.notna(row.get('Reported EPS')) else None,
                            'surprise_pct': float(row.get('Surprise(%)')) if pd.notna(row.get('Surprise(%)')) else None,
                            'marketcap': int(row.get('Marketcap', 0)) if pd.notna(row.get('Marketcap')) else 0
                        }
                        results.append(data)
                except Exception as e:
                    logger.warning(f"解析财报日历数据失败 {idx}: {e}")
                    continue

            if cache_manager and results:
                await cache_manager.save_cache(cache_key, results, subdirectory="finance")

            return results if results else None

        except Exception as e:
            logger.error(f"获取财报日历失败: {e}", exc_info=True)
            return None

    async def get_ipo_calendar(self, days: int = 30, limit: int = 50) -> Optional[List[Dict]]:
        """获取IPO日历 - 新股上市信息"""
        cache_key = f"calendar_ipo_{days}_{limit}"

        if cache_manager:
            config = get_config()
            cached_data = await cache_manager.load_cache(
                cache_key,
                max_age_seconds=config.finance_cache_duration * 6,  # IPO日历缓存30分钟
                subdirectory="finance"
            )
            if cached_data:
                logger.info(f"使用缓存的IPO日历数据: {days}天")
                return cached_data

        try:
            from yfinance import Calendars
            from datetime import timedelta

            start = datetime.now()
            end = start + timedelta(days=days)

            calendars = Calendars(start=start, end=end)
            df = calendars.get_ipo_info_calendar(limit=limit)

            if df is None or df.empty:
                return None

            results = []
            for idx, row in df.iterrows():
                try:
                    ipo_date = row.get('Date')
                    data = {
                        'symbol': str(idx),
                        'company': str(row.get('Company Name', idx))[:30],
                        'exchange': str(row.get('Exchange', '')) if pd.notna(row.get('Exchange')) else '',
                        'date': ipo_date.strftime('%Y-%m-%d') if pd.notna(ipo_date) and hasattr(ipo_date, 'strftime') else '',
                        'filing_date': row.get('Filing Date').strftime('%Y-%m-%d') if pd.notna(row.get('Filing Date')) and hasattr(row.get('Filing Date'), 'strftime') else '',
                        'price_from': float(row.get('Price From')) if pd.notna(row.get('Price From')) else None,
                        'price_to': float(row.get('Price To')) if pd.notna(row.get('Price To')) else None,
                        'price': float(row.get('Price')) if pd.notna(row.get('Price')) else None,
                        'shares': int(row.get('Shares')) if pd.notna(row.get('Shares')) else None,
                        'currency': str(row.get('Currency', 'USD')) if pd.notna(row.get('Currency')) else 'USD',
                        'deal_type': str(row.get('Deal Type', '')) if pd.notna(row.get('Deal Type')) else ''
                    }
                    results.append(data)
                except Exception as e:
                    logger.warning(f"解析IPO日历数据失败 {idx}: {e}")
                    continue

            if cache_manager and results:
                await cache_manager.save_cache(cache_key, results, subdirectory="finance")

            return results if results else None

        except Exception as e:
            logger.error(f"获取IPO日历失败: {e}", exc_info=True)
            return None

    async def get_economic_events_calendar(self, days: int = 7, limit: int = 50) -> Optional[List[Dict]]:
        """获取经济事件日历 - 宏观经济数据发布"""
        cache_key = f"calendar_economic_{days}_{limit}"

        if cache_manager:
            config = get_config()
            cached_data = await cache_manager.load_cache(
                cache_key,
                max_age_seconds=config.finance_cache_duration * 4,  # 经济事件日历缓存20分钟
                subdirectory="finance"
            )
            if cached_data:
                logger.info(f"使用缓存的经济事件日历数据: {days}天")
                return cached_data

        try:
            from yfinance import Calendars
            from datetime import timedelta

            start = datetime.now()
            end = start + timedelta(days=days)

            calendars = Calendars(start=start, end=end)
            df = calendars.get_economic_events_calendar(limit=limit)

            if df is None or df.empty:
                return None

            results = []
            for idx, row in df.iterrows():
                try:
                    event_time = row.get('Event Time')
                    data = {
                        'event': str(idx),
                        'region': str(row.get('Region', '')) if pd.notna(row.get('Region')) else '',
                        'time': event_time.strftime('%Y-%m-%d %H:%M') if pd.notna(event_time) and hasattr(event_time, 'strftime') else str(event_time) if pd.notna(event_time) else '',
                        'period': str(row.get('For', '')) if pd.notna(row.get('For')) else '',
                        'actual': float(row.get('Actual')) if pd.notna(row.get('Actual')) else None,
                        'expected': float(row.get('Expected')) if pd.notna(row.get('Expected')) else None,
                        'last': float(row.get('Last')) if pd.notna(row.get('Last')) else None,
                        'revised': float(row.get('Revised')) if pd.notna(row.get('Revised')) else None
                    }
                    results.append(data)
                except Exception as e:
                    logger.warning(f"解析经济事件日历数据失败 {idx}: {e}")
                    continue

            if cache_manager and results:
                await cache_manager.save_cache(cache_key, results, subdirectory="finance")

            return results if results else None

        except Exception as e:
            logger.error(f"获取经济事件日历失败: {e}", exc_info=True)
            return None

    async def get_splits_calendar(self, days: int = 30, limit: int = 50) -> Optional[List[Dict]]:
        """获取拆股日历 - 批量查看拆股事件"""
        cache_key = f"calendar_splits_{days}_{limit}"

        if cache_manager:
            config = get_config()
            cached_data = await cache_manager.load_cache(
                cache_key,
                max_age_seconds=config.finance_cache_duration * 6,  # 拆股日历缓存30分钟
                subdirectory="finance"
            )
            if cached_data:
                logger.info(f"使用缓存的拆股日历数据: {days}天")
                return cached_data

        try:
            from yfinance import Calendars
            from datetime import timedelta

            start = datetime.now()
            end = start + timedelta(days=days)

            calendars = Calendars(start=start, end=end)
            df = calendars.get_splits_calendar(limit=limit)

            if df is None or df.empty:
                return None

            results = []
            for idx, row in df.iterrows():
                try:
                    split_date = row.get('Payable On')
                    old_share = float(row.get('Old Shares')) if pd.notna(row.get('Old Shares')) else 1
                    new_share = float(row.get('New Shares')) if pd.notna(row.get('New Shares')) else 1

                    # 计算拆股比例文本
                    if new_share > old_share:
                        ratio_text = f"{int(new_share)}:{int(old_share)}"
                    else:
                        ratio_text = f"{int(old_share)}:{int(new_share)}"

                    data = {
                        'symbol': str(idx),
                        'company': str(row.get('Company Name', idx))[:30],
                        'date': split_date.strftime('%Y-%m-%d') if pd.notna(split_date) and hasattr(split_date, 'strftime') else str(split_date) if pd.notna(split_date) else '',
                        'old_shares': old_share,
                        'new_shares': new_share,
                        'ratio': new_share / old_share if old_share != 0 else 1,
                        'ratio_text': ratio_text,
                        'optionable': str(row.get('Optionable', '')) if pd.notna(row.get('Optionable')) else ''
                    }
                    results.append(data)
                except Exception as e:
                    logger.warning(f"解析拆股日历数据失败 {idx}: {e}")
                    continue

            if cache_manager and results:
                await cache_manager.save_cache(cache_key, results, subdirectory="finance")

            return results if results else None

        except Exception as e:
            logger.error(f"获取拆股日历失败: {e}", exc_info=True)
            return None
        
    async def get_stock_info(self, symbol: str, repair: bool = False) -> Optional[Dict]:
        """获取单只股票信息 - 支持数据修复和元数据获取

        Args:
            symbol: 股票代码
            repair: 是否启用数据修复（修复价格异常和货币转换）
        """
        cache_key = f"stock_info_{symbol.upper()}_r{int(repair)}"

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

            # 增强错误处理：检查info是否有效
            info = ticker.info
            if not info or not isinstance(info, dict):
                logger.warning(f"股票 {symbol} 返回空的info数据")
                return None

            # 使用repair参数修复数据质量
            history = ticker.history(period="1d", actions=True, repair=repair)

            # 获取历史元数据（包含时区、交易时段等信息）
            try:
                metadata = ticker.get_history_metadata()
            except Exception as e:
                logger.debug(f"获取历史元数据失败 {symbol}: {e}")
                metadata = {}

            # 获取最新价格 - 优先使用历史数据，其次使用info数据
            if not history.empty:
                current_price = history['Close'].iloc[-1]
                previous_close = info.get('previousClose', current_price)
            else:
                # 历史数据为空时，从info获取价格信息
                current_price = info.get('currentPrice') or info.get('regularMarketPrice') or 0
                previous_close = info.get('previousClose') or info.get('regularMarketPreviousClose', current_price)

            # 如果仍然没有价格信息，跳过这只股票
            if current_price == 0:
                logger.warning(f"股票 {symbol} 没有有效的价格数据 - 可能已退市或暂停交易")
                return None

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
                'timezone': metadata.get('timezone'),
                'exchange_timezone': metadata.get('exchangeTimezoneName'),
                'timestamp': datetime.now().isoformat()
            }

            if cache_manager:
                await cache_manager.save_cache(cache_key, data, subdirectory="finance")

            return data
                
        except Exception as e:
            logger.error(f"获取股票信息失败 {symbol}: {e}", exc_info=True)
            # 利用0.2.66改进的异常信息提供更具体的错误提示
            error_msg = str(e).lower()
            if "rate limit" in error_msg or "too many requests" in error_msg:
                logger.warning(f"股票 {symbol} 查询触发频率限制")
                return {"error": "rate_limit", "message": "访问频率过高，请稍后重试"}
            elif "not found" in error_msg or "no data found" in error_msg:
                logger.warning(f"股票 {symbol} 数据不存在")
                return {"error": "not_found", "message": "股票代码不存在或已退市"}
            elif "unauthorized" in error_msg or "403" in error_msg:
                logger.warning(f"股票 {symbol} 访问被拒绝")
                return {"error": "unauthorized", "message": "访问被拒绝，请稍后重试"}
            elif "timeout" in error_msg or "connection" in error_msg:
                logger.warning(f"股票 {symbol} 网络超时")
                return {"error": "timeout", "message": "网络超时，请检查网络连接"}
            else:
                logger.error(f"股票 {symbol} 未知错误: {e}")
                return {"error": "unknown", "message": f"获取数据时发生错误: {str(e)[:100]}"}
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
            # 使用yfinance的预定义筛选器，利用0.2.66新增的瑞士交易所支持
            from yfinance.screener.screener import PREDEFINED_SCREENER_QUERIES, screen

            if screener_type not in PREDEFINED_SCREENER_QUERIES:
                return []

            # 获取筛选结果，支持更多交易所包括瑞士
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
                                'market_cap': quote.get('marketCap', 0),
                                'currency': quote.get('currency', 'USD')
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
    
    async def get_analyst_recommendations(self, symbol: str) -> Optional[Dict]:
        """获取分析师评级 - 支持货币信息和评级变化"""
        cache_key = f"analyst_{symbol.upper()}"

        if cache_manager:
            config = get_config()
            cached_data = await cache_manager.load_cache(
                cache_key,
                max_age_seconds=config.finance_cache_duration * 2,  # 分析师数据缓存10分钟
                subdirectory="finance"
            )
            if cached_data:
                return cached_data

        try:
            ticker = yf.Ticker(symbol)

            # 获取分析师评级汇总
            recommendations_summary = ticker.recommendations_summary
            # 获取目标价
            price_targets = ticker.analyst_price_targets

            # 获取earnings_estimate（现在包含currency列）
            try:
                earnings_estimate = ticker.earnings_estimate
                estimate_currency = None
                if earnings_estimate is not None and not earnings_estimate.empty and 'currency' in earnings_estimate.columns:
                    estimate_currency = earnings_estimate['currency'].iloc[0] if len(earnings_estimate) > 0 else None
            except Exception as e:
                logger.debug(f"获取earnings_estimate失败 {symbol}: {e}")
                estimate_currency = None

            if recommendations_summary is not None and not recommendations_summary.empty:
                latest_summary = recommendations_summary.iloc[0]  # 最新的评级汇总

                data = {
                    'symbol': symbol.upper(),
                    'strong_buy': int(latest_summary.get('strongBuy', 0)),
                    'buy': int(latest_summary.get('buy', 0)),
                    'hold': int(latest_summary.get('hold', 0)),
                    'sell': int(latest_summary.get('sell', 0)),
                    'strong_sell': int(latest_summary.get('strongSell', 0)),
                    'period': latest_summary.name.strftime('%Y-%m-%d') if hasattr(latest_summary.name, 'strftime') else str(latest_summary.name),
                    'estimate_currency': estimate_currency,  # 新增：估值货币
                    'timestamp': datetime.now().isoformat()
                }

                # 添加目标价信息
                if price_targets and len(price_targets) > 0:
                    data.update({
                        'target_price_mean': float(price_targets.get('targetMeanPrice', 0)),
                        'target_price_high': float(price_targets.get('targetHighPrice', 0)),
                        'target_price_low': float(price_targets.get('targetLowPrice', 0)),
                        'num_analysts': int(price_targets.get('numberOfAnalystOpinions', 0))
                    })

                if cache_manager:
                    await cache_manager.save_cache(cache_key, data, subdirectory="finance")

                return data

        except Exception as e:
            logger.error(f"获取分析师评级失败 {symbol}: {e}")
            return None

        return None

    async def get_valuation_measures(self, symbol: str) -> Optional[Dict]:
        """获取估值指标"""
        cache_key = f"valuation_{symbol.upper()}"

        if cache_manager:
            config = get_config()
            cached_data = await cache_manager.load_cache(
                cache_key,
                max_age_seconds=config.finance_cache_duration * 2,
                subdirectory="finance"
            )
            if cached_data:
                return cached_data

        try:
            ticker = yf.Ticker(symbol)
            valuation_data = ticker.valuation

            if valuation_data is not None and not valuation_data.empty:
                data = {
                    'symbol': symbol.upper(),
                    'measures': valuation_data,
                    'timestamp': datetime.now().isoformat()
                }

                if cache_manager:
                    await cache_manager.save_cache(cache_key, data, subdirectory="finance")

                return data

        except Exception as e:
            logger.error(f"获取估值指标失败 {symbol}: {e}")
            return None

        return None

    async def get_earnings_dates(self, symbol: str) -> Optional[Dict]:
        """获取财报日期 - 利用0.2.66修复的earnings_dates功能"""
        cache_key = f"earnings_dates_{symbol.upper()}"

        if cache_manager:
            config = get_config()
            cached_data = await cache_manager.load_cache(
                cache_key,
                max_age_seconds=config.finance_cache_duration * 6,  # 财报日期缓存30分钟
                subdirectory="finance"
            )
            if cached_data:
                logger.info(f"使用缓存的财报日期数据: {symbol}")
                return cached_data

        try:
            ticker = yf.Ticker(symbol)

            # 获取财报日期 - 利用0.2.66的修复
            earnings_dates = ticker.earnings_dates

            if earnings_dates is not None and not earnings_dates.empty:
                # 获取未来几个财报日期，处理时区问题
                current_time = pd.Timestamp.now()

                # 统一时区处理
                current_time = align_timezone(current_time, earnings_dates.index)

                future_earnings = earnings_dates[earnings_dates.index >= current_time]
                past_earnings = earnings_dates[earnings_dates.index < current_time]

                # 获取货币信息
                info = ticker.info
                currency = info.get('currency', 'USD') if info else 'USD'

                data = {
                    'symbol': symbol.upper(),
                    'currency': currency,
                    'next_earnings': None,
                    'upcoming_earnings': [],
                    'recent_earnings': [],
                    'timestamp': datetime.now().isoformat()
                }

                # 下一个财报日期
                if not future_earnings.empty:
                    next_date = future_earnings.index[0]
                    data['next_earnings'] = {
                        'date': next_date.strftime('%Y-%m-%d'),
                        'eps_estimate': float(future_earnings.iloc[0].get('EPS Estimate', 0)) if 'EPS Estimate' in future_earnings.columns else None,
                        'reported_eps': float(future_earnings.iloc[0].get('Reported EPS', 0)) if 'Reported EPS' in future_earnings.columns else None
                    }

                # 即将到来的财报（未来4个）
                for i, (date, row) in enumerate(future_earnings.head(4).iterrows()):
                    earning_info = {
                        'date': date.strftime('%Y-%m-%d'),
                        'eps_estimate': float(row.get('EPS Estimate', 0)) if 'EPS Estimate' in row and pd.notna(row.get('EPS Estimate')) else None,
                        'reported_eps': float(row.get('Reported EPS', 0)) if 'Reported EPS' in row and pd.notna(row.get('Reported EPS')) else None
                    }
                    data['upcoming_earnings'].append(earning_info)

                # 最近的财报（过去4个）
                for i, (date, row) in enumerate(past_earnings.head(4).iterrows()):
                    earning_info = {
                        'date': date.strftime('%Y-%m-%d'),
                        'eps_estimate': float(row.get('EPS Estimate', 0)) if 'EPS Estimate' in row and pd.notna(row.get('EPS Estimate')) else None,
                        'reported_eps': float(row.get('Reported EPS', 0)) if 'Reported EPS' in row and pd.notna(row.get('Reported EPS')) else None,
                        'surprise': float(row.get('Surprise(%)', 0)) if 'Surprise(%)' in row and pd.notna(row.get('Surprise(%)')) else None
                    }
                    data['recent_earnings'].append(earning_info)

                if cache_manager:
                    await cache_manager.save_cache(cache_key, data, subdirectory="finance")

                return data

        except Exception as e:
            logger.error(f"获取财报日期失败 {symbol}: {e}", exc_info=True)
            return None

        return None

    async def get_dividends_splits(self, symbol: str, repair: bool = False) -> Optional[Dict]:
        """获取分红和拆股信息 - 支持外汇信息和数据修复

        Args:
            symbol: 股票代码
            repair: 是否启用数据修复（自动进行货币转换）
        """
        cache_key = f"dividends_splits_{symbol.upper()}_r{int(repair)}"

        if cache_manager:
            config = get_config()
            cached_data = await cache_manager.load_cache(
                cache_key,
                max_age_seconds=config.finance_cache_duration * 4,  # 分红拆股数据缓存20分钟
                subdirectory="finance"
            )
            if cached_data:
                logger.info(f"使用缓存的分红拆股数据: {symbol}")
                return cached_data

        try:
            ticker = yf.Ticker(symbol)

            # 使用get_actions()获取完整的分红信息（包括货币）
            actions = None
            dividend_fx = None
            try:
                actions = ticker.get_actions()
                # 检查是否有Dividends FX列（跨币种分红）
                if actions is not None and 'Dividends FX' in actions.columns:
                    fx_values = actions['Dividends FX'].dropna()
                    if not fx_values.empty:
                        dividend_fx = fx_values.iloc[0]  # 第一个非空的货币代码
                        logger.info(f"检测到 {symbol} 的分红外汇信息: {dividend_fx}")
            except Exception as e:
                logger.debug(f"获取actions失败 {symbol}: {e}")

            # 使用repair参数，自动进行货币转换
            dividends = ticker.get_dividends(period="max", repair=repair)
            splits = ticker.get_splits(period="max", repair=repair)

            # 获取货币信息
            info = ticker.info
            if not info or not isinstance(info, dict):
                logger.warning(f"股票 {symbol} 返回空的info数据")
                currency = 'USD'
            else:
                currency = info.get('currency', 'USD')

            data = {
                'symbol': symbol.upper(),
                'currency': currency,
                'dividend_currency': dividend_fx,  # 新增：分红货币（如果不同）
                'recent_dividends': [],
                'recent_splits': [],
                'dividend_yield': 0,
                'annual_dividend': 0,
                'timestamp': datetime.now().isoformat()
            }

            # 处理分红数据
            if dividends is not None and not dividends.empty:
                # 获取最近12个月的分红，处理时区问题
                current_time = pd.Timestamp.now()
                one_year_ago = current_time - pd.DateOffset(months=12)

                # 统一时区处理
                one_year_ago = align_timezone(one_year_ago, dividends.index)

                recent_dividends = dividends[dividends.index >= one_year_ago]

                for date, dividend in recent_dividends.tail(10).items():  # 最近10次分红
                    dividend_info = {
                        'date': date.strftime('%Y-%m-%d'),
                        'amount': float(dividend),
                        'type': 'regular'  # 可以根据需要扩展为特殊分红类型
                    }
                    data['recent_dividends'].append(dividend_info)

                # 计算年度分红和分红收益率
                if not recent_dividends.empty:
                    annual_dividend = float(recent_dividends.sum())
                    data['annual_dividend'] = annual_dividend

                    # 从已获取的info中获取分红收益率
                    if info and 'dividendYield' in info and info['dividendYield']:
                        data['dividend_yield'] = float(info['dividendYield'])  # 直接使用原始值

            # 处理拆股数据
            if splits is not None and not splits.empty:
                # 获取最近5年的拆股，处理时区问题
                current_time = pd.Timestamp.now()
                five_years_ago = current_time - pd.DateOffset(years=5)

                # 统一时区处理
                five_years_ago = align_timezone(five_years_ago, splits.index)

                recent_splits = splits[splits.index >= five_years_ago]

                for date, split_ratio in recent_splits.tail(10).items():  # 最近10次拆股
                    split_info = {
                        'date': date.strftime('%Y-%m-%d'),
                        'ratio': float(split_ratio),
                        'ratio_text': f"1:{int(split_ratio)}" if split_ratio > 1 else f"{int(1/split_ratio)}:1"
                    }
                    data['recent_splits'].append(split_info)

            # 如果没有任何数据，返回None
            if not data['recent_dividends'] and not data['recent_splits']:
                return None

            if cache_manager:
                await cache_manager.save_cache(cache_key, data, subdirectory="finance")

            return data

        except Exception as e:
            logger.error(f"获取分红拆股信息失败 {symbol}: {e}", exc_info=True)
            return None

        return None

    async def get_stock_quick_info(self, symbol: str) -> Optional[Dict]:
        """快速获取股票基本信息（性能优化版本）- 使用fast_info"""
        cache_key = f"stock_quick_{symbol.upper()}"

        if cache_manager:
            config = get_config()
            cached_data = await cache_manager.load_cache(
                cache_key,
                max_age_seconds=config.finance_cache_duration // 2,  # 快速信息缓存更短
                subdirectory="finance"
            )
            if cached_data:
                logger.info(f"使用缓存的快速股票数据: {symbol}")
                return cached_data

        try:
            ticker = yf.Ticker(symbol)
            fast_info = ticker.fast_info

            data = {
                'symbol': symbol.upper(),
                'current_price': float(fast_info.last_price) if hasattr(fast_info, 'last_price') else 0,
                'previous_close': float(fast_info.previous_close) if hasattr(fast_info, 'previous_close') else 0,
                'market_cap': int(fast_info.market_cap) if hasattr(fast_info, 'market_cap') else 0,
                'currency': fast_info.currency if hasattr(fast_info, 'currency') else 'USD',
                'timezone': fast_info.timezone if hasattr(fast_info, 'timezone') else None,
                'timestamp': datetime.now().isoformat()
            }

            # 计算涨跌
            if data['current_price'] and data['previous_close']:
                data['change'] = data['current_price'] - data['previous_close']
                data['change_percent'] = (data['change'] / data['previous_close'] * 100) if data['previous_close'] != 0 else 0

            if cache_manager:
                await cache_manager.save_cache(cache_key, data, subdirectory="finance")

            return data

        except Exception as e:
            logger.error(f"快速获取股票信息失败 {symbol}: {e}")
            return None

    async def get_analyst_upgrades_downgrades(self, symbol: str) -> Optional[Dict]:
        """获取分析师评级变化（升级/降级）"""
        cache_key = f"upgrades_downgrades_{symbol.upper()}"

        if cache_manager:
            config = get_config()
            cached_data = await cache_manager.load_cache(
                cache_key,
                max_age_seconds=config.finance_cache_duration * 6,  # 评级变化缓存30分钟
                subdirectory="finance"
            )
            if cached_data:
                return cached_data

        try:
            ticker = yf.Ticker(symbol)
            upgrades_downgrades = ticker.get_upgrades_downgrades()

            if upgrades_downgrades is not None and not upgrades_downgrades.empty:
                recent = upgrades_downgrades.head(15)  # 最近15条
                data = {
                    'symbol': symbol.upper(),
                    'changes': [],
                    'timestamp': datetime.now().isoformat()
                }

                for date, row in recent.iterrows():
                    change_info = {
                        'date': date.strftime('%Y-%m-%d') if hasattr(date, 'strftime') else str(date),
                        'firm': str(row.get('firm', '')) if pd.notna(row.get('firm')) else '',
                        'to_grade': str(row.get('toGrade', '')) if pd.notna(row.get('toGrade')) else '',
                        'from_grade': str(row.get('fromGrade', '')) if pd.notna(row.get('fromGrade')) else '',
                        'action': str(row.get('action', '')) if pd.notna(row.get('action')) else ''
                    }
                    data['changes'].append(change_info)

                if cache_manager:
                    await cache_manager.save_cache(cache_key, data, subdirectory="finance")

                return data

        except Exception as e:
            logger.error(f"获取评级变化失败 {symbol}: {e}")
            return None

        return None

    async def get_financial_statements(self, symbol: str, statement_type: str = "income") -> Optional[Dict]:
        """获取财务报表"""
        cache_key = f"financial_{statement_type}_{symbol.upper()}"
        
        if cache_manager:
            config = get_config()
            cached_data = await cache_manager.load_cache(
                cache_key, 
                max_age_seconds=config.finance_cache_duration * 12,  # 财务数据缓存1小时
                subdirectory="finance"
            )
            if cached_data:
                return cached_data
        
        try:
            ticker = yf.Ticker(symbol)
            
            # 获取股票基本信息以获取货币
            info = ticker.info
            currency = info.get('currency', 'USD') if info else 'USD'
            financial_currency = info.get('financialCurrency', currency) if info else currency
            
            if statement_type == "income":
                df = ticker.income_stmt
                title = "损益表"
            elif statement_type == "balance":
                df = ticker.balance_sheet  
                title = "资产负债表"
            elif statement_type == "cashflow":
                df = ticker.cash_flow
                title = "现金流量表"
            else:
                return None
            
            if df is not None and not df.empty:
                # 获取最新年度数据（第一列）
                latest_year = df.columns[0]
                latest_data = df.iloc[:, 0]
                
                # 选择关键指标进行展示
                if statement_type == "income":
                    key_items = [
                        'Total Revenue', 'Gross Profit', 'Operating Income', 
                        'Net Income', 'Basic EPS', 'Diluted EPS'
                    ]
                elif statement_type == "balance":
                    key_items = [
                        'Total Assets', 'Total Liabilities Net Minority Interest',
                        'Stockholders Equity', 'Cash And Cash Equivalents',
                        'Total Debt', 'Working Capital'
                    ]
                elif statement_type == "cashflow":
                    key_items = [
                        'Operating Cash Flow', 'Investing Cash Flow', 
                        'Financing Cash Flow', 'Free Cash Flow'
                    ]
                
                # 提取关键数据
                financial_data = {}
                for item in key_items:
                    if item in latest_data.index:
                        value = latest_data[item]
                        if pd.notna(value):
                            financial_data[item] = float(value)
                
                data = {
                    'symbol': symbol.upper(),
                    'statement_type': statement_type,
                    'title': title,
                    'period': latest_year.strftime('%Y-%m-%d') if hasattr(latest_year, 'strftime') else str(latest_year),
                    'data': financial_data,
                    'currency': financial_currency,
                    'timestamp': datetime.now().isoformat()
                }
                
                if cache_manager:
                    await cache_manager.save_cache(cache_key, data, subdirectory="finance")
                
                return data
                
        except Exception as e:
            logger.error(f"获取财务报表失败 {symbol} {statement_type}: {e}")
            return None
        
        return None

# 初始化服务实例
finance_service = FinanceService()

def format_stock_info(stock_data: Dict) -> str:
    """格式化股票信息"""
    # 检查是否为错误信息
    if stock_data.get('error'):
        error_type = stock_data['error']
        message = stock_data.get('message', '未知错误')

        error_emojis = {
            'rate_limit': '⏰',
            'not_found': '❌',
            'unauthorized': '🔒',
            'timeout': '🌐',
            'unknown': '⚠️'
        }

        emoji = error_emojis.get(error_type, '❌')
        return f"{emoji} **错误:** {message}"

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
    
    result = f"""📊 *{symbol} - {name}*

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

def format_analyst_recommendations(recommendation_data: Dict) -> str:
    """格式化分析师评级"""
    symbol = recommendation_data['symbol']
    strong_buy = recommendation_data.get('strong_buy', 0)
    buy = recommendation_data.get('buy', 0) 
    hold = recommendation_data.get('hold', 0)
    sell = recommendation_data.get('sell', 0)
    strong_sell = recommendation_data.get('strong_sell', 0)
    
    total = strong_buy + buy + hold + sell + strong_sell
    
    result = f"🎯 *{symbol} 分析师评级*\n\n"
    
    if total > 0:
        # 评级分布
        result += "📊 *评级分布:*\n"
        result += f"🚀 强烈买入: `{strong_buy}` ({strong_buy/total*100:.1f}%)\n"  
        result += f"📈 买入: `{buy}` ({buy/total*100:.1f}%)\n"
        result += f"⚖️ 持有: `{hold}` ({hold/total*100:.1f}%)\n"
        result += f"📉 卖出: `{sell}` ({sell/total*100:.1f}%)\n"
        result += f"🔻 强烈卖出: `{strong_sell}` ({strong_sell/total*100:.1f}%)\n\n"
        
        # 整体倾向
        bullish = strong_buy + buy
        bearish = sell + strong_sell
        if bullish > bearish:
            sentiment = "🟢 看涨"
        elif bearish > bullish:
            sentiment = "🔴 看跌" 
        else:
            sentiment = "🟡 中性"
        
        result += f"📊 整体倾向: {sentiment} `({bullish}买 vs {bearish}卖)`\n\n"
    
    # 目标价信息
    if 'target_price_mean' in recommendation_data and recommendation_data['target_price_mean'] > 0:
        mean_price = recommendation_data['target_price_mean']
        high_price = recommendation_data.get('target_price_high', 0)
        low_price = recommendation_data.get('target_price_low', 0)  
        num_analysts = recommendation_data.get('num_analysts', 0)
        
        result += "🎯 *目标价 (基于{num_analysts}位分析师):*\n".format(num_analysts=num_analysts)
        result += f"📊 平均目标价: `${mean_price:.2f}`\n"
        if high_price > 0:
            result += f"📈 最高目标价: `${high_price:.2f}`\n"
        if low_price > 0:
            result += f"📉 最低目标价: `${low_price:.2f}`\n"
    
    result += f"\n_更新时间: {datetime.now().strftime('%H:%M:%S')}_"
    return result

def format_financial_statement(financial_data: Dict) -> str:
    """格式化财务报表"""
    symbol = financial_data['symbol']
    title = financial_data['title'] 
    period = financial_data['period']
    data = financial_data['data']
    currency = financial_data.get('currency', 'USD')
    currency_symbol = get_currency_symbol(currency)
    
    result = f"📋 *{symbol} {title}*\n"
    result += f"📅 报告期: `{period}`\n\n"
    
    if not data:
        return result + "❌ 暂无财务数据"
    
    # 格式化不同类型的财务数据
    statement_type = financial_data['statement_type']
    
    if statement_type == "income":
        # 损益表关键指标
        if 'Total Revenue' in data:
            result += f"💰 总营收: `{currency_symbol}{data['Total Revenue']:,.0f}`\n"
        if 'Gross Profit' in data:
            result += f"💵 毛利润: `{currency_symbol}{data['Gross Profit']:,.0f}`\n"  
        if 'Operating Income' in data:
            result += f"⚙️ 营业利润: `{currency_symbol}{data['Operating Income']:,.0f}`\n"
        if 'Net Income' in data:
            result += f"💎 净利润: `{currency_symbol}{data['Net Income']:,.0f}`\n"
        if 'Basic EPS' in data:
            result += f"📊 基本EPS: `{currency_symbol}{data['Basic EPS']:.2f}`\n"
        if 'Diluted EPS' in data:
            result += f"📈 摊薄EPS: `{currency_symbol}{data['Diluted EPS']:.2f}`\n"
            
    elif statement_type == "balance":
        # 资产负债表关键指标
        if 'Total Assets' in data:
            result += f"🏛️ 总资产: `{currency_symbol}{data['Total Assets']:,.0f}`\n"
        if 'Total Liabilities Net Minority Interest' in data:
            result += f"📉 总负债: `{currency_symbol}{data['Total Liabilities Net Minority Interest']:,.0f}`\n"
        if 'Stockholders Equity' in data:
            result += f"🏦 股东权益: `{currency_symbol}{data['Stockholders Equity']:,.0f}`\n"
        if 'Cash And Cash Equivalents' in data:
            result += f"💰 现金及等价物: `{currency_symbol}{data['Cash And Cash Equivalents']:,.0f}`\n"
        if 'Total Debt' in data:
            result += f"💳 总债务: `{currency_symbol}{data['Total Debt']:,.0f}`\n"
        if 'Working Capital' in data:
            result += f"⚡ 营运资金: `{currency_symbol}{data['Working Capital']:,.0f}`\n"
            
    elif statement_type == "cashflow":
        # 现金流量表关键指标
        if 'Operating Cash Flow' in data:
            result += f"⚙️ 经营现金流: `{currency_symbol}{data['Operating Cash Flow']:,.0f}`\n"
        if 'Investing Cash Flow' in data:
            result += f"📈 投资现金流: `{currency_symbol}{data['Investing Cash Flow']:,.0f}`\n"
        if 'Financing Cash Flow' in data:
            result += f"💰 融资现金流: `{currency_symbol}{data['Financing Cash Flow']:,.0f}`\n"
        if 'Free Cash Flow' in data:
            result += f"💎 自由现金流: `{currency_symbol}{data['Free Cash Flow']:,.0f}`\n"
    
    result += f"\n_更新时间: {datetime.now().strftime('%H:%M:%S')}_"
    return result

def format_valuation_measures(valuation_data: Dict) -> str:
    """格式化估值指标"""
    symbol = valuation_data['symbol']
    measures = valuation_data.get('measures')

    result = f"📊 *{symbol} 估值指标*\n\n"

    if not measures or measures.empty:
        return result + "❌ 暂无估值数据"

    # 获取当前列（第一列通常是最新数据）
    if len(measures.columns) > 0:
        current_col = measures.columns[0]
        result += f"📅 数据时间: `{current_col}`\n\n"

        # 关键估值指标
        key_metrics = {
            'Market Cap': '💎 市值',
            'Enterprise Value': '🏢 企业价值',
            'Trailing P/E': '📈 市盈率(TTM)',
            'Forward P/E': '📊 预期市盈率',
            'PEG Ratio (5yr expected)': '📉 PEG比率',
            'Price/Sales': '💰 市销率',
            'Price/Book': '📚 市净率',
            'Enterprise Value/Revenue': '🏭 EV/收入',
            'Enterprise Value/EBITDA': '⚡ EV/EBITDA'
        }

        for metric_name, display_name in key_metrics.items():
            if metric_name in measures.index:
                value = measures.loc[metric_name, current_col]
                if value and value != 'N/A':
                    result += f"{display_name}: `{value}`\n"

    result += f"\n_更新时间: {datetime.now().strftime('%H:%M:%S')}_"
    return result

def format_earnings_dates(earnings_data: Dict) -> str:
    """格式化财报日期"""
    symbol = earnings_data['symbol']
    currency = earnings_data.get('currency', 'USD')
    currency_symbol = get_currency_symbol(currency)
    next_earnings = earnings_data.get('next_earnings')
    upcoming_earnings = earnings_data.get('upcoming_earnings', [])
    recent_earnings = earnings_data.get('recent_earnings', [])

    result = f"📅 *{symbol} 财报日期*\n\n"

    # 下一个财报日期
    if next_earnings:
        result += "🔥 *下次财报:*\n"
        result += f"📆 日期: `{next_earnings['date']}`\n"
        if next_earnings.get('eps_estimate'):
            result += f"📊 EPS预期: `{currency_symbol}{next_earnings['eps_estimate']:.2f}`\n"
        result += "\n"

    # 即将到来的财报
    if upcoming_earnings:
        result += "📈 *即将发布 (未来4次):*\n"
        for i, earning in enumerate(upcoming_earnings, 1):
            result += f"`{i}.` {earning['date']}"
            if earning.get('eps_estimate'):
                result += f" (EPS预期: {currency_symbol}{earning['eps_estimate']:.2f})"
            result += "\n"
        result += "\n"

    # 最近的财报
    if recent_earnings:
        result += "📊 *最近发布 (过去4次):*\n"
        for i, earning in enumerate(recent_earnings, 1):
            result += f"`{i}.` {earning['date']}"
            if earning.get('reported_eps'):
                result += f" - EPS: {currency_symbol}{earning['reported_eps']:.2f}"
            if earning.get('surprise'):
                surprise = earning['surprise']
                emoji = "📈" if surprise > 0 else "📉" if surprise < 0 else "➡️"
                result += f" {emoji} ({surprise:+.1f}%)"
            result += "\n"
        result += "\n"

    if not next_earnings and not upcoming_earnings and not recent_earnings:
        result += "❌ 暂无财报日期数据"

    result += f"_更新时间: {datetime.now().strftime('%H:%M:%S')}_"
    return result

def format_analyst_upgrades_downgrades(upgrades_data: Dict) -> str:
    """格式化分析师评级变化"""
    symbol = upgrades_data['symbol']
    changes = upgrades_data.get('changes', [])

    result = f"📊 *{symbol} 分析师评级变化*\n\n"

    if changes:
        result += f"共 `{len(changes)}` 条评级变化记录\n\n"

        for i, change in enumerate(changes[:10], 1):  # 显示最近10条
            date = change.get('date', '')
            firm = change.get('firm', '')
            action = change.get('action', '')
            from_grade = change.get('from_grade', '')
            to_grade = change.get('to_grade', '')

            # 根据action类型选择emoji
            if action.lower() in ['up', 'upgrade', 'init']:
                emoji = "📈"
            elif action.lower() in ['down', 'downgrade']:
                emoji = "📉"
            elif action.lower() in ['main', 'reit']:
                emoji = "➡️"
            else:
                emoji = "🔄"

            result += f"`{i:2d}.` {emoji} *{date}*\n"
            if firm:
                result += f"     🏢 {firm}\n"
            if action:
                result += f"     🎯 {action}"
            if from_grade and to_grade:
                result += f": {from_grade} → {to_grade}"
            elif to_grade:
                result += f": {to_grade}"
            result += "\n\n"
    else:
        result += "❌ 暂无评级变化数据"

    result += f"_更新时间: {datetime.now().strftime('%H:%M:%S')}_"
    return result

def format_dividends_splits(dividends_data: Dict) -> str:
    """格式化分红拆股信息 - 支持外汇信息显示"""
    symbol = dividends_data['symbol']
    currency = dividends_data.get('currency', 'USD')
    dividend_currency = dividends_data.get('dividend_currency')  # 新增：分红货币
    currency_symbol = get_currency_symbol(currency)
    recent_dividends = dividends_data.get('recent_dividends', [])
    recent_splits = dividends_data.get('recent_splits', [])
    dividend_yield = dividends_data.get('dividend_yield', 0)
    annual_dividend = dividends_data.get('annual_dividend', 0)

    result = f"💰 *{symbol} 分红拆股信息*\n\n"

    # 分红信息
    if recent_dividends:
        result += "💵 *分红信息:*\n"

        # 如果分红货币与股价货币不同，显示警告
        if dividend_currency and dividend_currency != currency:
            div_currency_symbol = get_currency_symbol(dividend_currency)
            result += f"⚠️ 分红货币: `{dividend_currency}` {div_currency_symbol} (不同于股价货币 {currency})\n"

        if annual_dividend > 0:
            result += f"📊 年度分红: `{currency_symbol}{annual_dividend:.2f}`\n"
        if dividend_yield > 0:
            result += f"📈 分红收益率: `{dividend_yield:.2f}%`\n"
        result += "\n"

        result += "📋 *最近分红记录:*\n"
        for i, dividend in enumerate(recent_dividends[-8:], 1):  # 显示最近8次
            result += f"`{i}.` {dividend['date']} - `{currency_symbol}{dividend['amount']:.2f}`\n"
        result += "\n"
    else:
        result += "💵 *分红信息:* 暂无分红记录\n\n"

    # 拆股信息
    if recent_splits:
        result += "🔀 *拆股信息:*\n"
        result += "📋 *最近拆股记录:*\n"
        for i, split in enumerate(recent_splits[-5:], 1):  # 显示最近5次
            result += f"`{i}.` {split['date']} - 拆股比例 `{split['ratio_text']}`\n"
        result += "\n"
    else:
        result += "🔀 *拆股信息:* 暂无拆股记录\n\n"

    if not recent_dividends and not recent_splits:
        result += "❌ 暂无分红拆股数据"

    result += f"_更新时间: {datetime.now().strftime('%H:%M:%S')}_"
    return result

def format_earnings_calendar(calendar_data: List[Dict]) -> str:
    """格式化财报日历"""
    if not calendar_data:
        return "❌ 暂无财报日历数据"

    result = f"📅 *财报日历 (未来7天)*\n\n"
    result += f"共 `{len(calendar_data)}` 家公司即将发布财报\n\n"

    # 按日期分组
    by_date = {}
    for item in calendar_data[:20]:  # 限制显示前20个
        date = item['date']
        if date not in by_date:
            by_date[date] = []
        by_date[date].append(item)

    for date in sorted(by_date.keys()):
        items = by_date[date]
        result += f"📆 *{date}*\n"

        for item in items[:5]:  # 每天最多显示5个
            symbol = item['symbol']
            company = item['company']
            time_str = item.get('time', '')
            eps_est = item.get('eps_estimate')

            result += f"  • *{symbol}* - {company}\n"
            if time_str:
                result += f"    ⏰ {time_str}"
            if eps_est is not None:
                result += f" | EPS预期: `${eps_est:.2f}`"
            result += "\n"

        if len(items) > 5:
            result += f"    _...还有 {len(items) - 5} 家公司_\n"
        result += "\n"

    result += f"_更新时间: {datetime.now().strftime('%H:%M:%S')}_"
    return result

def format_ipo_calendar(calendar_data: List[Dict]) -> str:
    """格式化IPO日历"""
    if not calendar_data:
        return "❌ 暂无IPO日历数据"

    result = f"🚀 *IPO日历 (未来30天)*\n\n"
    result += f"共 `{len(calendar_data)}` 只新股即将上市\n\n"

    for i, item in enumerate(calendar_data[:15], 1):  # 最多显示15个
        symbol = item['symbol']
        company = item['company']
        date = item.get('date', '')
        exchange = item.get('exchange', '')
        price_from = item.get('price_from')
        price_to = item.get('price_to')
        price = item.get('price')
        shares = item.get('shares')
        currency = item.get('currency', 'USD')
        currency_symbol = get_currency_symbol(currency)

        result += f"`{i:2d}.` *{symbol}* - {company}\n"
        if date:
            result += f"     📆 上市日期: `{date}`\n"
        if exchange:
            result += f"     🏛️ 交易所: `{exchange}`\n"

        # 价格信息
        if price:
            result += f"     💰 发行价: `{currency_symbol}{price:.2f}`\n"
        elif price_from and price_to:
            result += f"     💰 价格区间: `{currency_symbol}{price_from:.2f} - {currency_symbol}{price_to:.2f}`\n"

        if shares:
            if shares >= 1_000_000:
                shares_str = f"{shares / 1_000_000:.1f}M"
            else:
                shares_str = f"{shares:,}"
            result += f"     📊 发行股数: `{shares_str}`\n"

        result += "\n"

    if len(calendar_data) > 15:
        result += f"_...还有 {len(calendar_data) - 15} 只新股未显示_\n\n"

    result += f"_更新时间: {datetime.now().strftime('%H:%M:%S')}_"
    return result

def format_economic_events_calendar(calendar_data: List[Dict]) -> str:
    """格式化经济事件日历"""
    if not calendar_data:
        return "❌ 暂无经济事件日历数据"

    result = f"🌍 *经济事件日历 (未来7天)*\n\n"
    result += f"共 `{len(calendar_data)}` 项经济数据即将发布\n\n"

    # 按日期分组
    by_date = {}
    for item in calendar_data[:30]:  # 限制显示前30个
        time_str = item.get('time', '')
        if time_str:
            date = time_str.split(' ')[0] if ' ' in time_str else time_str[:10]
        else:
            date = 'Unknown'

        if date not in by_date:
            by_date[date] = []
        by_date[date].append(item)

    for date in sorted(by_date.keys()):
        items = by_date[date]
        result += f"📆 *{date}*\n"

        for item in items[:8]:  # 每天最多显示8个
            event = item['event']
            region = item.get('region', '')
            time_str = item.get('time', '')
            expected = item.get('expected')
            last = item.get('last')

            # 提取时间部分
            time_part = ''
            if ' ' in time_str:
                time_part = time_str.split(' ')[1]

            result += f"  • {region} {event}\n"
            if time_part:
                result += f"    ⏰ {time_part}"
            if expected is not None:
                result += f" | 预期: `{expected}`"
            if last is not None:
                result += f" | 前值: `{last}`"
            result += "\n"

        if len(items) > 8:
            result += f"    _...还有 {len(items) - 8} 项事件_\n"
        result += "\n"

    result += f"_更新时间: {datetime.now().strftime('%H:%M:%S')}_"
    return result

def format_splits_calendar(calendar_data: List[Dict]) -> str:
    """格式化拆股日历"""
    if not calendar_data:
        return "❌ 暂无拆股日历数据"

    result = f"🔀 *拆股日历 (未来30天)*\n\n"
    result += f"共 `{len(calendar_data)}` 只股票即将拆股\n\n"

    for i, item in enumerate(calendar_data[:20], 1):  # 最多显示20个
        symbol = item['symbol']
        company = item['company']
        date = item.get('date', '')
        ratio_text = item.get('ratio_text', '')
        optionable = item.get('optionable', '')

        result += f"`{i:2d}.` *{symbol}* - {company}\n"
        if date:
            result += f"     📆 拆股日期: `{date}`\n"
        if ratio_text:
            result += f"     🔀 拆股比例: `{ratio_text}`\n"
        if optionable:
            result += f"     📋 可期权: `{optionable}`\n"
        result += "\n"

    if len(calendar_data) > 20:
        result += f"_...还有 {len(calendar_data) - 20} 只股票未显示_\n\n"

    result += f"_更新时间: {datetime.now().strftime('%H:%M:%S')}_"
    return result

def format_ranking_list(stocks: List[Dict], title: str) -> str:
    """格式化排行榜"""
    if not stocks:
        return f"❌ {title} 数据获取失败"
    
    result = f"📋 *{title}*\n\n"
    
    for i, stock in enumerate(stocks[:10], 1):
        symbol = stock['symbol']
        name = stock.get('name', symbol)
        price = stock['current_price']
        change_percent = stock['change_percent']
        currency = stock.get('currency', 'USD')
        currency_symbol = get_currency_symbol(currency)
        
        trend_emoji = "📈" if change_percent >= 0 else "📉"
        change_sign = "+" if change_percent >= 0 else ""
        
        # 显示完整公司名称
        result += f"`{i:2d}.` {trend_emoji} *{symbol}* - {name}\n"
        result += f"     `{currency_symbol}{price:.2f}` `({change_sign}{change_percent:.2f}%)`\n\n"
    
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
        # 删除用户命令
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        return

    # 没有参数，显示主菜单
    keyboard = [
        [
            InlineKeyboardButton("📊 查询股票", callback_data="finance_search"),
            InlineKeyboardButton("🔍 搜索股票", callback_data="finance_search_menu")
        ],
        [
            InlineKeyboardButton("📈 股票排行榜", callback_data="finance_stock_rankings"),
            InlineKeyboardButton("💰 基金排行榜", callback_data="finance_fund_rankings")
        ],
        [
            InlineKeyboardButton("📆 金融日历", callback_data="finance_calendars_menu")
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
• **金融日历**: 财报、IPO、经济事件等

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
            # 检查是否为错误信息
            if stock_data.get('error'):
                # 处理错误情况
                result_text = format_stock_info(stock_data)
                keyboard = [[InlineKeyboardButton("🔙 返回主菜单", callback_data="finance_main_menu")]]
                reply_markup = InlineKeyboardMarkup(keyboard)

                if callback_query:
                    await callback_query.edit_message_text(
                        text=foldable_text_v2(result_text),
                        parse_mode="MarkdownV2",
                        reply_markup=reply_markup
                    )
                else:
                    await message.edit_text(
                        text=foldable_text_v2(result_text),
                        parse_mode="MarkdownV2",
                        reply_markup=reply_markup
                    )

                # 错误消息10秒后删除
                await _schedule_auto_delete(context, message.chat_id, message.message_id, 10)
                return

            # 找到正常股票信息，直接显示
            result_text = format_stock_info(stock_data)

            # 添加分析师评级和财务报表按钮
            symbol = stock_data['symbol']
            short_id = get_short_stock_id(symbol)
            keyboard = [
                [
                    InlineKeyboardButton("🎯 分析师评级", callback_data=f"finance_analyst:{short_id}"),
                    InlineKeyboardButton("📊 估值指标", callback_data=f"finance_valuation:{short_id}")
                ],
                [
                    InlineKeyboardButton("📋 损益表", callback_data=f"finance_income:{short_id}"),
                    InlineKeyboardButton("🏛️资产负债表", callback_data=f"finance_balance:{short_id}")
                ],
                [
                    InlineKeyboardButton("💰 现金流量表", callback_data=f"finance_cashflow:{short_id}"),
                    InlineKeyboardButton("📅 财报日期", callback_data=f"finance_earnings:{short_id}")
                ],
                [
                    InlineKeyboardButton("💰 分红拆股", callback_data=f"finance_dividends:{short_id}"),
                    InlineKeyboardButton("🔙 返回主菜单", callback_data="finance_main_menu")
                ]
            ]
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
                
                # 搜索结果也安排自动删除
                config = get_config()
                await _schedule_auto_delete(context, message.chat_id, message.message_id, config.auto_delete_delay)
            else:
                # 没有找到任何结果
                error_text = f"❌ 未找到 '{query}' 相关的股票信息\n\n💡 请检查股票代码是否正确，或尝试使用公司名称搜索"
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

async def finance_stock_rankings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """显示股票排行榜菜单"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [
            InlineKeyboardButton("📈 日涨幅榜", callback_data="finance_gainers"),
            InlineKeyboardButton("📉 日跌幅榜", callback_data="finance_losers")
        ],
        [
            InlineKeyboardButton("🔥 最活跃", callback_data="finance_actives"),
            InlineKeyboardButton("⚡ 激进小盘", callback_data="finance_aggressive_small_caps")
        ],
        [
            InlineKeyboardButton("💎 小盘涨幅", callback_data="finance_small_cap_gainers"),
            InlineKeyboardButton("🩸 最多做空", callback_data="finance_most_shorted")
        ],
        [
            InlineKeyboardButton("🚀 成长科技", callback_data="finance_growth_tech"),
            InlineKeyboardButton("💰 低估大盘", callback_data="finance_undervalued_large")
        ],
        [
            InlineKeyboardButton("📊 低估成长", callback_data="finance_undervalued_growth")
        ],
        [
            InlineKeyboardButton("🇨🇭 瑞士市场", callback_data="finance_swiss_markets"),
            InlineKeyboardButton("🌍 国际市场", callback_data="finance_international_markets")
        ],
        [
            InlineKeyboardButton("🔙 返回主菜单", callback_data="finance_main_menu")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    help_text = """📈 股票排行榜

选择你要查看的股票排行榜类型:"""
    
    await query.edit_message_text(
        text=foldable_text_with_markdown_v2(help_text),
        parse_mode="MarkdownV2",
        reply_markup=reply_markup
    )

async def finance_fund_rankings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """显示基金排行榜菜单"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [
            InlineKeyboardButton("🌍 保守外国", callback_data="finance_conservative_foreign"),
            InlineKeyboardButton("💸 高收益债券", callback_data="finance_high_yield_bond")
        ],
        [
            InlineKeyboardButton("⚓ 核心基金", callback_data="finance_portfolio_anchors"),
            InlineKeyboardButton("📈 大盘成长", callback_data="finance_large_growth_funds")
        ],
        [
            InlineKeyboardButton("📊 中盘成长", callback_data="finance_midcap_growth_funds"),
            InlineKeyboardButton("🏆 顶级基金", callback_data="finance_top_mutual_funds")
        ],
        [
            InlineKeyboardButton("🔙 返回主菜单", callback_data="finance_main_menu")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    help_text = """💰 基金排行榜

选择你要查看的基金排行榜类型:"""
    
    await query.edit_message_text(
        text=foldable_text_with_markdown_v2(help_text),
        parse_mode="MarkdownV2",
        reply_markup=reply_markup
    )

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
            InlineKeyboardButton("📈 股票排行榜", callback_data="finance_stock_rankings"),
            InlineKeyboardButton("💰 基金排行榜", callback_data="finance_fund_rankings")
        ],
        [
            InlineKeyboardButton("🎯 ETF排行榜", callback_data="finance_etf_rankings"),
            InlineKeyboardButton("📆 金融日历", callback_data="finance_calendars_menu")
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
• **金融日历**: 财报、IPO、经济事件等

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
• 美股 (NASDAQ, NYSE) - 如 AAPL, GOOGL
• 港股 (HKEX) - 如 0700.HK, 9988.HK
• A股 (上交所/深交所) - 如 000001.SZ, 600000.SS
• 🇨🇭 瑞士股市 (SIX) - 如 NESN.SW, NOVN.SW
• 🇬🇧 英国股市 (LSE) - 如 SHEL.L, AZN.L
• 🇩🇪 德国股市 (XETRA) - 如 SAP.DE, SIE.DE
• 🇫🇷 法国股市 (EPA) - 如 MC.PA, OR.PA
• 🇯🇵 日本股市 (TSE) - 如 7203.T, 6758.T

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

async def finance_aggressive_small_caps_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """激进小盘股"""
    query = update.callback_query
    await query.answer("正在获取激进小盘股...")
    await _execute_ranking(update, context, "aggressive_small_caps", "激进小盘股", query)

async def finance_most_shorted_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """最多做空股票"""
    query = update.callback_query
    await query.answer("正在获取最多做空股票...")
    await _execute_ranking(update, context, "most_shorted_stocks", "最多做空股票", query)

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

async def finance_undervalued_growth_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """低估值成长股"""
    query = update.callback_query
    await query.answer("正在获取低估值成长股...")
    await _execute_ranking(update, context, "undervalued_growth_stocks", "低估值成长股", query)

async def finance_swiss_markets_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """瑞士市场菜单"""
    query = update.callback_query
    await query.answer()

    help_text = """🇨🇭 瑞士股市 (SIX Swiss Exchange)

**示例股票代码:**
• `NESN.SW` - 雀巢
• `NOVN.SW` - 诺华制药
• `ROG.SW` - 罗氏控股
• `UHR.SW` - 斯沃琪集团
• `ABBN.SW` - ABB集团

请使用 `/finance [股票代码]` 查询瑞士股票"""

    keyboard = [
        [
            InlineKeyboardButton("🔍 查询 NESN.SW", callback_data="finance_search_NESN.SW"),
            InlineKeyboardButton("🔍 查询 NOVN.SW", callback_data="finance_search_NOVN.SW")
        ],
        [
            InlineKeyboardButton("🔍 查询 ROG.SW", callback_data="finance_search_ROG.SW"),
            InlineKeyboardButton("🔍 查询 UHR.SW", callback_data="finance_search_UHR.SW")
        ],
        [
            InlineKeyboardButton("🔙 返回排行榜", callback_data="finance_stock_rankings")
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        text=foldable_text_with_markdown_v2(help_text),
        parse_mode="MarkdownV2",
        reply_markup=reply_markup
    )

async def finance_international_markets_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """国际市场菜单"""
    query = update.callback_query
    await query.answer()

    help_text = """🌍 国际股市

**主要市场示例:**
🇬🇧 **英国 (LSE):** `SHEL.L`, `AZN.L`, `BP.L`
🇩🇪 **德国 (XETRA):** `SAP.DE`, `SIE.DE`, `VOW3.DE`
🇫🇷 **法国 (EPA):** `MC.PA`, `OR.PA`, `AI.PA`
🇯🇵 **日本 (TSE):** `7203.T`, `6758.T`, `9984.T`

请使用 `/finance [股票代码]` 查询国际股票"""

    keyboard = [
        [
            InlineKeyboardButton("🇬🇧 查询 SHEL.L", callback_data="finance_search_SHEL.L"),
            InlineKeyboardButton("🇩🇪 查询 SAP.DE", callback_data="finance_search_SAP.DE")
        ],
        [
            InlineKeyboardButton("🇫🇷 查询 MC.PA", callback_data="finance_search_MC.PA"),
            InlineKeyboardButton("🇯🇵 查询 7203.T", callback_data="finance_search_7203.T")
        ],
        [
            InlineKeyboardButton("🔙 返回排行榜", callback_data="finance_stock_rankings")
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        text=foldable_text_with_markdown_v2(help_text),
        parse_mode="MarkdownV2",
        reply_markup=reply_markup
    )

async def finance_search_symbol_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理快速查询按钮"""
    query = update.callback_query
    await query.answer()

    if not query or not query.data:
        return

    try:
        callback_data = query.data
        if callback_data.startswith("finance_search_"):
            symbol = callback_data.replace("finance_search_", "")
            # 执行股票查询
            await _execute_stock_search(update, context, symbol, query)

    except Exception as e:
        logger.error(f"处理快速查询回调时发生错误: {e}", exc_info=True)
        try:
            await query.edit_message_text(
                foldable_text_v2(f"❌ 处理请求时发生错误: {str(e)}"),
                parse_mode="MarkdownV2"
            )
        except:
            pass

# 基金排行榜回调处理器
async def finance_conservative_foreign_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """保守外国基金"""
    query = update.callback_query
    await query.answer("正在获取保守外国基金...")
    await _execute_ranking(update, context, "conservative_foreign_funds", "保守外国基金", query)

async def finance_high_yield_bond_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """高收益债券基金"""
    query = update.callback_query
    await query.answer("正在获取高收益债券基金...")
    await _execute_ranking(update, context, "high_yield_bond", "高收益债券基金", query)

async def finance_portfolio_anchors_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """投资组合核心基金"""
    query = update.callback_query
    await query.answer("正在获取投资组合核心基金...")
    await _execute_ranking(update, context, "portfolio_anchors", "投资组合核心基金", query)

async def finance_large_growth_funds_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """优质大盘成长基金"""
    query = update.callback_query
    await query.answer("正在获取优质大盘成长基金...")
    await _execute_ranking(update, context, "solid_large_growth_funds", "优质大盘成长基金", query)

async def finance_midcap_growth_funds_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """优质中盘成长基金"""
    query = update.callback_query
    await query.answer("正在获取优质中盘成长基金...")
    await _execute_ranking(update, context, "solid_midcap_growth_funds", "优质中盘成长基金", query)

async def finance_top_mutual_funds_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """顶级共同基金"""
    query = update.callback_query
    await query.answer("正在获取顶级共同基金...")
    await _execute_ranking(update, context, "top_mutual_funds", "顶级共同基金", query)

async def finance_etf_rankings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """显示ETF排行榜菜单"""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [
            InlineKeyboardButton("🇺🇸 美国顶级ETF", callback_data="finance_top_etfs_us"),
            InlineKeyboardButton("📈 高表现ETF", callback_data="finance_top_performing_etfs")
        ],
        [
            InlineKeyboardButton("💻 科技ETF", callback_data="finance_technology_etfs"),
            InlineKeyboardButton("💰 债券ETF", callback_data="finance_bond_etfs")
        ],
        [
            InlineKeyboardButton("🔙 返回主菜单", callback_data="finance_main_menu")
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    help_text = """🎯 ETF排行榜

选择你要查看的ETF排行榜类型:"""

    await query.edit_message_text(
        text=foldable_text_with_markdown_v2(help_text),
        parse_mode="MarkdownV2",
        reply_markup=reply_markup
    )

async def finance_top_etfs_us_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """美国顶级ETF"""
    query = update.callback_query
    await query.answer("正在获取美国顶级ETF...")
    await _execute_ranking(update, context, "top_etfs_us", "美国顶级ETF", query)

async def finance_top_performing_etfs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """高表现ETF"""
    query = update.callback_query
    await query.answer("正在获取高表现ETF...")
    await _execute_ranking(update, context, "top_performing_etfs", "高表现ETF", query)

async def finance_technology_etfs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """科技ETF"""
    query = update.callback_query
    await query.answer("正在获取科技ETF...")
    await _execute_ranking(update, context, "technology_etfs", "科技ETF", query)

async def finance_bond_etfs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """债券ETF"""
    query = update.callback_query
    await query.answer("正在获取债券ETF...")
    await _execute_ranking(update, context, "bond_etfs", "债券ETF", query)

# 分析师评级和财务报表回调处理器
async def finance_analyst_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理分析师评级按钮点击"""
    query = update.callback_query
    await query.answer("正在获取分析师评级...")
    
    if not query or not query.data:
        return
        
    try:
        callback_data = query.data
        if callback_data.startswith("finance_analyst:"):
            short_id = callback_data.replace("finance_analyst:", "")
            symbol = get_full_stock_id(short_id)
            if not symbol:
                await query.edit_message_text(
                    foldable_text_v2("❌ 股票信息已过期，请重新查询"),
                    parse_mode="MarkdownV2"
                )
                await _schedule_auto_delete(context, query.message.chat_id, query.message.message_id, 5)
                return
            
            # 获取分析师评级数据
            recommendation_data = await finance_service.get_analyst_recommendations(symbol)
            
            if recommendation_data:
                result_text = format_analyst_recommendations(recommendation_data)
                
                keyboard = [
                    [
                        InlineKeyboardButton("📊 股票信息", callback_data=f"finance_stock_detail:{short_id}"),
                        InlineKeyboardButton("📋 损益表", callback_data=f"finance_income:{short_id}")
                    ],
                    [
                        InlineKeyboardButton("🔙 返回主菜单", callback_data="finance_main_menu")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    text=foldable_text_with_markdown_v2(result_text),
                    parse_mode="MarkdownV2",
                    reply_markup=reply_markup
                )
            else:
                error_text = f"❌ 暂无 {symbol} 的分析师评级数据"
                keyboard = [[InlineKeyboardButton("🔙 返回主菜单", callback_data="finance_main_menu")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    text=foldable_text_v2(error_text),
                    parse_mode="MarkdownV2", 
                    reply_markup=reply_markup
                )
                await _schedule_auto_delete(context, query.message.chat_id, query.message.message_id, 5)
            
    except Exception as e:
        logger.error(f"处理分析师评级回调时发生错误: {e}", exc_info=True)
        try:
            await query.edit_message_text(
                foldable_text_v2(f"❌ 处理请求时发生错误: {str(e)}"),
                parse_mode="MarkdownV2"
            )
        except:
            pass

async def finance_valuation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理估值指标按钮点击"""
    query = update.callback_query
    await query.answer("正在获取估值指标...")

    if not query or not query.data:
        return

    try:
        callback_data = query.data
        if callback_data.startswith("finance_valuation:"):
            short_id = callback_data.replace("finance_valuation:", "")
            symbol = get_full_stock_id(short_id)
            if not symbol:
                await query.edit_message_text(
                    foldable_text_v2("❌ 股票信息已过期，请重新查询"),
                    parse_mode="MarkdownV2"
                )
                await _schedule_auto_delete(context, query.message.chat_id, query.message.message_id, 5)
                return

            # 获取估值指标数据
            valuation_data = await finance_service.get_valuation_measures(symbol)

            if valuation_data:
                result_text = format_valuation_measures(valuation_data)

                keyboard = [
                    [
                        InlineKeyboardButton("📊 股票信息", callback_data=f"finance_stock_detail:{short_id}"),
                        InlineKeyboardButton("🎯 分析师评级", callback_data=f"finance_analyst:{short_id}")
                    ],
                    [
                        InlineKeyboardButton("🔙 返回主菜单", callback_data="finance_main_menu")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                await query.edit_message_text(
                    text=foldable_text_with_markdown_v2(result_text),
                    parse_mode="MarkdownV2",
                    reply_markup=reply_markup
                )
            else:
                error_text = f"❌ 暂无 {symbol} 的估值指标数据"
                keyboard = [[InlineKeyboardButton("🔙 返回主菜单", callback_data="finance_main_menu")]]
                reply_markup = InlineKeyboardMarkup(keyboard)

                await query.edit_message_text(
                    text=foldable_text_v2(error_text),
                    parse_mode="MarkdownV2",
                    reply_markup=reply_markup
                )
                await _schedule_auto_delete(context, query.message.chat_id, query.message.message_id, 5)

    except Exception as e:
        logger.error(f"处理估值指标回调时发生错误: {e}", exc_info=True)
        try:
            await query.edit_message_text(
                foldable_text_v2(f"❌ 处理请求时发生错误: {str(e)}"),
                parse_mode="MarkdownV2"
            )
        except:
            pass

async def finance_financial_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理财务报表按钮点击"""
    query = update.callback_query
    
    if not query or not query.data:
        return
        
    try:
        callback_data = query.data
        
        # 确定报表类型
        if callback_data.startswith("finance_income:"):
            statement_type = "income"
            short_id = callback_data.replace("finance_income:", "")
            await query.answer("正在获取损益表...")
        elif callback_data.startswith("finance_balance:"):
            statement_type = "balance" 
            short_id = callback_data.replace("finance_balance:", "")
            await query.answer("正在获取资产负债表...")
        elif callback_data.startswith("finance_cashflow:"):
            statement_type = "cashflow"
            short_id = callback_data.replace("finance_cashflow:", "") 
            await query.answer("正在获取现金流量表...")
        else:
            return
            
        symbol = get_full_stock_id(short_id)
        if not symbol:
            await query.edit_message_text(
                foldable_text_v2("❌ 股票信息已过期，请重新查询"),
                parse_mode="MarkdownV2"
            )
            await _schedule_auto_delete(context, query.message.chat_id, query.message.message_id, 5)
            return
        
        # 获取财务报表数据
        financial_data = await finance_service.get_financial_statements(symbol, statement_type)
        
        if financial_data:
            result_text = format_financial_statement(financial_data)
            
            keyboard = [
                [
                    InlineKeyboardButton("📊 股票信息", callback_data=f"finance_stock_detail:{short_id}"),
                    InlineKeyboardButton("🎯 分析师评级", callback_data=f"finance_analyst:{short_id}")
                ],
                [
                    InlineKeyboardButton("📋 损益表", callback_data=f"finance_income:{short_id}"),
                    InlineKeyboardButton("🏛️ 资产负债表", callback_data=f"finance_balance:{short_id}")
                ],
                [
                    InlineKeyboardButton("💰 现金流量表", callback_data=f"finance_cashflow:{short_id}"),
                    InlineKeyboardButton("🔙 返回主菜单", callback_data="finance_main_menu")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                text=foldable_text_with_markdown_v2(result_text),
                parse_mode="MarkdownV2",
                reply_markup=reply_markup
            )
        else:
            error_text = f"❌ 暂无 {symbol} 的{financial_data.get('title', '财务')}数据" if financial_data else f"❌ 暂无 {symbol} 的财务数据"
            keyboard = [[InlineKeyboardButton("🔙 返回主菜单", callback_data="finance_main_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                text=foldable_text_v2(error_text),
                parse_mode="MarkdownV2",
                reply_markup=reply_markup
            )
            await _schedule_auto_delete(context, query.message.chat_id, query.message.message_id, 5)
        
    except Exception as e:
        logger.error(f"处理财务报表回调时发生错误: {e}", exc_info=True)
        try:
            await query.edit_message_text(
                foldable_text_v2(f"❌ 处理请求时发生错误: {str(e)}"),
                parse_mode="MarkdownV2"
            )
        except:
            pass

async def finance_earnings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理财报日期按钮点击"""
    query = update.callback_query
    await query.answer("正在获取财报日期...")

    if not query or not query.data:
        return

    try:
        callback_data = query.data
        if callback_data.startswith("finance_earnings:"):
            short_id = callback_data.replace("finance_earnings:", "")
            symbol = get_full_stock_id(short_id)
            if not symbol:
                await query.edit_message_text(
                    foldable_text_v2("❌ 股票信息已过期，请重新查询"),
                    parse_mode="MarkdownV2"
                )
                await _schedule_auto_delete(context, query.message.chat_id, query.message.message_id, 5)
                return

            # 获取财报日期数据
            earnings_data = await finance_service.get_earnings_dates(symbol)

            if earnings_data:
                result_text = format_earnings_dates(earnings_data)

                keyboard = [
                    [
                        InlineKeyboardButton("📊 股票信息", callback_data=f"finance_stock_detail:{short_id}"),
                        InlineKeyboardButton("🎯 分析师评级", callback_data=f"finance_analyst:{short_id}")
                    ],
                    [
                        InlineKeyboardButton("📋 损益表", callback_data=f"finance_income:{short_id}"),
                        InlineKeyboardButton("💰 分红拆股", callback_data=f"finance_dividends:{short_id}")
                    ],
                    [
                        InlineKeyboardButton("🔙 返回主菜单", callback_data="finance_main_menu")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                await query.edit_message_text(
                    text=foldable_text_with_markdown_v2(result_text),
                    parse_mode="MarkdownV2",
                    reply_markup=reply_markup
                )
            else:
                error_text = f"❌ 暂无 {symbol} 的财报日期数据"
                keyboard = [[InlineKeyboardButton("🔙 返回主菜单", callback_data="finance_main_menu")]]
                reply_markup = InlineKeyboardMarkup(keyboard)

                await query.edit_message_text(
                    text=foldable_text_v2(error_text),
                    parse_mode="MarkdownV2",
                    reply_markup=reply_markup
                )
                await _schedule_auto_delete(context, query.message.chat_id, query.message.message_id, 5)

    except Exception as e:
        logger.error(f"处理财报日期回调时发生错误: {e}", exc_info=True)
        try:
            await query.edit_message_text(
                foldable_text_v2(f"❌ 处理请求时发生错误: {str(e)}"),
                parse_mode="MarkdownV2"
            )
        except:
            pass

async def finance_dividends_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理分红拆股按钮点击"""
    query = update.callback_query
    await query.answer("正在获取分红拆股信息...")

    if not query or not query.data:
        return

    try:
        callback_data = query.data
        if callback_data.startswith("finance_dividends:"):
            short_id = callback_data.replace("finance_dividends:", "")
            symbol = get_full_stock_id(short_id)
            if not symbol:
                await query.edit_message_text(
                    foldable_text_v2("❌ 股票信息已过期，请重新查询"),
                    parse_mode="MarkdownV2"
                )
                await _schedule_auto_delete(context, query.message.chat_id, query.message.message_id, 5)
                return

            # 获取分红拆股数据
            dividends_data = await finance_service.get_dividends_splits(symbol)

            if dividends_data:
                result_text = format_dividends_splits(dividends_data)

                keyboard = [
                    [
                        InlineKeyboardButton("📊 股票信息", callback_data=f"finance_stock_detail:{short_id}"),
                        InlineKeyboardButton("🎯 分析师评级", callback_data=f"finance_analyst:{short_id}")
                    ],
                    [
                        InlineKeyboardButton("📅 财报日期", callback_data=f"finance_earnings:{short_id}"),
                        InlineKeyboardButton("📋 损益表", callback_data=f"finance_income:{short_id}")
                    ],
                    [
                        InlineKeyboardButton("🔙 返回主菜单", callback_data="finance_main_menu")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                await query.edit_message_text(
                    text=foldable_text_with_markdown_v2(result_text),
                    parse_mode="MarkdownV2",
                    reply_markup=reply_markup
                )
            else:
                error_text = f"❌ 暂无 {symbol} 的分红拆股数据"
                keyboard = [[InlineKeyboardButton("🔙 返回主菜单", callback_data="finance_main_menu")]]
                reply_markup = InlineKeyboardMarkup(keyboard)

                await query.edit_message_text(
                    text=foldable_text_v2(error_text),
                    parse_mode="MarkdownV2",
                    reply_markup=reply_markup
                )
                await _schedule_auto_delete(context, query.message.chat_id, query.message.message_id, 5)

    except Exception as e:
        logger.error(f"处理分红拆股回调时发生错误: {e}", exc_info=True)
        try:
            await query.edit_message_text(
                foldable_text_v2(f"❌ 处理请求时发生错误: {str(e)}"),
                parse_mode="MarkdownV2"
            )
        except:
            pass

async def finance_calendars_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """显示日历菜单"""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [
            InlineKeyboardButton("📅 财报日历", callback_data="finance_calendar_earnings"),
            InlineKeyboardButton("🚀 IPO日历", callback_data="finance_calendar_ipo")
        ],
        [
            InlineKeyboardButton("🌍 经济事件", callback_data="finance_calendar_economic"),
            InlineKeyboardButton("🔀 拆股日历", callback_data="finance_calendar_splits")
        ],
        [
            InlineKeyboardButton("🔙 返回主菜单", callback_data="finance_main_menu")
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    help_text = """📆 *金融日历*

选择你要查看的日历类型:

📅 *财报日历* - 未来7天公司财报发布
🚀 *IPO日历* - 未来30天新股上市
🌍 *经济事件* - 未来7天宏观经济数据
🔀 *拆股日历* - 未来30天股票拆股事件"""

    await query.edit_message_text(
        text=foldable_text_with_markdown_v2(help_text),
        parse_mode="MarkdownV2",
        reply_markup=reply_markup
    )

async def finance_calendar_earnings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """显示财报日历"""
    query = update.callback_query
    await query.answer("正在获取财报日历...")

    loading_message = "📅 正在获取财报日历... ⏳"
    await query.edit_message_text(
        text=foldable_text_v2(loading_message),
        parse_mode="MarkdownV2"
    )

    try:
        calendar_data = await finance_service.get_earnings_calendar(days=7, limit=50)

        if calendar_data:
            result_text = format_earnings_calendar(calendar_data)

            keyboard = [
                [
                    InlineKeyboardButton("🔄 刷新", callback_data="finance_calendar_earnings"),
                    InlineKeyboardButton("🔙 返回日历", callback_data="finance_calendars_menu")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                text=foldable_text_with_markdown_v2(result_text),
                parse_mode="MarkdownV2",
                reply_markup=reply_markup
            )
        else:
            error_text = "❌ 暂无财报日历数据"
            keyboard = [[InlineKeyboardButton("🔙 返回日历", callback_data="finance_calendars_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                text=foldable_text_v2(error_text),
                parse_mode="MarkdownV2",
                reply_markup=reply_markup
            )

    except Exception as e:
        logger.error(f"获取财报日历时发生错误: {e}", exc_info=True)
        error_text = f"❌ 获取财报日历失败: {str(e)}"

        await query.edit_message_text(
            text=foldable_text_v2(error_text),
            parse_mode="MarkdownV2"
        )

async def finance_calendar_ipo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """显示IPO日历"""
    query = update.callback_query
    await query.answer("正在获取IPO日历...")

    loading_message = "🚀 正在获取IPO日历... ⏳"
    await query.edit_message_text(
        text=foldable_text_v2(loading_message),
        parse_mode="MarkdownV2"
    )

    try:
        calendar_data = await finance_service.get_ipo_calendar(days=30, limit=50)

        if calendar_data:
            result_text = format_ipo_calendar(calendar_data)

            keyboard = [
                [
                    InlineKeyboardButton("🔄 刷新", callback_data="finance_calendar_ipo"),
                    InlineKeyboardButton("🔙 返回日历", callback_data="finance_calendars_menu")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                text=foldable_text_with_markdown_v2(result_text),
                parse_mode="MarkdownV2",
                reply_markup=reply_markup
            )
        else:
            error_text = "❌ 暂无IPO日历数据"
            keyboard = [[InlineKeyboardButton("🔙 返回日历", callback_data="finance_calendars_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                text=foldable_text_v2(error_text),
                parse_mode="MarkdownV2",
                reply_markup=reply_markup
            )

    except Exception as e:
        logger.error(f"获取IPO日历时发生错误: {e}", exc_info=True)
        error_text = f"❌ 获取IPO日历失败: {str(e)}"

        await query.edit_message_text(
            text=foldable_text_v2(error_text),
            parse_mode="MarkdownV2"
        )

async def finance_calendar_economic_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """显示经济事件日历"""
    query = update.callback_query
    await query.answer("正在获取经济事件日历...")

    loading_message = "🌍 正在获取经济事件日历... ⏳"
    await query.edit_message_text(
        text=foldable_text_v2(loading_message),
        parse_mode="MarkdownV2"
    )

    try:
        calendar_data = await finance_service.get_economic_events_calendar(days=7, limit=50)

        if calendar_data:
            result_text = format_economic_events_calendar(calendar_data)

            keyboard = [
                [
                    InlineKeyboardButton("🔄 刷新", callback_data="finance_calendar_economic"),
                    InlineKeyboardButton("🔙 返回日历", callback_data="finance_calendars_menu")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                text=foldable_text_with_markdown_v2(result_text),
                parse_mode="MarkdownV2",
                reply_markup=reply_markup
            )
        else:
            error_text = "❌ 暂无经济事件日历数据"
            keyboard = [[InlineKeyboardButton("🔙 返回日历", callback_data="finance_calendars_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                text=foldable_text_v2(error_text),
                parse_mode="MarkdownV2",
                reply_markup=reply_markup
            )

    except Exception as e:
        logger.error(f"获取经济事件日历时发生错误: {e}", exc_info=True)
        error_text = f"❌ 获取经济事件日历失败: {str(e)}"

        await query.edit_message_text(
            text=foldable_text_v2(error_text),
            parse_mode="MarkdownV2"
        )

async def finance_calendar_splits_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """显示拆股日历"""
    query = update.callback_query
    await query.answer("正在获取拆股日历...")

    loading_message = "🔀 正在获取拆股日历... ⏳"
    await query.edit_message_text(
        text=foldable_text_v2(loading_message),
        parse_mode="MarkdownV2"
    )

    try:
        calendar_data = await finance_service.get_splits_calendar(days=30, limit=50)

        if calendar_data:
            result_text = format_splits_calendar(calendar_data)

            keyboard = [
                [
                    InlineKeyboardButton("🔄 刷新", callback_data="finance_calendar_splits"),
                    InlineKeyboardButton("🔙 返回日历", callback_data="finance_calendars_menu")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                text=foldable_text_with_markdown_v2(result_text),
                parse_mode="MarkdownV2",
                reply_markup=reply_markup
            )
        else:
            error_text = "❌ 暂无拆股日历数据"
            keyboard = [[InlineKeyboardButton("🔙 返回日历", callback_data="finance_calendars_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                text=foldable_text_v2(error_text),
                parse_mode="MarkdownV2",
                reply_markup=reply_markup
            )

    except Exception as e:
        logger.error(f"获取拆股日历时发生错误: {e}", exc_info=True)
        error_text = f"❌ 获取拆股日历失败: {str(e)}"

        await query.edit_message_text(
            text=foldable_text_v2(error_text),
            parse_mode="MarkdownV2"
        )

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
    permission=Permission.NONE,
    description="金融数据查询 - 股票信息、排行榜等"
)

# 注册回调处理器
command_factory.register_callback(r"^finance_main_menu$", finance_main_menu_callback, permission=Permission.NONE, description="金融主菜单")
command_factory.register_callback(r"^finance_search$", finance_search_callback, permission=Permission.NONE, description="股票查询说明")
command_factory.register_callback(r"^finance_search_menu$", finance_search_callback, permission=Permission.NONE, description="股票搜索菜单")
command_factory.register_callback(r"^finance_stock_detail:", finance_stock_detail_callback, permission=Permission.NONE, description="股票详情")

# 菜单导航
command_factory.register_callback(r"^finance_stock_rankings$", finance_stock_rankings_callback, permission=Permission.NONE, description="股票排行榜菜单")
command_factory.register_callback(r"^finance_fund_rankings$", finance_fund_rankings_callback, permission=Permission.NONE, description="基金排行榜菜单")

# 股票排行榜
command_factory.register_callback(r"^finance_gainers$", finance_gainers_callback, permission=Permission.NONE, description="日涨幅榜")
command_factory.register_callback(r"^finance_losers$", finance_losers_callback, permission=Permission.NONE, description="日跌幅榜")
command_factory.register_callback(r"^finance_actives$", finance_actives_callback, permission=Permission.NONE, description="最活跃股票")
command_factory.register_callback(r"^finance_aggressive_small_caps$", finance_aggressive_small_caps_callback, permission=Permission.NONE, description="激进小盘股")
command_factory.register_callback(r"^finance_small_cap_gainers$", finance_small_cap_gainers_callback, permission=Permission.NONE, description="小盘股涨幅榜")
command_factory.register_callback(r"^finance_most_shorted$", finance_most_shorted_callback, permission=Permission.NONE, description="最多做空股票")
command_factory.register_callback(r"^finance_growth_tech$", finance_growth_tech_callback, permission=Permission.NONE, description="成长科技股")
command_factory.register_callback(r"^finance_undervalued_large$", finance_undervalued_large_callback, permission=Permission.NONE, description="低估值大盘股")
command_factory.register_callback(r"^finance_undervalued_growth$", finance_undervalued_growth_callback, permission=Permission.NONE, description="低估值成长股")

# 国际市场支持
command_factory.register_callback(r"^finance_swiss_markets$", finance_swiss_markets_callback, permission=Permission.NONE, description="瑞士市场")
command_factory.register_callback(r"^finance_international_markets$", finance_international_markets_callback, permission=Permission.NONE, description="国际市场")
command_factory.register_callback(r"^finance_search_", finance_search_symbol_callback, permission=Permission.NONE, description="快速查询股票")

# 基金排行榜
command_factory.register_callback(r"^finance_conservative_foreign$", finance_conservative_foreign_callback, permission=Permission.NONE, description="保守外国基金")
command_factory.register_callback(r"^finance_high_yield_bond$", finance_high_yield_bond_callback, permission=Permission.NONE, description="高收益债券基金")
command_factory.register_callback(r"^finance_portfolio_anchors$", finance_portfolio_anchors_callback, permission=Permission.NONE, description="投资组合核心基金")
command_factory.register_callback(r"^finance_large_growth_funds$", finance_large_growth_funds_callback, permission=Permission.NONE, description="优质大盘成长基金")
command_factory.register_callback(r"^finance_midcap_growth_funds$", finance_midcap_growth_funds_callback, permission=Permission.NONE, description="优质中盘成长基金")
command_factory.register_callback(r"^finance_top_mutual_funds$", finance_top_mutual_funds_callback, permission=Permission.NONE, description="顶级共同基金")

# ETF排行榜
command_factory.register_callback(r"^finance_etf_rankings$", finance_etf_rankings_callback, permission=Permission.NONE, description="ETF排行榜菜单")
command_factory.register_callback(r"^finance_top_etfs_us$", finance_top_etfs_us_callback, permission=Permission.NONE, description="美国顶级ETF")
command_factory.register_callback(r"^finance_top_performing_etfs$", finance_top_performing_etfs_callback, permission=Permission.NONE, description="高表现ETF")
command_factory.register_callback(r"^finance_technology_etfs$", finance_technology_etfs_callback, permission=Permission.NONE, description="科技ETF")
command_factory.register_callback(r"^finance_bond_etfs$", finance_bond_etfs_callback, permission=Permission.NONE, description="债券ETF")

# 分析师评级和财务报表
command_factory.register_callback(r"^finance_analyst:", finance_analyst_callback, permission=Permission.NONE, description="分析师评级")
command_factory.register_callback(r"^finance_valuation:", finance_valuation_callback, permission=Permission.NONE, description="估值指标")
command_factory.register_callback(r"^finance_income:", finance_financial_callback, permission=Permission.NONE, description="损益表")
command_factory.register_callback(r"^finance_balance:", finance_financial_callback, permission=Permission.NONE, description="资产负债表")
command_factory.register_callback(r"^finance_cashflow:", finance_financial_callback, permission=Permission.NONE, description="现金流量表")

# 新增功能
command_factory.register_callback(r"^finance_earnings:", finance_earnings_callback, permission=Permission.NONE, description="财报日期")
command_factory.register_callback(r"^finance_dividends:", finance_dividends_callback, permission=Permission.NONE, description="分红拆股")

# 日历功能
command_factory.register_callback(r"^finance_calendars_menu$", finance_calendars_menu_callback, permission=Permission.NONE, description="金融日历菜单")
command_factory.register_callback(r"^finance_calendar_earnings$", finance_calendar_earnings_callback, permission=Permission.NONE, description="财报日历")
command_factory.register_callback(r"^finance_calendar_ipo$", finance_calendar_ipo_callback, permission=Permission.NONE, description="IPO日历")
command_factory.register_callback(r"^finance_calendar_economic$", finance_calendar_economic_callback, permission=Permission.NONE, description="经济事件日历")
command_factory.register_callback(r"^finance_calendar_splits$", finance_calendar_splits_callback, permission=Permission.NONE, description="拆股日历")

command_factory.register_callback(r"^finance_close$", finance_close_callback, permission=Permission.NONE, description="关闭金融消息")

# 已迁移到统一缓存管理命令 /cleancache
# command_factory.register_command("finance_cleancache", finance_clean_cache_command, permission=Permission.ADMIN, description="清理金融模块缓存")


# =============================================================================
# Inline 执行入口
# =============================================================================

async def finance_inline_execute(args: str) -> dict:
    """
    Inline Query 执行入口 - 提供股票查询功能（仅支持精确股票代码）

    Args:
        args: 用户输入的股票代码，如 "AAPL" 或 "MSFT"

    Returns:
        dict: {
            "success": bool,
            "title": str,
            "message": str,
            "description": str,
            "error": str | None
        }
    """
    from utils.formatter import foldable_text_with_markdown_v2

    if not args or not args.strip():
        return {
            "success": False,
            "title": "❌ 请输入股票代码",
            "message": "请提供股票代码\\n\\n*使用方法:*\\n• `finance AAPL` \\\\- 苹果\\n• `finance MSFT` \\\\- 微软\\n• `finance TSLA` \\\\- 特斯拉\\n• `finance 0700.HK` \\\\- 腾讯\\n• `finance 600519.SS` \\\\- 茅台",
            "description": "请提供股票代码，如 AAPL, MSFT",
            "error": "未提供股票代码"
        }

    symbol = args.strip().split()[0].upper()

    try:
        # 获取股票信息（仅精确匹配）
        stock_data = await finance_service.get_stock_info(symbol)

        if not stock_data or stock_data.get('error'):
            error_msg = stock_data.get('message', '股票代码不存在') if stock_data else '股票代码不存在'
            return {
                "success": False,
                "title": f"❌ 未找到 {symbol}",
                "message": f"未找到股票代码 `{symbol}`\\n\\n💡 请使用精确的股票代码:\\n• 美股: AAPL, MSFT, GOOGL\\n• 港股: 0700\\.HK, 9988\\.HK\\n• A股: 600519\\.SS, 000001\\.SZ",
                "description": f"未找到: {symbol}",
                "error": error_msg
            }

        # 格式化结果
        formatted_result = format_stock_info(stock_data)

        name = stock_data.get('name', symbol)
        price = stock_data.get('current_price', 0)
        change_percent = stock_data.get('change_percent', 0)
        currency = stock_data.get('currency', 'USD')

        trend = "📈" if change_percent >= 0 else "📉"
        short_desc = f"{name} | {price:.2f} {currency} {trend} {change_percent:+.2f}%"

        return {
            "success": True,
            "title": f"📊 {symbol} - {name}",
            "message": foldable_text_with_markdown_v2(formatted_result),
            "description": short_desc,
            "error": None
        }

    except Exception as e:
        logger.error(f"Inline finance query failed: {e}")
        return {
            "success": False,
            "title": "❌ 查询失败",
            "message": f"查询股票失败: {str(e)}",
            "description": "查询失败",
            "error": str(e)
        }


# =============================================================================
# Inline 搜索入口（返回多个结果）
# =============================================================================

async def handle_inline_finance_search(
    keyword: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> list:
    """
    Inline 搜索股票（参考 appstore 的 handle_inline_appstore_search）
    返回多个搜索结果供用户选择

    Args:
        keyword: 搜索关键词，如 "apple" 或 "腾讯"
        context: Telegram context

    Returns:
        list: InlineQueryResult 列表
    """
    from telegram import InlineQueryResultArticle, InputTextMessageContent
    from uuid import uuid4
    from utils.formatter import foldable_text_with_markdown_v2

    if not keyword.strip():
        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="🔍 请输入搜索关键词",
                description="例如: finance apple$ 或 finance 腾讯$",
                input_message_content=InputTextMessageContent(
                    message_text="🔍 请输入股票名称或代码搜索\n\n"
                    "支持格式:\n"
                    "• finance apple$\n"
                    "• finance 腾讯$\n"
                    "• finance AAPL$"
                ),
            )
        ]

    try:
        # 搜索股票
        logger.info(f"Inline Finance 搜索: '{keyword}'")
        search_results = await finance_service.search_stocks(keyword, limit=10)

        if not search_results:
            return [
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title="❌ 未找到结果",
                    description=f"关键词: {keyword}",
                    input_message_content=InputTextMessageContent(
                        message_text=f"❌ 未找到与 \"{keyword}\" 相关的股票"
                    ),
                )
            ]

        # 构建搜索结果列表（最多10个）
        results = []
        for stock in search_results[:10]:
            symbol = stock.get('symbol', '')
            name = stock.get('name', symbol)
            exchange = stock.get('exchange', '')
            stock_type = stock.get('type', '')

            if not symbol:
                continue

            # 构建描述
            description_parts = []
            if exchange:
                description_parts.append(exchange)
            if stock_type:
                description_parts.append(stock_type)

            description = " | ".join(description_parts) if description_parts else "点击查看详情"

            # 获取股票详细信息
            try:
                stock_data = await finance_service.get_stock_info(symbol)

                if stock_data and not stock_data.get('error'):
                    # 格式化股票信息
                    formatted_result = format_stock_info(stock_data)
                    message_text = foldable_text_with_markdown_v2(formatted_result)
                    parse_mode = "MarkdownV2"

                    # 更新描述，包含价格信息
                    price = stock_data.get('current_price', 0)
                    change_percent = stock_data.get('change_percent', 0)
                    currency = stock_data.get('currency', 'USD')
                    trend = "📈" if change_percent >= 0 else "📉"
                    description = f"{price:.2f} {currency} {trend} {change_percent:+.2f}%"
                else:
                    # 降级：只显示基本信息
                    message_text = f"📊 *{name}* ({symbol})\n\n❌ 获取详细信息失败\n\n💡 请使用 `/finance {symbol}` 重试"
                    parse_mode = "Markdown"

            except Exception as e:
                logger.warning(f"获取股票 {symbol} 详情失败: {e}")
                # 降级：只显示基本信息
                message_text = f"📊 *{name}* ({symbol})\n\n❌ 获取详细信息失败\n\n💡 请使用 `/finance {symbol}` 重试"
                parse_mode = "Markdown"

            results.append(
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title=f"📊 {symbol} - {name}",
                    description=description,
                    input_message_content=InputTextMessageContent(
                        message_text=message_text,
                        parse_mode=parse_mode,
                    ),
                )
            )

        return results

    except Exception as e:
        logger.error(f"Inline Finance 搜索失败: {e}", exc_info=True)
        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="❌ 搜索失败",
                description=str(e)[:100],
                input_message_content=InputTextMessageContent(
                    message_text=f"❌ 搜索失败: {str(e)}"
                ),
            )
        ]