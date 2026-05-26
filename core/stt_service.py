"""
STT Service — Speech-to-Text using MiMo-V2-Omni
语音识别服务 — 使用 MiMo-V2-Omni 模型

Uses OpenAI-compatible chat completions API with multimodal audio input.
Audio is sent as base64-encoded data inside a multimodal message.
"""

from __future__ import annotations

import asyncio
import base64
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import aiohttp
from astrbot.api import logger

# Supported audio formats / 支持的音频格式
SUPPORTED_AUDIO_FORMATS = {"wav", "mp3", "ogg", "flac", "m4a", "webm", "aac", "silk", "amr"}


@dataclass
class TranscribeResult:
    """Speech-to-text transcription result / 语音转文字结果"""

    text: str           # Transcribed text / 转录文本
    language: str       # Detected language code / 检测到的语言
    confidence: float   # Confidence score (0.0–1.0) / 置信度
    duration: float     # Audio duration in seconds / 音频时长（秒）


class STTService:
    """
    Speech-to-Text service backed by MiMo-V2-Omni.

    The model exposes an OpenAI-compatible ``/chat/completions`` endpoint.
    Audio is sent as base64-encoded data inside a multimodal message using
    the ``input_audio`` content type.
    """

    # Prompt instructs the model to produce a clean transcription only
    _TRANSCRIBE_PROMPT = (
        "Please transcribe this audio accurately. "
        "Return only the transcribed text, nothing else."
    )

    def __init__(
        self,
        api_key: str,
        api_base: str,
        model: str = "mimo-v2-omni",
        timeout: int = 60,
    ):
        """
        初始化 STT 服务。

        Args:
            api_key:  API key for authentication / API 密钥
            api_base: Base URL of the API (e.g. ``http://host:port/v1``) / API 基础地址
            model:    Model name for transcription / 模型名称
            timeout:  HTTP request timeout in seconds / 请求超时（秒）
        """
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = model
        self.timeout = timeout

    @property
    def available(self) -> bool:
        """Whether the service is configured and ready. / 服务是否可用"""
        return bool(self.api_key)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def transcribe(self, audio_path: str) -> TranscribeResult:
        """
        Transcribe an audio file to text.
        将音频文件转录为文本。

        Args:
            audio_path: Absolute or relative path to the audio file.

        Returns:
            A ``TranscribeResult`` with transcribed text, detected language,
            confidence score, and audio duration.

        Raises:
            FileNotFoundError: If *audio_path* does not exist.
            ValueError:        If the audio format is unsupported or
                               the API response is malformed / empty.
            RuntimeError:      On network or authentication errors.
        """
        # --- 1. Validate file existence ---
        if not os.path.isfile(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        path = Path(audio_path)
        ext = path.suffix.lstrip(".").lower()
        if ext not in SUPPORTED_AUDIO_FORMATS:
            raise ValueError(
                f"Unsupported audio format '.{ext}'. "
                f"Supported: {', '.join(sorted(SUPPORTED_AUDIO_FORMATS))}"
            )

        # --- 2. Read file & base64 encode ---
        with open(audio_path, "rb") as f:
            audio_bytes = f.read()
        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

        logger.info(
            f"[STT] Encoding audio: {path.name} "
            f"({len(audio_bytes) / 1024:.1f} KB, format={ext})"
        )

        # --- 3. Measure audio duration via pydub (non-blocking) ---
        duration = await self._get_audio_duration(audio_path)

        # --- 4. Build request payload (multimodal format) ---
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": audio_b64,
                                "format": ext,
                            },
                        },
                        {
                            "type": "text",
                            "text": self._TRANSCRIBE_PROMPT,
                        },
                    ],
                }
            ],
        }

        # --- 5. Call API ---
        text = await self._call_api(payload)

        # --- 6. Assemble result ---
        result = TranscribeResult(
            text=text.strip(),
            language=self._guess_language(text),
            confidence=1.0,  # model does not surface confidence; default 1.0
            duration=duration,
        )

        logger.info(
            f"[STT] Transcription OK: lang={result.language}, "
            f"duration={result.duration:.1f}s, "
            f"text={result.text[:80]}{'...' if len(result.text) > 80 else ''}"
        )
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _call_api(self, payload: dict) -> str:
        """
        Send request to ``/chat/completions`` and return the assistant
        message content string.
        发送请求到 API 并返回助手消息文本。
        """
        url = f"{self.api_base}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        try:
            client_timeout = aiohttp.ClientTimeout(total=self.timeout)
            async with aiohttp.ClientSession(timeout=client_timeout) as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status == 401:
                        raise RuntimeError(
                            "[STT] Authentication failed — check your API key."
                        )
                    if resp.status != 200:
                        body = await resp.text()
                        raise RuntimeError(
                            f"[STT] API returned HTTP {resp.status}: "
                            f"{body[:500]}"
                        )
                    data = await resp.json()

        except aiohttp.ClientError as exc:
            raise RuntimeError(
                f"[STT] Network error communicating with API: {exc}"
            ) from exc
        except asyncio.TimeoutError as exc:
            raise RuntimeError(
                f"[STT] Request timed out after {self.timeout}s"
            ) from exc

        # --- Parse response ---
        try:
            content: str = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError(
                f"[STT] Malformed API response — "
                f"could not extract content: {data}"
            ) from exc

        if not content or not content.strip():
            raise ValueError("[STT] API returned an empty transcription.")

        return content

    async def _get_audio_duration(self, audio_path: str) -> float:
        """
        Return audio duration in seconds using *pydub*.
        使用 pydub 获取音频时长。

        Runs the blocking pydub call in a thread executor so the event
        loop is not blocked.
        """
        loop = asyncio.get_running_loop()
        try:
            duration = await loop.run_in_executor(
                None, self._load_duration_sync, audio_path
            )
            return duration
        except Exception as exc:
            logger.warning(f"[STT] Could not determine audio duration: {exc}")
            return 0.0

    @staticmethod
    def _load_duration_sync(audio_path: str) -> float:
        """Synchronous helper — loads audio with pydub to read duration."""
        from pydub import AudioSegment  # lazy import to reduce startup cost

        segment = AudioSegment.from_file(audio_path)
        return len(segment) / 1000.0  # pydub reports milliseconds

    @staticmethod
    def _guess_language(text: str) -> str:
        """
        Simple heuristic to guess the dominant language in *text*.
        简单的语言检测启发式方法。

        Returns ``'zh'`` if more than 30 % of characters are CJK,
        otherwise ``'en'``.
        """
        if not text:
            return "unknown"

        cjk_count = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
        ratio = cjk_count / max(len(text), 1)
        return "zh" if ratio > 0.3 else "en"
