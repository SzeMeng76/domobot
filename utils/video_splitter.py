"""
视频分割工具
用于将大视频分割为多个小片段，解决Telegram文件大小限制
需要安装 FFmpeg
"""

import logging
import asyncio
import subprocess
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


class VideoSplitter:
    """视频分割器"""

    def __init__(self, ffmpeg_path: str = "ffmpeg"):
        """
        初始化视频分割器

        Args:
            ffmpeg_path: FFmpeg可执行文件路径
        """
        self.ffmpeg_path = ffmpeg_path

    def check_ffmpeg(self) -> bool:
        """检查FFmpeg是否可用"""
        try:
            result = subprocess.run(
                [self.ffmpeg_path, "-version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except Exception as e:
            logger.error(f"FFmpeg检查失败: {e}")
            return False

    async def get_video_duration(self, video_path: Path) -> Optional[float]:
        """获取视频时长（秒）"""
        try:
            cmd = [
                self.ffmpeg_path,
                "-i", str(video_path),
                "-f", "null",
                "-"
            ]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            _, stderr = await proc.communicate()
            stderr_text = stderr.decode('utf-8', errors='ignore')

            # 从输出中提取时长
            import re
            match = re.search(r"Duration: (\d{2}):(\d{2}):(\d{2}.\d{2})", stderr_text)
            if match:
                hours, minutes, seconds = match.groups()
                duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
                return duration

            return None

        except Exception as e:
            logger.error(f"获取视频时长失败: {e}")
            return None

    async def split_video(
        self,
        input_path: Path,
        output_dir: Path,
        max_size_mb: int = 45
    ) -> List[Path]:
        """
        分割视频文件

        Args:
            input_path: 输入视频路径
            output_dir: 输出目录
            max_size_mb: 每段最大大小（MB）

        Returns:
            分割后的文件路径列表
        """
        if not self.check_ffmpeg():
            logger.error("FFmpeg不可用，无法分割视频")
            return []

        try:
            # 创建输出目录
            output_dir.mkdir(parents=True, exist_ok=True)

            # 获取视频信息
            file_size_mb = input_path.stat().st_size / (1024 * 1024)
            duration = await self.get_video_duration(input_path)

            if not duration:
                logger.error("无法获取视频时长")
                return []

            # 计算需要分割的段数
            num_parts = int((file_size_mb / max_size_mb) + 0.5) + 1
            segment_duration = duration / num_parts

            logger.info(f"视频大小: {file_size_mb:.1f}MB, 时长: {duration:.1f}s, 将分割为 {num_parts} 段")

            # 分割视频
            output_pattern = output_dir / f"{input_path.stem}_part%03d{input_path.suffix}"
            cmd = [
                self.ffmpeg_path,
                "-i", str(input_path),
                "-c", "copy",  # 不重新编码，直接复制流
                "-f", "segment",
                "-segment_time", str(segment_duration),
                "-reset_timestamps", "1",
                str(output_pattern)
            ]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            _, stderr = await proc.wait()

            if proc.returncode != 0:
                error_msg = stderr.decode('utf-8', errors='ignore')
                logger.error(f"视频分割失败: {error_msg}")
                return []

            # 获取分割后的文件列表
            output_files = sorted(output_dir.glob(f"{input_path.stem}_part*{input_path.suffix}"))

            logger.info(f"✅ 视频分割完成，共 {len(output_files)} 个片段")
            return output_files

        except Exception as e:
            logger.error(f"视频分割失败: {e}")
            return []


async def split_video_if_needed(
    video_path: Path,
    max_size_mb: int = 45,
    ffmpeg_path: str = "ffmpeg"
) -> List[Path]:
    """
    便捷函数：如果视频超过大小限制，则分割

    Args:
        video_path: 视频路径
        max_size_mb: 最大大小（MB）
        ffmpeg_path: FFmpeg路径

    Returns:
        文件路径列表（如果不需要分割，返回原文件；否则返回分割后的文件）
    """
    file_size_mb = video_path.stat().st_size / (1024 * 1024)

    # 不需要分割
    if file_size_mb <= max_size_mb:
        return [video_path]

    # 需要分割
    output_dir = video_path.parent / f"{video_path.stem}_split"
    splitter = VideoSplitter(ffmpeg_path)
    parts = await splitter.split_video(video_path, output_dir, max_size_mb)

    if not parts:
        # 分割失败，返回原文件
        logger.warning("视频分割失败，将发送原文件")
        return [video_path]

    return parts
