"""
社交媒体解析命令模块
支持20+平台的视频、图片、图文解析
"""

import hashlib
import logging
import time
from pathlib import Path
from telegram import Update
from telegram.ext import ContextTypes

# IMPORTANT: Delay parsehub imports to allow patch to apply first
# ParseHub types are imported inside functions that need them
# from parsehub.types import Video, Image, VideoParseResult, ImageParseResult, MultimediaParseResult

from utils.command_factory import command_factory
from utils.error_handling import with_error_handling
from utils.message_manager import send_error, send_info, delete_user_command
from utils.permissions import Permission

logger = logging.getLogger(__name__)


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
        result, platform, parse_time, error_msg = await _adapter.parse_url(text, user_id, group_id)

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
        formatted = await _adapter.format_result(result, platform)
        logger.info(f"🔍 formatted结果: title='{formatted.get('title')}', desc='{formatted.get('desc', '')[:100]}'")

        # 构建标题和描述（类似parse_hub_bot：有title或desc才显示，都没有才显示"无标题"）
        if formatted['title'] or formatted['desc']:
            caption_parts = []
            title = formatted['title']
            desc = formatted['desc']

            # 去重：如果title包含desc或desc包含title，只显示一个
            if title and desc:
                # 检查是否重复（title包含desc的前50个字符，或desc包含title的前50个字符）
                if desc[:50] in title or title[:50] in desc:
                    # 重复了，只显示较长的那个
                    if len(title) >= len(desc):
                        caption_parts.append(f"**{title}**")
                    else:
                        caption_parts.append(desc[:500])
                else:
                    # 不重复，都显示
                    caption_parts.append(f"**{title}**")
                    caption_parts.append(desc[:500])
            elif title:
                caption_parts.append(f"**{title}**")
            elif desc:
                caption_parts.append(desc[:500])

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
                'desc': formatted.get('desc', ''),
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
        await _send_media(context, chat_id, result, caption, reply_to_message_id=update.message.message_id if update.message else None, reply_markup=reply_markup)

        # 删除状态消息
        await status_msg.delete()

        # 删除用户命令
        if update.message:
            await delete_user_command(context, chat_id, update.message.message_id)

        logger.info(f"用户 {user_id} 解析成功: {platform} - {formatted['title']}")

    except Exception as e:
        logger.error(f"解析失败: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ 处理失败: {str(e)}")
        if update.message:
            await delete_user_command(context, chat_id, update.message.message_id)


async def _send_media(context: ContextTypes.DEFAULT_TYPE, chat_id: int, download_result, caption: str, reply_to_message_id: int = None, reply_markup=None):
    """发送媒体文件"""
    from parsehub.types import Video, Image, VideoParseResult, ImageParseResult, MultimediaParseResult

    try:
        # download_result.pr 是原始的 ParseResult
        if isinstance(download_result.pr, VideoParseResult):
            # 发送视频
            await _send_video(context, chat_id, download_result, caption, reply_to_message_id, reply_markup)
        elif isinstance(download_result.pr, ImageParseResult):
            # 发送图片
            await _send_images(context, chat_id, download_result, caption, reply_to_message_id, reply_markup)
        elif isinstance(download_result.pr, MultimediaParseResult):
            # 发送混合媒体
            await _send_multimedia(context, chat_id, download_result, caption, reply_to_message_id, reply_markup)
        else:
            # 只发送文本
            await context.bot.send_message(
                chat_id=chat_id,
                text=caption,
                parse_mode="Markdown",
                reply_to_message_id=reply_to_message_id,
                disable_web_page_preview=True,
                reply_markup=reply_markup
            )
    except Exception as e:
        logger.error(f"发送媒体失败: {e}")
        raise


async def _send_video(context: ContextTypes.DEFAULT_TYPE, chat_id: int, download_result, caption: str, reply_to_message_id: int = None, reply_markup=None):
    """发送视频（支持视频分割和图床上传）"""
    media = download_result.media

    # 如果没有媒体文件（下载失败），只发送文本
    if not media or not hasattr(media, 'path') or not media.path:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"{caption}\n\n⚠️ 媒体下载失败",
            parse_mode="Markdown",
            reply_to_message_id=reply_to_message_id,
            disable_web_page_preview=True,
            reply_markup=reply_markup
        )
        return

    video_path = Path(media.path)

    # 检查文件大小（Telegram 限制 50MB）
    video_size_mb = video_path.stat().st_size / (1024 * 1024)

    if video_size_mb > 50:
        # 文件太大，尝试分割或上传到图床
        logger.info(f"视频文件过大 ({video_size_mb:.1f}MB)，尝试高级处理...")

        # 尝试视频分割
        video_parts = await _adapter.split_large_video(video_path)
        if len(video_parts) > 1:
            # 分割成功，逐个发送
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"{caption}\n\n📁 视频已分割为 {len(video_parts)} 个片段",
                parse_mode="Markdown",
                reply_to_message_id=reply_to_message_id,
                disable_web_page_preview=True
            )

            for i, part in enumerate(video_parts, 1):
                with open(part, 'rb') as video_file:
                    await context.bot.send_video(
                        chat_id=chat_id,
                        video=video_file,
                        caption=f"片段 {i}/{len(video_parts)}",
                        supports_streaming=True
                    )
            return

        # 分割失败或未启用，尝试上传到图床
        image_host_url = await _adapter.upload_to_image_host(video_path)
        if image_host_url:
            # 上传成功
            message_text = f"{caption}\n\n⚠️ 视频文件过大 ({video_size_mb:.1f}MB)\n📤 已上传到图床\n🔗 [点击查看视频]({image_host_url})"
            if media.thumb_url:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=media.thumb_url,
                    caption=message_text,
                    parse_mode="Markdown",
                    reply_to_message_id=reply_to_message_id
                )
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=message_text,
                    parse_mode="Markdown",
                    reply_to_message_id=reply_to_message_id,
                    disable_web_page_preview=False
                )
            return

        # 都失败了，只发送缩略图和提示
        if media.thumb_url:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=media.thumb_url,
                caption=f"{caption}\n\n⚠️ 视频文件过大 ({video_size_mb:.1f}MB)，无法直接发送",
                parse_mode="Markdown",
                reply_to_message_id=reply_to_message_id
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"{caption}\n\n⚠️ 视频文件过大，无法直接发送",
                parse_mode="Markdown",
                reply_to_message_id=reply_to_message_id,
                disable_web_page_preview=True
            )
        return

    # 文件大小正常，直接发送
    with open(video_path, 'rb') as video_file:
        await context.bot.send_video(
            chat_id=chat_id,
            video=video_file,
            caption=caption,
            parse_mode="Markdown",
            width=media.width or 0,
            height=media.height or 0,
            duration=media.duration or 0,
            reply_to_message_id=reply_to_message_id,
            supports_streaming=True,
            reply_markup=reply_markup
        )


async def _send_images(context: ContextTypes.DEFAULT_TYPE, chat_id: int, download_result, caption: str, reply_to_message_id: int = None, reply_markup=None):
    """发送图片"""
    media_list = download_result.media
    if not isinstance(media_list, list):
        media_list = [media_list]

    # 过滤掉None的媒体对象（下载失败的）
    media_list = [m for m in media_list if m is not None and hasattr(m, 'path') and m.path]

    if len(media_list) == 0:
        # 没有图片（下载失败），只发送文本
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"{caption}\n\n⚠️ 媒体下载失败（CDN错误），仅显示文字内容",
            parse_mode="Markdown",
            reply_to_message_id=reply_to_message_id,
            disable_web_page_preview=True,
            reply_markup=reply_markup
        )
    elif len(media_list) == 1:
        # 单张图片
        image_path = str(media_list[0].path)
        with open(image_path, 'rb') as photo_file:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=photo_file,
                caption=caption,
                parse_mode="Markdown",
                reply_to_message_id=reply_to_message_id,
                reply_markup=reply_markup
            )
    elif len(media_list) <= 10:
        # 多张图片（使用媒体组，最多10张）
        from telegram import InputMediaPhoto

        media_group = []
        for img in media_list[:10]:
            image_path = str(img.path)
            with open(image_path, 'rb') as photo_file:
                media_group.append(InputMediaPhoto(media=photo_file.read()))

        # 发送媒体组（不带caption）
        messages = await context.bot.send_media_group(
            chat_id=chat_id,
            media=media_group,
            reply_to_message_id=reply_to_message_id
        )

        # 单独发送文本消息带caption和按钮
        await context.bot.send_message(
            chat_id=chat_id,
            text=caption,
            parse_mode="Markdown",
            reply_to_message_id=messages[0].message_id,  # 回复到第一张图片
            disable_web_page_preview=True,
            reply_markup=reply_markup
        )
    else:
        # 超过10张，上传到图床并发送Telegraph链接（类似parse_hub_bot）
        if _adapter.config and _adapter.config.enable_image_host:
            try:
                # 上传图片到图床
                logger.info(f"上传 {len(media_list)} 张图片到图床...")
                uploaded_urls = []
                for img in media_list:
                    img_url = await _adapter.upload_to_image_host(img.path)
                    if img_url:
                        uploaded_urls.append(img_url)

                if uploaded_urls:
                    # 创建HTML内容
                    html_content = f"<p>{download_result.pr.desc or ''}</p><br><br>"
                    html_content += "".join([f'<img src="{url}">' for url in uploaded_urls])

                    # 发布到Telegraph
                    telegraph_url = await _adapter.publish_to_telegraph(download_result.pr, html_content)

                    if telegraph_url:
                        # 发送Telegraph链接
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=f"{caption}\n\n📷 共{len(media_list)}张图片\n🔗 [查看完整图集]({telegraph_url})",
                            parse_mode="Markdown",
                            reply_to_message_id=reply_to_message_id,
                            disable_web_page_preview=False,
                            reply_markup=reply_markup
                        )
                        return
            except Exception as e:
                logger.error(f"上传图床失败: {e}")

        # 图床失败或未启用，降级为分批发送
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"{caption}\n\n📷 共{len(media_list)}张图片，分批发送中...",
            parse_mode="Markdown",
            reply_to_message_id=reply_to_message_id,
            disable_web_page_preview=True,
            reply_markup=reply_markup
        )

        from telegram import InputMediaPhoto
        for batch_start in range(0, len(media_list), 10):
            batch = media_list[batch_start:batch_start + 10]
            media_group = []
            for img in batch:
                image_path = str(img.path)
                with open(image_path, 'rb') as photo_file:
                    media_group.append(InputMediaPhoto(media=photo_file.read()))
            await context.bot.send_media_group(chat_id=chat_id, media=media_group)


async def _send_multimedia(context: ContextTypes.DEFAULT_TYPE, chat_id: int, download_result, caption: str, reply_to_message_id: int = None, reply_markup=None):
    """发送混合媒体（参考parse_hub_bot的实现，使用media_group分批发送）"""
    from telegram import InputMediaPhoto, InputMediaVideo
    from parsehub.types import Video, Image

    media_list = download_result.media
    if not isinstance(media_list, list):
        media_list = [media_list]

    # 过滤掉None的媒体对象
    media_list = [m for m in media_list if m is not None and hasattr(m, 'path') and m.path]

    count = len(media_list)

    if count == 0:
        # 没有媒体文件，只发送文本
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"{caption}\n\n⚠️ 媒体下载失败",
            parse_mode="Markdown",
            reply_to_message_id=reply_to_message_id,
            disable_web_page_preview=True,
            reply_markup=reply_markup
        )
        return
    elif count == 1:
        # 单个媒体文件，直接发送
        media = media_list[0]
        if isinstance(media, Video):
            with open(str(media.path), 'rb') as video_file:
                await context.bot.send_video(
                    chat_id=chat_id,
                    video=video_file,
                    caption=caption,
                    parse_mode="Markdown",
                    reply_to_message_id=reply_to_message_id,
                    supports_streaming=True,
                    reply_markup=reply_markup
                )
        elif isinstance(media, Image):
            with open(str(media.path), 'rb') as photo_file:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=photo_file,
                    caption=caption,
                    parse_mode="Markdown",
                    reply_to_message_id=reply_to_message_id,
                    reply_markup=reply_markup
                )
    else:
        # 多个媒体文件，使用media_group分批发送（每批最多10个）
        # 参考: parse_hub_bot/methods/tg_parse_hub.py:809
        media_groups = []
        for i in range(0, count, 10):
            batch = media_list[i:i + 10]
            media_group = []
            for media in batch:
                try:
                    if isinstance(media, Video):
                        media_group.append(InputMediaVideo(
                            media=open(str(media.path), 'rb'),
                            width=media.width or 0,
                            height=media.height or 0,
                            duration=media.duration or 0,
                            supports_streaming=True
                        ))
                    elif isinstance(media, Image):
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
        if media_groups:
            first_message = media_groups[0][0] if media_groups[0] else None
            if first_message:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=caption,
                    parse_mode="Markdown",
                    reply_to_message_id=first_message.message_id,
                    disable_web_page_preview=True,
                    reply_markup=reply_markup
                )


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

    text = "🌐 *支持的平台列表：*\n\n"
    text += "\n".join([f"• {platform}" for platform in platforms])
    text += f"\n\n共支持 *{len(platforms)}* 个平台"

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text,
        parse_mode="Markdown"
    )

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
