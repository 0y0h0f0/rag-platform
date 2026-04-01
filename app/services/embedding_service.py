from __future__ import annotations

import hashlib
import math
import re

from app.core.config import settings

try:
    from sentence_transformers import SentenceTransformer
except Exception:  # noqa: BLE001
    SentenceTransformer = None


class EmbeddingService:
    _model = None

    def tokenize(self, text: str) -> list[str]:
        return re.findall(r"\w+", text.lower())

    def _load_model(self):
        if settings.embedding_backend != "sentence_transformers":
            return None
        if SentenceTransformer is None:
            raise RuntimeError(
                "sentence-transformers is not available. Install dependencies or set EMBEDDING_BACKEND=local."
            )
        if self.__class__._model is None:
            self.__class__._model = SentenceTransformer(settings.embedding_model_name)
        return self.__class__._model

    def _embed_with_model(self, text: str) -> list[float]:
        model = self._load_model()
        vector = model.encode(text, normalize_embeddings=True)
        return [float(value) for value in vector]

    def _embed_with_local_hash(self, text: str) -> list[float]:
        vector = [0.0] * settings.embedding_dim
        tokens = self.tokenize(text)
        if not tokens:
            return vector

        for token in tokens:
            digest = hashlib.md5(token.encode("utf-8")).hexdigest()
            idx = int(digest, 16) % settings.embedding_dim
            vector[idx] += 1.0

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            return vector
        return [float(value / norm) for value in vector]

    def embed_text(self, text: str) -> list[float]:
        if settings.embedding_backend == "sentence_transformers":
            return self._embed_with_model(text)
        return self._embed_with_local_hash(text)

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        if settings.embedding_backend == "sentence_transformers":
            model = self._load_model()
            vectors = model.encode(texts, normalize_embeddings=True)
            return [[float(value) for value in vector] for vector in vectors]
        return [self._embed_with_local_hash(text) for text in texts]
