"""
Session state machine — 会话状态机

Manages per-user practice session lifecycle with an in-memory store.
Tracks session state (IDLE → mode → IDLE), conversation history,
and automatic expiration of stale sessions.
"""

import datetime
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from astrbot.api import logger


class SessionState(Enum):
    """Practice session states / 练习会话状态"""

    IDLE = "idle"
    FREE_TALK = "free_talk"
    READ_ALOUD = "read_aloud"
    SCENARIO = "scenario"
    WORD_DRILL = "word_drill"


@dataclass
class Session:
    """Represents a single user's practice session.

    表示单个用户的练习会话。

    Attributes:
        user_id: Unique user identifier.
        display_name: Human-readable display name.
        state: Current session state.
        mode_data: Arbitrary data for the active mode (e.g., scenario config).
        conversation_history: List of {"role": ..., "content": ...} dicts.
        current_reference: Reference text for read-aloud mode.
        scenario_step: Current step index in scenario mode.
        created_at: When the session was first created.
        last_active: When the session was last interacted with.
    """

    user_id: str
    display_name: str
    state: SessionState = SessionState.IDLE
    mode_data: dict = field(default_factory=dict)
    conversation_history: List[dict] = field(default_factory=list)
    current_reference: str = ""
    scenario_step: int = 0
    created_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    last_active: datetime.datetime = field(default_factory=datetime.datetime.now)

    def touch(self) -> None:
        """Update last_active timestamp to now / 更新最后活跃时间"""
        self.last_active = datetime.datetime.now()

    @property
    def is_active(self) -> bool:
        """Whether the session is in an active practice mode / 是否处于活跃练习模式"""
        return self.state != SessionState.IDLE

    @property
    def duration_minutes(self) -> float:
        """Minutes since session creation / 会话创建以来的分钟数"""
        delta = datetime.datetime.now() - self.created_at
        return delta.total_seconds() / 60.0


class SessionManager:
    """Manages all user sessions in memory.

    管理所有用户的内存会话。
    Sessions are keyed by user_id and automatically track state transitions.
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, Session] = {}

    def get_or_create(self, user_id: str, display_name: str = "") -> Session:
        """Get an existing session or create a new one for the user.

        获取现有会话或为用户创建新会话。

        Args:
            user_id: Unique user identifier.
            display_name: Human-readable name (used only on creation).

        Returns:
            Session: The user's session instance.
        """
        if user_id not in self._sessions:
            session = Session(user_id=user_id, display_name=display_name or user_id)
            self._sessions[user_id] = session
            logger.info(
                f"[session] Created new session for user '{display_name}' "
                f"(id={user_id})"
            )
        else:
            self._sessions[user_id].touch()

        return self._sessions[user_id]

    def get(self, user_id: str) -> Optional[Session]:
        """Get a session by user_id, or None if not found.

        通过 user_id 获取会话，未找到则返回 None。

        Args:
            user_id: Unique user identifier.

        Returns:
            Optional[Session]: The session if it exists, else None.
        """
        session = self._sessions.get(user_id)
        if session is not None:
            session.touch()
        return session

    def start_mode(
        self,
        user_id: str,
        mode: SessionState,
        mode_data: Optional[dict] = None,
    ) -> None:
        """Transition user session to a specific practice mode.

        将用户会话切换到指定的练习模式。

        Args:
            user_id: Unique user identifier.
            mode: Target session state (must not be IDLE).
            mode_data: Optional mode-specific configuration dict.

        Raises:
            ValueError: If user has no session.
        """
        session = self._sessions.get(user_id)
        if session is None:
            raise ValueError(
                f"Cannot start mode: no session found for user '{user_id}'"
            )

        old_state = session.state
        session.state = mode
        session.mode_data = mode_data or {}
        session.conversation_history = []  # Reset history for new mode
        session.current_reference = ""
        session.scenario_step = 0
        session.touch()

        logger.info(
            f"[session] User '{session.display_name}' transitioned "
            f"{old_state.value} -> {mode.value}"
        )

    def end_mode(self, user_id: str) -> None:
        """End the current practice mode and reset session to IDLE.

        结束当前练习模式，将会话重置为 IDLE。

        Args:
            user_id: Unique user identifier.
        """
        session = self._sessions.get(user_id)
        if session is None:
            return

        old_state = session.state
        session.state = SessionState.IDLE
        session.mode_data = {}
        session.current_reference = ""
        session.scenario_step = 0
        session.touch()

        logger.info(
            f"[session] User '{session.display_name}' ended mode "
            f"{old_state.value} -> IDLE"
        )

    def is_active(self, user_id: str) -> bool:
        """Check if a user has an active (non-IDLE) session.

        检查用户是否有活跃的（非 IDLE）会话。

        Args:
            user_id: Unique user identifier.

        Returns:
            bool: True if the user's session is in a practice mode.
        """
        session = self._sessions.get(user_id)
        if session is None:
            return False
        return session.is_active

    def cleanup_expired(self, max_minutes: int = 30) -> int:
        """Remove sessions that have been inactive beyond the max duration.

        清理超过最大时长的过期会话。

        Args:
            max_minutes: Maximum allowed inactivity in minutes.

        Returns:
            int: Number of sessions removed.
        """
        now = datetime.datetime.now()
        expired_ids: list[str] = []

        for user_id, session in self._sessions.items():
            idle_minutes = (now - session.last_active).total_seconds() / 60.0
            if idle_minutes > max_minutes:
                expired_ids.append(user_id)

        for user_id in expired_ids:
            session = self._sessions.pop(user_id)
            logger.info(
                f"[session] Expired session for user '{session.display_name}' "
                f"(inactive {max_minutes}+ min)"
            )

        if expired_ids:
            logger.info(f"[session] Cleaned up {len(expired_ids)} expired session(s)")

        return len(expired_ids)

    def add_conversation(self, user_id: str, role: str, content: str) -> None:
        """Add a message to the user's conversation history.

        向用户的对话历史中添加一条消息。

        Args:
            user_id: Unique user identifier.
            role: Message role ('user', 'assistant', or 'system').
            content: Message text content.
        """
        session = self._sessions.get(user_id)
        if session is None:
            logger.warning(
                f"[session] Cannot add conversation: no session for '{user_id}'"
            )
            return

        session.conversation_history.append({"role": role, "content": content})
        session.touch()

    def get_conversation_history(self, user_id: str, max_messages: int = 20) -> list:
        """Get recent conversation history for a user.

        获取用户的近期对话历史。

        Args:
            user_id: Unique user identifier.
            max_messages: Maximum number of recent messages to return (default: 20).

        Returns:
            list: List of {"role": ..., "content": ...} dicts, most recent last.
                  Returns an empty list if no session exists.
        """
        session = self._sessions.get(user_id)
        if session is None:
            return []

        history = session.conversation_history
        if len(history) <= max_messages:
            return list(history)

        # Return the most recent messages, preserving chronological order
        # 返回最近的消息，保持时间顺序
        return list(history[-max_messages:])
