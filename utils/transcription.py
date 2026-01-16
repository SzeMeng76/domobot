"""
视频/音频转录工具
支持 OpenAI Whisper、Azure Speech、FastWhisper
"""

import logging
import asyncio
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class TranscriptionService:
    """转录服务基类"""

    async def transcribe(self, media_path: Path) -> Optional[str]:
        """转录媒体文件"""
        raise NotImplementedError


class OpenAITranscription(TranscriptionService):
    """OpenAI Whisper 转录"""

    def __init__(self, api_key: str, base_url: Optional[str] = None, model: str = "whisper-1"):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

    async def transcribe(self, media_path: Path) -> Optional[str]:
        """使用 OpenAI Whisper 转录"""
        try:
            import openai

            client = openai.AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url or None
            )

            # 如果是视频，先提取音频
            audio_path = await self._extract_audio_if_video(media_path)

            with open(audio_path, 'rb') as audio_file:
                response = await client.audio.transcriptions.create(
                    model=self.model,
                    file=audio_file,
                    language="zh",  # 中文，可以配置
                    response_format="text"
                )

            # 清理临时音频
            if audio_path != media_path:
                audio_path.unlink(missing_ok=True)

            logger.info(f"✅ OpenAI转录成功")
            return response

        except Exception as e:
            logger.error(f"OpenAI转录失败: {e}")
            return None

    async def _extract_audio_if_video(self, media_path: Path) -> Path:
        """如果是视频，提取音频"""
        # 视频格式
        video_exts = ['.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv', '.webm']

        if media_path.suffix.lower() not in video_exts:
            # 已经是音频文件
            return media_path

        # 提取音频
        try:
            audio_path = media_path.parent / f"{media_path.stem}_audio.mp3"

            cmd = [
                "ffmpeg",
                "-i", str(media_path),
                "-vn",  # 不要视频
                "-acodec", "libmp3lame",
                "-ar", "16000",  # 采样率 16kHz（Whisper推荐）
                "-ac", "1",  # 单声道
                "-q:a", "4",  # 音质
                "-y",  # 覆盖输出
                str(audio_path)
            ]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            _, stderr = await proc.wait()

            if proc.returncode == 0 and audio_path.exists():
                logger.info(f"✅ 音频提取成功: {audio_path}")
                return audio_path
            else:
                error = stderr.decode('utf-8', errors='ignore')
                logger.error(f"音频提取失败: {error}")
                return media_path

        except Exception as e:
            logger.error(f"音频提取失败: {e}")
            return media_path


class AzureTranscription(TranscriptionService):
    """Azure Speech 转录"""

    def __init__(self, api_key: str, region: str):
        self.api_key = api_key
        self.region = region

    async def transcribe(self, media_path: Path) -> Optional[str]:
        """使用 Azure Speech 转录"""
        try:
            import azure.cognitiveservices.speech as speechsdk

            # 配置
            speech_config = speechsdk.SpeechConfig(
                subscription=self.api_key,
                region=self.region
            )
            speech_config.speech_recognition_language = "zh-CN"

            # 如果是视频，先提取音频
            audio_path = await OpenAITranscription(None)._extract_audio_if_video(media_path)

            # 音频配置
            audio_config = speechsdk.AudioConfig(filename=str(audio_path))

            # 创建识别器
            speech_recognizer = speechsdk.SpeechRecognizer(
                speech_config=speech_config,
                audio_config=audio_config
            )

            # 识别
            result = speech_recognizer.recognize_once()

            # 清理临时音频
            if audio_path != media_path:
                audio_path.unlink(missing_ok=True)

            if result.reason == speechsdk.ResultReason.RecognizedSpeech:
                logger.info(f"✅ Azure转录成功")
                return result.text
            else:
                logger.error(f"Azure转录失败: {result.reason}")
                return None

        except Exception as e:
            logger.error(f"Azure转录失败: {e}")
            return None


class FastWhisperTranscription(TranscriptionService):
    """FastWhisper 本地转录"""

    def __init__(self, model_size: str = "base"):
        """
        Args:
            model_size: 模型大小 (tiny, base, small, medium, large)
        """
        self.model_size = model_size
        self._model = None

    async def transcribe(self, media_path: Path) -> Optional[str]:
        """使用 FastWhisper 本地转录"""
        try:
            from faster_whisper import WhisperModel

            # 懒加载模型
            if self._model is None:
                logger.info(f"加载 FastWhisper 模型: {self.model_size}")
                self._model = WhisperModel(self.model_size, device="cpu", compute_type="int8")

            # 如果是视频，先提取音频
            audio_path = await OpenAITranscription(None)._extract_audio_if_video(media_path)

            # 转录
            segments, info = self._model.transcribe(
                str(audio_path),
                language="zh",
                beam_size=5
            )

            # 合并所有片段
            text = " ".join([segment.text for segment in segments])

            # 清理临时音频
            if audio_path != media_path:
                audio_path.unlink(missing_ok=True)

            logger.info(f"✅ FastWhisper转录成功")
            return text

        except Exception as e:
            logger.error(f"FastWhisper转录失败: {e}")
            return None


class TranscriptionManager:
    """转录管理器"""

    def __init__(self, provider: str, **kwargs):
        """
        Args:
            provider: 服务提供商 (openai, azure, fast_whisper)
            **kwargs: 提供商特定的参数
        """
        self.provider = provider.lower()

        if self.provider == "openai":
            self.service = OpenAITranscription(
                api_key=kwargs.get("api_key"),
                base_url=kwargs.get("base_url"),
                model=kwargs.get("model", "whisper-1")
            )
        elif self.provider == "azure":
            self.service = AzureTranscription(
                api_key=kwargs.get("api_key"),
                region=kwargs.get("region", "eastus")
            )
        elif self.provider == "fast_whisper":
            self.service = FastWhisperTranscription(
                model_size=kwargs.get("model_size", "base")
            )
        else:
            raise ValueError(f"不支持的转录服务: {provider}")

    async def transcribe(self, media_path: Path) -> Optional[str]:
        """转录媒体文件"""
        return await self.service.transcribe(media_path)


async def transcribe_media(
    media_path: Path,
    provider: str = "openai",
    **kwargs
) -> Optional[str]:
    """
    便捷函数：转录媒体文件

    Args:
        media_path: 媒体文件路径
        provider: 服务提供商 (openai, azure, fast_whisper)
        **kwargs: 提供商特定的参数

    Returns:
        转录文本，失败返回None
    """
    manager = TranscriptionManager(provider, **kwargs)
    return await manager.transcribe(media_path)
