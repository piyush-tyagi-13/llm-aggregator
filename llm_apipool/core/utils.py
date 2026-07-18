"""Shared utility functions for llm-apipool.

Centralizes small helpers that were previously duplicated across the codebase:
key masking, chunk ID generation, UTC midnight calculation, and no-auth HTTP
transport.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import httpx


def mask_key(key: str, visible_chars: int = 4) -> str:
    """Mask an API key for safe logging.

    Shows the first *visible_chars* characters, then a variable-length
    masked middle section, then the last 4 characters.

    Examples:
        >>> mask_key("sk-abc123def456ghi789")
        'sk-***************i789'
        >>> mask_key("short")
        'short'
    """
    if len(key) <= visible_chars + 4:
        return key[:visible_chars] + "..." if len(key) > visible_chars else key
    return key[:visible_chars] + "*" * (len(key) - visible_chars - 4) + key[-4:]


def make_chunk_id() -> str:
    """Generate a unique chunk/response ID for streaming chunks and completions.

    Returns a string like ``chatcmpl-0123456789abcdef01234567``.
    """
    return f"chatcmpl-{uuid.uuid4().hex[:24]}"


def next_utc_midnight() -> str:
    """Return an ISO-8601 timestamp for the next UTC midnight.

    Used by cooldown strategies and daily quota reset logic.
    """
    now = datetime.now(UTC)
    return (
        (now + timedelta(days=1))
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .isoformat()
    )


class NoAuth(httpx.Auth):
    """httpx authentication handler that strips the ``Authorization`` header.

    Used for providers that do not require authentication (e.g. local or
    no-auth providers like OpenCode Zen).
    """

    def auth_flow(
        self, request: httpx.Request
    ) -> Generator[httpx.Request, httpx.Response, None]:
        request.headers.pop("authorization", None)
        yield request


__all__ = [
    "mask_key",
    "make_chunk_id",
    "next_utc_midnight",
    "NoAuth",
]
