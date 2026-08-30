import json
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Callable

from .key_store import KeyStore
from .providers.headers import extract_cooldown


def _next_utc_midnight() -> str:
    now = datetime.now(timezone.utc)
    return (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).isoformat()


def _next_first_of_month() -> str:
    now = datetime.now(timezone.utc)
    month = now.month + 1
    year  = now.year + (1 if month > 12 else 0)
    month = 1 if month > 12 else month
    return now.replace(
        year=year, month=month, day=1,
        hour=0, minute=0, second=0, microsecond=0,
    ).isoformat()


def _rolling(seconds: int) -> Callable[[], str]:
    def _inner() -> str:
        return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
    return _inner


_FALLBACK_STRATEGIES = {
    "daily_utc_midnight":      _next_utc_midnight,
    "first_of_calendar_month": _next_first_of_month,
    "rolling_60":              _rolling(60),
    "rolling_65":              _rolling(65),
    "rolling_120":             _rolling(120),
}
_DEFAULT_FALLBACK = _rolling(60)


def _fallback_from_config(cfg: dict) -> Callable[[], str]:
    key = cfg.get("cooldown_fallback", {}).get("strategy", "rolling_60")
    return _FALLBACK_STRATEGIES.get(key, _DEFAULT_FALLBACK)


def _score_key(key: dict, cfg: dict) -> float:
    rpd = cfg.get("limits", {}).get("rpd")
    return float(rpd - key["requests_today"]) if rpd else float(-key["requests_today"])


def _resolve_model(cfg: dict, cap_key: str) -> str:
    models = cfg.get("models", {})
    if isinstance(models, list):
        return models[0] if models else ""
    if isinstance(models, dict):
        cat_models = models.get(cap_key, [])
        return cat_models[0] if cat_models else ""
    return cfg.get("default_model", "")


def _cap_key(capabilities: list[str]) -> str:
    """Canonical string key for a capabilities set, used as rotation state key."""
    return ",".join(sorted(capabilities))


class Rotator:
    def __init__(self, store: KeyStore, provider_configs: dict, rotate_every: int = 5):
        self.store = store
        self.configs = provider_configs
        self.rotate_every = rotate_every

        self._order: dict[str, list[int]] = {}
        self._cursor: dict[str, int] = {}
        # slot_count indexed per cap_key to avoid cross-voice pollution
        # (fast/agentic/general_purpose share the same keys but must rotate
        # independently — see issue #10)
        self._slot_count: dict[str, dict[int, int]] = {}
        self._loaded_cap_keys: set[str] = set()
        # track which cap_key context each key_id was last selected under
        self._key_last_cap_key: dict[int, str] = {}

    def _slot(self, ck: str) -> dict[int, int]:
        return self._slot_count.setdefault(ck, {})

    def _load_state(self, ck: str):
        if ck in self._loaded_cap_keys:
            return
        cursor, slot_counts = self.store.load_rotation_state(ck)
        self._cursor[ck] = cursor
        # slot_counts are now scoped per cap_key (issue #10)
        self._slot_count[ck] = slot_counts
        self._loaded_cap_keys.add(ck)

    def _persist_state(self, ck: str):
        self.store.save_rotation_state(
            ck,
            self._cursor.get(ck, 0),
            self._slot_count.get(ck, {}),
        )

    def _ensure_order(self, ck: str, capabilities: list[str], active_ids: set[int]):
        self._load_state(ck)
        current = self._order.get(ck, [])
        if set(current) == active_ids:
            return
        all_keys = self.store.get_all_keys()
        ordered = sorted(
            [
                k for k in all_keys
                if k["is_active"] and any(
                    c in self.store.parse_capabilities(k) for c in capabilities
                )
            ],
            key=lambda k: _score_key(k, self.configs.get(k["provider"], {})),
            reverse=True,
        )
        self._order[ck] = [k["id"] for k in ordered]
        if ck not in self._cursor:
            self._cursor[ck] = 0
        else:
            self._cursor[ck] %= max(len(self._order[ck]), 1)
        for k in ordered:
            self._slot(ck).setdefault(k["id"], 0)

    def get_best_key(
        self,
        capabilities: list[str] | str,
        subscriber_id: str = "unknown",
    ) -> Optional[dict]:
        if isinstance(capabilities, str):
            capabilities = [capabilities]
        ck = _cap_key(capabilities)
        active = self.store.get_active_keys(capabilities)
        if not active:
            return None

        active_map = {k["id"]: k for k in active}
        self._ensure_order(ck, capabilities, set(active_map.keys()))

        order  = self._order[ck]
        cursor = self._cursor.get(ck, 0) % len(order)
        slots = self._slot(ck)

        # Bug 1 (issue #9): the old reset compared the advanced `cursor` against
        # `_cursor[ck]` which was already overwritten at the end of the previous
        # call, so the reset never fired and the last provider repeated forever.
        # Fix: scan one full cycle; if every provider is saturated, reset this
        # cap_key's slot_count and advance the cursor by one so the last
        # saturated provider is not immediately re-selected.
        scanned = 0
        while True:
            key_id = order[cursor % len(order)]
            if key_id in active_map and slots.get(key_id, 0) < self.rotate_every:
                break
            cursor = (cursor + 1) % len(order)
            scanned += 1
            if scanned >= len(order):
                for kid in order:
                    slots[kid] = 0
                scanned = 0
                cursor = (cursor + 1) % len(order)
                if all(slots.get(order[c], 0) >= self.rotate_every for c in range(len(order))):
                    break
        else:
            return None

        self._cursor[ck] = cursor
        best = active_map[order[cursor]]
        cfg   = self.configs.get(best["provider"], {})
        extra = json.loads(best["extra_params"] or "{}")

        base_url = cfg.get("base_url", "")
        if "{account_id}" in base_url:
            base_url = base_url.format(account_id=extra.get("account_id", ""))

        slot_pos = slots.get(best["id"], 0) + 1
        self._key_last_cap_key[best["id"]] = ck

        return {
            "key_id":            best["id"],
            "provider":          best["provider"],
            "api_key":           best["api_key"],
            "base_url":          base_url,
            "model":             best["model"] or _resolve_model(cfg, ck),
            "capabilities":      self.store.parse_capabilities(best),
            "cap_key":           ck,
            "subscriber_id":     subscriber_id,
            "openai_compatible": cfg.get("openai_compatible", True),
            "extra_params":      extra,
            "requests_today":    best["requests_today"],
            "tokens_used_today": best["tokens_used_today"],
            "cycle_position":    slot_pos,
            "rotate_every":      self.rotate_every,
        }

    def peek_current_key(self, capabilities: list[str] | str) -> Optional[dict]:
        """Return the key that would be selected next without mutating state."""
        if isinstance(capabilities, str):
            capabilities = [capabilities]
        ck = _cap_key(capabilities)
        active = self.store.get_active_keys(capabilities)
        if not active:
            return None

        active_map = {k["id"]: k for k in active}
        self._ensure_order(ck, capabilities, set(active_map.keys()))

        order      = self._order[ck]
        cursor     = self._cursor.get(ck, 0) % len(order)
        slot_count = dict(self._slot_count)

        for _ in range(len(order) + 1):
            key_id = order[cursor % len(order)]
            if key_id in active_map and slot_count.get(key_id, 0) < self.rotate_every:
                break
            cursor = (cursor + 1) % len(order)
        else:
            return None

        best = active_map[order[cursor]]
        cfg  = self.configs.get(best["provider"], {})
        slot_pos = slot_count.get(best["id"], 0) + 1
        return {
            "key_id":            best["id"],
            "provider":          best["provider"],
            "model":             best["model"] or _resolve_model(cfg, ck),
            "capabilities":      self.store.parse_capabilities(best),
            "requests_today":    best["requests_today"],
            "tokens_used_today": best["tokens_used_today"],
            "cooldown_until":    best.get("cooldown_until"),
            "cycle_position":    slot_pos,
            "rotate_every":      self.rotate_every,
        }

    def handle_429(
        self,
        key_id: int,
        provider: str,
        headers: dict | None = None,
        subscriber_id: str = "unknown",
        model: str = "",
    ) -> str:
        headers = headers or {}
        cooldown = extract_cooldown(provider, headers, was_429=True)
        if cooldown is None:
            cfg = self.configs.get(provider, {})
            cooldown = _fallback_from_config(cfg)()
        self.store.record_usage(key_id, tokens=0, was_429=True, cooldown_until=cooldown)
        # Bug 2 (issue #10): scope slot_count to the cap_key that actually
        # consumed the request, so a 429 in one voice does not pollute the
        # other voice's rotation. The cooldown (get_active_keys) already
        # excludes the key from all voices.
        ck = self._key_last_cap_key.get(key_id, "")
        if ck:
            self._slot(ck)[key_id] = self._slot(ck).get(key_id, 0) + 1
            self._persist_state(ck)
        self.store.log_audit(
            subscriber_id=subscriber_id,
            key_id=key_id,
            provider=provider,
            model=model,
            success=False,
            error="429 rate limit",
        )
        return cooldown

    def handle_success(
        self,
        key_id: int,
        tokens_used: int,
        headers: dict | None = None,
        provider: str = "",
        tokens_in: int = 0,
        latency_ms: int = 0,
        subscriber_id: str = "unknown",
        model: str = "",
    ):
        headers = headers or {}
        cooldown = extract_cooldown(provider, headers, was_429=False) if provider else None
        self.store.record_usage(key_id, tokens=tokens_used, was_429=False, cooldown_until=cooldown)
        # Bug 2 (issue #10): same scoping fix as handle_429.
        ck = self._key_last_cap_key.get(key_id, "")
        if ck:
            self._slot(ck)[key_id] = self._slot(ck).get(key_id, 0) + 1
            self._persist_state(ck)
        self.store.log_audit(
            subscriber_id=subscriber_id,
            key_id=key_id,
            provider=provider,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_used,
            latency_ms=latency_ms,
            success=True,
        )

    def get_earliest_retry(self, capabilities: list[str] | str) -> Optional[str]:
        if isinstance(capabilities, str):
            capabilities = [capabilities]
        all_keys = self.store.get_all_keys()
        cooldowns = [
            k["cooldown_until"] for k in all_keys
            if k["is_active"] and k["cooldown_until"]
            and any(c in self.store.parse_capabilities(k) for c in capabilities)
        ]
        return min(cooldowns) if cooldowns else None
