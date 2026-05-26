"""
Read Aloud Mode — 朗读练习模式
Bot 给出句子，用户朗读后获得 Azure 发音评估反馈
"""

from __future__ import annotations

import random
from typing import Optional

from astrbot.api import logger

from .base_mode import BaseMode


class ReadAloudMode(BaseMode):
    """
    朗读练习模式

    流程：Bot 出题 → 用户语音朗读 → Azure 评估 → 反馈报告

    支持内置句库和 LLM 动态生成句子。
    """

    # 内置分级练习句库
    PRACTICE_SENTENCES: dict[str, list[str]] = {
        "A1": [
            "Hello, my name is nice to meet you.",
            "How are you today?",
            "I like to eat apples and oranges.",
            "The weather is nice today.",
            "Where is the library?",
            "Can you help me please?",
            "I have two brothers and one sister.",
            "She is reading a book.",
            "We go to school every day.",
            "Thank you very much.",
        ],
        "A2": [
            "I usually wake up at seven o'clock in the morning.",
            "Could you please tell me the way to the station?",
            "She enjoys reading books in her free time.",
            "We had a wonderful time at the beach last weekend.",
            "I would like to order a cup of coffee, please.",
            "The restaurant is on the other side of the street.",
            "He has been studying English for three years.",
            "What kind of music do you like to listen to?",
            "I think this movie is really interesting.",
            "They are planning a trip to Japan next month.",
        ],
        "B1": [
            "The weather is beautiful today, and I feel like going for a walk in the park.",
            "Although the movie was quite long, I found it incredibly engaging.",
            "If I had more free time, I would definitely travel around the world.",
            "The restaurant we visited last night had an excellent selection of dishes.",
            "Learning a new language requires patience, dedication, and consistent practice.",
            "I've been thinking about changing my career path for quite some time now.",
            "The conference was well organized and the speakers were very knowledgeable.",
            "Would you mind if I opened the window? It's getting rather warm in here.",
            "She managed to finish the project despite facing numerous challenges.",
            "The city has changed dramatically over the past decade.",
        ],
        "B2": [
            "Despite the challenging circumstances, the team managed to deliver the project ahead of schedule.",
            "The exhibition showcased a remarkable collection of contemporary art from emerging artists.",
            "Environmental sustainability has become one of the most pressing issues of our generation.",
            "The entrepreneur successfully navigated the complexities of international business regulations.",
            "Advances in artificial intelligence are fundamentally transforming how we approach problem-solving.",
            "The government's new policy aims to address the growing inequality in access to education.",
            "It's worth considering the long-term implications before making such a significant decision.",
            "The research findings suggest a strong correlation between physical exercise and mental health.",
            "Cultural differences can sometimes lead to misunderstandings in international negotiations.",
            "The unprecedented growth in technology has created both opportunities and challenges for society.",
        ],
    }

    async def start(self) -> tuple[str, Optional[bytes]]:
        """启动朗读练习模式"""
        logger.info(f"{self._log_prefix()} 朗读练习模式启动")

        # 获取用户等级
        level = self.session.mode_data.get("level", "B1")
        if self.progress_tracker:
            try:
                level = await self.progress_tracker.get_user_level(
                    self.session.user_id
                )
            except Exception:
                pass
        self.session.mode_data["level"] = level
        self.session.mode_data["practiced_sentences"] = []
        self.session.mode_data["scores"] = []

        # 获取第一个句子
        sentence = await self._get_next_sentence()
        self.session.current_reference = sentence

        welcome = (
            "📖 朗读练习模式已开启！\n"
            f"📚 当前等级: CEFR {level}\n"
            "━━━━━━━━━━━━━━━━━━━\n\n"
            f"请朗读以下句子：\n\n"
            f"📝 \"{sentence}\"\n\n"
            "准备好了就发送语音~ 🎤\n\n"
            "💡 命令: 输入「下一个」跳过 | 「换难度」调整等级"
        )

        # TTS 朗读示范
        audio = await self._try_tts(sentence)

        return welcome, audio

    async def handle_voice(self, audio_path: str) -> tuple[str, Optional[bytes]]:
        """
        处理用户朗读语音

        1. 获取参考文本
        2. Azure 发音评估
        3. 生成反馈
        4. 记录分数
        """
        reference = self.session.current_reference
        if not reference:
            return "⚠️ 当前没有朗读任务，请发送 /oral read 重新开始", None

        logger.info(f"{self._log_prefix()} 评估朗读: \"{reference[:50]}...\"")

        # 发音评估
        if self.pronunciation_assessor:
            try:
                assessment = await self.pronunciation_assessor.assess(
                    audio_path=audio_path,
                    reference_text=reference,
                    language="en-US",
                )
            except Exception as e:
                logger.error(f"{self._log_prefix()} Azure 评估失败: {e}")
                # 降级：仅做 STT 转写
                return await self._fallback_stt_only(audio_path, reference)
        else:
            return await self._fallback_stt_only(audio_path, reference)

        # 生成反馈报告
        if self.feedback_generator:
            try:
                report = await self.feedback_generator.generate(
                    assessment=assessment,
                    reference_text=reference,
                )
                feedback_text = report.summary_text
            except Exception as e:
                logger.warning(f"{self._log_prefix()} 反馈生成失败: {e}")
                feedback_text = self._simple_feedback(assessment)
        else:
            feedback_text = self._simple_feedback(assessment)

        # 记录分数
        self.session.mode_data.setdefault("scores", []).append(
            assessment.overall_score
        )

        # 记录发音错误
        if self.progress_tracker and assessment.problem_words:
            for pw in assessment.problem_words:
                try:
                    await self.progress_tracker.record_pronunciation_error(
                        user_id=self.session.user_id,
                        word=pw.word,
                        error_type=pw.error_type,
                        accuracy_score=pw.accuracy_score,
                    )
                except Exception:
                    pass

        # 构建完整响应
        text_parts = [feedback_text, ""]

        # 判断是否需要重试
        if assessment.overall_score >= 85:
            text_parts.append("✨ 太棒了！发送语音继续下一个句子~")
            # 自动切换到下一个句子
            next_sentence = await self._get_next_sentence()
            self.session.current_reference = next_sentence
            text_parts.extend([
                "",
                "📝 下一个句子：",
                f"\"{next_sentence}\"",
            ])
        else:
            text_parts.append(
                "💪 要再试一次吗？发送语音重新朗读~\n"
                "或输入「下一个」跳到新句子"
            )

        return "\n".join(text_parts), None

    async def handle_text(self, text: str) -> tuple[str, Optional[bytes]]:
        """处理文本命令"""
        text_lower = text.strip().lower()

        # 下一个句子
        if text_lower in ("下一个", "next", "skip", "跳过"):
            sentence = await self._get_next_sentence()
            self.session.current_reference = sentence
            response = (
                f"📝 请朗读以下句子：\n\n"
                f"\"{sentence}\"\n\n"
                "准备好了就发送语音~ 🎤"
            )
            audio = await self._try_tts(sentence)
            return response, audio

        # 重试当前句子
        elif text_lower in ("再来", "again", "retry", "重试"):
            sentence = self.session.current_reference
            if sentence:
                response = (
                    f"📝 再来一次：\n\n"
                    f"\"{sentence}\"\n\n"
                    "加油~ 🎤"
                )
                audio = await self._try_tts(sentence)
                return response, audio
            else:
                return "⚠️ 没有当前句子，请发送 /oral read 重新开始", None

        # 更改难度
        elif text_lower.startswith(("换难度", "level", "等级")):
            parts = text.strip().split()
            if len(parts) >= 2:
                new_level = parts[-1].upper()
                if new_level in self.PRACTICE_SENTENCES:
                    self.session.mode_data["level"] = new_level
                    if self.progress_tracker:
                        try:
                            await self.progress_tracker.update_user_level(
                                self.session.user_id, new_level
                            )
                        except Exception:
                            pass
                    sentence = await self._get_next_sentence()
                    self.session.current_reference = sentence
                    return (
                        f"✅ 难度已调整为 CEFR {new_level}\n\n"
                        f"📝 请朗读：\n\"{sentence}\"\n\n"
                        "准备好了就发送语音~ 🎤"
                    ), None
                else:
                    return "❌ 无效等级，请选择: A1, A2, B1, B2", None
            else:
                return (
                    "请指定等级，例如：\n"
                    "• 换难度 A1\n• 换难度 B2\n\n"
                    "可选: A1, A2, B1, B2"
                ), None

        else:
            return (
                "📖 朗读练习模式中\n\n"
                "可用命令：\n"
                "• 发送语音 — 朗读当前句子\n"
                "• 下一个 — 跳到新句子\n"
                "• 再来 — 重试当前句子\n"
                "• 换难度 <A1/A2/B1/B2> — 调整难度\n"
                "• /oral stop — 结束练习"
            ), None

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    async def _get_next_sentence(self) -> str:
        """获取下一个练习句子"""
        level = self.session.mode_data.get("level", "B1")
        practiced = self.session.mode_data.get("practiced_sentences", [])

        # 先尝试 LLM 生成
        if self.conversation_engine and self.conversation_engine.available:
            try:
                sentence = await self.conversation_engine.generate_sentence(
                    level=level, topic="daily life"
                )
                if sentence and len(sentence) > 5:
                    practiced.append(sentence)
                    return sentence
            except Exception as e:
                logger.debug(f"{self._log_prefix()} LLM 句子生成失败，使用内置: {e}")

        # 内置句库
        sentences = self.PRACTICE_SENTENCES.get(level, self.PRACTICE_SENTENCES["B1"])

        # 过滤已练习过的
        available = [s for s in sentences if s not in practiced]
        if not available:
            # 全部练习完，重新开始
            practiced.clear()
            available = sentences

        sentence = random.choice(available)
        practiced.append(sentence)
        return sentence

    async def _fallback_stt_only(
        self, audio_path: str, reference: str
    ) -> tuple[str, Optional[bytes]]:
        """降级处理：仅做 STT 转写（无评估）"""
        try:
            result = await self.stt_service.transcribe(audio_path)
            user_text = result.text
        except Exception as e:
            return f"😅 语音识别失败: {str(e)[:100]}", None

        response = (
            "📝 你的朗读：\n"
            f"\"{user_text}\"\n\n"
            "📖 参考文本：\n"
            f"\"{reference}\"\n\n"
            "⚠️ 发音评估服务暂不可用，仅显示识别结果。\n"
            "请检查 Azure Speech API Key 配置。\n\n"
            "发送语音重试，或输入「下一个」继续"
        )
        return response, None

    def _simple_feedback(self, assessment) -> str:
        """简单模板反馈（当 FeedbackGenerator 不可用时）"""
        score = assessment.overall_score

        # 进度条
        bar = "█" * round(score / 10) + "░" * (10 - round(score / 10))

        lines = [
            "📊 发音评估报告",
            "━━━━━━━━━━━━━━━━━━━",
            f"🎯 总分: {score:.0f}/100  {bar}",
            "",
            f"📌 准确度: {assessment.accuracy_score:.0f}/100",
            f"📌 流利度: {assessment.fluency_score:.0f}/100",
            f"📌 完整度: {assessment.completeness_score:.0f}/100",
            f"📌 韵律:   {assessment.prosody_score:.0f}/100",
        ]

        # 问题单词
        if assessment.problem_words:
            lines.extend(["", "⚠️ 需要注意:"])
            for pw in assessment.problem_words[:3]:
                lines.append(f"  • \"{pw.word}\" — {pw.error_type}")

        # 好的单词
        if assessment.good_words:
            good = ", ".join(f'"{w.word}"' for w in assessment.good_words[:5])
            lines.extend(["", f"🌟 发音很棒: {good}"])

        # 等级
        if score >= 90:
            lines.append("\n⭐ Excellent! 太棒了！")
        elif score >= 75:
            lines.append("\n👍 Good! 做得不错！")
        elif score >= 60:
            lines.append("\n💪 Keep Practicing! 继续加油！")
        else:
            lines.append("\n📚 多练习几次一定会进步的！")

        return "\n".join(lines)

    async def _try_tts(self, text: str) -> Optional[bytes]:
        """尝试 TTS（优雅降级）"""
        if not self.tts_service or not self.tts_service.available:
            return None
        try:
            result = await self.tts_service.synthesize(text, emotion="warm")
            return result.audio_data
        except Exception as e:
            logger.warning(f"{self._log_prefix()} TTS 失败: {e}")
            return None
