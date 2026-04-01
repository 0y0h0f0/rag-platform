from __future__ import annotations

import hashlib
import json
from typing import Any

from app.core.config import settings
from app.core.metrics import CACHE_HITS, CACHE_MISSES
from app.db.redis_client import get_redis_safe


class CacheService:
    def _key(self, namespace: str, payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=True)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return f"rag-platform:{namespace}:{digest}"

    def get_json(self, namespace: str, payload: dict[str, Any]) -> list[dict] | None:
        client = get_redis_safe()
        if client is None:
            return None
        key = self._key(namespace, payload)
        value = client.get(key)
        if value is None:
            CACHE_MISSES.inc()
            return None
        CACHE_HITS.inc()
        return json.loads(value)

    def set_json(self, namespace: str, payload: dict[str, Any], value: list[dict]) -> None:
        client = get_redis_safe()
        if client is None:
            return
        key = self._key(namespace, payload)
        client.setex(key, settings.search_cache_ttl_seconds, json.dumps(value, ensure_ascii=True))

    def clear_namespace(self, namespace: str) -> None:
        client = get_redis_safe()
        if client is None:
            return
        keys = client.keys(f"rag-platform:{namespace}:*")
        if keys:
            client.delete(*keys)

