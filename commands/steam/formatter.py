# Description: Steam 模块的游戏/捆绑包信息格式化
# 从原 steam.py 拆分

import asyncio
import re

from utils.country_data import SUPPORTED_COUNTRIES, get_country_flag
from utils.price_parser import extract_currency_and_price

from . import cache
from .models import Config
from .parser import escape_markdown, get_country_code

config = Config()


def select_best_match(search_results: list[dict], query: str) -> dict:
    """智能选择最匹配的游戏结果"""
    if not search_results:
        return {}

    if len(search_results) == 1:
        return search_results[0]

    query_lower = query.lower()

    # 计算每个结果的匹配分数
    scored_results = []
    for result in search_results:
        name = result.get("name", "").lower()
        score = 0

        # 完全匹配得分最高
        if name == query_lower:
            score += 1000

        # 包含查询词得分
        if query_lower in name:
            score += 500

        # 查询词包含在名称中得分
        if name in query_lower:
            score += 300

        # 长度相似性得分 (越接近越好)
        length_diff = abs(len(name) - len(query_lower))
        score += max(0, 100 - length_diff * 5)

        # 避免选择DLC、Pass、Pack等附加内容
        penalty_keywords = [
            "dlc",
            "pack",
            "pass",
            "bundle",
            "edition",
            "soundtrack",
            "ost",
            "friend's",
            "season",
        ]
        for keyword in penalty_keywords:
            if keyword in name:
                score -= 200

        # 如果有价格信息，优先选择有价格的
        if result.get("price"):
            score += 50

        scored_results.append((score, result))

    # 按分数排序，返回最高分的
    scored_results.sort(key=lambda x: x[0], reverse=True)
    return scored_results[0][1]


async def format_price_with_cny(
    price_info: dict, country_currency: str, country_code: str = None
) -> str:
    """格式化价格信息并添加 CNY 转换"""
    if not price_info:
        return "❓ 暂无价格信息"

    if price_info.get("is_free"):
        return "🆓 免费游戏"

    if not cache.rate_converter:
        return "❌ 汇率转换器未初始化，无法格式化价格。"

    currency = price_info.get("currency", country_currency)

    initial_num = price_info.get("initial", 0) / 100.0
    final_num = price_info.get("final", 0) / 100.0

    # 获取当前地区代码，如果是中国地区则不显示汇率转换
    cc = country_code or country_currency

    # 智能格式化价格
    def format_currency_price(amount, curr_code, c_code):
        country_data = SUPPORTED_COUNTRIES.get(
            c_code, {"currency": "USD", "symbol": "$"}
        )
        if curr_code == country_data["currency"]:
            return f"{country_data['symbol']}{amount:.2f}"
        currency_symbols = {
            "USD": "$",
            "EUR": "€",
            "GBP": "£",
            "CNY": "¥",
            "JPY": "¥",
        }
        symbol = currency_symbols.get(curr_code, "$")
        return f"{symbol}{amount:.2f}"

    if (
        currency != "CNY"
        and cc != "CN"
        and cache.rate_converter
        and cache.rate_converter.rates
        and currency in cache.rate_converter.rates
    ):
        initial_cny = await cache.rate_converter.convert(initial_num, currency, "CNY")
        final_cny = await cache.rate_converter.convert(final_num, currency, "CNY")

        if initial_cny is not None and final_cny is not None:
            initial_with_cny = f"{format_currency_price(initial_num, currency, cc)} - ¥{initial_cny:.2f}CNY"
            final_with_cny = f"{format_currency_price(final_num, currency, cc)} - ¥{final_cny:.2f}CNY"
        else:
            initial_with_cny = format_currency_price(initial_num, currency, cc)
            final_with_cny = format_currency_price(final_num, currency, cc)
    else:
        initial_with_cny = format_currency_price(initial_num, currency, cc)
        final_with_cny = format_currency_price(final_num, currency, cc)

    discount = price_info.get("discount_percent", 0)

    if discount > 0:
        return f"💵 价格: {final_with_cny} ⬇️ (-{discount}%)\n💰   原价: {initial_with_cny}"
    return f"💵 价格: {final_with_cny}"


async def format_game_info(game_data: dict, cc: str) -> str:
    """格式化游戏信息以供显示"""
    if not game_data.get("success"):
        return "❌ 无法获取游戏信息"

    data = game_data.get("data", {})
    name = data.get("name", "未知游戏")
    price_info = data.get("price_overview", {})
    app_id = data.get("steam_appid")

    country_info = SUPPORTED_COUNTRIES.get(cc, {"name": cc})

    store_url = f"https://store.steampowered.com/app/{app_id}/_/"

    currency = price_info.get("currency", cc)

    result = [
        f"🎮 {escape_markdown(name)} - [Store Page]({store_url})",
        f"🔑 Steam ID: `{app_id}`",
        f"🌍 国家/地区: {get_country_flag(cc)} {country_info['name']} ({cc})",
        await format_price_with_cny(price_info, currency, cc),
    ]

    package_groups = data.get("package_groups", [])
    purchase_options = []
    if package_groups:
        for group in package_groups:
            subs = group.get("subs", [])
            for package in subs:
                option_text = re.sub(
                    r"<.*?>", "", package.get("option_text", "未知包裹")
                )
                is_free_license = package.get("is_free_license", False)
                package_final_price_cents = package.get(
                    "price_in_cents_with_discount", 0
                )
                main_final_price_cents = price_info.get("final", 0)

                # 智能识别内容类型
                option_text_lower = option_text.lower()
                content_type = ""
                if any(
                    keyword in option_text_lower
                    for keyword in ["dlc", "downloadable content", "可下载内容"]
                ):
                    content_type = "📦"
                elif any(
                    keyword in option_text_lower
                    for keyword in ["season pass", "季票", "season"]
                ):
                    content_type = "🎫"
                elif any(
                    keyword in option_text_lower
                    for keyword in ["bundle", "pack", "捆绑包", "包装"]
                ):
                    content_type = "🛍"
                elif any(
                    keyword in option_text_lower
                    for keyword in ["expansion", "扩展包", "addon"]
                ):
                    content_type = "🎮"
                elif any(
                    keyword in option_text_lower
                    for keyword in [
                        "deluxe",
                        "premium",
                        "gold",
                        "ultimate",
                        "豪华版",
                        "黄金版",
                    ]
                ):
                    content_type = "💎"
                elif any(
                    keyword in option_text_lower
                    for keyword in ["soundtrack", "ost", "原声", "音轨"]
                ):
                    content_type = "🎵"
                else:
                    content_type = "🎯"

                # 显示所有非基础游戏的购买选项
                should_show = True

                # 如果价格相同且是基础游戏名称，则跳过
                if package_final_price_cents == main_final_price_cents and (
                    option_text == data.get("name", "")
                    or "游戏本体" in option_text_lower
                    or "base game" in option_text_lower
                ):
                    should_show = False

                if should_show:
                    if is_free_license:
                        purchase_options.append(f"• 🆓 {option_text} - 免费")
                    elif package_final_price_cents > 0:
                        package_price_num = package_final_price_cents / 100.0
                        package_currency = package.get("currency", currency)

                        # 清理option_text
                        clean_option_text = re.sub(r"<.*?>", "", option_text)

                        # 智能价格格式化
                        def format_local_price(amount, currency_code, country_code):
                            country_info_local = SUPPORTED_COUNTRIES.get(
                                country_code, {"currency": "USD", "symbol": "$"}
                            )
                            if currency_code == country_info_local["currency"]:
                                return f"{country_info_local['symbol']}{amount:.2f}"
                            currency_symbols = {
                                "USD": "$",
                                "EUR": "€",
                                "GBP": "£",
                                "CNY": "¥",
                                "JPY": "¥",
                            }
                            symbol = currency_symbols.get(currency_code, "$")
                            return f"{symbol}{amount:.2f}"

                        price_display = format_local_price(
                            package_price_num, package_currency, cc
                        )

                        # 如果不是中国地区且不是人民币，添加人民币汇率转换
                        if (
                            cc != "CN"
                            and package_currency != "CNY"
                            and cache.rate_converter
                            and cache.rate_converter.rates
                            and package_currency in cache.rate_converter.rates
                        ):
                            cny_price = await cache.rate_converter.convert(
                                package_price_num, package_currency, "CNY"
                            )
                            if cny_price is not None:
                                price_display += f" - ¥{cny_price:.2f}CNY"

                        # 清理option_text，移除价格信息
                        clean_name = re.sub(
                            r"\s*-?\s*([\$¥€£]\s*\d+\.?\d*\s*)*$",
                            "",
                            clean_option_text,
                        ).strip()
                        clean_name = re.sub(
                            r"\s*-?\s*[\$¥€£]\s*\d+\.?\d*\s*[\$¥€£]\s*\d+\.?\d*$",
                            "",
                            clean_name,
                        ).strip()

                        purchase_options.append(
                            f"• {content_type} {clean_name} - {price_display}"
                        )
                    else:
                        # 价格为0但不是免费许可证的情况
                        purchase_options.append(
                            f"• {content_type} {option_text} (暂无价格信息)"
                        )

    if purchase_options:
        result.append("🛒 购买选项:")
        result.extend(purchase_options)

    return "\n".join(result)


async def format_bundle_info(bundle_data: dict, cc: str) -> str:
    """格式化捆绑包信息，包括价格转换到 CNY"""
    if not bundle_data:
        return "❌ 无法获取捆绑包信息"

    # 国区不做任何额外换算
    if cc.upper() == "CN":
        final = bundle_data.get("final_price", "未知")
        original = bundle_data.get("original_price", "未知")
        discount = bundle_data.get("discount_pct", "0")
        savings = bundle_data.get("savings", "0")
        text = [
            f"🎮 {escape_markdown(bundle_data['name'])}",
            f"🔗 链接：{bundle_data['url']}",
            f"💵 优惠价: {final}",
            f"💰 原价: {original}" if original and original != final else "",
            f"🛍 折扣: -{discount}%" if discount != "0" else "",
            f"📉 共节省: {savings}" if savings not in ("0", "未知") else "",
        ]
        # 包含内容直接附上，不做汇率转换
        if bundle_data.get("items"):
            text.append("\n🎮 包含内容:")
            for it in bundle_data["items"]:
                text.append(
                    f"• {escape_markdown(it['name'])} - {it['price']['final_formatted']}"
                )
        return "\n".join([t for t in text if t])

    if not cache.rate_converter:
        return "❌ 汇率转换器未初始化，无法格式化价格。"

    result = []

    result.append(f"🎮 {escape_markdown(bundle_data['name'])}")
    result.append(f"🔗 链接：{bundle_data['url']}")
    result.append(f"🌍 查询地区: {get_country_flag(cc)} {cc}")

    final_price_str = bundle_data.get("final_price", "未知")
    original_price_str = bundle_data.get("original_price", "未知")
    savings_str = bundle_data.get("savings", "0")
    discount_pct = bundle_data.get("discount_pct", "0")

    final_currency_code, final_price_num = extract_currency_and_price(
        final_price_str, cc
    )
    final_price_display = final_price_str

    if final_price_num == 0.0:
        final_price_display = "🆓 免费"
    elif final_price_num > 0 and final_currency_code != "CNY":
        final_cny = await cache.rate_converter.convert(
            final_price_num, final_currency_code, "CNY"
        )
        if final_cny is not None:
            final_price_display = f"{final_price_str} ( ≈ ¥{final_cny:.2f} CNY )"

    original_currency_code, original_price_num = extract_currency_and_price(
        original_price_str, cc
    )
    original_price_display = original_price_str
    if (
        original_price_num > 0
        and original_currency_code != "CNY"
        and original_price_num != final_price_num
    ):
        original_cny = await cache.rate_converter.convert(
            original_price_num, original_currency_code, "CNY"
        )
        if original_cny is not None:
            original_price_display = (
                f"{original_price_str} ( ≈ ¥{original_cny:.2f} CNY )"
            )

    savings_currency_code, savings_num = extract_currency_and_price(savings_str, cc)
    savings_display = savings_str
    if savings_num > 0 and savings_currency_code != "CNY":
        savings_cny = await cache.rate_converter.convert(
            savings_num, savings_currency_code, "CNY"
        )
        if savings_cny is not None:
            savings_display = f"{savings_str} ( ≈ ¥{savings_cny:.2f} CNY )"

    if final_price_num == 0.0:
        result.append("\n🆓 免费")
    elif final_price_num > 0:
        result.append(f"\n💵 优惠价: {final_price_display}")
        if (
            original_price_num > 0
            and original_price_num != final_price_num
            and original_price_display != "未知"
        ):
            result.append(f"💰   原价: {original_price_display}")

    if discount_pct and discount_pct != "0":
        result.append(f"🛍 捆绑包额外折扣: -{discount_pct}%")

    if savings_num > 0 and savings_display != "未知" and savings_display != "0":
        result.append(f"📉 共节省: {savings_display}")

    if bundle_data.get("items"):
        result.append("\n🎮 包含内容:")
        for item in bundle_data["items"]:
            price_item_str = item.get("price", {}).get("final_formatted", "未知价格")
            item_name = escape_markdown(item.get("name", "未知项目"))
            result.append(f"• 📄 {item_name} - {price_item_str}")

    return "\n".join(result)


async def search_multiple_countries(game_query: str, country_inputs: list[str]) -> str:
    """跨多个国家搜索游戏价格"""
    from .models import ErrorHandler
    from .search import get_game_details, search_game

    results = []
    valid_country_codes = []

    for country_input in country_inputs:
        country_code = get_country_code(country_input)
        if country_code:
            valid_country_codes.append(country_code)
        else:
            results.append(f"❌ 无效的国家/地区: {country_input}")

    if not valid_country_codes:
        valid_country_codes = [config.DEFAULT_CC]

    search_results = await search_game(game_query, valid_country_codes[0])
    if not search_results:
        return f"❌ 未找到相关游戏\\n搜索词: `{game_query}`"

    # 智能选择最匹配的游戏
    game = select_best_match(search_results, game_query)
    app_id = str(game.get("id"))

    for cc in valid_country_codes:
        try:
            game_details = await get_game_details(app_id, cc)
            if game_details:
                formatted_info = await format_game_info(game_details, cc)
                results.append(formatted_info)
            await asyncio.sleep(config.REQUEST_DELAY)
        except Exception as e:
            error_msg = ErrorHandler.handle_network_error(e)
            results.append(f"❌ {cc}区查询失败: {error_msg}")

    return "\n\n".join(results)
