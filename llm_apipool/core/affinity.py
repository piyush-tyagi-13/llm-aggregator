"""Affinity routing — UID-based key+model pinning with busy/semi-busy tracking.

Replaces sticky sessions when enabled (mutually exclusive).
- 5 concurrent request slots
- Keys marked ``busy`` while processing, ``semi-busy`` for 60s after completion
- A UID gets pinned to the first successful (key, model_db_id) pair
- Subsequent requests with the same UID reuse that pair unless it errors
- Busy + semi-busy keys are excluded from routing
"""

from __future__ import annotations

import os
import time
import threading
from typing import Any, Literal

_MAX_SLOTS = 5
_SEMI_BUSY_SECS = 60

KeyState = Literal["idle", "busy", "semi_busy"]

# (key_id, model_name) → state
_key_states: dict[tuple[int, str], KeyState] = {}
_key_semi_expiry: dict[tuple[int, str], float] = {}

# uid → (key_id, model_name, slot_index)
_uid_map: dict[str, tuple[int, str, int]] = {}

# slot management
_slot_owners: dict[int, str | None] = {}  # slot_index → uid or None
_next_slot: int = 0
_lock = threading.RLock()  # Reentrant lock to allow nested acquire
_AFFINITY_OVERRIDE: list[bool | None] = [None]


def _now() -> float:
    return time.time()


def is_affinity_enabled() -> bool:
    """Check whether affinity routing is active."""
    override = _AFFINITY_OVERRIDE[0]
    if override is not None:
        return override
    raw = os.environ.get("LLM_AFFINITY_ROUTING", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def set_affinity_enabled(val: bool) -> None:
    """Enable or disable affinity routing at runtime."""
    _AFFINITY_OVERRIDE[0] = val
    if val:
        _reset()


def _reset() -> None:
    """Reset all affinity state."""
    _key_states.clear()
    _key_semi_expiry.clear()
    _uid_map.clear()
    _slot_owners.clear()
    for i in range(_MAX_SLOTS):
        _slot_owners[i] = None


def available_slots() -> int:
    """Return how many concurrent request slots are free."""
    with _lock:
        taken = sum(1 for v in _slot_owners.values() if v is not None)
        return _MAX_SLOTS - taken


def is_key_available(key_id: int, model_name: str) -> bool:
    """Check if a (key, model) pair is available for routing."""
    pair = (key_id, model_name)
    with _lock:
        state = _key_states.get(pair)
        if state == "busy":
            return False
        if state == "semi_busy":
            expiry = _key_semi_expiry.get(pair, 0)
            if _now() < expiry:
                return False
            # Expired — clear it
            _key_states[pair] = "idle"
            _key_semi_expiry.pop(pair, None)
            return True
        return True


def register_request(uid: str, key_id: int, model_name: str) -> bool:
    """Register a new request for *uid* using *key_id/model_name*.

    Tries to acquire a slot. Returns True if a slot was available.
    On success marks the key as busy.
    """
    if not uid:
        return False
    with _lock:
        if available_slots() <= 0:
            return False
        for slot_idx in range(_MAX_SLOTS):
            if _slot_owners.get(slot_idx) is None:
                _slot_owners[slot_idx] = uid
                break
        else:
            return False

        pair = (key_id, model_name)
        _key_states[pair] = "busy"
        _uid_map[uid] = (key_id, model_name, slot_idx)
        return True


def register_no_uid(key_id: int, model_name: str) -> bool:
    """Register a request without a UID — just mark the key busy.

    Returns True if a slot was available.
    """
    with _lock:
        if available_slots() <= 0:
            return False
        for slot_idx in range(_MAX_SLOTS):
            if _slot_owners.get(slot_idx) is None:
                _slot_owners[slot_idx] = "_no_uid"
                break
        else:
            return False
        _key_states[(key_id, model_name)] = "busy"
        return True


def get_uid_pin(uid: str) -> tuple[int, str, int] | None:
    """Return the pinned (key_id, model_name, slot_index) for a UID, or None."""
    with _lock:
        pinned = _uid_map.get(uid)
        if pinned is None:
            return None
        key_id, model_name, slot_idx = pinned
        if _slot_owners.get(slot_idx) != uid:
            return None
        pair = (key_id, model_name)
        state = _key_states.get(pair)
        if state not in ("busy", "semi_busy"):
            return None
        return pinned


def on_success(uid: str, key_id: int, model_name: str) -> None:
    """Mark a (key, model) pair as semi-busy for 60s after success.

    Also releases the slot so new requests can enter.
    """
    with _lock:
        pair = (key_id, model_name)
        _key_states[pair] = "semi_busy"
        _key_semi_expiry[pair] = _now() + _SEMI_BUSY_SECS
        pinned = _uid_map.pop(uid, None) if uid else None
        if pinned:
            _slot_owners[pinned[2]] = None
        else:
            for slot_idx, owner in list(_slot_owners.items()):
                if owner == uid:
                    _slot_owners[slot_idx] = None
                    break
        if uid:
            _uid_map[uid] = (key_id, model_name, -1)


def on_error(uid: str, key_id: int, model_name: str) -> None:
    """Handle an error for a (key, model) pair.

    Removes the pin so the UID gets reassigned on next attempt.
    The key itself may still be on cooldown (handled by rotator).
    """
    with _lock:
        pair = (key_id, model_name)
        _key_states.pop(pair, None)
        _key_semi_expiry.pop(pair, None)
        pinned = _uid_map.pop(uid, None) if uid else None
        if pinned:
            _slot_owners[pinned[2]] = None
        else:
            for slot_idx, owner in list(_slot_owners.items()):
                if owner == uid:
                    _slot_owners[slot_idx] = None
                    break


def release_no_uid(key_id: int, model_name: str) -> None:
    """Release a no-UID request — mark as semi-busy."""
    with _lock:
        pair = (key_id, model_name)
        _key_states[pair] = "semi_busy"
        _key_semi_expiry[pair] = _now() + _SEMI_BUSY_SECS
        for slot_idx, owner in list(_slot_owners.items()):
            if owner == "_no_uid":
                _slot_owners[slot_idx] = None
                break


# ── Introspection ─────────────────────────────────────────────────────


def get_state_snapshot() -> dict[str, Any]:
    """Return a snapshot of all affinity state for the dashboard."""
    with _lock:
        busy = []
        semi = []
        for (key_id, mname), state in _key_states.items():
            if state == "busy":
                busy.append({"key_id": key_id, "model_name": mname})
            elif state == "semi_busy":
                expiry = _key_semi_expiry.get((key_id, mname), 0)
                remaining = max(0, int(expiry - _now()))
                semi.append(
                    {"key_id": key_id, "model_name": mname, "remaining_secs": remaining}
                )
        taken = sum(1 for v in _slot_owners.values() if v is not None)
        available = _MAX_SLOTS - taken
        return {
            "enabled": is_affinity_enabled(),
            "available_slots": available,
            "total_slots": _MAX_SLOTS,
            "busy": busy,
            "semi_busy": semi,
            "pinned_uids": len(_uid_map),
        }
