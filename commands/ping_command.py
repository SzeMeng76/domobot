"""
IP 信誉检测命令
通过 MyIP 服务查询 IP 信息，结合 AbuseIPDB 查询风控分数
"""

import logging
import re
from typing import Optional, Dict
from telegram import Update
from telegram.ext import ContextTypes

from utils.command_factory import command_factory
from utils.permissions import Permission
from utils.message_manager import send_error, delete_user_command, _schedule_deletion
from utils.config_manager import get_config

logger = logging.getLogger(__name__)

# 全局变量
cache_manager = None
httpx_client = None
_api_key_index = 0  # AbuseIPDB API Key 轮询索引

def set_dependencies(c_manager, h_client):
    """设置依赖注入"""
    global cache_manager, httpx_client
    cache_manager = c_manager
    httpx_client = h_client


def get_next_abuseipdb_key() -> Optional[str]:
    """获取下一个可用的 AbuseIPDB API Key（轮询）"""
    global _api_key_index
    config = get_config()

    if not config.abuseipdb_api_keys:
        return None

    # 轮询获取 API Key
    api_key = config.abuseipdb_api_keys[_api_key_index % len(config.abuseipdb_api_keys)]
    _api_key_index += 1

    return api_key


async def get_ipapi_info(ip_address: str) -> Optional[Dict]:
    """从 ipapi.is 获取 IP 信息"""
    if not httpx_client:
        logger.error("httpx_client 未初始化")
        return None

    try:
        url = f"https://api.ipapi.is/?q={ip_address}"
        headers = {
            "User-Agent": "DomoBot/1.0"
        }

        logger.info(f"查询 ipapi.is 信息: {ip_address}")

        response = await httpx_client.get(url, headers=headers, timeout=30.0)
        response.raise_for_status()

        data = response.json()
        logger.info(f"✅ ipapi.is 查询成功: {ip_address}")
        return data

    except Exception as e:
        logger.error(f"ipapi.is 查询失败: {e}", exc_info=True)
        return None


async def get_abuseipdb_score(ip_address: str) -> Optional[Dict]:
    """从 AbuseIPDB 获取风控分数（带缓存）"""
    cache_key = f"abuseipdb_{ip_address}"
    cached_data = await cache_manager.load_cache(cache_key, subdirectory="abuseipdb")
    if cached_data:
        logger.info(f"使用缓存的 AbuseIPDB 数据: {ip_address}")
        return cached_data

    api_key = get_next_abuseipdb_key()
    if not api_key:
        logger.warning("无可用的 AbuseIPDB API Key，跳过风控检测")
        return None

    try:
        url = "https://api.abuseipdb.com/api/v2/check"
        headers = {
            "Key": api_key,
            "Accept": "application/json"
        }
        params = {
            "ipAddress": ip_address,
            "maxAgeInDays": 90
        }

        logger.info(f"查询 AbuseIPDB 风控分数: {ip_address}")

        response = await httpx_client.get(url, headers=headers, params=params, timeout=30.0)
        response.raise_for_status()

        data = response.json().get("data", {})

        if data:
            # 缓存结果（默认7天）
            await cache_manager.save_cache(cache_key, data, subdirectory="abuseipdb")
            logger.info(f"✅ AbuseIPDB 查询成功并缓存: {ip_address}")
            return data

        return None

    except Exception as e:
        logger.error(f"AbuseIPDB 查询失败: {e}", exc_info=True)
        return None


async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /ping <IP> - 查询 IP 信息和风控分数
    """
    config = get_config()
    chat_id = update.effective_chat.id

    # 检查参数
    if not context.args or len(context.args) == 0:
        help_text = (
            "📊 *IP 信息检测*\n\n"
            "*使用方法：*\n"
            "`/ping <IP地址>`\n\n"
            "*示例：*\n"
            "`/ping 8.8.8.8`\n"
            "`/ping 1.1.1.1`\n\n"
            "*查询信息：*\n"
            "• 风控指数 (0-100)\n"
            "• IP 类型 (原生/数据中心)\n"
            "• 地理位置和 ISP\n"
            "• ASN 信息"
        )
        msg = await context.bot.send_message(
            chat_id=chat_id,
            text=help_text,
            parse_mode="Markdown"
        )
        # 自动删除帮助消息
        await _schedule_deletion(context, chat_id, msg.message_id, config.auto_delete_delay)
        if update.message:
            await delete_user_command(context, chat_id, update.message.message_id)
        return

    ip_address = context.args[0]

    # 验证 IP 格式（支持 IPv4 和 IPv6）
    ipv4_pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
    ipv6_pattern = r'^([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}$'
    if not (re.match(ipv4_pattern, ip_address) or re.match(ipv6_pattern, ip_address)):
        await send_error(context, chat_id, "❌ 无效的 IP 地址格式")
        if update.message:
            await delete_user_command(context, chat_id, update.message.message_id)
        return

    # 发送处理中消息
    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"🔍 正在查询 IP: `{ip_address}`\n⏳ 请稍候...",
        parse_mode="Markdown"
    )

    try:
        # 并行查询 ipapi.is 和 AbuseIPDB
        import asyncio
        ipapi_task = get_ipapi_info(ip_address)
        abuseipdb_task = get_abuseipdb_score(ip_address)

        ipapi_data, abuseipdb_data = await asyncio.gather(ipapi_task, abuseipdb_task, return_exceptions=True)

        # 处理异常
        if isinstance(ipapi_data, Exception):
            logger.error(f"ipapi.is 查询异常: {ipapi_data}")
            ipapi_data = None
        if isinstance(abuseipdb_data, Exception):
            logger.error(f"AbuseIPDB 查询异常: {abuseipdb_data}")
            abuseipdb_data = None

        if not ipapi_data:
            await status_msg.edit_text("❌ 查询失败：无法获取 IP 信息")
            await _schedule_deletion(context, chat_id, status_msg.message_id, config.auto_delete_delay)
            if update.message:
                await delete_user_command(context, chat_id, update.message.message_id)
            return

        # 解析 ipapi.is 数据
        location_data = ipapi_data.get("location", {})
        asn_data = ipapi_data.get("asn", {})
        company_data = ipapi_data.get("company", {})

        ip = ipapi_data.get("ip", ip_address)
        city = location_data.get("city", "")
        region = location_data.get("state", "")
        country_name = location_data.get("country", "未知")
        country_code = location_data.get("country_code", "")
        asn = f"AS{asn_data.get('asn', '')}" if asn_data.get('asn') else ""
        org = company_data.get("name", asn_data.get("org", "未知"))
        latitude = location_data.get("latitude", 0)
        longitude = location_data.get("longitude", 0)

        # ipapi.is 特有字段
        is_datacenter = ipapi_data.get("is_datacenter", False)
        is_proxy = ipapi_data.get("is_proxy", False)
        is_vpn = ipapi_data.get("is_vpn", False)
        is_tor = ipapi_data.get("is_tor", False)
        is_mobile = ipapi_data.get("is_mobile", False)
        is_crawler = ipapi_data.get("is_crawler", False)
        is_abuser = ipapi_data.get("is_abuser", False)
        company_type = company_data.get("type", "")
        company_abuser_score = company_data.get("abuser_score", "")
        asn_abuser_score = asn_data.get("abuser_score", "")

        # 解析 AbuseIPDB 数据（风控分数）
        abuse_score = 0
        usage_type = ""
        is_whitelisted = False
        is_tor = False
        total_reports = 0

        if abuseipdb_data:
            abuse_score = abuseipdb_data.get("abuseConfidenceScore", 0)
            usage_type = abuseipdb_data.get("usageType", "")
            is_whitelisted = abuseipdb_data.get("isWhitelisted", False)
            is_tor = abuseipdb_data.get("isTor", False)
            total_reports = abuseipdb_data.get("totalReports", 0)

        # 判断 IP 类型（优先使用 ipapi.is 数据）
        native_emoji = "❓"
        native_text = "未知"

        if is_tor:
            native_emoji = "🧅"
            native_text = "Tor 节点"
        elif is_proxy or is_vpn:
            native_emoji = "🔒"
            native_text = "代理/VPN"
        elif is_datacenter:
            native_emoji = "🏢"
            native_text = "数据中心"
        elif is_mobile:
            native_emoji = "📱"
            native_text = "移动网络"
        elif company_type == "isp":
            native_emoji = "✅"
            native_text = "原生 IP (ISP)"
        elif company_type == "hosting":
            native_emoji = "🏢"
            native_text = "托管服务"
        elif company_type == "business":
            native_emoji = "🏢"
            native_text = "企业网络"
        elif usage_type:
            # 如果有 AbuseIPDB 数据，作为补充
            usage_lower = usage_type.lower()
            if "residential" in usage_lower or "fixed line isp" in usage_lower:
                native_emoji = "✅"
                native_text = "原生 IP"
            elif "mobile" in usage_lower or "cellular" in usage_lower:
                native_emoji = "📱"
                native_text = "移动网络"
            elif "content delivery" in usage_lower or "cdn" in usage_lower:
                native_emoji = "🌐"
                native_text = "CDN"
        else:
            # 根据 ASN/Org 简单判断
            org_lower = org.lower()
            if any(keyword in org_lower for keyword in ["hosting", "server", "cloud", "datacenter", "data center"]):
                native_emoji = "🏢"
                native_text = "数据中心"
            elif any(keyword in org_lower for keyword in ["telecom", "mobile", "wireless", "cellular"]):
                native_emoji = "📱"
                native_text = "移动网络"
            else:
                native_emoji = "✅"
                native_text = "可能原生"

        # 根据滥用分数判断风险等级
        if abuse_score == 0:
            risk_emoji = "✅"
            risk_level = "安全"
        elif abuse_score < 25:
            risk_emoji = "🟢"
            risk_level = "低风险"
        elif abuse_score < 50:
            risk_emoji = "🟡"
            risk_level = "中风险"
        elif abuse_score < 75:
            risk_emoji = "🟠"
            risk_level = "高风险"
        else:
            risk_emoji = "🔴"
            risk_level = "极高风险"

        # 格式化结果
        location_parts = [city, region, country_name]
        location = ", ".join([p for p in location_parts if p])

        result_text = (
            f"📊 *IP 信息检测结果*\n\n"
            f"🌐 IP: `{ip}`\n\n"
        )

        # 风控指数（如果有 AbuseIPDB 数据）
        if abuseipdb_data:
            result_text += f"🎯 *AbuseIPDB 风控*: {risk_emoji} *{abuse_score}/100* ({risk_level})\n"

        result_text += f"🏠 *IP 类型*: {native_emoji} *{native_text}*\n"

        # ipapi.is 特殊标签
        tags = []
        if is_crawler:
            tags.append("🕷️ 爬虫")
        if is_abuser:
            tags.append("⚠️ 滥用者")
        if is_whitelisted:
            tags.append("⭐ 白名单")

        if tags:
            result_text += f"🏷️ *标签*: {' '.join(tags)}\n"

        # ipapi.is 滥用分数
        if company_abuser_score:
            result_text += f"📊 *公司滥用分数*: {company_abuser_score}\n"
        if asn_abuser_score:
            result_text += f"📊 *ASN 滥用分数*: {asn_abuser_score}\n"

        result_text += (
            f"\n📍 *地理位置*\n"
            f"• 位置: {location}\n"
        )

        if latitude and longitude:
            result_text += f"• 坐标: {latitude}, {longitude}\n"

        result_text += f"• ISP: {org}\n"

        if asn:
            result_text += f"• ASN: {asn}\n"

        if company_type:
            result_text += f"• 类型: {company_type.upper()}\n"

        if total_reports > 0:
            result_text += (
                f"\n⚠️ *AbuseIPDB 报告*\n"
                f"• 总报告数: {total_reports}\n"
            )

        result_text += f"\n🔗 [查看详情](https://ipcheck.ing/?ip={ip})"

        await status_msg.edit_text(
            result_text,
            parse_mode="Markdown",
            disable_web_page_preview=True
        )

        # 自动删除结果消息
        await _schedule_deletion(context, chat_id, status_msg.message_id, config.auto_delete_delay)

        logger.info(f"✅ IP 查询成功: {ip_address} (风控分数: {abuse_score})")

    except Exception as e:
        logger.error(f"IP 查询失败: {e}", exc_info=True)
        error_text = f"❌ 查询失败: {str(e)}"
        await status_msg.edit_text(error_text)
        await _schedule_deletion(context, chat_id, status_msg.message_id, config.auto_delete_delay)

    if update.message:
        await delete_user_command(context, chat_id, update.message.message_id)


# 注册命令
command_factory.register_command(
    "ping",
    ping_command,
    permission=Permission.USER,  # 白名单用户可用
    description="查询 IP 信息和风控分数"
)
