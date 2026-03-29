import logging
import json
from typing import Optional, Dict

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown

from utils.command_factory import command_factory
from utils.permissions import Permission
from utils.config_manager import get_config
from utils.formatter import foldable_text_v2, foldable_text_with_markdown_v2
from utils.message_manager import send_message_with_auto_delete, delete_user_command, _schedule_deletion, send_error, send_success

# 全局变量
cache_manager = None
httpx_client = None

def set_dependencies(c_manager, h_client):
    global cache_manager, httpx_client
    cache_manager = c_manager
    httpx_client = h_client

# BIN查询API配置
BIN_API_URL = "https://api.dy.ax/v1/finance/bin"
COUNTRY_DATA_URL = "https://raw.githubusercontent.com/umpirsky/country-list/master/data/zh_CN/country.json"
CURRENCY_DATA_URL = "https://raw.githubusercontent.com/umpirsky/currency-list/refs/heads/master/data/zh_CN/currency.json"

class BINMapping:
    """映射类，用于转换API返回的英文值为中文显示"""
    brand = {
        'VISA': 'Visa',
        'MASTERCARD': 'Master Card',
        'AMERICAN EXPRESS': 'Amex',
        'CHINA UNION PAY': '银联',
        'CHINA UNION': '银联',
    }
    
    card_type = {
        'CREDIT': '贷记',
        'DEBIT': '借记',
    }

async def get_country_data() -> Dict:
    """获取国家数据映射，并缓存结果"""
    cache_key = "country_data"
    cached_data = await cache_manager.load_cache(cache_key, subdirectory="bin")
    if cached_data:
        logging.info("使用缓存的国家数据")
        return cached_data

    try:
        response = await httpx_client.get(COUNTRY_DATA_URL, timeout=20)
        if response.status_code == 200:
            data = response.json()
            await cache_manager.save_cache(cache_key, data, subdirectory="bin")
            return data
        else:
            logging.warning(f"获取国家数据失败: HTTP {response.status_code}")
    except Exception as e:
        logging.error(f"获取国家数据异常: {e}")
    return {}

async def get_currency_data() -> Dict:
    """获取货币数据映射，并缓存结果"""
    cache_key = "currency_data"
    cached_data = await cache_manager.load_cache(cache_key, subdirectory="bin")
    if cached_data:
        logging.info("使用缓存的货币数据")
        return cached_data

    try:
        response = await httpx_client.get(CURRENCY_DATA_URL, timeout=20)
        if response.status_code == 200:
            data = response.json()
            await cache_manager.save_cache(cache_key, data, subdirectory="bin")
            return data
        else:
            logging.warning(f"获取货币数据失败: HTTP {response.status_code}")
    except Exception as e:
        logging.error(f"获取货币数据异常: {e}")
    return {}

async def get_bin_info(bin_number: str) -> Optional[Dict]:
    """从API获取BIN信息，并缓存结果"""
    cache_key = f"bin_{bin_number}"
    cached_data = await cache_manager.load_cache(cache_key, subdirectory="bin")
    if cached_data:
        logging.info(f"使用缓存的BIN数据: {bin_number}")
        return cached_data

    config = get_config()
    if not config.bin_api_key:
        logging.error("BIN API Key 未配置")
        return None

    headers = {"Accept": "application/json"}
    params = {"number": bin_number, "apiKey": config.bin_api_key}

    try:
        response = await httpx_client.get(BIN_API_URL, headers=headers, params=params, timeout=20)
        if response.status_code == 200:
            data = response.json()
            if data.get("data"):
                await cache_manager.save_cache(cache_key, data, subdirectory="bin")
                return data
            else:
                logging.warning(f"BIN API 返回空数据: {data}")
        elif response.status_code == 400:
            logging.warning(f"BIN API 请求参数错误: {bin_number}, response: {response.text}")
        elif response.status_code == 401:
            logging.warning(f"BIN API 认证失败, response: {response.text}")
        elif response.status_code == 429:
            logging.warning(f"BIN API 请求频率超限, response: {response.text}")
        else:
            logging.warning(f"BIN API 请求失败: HTTP {response.status_code}, response: {response.text}")
    except Exception as e:
        logging.error(f"BIN API 请求异常: {e}")
    return None

def format_bin_data(bin_number: str, data: Dict, country_data: Dict, currency_data: Dict) -> str:
    """格式化BIN数据"""
    bin_data = data.get("data", {})
    safe_bin = escape_markdown(bin_number, version=2)
    
    lines = [f"🔢 *BIN卡头: {safe_bin}*"]
    
    # 卡片品牌
    brand = bin_data.get("card_brand", "")
    if brand in BINMapping.brand:
        brand = BINMapping.brand[brand]
    if brand:
        safe_brand = escape_markdown(brand, version=2)
        lines.append(f"💳 品牌: `{safe_brand}`")
    
    # 卡片类型
    card_type = bin_data.get("card_type", "")
    if card_type in BINMapping.card_type:
        card_type = BINMapping.card_type[card_type]
    if card_type:
        safe_type = escape_markdown(card_type, version=2)
        lines.append(f"🔖 类型: `{safe_type}`")
    
    # 卡片等级
    category = bin_data.get("card_category", "")
    if category:
        safe_category = escape_markdown(category, version=2)
        lines.append(f"💹 等级: `{safe_category}`")
    
    lines.append("")  # 空行分隔
    
    # 国家信息
    country = bin_data.get("country", "")
    country_code = bin_data.get("country_code", "")
    if country_code and country_code in country_data:
        country = country_data[country_code]
    if country:
        safe_country = escape_markdown(country, version=2)
        lines.append(f"🗺 国家: `{safe_country}`")
    
    # 货币信息
    currency_code = bin_data.get("currency_code", "")
    if currency_code:
        currency_name = currency_code  # 默认显示货币代码
        if currency_code in currency_data:
            currency_name = currency_data[currency_code]
        safe_currency = escape_markdown(currency_name, version=2)
        lines.append(f"💸 货币: `{safe_currency}`")
    
    # 发卡银行
    issuer = bin_data.get("issuer", "")
    if issuer:
        safe_issuer = escape_markdown(issuer, version=2)
        lines.append(f"🏦 银行: `{safe_issuer}`")
    
    lines.append("")  # 空行分隔
    
    # 预付卡信息
    is_prepaid = bin_data.get("is_prepaid")
    if is_prepaid is not None:
        prepaid_status = "✓" if is_prepaid else "×"
        lines.append(f"💰 预付卡: `{prepaid_status}`")
    
    # 商业卡信息
    is_commercial = bin_data.get("is_commercial")
    if is_commercial is not None:
        commercial_status = "✓" if is_commercial else "×"
        lines.append(f"🧾 商业卡: `{commercial_status}`")
    
    lines.append("\n_数据来源: DY API_")
    
    return "\n".join(lines)

async def bin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat: 
        return
    await delete_user_command(context, update.effective_chat.id, update.message.message_id)

    if not context.args:
        help_text = (
            "*BIN卡头查询帮助*\n\n"
            "`/bin [BIN号码]`\n\n"
            "**示例:**\n"
            "• `/bin 123456` \\- 查询BIN为123456的卡片信息\n"
            "• `/bin 12345678` \\- 查询BIN为12345678的卡片信息\n\n"
            "**说明:**\n"
            "• BIN号码通常是信用卡号的前6\\-8位数字\n"
            "• 可以查询卡片品牌、类型、发卡银行等信息"
        )
        await send_message_with_auto_delete(context, update.effective_chat.id, help_text, parse_mode=ParseMode.MARKDOWN_V2)
        return

    bin_number = context.args[0].strip()
    
    # 验证BIN号码
    if not bin_number.isdigit():
        error_text = "❌ BIN号码必须为数字"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_text), parse_mode="MarkdownV2")
        return
    
    if len(bin_number) < 6 or len(bin_number) > 8:
        error_text = "❌ BIN号码长度必须在6-8位之间"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_text), parse_mode="MarkdownV2")
        return

    safe_bin = escape_markdown(bin_number, version=2)
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id, 
        text=f"🔍 正在查询BIN *{safe_bin}* 的信息\\.\\.\\.", 
        parse_mode=ParseMode.MARKDOWN_V2
    )

    # 获取BIN信息、国家数据和货币数据
    bin_data = await get_bin_info(bin_number)
    country_data = await get_country_data()
    currency_data = await get_currency_data()
    
    if bin_data:
        result_text = format_bin_data(bin_number, bin_data, country_data, currency_data)
    else:
        config = get_config()
        if not config.bin_api_key:
            result_text = f"❌ BIN API Key 未配置，请联系管理员。"
        else:
            result_text = f"❌ 无法获取BIN *{safe_bin}* 的信息，请检查号码是否正确或稍后重试。"

    await message.edit_text(
        foldable_text_with_markdown_v2(result_text),
        parse_mode=ParseMode.MARKDOWN_V2, 
        disable_web_page_preview=True
    )

    config = get_config()
    if config.auto_delete_delay > 0:
        await _schedule_deletion(context, update.effective_chat.id, message.message_id, config.auto_delete_delay)

async def bin_clean_cache_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /bin_cleancache 命令以清理BIN相关缓存"""
    if not update.message or not update.effective_chat:
        return
    try:
        await context.bot_data["cache_manager"].clear_cache(subdirectory="bin", key_prefix="bin_")
        await context.bot_data["cache_manager"].clear_cache(subdirectory="bin", key_prefix="country_")
        await context.bot_data["cache_manager"].clear_cache(subdirectory="bin", key_prefix="currency_")
        success_message = "✅ BIN查询缓存已清理。"
        await send_success(context, update.effective_chat.id, foldable_text_v2(success_message), parse_mode="MarkdownV2")
        await delete_user_command(context, update.effective_chat.id, update.message.message_id)
        return
    except Exception as e:
        logging.error(f"Error clearing BIN cache: {e}")
        error_message = f"❌ 清理BIN缓存时发生错误: {e!s}"
        await send_error(context, update.effective_chat.id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        await delete_user_command(context, update.effective_chat.id, update.message.message_id)
        return

# 注册命令
command_factory.register_command(
    "bin",
    bin_command,
    permission=Permission.USER,
    description="查询信用卡BIN信息，例如 /bin 123456"
)

# 已迁移到统一缓存管理命令 /cleancache
# command_factory.register_command(
#     "bin_cleancache",
#     bin_clean_cache_command,
#     permission=Permission.ADMIN,
#     description="清理BIN查询缓存"
# )


# =============================================================================
# Inline 执行入口
# =============================================================================

async def bin_inline_execute(args: str) -> dict:
    """
    Inline Query 执行入口 - 提供完整的BIN查询功能

    Args:
        args: 用户输入的参数字符串，如 "123456"

    Returns:
        dict: {
            "success": bool,
            "title": str,
            "message": str,
            "description": str,
            "error": str | None
        }
    """
    if not args or not args.strip():
        return {
            "success": False,
            "title": "❌ 请输入BIN号码",
            "message": "请提供BIN卡头号码\n\n*使用方法:*\n• `bin 123456` \\- 查询6位BIN\n• `bin 12345678` \\- 查询8位BIN\n\n*说明:*\nBIN号码是信用卡号的前6\\-8位数字",
            "description": "请提供BIN卡头号码（6-8位数字）",
            "error": "未提供BIN参数"
        }

    if not cache_manager or not httpx_client:
        return {
            "success": False,
            "title": "❌ 服务未初始化",
            "message": "BIN查询服务未初始化，请联系管理员",
            "description": "服务未初始化",
            "error": "服务未初始化"
        }

    bin_number = args.strip().split()[0]

    # 验证BIN号码
    if not bin_number.isdigit():
        return {
            "success": False,
            "title": "❌ 格式错误",
            "message": "BIN号码必须为纯数字",
            "description": "BIN号码必须为纯数字",
            "error": "BIN号码必须为数字"
        }

    if len(bin_number) < 6 or len(bin_number) > 8:
        return {
            "success": False,
            "title": "❌ 长度错误",
            "message": "BIN号码长度必须在6\\-8位之间",
            "description": "BIN号码长度必须在6-8位之间",
            "error": "BIN号码长度错误"
        }

    try:
        # 获取BIN信息
        bin_data = await get_bin_info(bin_number)
        country_data = await get_country_data()
        currency_data = await get_currency_data()

        if not bin_data:
            config = get_config()
            if not config.bin_api_key:
                return {
                    "success": False,
                    "title": "❌ API未配置",
                    "message": "BIN API Key 未配置，请联系管理员",
                    "description": "BIN API未配置",
                    "error": "API Key 未配置"
                }
            return {
                "success": False,
                "title": f"❌ 未找到 {bin_number}",
                "message": f"无法获取BIN *{escape_markdown(bin_number, version=2)}* 的信息\n\n请检查号码是否正确",
                "description": f"未找到BIN {bin_number} 的信息",
                "error": "API 返回空数据"
            }

        # 格式化结果
        result_text = format_bin_data(bin_number, bin_data, country_data, currency_data)

        # 提取简短描述
        data = bin_data.get("data", {})
        brand = data.get("card_brand", "")
        if brand in BINMapping.brand:
            brand = BINMapping.brand[brand]
        card_type = data.get("card_type", "")
        if card_type in BINMapping.card_type:
            card_type = BINMapping.card_type[card_type]
        issuer = data.get("issuer", "")

        short_desc_parts = [bin_number]
        if brand:
            short_desc_parts.append(brand)
        if card_type:
            short_desc_parts.append(card_type)
        if issuer:
            short_desc_parts.append(issuer[:20])
        short_desc = " | ".join(short_desc_parts)

        return {
            "success": True,
            "title": f"💳 BIN {bin_number}",
            "message": result_text,
            "description": short_desc,
            "error": None
        }

    except Exception as e:
        logging.error(f"Inline BIN query failed: {e}")
        return {
            "success": False,
            "title": "❌ 查询失败",
            "message": f"查询BIN信息失败: {str(e)}",
            "description": "查询失败",
            "error": str(e)
        }
