"""
IP 风控检测命令
通过 FlareSolverr 访问 ping0.cc 查询 IP 风控指数
"""

import logging
import re
from telegram import Update
from telegram.ext import ContextTypes
from bs4 import BeautifulSoup

from utils.command_factory import command_factory
from utils.permissions import Permission
from utils.message_manager import send_error, delete_user_command
from utils.flaresolverr_client import get_flaresolverr_client

logger = logging.getLogger(__name__)


async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /ping <IP> - 查询 IP 风控指数
    """
    chat_id = update.effective_chat.id

    # 检查参数
    if not context.args or len(context.args) == 0:
        help_text = (
            "📊 *IP 风控检测*\n\n"
            "*使用方法：*\n"
            "`/ping <IP地址>`\n\n"
            "*示例：*\n"
            "`/ping 8.8.8.8`\n"
            "`/ping 1.1.1.1`"
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=help_text,
            parse_mode="Markdown"
        )
        if update.message:
            await delete_user_command(context, chat_id, update.message.message_id)
        return

    ip_address = context.args[0]

    # 验证 IP 格式
    ip_pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
    if not re.match(ip_pattern, ip_address):
        await send_error(context, chat_id, "❌ 无效的 IP 地址格式")
        if update.message:
            await delete_user_command(context, chat_id, update.message.message_id)
        return

    # 发送处理中消息
    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"🔍 正在查询 IP: `{ip_address}`\n⏳ 请稍候（可能需要 30-60 秒）...",
        parse_mode="Markdown"
    )

    try:
        # 获取 FlareSolverr 客户端
        client = get_flaresolverr_client()
        if not client:
            await status_msg.edit_text("❌ FlareSolverr 服务未配置或未运行")
            return

        # 查询 ping0.cc
        url = f"https://ping0.cc/ip/{ip_address}"
        logger.info(f"查询 IP 风控: {ip_address}")

        # FlareSolverr 的 get 方法是同步的，需要在 executor 中运行
        result = await context.bot.loop.run_in_executor(
            None,
            lambda: client.get(url, max_timeout=90000, disableMedia=True)
        )

        if not result or not result.get('html'):
            await status_msg.edit_text("❌ 查询失败：无法获取响应")
            return

        html = result.get('html', '')
        if not html:
            await status_msg.edit_text("❌ 查询失败：响应为空")
            return

        # 解析 HTML
        soup = BeautifulSoup(html, 'html.parser')

        # 检查是否还在验证页面
        if 'cf-turnstile' in html or 'captcha' in html.lower():
            await status_msg.edit_text(
                f"⚠️ 查询 `{ip_address}` 遇到人机验证\n"
                f"Cloudflare 需要更多时间验证，请稍后重试",
                parse_mode="Markdown"
            )
            return

        # 提取风控信息（根据 ping0.cc 的 HTML 结构解析）
        # TODO: 需要根据实际 HTML 结构调整选择器
        risk_score = soup.find('div', class_='risk-score')
        risk_level = soup.find('div', class_='risk-level')

        if risk_score or risk_level:
            # 成功提取到风控信息
            score_text = risk_score.get_text(strip=True) if risk_score else "未知"
            level_text = risk_level.get_text(strip=True) if risk_level else "未知"

            result_text = (
                f"📊 *IP 风控检测结果*\n\n"
                f"🌐 IP: `{ip_address}`\n"
                f"📈 风控指数: {score_text}\n"
                f"⚠️ 风险等级: {level_text}\n\n"
                f"🔗 [查看详情]({url})"
            )
        else:
            # 无法解析，返回原始链接
            result_text = (
                f"📊 *IP 风控检测*\n\n"
                f"🌐 IP: `{ip_address}`\n"
                f"✅ 查询成功，但无法自动解析结果\n\n"
                f"🔗 [点击查看详情]({url})\n\n"
                f"_提示：页面可能需要人工验证_"
            )

        await status_msg.edit_text(
            result_text,
            parse_mode="Markdown",
            disable_web_page_preview=True
        )

        logger.info(f"✅ IP 风控查询成功: {ip_address}")

    except Exception as e:
        logger.error(f"IP 风控查询失败: {e}", exc_info=True)
        await status_msg.edit_text(
            f"❌ 查询失败: {str(e)}\n\n"
            f"可能原因：\n"
            f"• FlareSolverr 服务异常\n"
            f"• Cloudflare 验证超时\n"
            f"• 网络连接问题"
        )

    if update.message:
        await delete_user_command(context, chat_id, update.message.message_id)


# 注册命令
command_factory.register_command(
    "ping",
    ping_command,
    permission=Permission.USER,  # 白名单用户可用
    description="查询 IP 风控指数"
)
