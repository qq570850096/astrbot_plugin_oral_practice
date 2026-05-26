"""
Word Drill Mode — 单词操练模式
逐词发音练习，配合 IPA 音标和 Azure 评估
"""

from __future__ import annotations

import random
from typing import Optional

from astrbot.api import logger

from .base_mode import BaseMode


class WordDrillMode(BaseMode):
    """
    单词发音操练模式

    逐个单词练习发音，提供 IPA 音标参考，
    通过 Azure 评估给出精准反馈。
    达到 80 分自动进入下一个词。

    流程：展示单词+IPA → 用户朗读 → 评估 → 反馈 → 下一个
    """

    # 分级词汇表 (word, IPA)
    WORD_LISTS: dict[str, list[tuple[str, str]]] = {
        "A1": [
            ("hello", "/həˈloʊ/"),
            ("thank you", "/θæŋk juː/"),
            ("please", "/pliːz/"),
            ("water", "/ˈwɔːtər/"),
            ("morning", "/ˈmɔːrnɪŋ/"),
            ("beautiful", "/ˈbjuːtɪfl/"),
            ("family", "/ˈfæmɪli/"),
            ("together", "/təˈɡeðər/"),
            ("important", "/ɪmˈpɔːrtənt/"),
            ("different", "/ˈdɪfərənt/"),
            ("children", "/ˈtʃɪldrən/"),
            ("question", "/ˈkwestʃən/"),
            ("picture", "/ˈpɪktʃər/"),
            ("animal", "/ˈænɪml/"),
            ("country", "/ˈkʌntri/"),
        ],
        "A2": [
            ("restaurant", "/ˈrestərɒnt/"),
            ("comfortable", "/ˈkʌmftəbl/"),
            ("experience", "/ɪkˈspɪriəns/"),
            ("temperature", "/ˈtemprətʃər/"),
            ("vegetable", "/ˈvedʒtəbl/"),
            ("wednesday", "/ˈwenzdeɪ/"),
            ("interesting", "/ˈɪntrəstɪŋ/"),
            ("chocolate", "/ˈtʃɒklət/"),
            ("necessary", "/ˈnesəseri/"),
            ("education", "/ˌedʒuˈkeɪʃn/"),
            ("favorite", "/ˈfeɪvərɪt/"),
            ("definitely", "/ˈdefɪnɪtli/"),
            ("probably", "/ˈprɒbəbli/"),
            ("government", "/ˈɡʌvərnmənt/"),
            ("especially", "/ɪˈspeʃəli/"),
        ],
        "B1": [
            ("entrepreneur", "/ˌɒntrəprəˈnɜːr/"),
            ("pronunciation", "/prəˌnʌnsiˈeɪʃn/"),
            ("environment", "/ɪnˈvaɪrənmənt/"),
            ("opportunities", "/ˌɒpəˈtjuːnɪtiz/"),
            ("sophisticated", "/səˈfɪstɪkeɪtɪd/"),
            ("architecture", "/ˈɑːrkɪtektʃər/"),
            ("communication", "/kəˌmjuːnɪˈkeɪʃn/"),
            ("photography", "/fəˈtɒɡrəfi/"),
            ("contemporary", "/kənˈtempəreri/"),
            ("enthusiasm", "/ɪnˈθjuːziæzəm/"),
            ("development", "/dɪˈveləpmənt/"),
            ("unfortunately", "/ʌnˈfɔːrtʃənɪtli/"),
            ("professional", "/prəˈfeʃənl/"),
            ("responsibility", "/rɪˌspɒnsəˈbɪlɪti/"),
            ("approximately", "/əˈprɒksɪmɪtli/"),
        ],
        "B2": [
            ("unequivocally", "/ˌʌnɪˈkwɪvəkli/"),
            ("entrepreneurship", "/ˌɒntrəprəˈnɜːrʃɪp/"),
            ("conscientious", "/ˌkɒnʃiˈenʃəs/"),
            ("miscellaneous", "/ˌmɪsəˈleɪniəs/"),
            ("simultaneously", "/ˌsaɪmlˈteɪniəsli/"),
            ("pharmaceutical", "/ˌfɑːrməˈsuːtɪkl/"),
            ("unprecedented", "/ʌnˈpresɪdentɪd/"),
            ("deteriorate", "/dɪˈtɪriəreɪt/"),
            ("quintessential", "/ˌkwɪntɪˈsenʃl/"),
            ("idiosyncratic", "/ˌɪdiəsɪŋˈkrætɪk/"),
            ("onomatopoeia", "/ˌɒnəˌmætəˈpiːə/"),
            ("worcestershire", "/ˈwʊstərʃər/"),
            ("archaeological", "/ˌɑːrkiəˈlɒdʒɪkl/"),
            ("bureaucratic", "/ˌbjʊərəˈkrætɪk/"),
            ("hyperbole", "/haɪˈpɜːrbəli/"),
        ],
    }

    async def start(self) -> tuple[str, Optional[bytes]]:
        """启动单词操练模式"""
        logger.info(f"{self._log_prefix()} 单词操练模式启动")

        # 获取用户等级
        level = self.session.mode_data.get("level", "A2")
        if self.progress_tracker:
            try:
                level = await self.progress_tracker.get_user_level(
                    self.session.user_id
                )
            except Exception:
                pass

        self.session.mode_data["level"] = level
        self.session.mode_data["practiced_words"] = []
        self.session.mode_data["correct_count"] = 0
        self.session.mode_data["total_count"] = 0

        # 检查是否有需要复习的单词
        review_words = []
        if self.progress_tracker:
            try:
                review_words = await self.progress_tracker.get_words_for_review(
                    self.session.user_id, limit=5
                )
            except Exception:
                pass

        if review_words:
            # 优先复习
            first_word = review_words[0].word
            self.session.mode_data["review_mode"] = True
            self.session.mode_data["review_words"] = [
                w.word for w in review_words
            ]
            self.session.current_reference = first_word

            # 查找 IPA
            ipa = self._find_ipa(first_word, level)

            welcome = (
                "📝 单词发音操练\n"
                f"📚 等级: CEFR {level}\n"
                "━━━━━━━━━━━━━━━━━━━\n\n"
                f"🔄 你有 {len(review_words)} 个单词需要复习！\n\n"
                + self._format_word_prompt(first_word, ipa)
            )
        else:
            # 新单词
            word, ipa = self._get_random_word(level)
            self.session.current_reference = word
            self.session.mode_data["current_ipa"] = ipa

            welcome = (
                "📝 单词发音操练\n"
                f"📚 等级: CEFR {level}\n"
                "━━━━━━━━━━━━━━━━━━━\n\n"
                + self._format_word_prompt(word, ipa)
                + "\n\n💡 命令: 「下一个」跳过 | 「换难度 <等级>」调整"
            )

        # TTS 示范发音
        audio = await self._try_tts(self.session.current_reference)

        return welcome, audio

    async def handle_voice(self, audio_path: str) -> tuple[str, Optional[bytes]]:
        """
        处理用户朗读

        1. 获取当前单词
        2. Azure 评估
        3. ≥80 自动下一个，<80 提示重试
        """
        current_word = self.session.current_reference
        if not current_word:
            return "⚠️ 没有当前单词，请发送 /oral drill 重新开始", None

        logger.info(f"{self._log_prefix()} 评估单词: \"{current_word}\"")

        # 发音评估
        if self.pronunciation_assessor:
            try:
                assessment = await self.pronunciation_assessor.assess(
                    audio_path=audio_path,
                    reference_text=current_word,
                    language="en-US",
                )
            except Exception as e:
                logger.error(f"{self._log_prefix()} 评估失败: {e}")
                return (
                    "😅 评估出了点问题，请再试一次~\n"
                    f"当前单词: \"{current_word}\"",
                    None,
                )
        else:
            # 无评估服务，仅做 STT
            try:
                result = await self.stt_service.transcribe(audio_path)
                return (
                    f"📝 识别结果: \"{result.text}\"\n"
                    f"📖 目标单词: \"{current_word}\"\n\n"
                    "⚠️ 发音评估服务未配置，仅显示识别结果。",
                    None,
                )
            except Exception:
                return "😅 语音识别失败，请再试一次~", None

        score = assessment.accuracy_score
        self.session.mode_data["total_count"] = (
            self.session.mode_data.get("total_count", 0) + 1
        )

        # 记录发音错误
        if score < 80 and self.progress_tracker:
            try:
                error_type = "mispronunciation"
                if assessment.problem_words:
                    error_type = assessment.problem_words[0].error_type
                await self.progress_tracker.record_pronunciation_error(
                    user_id=self.session.user_id,
                    word=current_word,
                    error_type=error_type,
                    accuracy_score=score,
                )
            except Exception:
                pass

        # 生成反馈
        level = self.session.mode_data.get("level", "A2")
        ipa = self.session.mode_data.get("current_ipa", "")

        if score >= 80:
            # 通过！自动下一个
            self.session.mode_data["correct_count"] = (
                self.session.mode_data.get("correct_count", 0) + 1
            )

            # 获取统计
            correct = self.session.mode_data["correct_count"]
            total = self.session.mode_data["total_count"]

            # 下一个词
            next_word, next_ipa = self._get_random_word(
                level,
                exclude=self.session.mode_data.get("practiced_words", []),
            )
            self.session.current_reference = next_word
            self.session.mode_data["current_ipa"] = next_ipa
            self.session.mode_data.setdefault("practiced_words", []).append(
                current_word
            )

            # 评语
            if score >= 95:
                praise = "🌟 Perfect! 完美发音！"
            elif score >= 90:
                praise = "⭐ Excellent! 非常棒！"
            else:
                praise = "✅ Good! 发音过关！"

            response = (
                f"🎯 \"{current_word}\" — 准确度: {score:.0f}/100\n"
                f"{praise}\n"
                f"📈 进度: {correct}/{total} 正确\n\n"
                "━━━━━━━━━━━━━━━━━━━\n\n"
                f"下一个：\n"
                + self._format_word_prompt(next_word, next_ipa)
            )

            audio = await self._try_tts(next_word)
            return response, audio

        else:
            # 未通过，提示重试
            bar = "█" * round(score / 10) + "░" * (10 - round(score / 10))

            lines = [
                f"🎯 \"{current_word}\" — 准确度: {score:.0f}/100  {bar}",
            ]

            # 具体问题
            if assessment.problem_words:
                pw = assessment.problem_words[0]
                error_labels = {
                    "Mispronunciation": "发音不准确",
                    "Omission": "遗漏",
                    "Insertion": "多余发音",
                }
                label = error_labels.get(pw.error_type, pw.error_type)
                lines.append(f"⚠️ 问题: {label}")

            if ipa:
                lines.append(f"🔊 正确发音: {ipa}")

            # 分解提示
            if len(current_word) > 5:
                syllables = self._suggest_syllables(current_word)
                if syllables:
                    lines.append(f"💡 分解练习: {syllables}")

            lines.extend([
                "",
                "再试一次？发送语音重新朗读~",
                "或输入「下一个」跳过",
            ])

            # TTS 示范
            audio = await self._try_tts(current_word)
            return "\n".join(lines), audio

    async def handle_text(self, text: str) -> tuple[str, Optional[bytes]]:
        """处理文本命令"""
        text_lower = text.strip().lower()

        # 下一个
        if text_lower in ("下一个", "next", "skip", "跳过"):
            level = self.session.mode_data.get("level", "A2")
            word, ipa = self._get_random_word(
                level,
                exclude=self.session.mode_data.get("practiced_words", []),
            )
            self.session.current_reference = word
            self.session.mode_data["current_ipa"] = ipa
            self.session.mode_data.setdefault("practiced_words", []).append(word)

            response = self._format_word_prompt(word, ipa)
            audio = await self._try_tts(word)
            return response, audio

        # 重试
        elif text_lower in ("再来", "again", "retry", "重试"):
            word = self.session.current_reference
            ipa = self.session.mode_data.get("current_ipa", "")
            if word:
                response = f"🔄 再来一次！\n\n" + self._format_word_prompt(word, ipa)
                audio = await self._try_tts(word)
                return response, audio
            return "⚠️ 没有当前单词，请发送 /oral drill 重新开始", None

        # 换难度
        elif text_lower.startswith(("换难度", "level", "等级")):
            parts = text.strip().split()
            if len(parts) >= 2:
                new_level = parts[-1].upper()
                if new_level in self.WORD_LISTS:
                    self.session.mode_data["level"] = new_level
                    self.session.mode_data["practiced_words"] = []
                    if self.progress_tracker:
                        try:
                            await self.progress_tracker.update_user_level(
                                self.session.user_id, new_level
                            )
                        except Exception:
                            pass

                    word, ipa = self._get_random_word(new_level)
                    self.session.current_reference = word
                    self.session.mode_data["current_ipa"] = ipa

                    return (
                        f"✅ 难度已调整为 CEFR {new_level}\n\n"
                        + self._format_word_prompt(word, ipa)
                    ), await self._try_tts(word)
                else:
                    return "❌ 无效等级，请选择: A1, A2, B1, B2", None
            else:
                return "请指定等级，例如: 换难度 B1", None

        else:
            return (
                "📝 单词操练模式中\n\n"
                "可用命令：\n"
                "• 发送语音 — 朗读当前单词\n"
                "• 下一个 — 跳到新单词\n"
                "• 再来 — 重试当前单词\n"
                "• 换难度 <A1/A2/B1/B2> — 调整难度\n"
                "• /oral stop — 结束练习"
            ), None

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _get_random_word(
        self, level: str, exclude: list = None
    ) -> tuple[str, str]:
        """获取随机单词和 IPA"""
        words = self.WORD_LISTS.get(level, self.WORD_LISTS["A2"])
        exclude = exclude or []

        available = [(w, i) for w, i in words if w not in exclude]
        if not available:
            # 全部练完，重置
            available = words
            if "practiced_words" in self.session.mode_data:
                self.session.mode_data["practiced_words"] = []

        word, ipa = random.choice(available)
        return word, ipa

    def _find_ipa(self, word: str, level: str) -> str:
        """查找单词的 IPA 音标"""
        word_lower = word.lower().strip()
        # 搜索所有等级
        for lvl in [level] + list(self.WORD_LISTS.keys()):
            for w, ipa in self.WORD_LISTS.get(lvl, []):
                if w.lower() == word_lower:
                    return ipa
        return ""

    @staticmethod
    def _format_word_prompt(word: str, ipa: str) -> str:
        """格式化单词展示"""
        lines = [
            f"📝 请朗读: \"{word}\"",
        ]
        if ipa:
            lines.append(f"🔊 {ipa}")
        lines.append("")
        lines.append("准备好了就发送语音~ 🎤")
        return "\n".join(lines)

    @staticmethod
    def _suggest_syllables(word: str) -> str:
        """
        简单的音节分解建议

        基于辅音-元音模式的启发式分割，不完全准确但足够有用
        """
        vowels = set("aeiou")
        result = []
        current = ""

        for i, ch in enumerate(word.lower()):
            current += ch
            # 在元音后、下一个辅音前分割
            if (
                ch in vowels
                and i + 1 < len(word)
                and word[i + 1].lower() not in vowels
                and len(current) >= 2
            ):
                result.append(current)
                current = ""

        if current:
            if result:
                result[-1] += current
            else:
                result.append(current)

        if len(result) <= 1:
            return ""

        # 标记重音（简化：最长音节加重音）
        longest_idx = max(range(len(result)), key=lambda i: len(result[i]))
        parts = []
        for i, syl in enumerate(result):
            if i == longest_idx:
                parts.append(syl.upper())
            else:
                parts.append(syl)

        return "-".join(parts)

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
