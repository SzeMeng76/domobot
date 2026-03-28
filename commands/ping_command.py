"""
IP 信誉检测命令
通过 AbuseIPDB API 查询 IP 信誉和滥用报告
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
_api_key_index = 0  # API Key 轮询索引

def set_dependencies(c_manager, h_client):
    """设置依赖注入"""
    global cache_manager, httpx_client
    cache_manager = c_manager
    httpx_client = h_client


def get_next_api_key() -> Optional[str]:
    """获取下一个可用的 API Key（轮询）"""
    global _api_key_index
    config = get_config()

    if not config.abuseipdb_api_keys:
        logger.error("AbuseIPDB API Keys 未配置")
        return None

    # 轮询获取 API Key
    api_key = config.abuseipdb_api_keys[_api_key_index % len(config.abuseipdb_api_keys)]
    _api_key_index += 1

    return api_key


async def get_ip_reputation(ip_address: str) -> Optional[Dict]:
    """从 AbuseIPDB API 获取 IP 信誉信息，并缓存结果"""
    cache_key = f"abuseipdb_{ip_address}"
    cached_data = await cache_manager.load_cache(cache_key, subdirectory="abuseipdb")
    if cached_data:
        logger.info(f"使用缓存的 IP 信誉数据: {ip_address}")
        return cached_data

    api_key = get_next_api_key()
    if not api_key:
        logger.error("无可用的 AbuseIPDB API Key")
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

        logger.info(f"查询 IP 信誉: {ip_address} (使用 API Key: {api_key[:10]}...)")

        response = await httpx_client.get(url, headers=headers, params=params, timeout=30.0)
        response.raise_for_status()

        data = response.json().get("data", {})

        if data:
            # 缓存结果（默认7天）
            from utils.config_manager import get_config as _get_config
            cfg = _get_config()
            cache_duration = getattr(cfg, 'abuseipdb_cache_duration', 604800)
            await cache_manager.save_cache(cache_key, data, subdirectory="abuseipdb", duration=cache_duration)
            logger.info(f"✅ IP 信誉查询成功并缓存: {ip_address}")
            return data
        else:
            logger.warning(f"IP 信誉查询返回空数据: {ip_address}")
            return None

    except Exception as e:
        logger.error(f"IP 信誉查询失败: {e}", exc_info=True)
        return None


async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /ping <IP> - 查询 IP 信誉和滥用报告
    """
    config = get_config()
    chat_id = update.effective_chat.id

    # 检查参数
    if not context.args or len(context.args) == 0:
        help_text = (
            "📊 *IP 信誉检测*\n\n"
            "*使用方法：*\n"
            "`/ping <IP地址>`\n\n"
            "*示例：*\n"
            "`/ping 8.8.8.8`\n"
            "`/ping 1.1.1.1`\n\n"
            "*查询信息：*\n"
            "• 风控指数 (0-100)\n"
            "• IP 类型 (原生/数据中心)\n"
            "• 地理位置和 ISP\n"
            "• 滥用报告统计"
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
        # 获取 IP 信誉数据
        data = await get_ip_reputation(ip_address)

        if not data:
            await status_msg.edit_text("❌ 查询失败：无法获取 IP 信誉数据")
            await _schedule_deletion(context, chat_id, status_msg.message_id, config.auto_delete_delay)
            if update.message:
                await delete_user_command(context, chat_id, update.message.message_id)
            return

        # 解析数据
        ip = data.get("ipAddress", ip_address)
        abuse_score = data.get("abuseConfidenceScore", 0)
        country_code = data.get("countryCode", "未知")
        country_name = data.get("countryName", "未知")
        usage_type = data.get("usageType", "未知")
        isp = data.get("isp", "未知")
        domain = data.get("domain", "")
        is_whitelisted = data.get("isWhitelisted", False)
        is_tor = data.get("isTor", False)
        total_reports = data.get("totalReports", 0)
        num_distinct_users = data.get("numDistinctUsers", 0)
        last_reported = data.get("lastReportedAt", "")

        # 判断是否原生 IP（住宅 IP）
        is_native = False
        native_emoji = "❌"
        native_text = "非原生"

        usage_lower = usage_type.lower()
        if "residential" in usage_lower or "fixed line isp" in usage_lower:
            is_native = True
            native_emoji = "✅"
            native_text = "原生 IP"
        elif "data center" in usage_lower or "hosting" in usage_lower or "web hosting" in usage_lower:
            native_emoji = "🏢"
            native_text = "数据中心"
        elif "mobile" in usage_lower or "cellular" in usage_lower:
            is_native = True
            native_emoji = "📱"
            native_text = "移动网络"
        elif "content delivery" in usage_lower or "cdn" in usage_lower:
            native_emoji = "🌐"
            native_text = "CDN"
        elif "corporate" in usage_lower or "business" in usage_lower:
            native_emoji = "🏢"
            native_text = "企业网络"

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

        # 格式化结果 - 突出风控指数和原生 IP
        result_text = (
            f"📊 *IP 风控检测结果*\n\n"
            f"🌐 IP: `{ip}`\n\n"
            f"🎯 *风控指数*: {risk_emoji} *{abuse_score}/100* ({risk_level})\n"
            f"🏠 *IP 类型*: {native_emoji} *{native_text}*\n"
        )

        if is_whitelisted:
            result_text += f"⭐ *白名单 IP*\n"

        if is_tor:
            result_text += f"🧅 *Tor 出口节点*\n"

        result_text += (
            f"\n📍 *地理位置*\n"
            f"• 国家: {country_name} ({country_code})\n"
            f"• ISP: {isp}\n"
        )

        if domain:
            result_text += f"• 域名: {domain}\n"

        result_text += f"• 用途: {usage_type}\n"

        if total_reports > 0:
            result_text += (
                f"\n⚠️ *滥用报告*\n"
                f"• 总报告数: {total_reports}\n"
                f"• 报告用户数: {num_distinct_users}\n"
            )
            if last_reported:
                result_text += f"• 最后报告: {last_reported[:10]}\n"

        result_text += f"\n🔗 [查看详情](https://www.abuseipdb.com/check/{ip})"

        await status_msg.edit_text(
            result_text,
            parse_mode="Markdown",
            disable_web_page_preview=True
        )

        # 自动删除结果消息
        await _schedule_deletion(context, chat_id, status_msg.message_id, config.auto_delete_delay)

        logger.info(f"✅ IP 信誉查询成功: {ip_address} (分数: {abuse_score})")

    except Exception as e:
        logger.error(f"IP 信誉查询失败: {e}", exc_info=True)
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
    description="查询 IP 信誉和滥用报告"
)
