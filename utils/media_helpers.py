"""
媒体信息处理辅助函数
提供统一的媒体信息获取接口
"""

import logging
from typing import Tuple, Optional, Any

logger = logging.getLogger(__name__)


def resolve_media_info(
    media_ref: Any,
    file_path: Optional[str] = None
) -> Tuple[int, int, int]:
    """
    统一获取媒体的宽、高、时长信息

    优先使用 MediaRef 中的信息，如果信息不完整且提供了本地文件路径，
    则尝试从文件中读取。

    Args:
        media_ref: ParseHub 的 MediaRef 对象（VideoRef, ImageRef 等）
        file_path: 本地文件路径（可选，如果已下载）

    Returns:
        (width, height, duration) 元组
        - width: 宽度（像素）
        - height: 高度（像素）
        - duration: 时长（秒，仅视频有效）
    """
    # 优先使用 MediaRef 中的信息
    width = getattr(media_ref, 'width', 0) or 0
    height = getattr(media_ref, 'height', 0) or 0
    duration = getattr(media_ref, 'duration', 0) or 0

    # 如果有本地文件且信息不完整，尝试从文件读取
    if file_path and (not width or not height):
        try:
            from parsehub.utils.media_info import MediaInfoReader
            info = MediaInfoReader.read(file_path)
            width = width or info.width
            height = height or info.height
            duration = duration or info.duration
            logger.debug(f"从文件读取媒体信息: {file_path} -> {width}x{height}, {duration}s")
        except Exception as e:
            logger.debug(f"无法从文件读取媒体信息: {e}")

    return width, height, duration


def get_media_dimensions(media_ref: Any) -> Tuple[Optional[int], Optional[int]]:
    """
    获取媒体的宽高尺寸

    Args:
        media_ref: ParseHub 的 MediaRef 对象

    Returns:
        (width, height) 元组，如果没有则返回 (None, None)
    """
    width = getattr(media_ref, 'width', None)
    height = getattr(media_ref, 'height', None)
    return width, height


def get_video_duration(media_ref: Any) -> int:
    """
    获取视频时长

    Args:
        media_ref: ParseHub 的 VideoRef 对象

    Returns:
        时长（秒），如果没有则返回 0
    """
    return getattr(media_ref, 'duration', 0) or 0


def format_duration(seconds: int) -> str:
    """
    格式化时长为可读字符串

    Args:
        seconds: 秒数

    Returns:
        格式化的时长字符串，如 "1:23" 或 "1:23:45"
    """
    if seconds <= 0:
        return "0:00"

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes}:{secs:02d}"


def format_file_size(bytes_size: int) -> str:
    """
    格式化文件大小为可读字符串

    Args:
        bytes_size: 字节数

    Returns:
        格式化的文件大小字符串，如 "1.5 MB"
    """
    if bytes_size < 1024:
        return f"{bytes_size} B"
    elif bytes_size < 1024 * 1024:
        return f"{bytes_size / 1024:.1f} KB"
    elif bytes_size < 1024 * 1024 * 1024:
        return f"{bytes_size / (1024 * 1024):.1f} MB"
    else:
        return f"{bytes_size / (1024 * 1024 * 1024):.2f} GB"
