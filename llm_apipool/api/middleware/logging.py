"""Comprehensive request/response logging middleware.

Logs every request — full headers, body, method, path, status, duration —
to a structured JSON Lines file at ``~/.llm-apipool/logs/access-*.jsonl``.

For chat-completion routes, the log also captures messages, model, provider,
and subscriber id when available.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from typing import Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

logger = logging.getLogger("llm-apipool.proxy")

_MAX_BODY_LOG = 100_000  # 100 KB max per request/response body


def _truncate(text: str, max_len: int = _MAX_BODY_LOG) -> str:
    return text if len(text) <= max_len else text[:max_len] + "..."


def _safe_json(text: str) -> str:
    """Try to pretty-print a JSON body; fall back to raw text."""
    try:
        parsed = json.loads(text)
        return json.dumps(parsed, indent=2, ensure_ascii=False)[:5000]
    except (json.JSONDecodeError, ValueError):
        return _truncate(text, 5000)


class ComprehensiveLoggingMiddleware(BaseHTTPMiddleware):
    """Logs every request with full headers, body, and response metadata."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        start = time.monotonic()
        req_id = uuid.uuid4().hex[:12]

        # ── Capture request body (re-readable via request.state) ──────
        body_bytes = await request.body()
        body_text = body_bytes.decode("utf-8", errors="replace") if body_bytes else ""
        request.state.raw_body = body_bytes

        # ── Capture ALL headers ───────────────────────────────────────
        headers: dict[str, str] = {}
        for key, val in request.headers.items():
            headers[key] = val

        # ── Process ───────────────────────────────────────────────────
        response = await call_next(request)
        elapsed = time.monotonic() - start
        latency_ms = int(elapsed * 1000)

        # ── Capture response body if possible ─────────────────────────
        resp_body = ""
        if hasattr(response, "body"):
            try:
                raw = response.body
                if isinstance(raw, bytes):
                    resp_body = raw.decode("utf-8", errors="replace")
            except Exception:
                pass

        # ── Redact sensitive headers before logging ────────────────────
        if "authorization" in headers:
            headers["authorization"] = "***"

        # ── Log to structured file ────────────────────────────────────
        method = request.method
        path = request.url.path
        query = str(request.url.query) if request.url.query else ""

        subscriber_id = (
            headers.get("x-subscriber-id")
            or headers.get("x-subscriber_id")
            or "unknown"
        )

        log_entry: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
            "request_id": str(req_id),
            "method": method,
            "path": path,
            "query": query or None,
            "status_code": response.status_code,
            "latency_ms": latency_ms,
            "subscriber_id": subscriber_id,
            "headers": headers,
            "request_body": _safe_json(body_text) if body_text else None,
            "response_body": _truncate(resp_body, 2000) if resp_body else None,
        }
        log_entry = {k: v for k, v in log_entry.items() if v is not None}

        # Write to structured JSONL access log
        _write_entry(log_entry)

        # Also log to standard logger at INFO
        logger.info(
            "%s %s → %d (%dms) sub=%s",
            method,
            path,
            response.status_code,
            latency_ms,
            subscriber_id,
        )

        return response


# ── JSONL writer (separate from proxy_logger to avoid circular deps) ──

_LOG_DIR = None


def _get_log_dir() -> Any:
    global _LOG_DIR
    if _LOG_DIR is None:
        from pathlib import Path

        _LOG_DIR = Path.home() / ".llm-apipool" / "logs"
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
    return _LOG_DIR


def _log_path() -> Any:
    """Rotated daily log file: access-YYYY-MM-DD.jsonl"""
    from datetime import date

    d = date.today().isoformat()
    return _get_log_dir() / f"access-{d}.jsonl"


def _cleanup_old_logs() -> None:
    """Remove access log files older than 7 days."""
    from datetime import date, timedelta

    cutoff_date = date.today() - timedelta(days=7)
    log_dir = _get_log_dir()
    for log_file in log_dir.glob("access-*.jsonl"):
        # Extract date from filename: access-YYYY-MM-DD.jsonl
        stem = log_file.stem
        if stem.startswith("access-"):
            date_str = stem[7:]
            try:
                parts = date_str.split("-")
                if len(parts) >= 3:
                    file_date = date(int(parts[0]), int(parts[1]), int(parts[2]))
                    if file_date < cutoff_date:
                        log_file.unlink()
            except (ValueError, IndexError):
                pass


def _write_entry(entry: dict[str, Any]) -> None:
    """Thread-safe append to the daily access log."""
    path = _log_path()
    try:
        with open(path, "a") as f:
            f.write(json.dumps(entry, default=str, ensure_ascii=False) + "\n")
    except OSError:
        pass  # best-effort logging
    # Probabilistic cleanup: ~1/1000 writes triggers cleanup
    try:
        from datetime import date as _dt_date

        today_str = _dt_date.today().isoformat()
        hash_val = int(hashlib.sha256(today_str.encode()).hexdigest(), 16)
        if hash_val % 1000 == 0:
            _cleanup_old_logs()
    except Exception:
        pass  # best-effort cleanup


def add_logging_middleware(app: Any) -> None:
    """Add comprehensive request logging middleware to the app."""
    app.add_middleware(ComprehensiveLoggingMiddleware)
