"""
Conversation Engine — GPT 5.5 对话引擎
管理对话上下文，通过 OpenAI 兼容 API 调用 GPT 5.5
"""

from __future__ import annotations

import asyncio
import json
from typing import Optional

import aiohttp
from astrbot.api import logger


class ConversationEngine:
    """
    GPT 5.5 对话引擎

    通过 OpenAI 兼容的 /chat/completions API 调用大语言模型，
    管理对话上下文并生成回复。
    """

    def __init__(
        self,
        api_key: str = "",
        api_base: str = "https://api.openai.com/v1",
        model: str = "gpt-5.5",
        context=None,
        timeout: int = 30,
    ):
        """
        初始化对话引擎

        Args:
            api_key:  GPT API Key
            api_base: API Base URL (须以 /v1 结尾)
            model:    模型名称
            context:  AstrBot Context（备用，用于内置 LLM 调用）
            timeout:  请求超时秒数
        """
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = model
        self.context = context
        self.timeout = timeout

    @property
    def available(self) -> bool:
        """服务是否可用"""
        return bool(self.api_key)

    # ------------------------------------------------------------------
    # 核心 API 调用
    # ------------------------------------------------------------------

    async def generate(
        self,
        messages: list[dict],
        temperature: float = 0.8,
        max_tokens: int = 500,
    ) -> str:
        """
        调用 GPT 5.5 生成回复

        Args:
            messages: 消息列表 [{"role": "system"/"user"/"assistant", "content": "..."}]
            temperature: 创造性参数 (0.0-2.0)
            max_tokens: 最大回复长度

        Returns:
            生成的文本回复

        Raises:
            RuntimeError: 网络或认证错误
            ValueError: 响应格式异常
        """
        if not self.api_key:
            raise RuntimeError("[Conversation] GPT API Key 未配置")

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        url = f"{self.api_base}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        try:
            client_timeout = aiohttp.ClientTimeout(total=self.timeout)
            async with aiohttp.ClientSession(timeout=client_timeout) as session:
                logger.debug(
                    f"[Conversation] POST {url} model={self.model} "
                    f"messages={len(messages)} temp={temperature}"
                )

                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status == 401:
                        raise RuntimeError(
                            "[Conversation] GPT API Key 无效或已过期，请检查配置"
                        )
                    elif resp.status == 429:
                        raise RuntimeError(
                            "[Conversation] GPT API 请求频率超限，请稍后重试"
                        )
                    elif resp.status >= 500:
                        raise RuntimeError(
                            f"[Conversation] GPT 服务器错误 (HTTP {resp.status})"
                        )
                    elif resp.status != 200:
                        body = await resp.text()
                        raise RuntimeError(
                            f"[Conversation] GPT API 错误 (HTTP {resp.status}): "
                            f"{body[:300]}"
                        )
                    data = await resp.json()

        except aiohttp.ClientError as exc:
            raise RuntimeError(
                f"[Conversation] 网络请求失败: {exc}"
            ) from exc
        except asyncio.TimeoutError as exc:
            raise RuntimeError(
                f"[Conversation] 请求超时 ({self.timeout}秒)"
            ) from exc

        # 解析响应
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            logger.error(f"[Conversation] 响应格式异常: {data}")
            raise ValueError(
                f"[Conversation] 响应解析失败: {exc}"
            ) from exc

        if not content or not content.strip():
            raise ValueError("[Conversation] GPT 返回了空回复")

        logger.debug(
            f"[Conversation] 回复 ({len(content)} chars): "
            f"{content[:100]}{'...' if len(content) > 100 else ''}"
        )
        return content.strip()

    # ------------------------------------------------------------------
    # 便捷方法
    # ------------------------------------------------------------------

    async def generate_response(
        self,
        user_text: str,
        conversation_history: list[dict],
        system_prompt: str,
    ) -> str:
        """
        生成对话回复

        基于系统 prompt + 对话历史 + 用户输入，生成自然对话回复

        Args:
            user_text: 用户最新输入
            conversation_history: 对话历史 [{"role": ..., "content": ...}]
            system_prompt: 系统 prompt

        Returns:
            生成的对话回复
        """
        messages = [{"role": "system", "content": system_prompt}]

        # 添加对话历史（取最近 20 条，避免 token 溢出）
        recent_history = conversation_history[-20:] if conversation_history else []
        messages.extend(recent_history)

        # 添加当前用户输入
        messages.append({"role": "user", "content": user_text})

        return await self.generate(messages, temperature=0.8, max_tokens=500)

    async def generate_feedback(
        self,
        assessment_json: str,
        reference_text: str,
        system_prompt: str,
    ) -> str:
        """
        根据发音评估结果生成人性化反馈

        Args:
            assessment_json: Azure 评估结果 JSON 字符串
            reference_text: 朗读参考文本
            system_prompt: 反馈系统 prompt

        Returns:
            人性化的反馈报告文本
        """
        user_prompt = (
            f"## 参考文本\n{reference_text}\n\n"
            f"## 发音评估结果 (JSON)\n```json\n{assessment_json}\n```\n\n"
            f"请根据以上评估数据生成反馈报告。"
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
        """
        生成指定 CEFR 等级的练习句子

        Args:
            level: CEFR 等级 (A1/A2/B1/B2)
            topic: 主题
            count: 生成数量

        Returns:
            生成的练习句子（或 JSON 数组字符串）
        """
        # 难度参数
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
            f"Include some pronunciation challenges (th/θ, r/l, word stress, linking).\n\n"
            f"Return ONLY the sentence(s), one per line. No numbering, no quotes, "
            f"no explanation."
        )

        messages = [
            {
                "role": "system",
                "content": "You are a helpful English language assistant. "
                "Generate natural, spoken-style English sentences.",
            },
            {"role": "user", "content": prompt},
        ]

        result = await self.generate(messages, temperature=0.9, max_tokens=200)

        # 如果只需要一个句子，返回第一行
        if count == 1:
            lines = [l.strip() for l in result.strip().split("\n") if l.strip()]
            return lines[0] if lines else result.strip()

        return result.strip()

    async def generate_scenario_response(
        self,
        user_text: str,
        conversation_history: list[dict],
        scenario_prompt: str,
    ) -> str:
        """
        在场景模式中生成角色回复

        Args:
            user_text: 用户输入
            conversation_history: 场景对话历史
            scenario_prompt: 已格式化的场景系统 prompt

        Returns:
            角色回复
        """
        return await self.generate_response(
            user_text, conversation_history, scenario_prompt
        )
