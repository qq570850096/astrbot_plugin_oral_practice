"""
Scenario Mode — 场景练习模式
角色扮演场景对话，结合发音评估
"""

from __future__ import annotations

from typing import Optional

from astrbot.api import logger

from .base_mode import BaseMode
from ..prompts.tutor_system import SCENARIO_SYSTEM_PROMPT


class ScenarioMode(BaseMode):
    """
    场景练习模式

    用户在预设场景中进行角色扮演对话，
    结合发音评估获得综合反馈。

    流程：选择场景 → 用户语音参与 → 评估 + 推进剧情 → 总结报告
    """

    BUILT_IN_SCENARIOS: dict[str, dict] = {
        "restaurant": {
            "name": "🍽️ 在餐厅点餐",
            "name_en": "Ordering at a Restaurant",
            "role": "waiter/waitress",
            "learner_role": "a customer ordering food",
            "setting": "A casual dining restaurant",
            "opening": "Welcome to The Golden Plate! Table for how many?",
            "hint": "告诉服务员你要几个人的桌子",
            "steps": [
                {"bot": "Welcome to The Golden Plate! Table for how many?",
                 "hint": "告诉服务员人数"},
                {"bot": "Right this way! Here's the menu. Would you like something to drink first?",
                 "hint": "点一杯饮料"},
                {"bot": "Great choice! Are you ready to order your main course?",
                 "hint": "点主菜"},
                {"bot": "Excellent! Would you like any dessert today?",
                 "hint": "决定是否要甜点"},
                {"bot": "Here's your bill. How would you like to pay?",
                 "hint": "选择付款方式"},
            ],
        },
        "airport": {
            "name": "✈️ 机场值机",
            "name_en": "Airport Check-in",
            "role": "airline check-in staff",
            "learner_role": "a passenger checking in for a flight",
            "setting": "An airport check-in counter",
            "opening": "Good morning! May I see your passport and booking confirmation?",
            "hint": "出示你的证件",
            "steps": [
                {"bot": "Good morning! May I see your passport and booking confirmation?",
                 "hint": "出示证件"},
                {"bot": "Thank you. Would you prefer a window or aisle seat?",
                 "hint": "选择座位偏好"},
                {"bot": "Do you have any luggage to check in?",
                 "hint": "说明行李情况"},
                {"bot": "Your flight departs from Gate B12. Boarding starts at 2:30 PM. Is there anything else I can help with?",
                 "hint": "询问其他信息或道谢"},
            ],
        },
        "interview": {
            "name": "💼 工作面试",
            "name_en": "Job Interview",
            "role": "interviewer at a tech company",
            "learner_role": "a job candidate",
            "setting": "A meeting room at a tech company",
            "opening": "Good morning! Thank you for coming in today. Please, have a seat. Could you start by telling me a little about yourself?",
            "hint": "做自我介绍",
            "steps": [
                {"bot": "Thank you for coming. Could you tell me a little about yourself?",
                 "hint": "自我介绍"},
                {"bot": "Interesting! What attracted you to this position?",
                 "hint": "说明申请原因"},
                {"bot": "Can you describe a challenging project you've worked on?",
                 "hint": "描述一个挑战性项目"},
                {"bot": "Where do you see yourself in five years?",
                 "hint": "描述职业规划"},
                {"bot": "Do you have any questions for us?",
                 "hint": "向面试官提问"},
            ],
        },
        "shopping": {
            "name": "🛍️ 商场购物",
            "name_en": "Shopping at a Store",
            "role": "shop assistant at a clothing store",
            "learner_role": "a customer looking for clothes",
            "setting": "A clothing store in a shopping mall",
            "opening": "Hi there! Welcome to our store. Is there anything I can help you find today?",
            "hint": "告诉店员你想买什么",
            "steps": [
                {"bot": "Hi! Is there anything I can help you find today?",
                 "hint": "说明你想买的东西"},
                {"bot": "Sure! What size are you looking for?",
                 "hint": "说明尺码"},
                {"bot": "Here are some options. Would you like to try them on?",
                 "hint": "决定是否试穿"},
                {"bot": "That looks great on you! Anything else you'd like?",
                 "hint": "决定是否还需要其他"},
                {"bot": "Your total comes to forty-five dollars. Cash or card?",
                 "hint": "选择付款方式"},
            ],
        },
        "hotel": {
            "name": "🏨 酒店入住",
            "name_en": "Hotel Check-in",
            "role": "hotel receptionist",
            "learner_role": "a guest checking in",
            "setting": "A hotel front desk",
            "opening": "Good evening! Welcome to the Grand Hotel. Do you have a reservation?",
            "hint": "确认你的预订",
            "steps": [
                {"bot": "Good evening! Welcome to the Grand Hotel. Do you have a reservation?",
                 "hint": "确认预订信息"},
                {"bot": "I found your reservation. Could I see some ID, please?",
                 "hint": "出示证件"},
                {"bot": "Your room is on the eighth floor. Would you prefer a room with a city view or garden view?",
                 "hint": "选择房间视野"},
                {"bot": "Breakfast is served from 7 to 10 AM in the restaurant on the ground floor. Is there anything else you need?",
                 "hint": "询问 WiFi、健身房等设施信息"},
            ],
        },
    }

    async def start(self) -> tuple[str, Optional[bytes]]:
        """启动场景练习模式"""
        logger.info(f"{self._log_prefix()} 场景练习模式启动")

        scenario_key = self.session.mode_data.get("scenario")

        if not scenario_key or scenario_key not in self.BUILT_IN_SCENARIOS:
            # 显示场景列表
            return self._list_scenarios(), None

        # 初始化场景
        scenario = self.BUILT_IN_SCENARIOS[scenario_key]
        self.session.scenario_step = 0
        self.session.mode_data["scenario_key"] = scenario_key
        self.session.mode_data["scores"] = []
        self.session.conversation_history = []

        first_step = scenario["steps"][0]
        bot_line = first_step["bot"]
        hint = first_step["hint"]

        welcome = (
            f"🎭 场景练习: {scenario['name']}\n"
            f"📍 {scenario['name_en']}\n"
            "━━━━━━━━━━━━━━━━━━━\n\n"
            f"[{scenario['role'].title()}]\n"
            f"💬 \"{bot_line}\"\n\n"
            f"💡 提示: {hint}\n\n"
            "请用语音回答~ 🎤"
        )

        # 添加到对话历史
        self.session.conversation_history.append({
            "role": "assistant",
            "content": bot_line,
        })

        audio = await self._try_tts(bot_line)
        return welcome, audio

    async def handle_voice(self, audio_path: str) -> tuple[str, Optional[bytes]]:
        """处理场景中的语音输入"""
        scenario_key = self.session.mode_data.get("scenario_key")

        if not scenario_key:
            # 可能是在选择场景
            try:
                result = await self.stt_service.transcribe(audio_path)
                return await self.handle_text(result.text)
            except Exception:
                return "请输入场景名称选择场景~", None

        scenario = self.BUILT_IN_SCENARIOS[scenario_key]

        # 1. STT 转写
        try:
            transcribe_result = await self.stt_service.transcribe(audio_path)
            user_text = transcribe_result.text
        except Exception as e:
            logger.error(f"{self._log_prefix()} STT 失败: {e}")
            return "😅 语音识别出了问题，请再试一次~", None

        # 2. 发音评估（如果可用）
        score_text = ""
        if self.pronunciation_assessor:
            try:
                assessment = await self.pronunciation_assessor.assess(
                    audio_path=audio_path,
                    reference_text=user_text,  # 自由发言用识别文本作为参考
                    language="en-US",
                )
                score = assessment.overall_score
                self.session.mode_data.setdefault("scores", []).append(score)

                # 简洁评分
                if score >= 85:
                    score_text = f"📊 发音: {score:.0f}/100 ⭐ "
                elif score >= 70:
                    score_text = f"📊 发音: {score:.0f}/100 👍 "
                else:
                    score_text = f"📊 发音: {score:.0f}/100 💪 "

                # 记录错误
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
            except Exception as e:
                logger.warning(f"{self._log_prefix()} 评估失败: {e}")

        # 3. 推进场景
        self.session.scenario_step += 1
        step = self.session.scenario_step
        total_steps = len(scenario["steps"])

        # 添加用户消息到历史
        self.session.conversation_history.append({
            "role": "user",
            "content": user_text,
        })

        if step >= total_steps:
            # 场景结束
            return await self._finish_scenario(user_text, score_text, scenario)

        # 4. 获取下一步
        next_step = scenario["steps"][step]

        # 尝试用 LLM 生成更自然的回复
        bot_line = await self._get_bot_response(
            user_text, scenario, next_step
        )

        hint = next_step.get("hint", "")

        # 添加到对话历史
        self.session.conversation_history.append({
            "role": "assistant",
            "content": bot_line,
        })

        response = (
            f"📝 你说: \"{user_text}\"\n"
            f"{score_text}\n\n"
            f"[{scenario['role'].title()}]\n"
            f"💬 \"{bot_line}\"\n\n"
            f"💡 提示: {hint}\n\n"
            f"请继续~ ({step + 1}/{total_steps}) 🎤"
        )

        audio = await self._try_tts(bot_line)
        return response, audio

    async def handle_text(self, text: str) -> tuple[str, Optional[bytes]]:
        """处理文本输入"""
        text_lower = text.strip().lower()

        # 选择场景
        for key, sc in self.BUILT_IN_SCENARIOS.items():
            if text_lower in (key, sc["name_en"].lower()):
                self.session.mode_data["scenario"] = key
                return await self.start()

        # 数字选择
        try:
            idx = int(text_lower) - 1
            keys = list(self.BUILT_IN_SCENARIOS.keys())
            if 0 <= idx < len(keys):
                self.session.mode_data["scenario"] = keys[idx]
                return await self.start()
        except ValueError:
            pass

        # 如果已在场景中，作为文本对话处理
        if self.session.mode_data.get("scenario_key"):
            # 模拟语音处理但跳过评估
            scenario = self.BUILT_IN_SCENARIOS[self.session.mode_data["scenario_key"]]
            self.session.scenario_step += 1
            step = self.session.scenario_step
            total_steps = len(scenario["steps"])

            self.session.conversation_history.append({
                "role": "user", "content": text,
            })

            if step >= total_steps:
                return await self._finish_scenario(text, "", scenario)

            next_step = scenario["steps"][step]
            bot_line = await self._get_bot_response(text, scenario, next_step)

            self.session.conversation_history.append({
                "role": "assistant", "content": bot_line,
            })

            response = (
                f"[{scenario['role'].title()}]\n"
                f"💬 \"{bot_line}\"\n\n"
                f"💡 提示: {next_step.get('hint', '')}\n\n"
                f"请继续~ ({step + 1}/{total_steps}) 🎤\n"
                "💡 建议发送语音练习口语哦~"
            )
            audio = await self._try_tts(bot_line)
            return response, audio

        return self._list_scenarios(), None

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _list_scenarios(self) -> str:
        """列出可用场景"""
        lines = [
            "🎭 场景练习模式",
            "━━━━━━━━━━━━━━━━━━━",
            "",
            "请选择一个场景（输入编号或名称）：",
            "",
        ]
        for i, (key, sc) in enumerate(self.BUILT_IN_SCENARIOS.items(), 1):
            lines.append(f"  {i}. {sc['name']}  ({sc['name_en']})")

        lines.extend([
            "",
            "💡 例如: 输入 1 或 restaurant",
            "   也可以: /oral scene restaurant",
        ])
        return "\n".join(lines)

    async def _get_bot_response(
        self, user_text: str, scenario: dict, next_step: dict
    ) -> str:
        """生成场景角色回复（优先 LLM，降级到脚本）"""
        if self.conversation_engine and self.conversation_engine.available:
            try:
                prompt = SCENARIO_SYSTEM_PROMPT.format(
                    role_name=scenario["role"],
                    scenario_description=scenario["name_en"],
                    setting=scenario["setting"],
                    learner_role=scenario["learner_role"],
                )
                response = await self.conversation_engine.generate_scenario_response(
                    user_text=user_text,
                    conversation_history=self.session.conversation_history[:-1],
                    scenario_prompt=prompt,
                )
                # 检查是否包含 [SCENARIO_END]
                if "[SCENARIO_END]" not in response:
                    return response
                # 如果 LLM 提前结束，使用脚本
            except Exception as e:
                logger.debug(f"{self._log_prefix()} LLM 场景回复失败: {e}")

        # 降级到脚本
        return next_step["bot"]

    async def _finish_scenario(
        self, last_text: str, score_text: str, scenario: dict
    ) -> tuple[str, Optional[bytes]]:
        """场景结束，生成总结"""
        scores = self.session.mode_data.get("scores", [])
        avg_score = sum(scores) / len(scores) if scores else 0

        lines = [
            f"📝 你说: \"{last_text}\"",
            score_text,
            "",
            "🎉 场景练习完成！",
            f"🎭 {scenario['name']}",
            "━━━━━━━━━━━━━━━━━━━",
        ]

        if scores:
            bar = "█" * round(avg_score / 10) + "░" * (10 - round(avg_score / 10))
            lines.extend([
                "",
                f"📊 平均发音评分: {avg_score:.0f}/100  {bar}",
                f"📝 完成对话轮次: {len(scores)} 轮",
            ])

            if avg_score >= 85:
                lines.append("\n⭐ 太棒了！你在这个场景中表现出色！")
            elif avg_score >= 70:
                lines.append("\n👍 做得不错！多练习会更流畅~")
            else:
                lines.append("\n💪 继续加油！建议重新挑战这个场景~")

        lines.extend([
            "",
            "💡 可以:",
            "  • 重新挑战: /oral scene " + self.session.mode_data.get("scenario_key", ""),
            "  • 选择新场景: /oral scene",
            "  • 结束练习: /oral stop",
        ])

        # 记录会话
        if self.progress_tracker:
            try:
                await self.progress_tracker.record_session(
                    user_id=self.session.user_id,
                    mode="scenario",
                    duration_seconds=0,
                    avg_accuracy=avg_score,
                    words_practiced=len(scores),
                )
            except Exception:
                pass

        return "\n".join(lines), None

    async def _try_tts(self, text: str) -> Optional[bytes]:
        """尝试 TTS（优雅降级）"""
        if not self.tts_service or not self.tts_service.available:
            return None
        try:
            result = await self.tts_service.synthesize(text, emotion="neutral")
            return result.audio_data
        except Exception as e:
            logger.warning(f"{self._log_prefix()} TTS 失败: {e}")
            return None
