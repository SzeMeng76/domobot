"""
社交媒体解析命令模块
支持20+平台的视频、图片、图文解析
"""

import hashlib
import logging
import os
import time
from pathlib import Path
from telegram import Update
from telegram.ext import ContextTypes
from PIL import Image as PILImage
import pillow_heif

from parsehub.types import VideoFile, ImageFile, VideoParseResult, ImageParseResult, MultimediaParseResult, RichTextParseResult
from utils.command_factory import command_factory
from utils.error_handling import with_error_handling


def _escape_markdown(text: str) -> str:
    """转义Markdown特殊字符"""
    if not text:
        return text
    # Telegram Markdown需要转义的字符
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text


def _format_text(text: str) -> str:
    """
    智能格式化文本内容，自动处理长文本

    - 超过900字：截断到800字并添加省略号（用于Telegraph摘要）
    - 其他：直接返回原文

    Args:
        text: 原始文本

    Returns:
        格式化后的文本
    """
    if not text:
        return text

    text = text.strip()

    # 超过900字：截断（用于Telegraph摘要显示）
    if len(text) > 900:
        text = text[:800] + "......"

    return text

from utils.message_manager import send_error, send_info, delete_user_command, _schedule_deletion
from utils.permissions import Permission
from utils.config_manager import get_config

logger = logging.getLogger(__name__)

# Register HEIF opener for Pillow
pillow_heif.register_heif_opener()


def _convert_image_to_webp(image_path: Path) -> Path:
    """
    Convert image to WebP format for better Telegram compatibility.
    Handles heif, heic, avif and other formats that may cause Telegram image_process_failed error.

    Reference: parse_hub_bot only converts HEIF/HEIC/AVIF to WebP, other formats are sent directly.
    WebP is preferred over JPEG because it has smaller file size with better quality.

    Args:
        image_path: Path to the image file

    Returns:
        Path to the converted image (or original if no conversion needed)
    """
    try:
        # Check file extension
        suffix = image_path.suffix.lower()

        # JPG, PNG, WebP are directly supported by Telegram
        if suffix in ['.jpg', '.jpeg', '.png', '.webp']:
            return image_path

        # HEIF/HEIC/AVIF need conversion (Telegram doesn't support them)
        if suffix not in ['.heif', '.heic', '.avif']:
            # Other formats: try to send directly first
            return image_path

        logger.info(f"🔄 Converting {suffix} image to WebP: {image_path.name}")

        # Open image
        img = PILImage.open(image_path)

        # Convert to RGBA if necessary (WebP supports transparency)
        if img.mode not in ('RGBA', 'RGB'):
            img = img.convert('RGBA')

        # Create new path with .webp extension
        new_path = image_path.with_suffix('.webp')

        # Save as WebP with high quality
        img.save(new_path, 'WEBP', quality=95, method=6)

        logger.info(f"✅ Image converted: {image_path.name} -> {new_path.name}")

        # Delete original file to save space
        try:
            image_path.unlink()
        except Exception as e:
            logger.warning(f"Failed to delete original image: {e}")

        return new_path

    except Exception as e:
        logger.error(f"❌ Image conversion failed: {e}, using original file")
        return image_path


def _generate_thumbnail(image_path: Path, max_width: int = 800, quality: int = 70) -> Path:
    """
    生成图片缩略图，用于优化Telegraph link preview加载速度

    为什么需要缩略图：
    - Telegraph页面有大量高清图片时，Telegram生成link preview需要加载所有图片
    - 用户在preview还没渲染完时点击，会导致页面闪烁
    - 使用缩略图可以让link preview快速渲染完成，避免闪烁

    Args:
        image_path: 原始图片路径
        max_width: 缩略图最大宽度（默认800px，足够preview显示）
        quality: JPEG质量（默认70，平衡大小和质量）

    Returns:
        缩略图路径
    """
    try:
        with PILImage.open(image_path) as img:
            # 如果图片宽度已经小于max_width，直接返回原图
            if img.width <= max_width:
                logger.debug(f"图片宽度({img.width}px)已小于{max_width}px，跳过缩略图生成")
                return image_path

            # 计算缩放比例
            ratio = max_width / img.width
            new_height = int(img.height * ratio)

            # 缩放图片
            img_resized = img.resize((max_width, new_height), PILImage.Resampling.LANCZOS)

            # 生成缩略图文件名
            thumb_path = image_path.parent / f"{image_path.stem}_thumb.jpg"

            # 保存为JPEG（压缩效果更好）
            if img_resized.mode in ('RGBA', 'LA', 'P'):
                # 如果有透明通道，转换为RGB并使用白色背景
                background = PILImage.new('RGB', img_resized.size, (255, 255, 255))
                if img_resized.mode == 'P':
                    img_resized = img_resized.convert('RGBA')
                background.paste(img_resized, mask=img_resized.split()[-1] if img_resized.mode == 'RGBA' else None)
                img_resized = background

            img_resized.save(thumb_path, 'JPEG', quality=quality, optimize=True)

        # 计算压缩比例（在with块外面，确保文件已保存）
        original_size = image_path.stat().st_size / 1024
        thumb_size = thumb_path.stat().st_size / 1024
        compression_ratio = (1 - thumb_size / original_size) * 100

        logger.info(f"✅ 生成缩略图: {image_path.name} ({original_size:.1f}KB) -> {thumb_path.name} ({thumb_size:.1f}KB), 压缩{compression_ratio:.1f}%")

        return thumb_path

    except Exception as e:
        logger.warning(f"⚠️ 生成缩略图失败: {e}，使用原图")
        return image_path


def get_url_hash(url: str) -> str:
    """生成URL的MD5哈希值（用于callback_data）"""
    md5 = hashlib.md5()
    md5.update(url.encode("utf-8"))
    return md5.hexdigest()

# 全局适配器实例
_adapter = None


def set_adapter(adapter):
    """设置 ParseHub 适配器"""
    global _adapter
    _adapter = adapter


@with_error_handling
async def parse_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /parse <URL> - 解析社交媒体链接
    /parse reply - 回复一条消息解析其中的链接
    """
    if not _adapter:
        await send_error(context, update.effective_chat.id, "❌ 解析功能未初始化")
        return

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    group_id = chat_id if chat_id < 0 else None

    # 获取要解析的文本
    text = None
    if context.args:
        text = " ".join(context.args)
    elif update.message.reply_to_message:
        text = update.message.reply_to_message.text or update.message.reply_to_message.caption

    if not text:
        help_text = (
            "📝 *使用方法：*\n\n"
            "• `/parse <链接>` \\- 解析指定链接\n"
            "• 回复一条消息并输入 `/parse` \\- 解析被回复消息中的链接\n\n"
            "🌐 *支持的平台：*\n"
            "抖音、快手、B站、YouTube、TikTok、小红书、Twitter/X、Instagram、Facebook、微博等20\\+平台"
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=help_text,
            parse_mode="MarkdownV2"
        )
        if update.message:
            await delete_user_command(context, chat_id, update.message.message_id)
        return

    # 检查是否包含支持的URL
    if not await _adapter.check_url_supported(text):
        await send_error(
            context,
            chat_id,
            "❌ 未检测到支持的平台链接\n\n支持：抖音、B站、YouTube、TikTok、小红书、Twitter等20+平台"
        )
        if update.message:
            await delete_user_command(context, chat_id, update.message.message_id)
        return

    # 发送处理中消息
    status_msg = await send_info(context, chat_id, "🔄 解析中...")

    try:
        # 解析URL
        result, parse_result, platform, parse_time, error_msg = await _adapter.parse_url(text, user_id, group_id)

        if not result:
            # 显示具体错误信息
            error_text = f"❌ {error_msg}" if error_msg else "❌ 解析失败，请检查链接是否正确"
            await status_msg.edit_text(error_text)
            if update.message:
                await delete_user_command(context, chat_id, update.message.message_id)
            return

        # 更新状态
        await status_msg.edit_text("📥 下载中...")

        # 格式化结果（result 现在是 DownloadResult）
        formatted = await _adapter.format_result(result, platform, parse_result=parse_result)
        logger.info(f"🔍 formatted结果: title='{formatted.get('title')}', content='{formatted.get('content', '')[:100]}'")

        # 构建标题和描述（类似parse_hub_bot：有title或content才显示，都没有才显示"无标题"）
        if formatted['title'] or formatted['content']:
            caption_parts = []
            title = formatted['title']
            desc = formatted['content']

            # 去重：如果title包含desc或desc包含title，只显示一个
            if title and desc:
                # 检查是否重复（title包含desc的前50个字符，或desc包含title的前50个字符）
                if desc[:50] in title or title[:50] in desc:
                    # 重复了，只显示较长的那个
                    if len(title) >= len(desc):
                        caption_parts.append(f"**{_escape_markdown(title)}**")
                    else:
                        caption_parts.append(_escape_markdown(_format_text(desc)))
                else:
                    # 不重复，都显示
                    caption_parts.append(f"**{_escape_markdown(title)}**")
                    caption_parts.append(_escape_markdown(_format_text(desc)))
            elif title:
                caption_parts.append(f"**{_escape_markdown(title)}**")
            elif desc:
                caption_parts.append(_escape_markdown(_format_text(desc)))

            caption = "\n\n".join(caption_parts)
        else:
            caption = "无标题"

        if formatted['url']:
            caption += f"\n\n🔗 [原链接]({formatted['url']})"
        caption += f"\n\n📱 平台: {platform.upper()}"

        # 更新状态
        await status_msg.edit_text("📤 上传中...")

        # 生成URL的MD5哈希（用于callback_data和缓存key）
        url_hash = get_url_hash(formatted['url'])
        logger.info(f"🔑 URL哈希: {url_hash}")

        # 创建inline keyboard按钮
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        buttons = [[InlineKeyboardButton("🔗 原链接", url=formatted['url'])]]

        # 如果启用了AI总结，添加AI总结按钮
        if _adapter.config and _adapter.config.enable_ai_summary:
            # 使用URL哈希作为callback_data（类似parse_hub_bot）
            buttons[0].append(InlineKeyboardButton("📝 AI总结", callback_data=f"summary_{url_hash}"))
            logger.info(f"✅ AI总结按钮已添加: summary_{url_hash}")
        else:
            logger.info(f"⚠️ 未添加AI总结按钮")

        reply_markup = InlineKeyboardMarkup(buttons)

        # 缓存解析数据到Redis（用于AI总结回调）
        if _adapter.config and _adapter.config.enable_ai_summary and _adapter.cache_manager:
            cache_data = {
                'url': formatted['url'],
                'caption': caption,
                'title': formatted.get('title', ''),
                'content': formatted.get('content', ''),
                'platform': platform
            }
            await _adapter.cache_manager.set(
                f"summary:{url_hash}",
                cache_data,
                ttl=86400,  # 缓存24小时
                subdirectory="social_parser"
            )
            logger.info(f"✅ 已缓存解析数据: cache:social_parser:summary:{url_hash}")

        # 发送媒体（带按钮）
        sent_messages = await _send_media(context, chat_id, result, caption, reply_to_message_id=update.message.message_id if update.message else None, reply_markup=reply_markup, parse_result=parse_result)

        # 删除状态消息
        await status_msg.delete()

        # 调度自动删除bot回复消息
        config = get_config()
        if sent_messages:
            for msg in sent_messages:
                await _schedule_deletion(context, chat_id, msg.message_id, config.auto_delete_delay)

        # 删除用户命令
        if update.message:
            await delete_user_command(context, chat_id, update.message.message_id)

        logger.info(f"用户 {user_id} 解析成功: {platform} - {formatted['title']}")

    except Exception as e:
        logger.error(f"解析失败: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ 处理失败: {str(e)}")
        if update.message:
            await delete_user_command(context, chat_id, update.message.message_id)


async def _send_media(context: ContextTypes.DEFAULT_TYPE, chat_id: int, download_result, caption: str, reply_to_message_id: int = None, reply_markup=None, parse_result=None):
    """发送媒体文件，返回发送的消息列表"""
    try:
        # 使用 parse_result（parsehub 2.0.0 不再存储在 download_result 中）
        pr = parse_result
        if isinstance(pr, VideoParseResult):
            # 发送视频
            return await _send_video(context, chat_id, download_result, caption, reply_to_message_id, reply_markup, parse_result=pr)
        elif isinstance(pr, ImageParseResult) or isinstance(pr, RichTextParseResult):
            # 发送图片
            return await _send_images(context, chat_id, download_result, caption, reply_to_message_id, reply_markup, parse_result=pr)
        elif isinstance(pr, MultimediaParseResult):
            # 发送混合媒体
            return await _send_multimedia(context, chat_id, download_result, caption, reply_to_message_id, reply_markup, parse_result=pr)
        else:
            # 只发送文本
            msg = await context.bot.send_message(
                chat_id=chat_id,
                text=caption,
                parse_mode="MarkdownV2",
                reply_to_message_id=reply_to_message_id,
                disable_web_page_preview=True,
                reply_markup=reply_markup
            )
            return [msg]
    except Exception as e:
        logger.error(f"发送媒体失败: {e}")
        raise


async def _send_video(context: ContextTypes.DEFAULT_TYPE, chat_id: int, download_result, caption: str, reply_to_message_id: int = None, reply_markup=None, parse_result=None):
    """发送视频（支持视频分割和图床上传），返回发送的消息列表"""
    media = download_result.media

    # 调试日志：检查media状态
    logger.info(f"[DEBUG _send_video] media={media}, type={type(media)}, has_path={hasattr(media, 'path') if media else 'N/A'}, path={getattr(media, 'path', 'N/A') if media else 'N/A'}")

    # 如果没有媒体文件，检查是否是长文本（超过500字自动Telegraph）
    if not media or not hasattr(media, 'path') or not media.path:
        # 获取原始文本内容（未转义的）
        raw_text = ""
        if parse_result:
            pr = parse_result
            if hasattr(pr, 'title') and pr.title:
                raw_text += pr.title + "\n\n"
            if hasattr(pr, 'content') and pr.content:
                raw_text += pr.content

        # 超过1000字，自动发布到Telegraph
        if len(raw_text) > 500:
            try:
                logger.info(f"检测到长文本 ({len(raw_text)}字)，自动发布到Telegraph")
                from markdown import markdown
                # 将文本转换为HTML
                html_content = markdown(raw_text)
                telegraph_url = await _adapter.publish_to_telegraph(parse_result, html_content)

                if telegraph_url:
                    # Telegraph成功，发送摘要+链接
                    summary = _format_text(raw_text)  # 截断到900字
                    msg = await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"{_escape_markdown(summary)}\n\n📰 [查看完整内容]({telegraph_url})",
                        parse_mode="MarkdownV2",
                        reply_to_message_id=reply_to_message_id,
                        disable_web_page_preview=False,
                        reply_markup=reply_markup
                    )
                    return [msg]
            except Exception as e:
                logger.warning(f"长文本Telegraph发布失败，降级为普通文本: {e}")

        # 普通文本或Telegraph失败，直接发送
        msg = await context.bot.send_message(
            chat_id=chat_id,
            text=caption,
            parse_mode="MarkdownV2",
            reply_to_message_id=reply_to_message_id,
            disable_web_page_preview=True,
            reply_markup=reply_markup
        )
        return [msg]

    video_path = Path(media.path)

    # 检查文件大小（Telegram 限制 50MB）
    video_size_mb = video_path.stat().st_size / (1024 * 1024)

    if video_size_mb > 50:
        # 大文件处理：优先级瀑布流
        # 50MB-2GB: Pyrogram → 分割 → 图床
        # >2GB: 分割 → 图床
        logger.info(f"视频文件过大 ({video_size_mb:.1f}MB)，启动优先级瀑布流处理...")

        # 步骤1: 先发送预览（缩略图 + 信息），让用户先看到内容
        size_text = f"{video_size_mb:.1f}".replace(".", "\\.")
        preview_caption = f"{caption}\n\n📦 文件大小: {size_text}MB\n📤 大文件上传中，请稍候\\.\\.\\."

        preview_msg = None
        if media.thumb_url:
            # 有缩略图，先发送缩略图
            try:
                preview_msg = await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=media.thumb_url,
                    caption=preview_caption,
                    parse_mode="MarkdownV2",
                    reply_to_message_id=reply_to_message_id,
                    reply_markup=reply_markup
                )
            except Exception as e:
                logger.warning(f"发送预览缩略图失败: {e}")

        if not preview_msg:
            # 无缩略图或发送失败，发送纯文本
            preview_msg = await context.bot.send_message(
                chat_id=chat_id,
                text=preview_caption,
                parse_mode="MarkdownV2",
                reply_to_message_id=reply_to_message_id,
                disable_web_page_preview=True
            )

        # 步骤2: 优先尝试Pyrogram上传（仅50MB-2GB文件）
        if 50 < video_size_mb <= 2048:  # 2GB = 2048MB
            try:
                logger.info(f"🚀 尝试Pyrogram上传 {video_size_mb:.1f}MB 视频...")

                # 获取Pyrogram客户端
                pyrogram_helper = getattr(_adapter, 'pyrogram_helper', None)

                if pyrogram_helper and pyrogram_helper.is_started:
                    # 使用Pyrogram发送大视频
                    from utils.pyrogram_client import PyrogramHelper

                    video_msg = await pyrogram_helper.send_large_video(
                        chat_id=chat_id,
                        video_path=str(video_path),
                        caption=caption,
                        reply_to_message_id=reply_to_message_id,
                        width=media.width or 0,
                        height=media.height or 0,
                        duration=media.duration or 0,
                        thumb=media.thumb_url,
                        reply_markup=reply_markup,
                        parse_mode="MarkdownV2"
                    )

                    # 上传成功，删除预览消息
                    try:
                        await preview_msg.delete()
                    except:
                        pass

                    logger.info(f"✅ Pyrogram上传成功: {video_size_mb:.1f}MB")
                    return [video_msg]
                else:
                    logger.warning("Pyrogram客户端未启动，跳过Pyrogram上传")

            except Exception as e:
                logger.warning(f"⚠️ Pyrogram上传失败: {e}，降级到分割/图床方案")

        # 步骤3: 尝试视频分割（如果启用FFmpeg）
        logger.info("🔪 尝试视频分割...")
        video_parts = await _adapter.split_large_video(video_path)
        if len(video_parts) > 1:
            # 分割成功，更新预览消息
            try:
                if media.thumb_url:
                    await preview_msg.edit_caption(
                        caption=f"{caption}\n\n📁 视频已分割为 {len(video_parts)} 个片段",
                        parse_mode="MarkdownV2"
                    )
                else:
                    await preview_msg.edit_text(
                        text=f"{caption}\n\n📁 视频已分割为 {len(video_parts)} 个片段",
                        parse_mode="MarkdownV2"
                    )
            except Exception as e:
                logger.debug(f"更新预览消息失败: {e}")

            sent_messages = [preview_msg]
            for i, part in enumerate(video_parts, 1):
                with open(part, 'rb') as video_file:
                    msg = await context.bot.send_video(
                        chat_id=chat_id,
                        video=video_file,
                        caption=f"片段 {i}/{len(video_parts)}",
                        supports_streaming=True
                    )
                    sent_messages.append(msg)

            logger.info(f"✅ 视频分割成功: {len(video_parts)} 个片段")
            return sent_messages

        # 步骤4: 兜底方案 - 上传到图床
        logger.info("📤 尝试图床上传...")
        image_host_url = await _adapter.upload_to_image_host(video_path)
        if image_host_url:
            # 图床上传成功，更新预览消息
            size_text = f"{video_size_mb:.1f}".replace(".", "\\.")
            success_caption = f"{caption}\n\n⚠️ 视频文件过大 \\({size_text}MB\\)\n📤 已上传到图床\n🔗 [点击查看视频]({image_host_url})"

            try:
                if media.thumb_url:
                    await preview_msg.edit_caption(
                        caption=success_caption,
                        parse_mode="MarkdownV2"
                    )
                else:
                    await preview_msg.edit_text(
                        text=success_caption,
                        parse_mode="MarkdownV2",
                        disable_web_page_preview=False
                    )
            except Exception as e:
                logger.debug(f"更新预览消息失败: {e}")

            logger.info(f"✅ 图床上传成功: {image_host_url}")
            return [preview_msg]

        # 步骤5: 所有方案都失败，更新预览消息为失败提示
        logger.warning("❌ 所有上传方案均失败")
        size_text = f"{video_size_mb:.1f}".replace(".", "\\.")
        fail_caption = f"{caption}\n\n⚠️ 视频文件过大 \\({size_text}MB\\)，所有上传方案均失败"

        try:
            if media.thumb_url:
                await preview_msg.edit_caption(
                    caption=fail_caption,
                    parse_mode="MarkdownV2"
                )
            else:
                await preview_msg.edit_text(
                    text=fail_caption,
                    parse_mode="MarkdownV2"
                )
        except Exception as e:
            logger.debug(f"更新预览消息失败: {e}")

        return [preview_msg]

    # 文件大小正常，直接发送
    with open(video_path, 'rb') as video_file:
        msg = await context.bot.send_video(
            chat_id=chat_id,
            video=video_file,
            caption=caption,
            parse_mode="MarkdownV2",
            width=media.width or 0,
            height=media.height or 0,
            duration=media.duration or 0,
            reply_to_message_id=reply_to_message_id,
            supports_streaming=True,
            reply_markup=reply_markup
        )
    return [msg]


async def _send_images(context: ContextTypes.DEFAULT_TYPE, chat_id: int, download_result, caption: str, reply_to_message_id: int = None, reply_markup=None, parse_result=None):
    """发送图片，返回发送的消息列表"""
    from parsehub.parsers.parser.coolapk import CoolapkImageParseResult
    from markdown import markdown

    # 检查是否是微信文章或酷安图文 - 自动使用 Telegraph
    if parse_result:
        # 微信公众号文章 (parsehub 2.0.0: WXParser returns RichTextParseResult)
        if isinstance(parse_result, RichTextParseResult) and hasattr(parse_result, 'markdown_content'):
            try:
                logger.info("检测到微信文章，自动发布到Telegraph")
                if parse_result.markdown_content:
                    html_content = markdown(parse_result.markdown_content.replace("mmbiz.qpic.cn", "mmbiz.qpic.cn.in"))
                    telegraph_url = await _adapter.publish_to_telegraph(parse_result, html_content)

                    if telegraph_url:
                        msg = await context.bot.send_message(
                            chat_id=chat_id,
                            text=f"{caption}\n\n📰 [查看完整文章]({telegraph_url})",
                            parse_mode="MarkdownV2",
                            reply_to_message_id=reply_to_message_id,
                            disable_web_page_preview=False,
                            reply_markup=reply_markup
                        )
                        return [msg]
            except Exception as e:
                logger.error(f"微信文章Telegraph发布失败: {e}")

        # 酷安图文内容
        elif isinstance(parse_result, CoolapkImageParseResult):
            try:
                if hasattr(parse_result, 'coolapk') and hasattr(parse_result.coolapk, 'markdown_content'):
                    markdown_content = parse_result.coolapk.markdown_content
                    if markdown_content:
                        logger.info("检测到酷安图文，自动发布到Telegraph")
                        html_content = markdown(markdown_content.replace("image.coolapk.com", "qpic.cn.in/image.coolapk.com"))
                        telegraph_url = await _adapter.publish_to_telegraph(parse_result, html_content)

                        if telegraph_url:
                            msg = await context.bot.send_message(
                                chat_id=chat_id,
                                text=f"{caption}\n\n📰 [查看完整内容]({telegraph_url})",
                                parse_mode="MarkdownV2",
                                reply_to_message_id=reply_to_message_id,
                                disable_web_page_preview=False,
                                reply_markup=reply_markup
                            )
                            return [msg]
            except Exception as e:
                logger.error(f"酷安图文Telegraph发布失败: {e}")

    media_list = download_result.media
    if not isinstance(media_list, list):
        media_list = [media_list]

    # 调试日志：检查下载结果
    logger.info(f"[DEBUG _send_images] 原始media_list长度: {len(media_list) if media_list else 0}")
    if media_list and len(media_list) > 0:
        logger.info(f"[DEBUG _send_images] 第一个media对象: type={type(media_list[0])}, has_path={hasattr(media_list[0], 'path')}, path={getattr(media_list[0], 'path', 'N/A')[:100] if hasattr(media_list[0], 'path') else 'N/A'}")

    # 过滤掉None的媒体对象（下载失败的）
    media_list = [m for m in media_list if m is not None and hasattr(m, 'path') and m.path]

    logger.info(f"[DEBUG _send_images] 过滤后media_list长度: {len(media_list)}")

    # 如果没有媒体文件，检查是否是长文本（超过1000字自动Telegraph）
    if len(media_list) == 0:
        # 获取原始文本内容（未转义的）
        raw_text = ""
        if parse_result:
            if hasattr(parse_result, 'title') and parse_result.title:
                raw_text += parse_result.title + "\n\n"
            if hasattr(parse_result, 'content') and parse_result.content:
                raw_text += parse_result.content

        # 超过1000字，自动发布到Telegraph
        if len(raw_text) > 500:
            try:
                logger.info(f"检测到长文本 ({len(raw_text)}字)，自动发布到Telegraph")
                html_content = markdown(raw_text)
                telegraph_url = await _adapter.publish_to_telegraph(parse_result, html_content)

                if telegraph_url:
                    # Telegraph成功，发送摘要+链接
                    summary = _format_text(raw_text)  # 截断到900字
                    msg = await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"{_escape_markdown(summary)}\n\n📰 [查看完整内容]({telegraph_url})",
                        parse_mode="MarkdownV2",
                        reply_to_message_id=reply_to_message_id,
                        disable_web_page_preview=False,
                        reply_markup=reply_markup
                    )
                    return [msg]
            except Exception as e:
                logger.warning(f"长文本Telegraph发布失败，降级为普通文本: {e}")

        # 普通文本或Telegraph失败，直接发送
        msg = await context.bot.send_message(
            chat_id=chat_id,
            text=caption,
            parse_mode="MarkdownV2",
            reply_to_message_id=reply_to_message_id,
            disable_web_page_preview=True,
            reply_markup=reply_markup
        )
        return [msg]
    elif len(media_list) == 1:
        # 单张图片
        # Convert to WebP if needed to avoid Telegram image_process_failed error
        converted_path = _convert_image_to_webp(Path(media_list[0].path))
        image_path = str(converted_path)
        with open(image_path, 'rb') as photo_file:
            msg = await context.bot.send_photo(
                chat_id=chat_id,
                photo=photo_file,
                caption=caption,
                parse_mode="MarkdownV2",
                reply_to_message_id=reply_to_message_id,
                reply_markup=reply_markup
            )
        return [msg]
    elif len(media_list) <= 10:
        # 多张图片（使用媒体组，最多10张）
        from telegram import InputMediaPhoto
        import imghdr

        media_group = []
        for img in media_list[:10]:
            try:
                # Convert to WebP if needed to avoid Telegram image_process_failed error
                converted_path = _convert_image_to_webp(Path(img.path))
                image_path = str(converted_path)

                # Verify file is actually an image
                if not imghdr.what(image_path):
                    logger.warning(f"⚠️ Skipping invalid image file: {image_path}")
                    continue

                # 检查文件大小，如果超过9MB则压缩
                file_size = os.path.getsize(image_path)
                max_size = 9 * 1024 * 1024  # 9MB（留1MB余量）

                if file_size > max_size:
                    logger.warning(f"⚠️ 图片大小 {file_size / 1024 / 1024:.2f}MB 超过限制，压缩中...")
                    # 使用缩略图功能压缩（质量60%，最大宽度1920）
                    compressed_path = _generate_thumbnail(Path(image_path), max_width=1920, quality=60)
                    image_path = str(compressed_path)
                    logger.info(f"✅ 压缩后大小: {os.path.getsize(image_path) / 1024 / 1024:.2f}MB")

                # 使用open()打开文件对象，python-telegram-bot会正确处理
                # 使用with语句确保文件正确关闭
                with open(image_path, 'rb') as photo_file:
                    # 复制文件内容到内存，避免文件句柄在异步发送时关闭
                    photo_data = photo_file.read()
                    media_group.append(InputMediaPhoto(media=photo_data))

            except Exception as e:
                logger.warning(f"⚠️ Failed to process image {img.path}: {e}, skipping")
                continue

        # Check if we have any valid images
        if not media_group:
            logger.error("❌ No valid images to send")
            raise ValueError("All images failed validation")

        # 发送媒体组（不带caption）
        messages = await context.bot.send_media_group(
            chat_id=chat_id,
            media=media_group,
            reply_to_message_id=reply_to_message_id
        )

        # 单独发送文本消息带caption和按钮
        text_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=caption,
            parse_mode="MarkdownV2",
            reply_to_message_id=messages[0].message_id,  # 回复到第一张图片
            disable_web_page_preview=True,
            reply_markup=reply_markup
        )
        return list(messages) + [text_msg]
    else:
        # 超过10张图片，自动尝试图床+Telegraph（参考parse_hub_bot逻辑）
        logger.info(f"检测到 {len(media_list)} 张图片（>10张），尝试图床+Telegraph")
        try:
            # 生成缩略图并上传到图床（优化link preview渲染速度）
            uploaded_urls = []
            for img in media_list:
                # 生成缩略图（800px宽，质量70%）
                thumb_path = _generate_thumbnail(Path(img.path), max_width=800, quality=70)

                # 上传缩略图到图床
                img_url = await _adapter.upload_to_image_host(thumb_path)
                if img_url:
                    uploaded_urls.append(img_url)

                # 清理缩略图文件（如果是生成的缩略图）
                if thumb_path != Path(img.path):
                    try:
                        thumb_path.unlink()
                    except Exception as e:
                        logger.debug(f"清理缩略图失败: {e}")

            if uploaded_urls:
                # 创建HTML内容（使用原生lazy loading优化移动端加载）
                desc = parse_result.content if parse_result and hasattr(parse_result, 'content') else ""

                # 添加描述
                html_content = ""
                if desc:
                    html_content += f"<p>{desc}</p>"

                # 使用HTML5原生懒加载：前3张立即加载，后续图片lazy load
                # 配合缩略图，可以让Telegram link preview快速渲染完成
                for idx, url in enumerate(uploaded_urls):
                    if idx < 3:
                        # 前3张图片：立即加载（loading="eager"）
                        html_content += f'<figure><img src="{url}" loading="eager"/></figure>'
                    else:
                        # 后续图片：懒加载（loading="lazy"，浏览器原生支持）
                        html_content += f'<figure><img src="{url}" loading="lazy"/></figure>'

                # 添加图片数量统计
                html_content += f'<p><i>共 {len(uploaded_urls)} 张图片</i></p>'

                # 发布到Telegraph
                telegraph_url = await _adapter.publish_to_telegraph(parse_result, html_content) if parse_result else None

                if telegraph_url:
                    # Telegraph成功，发送链接（启用preview，缩略图让preview快速渲染完成）
                    msg = await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"{caption}\n\n📷 共 {len(media_list)} 张图片\n🔗 [查看完整图集]({telegraph_url})",
                        parse_mode="MarkdownV2",
                        reply_to_message_id=reply_to_message_id,
                        disable_web_page_preview=False,
                        reply_markup=reply_markup
                    )
                    return [msg]
        except Exception as e:
            logger.warning(f"图床+Telegraph失败，降级为分批发送: {e}")

        # 图床失败或未启用，降级为分批发送
        info_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=f"{caption}\n\n📷 共{len(media_list)}张图片，分批发送中...",
            parse_mode="MarkdownV2",
            reply_to_message_id=reply_to_message_id,
            disable_web_page_preview=True,
            reply_markup=reply_markup
        )

        sent_messages = [info_msg]
        from telegram import InputMediaPhoto
        for batch_start in range(0, len(media_list), 10):
            batch = media_list[batch_start:batch_start + 10]
            media_group = []
            for img in batch:
                image_path = str(img.path)
                with open(image_path, 'rb') as photo_file:
                    media_group.append(InputMediaPhoto(media=photo_file.read()))
            batch_messages = await context.bot.send_media_group(chat_id=chat_id, media=media_group)
            sent_messages.extend(batch_messages)

        return sent_messages


async def _send_multimedia(context: ContextTypes.DEFAULT_TYPE, chat_id: int, download_result, caption: str, reply_to_message_id: int = None, reply_markup=None, parse_result=None):
    """发送混合媒体（参考parse_hub_bot的实现，使用media_group分批发送），返回发送的消息列表"""
    from telegram import InputMediaPhoto, InputMediaVideo

    media_list = download_result.media
    if not isinstance(media_list, list):
        media_list = [media_list]

    # 过滤掉None的媒体对象
    media_list = [m for m in media_list if m is not None and hasattr(m, 'path') and m.path]

    count = len(media_list)

    # 如果没有媒体文件，检查是否是长文本（超过1000字自动Telegraph）
    if count == 0:
        # 获取原始文本内容（未转义的）
        raw_text = ""
        if parse_result:
            if hasattr(parse_result, 'title') and parse_result.title:
                raw_text += parse_result.title + "\n\n"
            if hasattr(parse_result, 'content') and parse_result.content:
                raw_text += parse_result.content

        # 超过1000字，自动发布到Telegraph
        if len(raw_text) > 500:
            try:
                logger.info(f"检测到长文本 ({len(raw_text)}字)，自动发布到Telegraph")
                from markdown import markdown
                html_content = markdown(raw_text)
                telegraph_url = await _adapter.publish_to_telegraph(parse_result, html_content)

                if telegraph_url:
                    # Telegraph成功，发送摘要+链接
                    summary = _format_text(raw_text)  # 截断到900字
                    msg = await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"{_escape_markdown(summary)}\n\n📰 [查看完整内容]({telegraph_url})",
                        parse_mode="MarkdownV2",
                        reply_to_message_id=reply_to_message_id,
                        disable_web_page_preview=False,
                        reply_markup=reply_markup
                    )
                    return [msg]
            except Exception as e:
                logger.warning(f"长文本Telegraph发布失败，降级为普通文本: {e}")

        # 普通文本或Telegraph失败，直接发送
        msg = await context.bot.send_message(
            chat_id=chat_id,
            text=caption,
            parse_mode="MarkdownV2",
            reply_to_message_id=reply_to_message_id,
            disable_web_page_preview=True,
            reply_markup=reply_markup
        )
        return [msg]
    elif count == 1:
        # 单个媒体文件，直接发送
        media = media_list[0]
        if isinstance(media, VideoFile):
            # 检查视频文件大小（Telegram限制50MB）
            video_path = Path(media.path)
            video_size_mb = video_path.stat().st_size / (1024 * 1024)

            if video_size_mb > 50:
                # 视频太大，只发送文本提示
                msg = await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"{caption}\n\n⚠️ 视频文件过大 \\({video_size_mb:.1f}MB\\)，无法直接发送",
                    parse_mode="MarkdownV2",
                    reply_to_message_id=reply_to_message_id,
                    disable_web_page_preview=True,
                    reply_markup=reply_markup
                )
                return [msg]

            with open(str(media.path), 'rb') as video_file:
                msg = await context.bot.send_video(
                    chat_id=chat_id,
                    video=video_file,
                    caption=caption,
                    parse_mode="MarkdownV2",
                    reply_to_message_id=reply_to_message_id,
                    supports_streaming=True,
                    reply_markup=reply_markup
                )
            return [msg]
        elif isinstance(media, ImageFile):
            with open(str(media.path), 'rb') as photo_file:
                msg = await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=photo_file,
                    caption=caption,
                    parse_mode="MarkdownV2",
                    reply_to_message_id=reply_to_message_id,
                    reply_markup=reply_markup
                )
            return [msg]
    else:
        # 多个媒体文件，使用media_group分批发送（每批最多10个）
        # 参考: parse_hub_bot/methods/tg_parse_hub.py:809
        media_groups = []
        for i in range(0, count, 10):
            batch = media_list[i:i + 10]
            media_group = []
            for media in batch:
                try:
                    if isinstance(media, VideoFile):
                        media_group.append(InputMediaVideo(
                            media=open(str(media.path), 'rb'),
                            width=media.width or 0,
                            height=media.height or 0,
                            duration=media.duration or 0,
                            supports_streaming=True
                        ))
                    elif isinstance(media, ImageFile):
                        media_group.append(InputMediaPhoto(media=open(str(media.path), 'rb')))
                except Exception as e:
                    logger.error(f"准备媒体失败: {e}")
                    continue

            if media_group:
                try:
                    messages = await context.bot.send_media_group(
                        chat_id=chat_id,
                        media=media_group,
                        reply_to_message_id=reply_to_message_id
                    )
                    media_groups.append(messages)
                except Exception as e:
                    logger.error(f"发送media_group失败: {e}")

        # 在第一个media_group下发送文本消息（带caption和按钮）
        sent_messages = []
        if media_groups:
            # 收集所有发送的媒体消息
            for group in media_groups:
                sent_messages.extend(group)

            first_message = media_groups[0][0] if media_groups[0] else None
            if first_message:
                text_msg = await context.bot.send_message(
                    chat_id=chat_id,
                    text=caption,
                    parse_mode="MarkdownV2",
                    reply_to_message_id=first_message.message_id,
                    disable_web_page_preview=True,
                    reply_markup=reply_markup
                )
                sent_messages.append(text_msg)

        return sent_messages


@with_error_handling
async def platforms_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/platforms - 查看支持的平台列表"""
    if not _adapter:
        await send_error(context, update.effective_chat.id, "❌ 解析功能未初始化")
        return

    platforms = await _adapter.get_supported_platforms()

    if not platforms:
        await send_error(context, update.effective_chat.id, "❌ 获取平台列表失败")
        return

    text = "🌐 *支持的平台列表*\n\n"

    for idx, platform in enumerate(platforms, 1):
        # ParseHub 返回格式: "平台名: 类型1|类型2"
        escaped_platform = _escape_markdown(platform)
        text += f"*{idx}\\.* {escaped_platform}\n"

    text += f"\n共支持 *{len(platforms)}* 个平台\n"
    text += f"_使用 /parse \\+ URL 进行解析_"

    reply_msg = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text,
        parse_mode="MarkdownV2"
    )

    # 调度删除回复消息（30秒后）
    await _schedule_deletion(context, update.effective_chat.id, reply_msg.message_id, delay=30)

    if update.message:
        await delete_user_command(context, update.effective_chat.id, update.message.message_id)


# 注册命令
command_factory.register_command(
    "parse",
    parse_command,
    permission=Permission.USER,  # 白名单用户/群组可用（涉及API费用）
    description="解析社交媒体链接"
)

command_factory.register_command(
    "platforms",
    platforms_command,
    permission=Permission.NONE,  # 公开命令，所有人可用
    description="查看支持的平台列表"
)
