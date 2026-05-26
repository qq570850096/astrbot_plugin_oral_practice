"""
Azure Text-to-Speech service.

Provides speech replies without relying on AstrBot global TTS or MiMo.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Optional

from astrbot.api import logger

from .tts_service import SynthesisResult

try:
    import azure.cognitiveservices.speech as speechsdk

    _AZURE_SDK_AVAILABLE = True
except ImportError:
    speechsdk = None
    _AZURE_SDK_AVAILABLE = False


class AzureTTSService:
    """Text-to-speech adapter backed by Azure AI Speech."""

    def __init__(
        self,
        subscription_key: str,
        region: str,
        voice_name: str = "en-US-JennyMultilingualNeural",
        temp_dir: Optional[str] = None,
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
        self.voice_name = (voice_name or "en-US-JennyMultilingualNeural").strip()
        self.temp_dir = Path(temp_dir or ".")
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    @property
    def available(self) -> bool:
        return bool(self.subscription_key and self.region)

    async def synthesize(
        self,
        text: str,
        emotion: Optional[str] = None,
        output_path: Optional[str] = None,
    ) -> SynthesisResult:
        if not text or not text.strip():
            raise ValueError("[AzureTTS] Cannot synthesize empty text.")

        return await asyncio.to_thread(self._synthesize_sync, text, output_path)

    async def synthesize_feedback(self, text: str) -> SynthesisResult:
        return await self.synthesize(text)

    def _synthesize_sync(
        self,
        text: str,
        output_path: Optional[str],
    ) -> SynthesisResult:
        audio_path = output_path or self._new_output_path()
        speech_config = speechsdk.SpeechConfig(
            subscription=self.subscription_key,
            region=self.region,
        )
        speech_config.speech_synthesis_voice_name = self.voice_name
        speech_config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Riff16Khz16BitMonoPcm
        )

        audio_config = speechsdk.audio.AudioOutputConfig(filename=audio_path)
        synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=speech_config,
            audio_config=audio_config,
        )

        logger.info(
            "[AzureTTS] Starting synthesis region=%s voice=%s chars=%s",
            self.region,
            self.voice_name,
            len(text),
        )
        result = synthesizer.speak_text_async(text).get()

        if result.reason == speechsdk.ResultReason.Canceled:
            cancellation = result.cancellation_details
            raise RuntimeError(
                "Azure TTS canceled: "
                f"reason={cancellation.reason}, "
                f"code={cancellation.error_code}, "
                f"details={cancellation.error_details}"
            )

        if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
            raise RuntimeError(f"Unexpected Azure TTS result reason: {result.reason}")

        if not os.path.isfile(audio_path):
            raise RuntimeError("Azure TTS did not produce an audio file.")

        with open(audio_path, "rb") as file:
            audio_bytes = file.read()

        logger.info("[AzureTTS] Audio saved: %s", audio_path)
        return SynthesisResult(
            audio_data=audio_bytes,
            audio_path=audio_path,
            duration=0.0,
        )

    def _new_output_path(self) -> str:
        return str(self.temp_dir / f"azure_tts_{int(time.time() * 1000)}.wav")
