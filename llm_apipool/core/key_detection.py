"""Key format detection — identify provider(s) from an API key string.

Heuristics
----------
Some providers issue keys with distinctive prefixes that uniquely identify
them (:data:`UNIQUE_PREFIXES`).  Many OpenAI-compatible providers all use the
same ``sk-`` prefix, making them ambiguous — for those we probe each candidate
with a lightweight API call to determine the true owner.

Flow
----
1. Trim whitespace, skip blank lines, strip trailing ``***`` from masked keys.
2. Check :data:`UNIQUE_PREFIXES` — if exactly one match → **auto**.
3. Check for ``sk-`` prefix → **probe** all OpenAI-compatible providers.
4. Otherwise → **unknown**.
"""

from __future__ import annotations

import re
from typing import Any

# ── Known unique key prefixes → provider name ─────────────────────────
# These formats are distinctive enough that we can auto-assign without
# making any network call.
UNIQUE_PREFIXES: dict[str, str] = {
    "sk-paxsenix-": "paxsenix",
    "sk-proj-": "openai",
    "sk-ant-": "anthropic",
    "AIzaSy": "google",
    "AIza": "google",
    "pplx-": "openrouter",  # Perplexity — proxied
    "xai-": "openrouter",  # xAI/Grok — proxied
    "hf_": "huggingface_router",
    "gsk_": "groq",
    "gsk-": "groq",
    "cs_": "cerebras",
    "cs-": "cerebras",
}

# OpenAI *project* keys follow the pattern sk-proj-XXXXXXXXXXXX
_PROJECT_KEY_RE = re.compile(r"^sk-proj-[A-Za-z0-9]{20,}$")

# General OpenAI-compatible key format
_OPENAI_KEY_RE = re.compile(r"^sk-[A-Za-z0-9\-_]{15,}$")

# Cohere key format
_COHERE_KEY_RE = re.compile(r"^[A-Za-z0-9+/]{40,}={0,2}$")

# Cloudflare — no fixed prefix but always starts with a UUID-like pattern
_CLOUDFLARE_KEY_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


def sanitise_key(raw: str) -> str:
    """Strip whitespace and trailing masked characters (``***``)."""
    key = raw.strip()
    # Remove trailing *** (user masked the key)
    if key.endswith("***"):
        key = key[:-3].rstrip("*").strip()
    # Remove trailing * (partial mask)
    key = key.rstrip("*").strip()
    return key


def detect_candidates(key: str, configs: dict[str, Any] | None = None) -> list[str]:
    """Return list of probable provider names for *key*.

    * ``["provider_name"]`` — unique match, no probing needed.
    * ``["provider_a", "provider_b", ...]`` — ambiguous, needs probing.
    * ``[]`` — unrecognised format.
    """
    # 1. Unique prefix check
    for prefix, provider in UNIQUE_PREFIXES.items():
        if key.startswith(prefix):
            return [provider]

    # 2. ``sk-`` prefix — any OpenAI-compatible provider
    if _OPENAI_KEY_RE.match(key) or _PROJECT_KEY_RE.match(key):
        return _openai_compatible_names(configs)

    # 3. Cohere-style base64 key
    if _COHERE_KEY_RE.match(key):
        return ["cohere"]

    # 4. Cloudflare UUID-style
    if _CLOUDFLARE_KEY_RE.match(key):
        return ["cloudflare"]

    return []


def classify_key(
    key: str,
    configs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify a single key into a structured result.

    Returns::
        {"key": "...", "candidates": [...], "status": "auto"|"probe"|"unknown"}
    """
    raw = sanitise_key(key)
    if not raw:
        return {"key": key, "candidates": [], "status": "skip"}
    candidates = detect_candidates(raw, configs)

    if len(candidates) == 1:
        return {"key": raw, "candidates": candidates, "status": "auto"}
    if len(candidates) > 1:
        return {"key": raw, "candidates": candidates, "status": "probe"}
    return {"key": raw, "candidates": [], "status": "unknown"}


def analyse_bulk(
    text: str,
    configs: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Process a bulk-import text blob and classify every key.

    Each line is treated as one key.  Blank lines are skipped.
    Returns a list of :meth:`classify_key` results.
    """
    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    for line in text.splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or raw.startswith("//"):
            continue  # skip blanks and comments

        if raw in seen:
            continue
        seen.add(raw)

        results.append(classify_key(raw, configs))

    return results


# ── Internal helpers ──────────────────────────────────────────────────

_OPENAI_COMPAT_CACHE: list[str] | None = None


def _openai_compatible_names(configs: dict[str, Any] | None) -> list[str]:
    """Return a sorted list of all providers with ``openai_compatible: true``."""
    global _OPENAI_COMPAT_CACHE
    if _OPENAI_COMPAT_CACHE is not None and configs is None:
        return _OPENAI_COMPAT_CACHE
    if configs is None:
        return []

    result = sorted(
        name for name, cfg in configs.items() if cfg.get("openai_compatible")
    )
    _OPENAI_COMPAT_CACHE = result
    return result


def _clear_cache() -> None:
    """For testing only."""
    global _OPENAI_COMPAT_CACHE
    _OPENAI_COMPAT_CACHE = None


__all__ = [
    "UNIQUE_PREFIXES",
    "sanitise_key",
    "detect_candidates",
    "classify_key",
    "analyse_bulk",
]
