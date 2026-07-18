"""SlimeyRouter — QoS-based routing engine.

Tracks TTFT + throughput per UID-provider pair.
If QoS degrades outside user's acceptable spectrum, unpins and falls back.
"""

from __future__ import annotations

import time
import threading
from collections import defaultdict
from typing import Any


class SlimeyRouter:
    """QoS-based routing: tracks TTFT + throughput per UID-provider pair.
    If QoS degrades outside user's acceptable spectrum, unpins and falls back."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # uid -> (provider, model, key_id, slot_index)
        self._uid_pins: dict[str, tuple[str, str, int, int]] = {}
        # (uid, provider, model) -> qos history
        self._qos_history: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(
            lambda: {
                "ttft_samples": [],
                "throughput_samples": [],
                "last_ttft": 0,
                "last_throughput": 0,
                "total_requests": 0,
                "failed_requests": 0,
                "last_error_time": 0.0,
            }
        )
        self._slots: dict[int, str | None] = {i: None for i in range(10)}
        self._SLIMEY_OVERRIDE: list[bool | None] = [None]
        self._max_ttft_ms: list[int] = [5000]  # max acceptable TTFT
        self._min_throughput: list[int] = [10]  # min acceptable tokens/second
        self._MAX_SLOTS = 10
        self._ERROR_RESET_SECS = 300  # 5 min before retrying a failed provider

    def is_enabled(self) -> bool:
        if self._SLIMEY_OVERRIDE[0] is not None:
            return self._SLIMEY_OVERRIDE[0]
        return False

    def set_enabled(self, val: bool) -> None:
        self._SLIMEY_OVERRIDE[0] = val
        if val:
            self._reset()

    def get_qos_config(self) -> dict[str, int]:
        return {
            "max_ttft_ms": self._max_ttft_ms[0],
            "min_throughput": self._min_throughput[0],
        }

    def set_qos_config(self, max_ttft_ms: int, min_throughput: int) -> None:
        self._max_ttft_ms[0] = max(100, min(max_ttft_ms, 30000))
        self._min_throughput[0] = max(1, min(min_throughput, 10000))

    def _reset(self) -> None:
        self._uid_pins.clear()
        self._qos_history.clear()
        self._slots = {i: None for i in range(self._MAX_SLOTS)}

    def available_slots(self) -> int:
        with self._lock:
            return sum(1 for v in self._slots.values() if v is None)

    def get_pin(self, uid: str) -> tuple[str, str, int, int] | None:
        """Returns (provider, model, key_id, slot_index) if pinned."""
        with self._lock:
            return self._uid_pins.get(uid)

    def try_pin(
        self, uid: str, provider: str, model: str, key_id: int
    ) -> bool:
        """Try to pin a UID to a provider+model. Returns True if pinned."""
        with self._lock:
            if uid in self._uid_pins:
                return True  # already pinned
            for slot_idx, owner in self._slots.items():
                if owner is None:
                    self._slots[slot_idx] = uid
                    self._uid_pins[uid] = (provider, model, key_id, slot_idx)
                    return True
            return False  # all slots full

    def record_ttft(
        self, uid: str, provider: str, model: str, ttft_ms: float
    ) -> None:
        with self._lock:
            key = (uid, provider, model)
            hist = self._qos_history[key]
            hist["ttft_samples"].append(ttft_ms)
            hist["last_ttft"] = ttft_ms
            hist["total_requests"] += 1
            # Keep last 20 samples
            if len(hist["ttft_samples"]) > 20:
                hist["ttft_samples"].pop(0)

    def record_throughput(
        self, uid: str, provider: str, model: str, tokens_per_sec: float
    ) -> None:
        with self._lock:
            key = (uid, provider, model)
            hist = self._qos_history[key]
            hist["throughput_samples"].append(tokens_per_sec)
            hist["last_throughput"] = tokens_per_sec
            if len(hist["throughput_samples"]) > 20:
                hist["throughput_samples"].pop(0)

    def record_error(self, uid: str, provider: str, model: str) -> None:
        with self._lock:
            key = (uid, provider, model)
            self._qos_history[key]["failed_requests"] += 1
            self._qos_history[key]["last_error_time"] = time.time()
            # Unpin on error
            if uid in self._uid_pins:
                _, _, _, slot_idx = self._uid_pins.pop(uid)
                self._slots[slot_idx] = None

    def is_qos_acceptable(
        self, uid: str, provider: str, model: str
    ) -> bool:
        """Check if current QoS is within user's acceptable spectrum."""
        with self._lock:
            key = (uid, provider, model)
            hist = self._qos_history.get(key)
            if not hist or hist["total_requests"] == 0:
                return True  # No data yet, assume acceptable

            # Check if provider recently errored
            if time.time() - hist["last_error_time"] < self._ERROR_RESET_SECS:
                return False

            # Check TTFT (use recent samples, then last)
            if hist["ttft_samples"]:
                avg_ttft = sum(hist["ttft_samples"][-5:]) / max(
                    len(hist["ttft_samples"][-5:]), 1
                )
                if avg_ttft > self._max_ttft_ms[0]:
                    return False

            # Check throughput
            if hist["throughput_samples"]:
                avg_tp = sum(hist["throughput_samples"][-5:]) / max(
                    len(hist["throughput_samples"][-5:]), 1
                )
                if avg_tp < self._min_throughput[0]:
                    return False

            return True

    def get_state_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self.is_enabled(),
                "max_ttft_ms": self._max_ttft_ms[0],
                "min_throughput": self._min_throughput[0],
                "available_slots": self.available_slots(),
                "total_slots": self._MAX_SLOTS,
                "active_pins": len(self._uid_pins),
                "pins": {
                    k: {"provider": v[0], "model": v[1], "slot": v[3]}
                    for k, v in self._uid_pins.items()
                },
            }


_slimey_router = SlimeyRouter()


def get_slimey_router() -> SlimeyRouter:
    return _slimey_router
