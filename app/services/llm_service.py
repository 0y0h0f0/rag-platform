from __future__ import annotations

import logging

from app.infra.provider_registry import ProviderRegistry

logger = logging.getLogger(__name__)


class LLMService:
    def _build_messages(self, query: str, hits: list[dict]) -> list[dict[str, str]]:
        context_lines = []
        for index, hit in enumerate(hits[:5], start=1):
            context_lines.append(
                f"[{index}] source={hit['source']} chunk_index={hit['chunk_index']}\n{hit['text']}"
            )

        context = "\n\n".join(context_lines)
        user_prompt = (
            "请基于给定的检索上下文回答问题。\n"
            "要求：\n"
            "1. 优先依据上下文回答，不要编造。\n"
            "2. 如果上下文不足，请明确说明。\n"
            "3. 尽量给出结构化、简洁的中文答案。\n"
            f"\n问题：{query}\n"
            f"\n检索上下文：\n{context}"
        )
        return [
            {
                "role": "system",
                "content": "你是一个面向知识库问答场景的中文 AI 助手，回答必须基于检索上下文。",
            },
            {"role": "user", "content": user_prompt},
        ]

    def answer(self, query: str, hits: list[dict]) -> str:
        if not hits:
            return "未检索到相关上下文，当前无法基于知识库生成回答。"

        messages = self._build_messages(query, hits)
        registry = ProviderRegistry.get_instance()
        llm = registry.get_llm()

        try:
            response = llm.chat_completion(messages)
        except RuntimeError as exc:
            return f"LLM 调用失败: {exc}"

        if not response.content:
            return "LLM 返回结果为空。"

        return response.content

    def answer_with_metadata(self, query: str, hits: list[dict]) -> dict:
        """Like answer() but returns model version metadata for A/B testing."""
        if not hits:
            return {"answer": "未检索到相关上下文，当前无法基于知识库生成回答。", "model_version": None}

        messages = self._build_messages(query, hits)
        registry = ProviderRegistry.get_instance()
        llm = registry.get_llm()

        try:
            response = llm.chat_completion(messages)
        except RuntimeError as exc:
            return {"answer": f"LLM 调用失败: {exc}", "model_version": None}

        model_version = response.metadata.get("ab_model", response.model)
        return {
            "answer": response.content or "LLM 返回结果为空。",
            "model_version": model_version,
        }
