from __future__ import annotations

import logging
import time

import httpx

from app.core.config import settings
from app.infra.model_provider import EmbeddingProvider, LLMProvider, LLMResponse

logger = logging.getLogger(__name__)


class APILLMProvider(LLMProvider):
    """OpenAI-compatible API provider (DeepSeek, OpenAI, vLLM, etc.)."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self._base_url = (base_url or settings.llm_base_url).rstrip("/")
        self._api_key_override = api_key  # None means read from settings each time
        self._model = model or settings.llm_model
        self._timeout = timeout or settings.llm_timeout_seconds

    @property
    def _api_key(self) -> str:
        return self._api_key_override if self._api_key_override is not None else settings.llm_api_key

    @property
    def provider_name(self) -> str:
        return "api"

    @property
    def model_name(self) -> str:
        return self._model

    def chat_completion(self, messages: list[dict[str, str]], **kwargs) -> LLMResponse:
        from app.core.metrics import MODEL_INFERENCE_LATENCY, MODEL_INFERENCE_TOKENS

        if not self._api_key:
            raise RuntimeError("API Key 未配置。请在环境变量中设置 LLM_API_KEY。")

        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": kwargs.get("temperature", settings.llm_temperature),
            "max_tokens": kwargs.get("max_tokens", settings.llm_max_tokens),
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        start = time.perf_counter()
        try:
            with httpx.Client(timeout=self._timeout, trust_env=False) as client:
                resp = client.post(f"{self._base_url}/chat/completions", headers=headers, json=payload)
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"API LLM call failed: {exc}") from exc
        finally:
            elapsed = time.perf_counter() - start
            MODEL_INFERENCE_LATENCY.labels(provider="api", model=self._model, operation="chat").observe(elapsed)

        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            return LLMResponse(content="", model=self._model)

        content = choices[0].get("message", {}).get("content", "")
        usage = data.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)

        MODEL_INFERENCE_TOKENS.labels(model=self._model, direction="input").inc(prompt_tokens)
        MODEL_INFERENCE_TOKENS.labels(model=self._model, direction="output").inc(completion_tokens)

        return LLMResponse(
            content=content.strip(),
            model=self._model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        )

    def health_check(self) -> bool:
        try:
            with httpx.Client(timeout=5.0, trust_env=False) as client:
                resp = client.get(f"{self._base_url}/models", headers={"Authorization": f"Bearer {self._api_key}"})
                return resp.status_code == 200
        except Exception:
            return False
