"""Sticky sessions — route consecutive requests from the same session to the
same model+key combination unless it fails or the TTL expires.

Translated from FreeLLMAPI ``proxy.ts`` (in-memory Map pattern).
"""

from __future__ import annotations

import os
import time
import threading
from typing import Any

from ..config.loader import load_settings

_sticky_settings = load_settings().sticky
_STICKY_TTL_MS: list[int] = [_sticky_settings.sticky_ttl_ms]
_MAX_STICKY_ENTRIES: list[int] = [_sticky_settings.max_sticky_entries]


def get_sticky_ttl_ms() -> int:
    return _STICKY_TTL_MS[0]


def set_sticky_ttl_ms(ms: int) -> None:
    if ms < 1000:
        raise ValueError("sticky_ttl_ms must be >= 1000")
    _STICKY_TTL_MS[0] = ms


def get_max_sticky_entries() -> int:
    return _MAX_STICKY_ENTRIES[0]


def set_max_sticky_entries(n: int) -> None:
    if n < 1:
        raise ValueError("max_sticky_entries must be >= 1")
    _MAX_STICKY_ENTRIES[0] = n


def is_sticky_enabled() -> bool:
    """Check whether sticky sessions are active.

    Returns the runtime override if set (via ``set_sticky_enabled``),
    otherwise falls back to the ``FREELLMAPI_STICKY_SESSION`` env var
    (default ``True``).
    """
    override = _STICKY_OVERRIDE[0]
    if override is not None:
        return override
    raw = os.environ.get("FREELLMAPI_STICKY_SESSION", "").strip().lower()
    return raw != "off" and raw != "false" and raw != "0"


def set_sticky_enabled(val: bool) -> None:
    """Override the env toggle at runtime (e.g. from the settings API)."""
    _STICKY_OVERRIDE[0] = val


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------

StoreValue = dict[str, Any]  # {model_db_id, key_id, last_used_ms}

_store: dict[str, StoreValue] = {}
_lock = threading.Lock()
_STICKY_OVERRIDE: list[bool | None] = [None]


def _now() -> int:
    return int(time.time() * 1000)


def _prune() -> None:
    """Remove entries whose TTL has expired or that exceed the size cap."""
    now = _now()
    for key, val in list(_store.items()):
        if now - val["last_used_ms"] > _STICKY_TTL_MS[0]:
            del _store[key]
    max_entries = _MAX_STICKY_ENTRIES[0]
    if len(_store) > max_entries:
        sorted_items = sorted(_store.items(), key=lambda x: x[1]["last_used_ms"])
        for key, _ in sorted_items[: len(_store) - max_entries]:
            _store.pop(key, None)


def get_or_create(
    session_id: str,
    model_db_id: int,
    key_id: int,
) -> StoreValue:
    """Return the existing sticky entry for *session_id*, or create a new one.

    The caller is responsible for calling ``on_success()`` after a
    successful request to update the ``last_used_ms`` timestamp.
    """
    if not session_id:
        return {"model_db_id": model_db_id, "key_id": key_id, "last_used_ms": _now()}

    with _lock:
        _prune()
        existing = _store.get(session_id)
        if existing is not None:
            existing["last_used_ms"] = _now()
            return existing

        entry: StoreValue = {
            "model_db_id": model_db_id,
            "key_id": key_id,
            "last_used_ms": _now(),
        }
        _store[session_id] = entry
        return entry


def release(session_id: str) -> None:
    """Remove the sticky entry — called on error, failover, or explicit release."""
    if not session_id:
        return
    with _lock:
        _store.pop(session_id, None)


def on_success(session_id: str) -> None:
    """Update the ``last_used_ms`` timestamp after a successful request.

    Without this the entry will eventually expire via TTL pruning, but
    touching it proactively keeps active sessions alive.
    """
    if not session_id:
        return
    with _lock:
        entry = _store.get(session_id)
        if entry is not None:
            entry["last_used_ms"] = _now()


# ---------------------------------------------------------------------------
# Introspection (for the dashboard / API)
# ---------------------------------------------------------------------------


def get_all_sessions() -> list[dict[str, Any]]:
    """Return a snapshot of all active sticky sessions."""
    with _lock:
        _prune()
        return [
            {
                "session_id": sid,
                "model_db_id": v["model_db_id"],
                "key_id": v["key_id"],
                "last_used_ms": v["last_used_ms"],
            }
            for sid, v in _store.items()
        ]


def clear_all() -> None:
    """Drop every sticky session (used in tests)."""
    with _lock:
        _store.clear()


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _get_effective_setting() -> bool:
    return is_sticky_enabled()
