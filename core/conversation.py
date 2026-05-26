"""
Conversation Engine backed by AstrBot's configured LLM providers.
对话引擎：优先使用 AstrBot WebUI 中已配置的大语言模型提供商。
"""

from __future__ import annotations

from astrbot.api import logger


class ConversationEngine:
    """
    Thin wrapper around AstrBot's LLM provider API.

    The plugin keeps its own short conversation history, but delegates actual
    generation to the chat provider selected in AstrBot WebUI.
    """

    def __init__(self, context=None, provider_id: str = "", umo: str = ""):
        self.context = context
        self.provider_id = (provider_id or "").strip()
        self.umo = umo

    @property
    def available(self) -> bool:
        """Whether AstrBot LLM access is available."""
        return self.context is not None

    async def generate(
        self,
        messages: list[dict],
        temperature: float = 0.8,
        max_tokens: int = 500,
    ) -> str:
        """
        Generate a response using AstrBot's configured chat provider.

        ``temperature`` and ``max_tokens`` are currently advisory. AstrBot
        provider-level model settings remain the source of truth.
        """
        if not self.context:
            raise RuntimeError("[Conversation] AstrBot Context 不可用")

        provider_id = await self._resolve_provider_id()
        if not provider_id:
            raise RuntimeError("[Conversation] AstrBot LLM 提供商未配置")

        prompt, system_prompt = self._messages_to_prompt(messages)

        try:
            kwargs = {
                "chat_provider_id": provider_id,
                "prompt": prompt,
            }
            if system_prompt:
                kwargs["system_prompt"] = system_prompt

            llm_resp = await self.context.llm_generate(**kwargs)
        except TypeError:
            # Older AstrBot builds may not accept system_prompt here.
            full_prompt = prompt
            if system_prompt:
                full_prompt = f"{system_prompt}\n\n{prompt}"
            llm_resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=full_prompt,
            )
        except Exception as exc:
            raise RuntimeError(f"[Conversation] AstrBot LLM 调用失败: {exc}") from exc

        content = getattr(llm_resp, "completion_text", "") or str(llm_resp or "")
        if not content.strip():
            raise ValueError("[Conversation] AstrBot LLM 返回了空回复")

        logger.debug(
            f"[Conversation] AstrBot provider={provider_id or 'default'} "
            f"reply={content[:100]}{'...' if len(content) > 100 else ''}"
        )
        return content.strip()

    async def generate_response(
        self,
        user_text: str,
        conversation_history: list[dict],
        system_prompt: str,
    ) -> str:
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(conversation_history[-20:] if conversation_history else [])
        messages.append({"role": "user", "content": user_text})
        return await self.generate(messages, temperature=0.8, max_tokens=500)

    async def generate_feedback(
        self,
        assessment_json: str,
        reference_text: str,
        system_prompt: str,
    ) -> str:
        user_prompt = (
            f"## 参考文本\n{reference_text}\n\n"
            f"## 发音评估结果 (JSON)\n```json\n{assessment_json}\n```\n\n"
            "请根据以上评估数据生成反馈报告。"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        return await self.generate(messages, temperature=0.6, max_tokens=800)

    async def generate_sentence(
        self,
        level: str = "B1",
        topic: str = "daily life",
        count: int = 1,
    ) -> str:
        level_params = {
            "A1": {"min_words": 4, "max_words": 8},
            "A2": {"min_words": 6, "max_words": 12},
            "B1": {"min_words": 10, "max_words": 18},
            "B2": {"min_words": 14, "max_words": 25},
        }
        params = level_params.get(level, level_params["B1"])

        prompt = (
            f"Generate {count} natural English sentence(s) for oral reading practice.\n"
            f"CEFR Level: {level}\n"
            f"Topic: {topic}\n"
            f"Length: {params['min_words']}-{params['max_words']} words each.\n"
            "Include some pronunciation challenges (th/θ, r/l, word stress, linking).\n\n"
            "Return ONLY the sentence(s), one per line. No numbering, no quotes, "
            "no explanation."
        )

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a helpful English language assistant. "
                    "Generate natural, spoken-style English sentences."
                ),
            },
            {"role": "user", "content": prompt},
        ]

        result = await self.generate(messages, temperature=0.9, max_tokens=200)
        if count == 1:
            lines = [line.strip() for line in result.splitlines() if line.strip()]
            return lines[0] if lines else result.strip()
        return result.strip()

    async def generate_scenario_response(
        self,
        user_text: str,
        conversation_history: list[dict],
        scenario_prompt: str,
    ) -> str:
        return await self.generate_response(
            user_text, conversation_history, scenario_prompt
        )

    async def _resolve_provider_id(self) -> str:
        if self.provider_id:
            return self.provider_id

        if self.umo and hasattr(self.context, "get_current_chat_provider_id"):
            try:
                return await self.context.get_current_chat_provider_id(umo=self.umo)
            except TypeError:
                return await self.context.get_current_chat_provider_id(self.umo)
            except Exception as exc:
                logger.debug(f"[Conversation] 获取当前会话 provider 失败: {exc}")

        if hasattr(self.context, "get_using_provider"):
            try:
                provider = self.context.get_using_provider(self.umo or None)
            except TypeError:
                provider = self.context.get_using_provider()
            except Exception as exc:
                logger.debug(f"[Conversation] 获取默认 provider 失败: {exc}")
                provider = None

            if provider and hasattr(provider, "meta"):
                try:
                    return provider.meta().id
                except Exception as exc:
                    logger.debug(f"[Conversation] 读取 provider id 失败: {exc}")

        return ""

    @staticmethod
    def _messages_to_prompt(messages: list[dict]) -> tuple[str, str]:
        system_parts: list[str] = []
        prompt_parts: list[str] = []

        for message in messages:
            role = message.get("role", "user")
            content = str(message.get("content", "")).strip()
            if not content:
                continue
            if role == "system":
                system_parts.append(content)
            elif role == "assistant":
                prompt_parts.append(f"Assistant: {content}")
            else:
                prompt_parts.append(f"User: {content}")

        return "\n\n".join(prompt_parts), "\n\n".join(system_parts)
