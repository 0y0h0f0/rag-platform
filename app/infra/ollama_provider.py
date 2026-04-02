from __future__ import annotations

import logging
import time

import httpx

from app.core.config import settings
from app.infra.model_provider import EmbeddingProvider, LLMProvider, LLMResponse

logger = logging.getLogger(__name__)


class OllamaLLMProvider(LLMProvider):
    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self._base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self._model = model or settings.ollama_llm_model
        self._timeout = timeout or settings.llm_timeout_seconds

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self._model

    def warmup(self) -> None:
        try:
            with httpx.Client(timeout=self._timeout, trust_env=False) as client:
                client.post(
                    f"{self._base_url}/api/chat",
                    json={"model": self._model, "messages": [{"role": "user", "content": "hi"}], "stream": False},
                )
            logger.info("ollama LLM warmup completed for model %s", self._model)
        except Exception:
            logger.warning("ollama LLM warmup failed for model %s", self._model, exc_info=True)

    def chat_completion(self, messages: list[dict[str, str]], **kwargs) -> LLMResponse:
        from app.core.metrics import MODEL_INFERENCE_LATENCY, MODEL_INFERENCE_TOKENS

        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": kwargs.get("temperature", settings.llm_temperature),
                "num_predict": kwargs.get("max_tokens", settings.llm_max_tokens),
            },
        }

        start = time.perf_counter()
        try:
            with httpx.Client(timeout=self._timeout, trust_env=False) as client:
                resp = client.post(f"{self._base_url}/api/chat", json=payload)
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Ollama LLM call failed: {exc}") from exc
        finally:
            elapsed = time.perf_counter() - start
            MODEL_INFERENCE_LATENCY.labels(provider="ollama", model=self._model, operation="chat").observe(elapsed)

        data = resp.json()
        content = data.get("message", {}).get("content", "")
        prompt_tokens = data.get("prompt_eval_count", 0)
        completion_tokens = data.get("eval_count", 0)

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
                resp = client.get(f"{self._base_url}/api/tags")
                resp.raise_for_status()
                models = [m["name"] for m in resp.json().get("models", [])]
                return any(self._model in m for m in models)
        except Exception:
            return False


class OllamaEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        self._base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self._model = model or settings.ollama_embed_model
        self._detected_dim: int | None = None

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def embedding_dim(self) -> int | None:
        """Return the detected embedding dimension, or None if not yet probed."""
        return self._detected_dim

    def probe_dimension(self) -> int:
        """Send a probe request to detect the model's output dimension."""
        try:
            with httpx.Client(timeout=60.0, trust_env=False) as client:
                resp = client.post(
                    f"{self._base_url}/api/embed",
                    json={"model": self._model, "input": ["dimension probe"]},
                )
                resp.raise_for_status()
            embeddings = resp.json().get("embeddings", [])
            if embeddings:
                self._detected_dim = len(embeddings[0])
                logger.info(
                    "ollama embedding model %s detected dim=%d",
                    self._model,
                    self._detected_dim,
                )
                return self._detected_dim
        except Exception:
            logger.warning("failed to probe ollama embedding dimension", exc_info=True)
        return settings.embedding_dim

    def warmup(self) -> None:
        try:
            with httpx.Client(timeout=60.0, trust_env=False) as client:
                client.post(
                    f"{self._base_url}/api/embed",
                    json={"model": self._model, "input": ["warmup"]},
                )
            logger.info("ollama embedding warmup completed for model %s", self._model)
        except Exception:
            logger.warning("ollama embedding warmup failed for model %s", self._model, exc_info=True)

    def embed(self, texts: list[str]) -> list[list[float]]:
        from app.core.metrics import EMBEDDING_BATCH_SIZE, MODEL_INFERENCE_LATENCY

        EMBEDDING_BATCH_SIZE.observe(len(texts))

        start = time.perf_counter()
        try:
            with httpx.Client(timeout=60.0, trust_env=False) as client:
                resp = client.post(
                    f"{self._base_url}/api/embed",
                    json={"model": self._model, "input": texts},
                )
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Ollama embedding call failed: {exc}") from exc
        finally:
            elapsed = time.perf_counter() - start
            MODEL_INFERENCE_LATENCY.labels(provider="ollama", model=self._model, operation="embed").observe(elapsed)

        data = resp.json()
        return data.get("embeddings", [])

    def health_check(self) -> bool:
        try:
            with httpx.Client(timeout=5.0, trust_env=False) as client:
                resp = client.get(f"{self._base_url}/api/tags")
                resp.raise_for_status()
                models = [m["name"] for m in resp.json().get("models", [])]
                return any(self._model in m for m in models)
        except Exception:
            return False
