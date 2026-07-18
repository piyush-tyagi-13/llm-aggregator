"""FreeLLMAPI-compatible error responses for the proxy.

All error shapes follow the FreeLLMAPI convention::

    { "error": { "message": str, "type": str, "code"?: str } }

Error types
-----------
- ``authentication_error``  — invalid/missing API key (401)
- ``invalid_request_error`` — bad request body (400/422)
- ``rate_limit_error``      — rate limit hit (429)
- ``routing_error``         — no viable provider/key (503)
- ``server_error``          — internal / provider failure (502/500)
- ``stream_error``          — mid-stream provider failure (within SSE)
"""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse


# Error type constants — matching FreeLLMAPI exactly
AUTH_ERROR = "authentication_error"
INVALID_REQUEST_ERROR = "invalid_request_error"
RATE_LIMIT_ERROR = "rate_limit_error"
ROUTING_ERROR = "routing_error"
SERVER_ERROR = "server_error"
STREAM_ERROR = "stream_error"


def error_response(
    status: int,
    message: str,
    err_type: str = SERVER_ERROR,
    *,
    code: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Build a JSON error response in FreeLLMAPI format.

    Parameters
    ----------
    status:
        HTTP status code.
    message:
        Human-readable error description.
    err_type:
        One of the error type constants defined in this module.
    code:
        Optional machine-readable error code (e.g. ``"fusion_no_vision"``).
    headers:
        Optional extra response headers.
    """
    body: dict[str, Any] = {"error": {"message": message, "type": err_type}}
    if code is not None:
        body["error"]["code"] = code
    return JSONResponse(status_code=status, content=body, headers=headers)


__all__ = [
    "AUTH_ERROR",
    "INVALID_REQUEST_ERROR",
    "RATE_LIMIT_ERROR",
    "ROUTING_ERROR",
    "SERVER_ERROR",
    "STREAM_ERROR",
    "error_response",
]
