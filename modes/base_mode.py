"""
Abstract base class for practice modes — 练习模式抽象基类

All practice modes (FreeTalk, ReadAloud, Scenario, WordDrill) inherit
from BaseMode and implement the start/handle_voice/handle_text interface.
Each mode receives shared service instances for STT, TTS, conversation,
pronunciation assessment, feedback generation, and progress tracking.
"""

from abc import ABC, abstractmethod
from typing import Any, Optional

from ..core.session import Session


class BaseMode(ABC):
    """Abstract base class that all practice modes must implement.

    所有练习模式必须实现的抽象基类。

    Each mode encapsulates the logic for a specific type of oral practice
    (free talk, read aloud, scenario roleplay, word drill). Modes receive
    injected service dependencies so they can focus purely on mode-specific
    logic.

    Attributes:
        session: The active user session.
        stt_service: Speech-to-text service for transcribing user audio.
        tts_service: Text-to-speech service for generating audio responses.
        conversation_engine: LLM-based conversation engine for generating replies.
        pronunciation_assessor: Azure pronunciation assessment service (optional).
        feedback_generator: Generates structured feedback from assessment data (optional).
        progress_tracker: Tracks user progress and statistics (optional).
    """

    def __init__(
        self,
        session: Session,
        stt_service: Any,
        tts_service: Any,
        conversation_engine: Any,
        pronunciation_assessor: Optional[Any] = None,
        feedback_generator: Optional[Any] = None,
        progress_tracker: Optional[Any] = None,
    ) -> None:
        """Initialize the mode with session and service dependencies.

        使用会话和服务依赖初始化模式。

        Args:
            session: The active user session instance.
            stt_service: Speech-to-text service.
            tts_service: Text-to-speech service.
            conversation_engine: LLM conversation engine.
            pronunciation_assessor: Pronunciation assessment service (optional).
            feedback_generator: Feedback generation service (optional).
            progress_tracker: Progress tracking service (optional).
        """
        self.session = session
        self.stt_service = stt_service
        self.tts_service = tts_service
        self.conversation_engine = conversation_engine
        self.pronunciation_assessor = pronunciation_assessor
        self.feedback_generator = feedback_generator
        self.progress_tracker = progress_tracker

    @abstractmethod
    async def start(self) -> tuple[str, Optional[bytes]]:
        """Start the practice mode and return an initial greeting/instruction.

        启动练习模式，返回初始问候或指引。

        This is called once when the user enters a mode. It should set up
        any mode-specific state and return a welcome message (with optional
        audio).

        Returns:
            tuple[str, Optional[bytes]]:
                - text_response: The text greeting/instruction to send.
                - audio_bytes: Optional TTS audio bytes for the greeting,
                  or None if no audio should be sent.
        """
        pass

    @abstractmethod
    async def handle_voice(self, audio_path: str) -> tuple[str, Optional[bytes]]:
        """Handle a voice input from the user.

        处理用户的语音输入。

        This is the primary input method for oral practice. The mode should:
        1. Transcribe the audio using the STT service.
        2. Process the transcription (assess pronunciation, generate reply, etc.).
        3. Optionally generate TTS audio for the response.

        Args:
            audio_path: Absolute path to the user's audio file
                        (already converted to WAV PCM format).

        Returns:
            tuple[str, Optional[bytes]]:
                - text_response: The text reply (feedback, conversation, etc.).
                - audio_bytes: Optional TTS audio bytes for the response,
                  or None if no audio should be sent.
        """
        pass

    @abstractmethod
    async def handle_text(self, text: str) -> tuple[str, Optional[bytes]]:
        """Handle a text input from the user.

        处理用户的文本输入。

        Text input can be used for conversation, commands within a mode,
        or as a fallback when voice is unavailable.

        Args:
            text: The user's text message.

        Returns:
            tuple[str, Optional[bytes]]:
                - text_response: The text reply.
                - audio_bytes: Optional TTS audio bytes for the response,
                  or None if no audio should be sent.
        """
        pass

    def _log_prefix(self) -> str:
        """Build a log prefix with mode and user info for consistent logging.

        构建包含模式和用户信息的日志前缀。

        Returns:
            str: Formatted log prefix string.
        """
        mode_name = self.__class__.__name__
        return (
            f"[{mode_name}] user='{self.session.display_name}' "
            f"state={self.session.state.value}"
        )
