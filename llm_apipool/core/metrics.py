"""Production metrics tracking — request counts, latency, errors, token usage per key/provider/model.

All operations are thread-safe. Exposes a Prometheus-text endpoint via ``format_prometheus()``.
"""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock
from typing import Any


# ── In-memory metrics store ─────────────────────────────────────────────


class _MetricsStore:
    """Thread-safe metrics accumulator with time-windowed counters."""

    def __init__(self) -> None:
        self._lock = Lock()
        # Key: (provider, model)  →  counters
        self._requests: dict[tuple[str, str], int] = defaultdict(int)
        self._errors: dict[tuple[str, str], int] = defaultdict(int)
        self._429s: dict[tuple[str, str], int] = defaultdict(int)
        self._total_tokens: dict[tuple[str, str], int] = defaultdict(int)
        self._latencies: dict[tuple[str, str], list[float]] = defaultdict(list)
        self._key_requests: dict[tuple[str, str, int], int] = defaultdict(
            int
        )  # (provider, model, key_id)
        self._started_at: float = time.time()

    def record_request(
        self,
        provider: str,
        model: str,
        key_id: int,
        tokens_used: int,
        latency_ms: float,
        was_error: bool = False,
        was_429: bool = False,
    ) -> None:
        pmid = (provider, model)
        with self._lock:
            self._requests[pmid] += 1
            self._total_tokens[pmid] += tokens_used
            self._latencies[pmid].append(latency_ms)
            # Keep latency buffer bounded
            if len(self._latencies[pmid]) > 1000:
                self._latencies[pmid] = self._latencies[pmid][-500:]
            self._key_requests[(provider, model, key_id)] += 1
            if was_error:
                self._errors[pmid] += 1
            if was_429:
                self._429s[pmid] += 1

    def snapshot(self) -> dict[str, Any]:
        """Return a full snapshot for the /stats endpoint."""
        with self._lock:
            providers: dict[str, dict[str, Any]] = {}
            for (provider, model), count in self._requests.items():
                p = providers.setdefault(
                    provider,
                    {
                        "models": {},
                        "total_requests": 0,
                        "total_errors": 0,
                        "total_429s": 0,
                    },
                )
                latencies = self._latencies.get((provider, model), [])
                avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
                p["models"][model] = {
                    "requests": count,
                    "errors": self._errors.get((provider, model), 0),
                    "429s": self._429s.get((provider, model), 0),
                    "tokens": self._total_tokens.get((provider, model), 0),
                    "avg_latency_ms": round(avg_latency, 1),
                    "peak_latency_ms": round(max(latencies), 1) if latencies else 0.0,
                }
                p["total_requests"] += count
                p["total_errors"] += self._errors.get((provider, model), 0)
                p["total_429s"] += self._429s.get((provider, model), 0)

            uptime_seconds = time.time() - self._started_at
            total_requests = sum(self._requests.values())
            total_errors = sum(self._errors.values())
            total_429s = sum(self._429s.values())
            total_tokens = sum(self._total_tokens.values())

            return {
                "uptime_seconds": round(uptime_seconds, 1),
                "uptime_human": _format_duration(uptime_seconds),
                "total_requests": total_requests,
                "total_errors": total_errors,
                "total_429s": total_429s,
                "total_tokens": total_tokens,
                "error_rate": round(total_errors / total_requests, 4)
                if total_requests
                else 0.0,
                "providers": providers,
            }

    def format_prometheus(self) -> str:
        """Render metrics as Prometheus text format."""
        with self._lock:
            lines: list[str] = [
                "# HELP llm_apipool_requests_total Total requests per provider+model",
                "# TYPE llm_apipool_requests_total counter",
            ]
            for (provider, model), count in self._requests.items():
                lines.append(
                    f'llm_apipool_requests_total{{provider="{provider}",model="{model}"}} {count}'
                )

            lines += [
                "# HELP llm_apipool_errors_total Total errors per provider+model",
                "# TYPE llm_apipool_errors_total counter",
            ]
            for (provider, model), count in self._errors.items():
                lines.append(
                    f'llm_apipool_errors_total{{provider="{provider}",model="{model}"}} {count}'
                )

            lines += [
                "# HELP llm_apipool_ratelimit_total Total 429s per provider+model",
                "# TYPE llm_apipool_ratelimit_total counter",
            ]
            for (provider, model), count in self._429s.items():
                lines.append(
                    f'llm_apipool_ratelimit_total{{provider="{provider}",model="{model}"}} {count}'
                )

            lines += [
                "# HELP llm_apipool_tokens_total Total tokens consumed per provider+model",
                "# TYPE llm_apipool_tokens_total counter",
            ]
            for (provider, model), count in self._total_tokens.items():
                lines.append(
                    f'llm_apipool_tokens_total{{provider="{provider}",model="{model}"}} {count}'
                )

            lines += [
                "# HELP llm_apipool_up Startup timestamp",
                "# TYPE llm_apipool_up gauge",
                f"llm_apipool_up {int(self._started_at)}",
            ]
            return "\n".join(lines) + "\n"


# Singleton
_metrics = _MetricsStore()


def get_metrics() -> _MetricsStore:
    return _metrics


def _format_duration(seconds: float) -> str:
    days, remainder = divmod(int(seconds), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


__all__ = ["get_metrics"]
