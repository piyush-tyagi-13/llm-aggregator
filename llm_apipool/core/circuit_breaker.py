"""Circuit breaker for provider keys — auto-disables after configurable failure thresholds.

Tracks consecutive failures per (provider, model, key_id). When the threshold is
exceeded, the key is automatically marked as cooldowned so the rotator skips it.
After the recovery timeout, it's allowed back into rotation.

This is the key differentiator from FreeLLMAPI: intelligent self-healing.
"""

from __future__ import annotations

import time
from threading import Lock
from typing import Any

# ── Defaults (configurable at call sites) ───────────────────────────────
DEFAULT_FAILURE_THRESHOLD = 5  # consecutive failures before tripping
DEFAULT_RECOVERY_MS = 300_000  # 5 minutes
DEFAULT_HALF_OPEN_MAX = 3  # requests allowed in half-open state


class CircuitBreakerState:
    """Tracks circuit breaker state for a single (provider, model, key_id)."""

    def __init__(self, failure_threshold: int = DEFAULT_FAILURE_THRESHOLD) -> None:
        self.failure_threshold = failure_threshold
        self.consecutive_failures = 0
        self.state: str = "closed"  # closed → open → half-open → closed
        self.tripped_at: float = 0.0
        self.half_open_successes = 0

    def record_success(self) -> None:
        self.consecutive_failures = 0
        if self.state == "half-open":
            self.half_open_successes += 1
            if self.half_open_successes >= DEFAULT_HALF_OPEN_MAX:
                self.state = "closed"
                self.half_open_successes = 0

    def record_failure(self) -> str:
        self.consecutive_failures += 1
        if (
            self.consecutive_failures >= self.failure_threshold
            and self.state == "closed"
        ):
            self.state = "open"
            self.tripped_at = time.time()
            self.half_open_successes = 0
        return self.state

    def attempt_recovery(self) -> bool:
        if self.state == "open":
            elapsed_ms = (time.time() - self.tripped_at) * 1000
            if elapsed_ms >= DEFAULT_RECOVERY_MS:
                self.state = "half-open"
                self.half_open_successes = 0
                return True
            return False
        return True


class CircuitBreaker:
    """Manages circuit breakers for all (provider, model, key_id) combinations.

    Thread-safe. When a key trips the breaker, it's automatically cooldowned
    in the key store so the rotator skips it.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._breakers: dict[tuple[str, str, int], CircuitBreakerState] = {}

    def _key(self, provider: str, model: str, key_id: int) -> tuple[str, str, int]:
        return (provider, model, key_id)

    def record_success(self, provider: str, model: str, key_id: int) -> None:
        with self._lock:
            k = self._key(provider, model, key_id)
            cb = self._breakers.get(k)
            if cb:
                cb.record_success()

    def record_failure(self, provider: str, model: str, key_id: int) -> str:
        """Record a failure. Returns the new state ('closed' | 'open' | 'half-open')."""
        with self._lock:
            k = self._key(provider, model, key_id)
            cb = self._breakers.setdefault(k, CircuitBreakerState())
            return cb.record_failure()

    def is_allowed(self, provider: str, model: str, key_id: int) -> bool:
        """Check if a request is allowed. Attempts recovery if in open state."""
        with self._lock:
            k = self._key(provider, model, key_id)
            cb = self._breakers.get(k)
            if not cb:
                return True
            if cb.state == "open":
                return cb.attempt_recovery()
            return True

    def get_state(self, provider: str, model: str, key_id: int) -> str:
        with self._lock:
            k = self._key(provider, model, key_id)
            cb = self._breakers.get(k)
            return cb.state if cb else "closed"

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            result = []
            for (provider, model, key_id), cb in self._breakers.items():
                result.append(
                    {
                        "provider": provider,
                        "model": model,
                        "key_id": key_id,
                        "state": cb.state,
                        "consecutive_failures": cb.consecutive_failures,
                    }
                )
            return sorted(result, key=lambda x: x["state"])


# Singleton
_CIRCUIT_BREAKER = CircuitBreaker()


def get_circuit_breaker() -> CircuitBreaker:
    return _CIRCUIT_BREAKER
