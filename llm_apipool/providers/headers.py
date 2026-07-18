"""Rate-limit header parsing and cooldown derivation per provider.

Confirmed headers from live API probes (real keys, 2026-04-29):

  Groq:      x-ratelimit-{limit,remaining,reset}-{requests,tokens}
             reset values are duration strings: "1m26.4s", "170ms", "2h", "30s"
             retry-after on 429 (seconds as float/int)

  Cerebras:  x-ratelimit-{limit,remaining}-{requests,tokens}-{minute,hour,day}
             three time dimensions; no reset timestamps, only remaining counts

  Mistral:   x-ratelimit-{limit,remaining}-req-minute  ("req" not "requests")
             x-ratelimit-{limit,remaining}-tokens-minute
             no reset timestamps

  OpenRouter: no rate-limit headers observed on live probe
  GitHub Models: x-ratelimit-remaining-requests, x-ratelimit-remaining-tokens
  Others:    untested; fall back to config-driven strategy

Providers without custom extractors (Google, Cohere, Cloudflare, SambaNova,
NVIDIA NIM, Zhipu, Ollama Cloud, Kilo Gateway, Pollinations, OVH AI, LLM7,
HuggingFace Router, OpenCode Zen, Agnes AI, Interfaze) use the config-driven
cooldown_fallback strategy from providers.json.
"""

from __future__ import annotations


import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import httpx

# Matches Groq-style duration strings: "1m26.4s", "170ms", "2h5m", "30s"
_DURATION_RE = re.compile(
    r"^(?:(\d+(?:\.\d+)?)h)?"
    r"(?:(\d+(?:\.\d+)?)m(?!s))?"
    r"(?:(\d+(?:\.\d+)?)s)?"
    r"(?:(\d+(?:\.\d+)?)ms)?$",
)

_RL_PREFIXES = ("x-ratelimit", "ratelimit", "retry-after")


def collect_rl_headers(raw_headers: dict[str, Any] | httpx.Headers) -> dict[str, Any]:
    """Extract all rate-limit-related headers as a lowercase-keyed dict."""
    return {
        k.lower(): v
        for k, v in raw_headers.items()
        if any(k.lower().startswith(p) for p in _RL_PREFIXES)
    }


def _parse_duration_str(s: str) -> float | None:
    """Parse Groq duration strings to seconds. '1m26.4s'->86.4, '170ms'->0.17."""
    m = _DURATION_RE.match(s.strip())
    if not m or not any(m.groups()):
        return None
    h, mins, secs, ms = m.groups()
    total = 0.0
    if h:
        total += float(h) * 3600
    if mins:
        total += float(mins) * 60
    if secs:
        total += float(secs)
    if ms:
        total += float(ms) / 1000
    return total if total > 0 else None


def _in(seconds: float) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()


def _next_utc_midnight() -> str:
    now = datetime.now(UTC)
    return (
        (now + timedelta(days=1))
        .replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        .isoformat()
    )


# ---------------------------------------------------------------------------
# Per-provider extractors
# Each returns an ISO cooldown_until timestamp or None (no cooldown needed).
# ---------------------------------------------------------------------------


def _groq(headers: dict[str, Any], was_429: bool) -> str | None:  # noqa: C901, FBT001
    # On 429, prefer explicit retry-after first
    if was_429:
        ra = headers.get("retry-after")
        if ra:
            try:
                return _in(float(ra))
            except (ValueError, TypeError):
                pass

    # Daily requests dimension (reset value is a duration string)
    remaining = headers.get("x-ratelimit-remaining-requests")
    reset_str = headers.get("x-ratelimit-reset-requests")

    try:
        remaining_int = int(remaining) if remaining is not None else None
    except (ValueError, TypeError):
        remaining_int = None

    if (remaining_int == 0 or was_429) and reset_str:
        secs = _parse_duration_str(reset_str)
        if secs is not None:
            return _in(secs)

    # Per-minute token dimension (short cooldown on token exhaustion only)
    if not was_429:
        rem_tok = headers.get("x-ratelimit-remaining-tokens")
        rst_tok = headers.get("x-ratelimit-reset-tokens")
        try:
            rem_tok_int = int(rem_tok) if rem_tok is not None else None
        except (ValueError, TypeError):
            rem_tok_int = None
        if rem_tok_int == 0 and rst_tok:
            secs = _parse_duration_str(rst_tok)
            if secs is not None:
                return _in(secs)

    return None


def _cerebras(headers: dict[str, Any], was_429: bool) -> str | None:  # noqa: FBT001
    # Check dimensions from longest to shortest; first exhausted wins
    checks = [
        ("x-ratelimit-remaining-requests-day", _next_utc_midnight),
        ("x-ratelimit-remaining-requests-hour", lambda: _in(3600)),
        ("x-ratelimit-remaining-requests-minute", lambda: _in(60)),
    ]
    for header, cooldown_fn in checks:
        val = headers.get(header)
        if val is not None:
            try:
                if int(val) == 0:
                    return cooldown_fn()
            except (ValueError, TypeError):
                pass

    if was_429:
        return _in(60)  # fallback when headers don't clarify which window

    return None


def _mistral(headers: dict[str, Any], was_429: bool) -> str | None:  # noqa: FBT001
    # Mistral uses "req" not "requests" in header names
    rem = headers.get("x-ratelimit-remaining-req-minute")
    if rem is not None:
        try:
            if int(rem) == 0:
                return _in(60)
        except (ValueError, TypeError):
            pass

    if was_429:
        return _in(60)

    return None


def _github_models(headers: dict[str, Any], was_429: bool) -> str | None:  # noqa: FBT001
    # GitHub Models uses standard x-ratelimit headers
    remaining = headers.get("x-ratelimit-remaining-requests")
    if remaining is not None:
        try:
            if int(remaining) == 0:
                return _next_utc_midnight()
        except (ValueError, TypeError):
            pass
    if was_429:
        return _in(60)
    return None


def _interfaze(headers: dict[str, Any], was_429: bool) -> str | None:  # noqa: FBT001
    """Parse Interfaze rate-limit headers: x-ratelimit-remaining-{requests,tokens}."""
    remaining = headers.get("x-ratelimit-remaining-requests")
    if remaining is not None:
        try:
            if int(remaining) == 0:
                return _in(60)
        except (ValueError, TypeError):
            pass
    if was_429:
        return _in(60)
    return None


_EXTRACTORS = {
    "groq": _groq,
    "cerebras": _cerebras,
    "mistral": _mistral,
    "github_models": _github_models,
    "interfaze": _interfaze,
}


def extract_cooldown(
    provider: str, headers: dict[str, Any], was_429: bool
) -> str | None:  # noqa: FBT001
    """Return ISO 8601 cooldown_until derived from response headers, or None.

    None means either headers don't indicate exhaustion, or no extractor exists
    for this provider (caller should apply config-driven fallback).
    """
    extractor = _EXTRACTORS.get(provider)
    if extractor is None:
        return None
    return extractor(headers, was_429)


def extract_remaining_requests(provider: str, headers: dict[str, Any]) -> int | None:
    """Most relevant 'remaining requests' count for CompletionResult.remaining_requests."""
    if provider == "groq":
        key = "x-ratelimit-remaining-requests"
    elif provider == "cerebras":
        key = "x-ratelimit-remaining-requests-day"
    elif provider == "mistral":
        key = "x-ratelimit-remaining-req-minute"
    elif provider in ("github_models", "interfaze"):
        key = "x-ratelimit-remaining-requests"
    else:
        key = "x-ratelimit-remaining-requests"

    val = headers.get(key)
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None
