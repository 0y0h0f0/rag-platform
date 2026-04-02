from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass, field

from app.core.config import settings
from app.infra.model_provider import EmbeddingProvider, LLMProvider, LLMResponse

logger = logging.getLogger(__name__)


@dataclass
class ABStats:
    requests: int = 0
    total_latency: float = 0.0
    total_tokens: int = 0

    @property
    def avg_latency(self) -> float:
        return self.total_latency / self.requests if self.requests else 0.0

    @property
    def avg_tokens(self) -> float:
        return self.total_tokens / self.requests if self.requests else 0.0


class ABTestingLLMProvider(LLMProvider):
    """Wraps two LLM providers with traffic splitting for A/B testing."""

    def __init__(self, provider_a: LLMProvider, provider_b: LLMProvider, split: float = 0.8) -> None:
        self._provider_a = provider_a
        self._provider_b = provider_b
        self._split = split
        self._lock = threading.Lock()
        self._stats: dict[str, ABStats] = {
            provider_a.model_name: ABStats(),
            provider_b.model_name: ABStats(),
        }

    @property
    def provider_name(self) -> str:
        return "ab_test"

    @property
    def model_name(self) -> str:
        return f"{self._provider_a.model_name}|{self._provider_b.model_name}"

    @property
    def split(self) -> float:
        return self._split

    @split.setter
    def split(self, value: float) -> None:
        self._split = max(0.0, min(1.0, value))

    def _pick_provider(self) -> LLMProvider:
        return self._provider_a if random.random() < self._split else self._provider_b

    def chat_completion(self, messages: list[dict[str, str]], **kwargs) -> LLMResponse:
        provider = self._pick_provider()
        start = time.perf_counter()
        response = provider.chat_completion(messages, **kwargs)
        elapsed = time.perf_counter() - start

        with self._lock:
            stats = self._stats.setdefault(provider.model_name, ABStats())
            stats.requests += 1
            stats.total_latency += elapsed
            stats.total_tokens += response.total_tokens

        response.metadata["ab_model"] = provider.model_name
        return response

    def health_check(self) -> bool:
        return self._provider_a.health_check() or self._provider_b.health_check()

    def get_stats(self) -> dict:
        with self._lock:
            return {
                model: {
                    "requests": s.requests,
                    "avg_latency": round(s.avg_latency, 4),
                    "avg_tokens": round(s.avg_tokens, 2),
                }
                for model, s in self._stats.items()
            }

    def reset_stats(self) -> None:
        with self._lock:
            for s in self._stats.values():
                s.requests = 0
                s.total_latency = 0.0
                s.total_tokens = 0


class ProviderRegistry:
    _instance: ProviderRegistry | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._llm_provider: LLMProvider | None = None
        self._embedding_provider: EmbeddingProvider | None = None

    @classmethod
    def get_instance(cls) -> ProviderRegistry:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
                    cls._instance._init_providers()
        return cls._instance

    def _init_providers(self) -> None:
        self._llm_provider = self._create_llm_provider()
        self._embedding_provider = self._create_embedding_provider()
        self._auto_detect_embedding_dim()
        logger.info(
            "providers initialized: llm=%s/%s, embedding=%s/%s",
            self._llm_provider.provider_name,
            self._llm_provider.model_name,
            self._embedding_provider.provider_name,
            self._embedding_provider.model_name,
        )

    def _auto_detect_embedding_dim(self) -> None:
        """Probe the embedding provider for its output dimension.

        If the detected dim differs from settings.embedding_dim, update the
        setting and drop the existing LanceDB table so it gets recreated
        with the correct schema on next access.
        """
        from app.infra.ollama_provider import OllamaEmbeddingProvider

        emb = self._embedding_provider
        if not isinstance(emb, OllamaEmbeddingProvider):
            return

        detected = emb.probe_dimension()
        if detected == settings.embedding_dim:
            return

        old_dim = settings.embedding_dim
        settings.embedding_dim = detected
        logger.warning(
            "embedding_dim auto-updated: %d → %d (model: %s). "
            "Rebuilding LanceDB table to match new dimension.",
            old_dim,
            detected,
            emb.model_name,
        )

        try:
            from app.db.lancedb_client import LanceDBClient
            client = LanceDBClient()
            if client.table_name in client.db.table_names():
                client.db.drop_table(client.table_name)
                logger.info("dropped LanceDB table '%s' (old dim=%d)", client.table_name, old_dim)
            client.ensure_table()
            logger.info("recreated LanceDB table '%s' with dim=%d", client.table_name, detected)
        except Exception:
            logger.error("failed to rebuild LanceDB table after dim change", exc_info=True)

    def _create_llm_provider(self) -> LLMProvider:
        from app.infra.api_provider import APILLMProvider
        from app.infra.ollama_provider import OllamaLLMProvider

        provider_type = settings.llm_provider

        if provider_type == "ollama":
            return OllamaLLMProvider()
        elif provider_type == "ab_test":
            provider_a = OllamaLLMProvider(model=settings.ab_model_a)
            provider_b = OllamaLLMProvider(model=settings.ab_model_b)
            return ABTestingLLMProvider(provider_a, provider_b, settings.ab_traffic_split)
        else:
            # "api" or "deepseek" or any other — use OpenAI-compatible API
            return APILLMProvider()

    def _create_embedding_provider(self) -> EmbeddingProvider:
        from app.infra.ollama_provider import OllamaEmbeddingProvider

        provider_type = settings.embedding_provider

        if provider_type == "ollama":
            return OllamaEmbeddingProvider()
        else:
            # "sentence_transformers" or "local" — use legacy in-process embedding
            return _LegacyEmbeddingProvider()

    def get_llm(self) -> LLMProvider:
        assert self._llm_provider is not None
        return self._llm_provider

    def get_embedding(self) -> EmbeddingProvider:
        assert self._embedding_provider is not None
        return self._embedding_provider

    def list_models(self) -> list[dict]:
        models = []
        llm = self._llm_provider
        if isinstance(llm, ABTestingLLMProvider):
            models.append({"provider": "ab_test", "model": llm._provider_a.model_name, "type": "llm", "role": "model_a"})
            models.append({"provider": "ab_test", "model": llm._provider_b.model_name, "type": "llm", "role": "model_b"})
        else:
            models.append({"provider": llm.provider_name, "model": llm.model_name, "type": "llm"})
        emb = self._embedding_provider
        models.append({"provider": emb.provider_name, "model": emb.model_name, "type": "embedding"})
        return models

    def health_check_all(self) -> dict:
        results = {}
        llm = self._llm_provider
        if isinstance(llm, ABTestingLLMProvider):
            results[f"llm/{llm._provider_a.model_name}"] = llm._provider_a.health_check()
            results[f"llm/{llm._provider_b.model_name}"] = llm._provider_b.health_check()
        else:
            results[f"llm/{llm.model_name}"] = llm.health_check()
        emb = self._embedding_provider
        results[f"embedding/{emb.model_name}"] = emb.health_check()
        return results


class _LegacyEmbeddingProvider(EmbeddingProvider):
    """Wraps the existing local hash / sentence-transformers embedding."""

    def __init__(self) -> None:
        from app.services.embedding_service import EmbeddingService
        self._svc = EmbeddingService()

    @property
    def provider_name(self) -> str:
        return settings.embedding_backend

    @property
    def model_name(self) -> str:
        if settings.embedding_backend == "sentence_transformers":
            return settings.embedding_model_name
        return "local-hash"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._svc.embed_many(texts)

    def health_check(self) -> bool:
        try:
            result = self._svc.embed_text("health check")
            return len(result) == settings.embedding_dim
        except Exception:
            return False
