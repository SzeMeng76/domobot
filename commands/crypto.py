import logging
import datetime
from typing import Optional, Dict

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown

from utils.command_factory import command_factory
from utils.permissions import Permission
from utils.config_manager import get_config
from utils.formatter import foldable_text_v2, foldable_text_with_markdown_v2
from utils.message_manager import send_message_with_auto_delete, delete_user_command, _schedule_deletion

# 全局变量
cache_manager = None
httpx_client = None

def set_dependencies(c_manager, h_client):
    global cache_manager, httpx_client
    cache_manager = c_manager
    httpx_client = h_client

CMC_URL = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest"

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

    name = escape_markdown(coin_data.get("name", ""), version=2)
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
        help_text = (
            "*加密货币查询帮助*\n\n"
            "`/crypto [币种] [数量] [目标货币]`\n\n"
            "**示例:**\n"
            "• `/crypto btc` \\- 查询1个BTC对CNY的价格\n"
            "• `/crypto btc 0\\.5` \\- 查询0\\.5个BTC对CNY的价格\n"
            "• `/crypto eth usd` \\- 查询1个ETH对USD的价格\n"
            "• `/crypto eth 0\\.5 usd` \\- 查询0\\.5个ETH对USD的价格"
        )
        await send_message_with_auto_delete(context, update.effective_chat.id, help_text, parse_mode=ParseMode.MARKDOWN_V2)
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

command_factory.register_command(
    "crypto",
    crypto_command,
    permission=Permission.USER,
    description="查询加密货币价格，例如 /crypto btc 0.5 usd"
)
