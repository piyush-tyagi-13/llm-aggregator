"""In-memory token-bucket rate limiter for proxy endpoints.

Provides a simple per-IP token bucket that protects ``/v1/*`` from abuse.
Tokens refill at a configurable rate; burst sizes are limited.

Unlike FreeLLMAPI's per-key RPM/RPD tracking, this is purely a safety
layer against runaway clients — not a quota management system.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from llm_apipool.api.errors import error_response

logger = logging.getLogger(__name__)

# ── Token Bucket ─────────────────────────────────────────────────────────────


class TokenBucket:
    """Simple token bucket rate limiter.

    Thread-safe via ``asyncio.Lock``.
    """

    def __init__(self, rate: float, burst: int) -> None:
        self._rate = rate  # tokens per second
        self._burst = burst  # max accumulated tokens
        self._tokens = float(burst)
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def consume(self, tokens: float = 1.0) -> bool:
        """Try to consume *tokens* from the bucket.

        Returns ``True`` if allowed, ``False`` if rate-limited.
        """
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
            self._last = now

            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False


# ── Bucket registry ──────────────────────────────────────────────────────────


class RateLimiterRegistry:
    """Manages per-key token buckets with periodic stale-bucket cleanup."""

    def __init__(self, default_rate: float = 10.0, default_burst: int = 20) -> None:
        self._default_rate = default_rate
        self._default_burst = default_burst
        self._buckets: dict[str, TokenBucket] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task[Any] | None = None

    async def _cleanup_loop(self) -> None:
        """Remove buckets idle for more than 5 minutes."""
        while True:
            await asyncio.sleep(120)
            cutoff = time.monotonic() - 300
            async with self._lock:
                stale = [
                    k
                    for k, b in self._buckets.items()
                    if hasattr(b, "_last") and b._last < cutoff
                ]
                for k in stale:
                    del self._buckets[k]
                if stale:
                    logger.debug("Cleaned up %d stale rate-limiter buckets", len(stale))

    async def start(self) -> None:
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop(self) -> None:
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            self._cleanup_task = None

    async def check(self, key: str, tokens: float = 1.0) -> bool:
        """Check if *key* is allowed to consume *tokens*."""
        async with self._lock:
            if key not in self._buckets:
                self._buckets[key] = TokenBucket(
                    self._default_rate, self._default_burst
                )
            bucket = self._buckets[key]
        return await bucket.consume(tokens)


# ── FastAPI Middleware ───────────────────────────────────────────────────────

_RATE_LIMITER: RateLimiterRegistry | None = None


def get_limiter() -> RateLimiterRegistry:
    global _RATE_LIMITER
    if _RATE_LIMITER is None:
        _RATE_LIMITER = RateLimiterRegistry()
    return _RATE_LIMITER


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token-bucket rate limiter for ``/v1/*`` proxy endpoints.

    Uses client IP as the bucket key.  Enabled by setting
    ``LLM_APIPOOL_RATE_LIMIT`` env var (requests/second).
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Only apply to proxy endpoints
        if not request.url.path.startswith("/v1/"):
            return await call_next(request)

        limiter = get_limiter()
        client_ip = request.client.host if request.client else "unknown"
        allowed = await limiter.check(client_ip)
        if not allowed:
            logger.warning(
                "Rate-limited request from %s (path=%s)", client_ip, request.url.path
            )
            return error_response(
                429,
                "Too many requests. Please slow down.",
                "rate_limit_error",
            )

        return await call_next(request)


def add_rate_limit_middleware(app: Any, rate: float = 10.0, burst: int = 20) -> None:
    """Add rate-limiting middleware to a FastAPI app.

    Parameters
    ----------
    app:
        The FastAPI application.
    rate:
        Requests per second per client IP.
    burst:
        Maximum burst size (short-term spike allowance).
    """
    import os

    env_rate = os.environ.get("LLM_APIPOOL_RATE_LIMIT")
    if env_rate is not None:
        try:
            rate = float(env_rate)
        except ValueError:
            logger.warning("Invalid LLM_APIPOOL_RATE_LIMIT=%r, using default", env_rate)

    limiter = get_limiter()
    limiter._default_rate = rate
    limiter._default_burst = burst
    app.add_middleware(RateLimitMiddleware)
    logger.info("Rate limiter enabled: %s req/s, burst %d", rate, burst)
