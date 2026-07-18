"""Context handoff — preserve conversation context when switching between models.

Translated from FreeLLMAPI ``server/src/services/context-handoff.ts``.
"""

from __future__ import annotations

import os
import time
import threading
from typing import Any

from ..config.loader import load_settings

_handoff_settings = load_settings().handoff
MAX_RECENT_MESSAGES = _handoff_settings.max_recent_messages
MAX_HANDOFF_CHARS = _handoff_settings.max_handoff_chars
MAX_CONTENT_PER_MSG = _handoff_settings.max_content_per_msg
SESSION_TTL_MS = _handoff_settings.session_ttl_ms
MAX_STORE_SIZE = _handoff_settings.max_store_size

# Exported so proxy/route can pad the routing token estimate for the
# injected handoff message before the context-window / TPM checks run.
HANDOFF_MAX_TOKENS = (MAX_HANDOFF_CHARS + 400) // 4


_HANDOFF_OVERRIDE: list[str | None] = [None]


def get_handoff_mode() -> str:
    """Return ``'on_model_switch'`` or ``'off'``.

    Uses runtime override first (set via ``set_handoff_mode``),
    then falls back to the ``FREELLMAPI_CONTEXT_HANDOFF`` env var.
    """
    override = _HANDOFF_OVERRIDE[0]
    if override is not None:
        return override
    raw = os.environ.get("FREELLMAPI_CONTEXT_HANDOFF", "").strip().lower()
    return "on_model_switch" if raw == "on_model_switch" else "off"


def set_handoff_mode(mode: str) -> None:
    """Override the handoff mode at runtime (e.g. from the settings API)."""
    if mode not in ("on_model_switch", "off"):
        raise ValueError(
            f"Invalid handoff mode: {mode!r}. Must be 'on_model_switch' or 'off'."
        )
    _HANDOFF_OVERRIDE[0] = mode


# ---------------------------------------------------------------------------
# In-memory session store
# ---------------------------------------------------------------------------

TrimmedMessage = dict[str, str]  # {role, content}
SessionContext = dict[str, Any]  # {lastModelKey, recentMessages[], updatedAt}

_store: dict[str, SessionContext] = {}
_lock = threading.Lock()


def _now() -> int:
    return int(time.time() * 1000)


def _safe_slice(text: str, max_len: int) -> str:
    """Slice without cutting through a UTF-16 surrogate pair.

    A bare ``str[:max]`` can land mid astral-plane char (emoji etc.)
    and some providers 400 on a lone high surrogate.
    """
    if len(text) <= max_len:
        return text
    last_code = ord(text[max_len - 1])
    end = max_len - 1 if 0xD800 <= last_code <= 0xDBFF else max_len
    return text[:end]


def _trim_content(content: Any) -> str:
    """Convert content to string and truncate to *MAX_CONTENT_PER_MSG* chars."""
    if isinstance(content, list):
        parts = [p.get("text", "") for p in content if isinstance(p, dict)]
        text = "".join(parts)
    elif isinstance(content, str):
        text = content
    else:
        text = str(content or "")
    if len(text) > MAX_CONTENT_PER_MSG:
        return _safe_slice(text, MAX_CONTENT_PER_MSG) + "…"
    return text


def _prune_expired() -> None:
    """Remove entries whose TTL has expired."""
    now = _now()
    for key, ctx in list(_store.items()):
        if now - ctx["updatedAt"] > SESSION_TTL_MS:
            del _store[key]


def _enforce_size_cap() -> None:
    """Enforce *MAX_STORE_SIZE* by evicting oldest entries."""
    if len(_store) <= MAX_STORE_SIZE:
        return
    sorted_items = sorted(_store.items(), key=lambda x: x[1]["updatedAt"])
    overflow = len(_store) - MAX_STORE_SIZE
    for key, _ in sorted_items[:overflow]:
        _store.pop(key, None)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def record_incoming(session_key: str, messages: list[dict[str, Any]]) -> None:
    """Store recent user/assistant turns from an incoming request.

    Mirrors FreeLLMAPI's ``recordIncomingMessages()``.
    """
    if not session_key:
        return
    with _lock:
        _prune_expired()

        trimmed = [
            {"role": m["role"], "content": _trim_content(m.get("content", ""))}
            for m in messages
            if m.get("role") in ("user", "assistant")
        ]
        trimmed = trimmed[-MAX_RECENT_MESSAGES:]

        has_assistant = any(m.get("role") == "assistant" for m in messages)
        existing = _store.get(session_key)
        if existing is not None:
            if not has_assistant:
                existing["lastModelKey"] = None
            existing["recentMessages"] = trimmed
            existing["updatedAt"] = _now()
        else:
            _store[session_key] = {
                "lastModelKey": None,
                "recentMessages": trimmed,
                "updatedAt": _now(),
            }

        _enforce_size_cap()


def has_prior_model(session_key: str) -> bool:
    """Check whether the session has a prior successful model on record."""
    if not session_key:
        return False
    ctx = _store.get(session_key)
    return bool(ctx and ctx.get("lastModelKey"))


def _build_summary(messages: list[TrimmedMessage]) -> str:
    """Build the handoff summary text."""
    lines = [
        f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
        for m in messages
    ]
    joined = "\n".join(lines)
    if len(joined) > MAX_HANDOFF_CHARS:
        return _safe_slice(joined, MAX_HANDOFF_CHARS) + "\n…[truncated]"
    return joined


def maybe_inject(
    session_key: str,
    messages: list[dict[str, Any]],
    selected_model_key: str,
) -> tuple[list[dict[str, Any]], bool, int]:
    """Inject a handoff system message when the model changes for a session.

    Returns ``(modified_messages, was_injected, injected_token_est)``.
    """
    mode = get_handoff_mode()
    if mode == "off" or not session_key:
        return messages, False, 0

    ctx = _store.get(session_key)
    if not ctx or not ctx.get("lastModelKey"):
        return messages, False, 0
    if ctx["lastModelKey"] == selected_model_key:
        return messages, False, 0

    # Detect if a handoff message is already present
    already = any(
        m.get("role") == "system"
        and (
            (
                isinstance(m.get("content"), str)
                and m["content"].startswith("llm-apipool context handoff:")
            )
            or (
                isinstance(m.get("content"), list)
                and any(
                    isinstance(p, dict)
                    and p.get("text", "").startswith("llm-apipool context handoff:")
                    for p in m["content"]
                )
            )
        )
        for m in messages
    )
    if already:
        return messages, False, 0

    summary = _build_summary(ctx.get("recentMessages", []))
    handoff_content = (
        "llm-apipool context handoff:\n"
        f"You are taking over an ongoing conversation from another model ({ctx['lastModelKey']} → {selected_model_key}).\n"
        "Continue the user's task using the conversation context already provided in this request.\n"
        "Do not restart the task, re-ask already answered setup questions, or discard prior tool results.\n"
        "Respect the user's latest message as the highest-priority instruction.\n"
        "\n"
        "Recent session summary:\n"
        f"{summary}"
    )

    handoff_msg: dict[str, Any] = {"role": "system", "content": handoff_content}

    # Insert after leading system messages (preserve provider system-prompt ordering)
    insert_at = next(
        (i for i, m in enumerate(messages) if m.get("role") != "system"),
        len(messages),
    )

    result = list(messages)
    result.insert(insert_at, handoff_msg)
    return result, True, (len(handoff_content) + 3) // 4


def record_successful(session_key: str, model_key: str) -> None:
    """Record the model that handled a request for this session.

    Mirrors FreeLLMAPI's ``recordSuccessfulModel()``.
    """
    if not session_key:
        return
    with _lock:
        _prune_expired()
        ctx = _store.get(session_key)
        if ctx is not None:
            ctx["lastModelKey"] = model_key
            ctx["updatedAt"] = _now()
        else:
            _store[session_key] = {
                "lastModelKey": model_key,
                "recentMessages": [],
                "updatedAt": _now(),
            }
            _enforce_size_cap()


# ---------------------------------------------------------------------------
# Introspection (dashboard / API) & testing helpers
# ---------------------------------------------------------------------------


def get_all_sessions() -> list[dict[str, Any]]:
    """Return a snapshot of all active handoff sessions."""
    with _lock:
        _prune_expired()
        return [
            {
                "session_key": k,
                "last_model_key": v.get("lastModelKey"),
                "recent_count": len(v.get("recentMessages", [])),
                "updated_at_ms": v["updatedAt"],
            }
            for k, v in _store.items()
        ]


def clear_all() -> None:
    """Drop all handoff state (used in tests)."""
    with _lock:
        _store.clear()
