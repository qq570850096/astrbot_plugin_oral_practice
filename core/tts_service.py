"""
TTS Service — Text-to-Speech using MiMo-V2-TTS
语音合成服务 — 使用 MiMo-V2-TTS 模型

Uses OpenAI-compatible chat completions API.
Emotion tags (e.g. [温柔], [开心]) are prepended to the text.
The response contains base64-encoded WAV audio in
``choices[0].message.audio.data``.
"""

from __future__ import annotations

import asyncio
import base64
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import aiohttp
from astrbot.api import logger


@dataclass
class SynthesisResult:
    """Text-to-speech synthesis result / 语音合成结果"""

    audio_data: bytes   # Raw WAV audio bytes / 原始 WAV 音频字节
    audio_path: str     # Saved file path / 保存的文件路径
    duration: float     # Duration in seconds / 时长（秒）


class TTSService:
    """
    Text-to-Speech service backed by MiMo-V2-TTS.

    The model exposes an OpenAI-compatible ``/chat/completions`` endpoint.
    An emotion tag such as ``[温柔]`` is prepended to the message text,
    and the response payload contains base64-encoded audio under
    ``choices[0].message.audio.data``.
    """

    # Mapping: English emotion key → Chinese emotion tag
    # 英文情绪键 → 中文情绪标签
    EMOTION_MAP: dict[str, str] = {
        "warm": "温柔",
        "happy": "开心",
        "encouraging": "鼓励",
        "serious": "严肃",
        "neutral": "",
    }

    def __init__(
        self,
        api_key: str,
        api_base: str,
        model: str = "mimo-v2-tts",
        default_emotion: str = "温柔",
        temp_dir: Optional[str] = None,
        timeout: int = 60,
    ):
        """
        初始化 TTS 服务。

        Args:
            api_key:          API key for authentication / API 密钥
            api_base:         Base URL of the API / API 基础地址
            model:            Model name for synthesis / 模型名称
            default_emotion:  Default emotion tag (Chinese) / 默认情绪标签
            temp_dir:         Directory for saving audio files.
                              Created automatically if missing. / 临时音频目录
            timeout:          HTTP request timeout in seconds / 请求超时（秒）
        """
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = model
        self.default_emotion = default_emotion
        self.timeout = timeout

        # Resolve temp directory — fall back to ``./data/tts_audio``
        if temp_dir:
            self.temp_dir = Path(temp_dir)
        else:
            self.temp_dir = Path("data") / "tts_audio"
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    @property
    def available(self) -> bool:
        """Whether the service is configured and ready. / 服务是否可用"""
        return bool(self.api_key)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def synthesize(
        self,
        text: str,
        emotion: Optional[str] = None,
        output_path: Optional[str] = None,
    ) -> SynthesisResult:
        """
        Convert text to speech.
        将文本转换为语音。

        Args:
            text:        The text to synthesize. / 需要合成的文本
            emotion:     Emotion key (English, e.g. ``'warm'``) **or**
                         Chinese tag (e.g. ``'温柔'``).
                         Falls back to *default_emotion* if ``None``.
            output_path: Optional explicit path for the output WAV file.
                         If ``None``, a unique filename is generated in
                         *temp_dir*.

        Returns:
            A ``SynthesisResult`` with raw audio bytes, saved path, and
            duration.

        Raises:
            ValueError:   If *text* is empty or the API response is
                          malformed / missing audio data.
            RuntimeError: On network or authentication errors.
        """
        if not text or not text.strip():
            raise ValueError("[TTS] Cannot synthesize empty text.")

        # --- Resolve emotion tag ---
        emotion_tag = self._resolve_emotion(emotion)

        # --- Build message content with prepended emotion tag ---
        if emotion_tag:
            content = f"[{emotion_tag}] {text}"
        else:
            content = text

        logger.info(
            f"[TTS] Synthesizing {len(text)} chars "
            f"(emotion={emotion_tag or 'none'})"
        )

        # --- Build request payload ---
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": content,
                }
            ],
            "audio": {
                "format": "wav",
                "voice": "default_en",
            },
        }

        # --- Call API ---
        audio_bytes = await self._call_api(payload)

        # --- Save to file ---
        save_path = self._resolve_output_path(output_path)
        with open(save_path, "wb") as f:
            f.write(audio_bytes)

        logger.info(
            f"[TTS] Audio saved: {save_path} "
            f"({len(audio_bytes) / 1024:.1f} KB)"
        )

        # --- Measure duration ---
        duration = await self._get_audio_duration(str(save_path))

        return SynthesisResult(
            audio_data=audio_bytes,
            audio_path=str(save_path),
            duration=duration,
        )

    async def synthesize_feedback(self, text: str) -> SynthesisResult:
        """
        Synthesize feedback text with an encouraging tone.
        使用鼓励语气合成反馈文本。

        Convenience wrapper around ``synthesize`` that sets emotion to
        ``'encouraging'``.
        """
        return await self.synthesize(text, emotion="encouraging")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _call_api(self, payload: dict) -> bytes:
        """
        Send the TTS request and return decoded WAV audio bytes.
        发送 TTS 请求并返回解码后的 WAV 音频字节。
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
                            "[TTS] Authentication failed — check your API key."
                        )
                    if resp.status != 200:
                        body = await resp.text()
                        raise RuntimeError(
                            f"[TTS] API returned HTTP {resp.status}: "
                            f"{body[:500]}"
                        )
                    data = await resp.json()

        except aiohttp.ClientError as exc:
            raise RuntimeError(
                f"[TTS] Network error communicating with API: {exc}"
            ) from exc
        except asyncio.TimeoutError as exc:
            raise RuntimeError(
                f"[TTS] Request timed out after {self.timeout}s"
            ) from exc

        # --- Extract base64 audio from response ---
        try:
            audio_b64: str = data["choices"][0]["message"]["audio"]["data"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError(
                f"[TTS] Malformed API response — "
                f"could not extract audio data: {data}"
            ) from exc

        if not audio_b64:
            raise ValueError("[TTS] API returned empty audio data.")

        # --- Decode base64 ---
        try:
            audio_bytes = base64.b64decode(audio_b64)
        except Exception as exc:
            raise ValueError(
                f"[TTS] Failed to decode base64 audio data: {exc}"
            ) from exc

        if len(audio_bytes) < 44:
            # A valid WAV header alone is 44 bytes — anything shorter
            # is almost certainly corrupted / empty.
            raise ValueError(
                f"[TTS] Decoded audio is too small ({len(audio_bytes)} bytes), "
                "possibly corrupted."
            )

        return audio_bytes

    def _resolve_emotion(self, emotion: Optional[str]) -> str:
        """
        Resolve an emotion value to a Chinese tag string.
        将情绪值解析为中文标签字符串。

        Accepts English keys from ``EMOTION_MAP`` (e.g. ``'warm'``) or
        direct Chinese tags (e.g. ``'温柔'``).  Falls back to
        *default_emotion* when *emotion* is ``None``.
        """
        if emotion is None:
            return self.default_emotion

        # Try English key first
        if emotion in self.EMOTION_MAP:
            return self.EMOTION_MAP[emotion]

        # Accept direct Chinese tag as-is
        return emotion

    def _resolve_output_path(self, output_path: Optional[str]) -> Path:
        """
        Return a ``Path`` for the output WAV file.
        返回输出 WAV 文件的路径。

        If *output_path* is not supplied, generates a unique filename
        inside *temp_dir* using a combination of timestamp and UUID.
        """
        if output_path:
            p = Path(output_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            return p

        # Generate unique filename: tts_<timestamp>_<short-uuid>.wav
        ts = int(time.time() * 1000)
        short_id = uuid.uuid4().hex[:8]
        filename = f"tts_{ts}_{short_id}.wav"
        return self.temp_dir / filename

    async def _get_audio_duration(self, audio_path: str) -> float:
        """
        Return audio duration in seconds using *pydub*.
        使用 pydub 获取音频时长。

        Runs the blocking pydub call in a thread executor.
        """
        loop = asyncio.get_running_loop()
        try:
            duration = await loop.run_in_executor(
                None, self._load_duration_sync, audio_path
            )
            return duration
        except Exception as exc:
            logger.warning(f"[TTS] Could not determine audio duration: {exc}")
            return 0.0

    @staticmethod
    def _load_duration_sync(audio_path: str) -> float:
        """Synchronous helper — loads audio with pydub to read duration."""
        from pydub import AudioSegment  # lazy import to reduce startup cost

        segment = AudioSegment.from_file(audio_path)
        return len(segment) / 1000.0  # pydub reports milliseconds
