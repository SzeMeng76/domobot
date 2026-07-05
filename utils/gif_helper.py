"""
GIF 智能处理工具
当 GIF 数量过多时，跳过上传并提供下载按钮
参考 parse_hub_bot 实现
"""

import logging
from typing import Sequence
from itertools import batched
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from parsehub.types import AniFile, AniRef

logger = logging.getLogger(__name__)

# GIF 数量阈值：超过此数量时跳过上传（参考 parse_hub_bot）
GIF_ONLY_SKIP_DOWNLOAD_COUNT_THRESHOLD = 5


def should_skip_gif_upload(parse_result) -> bool:
    """
    判断是否应该跳过 GIF 上传

    参考 parse_hub_bot 实现：
    - services/pipeline.py L171-178: 下载阶段检测
    - plugins/parse.py L713-717: 上传阶段检测

    条件（必须同时满足）：
    1. 纯 GIF 内容（所有媒体都是 AniRef）
    2. GIF 数量超过阈值（默认5个）

    Args:
        parse_result: ParseResult 对象（包含 media 字段）

    Returns:
        是否应该跳过上传
    """
    if not parse_result or not hasattr(parse_result, 'media'):
        return False

    # 提取媒体引用（parse_result.media 可能是单个或列表）
    media = parse_result.media
    media_refs = media if isinstance(media, list) else [media]

    if not media_refs:
        return False

    # 统计 GIF 数量
    gif_count = len([i for i in media_refs if isinstance(i, AniRef)])
    total_count = len(media_refs)

    # 关键逻辑：必须是纯 GIF 且数量超过阈值
    is_all_gif = (gif_count == total_count and total_count > 0)
    exceeds_threshold = gif_count > GIF_ONLY_SKIP_DOWNLOAD_COUNT_THRESHOLD

    if is_all_gif and exceeds_threshold:
        logger.info(f"🎬 检测到 {gif_count} 个纯GIF内容，超过阈值({GIF_ONLY_SKIP_DOWNLOAD_COUNT_THRESHOLD})，跳过上传")
        return True

    return False


def build_gif_download_buttons(parse_result) -> InlineKeyboardMarkup | None:
    """
    生成 GIF 下载按钮

    参考 parse_hub_bot 实现：
    - plugins/parse.py L689-696: _build_gif_button()

    Args:
        parse_result: 解析结果（包含 media 字段）

    Returns:
        InlineKeyboardMarkup 或 None
    """
    if not parse_result or not hasattr(parse_result, 'media'):
        return None

    # 提取媒体引用
    media = parse_result.media
    media_refs = media if isinstance(media, list) else [media]

    # 筛选出 GIF 并构建按钮
    buttons = []
    for i, media_ref in enumerate(media_refs):
        if isinstance(media_ref, AniRef) and hasattr(media_ref, 'url'):
            # 按钮显示序号，点击跳转原始URL
            buttons.append(InlineKeyboardButton(f"{i + 1}", url=media_ref.url))

    if not buttons:
        return None

    # 每行5个按钮（参考 parse_hub_bot: n=5）
    keyboard = [list(batch) for batch in batched(buttons, 5)]

    return InlineKeyboardMarkup(keyboard)


def get_gif_skip_message(gif_count: int) -> str:
    """
    生成跳过上传的提示消息

    Args:
        gif_count: GIF 数量

    Returns:
        提示文本（Markdown格式）
    """
    return f"⚠️ 检测到 {gif_count} 个 GIF，数量过多已跳过上传\n💾 请点击下方按钮下载原始文件"
