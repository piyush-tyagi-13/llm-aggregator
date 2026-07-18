"""API authentication middleware.

FreeLLMAPI-compatible auth for /v1/* proxy endpoints:
- Accepts ``Authorization: Bearer <key>`` OR ``X-API-Key: <key>``
- Uses constant-time HMAC comparison to prevent timing leaks
- When ``LLM_APIPOOL_API_KEY`` env var is unset, requests pass through
- Returns FreeLLMAPI-compatible ``authentication_error`` error shape
"""

from __future__ import annotations

import hmac
import os
from typing import Any

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from llm_apipool.api.errors import AUTH_ERROR, error_response


def _get_required_key() -> str | None:
    """Return the configured API key, or None if auth is disabled."""
    return os.environ.get("LLM_APIPOOL_API_KEY") or None


def _extract_token(request: Request) -> str | None:
    """Extract API token — accepts Authorization: Bearer or X-API-Key header."""
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        if token:
            return token
    api_key = request.headers.get("x-api-key", "")
    if api_key:
        return api_key.strip()
    return None


def _timing_safe_equal(provided: str, expected: str) -> bool:
    """Constant-time string comparison, matching FreeLLMAPI."""
    return hmac.compare_digest(provided, expected)


class ProxyAuthMiddleware(BaseHTTPMiddleware):
    """FreeLLMAPI-compatible auth for /v1/* proxy endpoints."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        required_key = _get_required_key()
        if required_key:
            provided = _extract_token(request)
            if not provided or not _timing_safe_equal(provided, required_key):
                return error_response(401, "Invalid API key", AUTH_ERROR)
        return await call_next(request)


def add_proxy_auth_middleware(app: Any) -> None:
    """Add FreeLLMAPI-compatible auth middleware for /v1/* proxy routes."""
    app.add_middleware(ProxyAuthMiddleware)
