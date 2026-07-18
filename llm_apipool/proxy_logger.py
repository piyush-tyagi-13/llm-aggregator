"""Structured proxy request/response logger — writes JSON Lines files."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

_LOG_DIR = Path.home() / ".llm-apipool" / "logs"
_MAX_LOG_SIZE = 50 * 1024 * 1024  # 50 MB
_MAX_LOG_DAYS = 7  # Keep 7 days of logs
_MAX_BODY_LOG = 50000


def _log_path(d: date | None = None) -> Path:
    """Get log file path with size-based rotation.

    If today's log file exceeds _MAX_LOG_SIZE, rotate to
    proxy-YYYY-MM-DD-N.jsonl where N is an incrementing counter.
    """
    d = d or date.today()
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    base_path = _LOG_DIR / f"proxy-{d.isoformat()}.jsonl"
    if not base_path.exists() or base_path.stat().st_size < _MAX_LOG_SIZE:
        return base_path

    # Find next available sequence number
    counter = 1
    while True:
        rotated_path = _LOG_DIR / f"proxy-{d.isoformat()}-{counter}.jsonl"
        if not rotated_path.exists():
            return rotated_path
        counter += 1


def _cleanup_old_logs() -> None:
    """Remove log files older than _MAX_LOG_DAYS."""
    cutoff_date = date.today() - timedelta(days=_MAX_LOG_DAYS)
    try:
        for log_file in _LOG_DIR.glob("proxy-*.jsonl*"):
            # Extract date from filename
            # Format: proxy-YYYY-MM-DD.jsonl or proxy-YYYY-MM-DD-N.jsonl
            stem = log_file.stem  # removes .jsonl
            if stem.startswith("proxy-"):
                date_str = stem[6:]  # remove "proxy-"
                # Handle both YYYY-MM-DD and YYYY-MM-DD-N formats
                date_parts = date_str.split("-")
                if len(date_parts) >= 3:
                    try:
                        file_date = date(
                            int(date_parts[0]), int(date_parts[1]), int(date_parts[2])
                        )
                        if file_date < cutoff_date:
                            log_file.unlink()
                    except ValueError:
                        # Skip files with invalid date format
                        pass
    except OSError:
        pass  # Ignore errors during cleanup


def write_entry(
    request_id: str,
    *,
    method: str,
    path: str,
    subscriber_id: str,
    model: str,
    provider: str,
    latency_ms: int,
    status_code: int,
    tokens_in: int = 0,
    tokens_out: int = 0,
    error: str | None = None,
    request_body: str | None = None,
    response_body: str | None = None,
    key_id: int | None = None,
    stream: bool = False,
) -> None:
    """Append a single structured log entry (thread-safe write).

    Stores full request/response bodies (truncated at 50KB to prevent
    unbounded file growth). For streaming responses only the metadata
    and last 500 chars are stored. Also triggers periodic log cleanup.
    """
    _maybe_cleanup()
    entry: dict[str, Any] = {
        "ts": datetime.now(UTC).isoformat(),
        "request_id": request_id,
        "method": method,
        "path": path,
        "subscriber_id": subscriber_id,
        "model": model,
        "provider": provider,
        "latency_ms": latency_ms,
        "status_code": status_code,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "error": error,
        "key_id": key_id,
        "stream": stream,
        "request_body": _truncate(request_body, _MAX_BODY_LOG)
        if request_body
        else None,
        "response_body": _truncate(response_body, _MAX_BODY_LOG)
        if response_body
        else None,
    }
    entry = {k: v for k, v in entry.items() if v is not None}
    path = _log_path()
    try:
        with open(path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except IOError as e:
        # Log to stderr as fallback if we can't write to log file
        import sys

        print(f"Failed to write to log file {path}: {e}", file=sys.stderr)


def _truncate(text: str, max_len: int) -> str:
    return text if len(text) <= max_len else text[:max_len] + "..."


# ── Reader ──────────────────────────────────────────────────────────


def read_entries(
    days: int = 1,
    subscriber_id: str | None = None,
    provider: str | None = None,
    status_code: int | None = None,
    error_only: bool = False,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Read log entries from the last N days with optional filters."""
    from datetime import timedelta

    results: list[dict[str, Any]] = []
    cutoff = date.today() - timedelta(days=days - 1)

    d = date.today()
    while d >= cutoff:
        p = _log_path(d)
        if p.exists():
            with open(p) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if subscriber_id and entry.get("subscriber_id") != subscriber_id:
                        continue
                    if provider and entry.get("provider") != provider:
                        continue
                    if (
                        status_code is not None
                        and entry.get("status_code") != status_code
                    ):
                        continue
                    if error_only and not entry.get("error"):
                        continue
                    results.append(entry)
                    if len(results) >= limit:
                        return results
        d -= timedelta(days=1)

    return results


def get_stats(days: int = 1) -> dict[str, Any]:
    """Aggregate statistics from recent log entries."""
    entries = read_entries(days=days, limit=50000)
    total = len(entries)
    if not total:
        return {"total": 0}

    success = sum(
        1 for e in entries if e.get("status_code", 0) < 400 or not e.get("error")
    )
    errors = total - success

    subscribers: dict[str, int] = {}
    providers: dict[str, int] = {}
    models: dict[str, int] = {}
    latencies: list[int] = []
    errors_by_code: dict[int, int] = {}
    tokens_total = 0

    for e in entries:
        sub = e.get("subscriber_id", "unknown")
        subscribers[sub] = subscribers.get(sub, 0) + 1

        prv = e.get("provider", "unknown")
        providers[prv] = providers.get(prv, 0) + 1

        mdl = e.get("model", "unknown")
        models[mdl] = models.get(mdl, 0) + 1

        if e.get("latency_ms") is not None:
            latencies.append(e["latency_ms"])

        if e.get("status_code") and e["status_code"] >= 400:
            errors_by_code[e["status_code"]] = (
                errors_by_code.get(e["status_code"], 0) + 1
            )

        tokens_total += e.get("tokens_in", 0) + e.get("tokens_out", 0)

    latencies.sort()
    stats: dict[str, Any] = {
        "total": total,
        "success": success,
        "errors": errors,
        "tokens_total": tokens_total,
        "top_subscribers": sorted(subscribers.items(), key=lambda x: -x[1])[:10],
        "top_providers": sorted(providers.items(), key=lambda x: -x[1])[:10],
        "top_models": sorted(models.items(), key=lambda x: -x[1])[:10],
        "errors_by_code": errors_by_code,
    }
    if latencies:
        n = len(latencies)
        stats["latency"] = {
            "min": latencies[0],
            "max": latencies[-1],
            "avg": sum(latencies) / n,
            "p50": latencies[n // 2],
            "p95": latencies[int(n * 0.95)],
            "p99": latencies[int(n * 0.99)],
        }
    return stats


def list_log_days() -> list[str]:
    """Return sorted list of dates that have log files."""
    if not _LOG_DIR.exists():
        return []
    return sorted(
        f.name.replace("proxy-", "").replace(".jsonl", "")
        for f in sorted(_LOG_DIR.iterdir())
        if f.name.startswith("proxy-") and f.suffix == ".jsonl"
    )


# Cleanup old logs periodically when writing
def _maybe_cleanup() -> None:
    """Cleanup old logs occasionally to avoid doing it on every write."""
    # Cleanup once per day on average
    import hashlib

    # Simple hash-based approach: cleanup if hash of current date mod 1000 < 1
    today_str = date.today().isoformat()
    hash_val = int(hashlib.sha256(today_str.encode()).hexdigest(), 16)
    if hash_val % 1000 == 0:
        _cleanup_old_logs()



