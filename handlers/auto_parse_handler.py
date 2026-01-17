"""
自动解析处理器
在启用的群组中自动监听并解析社交媒体链接
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters

logger = logging.getLogger(__name__)

# 全局适配器实例
_adapter = None


def set_adapter(adapter):
    """设置 ParseHub 适配器"""
    global _adapter
    _adapter = adapter


async def auto_parse_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    自动解析处理器
    在启用自动解析的群组中，检测并解析社交媒体链接
    """
    if not _adapter:
        return

    # 只处理群组消息
    if update.effective_chat.type not in ["group", "supergroup"]:
        return

    message = update.message
    if not message:
        return

    # 获取消息文本
    text = message.text or message.caption
    if not text:
        return

    user_id = update.effective_user.id
    group_id = update.effective_chat.id

    # 检查群组是否启用自动解析
    if not await _adapter.is_auto_parse_enabled(group_id):
        return

    # 检查是否包含支持的URL
    if not await _adapter.check_url_supported(text):
        return

    logger.info(f"群组 {group_id} 检测到支持的链接，开始自动解析")

    # 发送处理中消息
    status_msg = await message.reply_text("🔄 检测到链接，自动解析中...")

    try:
        # 解析URL
        result, platform, parse_time, error_msg = await _adapter.parse_url(text, user_id, group_id)

        if not result:
            error_text = f"❌ 自动解析失败: {error_msg}" if error_msg else "❌ 自动解析失败"
            await status_msg.edit_text(error_text)
            return

        # 更新状态
        await status_msg.edit_text("📥 下载中...")

        # 格式化结果
        formatted = await _adapter.format_result(result, platform)

        # 构建标题和描述
        caption = f"**{formatted['title']}**"
        if formatted['desc']:
            caption += f"\n\n{formatted['desc'][:200]}"
        if formatted['url']:
            caption += f"\n\n🔗 [原链接]({formatted['url']})"
        caption += f"\n\n📱 平台: {platform.upper()}"
        caption += f"\n🤖 自动解析"

        # 更新状态
        await status_msg.edit_text("📤 上传中...")

        # 导入发送媒体的函数
        from commands.social_parser import _send_media

        # 发送媒体
        await _send_media(context, group_id, result, caption, message.message_id)

        # 删除状态消息
        await status_msg.delete()

        logger.info(f"群组 {group_id} 自动解析成功: {platform} - {formatted['title']}")

    except Exception as e:
        logger.error(f"自动解析失败: {e}", exc_info=True)
        try:
            await status_msg.edit_text("❌ 自动解析失败")
        except Exception:
            pass


def setup_auto_parse_handler(application):
    """
    设置自动解析处理器

    Args:
        application: Telegram Application 实例
    """
    # 监听群组中的文本和图片说明消息
    # 优先级要低，避免干扰其他命令
    handler = MessageHandler(
        filters.ChatType.GROUPS & (filters.TEXT | filters.CAPTION) & ~filters.COMMAND,
        auto_parse_handler
    )

    # 添加到应用程序（添加到最后，优先级最低）
    application.add_handler(handler, group=99)

    logger.info("✅ 自动解析处理器已注册")
