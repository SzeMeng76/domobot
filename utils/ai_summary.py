"""
AI Summary Module
Standalone implementation ported from ParseHub 1.5.14's DownloadResult.summary()
Uses OpenAI-compatible API for LLM summarization and Whisper for audio transcription
"""

import asyncio
import base64
import io
import logging
import math
import os
from pathlib import Path
from typing import Optional

from openai import AsyncOpenAI
from PIL import Image

logger = logging.getLogger(__name__)

DEFAULT_PROMPT = """你是一个活泼友好的社交媒体助手，帮助用户快速了解视频/文章内容。

请用生动有趣的方式总结这个内容，要求：

**格式要求：**
- 使用 HTML 格式（<b>粗体</b>、<i>斜体</i>、<code>代码</code>、<blockquote>引用</blockquote>等）
- 中英文之间需要空格
- 技术关键词使用 <code>行内代码</code>
- 重要引用使用 <blockquote>引用内容</blockquote>
- 适当使用 emoji 让内容更友好（但不要过度）
- **禁止使用 Markdown 格式**（不要用 **、``、>、# 等符号）

**内容结构：**
1. <b>核心内容</b> - 用 1-2 句话说明主题（用粗体）
2. <b>关键要点</b> - 3-5 个要点，使用列表格式（每行用 - 开头）
3. <b>亮点/看点</b> - 如果有趣的片段、金句、或值得关注的细节，用引用格式突出显示

**语气风格：**
- 保持轻松友好，像朋友聊天一样
- 对有趣的内容可以加点俏皮评论
- 重要信息要清晰准确，不夸大不遗漏
- **必须使用中文回复**（如果内容是英文，请翻译成中文后再总结）

**注意事项：**
- 如果是视频，关注视觉内容和对话
- 如果是文章，关注论点和论据
- 如果是社交媒体帖子，关注情绪和互动
- 总长度控制在 200-500 字左右

现在请总结以下内容："""


class AISummarizer:
    """AI content summarizer using OpenAI-compatible API"""

    def __init__(
        self,
        api_key: str,
        base_url: str = None,
        model: str = "gpt-5-mini",
        prompt: str = None,
        transcription_provider: str = "openai",
        transcription_api_key: str = None,
        transcription_base_url: str = None,
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.prompt = prompt or DEFAULT_PROMPT
        self.transcription_provider = transcription_provider
        self.transcription_api_key = transcription_api_key
        self.transcription_base_url = transcription_base_url

    async def summarize(self, parse_result, download_result=None) -> Optional[str]:
        """
        Generate AI summary for parsed content.

        Args:
            parse_result: ParseResult from parsehub
            download_result: DownloadResult with downloaded media files (optional)

        Returns:
            Summary text or None on failure
        """
        try:
            # Collect media files from download_result
            media_list = []
            if download_result and download_result.media:
                media = download_result.media
                media_list = media if isinstance(media, list) else [media]

            # Process videos (transcription) and images (base64)
            subtitles = ""
            image_tasks = []

            for item in media_list:
                if _is_video(item):
                    subtitles = await self._video_to_subtitles(item.path)
                    if not subtitles:
                        # Fallback: extract screenshot from video
                        try:
                            img_path = await asyncio.to_thread(_video_to_screenshot, item.path)
                            image_tasks.append(_image_to_base64(img_path))
                        except Exception as e:
                            logger.warning(f"Video screenshot extraction failed: {e}")
                elif _is_image(item):
                    image_tasks.append(_image_to_base64(item.path))

            # Gather image base64 results
            image_results = []
            if image_tasks:
                results = await asyncio.gather(*image_tasks, return_exceptions=True)
                image_results = [r for r in results if isinstance(r, str)]

            # Build message content
            text_parts = []
            if parse_result.title:
                text_parts.append(f"标题: {parse_result.title}")
            if parse_result.content:
                text_parts.append(f"正文: {parse_result.content}")
            if subtitles:
                text_parts.append(f"视频字幕: {subtitles}")

            if not text_parts and not image_results:
                logger.warning("No content to summarize")
                return None

            content = [{"type": "text", "text": "\n".join(text_parts)}]
            for img_b64 in image_results:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"},
                })

            messages = [
                {"role": "system", "content": self.prompt},
                {"role": "user", "content": content},
                {"role": "user", "content": "请对以上内容进行总结！"},
            ]

            # Call LLM
            client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
            response = await client.chat.completions.create(
                model=self.model,
                messages=messages,
            )
            return response.choices[0].message.content

        except Exception as e:
            logger.error(f"AI summary failed: {e}", exc_info=True)
            return None

    async def _video_to_subtitles(self, video_path: str) -> str:
        """Extract subtitles from video via Whisper transcription"""
        if not self.transcription_api_key or not self.transcription_base_url:
            logger.warning("Transcription not configured, skipping subtitle extraction")
            return ""

        try:
            client = AsyncOpenAI(
                api_key=self.transcription_api_key,
                base_url=self.transcription_base_url,
            )

            # Split audio if file is too large (>20MB)
            file_size = os.path.getsize(video_path)
            if file_size > 20 * 1024 * 1024:
                return await self._transcribe_large_file(client, video_path)

            with open(video_path, "rb") as audio_file:
                result = await client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    response_format="verbose_json",
                )

            if not result.segments or len(result.segments) <= 5:
                return ""

            return " ".join(seg.text for seg in result.segments)

        except Exception as e:
            logger.warning(f"Video transcription failed: {e}")
            return ""

    async def _transcribe_large_file(self, client: AsyncOpenAI, file_path: str) -> str:
        """Split and transcribe large audio files"""
        import tempfile

        try:
            from pydub import AudioSegment
        except ImportError:
            logger.warning("pydub not installed, cannot split large audio files")
            return ""

        try:
            audio = await asyncio.to_thread(AudioSegment.from_file, file_path)
            file_size = os.path.getsize(file_path)
            chunk_size = 20 * 1024 * 1024
            duration_ms = len(audio)
            chunk_duration_ms = math.floor(duration_ms * (chunk_size / file_size))

            with tempfile.TemporaryDirectory() as temp_dir:
                chunks = []
                for i, chunk_start in enumerate(range(0, duration_ms, chunk_duration_ms)):
                    chunk_end = chunk_start + chunk_duration_ms
                    # Overlap 1 second to avoid boundary issues
                    actual_start = chunk_start if not i else chunk_start - 1000
                    chunk = audio[actual_start:chunk_end]
                    chunk_path = os.path.join(temp_dir, f"chunk_{i}.mp3")
                    await asyncio.to_thread(chunk.export, chunk_path, "mp3")
                    chunks.append(chunk_path)

                # Transcribe all chunks
                all_text = []
                for chunk_path in chunks:
                    try:
                        with open(chunk_path, "rb") as f:
                            result = await client.audio.transcriptions.create(
                                model="whisper-1",
                                file=f,
                                response_format="verbose_json",
                            )
                            if result.segments:
                                all_text.extend(seg.text for seg in result.segments)
                    except Exception as e:
                        logger.warning(f"Chunk transcription failed: {e}")

                if len(all_text) <= 5:
                    return ""
                return " ".join(all_text)

        except Exception as e:
            logger.error(f"Large file transcription failed: {e}")
            return ""


def _is_video(media) -> bool:
    """Check if media is a video type"""
    type_name = type(media).__name__
    return type_name in ("Video", "VideoRef", "VideoFile")


def _is_image(media) -> bool:
    """Check if media is an image type"""
    type_name = type(media).__name__
    return type_name in ("Image", "ImageRef", "ImageFile", "LivePhoto")


def _video_to_screenshot(video_path: str) -> str:
    """Extract first frame from video as screenshot"""
    import cv2

    output_path = f"{video_path}.png"
    cap = cv2.VideoCapture(str(video_path))
    ret, frame = cap.read()
    cap.release()
    if not ret:
        raise RuntimeError(f"Failed to read video frame: {video_path}")
    cv2.imwrite(output_path, frame)
    return output_path


async def _image_to_base64(image_path: str) -> str:
    """Convert image file to base64 string"""
    path = Path(image_path)
    ext = path.suffix.lower()

    if ext in (".png", ".jpeg", ".jpg", ".gif", ".webp"):
        import aiofiles
        async with aiofiles.open(str(path), "rb") as f:
            content = await f.read()
        return base64.b64encode(content).decode("utf-8")

    # Convert unsupported formats (HEIC, etc.) to WEBP
    def _convert():
        with Image.open(str(path)) as img:
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            buf = io.BytesIO()
            img.save(buf, format="WEBP")
            return buf.getvalue()

    data = await asyncio.to_thread(_convert)
    return base64.b64encode(data).decode("utf-8")
