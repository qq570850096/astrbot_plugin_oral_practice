"""
AstrBot 口语练习插件 — 主入口
English Oral Practice Plugin for AstrBot

支持：自由对话、朗读练习、场景练习、单词操练
集成：Azure 发音评估 + AstrBot LLM/STT/TTS 提供商
"""

from __future__ import annotations

import os
import inspect
import time
from typing import Optional

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import astrbot.api.message_components as Comp

from .core.stt_service import STTService
from .core.tts_service import TTSService
from .core.astrbot_services import AstrBotSTTService, AstrBotTTSService
from .core.pronunciation import PronunciationAssessor
from .core.conversation import ConversationEngine
from .core.feedback import FeedbackGenerator
from .core.progress import ProgressTracker
from .core.session import SessionManager, SessionState
from .core.audio_utils import convert_to_wav_pcm, ensure_temp_dir

from .modes.free_talk import FreeTalkMode
from .modes.read_aloud import ReadAloudMode
from .modes.scenario import ScenarioMode
from .modes.word_drill import WordDrillMode


@register(
    "astrbot_plugin_oral_practice",
    "OralPracticeBot",
    "英语口语练习插件 — 支持自由对话、朗读练习、场景练习、单词操练",
    "v0.1.0",
)
class OralPracticePlugin(Star):
    """
    AstrBot 口语练习插件

    通过 /oral 命令进入各种口语练习模式，
    结合 Azure 发音评估提供专业反馈。
    """

    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.config = config or {}
        self.session_manager = SessionManager()
        self._temp_dir = ensure_temp_dir()
        self._db_initialized = False

        # 初始化所有服务
        self._init_services()

        logger.info("🎙️ 口语练习插件已加载")

    # ==================================================================
    # 服务初始化
    # ==================================================================

    def _init_services(self):
        """根据配置初始化所有服务实例"""

        # --- STT: AstrBot provider by default, MiMo direct API as fallback ---
        stt_provider_id = self.config.get("stt_provider_id", "")
        use_astrbot_stt = self.config.get("use_astrbot_stt", True)
        mimo_key = self.config.get("mimo_api_key", "")
        mimo_base = self.config.get("mimo_api_base", "https://api.xiaomimimo.com/v1")

        if use_astrbot_stt:
            self.stt = AstrBotSTTService(
                context=self.context,
                provider_id=stt_provider_id,
            )
        else:
            self.stt = STTService(
                api_key=mimo_key,
                api_base=mimo_base,
                model=self.config.get("mimo_stt_model", "mimo-v2-omni"),
            )

        # --- TTS: AstrBot provider by default, MiMo direct API as fallback ---
        tts_provider_id = self.config.get("tts_provider_id", "")
        use_astrbot_tts = self.config.get("use_astrbot_tts", True)
        if use_astrbot_tts:
            self.tts = AstrBotTTSService(
                context=self.context,
                provider_id=tts_provider_id,
                temp_dir=self._temp_dir,
            )
        else:
            self.tts = TTSService(
                api_key=mimo_key,
                api_base=mimo_base,
                model=self.config.get("mimo_tts_model", "mimo-v2-tts"),
                default_emotion=self.config.get("tts_emotion", "温柔"),
                temp_dir=self._temp_dir,
            )

        # --- Pronunciation: Azure ---
        azure_key = self.config.get("azure_speech_key", "")
        azure_region = self.config.get("azure_speech_region", "eastasia")
        if azure_key:
            try:
                self.pronunciation = PronunciationAssessor(azure_key, azure_region)
                logger.info("✅ Azure 发音评估已配置")
            except ImportError as e:
                self.pronunciation = None
                logger.warning(f"⚠️ Azure SDK 未安装，发音评估功能不可用: {e}")
        else:
            self.pronunciation = None
            logger.warning("⚠️ Azure Speech Key 未配置，发音评估功能不可用")

        # --- Conversation: AstrBot LLM provider ---
        self.conversation = ConversationEngine(
            context=self.context,
            provider_id=self.config.get("llm_provider_id", ""),
        )

        # --- Feedback Generator ---
        async def llm_call(system_prompt: str, user_prompt: str) -> str:
            return await self.conversation.generate([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ])

        self.feedback = FeedbackGenerator(llm_call=llm_call)

        # --- Progress Tracker ---
        db_dir = os.path.join(os.path.dirname(__file__), "data")
        os.makedirs(db_dir, exist_ok=True)
        db_path = os.path.join(db_dir, "user_progress.db")
        self.progress = ProgressTracker(db_path)

    async def _ensure_db_initialized(self):
        """延迟初始化数据库（首次命令时调用）"""
        if self._db_initialized:
            return
        try:
            await self.progress.initialize()
            self._db_initialized = True
        except Exception as e:
            logger.error(f"数据库初始化失败: {e}")

    # ==================================================================
    # 模式工厂
    # ==================================================================

    def _create_mode(self, mode_class, session):
        """创建练习模式实例，注入所有服务"""
        return mode_class(
            session=session,
            stt_service=self.stt,
            tts_service=self.tts,
            conversation_engine=self.conversation,
            pronunciation_assessor=self.pronunciation,
            feedback_generator=self.feedback,
            progress_tracker=self.progress,
        )

    # ==================================================================
    # 命令处理
    # ==================================================================

    @filter.command("oral")
    async def cmd_oral(self, event: AstrMessageEvent):
        """口语练习主命令 /oral [talk|read|scene|drill|level|report|stop]"""
        subcmd, args = self._parse_oral_args(event)

        user_id = self._user_key(event)
        user_name = event.get_sender_name()
        self._bind_event_context(event)

        # 确保数据库已初始化
        await self._ensure_db_initialized()

        # 确保用户会话存在
        session = self.session_manager.get_or_create(user_id, user_name)

        # 确保用户在数据库中
        try:
            await self.progress.get_or_create_user(user_id, user_name)
        except Exception:
            pass

        if not subcmd:
            # 显示主菜单
            yield self._stop(event.plain_result(self._main_menu()))
            return

        # ---------- talk: 自由对话 ----------
        if subcmd == "talk":
            self.session_manager.start_mode(user_id, SessionState.FREE_TALK)
            mode = self._create_mode(FreeTalkMode, session)
            text, audio = await mode.start()
            yield self._stop(self._build_response(event, text, audio))

        # ---------- read: 朗读练习 ----------
        elif subcmd == "read":
            self.session_manager.start_mode(user_id, SessionState.READ_ALOUD)
            mode = self._create_mode(ReadAloudMode, session)
            text, audio = await mode.start()
            yield self._stop(self._build_response(event, text, audio))

        # ---------- scene: 场景练习 ----------
        elif subcmd in ("scene", "scenario"):
            scenario_name = args[0] if args else None
            mode_data = {"scenario": scenario_name} if scenario_name else {}
            self.session_manager.start_mode(
                user_id, SessionState.SCENARIO, mode_data
            )
            mode = self._create_mode(ScenarioMode, session)
            text, audio = await mode.start()
            yield self._stop(self._build_response(event, text, audio))

        # ---------- drill: 单词操练 ----------
        elif subcmd == "drill":
            self.session_manager.start_mode(user_id, SessionState.WORD_DRILL)
            mode = self._create_mode(WordDrillMode, session)
            text, audio = await mode.start()
            yield self._stop(self._build_response(event, text, audio))

        # ---------- level: 设置难度 ----------
        elif subcmd == "level":
            level = args[0].upper() if args else ""
            if level in ("A1", "A2", "B1", "B2"):
                session.mode_data["level"] = level
                try:
                    await self.progress.update_user_level(user_id, level)
                except Exception:
                    pass
                yield self._stop(event.plain_result(
                    f"✅ 难度等级已设置为 CEFR {level}\n\n"
                    "此设置将在下次开始练习时生效~"
                ))
            else:
                yield self._stop(event.plain_result(
                    "❌ 无效等级\n\n"
                    "请选择: A1, A2, B1, B2\n"
                    "例如: /oral level B1"
                ))

        # ---------- report: 练习报告 ----------
        elif subcmd == "report":
            try:
                report = await self.progress.generate_report(user_id)
            except Exception as e:
                report = f"📊 获取报告失败: {e}"
            yield self._stop(event.plain_result(report))

        # ---------- stop: 结束练习 ----------
        elif subcmd == "stop":
            if self.session_manager.is_active(user_id):
                # 记录会话
                start_time = session.mode_data.get("start_time", time.time())
                duration = int(time.time() - start_time)
                scores = session.mode_data.get("scores", [])
                avg_score = sum(scores) / len(scores) if scores else 0

                try:
                    await self.progress.record_session(
                        user_id=user_id,
                        mode=session.state.value,
                        duration_seconds=duration,
                        avg_accuracy=avg_score,
                    )
                except Exception:
                    pass

                self.session_manager.end_mode(user_id)
                yield self._stop(event.plain_result(
                    "✅ 练习已结束，辛苦了！👏\n\n"
                    "📊 发送 /oral report 查看你的练习报告\n"
                    "🎙️ 发送 /oral 查看主菜单"
                ))
            else:
                yield self._stop(event.plain_result("当前没有进行中的练习~"))

        # ---------- help: 帮助 ----------
        elif subcmd == "help":
            yield self._stop(event.plain_result(self._main_menu()))

        else:
            yield self._stop(event.plain_result(
                f"❓ 未知命令: {subcmd}\n\n" + self._main_menu()
            ))

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def handle_session_message(self, event: AstrMessageEvent):
        """
        处理活跃会话中的非命令消息（语音和文本）

        仅当用户处于活跃练习会话时才处理
        """
        if self._looks_like_command(event.message_str):
            return

        user_id = self._user_key(event)
        self._bind_event_context(event)

        # 检查是否有活跃会话
        if not self.session_manager.is_active(user_id):
            return  # 不在会话中，让其他插件处理

        session = self.session_manager.get(user_id)
        if not session:
            return

        # 获取当前模式处理器
        mode = self._get_mode_for_session(session)
        if not mode:
            return

        # 检查是否包含语音消息。QQ/微信语音通常是命令后的独立消息。
        audio_path = await self._extract_audio(event)

        try:
            if audio_path:
                # 语音消息 → 转换为 WAV 后处理
                wav_path = os.path.join(
                    self._temp_dir,
                    f"{hash(user_id)}_{int(time.time())}_input.wav",
                )
                await convert_to_wav_pcm(audio_path, wav_path)
                text, audio = await mode.handle_voice(wav_path)

                # 清理临时文件
                try:
                    os.remove(wav_path)
                except Exception:
                    pass
            else:
                # 文本消息
                text, audio = await mode.handle_text(event.message_str)
        except Exception as e:
            logger.error(f"处理消息失败: {e}", exc_info=True)
            text = f"😅 处理出了点问题: {str(e)[:100]}\n请再试一次~"
            audio = None

        if text:
            yield self._stop(self._build_response(event, text, audio))

    # ==================================================================
    # 辅助方法
    # ==================================================================

    def _get_mode_for_session(self, session):
        """根据会话状态获取对应的模式实例"""
        mode_map = {
            SessionState.FREE_TALK: FreeTalkMode,
            SessionState.READ_ALOUD: ReadAloudMode,
            SessionState.SCENARIO: ScenarioMode,
            SessionState.WORD_DRILL: WordDrillMode,
        }
        mode_class = mode_map.get(session.state)
        if mode_class:
            return self._create_mode(mode_class, session)
        return None

    def _parse_oral_args(self, event: AstrMessageEvent) -> tuple[str, list[str]]:
        """Parse /oral args from AstrBot parsed params or raw message text."""
        parts: list[str] = []
        extra = getattr(event, "extra", None)
        parsed_params = None
        if isinstance(extra, dict):
            parsed_params = extra.get("parsed_params")

        if parsed_params:
            if isinstance(parsed_params, str):
                parts = parsed_params.split()
            else:
                parts = [str(part) for part in parsed_params if str(part).strip()]
        else:
            raw = (event.message_str or "").strip()
            parts = raw.split()

        if parts and parts[0].lstrip("/").lower() == "oral":
            parts = parts[1:]

        subcmd = parts[0].lower() if parts else ""
        args = parts[1:] if len(parts) > 1 else []
        return subcmd, args

    def _user_key(self, event: AstrMessageEvent) -> str:
        """Build a per-sender session key so group members do not share state."""
        sender_id = ""
        try:
            sender_id = event.get_sender_id() or ""
        except Exception:
            pass

        if not sender_id:
            sender = getattr(getattr(event, "message_obj", None), "sender", None)
            raw_sender_id = getattr(sender, "user_id", "")
            sender_id = str(raw_sender_id) if raw_sender_id else ""

        try:
            session_id = event.unified_msg_origin or event.get_session_id()
        except Exception:
            session_id = event.unified_msg_origin

        session_id = str(session_id or "")
        return f"{session_id}:{sender_id}" if sender_id else session_id

    @staticmethod
    def _looks_like_command(message: str) -> bool:
        raw = (message or "").strip()
        if not raw:
            return False
        lowered = raw.lower()
        return lowered.startswith("/") or lowered == "oral" or lowered.startswith("oral ")

    @staticmethod
    def _stop(result):
        if hasattr(result, "stop_event"):
            return result.stop_event()
        return result

    async def _extract_audio(self, event: AstrMessageEvent) -> Optional[str]:
        """从消息中提取语音文件路径"""
        try:
            if hasattr(event, "get_messages"):
                messages = event.get_messages()
            elif hasattr(event, "message_obj") and event.message_obj:
                messages = event.message_obj.message
            else:
                messages = []

            for comp in messages:
                if not self._is_record_component(comp):
                    continue

                logger.info(
                    "[OralPractice] 检测到语音组件: %s",
                    self._component_debug_info(comp),
                )

                path = await self._record_to_file_path(comp)
                if path:
                    logger.info("[OralPractice] 语音文件路径: %s", path)
                    return str(path)

                logger.warning(
                    "[OralPractice] 语音组件未能转换为文件路径: %s",
                    self._component_debug_info(comp),
                )
        except Exception as e:
            logger.debug(f"提取音频失败: {e}", exc_info=True)
        return None

    @staticmethod
    def _is_record_component(comp) -> bool:
        """兼容 AstrBot 不同适配器的 Record 组件表示。"""
        if isinstance(comp, Comp.Record):
            return True

        comp_type = getattr(comp, "type", None)
        type_name = getattr(comp_type, "name", "")
        type_value = getattr(comp_type, "value", comp_type)
        type_texts = {
            str(type_name).lower(),
            str(type_value).lower(),
            str(comp_type).lower(),
            comp.__class__.__name__.lower(),
        }
        return bool(type_texts & {"record", "componenttype.record"})

    async def _record_to_file_path(self, comp) -> Optional[str]:
        if hasattr(comp, "convert_to_file_path"):
            path = comp.convert_to_file_path()
            if inspect.isawaitable(path):
                path = await path
            if path:
                return str(path)

        for attr in ("file", "path", "url"):
            path = getattr(comp, attr, None)
            if path:
                return str(path)

        return None

    @staticmethod
    def _component_debug_info(comp) -> str:
        fields = {
            "class": comp.__class__.__name__,
            "type": str(getattr(comp, "type", "")),
            "file": bool(getattr(comp, "file", None)),
            "path": bool(getattr(comp, "path", None)),
            "url": bool(getattr(comp, "url", None)),
            "convert_to_file_path": hasattr(comp, "convert_to_file_path"),
        }
        return ", ".join(f"{key}={value}" for key, value in fields.items())

    def _bind_event_context(self, event: AstrMessageEvent) -> None:
        umo = event.unified_msg_origin
        self.conversation.umo = umo
        for service in (self.stt, self.tts):
            if hasattr(service, "umo"):
                service.umo = umo

    def _build_response(self, event, text: str, audio: Optional[bytes] = None):
        """构建包含文本和可选语音的响应"""
        chain = [Comp.Plain(text)]

        if audio and isinstance(audio, bytes):
            try:
                audio_filename = f"resp_{hash(text) & 0xFFFFFFFF}_{int(time.time())}.wav"
                audio_path = os.path.join(self._temp_dir, audio_filename)
                with open(audio_path, "wb") as f:
                    f.write(audio)
                chain.append(Comp.Record(file=audio_path, url=audio_path))
            except Exception as e:
                logger.warning(f"保存响应音频失败: {e}")

        return event.chain_result(chain)

    @staticmethod
    def _main_menu() -> str:
        """生成主菜单文本"""
        return (
            "🎓 英语口语练习助手\n"
            "━━━━━━━━━━━━━━━━━━━\n\n"
            "📚 练习模式:\n"
            "  /oral talk    — 🗣️ 自由对话 (与 AI 伙伴聊天)\n"
            "  /oral read    — 📖 朗读练习 (朗读句子+发音评估)\n"
            "  /oral scene   — 🎭 场景练习 (角色扮演情景对话)\n"
            "  /oral drill   — 🔤 单词操练 (逐词发音练习)\n\n"
            "⚙️ 设置:\n"
            "  /oral level <A1/A2/B1/B2>  — 设置难度等级\n"
            "  /oral report  — 📊 查看练习报告\n"
            "  /oral stop    — ⏹️ 结束当前练习\n\n"
            "💡 提示: 在练习中直接发送语音消息即可开始!\n"
            "📌 首次使用请在 AstrBot WebUI 中选择模型提供商"
        )

    async def terminate(self):
        """插件卸载清理"""
        logger.info("🎙️ 口语练习插件正在关闭...")
        try:
            await self.progress.close()
        except Exception:
            pass
