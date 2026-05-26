"""
Free Talk Mode — 自由对话模式
与 AI 口语伙伴 Alex 进行自然英语对话
"""

from __future__ import annotations

from typing import Optional

from astrbot.api import logger

from .base_mode import BaseMode
from ..prompts.tutor_system import FREE_TALK_SYSTEM_PROMPT


class FreeTalkMode(BaseMode):
    """
    自由对话模式

    用户与 AI 口语伙伴 Alex 进行自然对话，
    AstrBot LLM 提供商会在对话中穿插语言表达建议。
    不做发音评估（避免打断对话流畅性）。

    流程：语音 → STT → GPT 对话 → 文本级反馈 → TTS 回复
    """

    async def start(self) -> tuple[str, Optional[bytes]]:
        """启动自由对话模式"""
        logger.info(f"{self._log_prefix()} 自由对话模式启动")

        # 初始化对话历史
        self.session.conversation_history = []

        welcome_text = (
            "🎙️ 自由对话模式已开启！\n\n"
            "Hi! I'm Alex, your English conversation partner. 😊\n"
            "Feel free to talk about anything — travel, movies, food, "
            "work, or whatever you'd like!\n\n"
            "Just send me a voice message to start.\n\n"
            "💡 我会在对话中给你一些表达建议哦~\n"
            "发送 /oral stop 结束练习"
        )

        # 尝试生成欢迎语音
        audio_bytes = await self._try_tts(
            "Hi! I'm Alex, your English conversation partner. "
            "Feel free to talk about anything you'd like!"
        )

        return welcome_text, audio_bytes

    async def handle_voice(self, audio_path: str) -> tuple[str, Optional[bytes]]:
        """
        处理语音输入

        1. STT 转写
        2. 添加到对话历史
        3. GPT 生成回复 + 表达建议
        4. TTS 合成回复
        """
        logger.info(f"{self._log_prefix()} 收到语音输入")

        # 1. 语音转文字
        try:
            transcribe_result = await self.stt_service.transcribe(audio_path)
            user_text = transcribe_result.text
        except Exception as e:
            logger.error(f"{self._log_prefix()} STT 失败: {e}")
            return (
                "😅 抱歉，语音识别出了点问题，请再试一次~\n"
                f"错误: {str(e)[:100]}",
                None,
            )

        if not user_text.strip():
            return "🤔 没有听清你说什么，请再说一次？", None

        # 2. 生成回复
        text_response, ai_reply = await self._generate_conversation(user_text)

        # 3. TTS 合成 AI 的对话部分
        audio_bytes = await self._try_tts(ai_reply) if ai_reply else None

        return text_response, audio_bytes

    async def handle_text(self, text: str) -> tuple[str, Optional[bytes]]:
        """处理文本输入（跳过 STT）"""
        logger.info(f"{self._log_prefix()} 收到文本输入: {text[:50]}")

        if not text.strip():
            return "🤔 你想说什么呢？试试发语音消息~", None

        # 生成回复
        text_response, ai_reply = await self._generate_conversation(text)

        # TTS 合成
        audio_bytes = await self._try_tts(ai_reply) if ai_reply else None

        return text_response, audio_bytes

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    async def _generate_conversation(
        self, user_text: str
    ) -> tuple[str, str]:
        """
        使用 GPT 生成对话回复

        Args:
            user_text: 用户输入文字

        Returns:
            (完整文本响应含识别结果, 纯 AI 回复用于 TTS)
        """
        # 添加用户消息到历史
        self.session.conversation_history.append({
            "role": "user",
            "content": user_text,
        })

        # 调用 GPT 生成回复
        try:
            ai_reply = await self.conversation_engine.generate_response(
                user_text=user_text,
                conversation_history=self.session.conversation_history[:-1],
                system_prompt=FREE_TALK_SYSTEM_PROMPT,
            )
        except Exception as e:
            logger.error(f"{self._log_prefix()} GPT 调用失败: {e}")
            ai_reply = (
                "Hmm, I'm having a bit of trouble thinking right now. "
                "Could you try saying that again? 😊"
            )

        # 添加 AI 回复到历史
        self.session.conversation_history.append({
            "role": "assistant",
            "content": ai_reply,
        })

        # 保持历史在合理长度
        if len(self.session.conversation_history) > 30:
            self.session.conversation_history = (
                self.session.conversation_history[-20:]
            )

        # 构建完整文本响应
        text_response = f"📝 识别文字: \"{user_text}\"\n\n🗣️ {ai_reply}"

        return text_response, ai_reply

    async def _try_tts(self, text: str) -> Optional[bytes]:
        """尝试 TTS 合成，失败时返回 None（优雅降级）"""
        if not self.tts_service or not self.tts_service.available:
            return None
        try:
            # 清理文本中的 emoji 和格式标记
            clean_text = self._clean_for_tts(text)
            if not clean_text:
                return None
            result = await self.tts_service.synthesize(clean_text, emotion="warm")
            return result.audio_data
        except Exception as e:
            logger.warning(f"{self._log_prefix()} TTS 失败 (优雅降级): {e}")
            return None

    @staticmethod
    def _clean_for_tts(text: str) -> str:
        """清理文本，移除不适合 TTS 的内容"""
        import re
        # 移除 emoji
        text = re.sub(
            r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF'
            r'\U0001F680-\U0001F6FF\U0001F900-\U0001F9FF'
            r'\U00002702-\U000027B0\U0001FA00-\U0001FA6F'
            r'\U0001FA70-\U0001FAFF\U00002600-\U000026FF]+',
            '', text
        )
        # 移除 **bold** 标记
        text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
        # 移除 💡 Tip: 前缀（保留内容）
        text = re.sub(r'💡\s*\*?Tip:?\*?\s*', '', text)
        return text.strip()
