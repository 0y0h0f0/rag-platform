from __future__ import annotations

import logging
import threading
import time
from enum import Enum
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerOpen(RuntimeError):
    """Raised when the circuit breaker is open."""


class CircuitBreaker:
    """Simple circuit breaker with three states: CLOSED -> OPEN -> HALF_OPEN.

    Args:
        name: Identifier for logging/metrics.
        failure_threshold: Consecutive failures before opening.
        recovery_timeout: Seconds to wait before trying half-open.
        half_open_max_calls: Calls allowed in half-open state before deciding.
    """

    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 1,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._half_open_calls = 0
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            if self._state == CircuitState.OPEN:
                if time.monotonic() - self._last_failure_time >= self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_calls = 0
                    logger.info("circuit breaker '%s' transitioning to HALF_OPEN", self.name)
            return self._state

    def call(self, func: Callable[..., T], *args, **kwargs) -> T:
        current_state = self.state

        if current_state == CircuitState.OPEN:
            raise CircuitBreakerOpen(f"Circuit breaker '{self.name}' is OPEN")

        if current_state == CircuitState.HALF_OPEN:
            with self._lock:
                if self._half_open_calls >= self.half_open_max_calls:
                    raise CircuitBreakerOpen(f"Circuit breaker '{self.name}' HALF_OPEN limit reached")
                self._half_open_calls += 1

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as exc:
            self._on_failure()
            raise

    def _on_success(self) -> None:
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                logger.info("circuit breaker '%s' recovered, transitioning to CLOSED", self.name)
            self._state = CircuitState.CLOSED
            self._failure_count = 0

    def _on_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                logger.warning("circuit breaker '%s' failed in HALF_OPEN, back to OPEN", self.name)
            elif self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning(
                    "circuit breaker '%s' opened after %d consecutive failures",
                    self.name,
                    self._failure_count,
                )
