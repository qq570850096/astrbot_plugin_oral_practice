"""
Azure Speech-to-Text service.

Used by conversation/scenario/drill modes so the plugin does not depend on
AstrBot global STT or MiMo connectivity.
"""

from __future__ import annotations

import asyncio
import os

from astrbot.api import logger

from .stt_service import TranscribeResult

try:
    import azure.cognitiveservices.speech as speechsdk

    _AZURE_SDK_AVAILABLE = True
except ImportError:
    speechsdk = None
    _AZURE_SDK_AVAILABLE = False


class AzureSTTService:
    """Speech-to-text adapter backed by Azure AI Speech."""

    def __init__(
        self,
        subscription_key: str,
        region: str,
        language: str = "en-US",
    ):
        if not _AZURE_SDK_AVAILABLE:
            raise ImportError(
                "azure-cognitiveservices-speech 未安装。"
                "请运行: pip install azure-cognitiveservices-speech"
            )
        if not subscription_key or not subscription_key.strip():
            raise ValueError("Azure Speech key must not be empty")
        if not region or not region.strip():
            raise ValueError("Azure Speech region must not be empty")

        self.subscription_key = subscription_key.strip()
        self.region = region.strip()
        self.language = (language or "en-US").strip()

    @property
    def available(self) -> bool:
        return bool(self.subscription_key and self.region)

    async def transcribe(self, audio_path: str) -> TranscribeResult:
        if not os.path.isfile(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        return await asyncio.to_thread(self._transcribe_sync, audio_path)

    def _transcribe_sync(self, audio_path: str) -> TranscribeResult:
        speech_config = speechsdk.SpeechConfig(
            subscription=self.subscription_key,
            region=self.region,
        )
        speech_config.speech_recognition_language = self.language

        audio_config = speechsdk.audio.AudioConfig(filename=audio_path)
        recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            audio_config=audio_config,
        )

        logger.info(
            "[AzureSTT] Starting recognition region=%s language=%s audio=%s",
            self.region,
            self.language,
            audio_path,
        )
        result = recognizer.recognize_once_async().get()

        if result.reason == speechsdk.ResultReason.Canceled:
            cancellation = result.cancellation_details
            raise RuntimeError(
                "Azure STT canceled: "
                f"reason={cancellation.reason}, "
                f"code={cancellation.error_code}, "
                f"details={cancellation.error_details}"
            )

        if result.reason == speechsdk.ResultReason.NoMatch:
            raise ValueError("Azure STT did not recognize speech.")

        if result.reason != speechsdk.ResultReason.RecognizedSpeech:
            raise RuntimeError(f"Unexpected Azure STT result reason: {result.reason}")

        text = (result.text or "").strip()
        if not text:
            raise ValueError("Azure STT returned empty text.")

        logger.info("[AzureSTT] Recognition OK: %s", text[:100])
        return TranscribeResult(
            text=text,
            language=self.language,
            confidence=1.0,
            duration=0.0,
        )


class UnavailableSTTService:
    """Explicit placeholder used when the selected STT backend is not configured."""

    def __init__(self, reason: str):
        self.reason = reason

    @property
    def available(self) -> bool:
        return False

    async def transcribe(self, audio_path: str) -> TranscribeResult:
        raise RuntimeError(self.reason)
