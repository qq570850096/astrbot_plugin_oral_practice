"""
Feedback Report Generator
反馈报告生成模块

Takes an AssessmentResult and generates human-friendly feedback, either via
template-based formatting (fallback) or GPT-enhanced rich feedback.
"""

import json
from dataclasses import dataclass, field
from typing import Optional, Callable, Awaitable, List, Tuple
from astrbot.api import logger

from .pronunciation import AssessmentResult


# ── Feedback prompt for LLM-based feedback generation ──
FEEDBACK_SYSTEM_PROMPT = """\
你是一位严格、专业、真心希望学生提高口语的英语发音教练。学生是中文母语者。

你的反馈必须中英混合，像真人老师一样具体、直接、有训练价值。不要只说
"Good work" 或 "很棒"。即使分数高，也要指出至少一个可以继续打磨的点。

评分态度：
- overall < 85：不要说“很棒”，只能说“基础不错/能听懂，但仍需打磨”
- accuracy 高且 fluency 高时，也要检查 word stress、sentence stress、linking、ending sounds
- prosody 为 0 或缺失时，不要批评 Azure 没给分；改为提醒学生练重音、停顿和语调

反馈结构：
1. 先用一句话评价整体表现，中文为主，夹一个自然英文短句。
2. 指出 2 个最值得练的问题：具体到单词、音素 IPA、重音或连读。
3. 每个问题都给一个“怎么练”的动作，例如舌位、嘴型、重读位置、慢读次数。
4. 最后给 1 个 30 秒练习任务。

格式要求：
- 使用中文解释，关键术语和例句可用英文。
- 必须包含 IPA，例如 /θ/, /lɪtl/, /ˈmɔːrnɪŋz/。
- 180-350 中文字，最多 8 行。
- 语气严格但不打击人：像负责的老师，不像客服。
"""


@dataclass
class FeedbackReport:
    """Complete feedback report / 完整反馈报告"""
    summary_text: str           # Full text feedback for display
    score_card: str             # Visual score card with progress bars
    tips: List[str]             # Actionable tips
    problem_words_text: str     # Problem words with details
    praise_text: str            # Positive reinforcement
    overall_grade: str          # 'Excellent'/'Good'/'Keep Practicing'/'Needs Work'


# ── Error type display mapping (English -> Chinese) ──
_ERROR_TYPE_LABELS = {
    "None": "正确",
    "Omission": "遗漏",
    "Insertion": "多读",
    "Mispronunciation": "发音不准确",
    "UnexpectedBreak": "意外停顿",
    "MissingBreak": "缺少停顿",
    "Monotone": "语调单一",
}


class FeedbackGenerator:
    """
    Generates human-friendly feedback reports from pronunciation assessment results.
    根据发音评估结果生成用户友好的反馈报告

    Supports two modes:
    1. Template-based (no LLM) — always available as fallback
    2. LLM-enhanced — uses GPT for rich, personalized feedback
    """

    GRADE_THRESHOLDS: List[Tuple[int, Tuple[str, str]]] = [
        (90, ("⭐ Excellent!", "太棒了！")),
        (75, ("👍 Good!", "做得不错！")),
        (60, ("💪 Keep Practicing!", "继续加油！")),
        (0,  ("📚 Needs Work", "需要多练习~")),
    ]

    # Template-based tips pool, keyed by issue category
    # 基于模板的提示库
    _TIPS_BY_ISSUE = {
        "low_accuracy": [
            "试着放慢语速，一个词一个词地发清楚",
            "可以用手机录音对比原文发音，找到差异",
            "关注元音的发音位置，嘴型要到位",
        ],
        "low_fluency": [
            "多做跟读练习，模仿原文的节奏和停顿",
            "试着把句子分成意群来读，每个意群之间自然停顿",
            "先慢读确保正确，再逐渐提速",
        ],
        "low_completeness": [
            "注意不要漏读单词，可以先看一遍原文再开始朗读",
            "朗读时用手指跟着文字移动，确保每个词都读到",
            "如果遇到不认识的单词，先查发音再朗读",
        ],
        "low_prosody": [
            "注意句子的升降调，陈述句结尾降调，疑问句结尾升调",
            "试着模仿母语者的语调变化，可以跟读新闻播报",
            "给重点单词适当加重读，让表达更自然",
        ],
        "perfect": [
            "继续保持！可以尝试更长或更难的篇章",
            "试着用更自然的语调朗读，加入情感表达",
            "挑战绕口令或演讲段落，进一步提升流利度",
        ],
    }

    def __init__(self, llm_call: Optional[Callable] = None):
        """
        Initialize the feedback generator.

        Args:
            llm_call: Optional async callable with signature:
                      (system_prompt: str, user_prompt: str) -> str
                      If None, uses template-based feedback only.
        """
        self.llm_call = llm_call

    async def generate(
        self,
        assessment: AssessmentResult,
        reference_text: Optional[str] = None,
    ) -> FeedbackReport:
        """
        Generate a complete feedback report from assessment results.
        根据评估结果生成完整的反馈报告

        If llm_call is available, uses GPT for the summary text.
        Otherwise, uses template-based feedback as fallback.

        Args:
            assessment: The pronunciation assessment result
            reference_text: Original reference text (used for LLM context)

        Returns:
            FeedbackReport with all sections populated
        """
        # Generate individual sections
        score_card = self._generate_score_card(assessment)
        grade_en, grade_cn = self._get_grade(assessment.overall_score)
        overall_grade = f"{grade_en} {grade_cn}"
        problem_words_text = self._format_problem_words(assessment)
        praise_text = self._format_praise(assessment)
        tips = self._select_tips(assessment)

        # Generate summary text
        if self.llm_call and reference_text:
            try:
                llm_summary = await self._generate_llm_feedback(
                    assessment, reference_text
                )
                summary_text = llm_summary
            except Exception as e:
                logger.warning(
                    f"[FeedbackGenerator] LLM feedback generation failed: {e}. "
                    "Falling back to template."
                )
                summary_text = self._generate_template_summary(
                    assessment, grade_en, grade_cn
                )
        else:
            summary_text = self._generate_template_summary(
                assessment, grade_en, grade_cn
            )

        return FeedbackReport(
            summary_text=summary_text,
            score_card=score_card,
            tips=tips,
            problem_words_text=problem_words_text,
            praise_text=praise_text,
            overall_grade=overall_grade,
        )

    # ─────────────────────────────────────────────
    # Score Card
    # ─────────────────────────────────────────────

    def _generate_score_card(self, assessment: AssessmentResult) -> str:
        """
        Generate a visual score card with Unicode progress bars.
        生成带有 Unicode 进度条的可视化评分卡

        Example output:
        📊 发音评估报告
        ━━━━━━━━━━━━━━━━━━━
        🎯 总分: 82/100

        📌 准确度: 85  ████████░░
        📌 流利度: 78  ███████░░░
        📌 完整度: 90  █████████░
        📌 韵律:   75  ███████░░░
        """
        lines = [
            "📊 发音评估报告",
            "━━━━━━━━━━━━━━━━━━━",
            f"🎯 总分: {assessment.overall_score:.0f}/100",
            "",
            f"📌 准确度: {assessment.accuracy_score:5.0f}  "
            f"{self._generate_progress_bar(assessment.accuracy_score)}",
            f"📌 流利度: {assessment.fluency_score:5.0f}  "
            f"{self._generate_progress_bar(assessment.fluency_score)}",
            f"📌 完整度: {assessment.completeness_score:5.0f}  "
            f"{self._generate_progress_bar(assessment.completeness_score)}",
            f"📌 韵律:   {assessment.prosody_score:5.0f}  "
            f"{self._generate_progress_bar(assessment.prosody_score)}",
        ]
        return "\n".join(lines)

    def _generate_progress_bar(self, score: float, width: int = 10) -> str:
        """
        Generate a text progress bar using Unicode block characters.
        使用 Unicode 方块字符生成文本进度条

        Args:
            score: Score from 0 to 100
            width: Total width of the progress bar in characters

        Returns:
            String like "████████░░" representing the score
        """
        # Clamp score to [0, 100]
        score = max(0.0, min(100.0, score))
        filled = round(score / 100 * width)
        empty = width - filled
        return "█" * filled + "░" * empty

    # ─────────────────────────────────────────────
    # Grade
    # ─────────────────────────────────────────────

    def _get_grade(self, score: float) -> Tuple[str, str]:
        """
        Get grade label from score.
        根据分数获取等级标签

        Returns:
            Tuple of (english_grade, chinese_grade)
        """
        for threshold, labels in self.GRADE_THRESHOLDS:
            if score >= threshold:
                return labels
        # Fallback (should not reach here due to 0 threshold)
        return self.GRADE_THRESHOLDS[-1][1]

    # ─────────────────────────────────────────────
    # Problem Words
    # ─────────────────────────────────────────────

    def _format_problem_words(self, assessment: AssessmentResult) -> str:
        """
        Format problem words with error descriptions.
        格式化问题单词及其错误描述

        Example output:
        ⚠️ 需要注意的发音:
        • "beautiful" → 准确度: 45/100
          错误类型: 发音不准确
        • "weather" → 准确度: 52/100
          错误类型: 发音不准确
        """
        problem = assessment.problem_words
        if not problem:
            return "✅ 没有明显的发音问题，继续保持！"

        lines = ["⚠️ 需要注意的发音:"]
        for w in problem:
            error_label = _ERROR_TYPE_LABELS.get(w.error_type, w.error_type)
            lines.append(f'• "{w.word}" → 准确度: {w.accuracy_score:.0f}/100')
            lines.append(f"  错误类型: {error_label}")

            # Add phoneme-level detail if available and helpful
            bad_phonemes = [
                p for p in w.phonemes
                if p.accuracy_score < 60 and p.nbt_score != "None"
            ]
            if bad_phonemes:
                phoneme_strs = [
                    f"/{p.phoneme}/ ({p.accuracy_score:.0f})"
                    for p in bad_phonemes[:3]  # Limit to top 3
                ]
                lines.append(f"  问题音素: {', '.join(phoneme_strs)}")

        return "\n".join(lines)

    # ─────────────────────────────────────────────
    # Praise
    # ─────────────────────────────────────────────

    def _format_praise(self, assessment: AssessmentResult) -> str:
        """
        Format praise for good words.
        格式化对发音良好单词的表扬

        Example output:
        🌟 发音很棒的词: "today", "park", "morning"
        """
        good = assessment.good_words
        if not good:
            # Even with no great words, provide encouragement
            if assessment.overall_score > 0:
                return "💡 每次练习都在进步，继续努力！"
            return ""

        # Limit displayed words to keep output clean
        display_words = good[:8]
        word_strs = [f'"{w.word}"' for w in display_words]
        result = f"🌟 发音很棒的词: {', '.join(word_strs)}"

        remaining = len(good) - len(display_words)
        if remaining > 0:
            result += f" 等{remaining + len(display_words)}个单词"

        return result

    # ─────────────────────────────────────────────
    # Tips Selection
    # ─────────────────────────────────────────────

    def _select_tips(self, assessment: AssessmentResult) -> List[str]:
        """
        Select actionable tips based on assessment weaknesses.
        根据评估的薄弱环节选择可操作的提示

        Returns 2-3 relevant tips prioritized by weakest areas.
        """
        # Check if all scores are excellent
        all_scores = [
            assessment.accuracy_score,
            assessment.fluency_score,
            assessment.completeness_score,
            assessment.prosody_score,
        ]
        if all(s >= 90 for s in all_scores):
            return self._TIPS_BY_ISSUE["perfect"][:2]

        # Identify weak areas and prioritize
        weakness_scores = [
            ("low_accuracy", assessment.accuracy_score),
            ("low_fluency", assessment.fluency_score),
            ("low_completeness", assessment.completeness_score),
            ("low_prosody", assessment.prosody_score),
        ]
        # Sort by score ascending — worst areas first
        weakness_scores.sort(key=lambda x: x[1])

        tips: List[str] = []
        seen_categories: set = set()

        for category, score in weakness_scores:
            if score >= 85:
                continue  # Skip strong areas
            if category in seen_categories:
                continue
            seen_categories.add(category)

            # Pick the first tip from this category not already in list
            category_tips = self._TIPS_BY_ISSUE.get(category, [])
            for tip in category_tips:
                if tip not in tips:
                    tips.append(tip)
                    break

            if len(tips) >= 3:
                break

        # If we have fewer than 2 tips, pad with general advice
        if len(tips) < 2:
            general = [
                "坚持每天朗读5分钟，养成练习习惯",
                "先听原文发音，再模仿跟读，效果更好",
            ]
            for g in general:
                if g not in tips:
                    tips.append(g)
                if len(tips) >= 2:
                    break

        return tips

    # ─────────────────────────────────────────────
    # Template-based Summary
    # ─────────────────────────────────────────────

    def _generate_template_summary(
        self,
        assessment: AssessmentResult,
        grade_en: str,
        grade_cn: str,
    ) -> str:
        """
        Generate template-based summary feedback (no LLM required).
        生成基于模板的总结反馈（不需要 LLM）

        Provides context-aware feedback based on score ranges.
        """
        score = assessment.overall_score
        parts: List[str] = []

        # Opening with grade
        parts.append(f"{grade_en} {grade_cn}")
        parts.append("")

        # Score context
        if score >= 90:
            parts.append(
                "你的发音非常出色！准确度、流利度和韵律都表现得很好。"
            )
            if assessment.problem_words:
                parts.append(
                    f"只有 {len(assessment.problem_words)} 个词需要稍加注意。"
                )
            else:
                parts.append("所有单词都发音准确，继续保持这个水平！")
        elif score >= 75:
            parts.append("你的发音整体不错！大部分单词都读得很好。")
            weak_areas = self._identify_weak_areas(assessment)
            if weak_areas:
                parts.append(f"可以重点提升: {', '.join(weak_areas)}。")
        elif score >= 60:
            parts.append("你在朝正确的方向努力！有一些发音点需要加强练习。")
            weak_areas = self._identify_weak_areas(assessment)
            if weak_areas:
                parts.append(f"建议重点关注: {', '.join(weak_areas)}。")
            if assessment.good_words:
                parts.append(
                    f"已经有 {len(assessment.good_words)} 个词发音很棒了！"
                )
        elif score > 0:
            parts.append("别灰心！发音是需要反复练习的技能。")
            parts.append("建议先从短句开始练习，一步步提升。")
            if assessment.good_words:
                parts.append(
                    f"你已经有 {len(assessment.good_words)} 个词读得不错了，"
                    "说明你有很好的基础！"
                )
        else:
            # Score is 0 — likely no speech detected
            parts.append("没有检测到语音内容。请确保麦克风正常工作，并在安静环境中朗读。")

        # Recognized text reminder
        if assessment.recognized_text:
            parts.append("")
            parts.append(f'🎤 识别内容: "{assessment.recognized_text}"')

        return "\n".join(parts)

    def _identify_weak_areas(self, assessment: AssessmentResult) -> List[str]:
        """
        Identify weak scoring areas for feedback.
        识别薄弱环节

        Returns list of Chinese labels for areas below 80.
        """
        weak: List[str] = []
        if assessment.accuracy_score < 80:
            weak.append("准确度")
        if assessment.fluency_score < 80:
            weak.append("流利度")
        if assessment.completeness_score < 80:
            weak.append("完整度")
        if assessment.prosody_score < 80:
            weak.append("韵律")
        return weak

    # ─────────────────────────────────────────────
    # LLM-enhanced Feedback
    # ─────────────────────────────────────────────

    async def _generate_llm_feedback(
        self,
        assessment: AssessmentResult,
        reference_text: str,
    ) -> str:
        """
        Use GPT to generate rich, personalized feedback.
        使用 GPT 生成丰富的个性化反馈

        Sends assessment data as structured context to the LLM and returns
        the generated feedback text.
        """
        if not self.llm_call:
            raise RuntimeError("LLM call function not available")

        # Build structured assessment data for LLM context
        assessment_data = {
            "reference_text": reference_text,
            "recognized_text": assessment.recognized_text,
            "scores": {
                "overall": assessment.overall_score,
                "accuracy": assessment.accuracy_score,
                "fluency": assessment.fluency_score,
                "completeness": assessment.completeness_score,
                "prosody": assessment.prosody_score,
            },
            "problem_words": [
                {
                    "word": w.word,
                    "accuracy": w.accuracy_score,
                    "error_type": w.error_type,
                    "problem_phonemes": [
                        {"phoneme": p.phoneme, "accuracy": p.accuracy_score}
                        for p in w.phonemes
                        if p.accuracy_score < 60
                    ],
                }
                for w in assessment.problem_words[:8]
            ],
            "lowest_words": [
                {
                    "word": w.word,
                    "accuracy": w.accuracy_score,
                    "error_type": w.error_type,
                    "phonemes": [
                        {"phoneme": p.phoneme, "accuracy": p.accuracy_score}
                        for p in w.phonemes[:5]
                    ],
                }
                for w in sorted(
                    assessment.words,
                    key=lambda item: item.accuracy_score,
                )[:5]
            ],
            "good_words": [w.word for w in assessment.good_words[:10]],
            "total_words": len(assessment.words),
        }

        user_prompt = (
            "以下是学生的 Azure Pronunciation Assessment 数据。"
            "请按系统要求生成严格、具体、中英混合的发音反馈。"
            "不要泛泛表扬，要指出可以马上练的发音点。\n\n"
            f"```json\n{json.dumps(assessment_data, ensure_ascii=False, indent=2)}\n```"
        )

        logger.debug("[FeedbackGenerator] Calling LLM for feedback generation")
        result = await self.llm_call(FEEDBACK_SYSTEM_PROMPT, user_prompt)

        if not result or not result.strip():
            raise ValueError("LLM returned empty feedback")

        return result.strip()
