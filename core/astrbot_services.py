"""
Adapters for AstrBot configured STT/TTS providers.
复用 AstrBot WebUI 已配置的语音识别和语音合成提供商。
"""

from __future__ import annotations

import inspect
import os
import tempfile
import time
from pathlib import Path
from typing import Optional

from astrbot.api import logger

from .stt_service import TranscribeResult
from .tts_service import SynthesisResult


class AstrBotSTTService:
    """STT service adapter backed by AstrBot's configured STT provider."""

    def __init__(self, context=None, provider_id: str = ""):
        self.context = context
        self.provider_id = (provider_id or "").strip()
        self.umo = ""

    @property
    def available(self) -> bool:
        return self.context is not None

    async def transcribe(self, audio_path: str, umo: str = "") -> TranscribeResult:
        provider = await self._get_provider(umo)
        if not provider:
            raise RuntimeError("[STT] AstrBot STT 提供商未配置")

        try:
            text = await provider.get_text(audio_path)
        except Exception as exc:
            raise RuntimeError(f"[STT] AstrBot STT 调用失败: {exc}") from exc

        if not text or not str(text).strip():
            raise ValueError("[STT] AstrBot STT 返回了空文本")

        return TranscribeResult(
            text=str(text).strip(),
            language=self._guess_language(str(text)),
            confidence=1.0,
            duration=0.0,
        )

    async def _get_provider(self, umo: str = ""):
        if self.provider_id and hasattr(self.context, "get_provider_by_id"):
            provider = self.context.get_provider_by_id(self.provider_id)
            return await provider if inspect.isawaitable(provider) else provider

        if hasattr(self.context, "get_using_stt_provider"):
            umo = umo or self.umo
            try:
                provider = self.context.get_using_stt_provider(umo=umo or None)
                return await provider if inspect.isawaitable(provider) else provider
            except TypeError:
                provider = self.context.get_using_stt_provider(umo or None)
                return await provider if inspect.isawaitable(provider) else provider

        return None

    @staticmethod
    def _guess_language(text: str) -> str:
        if not text:
            return "unknown"
        cjk_count = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
        return "zh" if cjk_count / max(len(text), 1) > 0.3 else "en"


class AstrBotTTSService:
    """TTS service adapter backed by AstrBot's configured TTS provider."""

    def __init__(
        self,
        context=None,
        provider_id: str = "",
        temp_dir: Optional[str] = None,
    ):
        self.context = context
        self.provider_id = (provider_id or "").strip()
        self.umo = ""
        self.temp_dir = Path(temp_dir or tempfile.gettempdir())
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    @property
    def available(self) -> bool:
        return self.context is not None

    async def synthesize(
        self,
        text: str,
        emotion: Optional[str] = None,
        output_path: Optional[str] = None,
        umo: str = "",
    ) -> SynthesisResult:
        if not text or not text.strip():
            raise ValueError("[TTS] Cannot synthesize empty text.")

        provider = await self._get_provider(umo)
        if not provider:
            raise RuntimeError("[TTS] AstrBot TTS 提供商未配置")

        try:
            result = await provider.get_audio(text)
        except Exception as exc:
            raise RuntimeError(f"[TTS] AstrBot TTS 调用失败: {exc}") from exc

        audio_bytes, audio_path = self._normalize_audio_result(result, output_path)
        return SynthesisResult(
            audio_data=audio_bytes,
            audio_path=audio_path,
            duration=0.0,
        )

    async def synthesize_feedback(self, text: str) -> SynthesisResult:
        return await self.synthesize(text, emotion="encouraging")

    async def _get_provider(self, umo: str = ""):
        if self.provider_id and hasattr(self.context, "get_provider_by_id"):
            provider = self.context.get_provider_by_id(self.provider_id)
            return await provider if inspect.isawaitable(provider) else provider

        if hasattr(self.context, "get_using_tts_provider"):
            umo = umo or self.umo
            try:
                provider = self.context.get_using_tts_provider(umo=umo or None)
                return await provider if inspect.isawaitable(provider) else provider
            except TypeError:
                provider = self.context.get_using_tts_provider(umo or None)
                return await provider if inspect.isawaitable(provider) else provider

        return None

    def _normalize_audio_result(
        self, result, output_path: Optional[str]
    ) -> tuple[bytes, str]:
        if isinstance(result, bytes):
            audio_bytes = result
            audio_path = output_path or self._new_output_path()
            with open(audio_path, "wb") as file:
                file.write(audio_bytes)
            return audio_bytes, audio_path

        path_value = getattr(result, "file", None) or getattr(result, "path", None)
        if isinstance(result, str):
            path_value = result

        if path_value and os.path.isfile(path_value):
            with open(path_value, "rb") as file:
                audio_bytes = file.read()
            return audio_bytes, path_value

        raise ValueError(f"[TTS] AstrBot TTS 返回了未知音频格式: {type(result)!r}")

    def _new_output_path(self) -> str:
        return str(self.temp_dir / f"astrbot_tts_{int(time.time() * 1000)}.wav")
