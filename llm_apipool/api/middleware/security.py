"""Security headers middleware.

Adds security-related HTTP headers to all responses:
``X-Content-Type-Options``, ``X-Frame-Options``, ``Content-Security-Policy``,
``Strict-Transport-Security``, and ``X-XSS-Protection``.
"""

from __future__ import annotations

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to every response."""

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        return response


def add_security_headers_middleware(app: FastAPI) -> None:
    """Add security headers middleware to the app."""
    app.add_middleware(SecurityHeadersMiddleware)
