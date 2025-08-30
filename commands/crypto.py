import logging
import datetime
from typing import Optional, Dict, List

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown

from utils.command_factory import command_factory
from utils.permissions import Permission
from utils.config_manager import get_config
from utils.formatter import foldable_text_v2, foldable_text_with_markdown_v2
from utils.message_manager import send_message_with_auto_delete, delete_user_command, _schedule_deletion, send_error, send_success, send_help

# 全局变量
cache_manager = None
httpx_client = None

def set_dependencies(c_manager, h_client):
    global cache_manager, httpx_client
    cache_manager = c_manager
    httpx_client = h_client

# CoinMarketCap URLs (需要API key)
CMC_URL = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest"

# CoinGecko URLs (免费，无需API key)
COINGECKO_MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"
COINGECKO_TRENDING_URL = "https://api.coingecko.com/api/v3/search/trending"
COINGECKO_GLOBAL_URL = "https://api.coingecko.com/api/v3/global"

async def get_crypto_price(symbol: str, convert_currency: str) -> Optional[Dict]:
    """从API获取加密货币价格，并缓存结果"""
    cache_key = f"crypto_{symbol.lower()}_{convert_currency.lower()}"
    cached_data = await cache_manager.load_cache(cache_key, subdirectory="crypto")
    if cached_data:
        logging.info(f"使用缓存的加密货币数据: {symbol} -> {convert_currency}")
        return cached_data

    config = get_config()
    if not config.cmc_api_key:
        logging.error("CoinMarketCap API Key 未配置")
        return None

    headers = {"Accepts": "application/json", "X-CMC_PRO_API_KEY": config.cmc_api_key}
    params = {"symbol": symbol.upper(), "convert": convert_currency.upper()}

    try:
        response = await httpx_client.get(CMC_URL, headers=headers, params=params, timeout=20)
        if response.status_code == 200:
            data = response.json()
            if data.get("status", {}).get("error_code") == 0 and data.get("data"):
                await cache_manager.save_cache(cache_key, data, subdirectory="crypto")
                return data
            else:
                logging.warning(f"CMC API 返回错误: {data.get('status')}")
        else:
            logging.warning(f"CMC API 请求失败: HTTP {response.status_code}")
    except Exception as e:
        logging.error(f"CMC API 请求异常: {e}")
    return None

async def get_coingecko_markets(vs_currency: str = "usd", order: str = "market_cap_desc", per_page: int = 10, page: int = 1, sort_by_change: str = None) -> Optional[List[Dict]]:
    """从CoinGecko获取市场数据"""
    # 为了获取涨跌幅排行，我们需要获取更多数据然后客户端排序
    actual_per_page = per_page if not sort_by_change else 100  # 获取更多数据用于排序
    cache_key = f"coingecko_markets_{vs_currency}_{order}_{sort_by_change or 'none'}_{per_page}_{page}"
    
    cached_data = await cache_manager.load_cache(cache_key, subdirectory="crypto")
    if cached_data:
        logging.info(f"使用缓存的CoinGecko市场数据: {order}")
        return cached_data

    params = {
        "vs_currency": vs_currency,
        "order": order,
        "per_page": actual_per_page,
        "page": page,
        "sparkline": "false",
        "price_change_percentage": "24h"
    }

    try:
        response = await httpx_client.get(COINGECKO_MARKETS_URL, params=params, timeout=20)
        if response.status_code == 200:
            data = response.json()
            if data:
                # 如果需要按价格变化排序，在客户端进行排序
                if sort_by_change:
                    # 过滤掉没有价格变化数据的币种
                    valid_coins = [coin for coin in data if coin.get('price_change_percentage_24h') is not None]
                    
                    if sort_by_change == "gainers":
                        # 涨幅榜：按24小时价格变化降序排列
                        data = sorted(valid_coins, key=lambda x: x['price_change_percentage_24h'], reverse=True)
                    elif sort_by_change == "losers":
                        # 跌幅榜：按24小时价格变化升序排列  
                        data = sorted(valid_coins, key=lambda x: x['price_change_percentage_24h'])
                
                # 取前per_page个结果
                result = data[:per_page]
                await cache_manager.save_cache(cache_key, result, subdirectory="crypto")
                return result
        else:
            logging.warning(f"CoinGecko Markets API 请求失败: HTTP {response.status_code}")
    except Exception as e:
        logging.error(f"CoinGecko Markets API 请求异常: {e}")
    return None

async def get_coingecko_trending() -> Optional[Dict]:
    """从CoinGecko获取热门搜索数据"""
    cache_key = "coingecko_trending"
    cached_data = await cache_manager.load_cache(cache_key, subdirectory="crypto")
    if cached_data:
        logging.info("使用缓存的CoinGecko热门搜索数据")
        return cached_data

    try:
        response = await httpx_client.get(COINGECKO_TRENDING_URL, timeout=20)
        if response.status_code == 200:
            data = response.json()
            if data:
                await cache_manager.save_cache(cache_key, data, subdirectory="crypto")
                return data
        else:
            logging.warning(f"CoinGecko Trending API 请求失败: HTTP {response.status_code}")
    except Exception as e:
        logging.error(f"CoinGecko Trending API 请求异常: {e}")
    return None

async def get_coingecko_single_coin(coin_id: str, vs_currency: str = "usd") -> Optional[Dict]:
    """从CoinGecko获取单个币种价格"""
    cache_key = f"coingecko_single_{coin_id}_{vs_currency}"
    cached_data = await cache_manager.load_cache(cache_key, subdirectory="crypto")
    if cached_data:
        logging.info(f"使用缓存的CoinGecko单币数据: {coin_id}")
        return cached_data

    params = {
        "ids": coin_id,
        "vs_currency": vs_currency,
        "order": "market_cap_desc",
        "per_page": 1,
        "page": 1,
        "sparkline": "false",
        "price_change_percentage": "24h,7d"
    }

    try:
        response = await httpx_client.get(COINGECKO_MARKETS_URL, params=params, timeout=20)
        if response.status_code == 200:
            data = response.json()
            if data and len(data) > 0:
                coin_data = data[0]
                await cache_manager.save_cache(cache_key, coin_data, subdirectory="crypto")
                return coin_data
        else:
            logging.warning(f"CoinGecko Single Coin API 请求失败: HTTP {response.status_code}")
    except Exception as e:
        logging.error(f"CoinGecko Single Coin API 请求异常: {e}")
    return None

def format_crypto_ranking(coins: List[Dict], title: str, vs_currency: str = "usd") -> str:
    """格式化加密货币排行榜"""
    if not coins:
        return f"❌ {title} 数据获取失败"
    
    currency_symbol = {"usd": "$", "cny": "¥", "eur": "€"}.get(vs_currency.lower(), vs_currency.upper())
    result = f"📊 *{title}*\n\n"
    
    # 检查是否为交易量榜
    is_volume_ranking = "交易量" in title
    
    for i, coin in enumerate(coins[:10], 1):
        name = coin.get("name", "")
        symbol = coin.get("symbol", "").upper()
        price = coin.get("current_price", 0)
        change_24h = coin.get("price_change_percentage_24h", 0)
        market_cap_rank = coin.get("market_cap_rank", i)
        total_volume = coin.get("total_volume", 0)
        
        trend_emoji = "📈" if change_24h >= 0 else "📉"
        change_sign = "+" if change_24h >= 0 else ""
        
        result += f"`{i:2d}.` {trend_emoji} *{symbol}* - {name}\n"
        
        if is_volume_ranking and total_volume > 0:
            # 交易量榜显示交易量
            if total_volume >= 1e9:
                volume_str = f"{total_volume/1e9:.1f}B"
            elif total_volume >= 1e6:
                volume_str = f"{total_volume/1e6:.1f}M"
            else:
                volume_str = f"{total_volume:,.0f}"
            result += f"     交易量: `{currency_symbol}{volume_str}` | 价格: `({change_sign}{change_24h:.2f}%)`"
        else:
            # 其他榜单显示价格
            if price < 0.01:
                price_str = f"{price:.6f}"
            elif price < 1:
                price_str = f"{price:.4f}"
            else:
                price_str = f"{price:,.2f}"
            result += f"     `{currency_symbol}{price_str}` `({change_sign}{change_24h:.2f}%)`"
            
        if market_cap_rank:
            result += f" `#{market_cap_rank}`"
        result += "\n\n"
    
    result += f"_数据来源: CoinGecko ({datetime.datetime.now().strftime('%H:%M:%S')})_"
    return result

def format_trending_coins(trending_data: Dict) -> str:
    """格式化热门搜索币种"""
    if not trending_data or "coins" not in trending_data:
        return "❌ 热门搜索数据获取失败"
    
    result = "🔥 *热门搜索币种*\n\n"
    
    for i, coin_wrapper in enumerate(trending_data["coins"][:10], 1):
        coin = coin_wrapper.get("item", {})
        name = coin.get("name", "")
        symbol = coin.get("symbol", "").upper()
        market_cap_rank = coin.get("market_cap_rank")
        
        # 获取价格变化数据
        price_data = coin.get("data", {})
        price_btc = price_data.get("price_btc", "")
        
        result += f"`{i:2d}.` 🔥 *{symbol}* - {name}"
        if market_cap_rank:
            result += f" `#{market_cap_rank}`"
        if price_btc:
            result += f"\n     `{float(price_btc):.8f} BTC`"
        result += "\n\n"
    
    result += f"_数据来源: CoinGecko ({datetime.datetime.now().strftime('%H:%M:%S')})_"
    return result

def format_crypto_data(data: Dict, symbol: str, amount: float, convert_currency: str) -> str:
    """格式化加密货币数据（更健壮的版本）"""
    symbol_upper = symbol.upper()
    
    # --- 你的健壮逻辑，保持不变 ---
    data_map = data.get("data")
    if not data_map:
        return f"❌ API 响应中未找到 'data' 字段。"
        
    coin_data_obj = data_map.get(symbol_upper)
    if not coin_data_obj:
        if list(data_map.values()):
            coin_data_obj = list(data_map.values())[0]
        else:
            return f"❌ 无法在API响应中找到 `{escape_markdown(symbol_upper, version=2)}` 的数据。"
    
    if isinstance(coin_data_obj, list):
        if not coin_data_obj:
            return f"❌ `{escape_markdown(symbol_upper, version=2)}` 的数据列表为空。"
        coin_data = coin_data_obj[0]
    else:
        coin_data = coin_data_obj

    if not isinstance(coin_data, dict):
        return f"❌ 解析到的 `{escape_markdown(symbol_upper, version=2)}` 数据不是有效格式。"
    # --- 逻辑结束 ---

    name = coin_data.get("name", "")  # 移除 escape_markdown
    lines = [f"🪙 *{escape_markdown(symbol_upper, version=2)} ({name}) 价格*"]

    # ✨ 新增：我们需要一个变量来存储更新时间
    last_updated_str = ""
    
    convert_currency_upper = convert_currency.upper()
    quote_data = coin_data.get("quote", {}).get(convert_currency_upper)
    
    if quote_data and quote_data.get("price") is not None:
        price = quote_data.get("price")
        # ✨ 修改点：使用传入的 amount 计算总价
        total = price * amount
        decimals = 4 if total < 1 else 2
        # ✨ 修改点：显示传入的 amount
        lines.append(f"`{amount:g} {escape_markdown(symbol_upper, version=2)}` = `{total:,.{decimals}f} {escape_markdown(convert_currency_upper, version=2)}`")

        change_24h = quote_data.get("percent_change_24h")
        change_7d = quote_data.get("percent_change_7d")

        if change_24h is not None:
            emoji_24h = "📈" if change_24h >= 0 else "📉"
            lines.append(f"{emoji_24h} 24h变化: `{change_24h:+.2f}%`")
            
        if change_7d is not None:
            emoji_7d = "📈" if change_7d >= 0 else "📉"
            lines.append(f"{emoji_7d} 7d变化: `{change_7d:+.2f}%`")

        # ✨ 新增：获取并格式化更新时间
        if not last_updated_str and quote_data.get("last_updated"):
            try:
                # 将ISO 8601格式的时间字符串转换为datetime对象
                dt_utc = datetime.datetime.fromisoformat(quote_data["last_updated"].replace('Z', '+00:00'))
                # 转换为北京时间 (UTC+8)
                dt_beijing = dt_utc.astimezone(datetime.timezone(datetime.timedelta(hours=8)))
                # 格式化为更易读的字符串
                last_updated_str = dt_beijing.strftime('%Y-%m-%d %H:%M:%S')
            except Exception as e:
                logging.warning(f"解析 last_updated 时间戳失败: {e}")
        
    else:
        lines.append(f"`{escape_markdown(convert_currency_upper, version=2)}` 价格获取失败。")

    # ✨ 修改：在数据来源后面加上时间
    if last_updated_str:
        lines.append(f"\n_数据来源: CoinMarketCap (更新于 {last_updated_str})_")
    else:
        lines.append("\n_数据来源: CoinMarketCap_")
        
    return "\n".join(lines)


async def crypto_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat: return
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)

    if not context.args:
        # 显示主菜单
        keyboard = [
            [
                InlineKeyboardButton("💰 查询币价", callback_data="crypto_price_help"),
                InlineKeyboardButton("🔥 热门币种", callback_data="crypto_trending")
            ],
            [
                InlineKeyboardButton("📈 涨幅榜", callback_data="crypto_gainers"),
                InlineKeyboardButton("📉 跌幅榜", callback_data="crypto_losers")
            ],
            [
                InlineKeyboardButton("💎 市值榜", callback_data="crypto_market_cap"),
                InlineKeyboardButton("📊 交易量榜", callback_data="crypto_volume")
            ],
            [
                InlineKeyboardButton("❌ 关闭", callback_data="crypto_close")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        help_text = """🚀 *加密货币数据查询*

🔍 功能介绍:
• **查询币价**: 输入币种代码查看价格信息
• **热门币种**: 查看当前热门搜索的币种  
• **各种排行榜**: 涨跌幅、市值、交易量等

💡 快速使用:
`/crypto btc` \- 查询比特币价格
`/crypto eth 2 usd` \- 查询2个ETH对USD价格

请选择功能:"""
        
        await send_message_with_auto_delete(
            context=context,
            chat_id=update.effective_chat.id,
            text=foldable_text_with_markdown_v2(help_text),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=reply_markup
        )
        return

    # ✨ 修改点：更智能的参数解析，支持数量
    symbol = context.args[0]
    amount = 1.0
    convert_currency = "CNY"
    
    if len(context.args) > 1:
        # 检查第二个参数是数量还是货币
        try:
            amount = float(context.args[1])
            # 如果成功，第三个参数（如果存在）就是货币
            if len(context.args) > 2:
                convert_currency = context.args[2]
        except ValueError:
            # 如果失败，说明第二个参数是货币
            amount = 1.0
            convert_currency = context.args[1]

    safe_symbol = escape_markdown(symbol, version=2)
    message = await context.bot.send_message(chat_id=update.effective_chat.id, text=f"🔍 正在查询 *{safe_symbol}* 的价格\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)

    data = await get_crypto_price(symbol, convert_currency)
    
    if data:
        result_text = format_crypto_data(data, symbol, amount, convert_currency)
    else:
        result_text = f"❌ 无法获取 *{safe_symbol}* 的价格数据，请检查币种或目标货币名称是否正确。"

    await message.edit_text(
        foldable_text_with_markdown_v2(result_text),
        parse_mode=ParseMode.MARKDOWN_V2, 
        disable_web_page_preview=True
    )

    config = get_config()
    if config.auto_delete_delay > 0:
        await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)

# =============================================================================
# Callback 处理器
# =============================================================================

async def crypto_price_help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """显示币价查询帮助"""
    query = update.callback_query
    await query.answer("请在命令后输入币种代码，如: /crypto btc")
    
    help_text = """💰 *币价查询说明*

请使用以下格式查询加密货币价格:
`/crypto [币种] [数量] [目标货币]`

**示例:**
• `/crypto btc` \- 查询1个BTC对CNY的价格  
• `/crypto btc 2` \- 查询2个BTC对CNY的价格
• `/crypto eth usd` \- 查询1个ETH对USD的价格
• `/crypto eth 2 usd` \- 查询2个ETH对USD的价格

**支持的目标货币:**
• CNY, USD, EUR, JPY 等

请发送新消息进行查询"""

    keyboard = [[InlineKeyboardButton("🔙 返回主菜单", callback_data="crypto_main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text=foldable_text_with_markdown_v2(help_text),
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=reply_markup
    )

async def crypto_main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """返回主菜单"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [
            InlineKeyboardButton("💰 查询币价", callback_data="crypto_price_help"),
            InlineKeyboardButton("🔥 热门币种", callback_data="crypto_trending")
        ],
        [
            InlineKeyboardButton("📈 涨幅榜", callback_data="crypto_gainers"),
            InlineKeyboardButton("📉 跌幅榜", callback_data="crypto_losers")
        ],
        [
            InlineKeyboardButton("💎 市值榜", callback_data="crypto_market_cap"),
            InlineKeyboardButton("📊 交易量榜", callback_data="crypto_volume")
        ],
        [
            InlineKeyboardButton("❌ 关闭", callback_data="crypto_close")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    help_text = """🚀 *加密货币数据查询*

🔍 功能介绍:
• **查询币价**: 输入币种代码查看价格信息
• **热门币种**: 查看当前热门搜索的币种
• **各种排行榜**: 涨跌幅、市值、交易量等

💡 快速使用:
`/crypto btc` \- 查询比特币价格
`/crypto eth 2 usd` \- 查询2个ETH对USD价格

请选择功能:"""
    
    await query.edit_message_text(
        text=foldable_text_with_markdown_v2(help_text),
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=reply_markup
    )

async def crypto_trending_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """显示热门币种"""
    query = update.callback_query
    await query.answer("正在获取热门币种...")
    
    loading_message = "🔥 正在获取热门搜索币种... ⏳"
    await query.edit_message_text(
        text=foldable_text_v2(loading_message),
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    try:
        trending_data = await get_coingecko_trending()
        
        if trending_data:
            result_text = format_trending_coins(trending_data)
            
            keyboard = [
                [
                    InlineKeyboardButton("🔄 刷新", callback_data="crypto_trending"),
                    InlineKeyboardButton("🔙 返回", callback_data="crypto_main_menu")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                text=foldable_text_with_markdown_v2(result_text),
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=reply_markup
            )
        else:
            error_text = "❌ 获取热门币种失败，请稍后重试"
            keyboard = [[InlineKeyboardButton("🔙 返回主菜单", callback_data="crypto_main_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                text=foldable_text_v2(error_text),
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=reply_markup
            )
            
    except Exception as e:
        logging.error(f"获取热门币种时发生错误: {e}")
        error_text = f"❌ 获取热门币种时发生错误: {str(e)}"
        
        await query.edit_message_text(
            text=foldable_text_v2(error_text),
            parse_mode=ParseMode.MARKDOWN_V2
        )

async def crypto_ranking_callback(ranking_type: str, title: str, sort_param: str, query: CallbackQuery) -> None:
    """通用排行榜回调处理"""
    loading_message = f"📊 正在获取{title}... ⏳"
    await query.edit_message_text(
        text=foldable_text_v2(loading_message),
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    try:
        # 根据排行榜类型决定如何获取数据
        if sort_param in ["gainers", "losers"]:
            # 涨跌幅榜需要客户端排序
            coins_data = await get_coingecko_markets(vs_currency="usd", order="market_cap_desc", per_page=10, sort_by_change=sort_param)
        elif sort_param == "volume_desc":
            # 交易量榜
            coins_data = await get_coingecko_markets(vs_currency="usd", order="volume_desc", per_page=10)
        else:
            # 市值榜和其他
            coins_data = await get_coingecko_markets(vs_currency="usd", order=sort_param, per_page=10)
        
        if coins_data:
            result_text = format_crypto_ranking(coins_data, title, "usd")
            
            keyboard = [
                [
                    InlineKeyboardButton(f"🔄 刷新", callback_data=ranking_type),
                    InlineKeyboardButton("🔙 返回", callback_data="crypto_main_menu")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                text=foldable_text_with_markdown_v2(result_text),
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=reply_markup
            )
        else:
            error_text = f"❌ 获取{title}失败，请稍后重试"
            keyboard = [[InlineKeyboardButton("🔙 返回主菜单", callback_data="crypto_main_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                text=foldable_text_v2(error_text),
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=reply_markup
            )
            
    except Exception as e:
        logging.error(f"获取{title}时发生错误: {e}")
        error_text = f"❌ 获取{title}时发生错误: {str(e)}"
        
        await query.edit_message_text(
            text=foldable_text_v2(error_text),
            parse_mode=ParseMode.MARKDOWN_V2
        )

async def crypto_gainers_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """涨幅榜"""
    query = update.callback_query
    await query.answer("正在获取涨幅榜...")
    await crypto_ranking_callback("crypto_gainers", "24小时涨幅榜", "gainers", query)

async def crypto_losers_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """跌幅榜"""
    query = update.callback_query  
    await query.answer("正在获取跌幅榜...")
    await crypto_ranking_callback("crypto_losers", "24小时跌幅榜", "losers", query)

async def crypto_market_cap_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """市值榜"""
    query = update.callback_query
    await query.answer("正在获取市值榜...")
    await crypto_ranking_callback("crypto_market_cap", "市值排行榜", "market_cap_desc", query)

async def crypto_volume_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """交易量榜"""
    query = update.callback_query
    await query.answer("正在获取交易量榜...")
    await crypto_ranking_callback("crypto_volume", "24小时交易量榜", "volume_desc", query)

async def crypto_close_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理关闭按钮点击"""
    query = update.callback_query
    await query.answer("消息已关闭")
    
    if not query:
        return
        
    try:
        await query.delete_message()
    except Exception as e:
        logging.error(f"删除消息时发生错误: {e}")
        try:
            await query.edit_message_text(
                text=foldable_text_v2("✅ 消息已关闭"),
                parse_mode=ParseMode.MARKDOWN_V2
            )
        except:
            pass

async def crypto_clean_cache_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /crypto_cleancache command to clear Apple Services related caches."""
    if not update.message or not update.effective_chat:
        return
    try:
        await context.bot_data["cache_manager"].clear_cache(subdirectory="crypto", 
        key_prefix="crypto_")
        await context.bot_data["cache_manager"].clear_cache(subdirectory="crypto", 
        key_prefix="coingecko_")
        success_message = "✅ 加密货币价格缓存已清理。"
        await send_success(context, update.effective_chat.id, foldable_text_v2(success_message), parse_mode="MarkdownV2")
        await delete_user_command(context, update.effective_chat.id, update.message.message_id)
        return
    except Exception as e:
        logging.error(f"Error clearing Crypto cache: {e}")
        error_message = f"❌ 清理加密货币缓存时发生错误: {e!s}"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        await delete_user_command(context, update.effective_chat.id, update.message.message_id)
        return

# =============================================================================
# 注册命令和回调
# =============================================================================

command_factory.register_command(
    "crypto",
    crypto_command,
    permission=Permission.USER,
    description="查询加密货币价格和排行榜，例如 /crypto btc 0.5 usd"
)

# 注册回调处理器
command_factory.register_callback(r"^crypto_main_menu$", crypto_main_menu_callback, permission=Permission.USER, description="加密货币主菜单")
command_factory.register_callback(r"^crypto_price_help$", crypto_price_help_callback, permission=Permission.USER, description="币价查询帮助") 
command_factory.register_callback(r"^crypto_trending$", crypto_trending_callback, permission=Permission.USER, description="热门币种")
command_factory.register_callback(r"^crypto_gainers$", crypto_gainers_callback, permission=Permission.USER, description="涨幅榜")
command_factory.register_callback(r"^crypto_losers$", crypto_losers_callback, permission=Permission.USER, description="跌幅榜")
command_factory.register_callback(r"^crypto_market_cap$", crypto_market_cap_callback, permission=Permission.USER, description="市值榜")
command_factory.register_callback(r"^crypto_volume$", crypto_volume_callback, permission=Permission.USER, description="交易量榜")
command_factory.register_callback(r"^crypto_close$", crypto_close_callback, permission=Permission.USER, description="关闭加密货币消息")

# 已迁移到统一缓存管理命令 /cleancache
# command_factory.register_command(
#     "crypto_cleancache", crypto_clean_cache_command, permission=Permission.ADMIN, description="清理加密货币缓存"
# )
