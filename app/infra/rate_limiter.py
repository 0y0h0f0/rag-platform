from __future__ import annotations

import threading
import time

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse

from app.core.config import settings


class TokenBucket:
    """In-memory token bucket rate limiter."""

    def __init__(self, rate: float, capacity: float) -> None:
        self._rate = rate          # tokens per second
        self._capacity = capacity  # max burst
        self._tokens = capacity
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> bool:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._last_refill = now

            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False


class RateLimitMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware that applies token bucket rate limiting."""

    def __init__(self, app, rpm: int | None = None) -> None:
        super().__init__(app)
        rpm = rpm or settings.rate_limit_requests_per_minute
        self._bucket = TokenBucket(rate=rpm / 60.0, capacity=rpm)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not settings.rate_limit_enabled:
            return await call_next(request)

        # Skip rate limiting for health/metrics endpoints
        if request.url.path in ("/health", "/health/ready", "/metrics"):
            return await call_next(request)

        if not self._bucket.acquire():
            from app.core.metrics import RATE_LIMIT_REJECTED
            RATE_LIMIT_REJECTED.inc()
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Please try again later."},
            )

        return await call_next(request)
