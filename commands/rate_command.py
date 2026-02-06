# Description: Telegram bot command for direct currency exchange rate lookup.
# This module provides a /rate command to convert amounts between currencies.

import logging

from telegram import Update
from telegram.ext import ContextTypes

from utils.command_factory import command_factory
from utils.country_data import SUPPORTED_COUNTRIES  # To get currency symbols
from utils.formatter import foldable_text_v2, foldable_text_with_markdown_v2
from utils.message_manager import (
    delete_user_command,
    send_error,
    send_help,
    send_search_result,
    send_success,
)
from utils.permissions import Permission
from utils.rate_converter import RateConverter


# Configure logging - 避免重复配置日志
logger = logging.getLogger(__name__)

rate_converter: RateConverter | None = None


async def convert_currency_with_fallback(amount: float, from_currency: str, to_currency: str) -> float | None:
    """
    汇率转换，支持备用源降级（优先 Neutrino）
    可被其他模块导入使用

    Args:
        amount: 金额
        from_currency: 起始货币
        to_currency: 目标货币

    Returns:
        转换后的金额，失败返回 None
    """
    if not rate_converter or not rate_converter.rates:
        return None

    from_currency = from_currency.upper()
    to_currency = to_currency.upper()

    # 检查主源是否支持
    primary_supported = from_currency in rate_converter.rates and to_currency in rate_converter.rates

    if not primary_supported:
        # 主源不支持，尝试加载 GitHub 备用源（优先 Neutrino）
        logger.info(f"Primary source doesn't support {from_currency}/{to_currency}, trying fallback sources")
        await rate_converter.get_rates(fetch_github_sources=True)

        # 按优先级顺序检查备用源
        preferred_order = ["Neutrino", "Coinbase", "Wise", "Visa", "UnionPay"]
        fallback_supported = False

        if rate_converter.platform_rates:
            for preferred_platform in preferred_order:
                if preferred_platform in rate_converter.platform_rates:
                    platform_data = rate_converter.platform_rates[preferred_platform]
                    rates = platform_data["rates"]
                    if from_currency in rates and to_currency in rates:
                        # 临时合并到主源
                        if from_currency not in rate_converter.rates:
                            rate_converter.rates[from_currency] = rates[from_currency]
                        if to_currency not in rate_converter.rates:
                            rate_converter.rates[to_currency] = rates[to_currency]
                        logger.info(f"✅ Using {preferred_platform} as backup for {from_currency}/{to_currency}")
                        fallback_supported = True
                        break

            # 如果优先平台都不支持，尝试其他平台
            if not fallback_supported:
                for platform_name, platform_data in rate_converter.platform_rates.items():
                    if platform_name in preferred_order:
                        continue
                    rates = platform_data["rates"]
                    if from_currency in rates and to_currency in rates:
                        if from_currency not in rate_converter.rates:
                            rate_converter.rates[from_currency] = rates[from_currency]
                        if to_currency not in rate_converter.rates:
                            rate_converter.rates[to_currency] = rates[to_currency]
                        logger.info(f"✅ Using {platform_name} as backup for {from_currency}/{to_currency}")
                        fallback_supported = True
                        break

        if not fallback_supported:
            logger.warning(f"No source supports {from_currency}/{to_currency}")
            return None

    # 执行转换
    return await rate_converter.convert(amount, from_currency, to_currency)


def set_rate_converter(converter: RateConverter):
    global rate_converter
    rate_converter = converter


def get_currency_symbol(currency_code: str) -> str:
    """Returns the symbol for a given currency code from SUPPORTED_COUNTRIES or a common mapping."""
    # Check SUPPORTED_COUNTRIES first
    for country_info in SUPPORTED_COUNTRIES.values():
        if country_info.get("currency") == currency_code.upper():
            return country_info.get("symbol", "")

    # Fallback to common symbols if not found in country data
    common_symbols = {
        "USD": "$",
        "EUR": "€",
        "GBP": "£",
        "JPY": "¥",
        "CNY": "¥",
        "KRW": "₩",
        "INR": "₹",
        "RUB": "₽",
        "TRY": "₺",
        "THB": "฿",
        "IDR": "Rp",
        "MYR": "RM",
        "SGD": "S$",
        "CAD": "C$",
        "HKD": "HK$",
        "TWD": "NT$",
        "BRL": "R$",
        "NGN": "₦",
        "UAH": "₴",
        "ILS": "₪",
        "CZK": "Kč",
        "PLN": "zł",
        "SEK": "kr",
        "NOK": "kr",
        "DKK": "kr",
        "CHF": "CHF",
        "AED": "د.إ",
        "SAR": "ر.س",
        "QAR": "ر.ق",
        "KWD": "د.ك",
        "BHD": ".د.ب",
        "OMR": "ر.ع.",
        "EGP": "£",
        "MXN": "$",
        "ARS": "$",
        "CLP": "$",
        "COP": "$",
        "PEN": "S/",
        "VES": "Bs.",
        "NZD": "NZ$",
        "BGN": "лв",
        "HUF": "Ft",
        "ISK": "kr",
        "LKR": "Rs",
        "MNT": "₮",
        "KZT": "₸",
        "AZN": "₼",
        "AMD": "֏",
        "GEL": "₾",
        "MDL": "L",
        "RON": "lei",
        "RSD": "дин",
        "BYN": "Br",
        "UZS": "сўм",
        "LAK": "₭",
        "KHR": "៛",
        "MMK": "Ks",
        "BDT": "৳",
        "NPR": "₨",
        "PKR": "₨",
        "PHP": "₱",
        "VND": "₫",
        "LBP": "ل.ل",
        "JOD": "د.ا",
        "SYP": "£",
        "YER": "﷼",
        "DZD": "دج",
        "LYD": "ل.د",
        "MAD": "د.م.",
        "TND": "د.ت",
        "FJD": "$",
        "WST": "T",
        "TOP": "T$",
        "PGK": "K",
        "SBD": "$",
        "SHP": "£",
        "STD": "Db",
        "TJS": "ЅМ",
        "TMT": "m",
        "ZAR": "R",
        "ZWL": "$",
        "BYR": "Br",
        "GHS": "₵",
        "MOP": "MOP$",
        "UYU": "$U",
        "VEF": "Bs.F.",
        "XAF": "FCFA",
        "XCD": "$",
        "XOF": "CFA",
        "XPF": "₣",
    }
    return common_symbols.get(currency_code.upper(), "")


async def rate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /rate command for currency conversion."""
    if not update.message:
        return

    if not rate_converter:
        error_message = "汇率转换器未初始化。请联系机器人管理员。"
        await send_error(context, update.message.chat_id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        return

    loading_message = "🔍 正在查询中... ⏳"
    message = await context.bot.send_message(
        chat_id=update.message.chat_id, text=foldable_text_v2(loading_message), parse_mode="MarkdownV2"
    )

    args = context.args
    from_currency = "USD"
    to_currency = "CNY"
    amount = 100.0
    expression = None

    if not args:
        # Display help message if no arguments
        help_message = (
            "*💱 货币汇率插件*\n\n"
            "*使用方法:* `/rate [from_currency] [to_currency] [amount]`\n"
            "`[amount]` 是可选的，默认为 100。\n"
            "`[to_currency]` 是可选的，默认为 CNY。\n\n"
            "*示例:*\n"
            "`/rate` (显示帮助)\n"
            "`/rate USD` (USD -> CNY, 100 USD)\n"
            "`/rate USD JPY` (USD -> JPY, 100 USD)\n"
            "`/rate USD CNY 50` (USD -> CNY, 50 USD)\n"
            "`/rate USD 1+1` (USD -> CNY, 计算 1+1)\n\n"
            "*✨ 新功能:*\n"
            "• 自动显示多平台汇率对比\n"
            "• 标记最优汇率 🏆\n"
            "• 计算平台间差价\n\n"
            "📣 主源每小时更新 | 平台每8小时更新\n"
            "🌐 数据来源: OpenExchange + Coinbase, Visa, Wise, UnionPay, Neutrino"
        )

        await message.delete()
        await send_help(context, update.message.chat_id, foldable_text_with_markdown_v2(help_message), parse_mode="MarkdownV2")
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        return

    # Parse arguments
    if len(args) == 1:
        from_currency = args[0].upper()
    elif len(args) == 2:
        from_currency = args[0].upper()
        # Check if second arg is a currency or an amount expression
        if len(args[1]) == 3 and args[1].isalpha():  # Likely a currency code
            to_currency = args[1].upper()
        else:
            # Assume it's an amount expression
            amount_str = args[1]
            try:
                amount = float(amount_str)
            except ValueError:
                # Try to evaluate as math expression
                try:
                    from utils.safe_math_evaluator import safe_eval_math

                    amount = safe_eval_math(amount_str)
                    expression = amount_str
                except ValueError:
                    error_message = f"❌ 无效的金额或表达式: {amount_str}"
                    await message.delete()
                    await send_error(context, update.message.chat_id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
                    await delete_user_command(context, update.message.chat_id, update.message.message_id)
                    return
    elif len(args) == 3:
        from_currency = args[0].upper()
        to_currency = args[1].upper()
        amount_str = args[2]
        try:
            amount = float(amount_str)
        except ValueError:
            try:
                from utils.safe_math_evaluator import safe_eval_math

                amount = safe_eval_math(amount_str)
                expression = amount_str
            except ValueError:
                error_message = f"❌ 无效的金额或表达式: {amount_str}"
                await message.delete()
                await send_error(context, update.message.chat_id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
                await delete_user_command(context, update.message.chat_id, update.message.message_id)
                return
    else:
        error_message = "❌ 参数过多。请检查使用方法。"
        await message.delete()
        await send_error(context, update.message.chat_id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        return

    # 快速检查数据可用性（无需等待网络）
    if not await rate_converter.is_data_available():
        # 数据太旧或不存在，尝试快速加载
        await rate_converter.get_rates()
        if not rate_converter.rates:
            error_message = "❌ 汇率数据暂时不可用。请稍后重试。"
            await message.delete()
            await send_error(context, update.message.chat_id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
            await delete_user_command(context, update.message.chat_id, update.message.message_id)
            return

    # 检查货币是否支持（使用统一的降级函数预检查）
    # 先尝试直接转换，如果失败会自动降级到备用源
    test_result = await convert_currency_with_fallback(1.0, from_currency, to_currency)

    if test_result is None:
        # 所有源都不支持
        error_message = f"❌ 不支持的货币对: {from_currency}/{to_currency}"
        await message.delete()
        await send_error(context, update.message.chat_id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        await delete_user_command(context, update.message.chat_id, update.message.message_id)
        return

    try:
        # 使用统一的降级转换函数
        converted_amount = await convert_currency_with_fallback(amount, from_currency, to_currency)
        if converted_amount is None:
            error_message = "❌ 转换失败，请检查货币代码。"
            await message.delete()
            await send_error(context, update.message.chat_id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
            await delete_user_command(context, update.message.chat_id, update.message.message_id)
            return

        from_symbol = get_currency_symbol(from_currency)
        to_symbol = get_currency_symbol(to_currency)

        # 格式化数字，移除不必要的小数位
        formatted_amount = f"{amount:.8f}".rstrip("0").rstrip(".")
        formatted_converted = f"{converted_amount:.2f}".rstrip("0").rstrip(".")

        # 美化排版的组装原始文本
        result_lines = ["💰 *汇率转换结果*"]
        result_lines.append("━━━━━━━━━━━━━━━━")

        if expression:
            result_lines.extend(["", "🧮 *计算公式*", f"   `{expression}` = `{formatted_amount}`"])

        result_lines.extend(
            [
                "",
                "💱 *主要汇率*",
                f"   {from_symbol} `{formatted_amount}` *{from_currency}* → {to_symbol} `{formatted_converted}` *{to_currency}*",
            ]
        )

        # 获取多平台对比数据
        try:
            comparison = await rate_converter.get_platform_comparison(amount, from_currency, to_currency)
            if comparison and comparison["platforms"]:
                result_lines.extend(["", "📊 *多平台对比*"])

                # 收集所有平台的结果（包括主源）
                all_results = []
                if comparison["primary"]:
                    all_results.append(("OpenExchange", comparison["primary"]["converted"]))

                for platform, data in comparison["platforms"].items():
                    all_results.append((platform, data["converted"]))

                # 找出最优汇率
                if all_results:
                    best_platform, best_value = max(all_results, key=lambda x: x[1])
                    worst_platform, worst_value = min(all_results, key=lambda x: x[1])

                    # 显示各平台汇率
                    for platform, data in sorted(comparison["platforms"].items()):
                        converted_val = data["converted"]
                        formatted_val = f"{converted_val:.2f}".rstrip("0").rstrip(".")

                        # 标记最优/最差
                        marker = ""
                        if converted_val == best_value:
                            marker = " 🏆"  # 最划算
                        elif converted_val == worst_value and len(all_results) > 1:
                            marker = " 📉"  # 最差

                        result_lines.append(f"   • {platform}: {to_symbol} `{formatted_val}`{marker}")

                    # 显示差价
                    if best_value != worst_value:
                        diff = best_value - worst_value
                        diff_percent = (diff / worst_value) * 100
                        formatted_diff = f"{diff:.2f}".rstrip("0").rstrip(".")
                        result_lines.append("")
                        result_lines.append(f"💡 *最大差价*: {to_symbol} `{formatted_diff}` ({diff_percent:.2f}%)")
        except Exception as e:
            logger.warning(f"Failed to get platform comparison: {e}")
            # 即使对比失败，也不影响主要功能

        result_lines.extend(
            [
                "",
                "━━━━━━━━━━━━━━━━",
                "📣 主源每小时更新 | 平台对比每8小时更新",
                "🌐 来源: OpenExchange + 5个主流平台",
            ]
        )

        result_text = "\n".join(result_lines)

        await message.delete()
        await send_search_result(context, update.message.chat_id, foldable_text_with_markdown_v2(result_text), parse_mode="MarkdownV2")
        await delete_user_command(context, update.message.chat_id, update.message.message_id)

    except Exception as e:
        logger.error(f"Error during rate conversion: {e}")
        error_message = f"❌ 转换时发生错误: {e!s}"
        await message.delete()
        await send_error(context, update.message.chat_id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        await delete_user_command(context, update.message.chat_id, update.message.message_id)


async def rate_clean_cache_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /rate_cleancache command to clear rate converter cache."""
    if not update.message:
        return

    try:
        if rate_converter:
            await rate_converter.cache_manager.clear_cache(key="exchange_rates")
            success_message = "✅ 汇率缓存已清理。"
            await send_success(context, update.message.chat_id, foldable_text_v2(success_message), parse_mode="MarkdownV2")
            await delete_user_command(context, update.message.chat_id, update.message.message_id)
        else:
            warning_message = "⚠️ 汇率转换器未初始化，无需清理缓存。"
            await send_error(context, update.message.chat_id, foldable_text_v2(warning_message), parse_mode="MarkdownV2")
            await delete_user_command(context, update.message.chat_id, update.message.message_id)
    except Exception as e:
        logger.error(f"Error clearing rate cache: {e}")
        error_message = f"❌ 清理汇率缓存时发生错误: {e!s}"
        await send_error(context, update.message.chat_id, foldable_text_v2(error_message), parse_mode="MarkdownV2")
        await delete_user_command(context, update.message.chat_id, update.message.message_id)


async def rate_inline_execute(args: str) -> dict:
    """
    Inline Query 执行入口 - 提供完整的汇率转换功能

    Args:
        args: 用户输入的参数字符串，如 "USD CNY 100" 或 "usd 50"

    Returns:
        dict: {
            "success": bool,
            "title": str,           # 简短标题
            "message": str,         # 完整消息（MarkdownV2 格式）
            "description": str,     # 简短描述（用于 inline 结果预览）
            "error": str | None     # 错误信息
        }
    """
    if not rate_converter:
        return {
            "success": False,
            "title": "❌ 汇率转换失败",
            "message": "汇率转换器未初始化。请联系机器人管理员。",
            "description": "汇率转换器未初始化",
            "error": "汇率转换器未初始化"
        }

    # 解析参数
    parts = args.strip().split() if args else []
    from_currency = "USD"
    to_currency = "CNY"
    amount = 100.0
    expression = None

    try:
        if len(parts) == 0:
            pass  # 使用默认值
        elif len(parts) == 1:
            from_currency = parts[0].upper()
        elif len(parts) == 2:
            from_currency = parts[0].upper()
            # 检查第二个参数是货币还是金额
            if len(parts[1]) == 3 and parts[1].isalpha():
                to_currency = parts[1].upper()
            else:
                # 尝试解析为金额或表达式
                try:
                    amount = float(parts[1])
                except ValueError:
                    from utils.safe_math_evaluator import safe_eval_math
                    amount = safe_eval_math(parts[1])
                    expression = parts[1]
        elif len(parts) >= 3:
            from_currency = parts[0].upper()
            to_currency = parts[1].upper()
            amount_str = parts[2]
            try:
                amount = float(amount_str)
            except ValueError:
                from utils.safe_math_evaluator import safe_eval_math
                amount = safe_eval_math(amount_str)
                expression = amount_str
    except ValueError as e:
        return {
            "success": False,
            "title": "❌ 参数错误",
            "message": f"无效的金额或表达式: {args}",
            "description": f"无效的金额或表达式",
            "error": str(e)
        }

    # 检查数据可用性
    if not await rate_converter.is_data_available():
        await rate_converter.get_rates()
        if not rate_converter.rates:
            return {
                "success": False,
                "title": "❌ 数据不可用",
                "message": "汇率数据暂时不可用。请稍后重试。",
                "description": "汇率数据暂时不可用",
                "error": "汇率数据不可用"
            }

    # 执行转换
    try:
        converted_amount = await convert_currency_with_fallback(amount, from_currency, to_currency)
        if converted_amount is None:
            return {
                "success": False,
                "title": "❌ 不支持的货币",
                "message": f"不支持的货币对: {from_currency}/{to_currency}\n\n💡 提示: 使用 /rate 查看支持的货币",
                "description": f"不支持的货币对: {from_currency}/{to_currency}",
                "error": f"不支持的货币对: {from_currency}/{to_currency}"
            }

        from_symbol = get_currency_symbol(from_currency)
        to_symbol = get_currency_symbol(to_currency)

        # 格式化数字
        formatted_amount = f"{amount:.8f}".rstrip("0").rstrip(".")
        formatted_converted = f"{converted_amount:.2f}".rstrip("0").rstrip(".")

        # 构建完整结果（与 rate_command 相同的格式）
        result_lines = ["💰 *汇率转换结果*"]
        result_lines.append("━━━━━━━━━━━━━━━━")

        if expression:
            result_lines.extend(["", "🧮 *计算公式*", f"   `{expression}` = `{formatted_amount}`"])

        result_lines.extend(
            [
                "",
                "💱 *主要汇率*",
                f"   {from_symbol} `{formatted_amount}` *{from_currency}* → {to_symbol} `{formatted_converted}` *{to_currency}*",
            ]
        )

        # 获取多平台对比数据
        try:
            comparison = await rate_converter.get_platform_comparison(amount, from_currency, to_currency)
            if comparison and comparison["platforms"]:
                result_lines.extend(["", "📊 *多平台对比*"])

                # 收集所有平台的结果
                all_results = []
                if comparison["primary"]:
                    all_results.append(("OpenExchange", comparison["primary"]["converted"]))

                for platform, data in comparison["platforms"].items():
                    all_results.append((platform, data["converted"]))

                # 找出最优汇率
                if all_results:
                    best_platform, best_value = max(all_results, key=lambda x: x[1])
                    worst_platform, worst_value = min(all_results, key=lambda x: x[1])

                    # 显示各平台汇率
                    for platform, data in sorted(comparison["platforms"].items()):
                        converted_val = data["converted"]
                        formatted_val = f"{converted_val:.2f}".rstrip("0").rstrip(".")

                        marker = ""
                        if converted_val == best_value:
                            marker = " 🏆"
                        elif converted_val == worst_value and len(all_results) > 1:
                            marker = " 📉"

                        result_lines.append(f"   • {platform}: {to_symbol} `{formatted_val}`{marker}")

                    # 显示差价
                    if best_value != worst_value:
                        diff = best_value - worst_value
                        diff_percent = (diff / worst_value) * 100
                        formatted_diff = f"{diff:.2f}".rstrip("0").rstrip(".")
                        result_lines.append("")
                        result_lines.append(f"💡 *最大差价*: {to_symbol} `{formatted_diff}` ({diff_percent:.2f}%)")
        except Exception as e:
            logger.warning(f"Failed to get platform comparison in inline: {e}")

        result_lines.extend(
            [
                "",
                "━━━━━━━━━━━━━━━━",
                "📣 主源每小时更新 | 平台对比每8小时更新",
                "🌐 来源: OpenExchange + 5个主流平台",
            ]
        )

        result_text = "\n".join(result_lines)

        # 简短描述（用于 inline 预览）
        short_description = f"{from_symbol}{formatted_amount} {from_currency} → {to_symbol}{formatted_converted} {to_currency}"

        return {
            "success": True,
            "title": f"💱 {from_currency} → {to_currency}",
            "message": result_text,
            "description": short_description,
            "error": None
        }

    except Exception as e:
        logger.error(f"Error during inline rate conversion: {e}")
        return {
            "success": False,
            "title": "❌ 转换失败",
            "message": f"转换时发生错误: {e!s}",
            "description": f"转换错误: {e!s}",
            "error": str(e)
        }


# Register commands
command_factory.register_command("rate", rate_command, permission=Permission.USER, description="汇率查询和转换")
# 已迁移到统一缓存管理命令 /cleancache
# command_factory.register_command(
#     "rate_cleancache", rate_clean_cache_command, permission=Permission.ADMIN, description="清理汇率缓存"
# )
