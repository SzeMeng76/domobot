"""
网络诊断命令
支持 IP 检测、MAC 查询、网站检测、延迟测试、路由追踪
"""

import logging
import re
from typing import Optional, Dict, Tuple, List
from telegram import Update, InlineQueryResultArticle, InputTextMessageContent
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from uuid import uuid4

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


def detect_input_type(input_str: str) -> Tuple[str, str]:
    """
    检测输入类型
    返回: (类型, 标准化后的值)
    类型: ip, mac, domain, url
    """
    input_str = input_str.strip()

    # 检测 MAC 地址
    mac_patterns = [
        r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$',  # 00:1A:2B:3C:4D:5E or 00-1A-2B-3C-4D-5E
        r'^([0-9A-Fa-f]{4}\.){2}([0-9A-Fa-f]{4})$',     # 001A.2B3C.4D5E
        r'^[0-9A-Fa-f]{12}$'                             # 001A2B3C4D5E
    ]
    if any(re.match(pattern, input_str) for pattern in mac_patterns):
        return ("mac", input_str.upper())

    # 检测 URL
    if input_str.startswith(('http://', 'https://')):
        return ("url", input_str)

    # 检测 IPv4
    ipv4_pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
    if re.match(ipv4_pattern, input_str):
        return ("ip", input_str)

    # 检测 IPv6
    ipv6_pattern = r'^([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}$'
    if re.match(ipv6_pattern, input_str):
        return ("ip", input_str)

    # 默认当作域名
    return ("domain", input_str.lower())


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


async def get_mac_vendor(mac_address: str) -> Optional[Dict]:
    """从 macvendors.com 获取 MAC 厂商信息"""
    if not httpx_client:
        logger.error("httpx_client 未初始化")
        return None

    try:
        url = f"https://api.macvendors.com/{mac_address}"
        headers = {"User-Agent": "DomoBot/1.0"}

        logger.info(f"查询 MAC 地址: {mac_address}")

        response = await httpx_client.get(url, headers=headers, timeout=10.0)

        if response.status_code == 404:
            logger.warning(f"MAC 地址未找到: {mac_address}")
            return {"vendor": "未知厂商"}

        response.raise_for_status()
        vendor = response.text.strip()

        logger.info(f"✅ MAC 查询成功: {mac_address} -> {vendor}")
        return {"vendor": vendor}

    except Exception as e:
        logger.error(f"MAC 查询失败: {e}", exc_info=True)
        return None


async def check_website(url: str) -> Optional[Dict]:
    """检测网站可用性"""
    if not httpx_client:
        logger.error("httpx_client 未初始化")
        return None

    try:
        import time
        logger.info(f"检测网站: {url}")

        start_time = time.time()
        response = await httpx_client.head(url, follow_redirects=True, timeout=10.0)
        elapsed_ms = int((time.time() - start_time) * 1000)

        logger.info(f"✅ 网站检测成功: {url} - {response.status_code} ({elapsed_ms}ms)")

        return {
            "status_code": response.status_code,
            "elapsed_ms": elapsed_ms,
            "final_url": str(response.url),
            "headers": dict(response.headers)
        }

    except Exception as e:
        logger.error(f"网站检测失败: {e}", exc_info=True)
        return None


async def global_latency_test(target: str, test_type: str = "ping") -> Optional[Dict]:
    """
    全球延迟测试或 MTR 路由追踪
    test_type: "ping" 或 "mtr"
    """
    if not httpx_client:
        logger.error("httpx_client 未初始化")
        return None

    try:
        # 创建测试任务
        payload = {
            "type": test_type,
            "target": target,
            "limit": 6,
            "locations": [
                {"continent": "AS"},
                {"continent": "EU"},
                {"continent": "NA"},
                {"continent": "OC"},
                {"continent": "SA"},
                {"continent": "AF"}
            ]
        }

        logger.info(f"创建 {test_type} 测试: {target}")

        response = await httpx_client.post(
            "https://api.globalping.io/v1/measurements",
            json=payload,
            timeout=10.0
        )
        response.raise_for_status()
        data = response.json()
        measurement_id = data.get("id")

        if not measurement_id:
            return None

        # 等待测试完成
        import asyncio
        await asyncio.sleep(5 if test_type == "ping" else 10)

        # 获取结果
        response = await httpx_client.get(
            f"https://api.globalping.io/v1/measurements/{measurement_id}",
            timeout=30.0
        )
        response.raise_for_status()
        result = response.json()

        logger.info(f"✅ {test_type} 测试完成: {target}")
        return result

    except Exception as e:
        logger.error(f"{test_type} 测试失败: {e}", exc_info=True)
        return None


async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /scan <目标> - 网络诊断工具
    支持: IP地址、MAC地址、域名、URL、延迟测试、路由追踪
    """
    config = get_config()
    chat_id = update.effective_chat.id

    # 检查参数
    if not context.args or len(context.args) == 0:
        help_text = (
            "🔍 *网络诊断工具*\n\n"
            "*使用方法：*\n"
            "`/scan <目标>`\n\n"
            "*支持类型：*\n"
            "• IP 地址: `/scan 8.8.8.8`\n"
            "• MAC 地址: `/scan 00:1A:2B:3C:4D:5E`\n"
            "• 域名: `/scan google.com`\n"
            "• URL: `/scan https://google.com`\n"
            "• 延迟测试: `/scan latency google.com`\n"
            "• 路由追踪: `/scan mtr google.com`\n\n"
            "*查询信息：*\n"
            "• IP: 风控指数、类型、位置、ASN\n"
            "• MAC: 网卡厂商信息\n"
            "• 域名: 解析 IP + IP 信息\n"
            "• URL: 可用性 + 响应时间\n"
            "• Latency: 全球延迟测试\n"
            "• MTR: 路由追踪"
        )
        msg = await context.bot.send_message(
            chat_id=chat_id,
            text=help_text,
            parse_mode="Markdown"
        )
        await _schedule_deletion(context, chat_id, msg.message_id, config.auto_delete_delay)
        if update.message:
            await delete_user_command(context, chat_id, update.message.message_id)
        return

    # 检查是否是特殊命令
    first_arg = context.args[0].lower()

    if first_arg == "latency" and len(context.args) > 1:
        target = context.args[1]
        await handle_latency_test(update, context, target)
        return
    elif first_arg == "mtr" and len(context.args) > 1:
        target = context.args[1]
        await handle_mtr_test(update, context, target)
        return
    elif first_arg == "warp":
        await handle_warp_query(update, context)
        return

    input_value = context.args[0]

    # 检测输入类型
    input_type, normalized_value = detect_input_type(input_value)

    # 根据类型路由到不同处理函数
    if input_type == "mac":
        await handle_mac_query(update, context, normalized_value)
    elif input_type == "url":
        await handle_url_check(update, context, normalized_value)
    elif input_type == "domain":
        await handle_domain_query(update, context, normalized_value)
    elif input_type == "ip":
        await handle_ip_query(update, context, normalized_value)


async def handle_mac_query(update: Update, context: ContextTypes.DEFAULT_TYPE, mac_address: str) -> None:
    """处理 MAC 地址查询"""
    config = get_config()
    chat_id = update.effective_chat.id

    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"🔍 正在查询 MAC: `{mac_address}`\n⏳ 请稍候...",
        parse_mode="Markdown"
    )

    try:
        vendor_data = await get_mac_vendor(mac_address)

        if not vendor_data:
            await status_msg.edit_text("❌ 查询失败：无法获取 MAC 信息")
            await _schedule_deletion(context, chat_id, status_msg.message_id, config.auto_delete_delay)
            if update.message:
                await delete_user_command(context, chat_id, update.message.message_id)
            return

        vendor = vendor_data.get("vendor", "未知厂商")

        result_text = (
            f"📀 *MAC 地址查询结果*\n\n"
            f"🔢 MAC: `{mac_address}`\n"
            f"🏢 厂商: *{vendor}*"
        )

        await status_msg.edit_text(result_text, parse_mode="Markdown")
        await _schedule_deletion(context, chat_id, status_msg.message_id, config.auto_delete_delay)
        logger.info(f"✅ MAC 查询成功: {mac_address}")

    except Exception as e:
        logger.error(f"MAC 查询失败: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ 查询失败: {str(e)}")
        await _schedule_deletion(context, chat_id, status_msg.message_id, config.auto_delete_delay)

    if update.message:
        await delete_user_command(context, chat_id, update.message.message_id)


async def handle_url_check(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str) -> None:
    """处理 URL 可用性检测"""
    config = get_config()
    chat_id = update.effective_chat.id

    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"🔍 正在检测: `{url}`\n⏳ 请稍候...",
        parse_mode="Markdown"
    )

    try:
        check_data = await check_website(url)

        if not check_data:
            await status_msg.edit_text("❌ 检测失败：无法访问网站")
            await _schedule_deletion(context, chat_id, status_msg.message_id, config.auto_delete_delay)
            if update.message:
                await delete_user_command(context, chat_id, update.message.message_id)
            return

        status_code = check_data.get("status_code", 0)
        elapsed_ms = check_data.get("elapsed_ms", 0)
        final_url = check_data.get("final_url", url)

        # 判断状态
        if 200 <= status_code < 300:
            status_emoji = "✅"
            status_text = "可访问"
        elif 300 <= status_code < 400:
            status_emoji = "🔄"
            status_text = "重定向"
        elif 400 <= status_code < 500:
            status_emoji = "⚠️"
            status_text = "客户端错误"
        elif 500 <= status_code < 600:
            status_emoji = "❌"
            status_text = "服务器错误"
        else:
            status_emoji = "❓"
            status_text = "未知"

        result_text = (
            f"🚦 *网站可用性检测*\n\n"
            f"🌐 URL: `{url}`\n"
            f"{status_emoji} *状态*: {status_text}\n"
            f"📊 *HTTP*: {status_code}\n"
            f"⏱️ *响应时间*: {elapsed_ms}ms\n"
        )

        if final_url != url:
            result_text += f"🔄 *最终 URL*: `{final_url}`\n"

        await status_msg.edit_text(result_text, parse_mode="Markdown")
        await _schedule_deletion(context, chat_id, status_msg.message_id, config.auto_delete_delay)
        logger.info(f"✅ URL 检测成功: {url}")

    except Exception as e:
        logger.error(f"URL 检测失败: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ 检测失败: {str(e)}")
        await _schedule_deletion(context, chat_id, status_msg.message_id, config.auto_delete_delay)

    if update.message:
        await delete_user_command(context, chat_id, update.message.message_id)


async def handle_domain_query(update: Update, context: ContextTypes.DEFAULT_TYPE, domain: str) -> None:
    """处理域名查询（解析 IP 后查询 IP 信息）"""
    config = get_config()
    chat_id = update.effective_chat.id

    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"🔍 正在解析域名: `{domain}`\n⏳ 请稍候...",
        parse_mode="Markdown"
    )

    try:
        import socket
        # 解析域名到 IP
        ip_address = socket.gethostbyname(domain)
        logger.info(f"域名解析: {domain} -> {ip_address}")

        # 查询 IP 信息
        await status_msg.edit_text(f"🔍 正在查询 IP: `{ip_address}`\n⏳ 请稍候...")

        # 调用 IP 查询逻辑
        await handle_ip_query(update, context, ip_address, domain=domain, status_msg=status_msg)

    except socket.gaierror:
        await status_msg.edit_text(f"❌ 域名解析失败：无法解析 `{domain}`", parse_mode="Markdown")
        await _schedule_deletion(context, chat_id, status_msg.message_id, config.auto_delete_delay)
        if update.message:
            await delete_user_command(context, chat_id, update.message.message_id)
    except Exception as e:
        logger.error(f"域名查询失败: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ 查询失败: {str(e)}")
        await _schedule_deletion(context, chat_id, status_msg.message_id, config.auto_delete_delay)
        if update.message:
            await delete_user_command(context, chat_id, update.message.message_id)


async def handle_latency_test(update: Update, context: ContextTypes.DEFAULT_TYPE, target: str) -> None:
    """处理全球延迟测试"""
    config = get_config()
    chat_id = update.effective_chat.id

    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"🔍 正在测试全球延迟: `{target}`\n⏳ 请稍候 5-10 秒...",
        parse_mode="Markdown"
    )

    try:
        result = await global_latency_test(target, "ping")

        if not result or result.get("status") != "finished":
            await status_msg.edit_text("❌ 延迟测试失败")
            await _schedule_deletion(context, chat_id, status_msg.message_id, config.auto_delete_delay)
            if update.message:
                await delete_user_command(context, chat_id, update.message.message_id)
            return

        # 解析结果
        results = result.get("results", [])
        if not results:
            await status_msg.edit_text("❌ 未获取到测试结果")
            await _schedule_deletion(context, chat_id, status_msg.message_id, config.auto_delete_delay)
            if update.message:
                await delete_user_command(context, chat_id, update.message.message_id)
            return

        # 按大洲分组
        continents = {"AS": "🌏 亚洲", "EU": "🌍 欧洲", "NA": "🌎 北美", "SA": "🌎 南美", "OC": "🌏 大洋洲", "AF": "🌍 非洲"}
        grouped = {}

        for r in results:
            probe = r.get("probe", {})
            result_data = r.get("result", {})
            stats = result_data.get("stats", {})

            continent = probe.get("continent", "")
            country = probe.get("country", "")
            city = probe.get("city", "")
            avg_latency = stats.get("avg", 0)

            if continent not in grouped:
                grouped[continent] = []

            grouped[continent].append({
                "country": country,
                "city": city,
                "latency": round(avg_latency, 1)
            })

        # 格式化输出
        result_text = f"⏱️ *全球延迟测试: {target}*\n\n"

        for continent_code, continent_name in continents.items():
            if continent_code in grouped:
                result_text += f"{continent_name}:\n"
                for location in grouped[continent_code]:
                    latency = location["latency"]
                    # 延迟等级
                    if latency < 50:
                        emoji = "✅"
                    elif latency < 100:
                        emoji = "🟢"
                    elif latency < 200:
                        emoji = "🟡"
                    elif latency < 300:
                        emoji = "🟠"
                    else:
                        emoji = "🔴"

                    result_text += f"  {location['city']}, {location['country']}: {latency}ms {emoji}\n"
                result_text += "\n"

        # 计算平均延迟
        all_latencies = [loc["latency"] for locs in grouped.values() for loc in locs]
        if all_latencies:
            avg_all = round(sum(all_latencies) / len(all_latencies), 1)
            min_latency = min(all_latencies)
            best_location = next((loc for locs in grouped.values() for loc in locs if loc["latency"] == min_latency), None)

            result_text += f"📊 *平均延迟*: {avg_all}ms\n"
            if best_location:
                result_text += f"✅ *最佳节点*: {best_location['city']}, {best_location['country']} ({min_latency}ms)"

        await status_msg.edit_text(result_text, parse_mode="Markdown")
        await _schedule_deletion(context, chat_id, status_msg.message_id, config.auto_delete_delay)
        logger.info(f"✅ 延迟测试完成: {target}")

    except Exception as e:
        logger.error(f"延迟测试失败: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ 测试失败: {str(e)}")
        await _schedule_deletion(context, chat_id, status_msg.message_id, config.auto_delete_delay)

    if update.message:
        await delete_user_command(context, chat_id, update.message.message_id)


async def handle_mtr_test(update: Update, context: ContextTypes.DEFAULT_TYPE, target: str) -> None:
    """处理 MTR 路由追踪"""
    config = get_config()
    chat_id = update.effective_chat.id

    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"🔍 正在追踪路由: `{target}`\n⏳ 请稍候 10-15 秒...",
        parse_mode="Markdown"
    )

    try:
        result = await global_latency_test(target, "mtr")

        if not result or result.get("status") != "finished":
            await status_msg.edit_text("❌ 路由追踪失败")
            await _schedule_deletion(context, chat_id, status_msg.message_id, config.auto_delete_delay)
            if update.message:
                await delete_user_command(context, chat_id, update.message.message_id)
            return

        # 解析结果（只显示第一个探测点的路由）
        results = result.get("results", [])
        if not results:
            await status_msg.edit_text("❌ 未获取到追踪结果")
            await _schedule_deletion(context, chat_id, status_msg.message_id, config.auto_delete_delay)
            if update.message:
                await delete_user_command(context, chat_id, update.message.message_id)
            return

        first_result = results[0]
        probe = first_result.get("probe", {})
        result_data = first_result.get("result", {})
        hops = result_data.get("hops", [])

        probe_location = f"{probe.get('city', '')}, {probe.get('country', '')}"

        result_text = f"📡 *MTR 路由追踪: {target}*\n"
        result_text += f"📍 *测试节点*: {probe_location}\n\n"
        result_text += "```\n"
        result_text += "跳 | IP地址              | 延迟\n"
        result_text += "---|---------------------|------\n"

        for i, hop in enumerate(hops[:15], 1):  # 只显示前15跳
            stats = hop.get("stats", {})
            avg_latency = stats.get("avg", 0)
            loss = stats.get("loss", 0)
            hostname = hop.get("resolvedHostname") or hop.get("resolvedAddress") or "*"

            # 截断过长的主机名
            if len(hostname) > 20:
                hostname = hostname[:17] + "..."

            if loss == 100:
                result_text += f"{i:2d} | {'*':20s} | -\n"
            else:
                result_text += f"{i:2d} | {hostname:20s} | {avg_latency:.1f}ms\n"

        result_text += "```"

        await status_msg.edit_text(result_text, parse_mode="Markdown")
        await _schedule_deletion(context, chat_id, status_msg.message_id, config.auto_delete_delay)
        logger.info(f"✅ MTR 追踪完成: {target}")

    except Exception as e:
        logger.error(f"MTR 追踪失败: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ 追踪失败: {str(e)}")
        await _schedule_deletion(context, chat_id, status_msg.message_id, config.auto_delete_delay)

    if update.message:
        await delete_user_command(context, chat_id, update.message.message_id)


async def handle_warp_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """查询 WARP 出口 IP 信息"""
    config = get_config()
    chat_id = update.effective_chat.id

    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text="🔍 正在查询 WARP 出口 IP...\n⏳ 请稍候...",
        parse_mode="Markdown"
    )

    try:
        # 创建带 WARP 代理的临时客户端
        import httpx
        async with httpx.AsyncClient(
            proxy="socks5://warp:1080",
            timeout=15.0
        ) as proxy_client:
            # 查询 ip-api.com (免费，无需token，限制更宽松)
            response = await proxy_client.get("http://ip-api.com/json/?fields=status,message,country,countryCode,region,regionName,city,zip,lat,lon,timezone,isp,org,as,query")
            response.raise_for_status()
            data = response.json()

            if data.get("status") != "success":
                raise Exception(f"IP查询失败: {data.get('message', 'Unknown error')}")

            warp_ip = data.get("query")

            # 查询 ipapi.is 获取更详细信息
            ipapi_data = None
            if warp_ip:
                try:
                    ipapi_response = await proxy_client.get(f"https://api.ipapi.is/?q={warp_ip}")
                    if ipapi_response.status_code == 200:
                        ipapi_data = ipapi_response.json()
                except Exception:
                    pass  # ipapi.is 失败不影响主要功能

        # 构建结果
        result_text = "🌐 *WARP 出口 IP 信息*\n\n"
        result_text += f"📍 *IP 地址*: `{data.get('query', 'N/A')}`\n"
        result_text += f"🏙️ *城市*: {data.get('city', 'N/A')}\n"
        result_text += f"🌍 *国家*: {data.get('country', 'N/A')} ({data.get('countryCode', 'N/A')})\n"
        result_text += f"📌 *地区*: {data.get('regionName', 'N/A')}\n"
        result_text += f"🏢 *ISP*: {data.get('isp', 'N/A')}\n"
        result_text += f"🏢 *组织*: {data.get('org', 'N/A')}\n"
        result_text += f"🔢 *AS*: `{data.get('as', 'N/A')}`\n"

        if data.get('lat') and data.get('lon'):
            result_text += f"🗺️ *坐标*: {data.get('lat')}, {data.get('lon')}\n"

        if data.get('timezone'):
            result_text += f"🕐 *时区*: {data.get('timezone')}\n"

        # 添加 ipapi.is 的详细信息
        if ipapi_data:
            company = ipapi_data.get('company', {})
            asn = ipapi_data.get('asn', {})

            result_text += f"\n*详细信息*:\n"
            result_text += f"🏢 *公司*: {company.get('name', 'N/A')}\n"
            result_text += f"🔢 *ASN*: `AS{asn.get('asn', 'N/A')}` ({asn.get('org', 'N/A')})\n"

            # IP 类型
            ip_type = []
            if ipapi_data.get('is_datacenter'):
                ip_type.append("数据中心")
            if ipapi_data.get('is_proxy'):
                ip_type.append("代理")
            if ipapi_data.get('is_vpn'):
                ip_type.append("VPN")
            if ipapi_data.get('is_tor'):
                ip_type.append("Tor")
            if ipapi_data.get('is_mobile'):
                ip_type.append("移动网络")

            if ip_type:
                result_text += f"🏷️ *类型*: {', '.join(ip_type)}\n"
            else:
                result_text += f"🏷️ *类型*: 住宅/普通 IP\n"

        result_text += f"\n💡 *提示*: 这是你的程序通过 WARP 访问外部网站时使用的 IP"

        await status_msg.edit_text(result_text, parse_mode="Markdown")
        await _schedule_deletion(context, chat_id, status_msg.message_id, config.auto_delete_delay)
        logger.info(f"✅ WARP IP 查询完成: {warp_data.get('ip')}")

    except Exception as e:
        logger.error(f"WARP IP 查询失败: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ 查询失败: {str(e)}\n\n💡 请确保 WARP 容器正在运行")
        await _schedule_deletion(context, chat_id, status_msg.message_id, config.auto_delete_delay)

    if update.message:
        await delete_user_command(context, chat_id, update.message.message_id)


async def handle_ip_query(update: Update, context: ContextTypes.DEFAULT_TYPE, ip_address: str, domain: str = None, status_msg = None) -> None:
    """处理 IP 地址查询"""
    config = get_config()
    chat_id = update.effective_chat.id

    # 如果没有传入 status_msg，创建新的
    if not status_msg:
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
        )

        # 如果是从域名查询来的，显示域名
        if domain:
            result_text += f"🌐 域名: `{domain}`\n"

        result_text += f"🌐 IP: `{ip}`\n\n"

        # 风控指数（如果有 AbuseIPDB 数据）
        if abuseipdb_data:
            result_text += f"🎯 *风控*: {risk_emoji} *{abuse_score}/100* ({risk_level})\n"

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
                f"\n⚠️ *滥用报告*\n"
                f"• 总报告数: {total_reports}\n"
            )

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
    "scan",
    ping_command,
    permission=Permission.USER,
    description="网络诊断工具（IP/MAC/域名/URL/延迟/MTR）"
)


async def handle_inline_scan(target: str, context: ContextTypes.DEFAULT_TYPE) -> List[InlineQueryResultArticle]:
    """
    处理 inline scan 查询
    用法: @botname scan 8.8.8.8$
    """
    try:
        # 检查是否是特殊命令
        parts = target.split(None, 1)
        first_arg = parts[0].lower() if parts else ""

        if first_arg == "latency" and len(parts) > 1:
            # 返回可点击的结果，点击后执行测试
            result_id = f"scan_latency_{uuid4().hex[:16]}"
            target_host = parts[1]

            # 缓存目标信息
            if not hasattr(context.bot_data, 'scan_inline_cache'):
                context.bot_data['scan_inline_cache'] = {}
            context.bot_data['scan_inline_cache'][result_id] = {
                'type': 'latency',
                'target': target_host
            }

            # 添加一个按钮显示测试信息
            from telegram import InlineKeyboardMarkup, InlineKeyboardButton
            reply_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("⏱️ 全球延迟测试", url=f"https://globalping.io")]
            ])

            return [
                InlineQueryResultArticle(
                    id=result_id,
                    title=f"⏱️ 全球延迟测试: {target_host}",
                    description="点击开始测试（需要 5-10 秒）",
                    input_message_content=InputTextMessageContent(
                        message_text=f"⏱️ 正在测试 {target_host} 的全球延迟...\n\n⏳ 请稍候，预计需要 5-10 秒",
                        parse_mode=ParseMode.MARKDOWN
                    ),
                    reply_markup=reply_markup
                )
            ]
        elif first_arg == "mtr" and len(parts) > 1:
            # 返回可点击的结果，点击后执行测试
            result_id = f"scan_mtr_{uuid4().hex[:16]}"
            target_host = parts[1]

            # 缓存目标信息
            if not hasattr(context.bot_data, 'scan_inline_cache'):
                context.bot_data['scan_inline_cache'] = {}
            context.bot_data['scan_inline_cache'][result_id] = {
                'type': 'mtr',
                'target': target_host
            }

            # 添加一个按钮显示测试信息
            from telegram import InlineKeyboardMarkup, InlineKeyboardButton
            reply_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("📡 MTR 路由追踪", url=f"https://globalping.io")]
            ])

            return [
                InlineQueryResultArticle(
                    id=result_id,
                    title=f"📡 MTR 路由追踪: {target_host}",
                    description="点击开始追踪（需要 10-15 秒）",
                    input_message_content=InputTextMessageContent(
                        message_text=f"📡 正在追踪 {target_host} 的路由...\n\n⏳ 请稍候，预计需要 10-15 秒",
                        parse_mode=ParseMode.MARKDOWN
                    ),
                    reply_markup=reply_markup
                )
            ]

        # 检测输入类型
        input_type, normalized_value = detect_input_type(target)

        # 根据类型执行不同查询
        if input_type == "ip":
            result_text = await _inline_query_ip(normalized_value)
        elif input_type == "mac":
            result_text = await _inline_query_mac(normalized_value)
        elif input_type == "domain":
            result_text = await _inline_query_domain(normalized_value)
        elif input_type == "url":
            result_text = await _inline_query_url(normalized_value)
        else:
            result_text = f"❌ 无法识别的目标: {target}"

        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title=f"🔍 Scan: {target}",
                description=f"查询 {input_type.upper()} 信息",
                input_message_content=InputTextMessageContent(
                    message_text=result_text,
                    parse_mode=ParseMode.MARKDOWN
                ),
            )
        ]

    except Exception as e:
        logger.error(f"Inline scan 失败: {e}", exc_info=True)
        return [
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="❌ 查询失败",
                description=str(e)[:100],
                input_message_content=InputTextMessageContent(
                    message_text=f"❌ 查询失败: {str(e)}"
                ),
            )
        ]


async def _inline_query_ip(ip_address: str) -> str:
    """Inline 查询 IP 信息"""
    import asyncio

    ipapi_task = get_ipapi_info(ip_address)
    abuseipdb_task = get_abuseipdb_score(ip_address)

    ipapi_data, abuseipdb_data = await asyncio.gather(ipapi_task, abuseipdb_task, return_exceptions=True)

    if isinstance(ipapi_data, Exception) or not ipapi_data:
        return f"❌ 无法获取 IP 信息: {ip_address}"

    # 解析数据（简化版）
    location_data = ipapi_data.get("location", {})
    company_data = ipapi_data.get("company", {})
    asn_data = ipapi_data.get("asn", {})

    city = location_data.get("city", "")
    country = location_data.get("country", "未知")
    org = company_data.get("name", "未知")
    company_type = company_data.get("type", "")
    is_datacenter = ipapi_data.get("is_datacenter", False)
    is_proxy = ipapi_data.get("is_proxy", False)

    # 判断 IP 类型
    if is_proxy:
        ip_type = "🔒 代理/VPN"
    elif is_datacenter:
        ip_type = "🏢 数据中心"
    elif company_type == "isp":
        ip_type = "✅ 原生 IP"
    else:
        ip_type = "❓ 未知"

    # 风控分数
    abuse_score = 0
    if isinstance(abuseipdb_data, dict):
        abuse_score = abuseipdb_data.get("abuseConfidenceScore", 0)

    result = f"📊 *IP 信息*\n\n"
    result += f"🌐 IP: `{ip_address}`\n"
    result += f"🎯 风控: {abuse_score}/100\n"
    result += f"🏠 类型: {ip_type}\n"
    result += f"📍 位置: {city}, {country}\n"
    result += f"🏢 ISP: {org}"

    return result


async def _inline_query_mac(mac_address: str) -> str:
    """Inline 查询 MAC 地址"""
    vendor_data = await get_mac_vendor(mac_address)

    if not vendor_data:
        return f"❌ 无法获取 MAC 信息: {mac_address}"

    vendor = vendor_data.get("vendor", "未知厂商")

    return f"📀 *MAC 地址查询*\n\n🔢 MAC: `{mac_address}`\n🏢 厂商: {vendor}"


async def _inline_query_domain(domain: str) -> str:
    """Inline 查询域名"""
    try:
        import socket
        ip_address = socket.gethostbyname(domain)
        # 查询 IP 信息
        ip_result = await _inline_query_ip(ip_address)
        return f"🌐 *域名: {domain}*\n\n{ip_result}"
    except socket.gaierror:
        return f"❌ 域名解析失败: {domain}"


async def _inline_query_url(url: str) -> str:
    """Inline 查询 URL 可用性"""
    check_data = await check_website(url)

    if not check_data:
        return f"❌ 无法访问: {url}"

    status_code = check_data.get("status_code", 0)
    elapsed_ms = check_data.get("elapsed_ms", 0)

    if 200 <= status_code < 300:
        status = "✅ 可访问"
    else:
        status = f"⚠️ HTTP {status_code}"

    return f"🚦 *网站检测*\n\n🌐 URL: `{url}`\n{status}\n⏱️ 响应: {elapsed_ms}ms"


async def handle_inline_scan_chosen(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    处理用户选择 inline scan 结果后的测试执行
    用于 latency 和 MTR 测试
    """
    chosen_result = update.chosen_inline_result
    inline_message_id = chosen_result.inline_message_id
    result_id = chosen_result.result_id

    # 只处理 scan_latency_ 和 scan_mtr_ 开头的结果
    if not (result_id.startswith("scan_latency_") or result_id.startswith("scan_mtr_")):
        return

    # 从缓存获取测试信息
    scan_cache = context.bot_data.get('scan_inline_cache', {})
    cached_data = scan_cache.get(result_id)

    if not cached_data:
        try:
            await context.bot.edit_message_text(
                inline_message_id=inline_message_id,
                text="❌ 测试请求已过期，请重新查询",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass
        return

    test_type = cached_data['type']
    target = cached_data['target']

    try:
        if test_type == 'latency':
            # 执行全球延迟测试
            result = await global_latency_test(target)

            if not result or result.get("status") != "finished":
                await context.bot.edit_message_text(
                    inline_message_id=inline_message_id,
                    text=f"❌ 延迟测试失败: {target}",
                    parse_mode=ParseMode.MARKDOWN
                )
                return

            # 解析结果
            results = result.get("results", [])
            if not results:
                await context.bot.edit_message_text(
                    inline_message_id=inline_message_id,
                    text=f"❌ 未获取到测试结果: {target}",
                    parse_mode=ParseMode.MARKDOWN
                )
                return

            # 按大洲分组
            continents = {"AS": "🌏 亚洲", "EU": "🌍 欧洲", "NA": "🌎 北美", "SA": "🌎 南美", "OC": "🌏 大洋洲", "AF": "🌍 非洲"}
            grouped = {}

            for r in results:
                probe = r.get("probe", {})
                result_data = r.get("result", {})
                stats = result_data.get("stats", {})

                continent = probe.get("continent", "")
                country = probe.get("country", "")
                city = probe.get("city", "")
                avg_latency = stats.get("avg", 0)

                if continent not in grouped:
                    grouped[continent] = []

                grouped[continent].append({
                    "country": country,
                    "city": city,
                    "latency": round(avg_latency, 1)
                })

            # 格式化输出
            response_lines = [f"⏱️ *全球延迟测试: {target}*\n"]

            for continent_code, continent_name in continents.items():
                if continent_code in grouped:
                    response_lines.append(f"{continent_name}:")
                    for location in grouped[continent_code]:
                        latency = location["latency"]
                        # 延迟等级
                        if latency < 50:
                            emoji = "✅"
                        elif latency < 100:
                            emoji = "🟢"
                        elif latency < 200:
                            emoji = "🟡"
                        elif latency < 300:
                            emoji = "🟠"
                        else:
                            emoji = "🔴"

                        response_lines.append(f"  {location['city']}, {location['country']}: {latency}ms {emoji}")
                    response_lines.append("")

            # 计算平均延迟
            all_latencies = [loc["latency"] for locs in grouped.values() for loc in locs]
            if all_latencies:
                avg_all = round(sum(all_latencies) / len(all_latencies), 1)
                response_lines.append(f"📊 平均延迟: {avg_all}ms")

            response_text = "\n".join(response_lines)

            await context.bot.edit_message_text(
                inline_message_id=inline_message_id,
                text=response_text,
                parse_mode=ParseMode.MARKDOWN
            )

        elif test_type == 'mtr':
            # 执行 MTR 路由追踪
            result = await global_latency_test(target, test_type="mtr")

            if not result or result.get("status") != "finished":
                await context.bot.edit_message_text(
                    inline_message_id=inline_message_id,
                    text=f"❌ MTR 追踪失败: {target}",
                    parse_mode=ParseMode.MARKDOWN
                )
                return

            # 解析结果（只显示第一个探测点的路由）
            results = result.get("results", [])
            if not results:
                await context.bot.edit_message_text(
                    inline_message_id=inline_message_id,
                    text=f"❌ 未获取到追踪结果: {target}",
                    parse_mode=ParseMode.MARKDOWN
                )
                return

            first_result = results[0]
            probe = first_result.get("probe", {})
            result_data = first_result.get("result", {})
            hops = result_data.get("hops", [])

            probe_location = f"{probe.get('city', '')}, {probe.get('country', '')}"

            response_text = f"📡 *MTR 路由追踪: {target}*\n"
            response_text += f"📍 *测试节点*: {probe_location}\n\n"
            response_text += "```\n"
            response_text += "跳 | IP地址              | 延迟\n"
            response_text += "---|---------------------|------\n"

            for i, hop in enumerate(hops[:15], 1):  # 只显示前15跳
                stats = hop.get("stats", {})
                avg_latency = stats.get("avg", 0)
                loss = stats.get("loss", 0)
                hostname = hop.get("resolvedHostname") or hop.get("resolvedAddress") or "*"

                # 截断过长的主机名
                if len(hostname) > 20:
                    hostname = hostname[:17] + "..."

                if loss == 100:
                    response_text += f"{i:2d} | {'*':20s} | -\n"
                else:
                    response_text += f"{i:2d} | {hostname:20s} | {avg_latency:.1f}ms\n"

            response_text += "```"

            await context.bot.edit_message_text(
                inline_message_id=inline_message_id,
                text=response_text,
                parse_mode=ParseMode.MARKDOWN
            )

    except Exception as e:
        logger.error(f"Inline scan chosen handler error: {e}")
        try:
            await context.bot.edit_message_text(
                inline_message_id=inline_message_id,
                text=f"❌ 测试执行失败: {str(e)}",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass

    finally:
        # 清理缓存
        if result_id in scan_cache:
            del scan_cache[result_id]


