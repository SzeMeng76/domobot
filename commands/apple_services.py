"""
Apple Services 价格查询命令
"""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from utils.cache_commands import delegate_to_service_handler
from utils.command_factory import command_factory
from utils.formatter import foldable_text_with_markdown_v2
from utils.permissions import Permission

logger = logging.getLogger(__name__)


async def apple_services_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handles the /aps command to query Apple service prices."""
    await delegate_to_service_handler(
        update,
        context,
        service_key="apple_services_service",
        service_display_name="Apple Services",
    )


# Register the commands
command_factory.register_command(
    "aps",
    apple_services_command,
    permission=Permission.USER,
    description="查询Apple服务价格 (iCloud, Apple One, Apple Music)",
)

logger.info("Apple Services 命令已注册")

# =============================================================================
# Inline 执行入口
# =============================================================================

async def appleservices_inline_execute(args: str, bot_instance=None) -> dict:
    """
    Inline Query 执行入口 - 提供完整的 Apple 服务价格查询功能

    Args:
        args: 用户输入的参数字符串，如 "icloud" 或 "appleone US"
        bot_instance: AppleServicesService 实例

    Returns:
        dict: {
            "success": bool,
            "title": str,
            "message": str,
            "description": str,
            "error": str | None
        }
    """
    import asyncio

    if not bot_instance:
        return {
            "success": False,
            "title": "❌ 服务未初始化",
            "message": "Apple Services 查询服务未初始化，请联系管理员",
            "description": "服务未初始化",
            "error": "Apple Services 服务未初始化"
        }

    if not args or not args.strip():
        return {
            "success": False,
            "title": "❌ 请指定服务类型",
            "message": "请提供服务类型\\n\\n*可用服务:*\\n• `appleservices icloud` \\\\- iCloud 价格\\n• `appleservices appleone` \\\\- Apple One 套餐\\n• `appleservices applemusic` \\\\- Apple Music 价格\\n\\n*可选国家:*\\n添加国家代码查询特定地区，如: `appleservices icloud US CN JP`",
            "description": "请指定服务类型: icloud, appleone, applemusic",
            "error": "未提供服务类型"
        }

    try:
        parts = args.strip().split()
        service = parts[0].lower().replace(" ", "")
        country_parts_start = 1

        # Check if first two parts form a valid service name
        if len(parts) > 1:
            combined = (parts[0] + parts[1]).lower().replace(" ", "")
            if combined in ["appleone", "applemusic"]:
                service = combined
                country_parts_start = 2

        if service not in ["icloud", "appleone", "applemusic"]:
            return {
                "success": False,
                "title": "❌ 无效的服务类型",
                "message": f"无效的服务类型: `{service}`\\n\\n*可用服务:*\\n• `icloud` \\\\- iCloud 存储\\n• `appleone` \\\\- Apple One 套餐\\n• `applemusic` \\\\- Apple Music",
                "description": "无效的服务类型",
                "error": "无效的服务类型"
            }

        # 解析国家参数
        from commands.apple_services_modules import DEFAULT_COUNTRIES
        countries = bot_instance.parse_countries_from_args(parts[country_parts_start:]) if len(parts) > country_parts_start else DEFAULT_COUNTRIES

        display_name = {"icloud": "iCloud", "appleone": "Apple One", "applemusic": "Apple Music"}.get(service, service)

        # 构建URL并获取数据
        tasks = []
        for country in countries:
            url = ""
            if service == "icloud":
                if country == "US":
                    url = "https://www.apple.com/icloud/"
                elif country == "CN":
                    url = "https://www.apple.com.cn/icloud/"
                else:
                    url = f"https://www.apple.com/{country.lower()}/icloud/"
            elif country == "US":
                url = f"https://www.apple.com/{service}/"
            elif country == "CN" and service == "appleone":
                url = "https://www.apple.com.cn/apple-one/"
            elif country == "CN" and service == "applemusic":
                url = "https://www.apple.com.cn/apple-music/"
            else:
                url = f"https://www.apple.com/{country.lower()}/{service}/"
            tasks.append(bot_instance.get_service_info(url, country, service))

        country_results = await asyncio.gather(*tasks)

        # 组装消息
        raw_message_parts = [f"*📱 {display_name} 价格信息*", ""]

        valid_results = [result for result in country_results if result]
        if valid_results:
            for i, result in enumerate(valid_results):
                raw_message_parts.append(result)
                if i < len(valid_results) - 1:
                    raw_message_parts.append("")
        else:
            raw_message_parts.append("所有查询地区均无此服务。")

        raw_final_message = "\n".join(raw_message_parts).strip()

        # 构建简短描述
        country_str = ", ".join(countries[:3])
        if len(countries) > 3:
            country_str += f" 等{len(countries)}个地区"

        return {
            "success": True,
            "title": f"📱 {display_name} 价格",
            "message": foldable_text_with_markdown_v2(raw_final_message),
            "description": f"{display_name} {country_str} 价格",
            "error": None
        }

    except Exception as e:
        logger.error(f"Inline Apple Services query failed: {e}")
        return {
            "success": False,
            "title": "❌ 查询失败",
            "message": f"查询 Apple 服务价格失败: {str(e)}",
            "description": "查询失败",
            "error": str(e)
        }
