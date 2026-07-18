"""Key rotation and rate-limit-aware key selection with model quality tiering."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from typing import Any

from .key_store import KeyStore
from .providers.headers import extract_cooldown
from .core.affinity import (
    is_affinity_enabled,
    is_key_available,
)

logger = logging.getLogger(__name__)


def _tier_fallback_allowed() -> bool:
    """Check whether tier fallback is currently enabled (runtime toggle)."""
    try:
        from .core.tier_fallback import is_tier_fallback_enabled

        return is_tier_fallback_enabled()
    except ImportError:
        logger.debug("tier_fallback module not available, fallback allowed")
        return True  # safe default - module not available yet


MONTHS_IN_YEAR = 12
MIN_QUALITY_TIER = 1
MAX_QUALITY_TIER = 4


def _get_model_features(model_name: str) -> dict[str, Any] | None:
    """Get model features from metadata cache."""
    try:
        from llm_apipool.core.model_metadata import get_model_features

        return get_model_features(model_name)
    except ImportError:
        logger.debug("model_metadata module not available")
        return None


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


def _next_first_of_month() -> str:
    now = datetime.now(UTC)
    month = now.month + 1
    year = now.year + (1 if month > MONTHS_IN_YEAR else 0)
    month = 1 if month > MONTHS_IN_YEAR else month
    return now.replace(
        year=year,
        month=month,
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    ).isoformat()


def _rolling(seconds: int) -> Callable[[], str]:
    def _inner() -> str:
        return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()

    return _inner


_FALLBACK_STRATEGIES = {
    "daily_utc_midnight": _next_utc_midnight,
    "first_of_calendar_month": _next_first_of_month,
    "rolling_60": _rolling(60),
    "rolling_65": _rolling(65),
    "rolling_120": _rolling(120),
}
_DEFAULT_FALLBACK = _rolling(60)

# ---------------------------------------------------------------------------
# Model quality tiers
# ---------------------------------------------------------------------------

_MODEL_TIER_MAP: dict[str, int] | None = None
_MODEL_TIER_MTIME: float = 0
_MODEL_TIER_PATH = Path(__file__).parent / "config" / "model_quality.json"


def _load_model_tiers(*, force_reload: bool = False) -> dict[str, int]:
    """Load model → tier mapping from model_quality.json.

    Returns a dict of {model_name: tier_number (1-4)}.
    Returns an empty dict if the file is missing or unparseable.

    Uses mtime-based cache invalidation so tier changes made via the
    API (which writes to the JSON file) are picked up automatically.
    """
    global _MODEL_TIER_MAP, _MODEL_TIER_MTIME  # noqa: PLW0603
    if not _MODEL_TIER_PATH.exists():
        _MODEL_TIER_MAP = {}
        return _MODEL_TIER_MAP

    current_mtime = _MODEL_TIER_PATH.stat().st_mtime

    if (
        not force_reload
        and _MODEL_TIER_MAP is not None
        and current_mtime <= _MODEL_TIER_MTIME
    ):
        return _MODEL_TIER_MAP

    try:
        with _MODEL_TIER_PATH.open() as f:
            data = json.load(f)
        result: dict[str, int] = {}
        for tier_key in ("tier1", "tier2", "tier3", "tier4"):
            tier_num = int(tier_key[-1])  # "tier1" → 1
            for model in data.get(tier_key, []):
                result[model] = tier_num
        _MODEL_TIER_MAP = result
        _MODEL_TIER_MTIME = current_mtime
    except (OSError, json.JSONDecodeError):
        _MODEL_TIER_MAP = {}
        _MODEL_TIER_MTIME = current_mtime
    return _MODEL_TIER_MAP


def get_model_tier(model: str) -> int:
    """Return the quality tier (1 = best, 4 = worst) for a model name.

    Falls back to tier 4 for unknown / unrecognised models.
    """
    tier_map = _load_model_tiers()
    return tier_map.get(model, 4)


def _fallback_from_config(cfg: dict[str, Any]) -> Callable[[], str]:
    key = cfg.get("cooldown_fallback", {}).get("strategy", "rolling_60")
    return _FALLBACK_STRATEGIES.get(key, _DEFAULT_FALLBACK)


def _score_key(key: dict[str, Any], cfg: dict[str, Any]) -> float:
    rpd = cfg.get("limits", {}).get("rpd")
    return float(rpd - key["requests_today"]) if rpd else float(-key["requests_today"])


def _key_priority(key: dict[str, Any]) -> int:
    """Get priority for a key, defaulting to 0 if not set."""
    return key.get("priority") or 0


def _resolve_model(cfg: dict[str, Any], cap_key: str) -> str:
    """Resolve the default model for a provider config.

    Model catalogues are synced live from provider /v1/models endpoints
    and stored in the DB.  The config only carries ``default_model`` for
    routing purposes — no hardcoded model lists.
    """
    return str(cfg.get("default_model", ""))


def _cap_key(capabilities: list[str]) -> str:
    """Canonical string key for a capabilities set, used as rotation state key."""
    return ",".join(sorted(capabilities))


class Rotator:
    """Selects best key by model quality tier, handles 429 cooldowns, and rotates evenly."""

    def __init__(
        self,
        store: KeyStore,
        provider_configs: dict[str, Any],
        rotate_every: int = 5,
        quality_tier: int = 1,
        max_fallback_tier: int = 4,
    ) -> None:
        """Initialize the Rotator.

        Parameters
        ----------
        store:
            KeyStore instance.
        provider_configs:
            Provider configuration dict (from providers.json).
        rotate_every:
            Requests per key before forcing a rotation.
        quality_tier:
            Preferred model quality tier (1 = best). The rotator will try
            this tier first and fall back through worse tiers when keys are exhausted.
        max_fallback_tier:
            Worst tier the rotator is allowed to fall back to (inclusive).
            Must be >= quality_tier.

        """
        if quality_tier < MIN_QUALITY_TIER or quality_tier > MAX_QUALITY_TIER:
            msg = f"quality_tier must be {MIN_QUALITY_TIER}-{MAX_QUALITY_TIER}, got {quality_tier}"
            raise ValueError(msg)
        if max_fallback_tier < MIN_QUALITY_TIER or max_fallback_tier > MAX_QUALITY_TIER:
            msg = f"max_fallback_tier must be {MIN_QUALITY_TIER}-{MAX_QUALITY_TIER}, got {max_fallback_tier}"
            raise ValueError(msg)
        if quality_tier > max_fallback_tier:
            msg = (
                f"quality_tier ({quality_tier}) must be <= "
                f"max_fallback_tier ({max_fallback_tier})"
            )
            raise ValueError(msg)

        self.store = store
        self.configs = provider_configs
        self.rotate_every = rotate_every
        self._quality_tier = quality_tier
        self._max_fallback_tier = max_fallback_tier

        # ── Force-provider override ────────────────────────────────────────
        # When set, get_best_key() returns a synthetic key_data pointing at
        # this provider regardless of what's in the key database.
        self._force_provider: str | None = None
        self._force_model: str | None = None

        # ── Model override (temp routing filter) ────────────────────────────
        self._forced_models: list[str] = []
        self._forced_models_version: int = 0

        self._order: dict[str, list[int]] = {}
        self._cursor: dict[str, int] = {}
        self._slot_count: dict[int, int] = {}
        self._loaded_cap_keys: set[str] = set()
        # track which cap_key context each key_id was last selected under
        self._key_last_cap_key: dict[int, str] = {}
        # version counter bumped when config that affects key filtering changes
        self._config_version: int = 0

    # ── Force-provider routing override ──────────────────────────────────

    @property
    def force_provider(self) -> str | None:
        """If set, all routing goes to this provider regardless of DB keys."""
        return self._force_provider

    def set_force_provider(self, provider: str, model: str | None = None) -> None:
        """Force all chat-completion routing to *provider* with optional *model*.

        When enabled, ``get_best_key()`` returns a synthetic key_data with no
        real API key — the provider must support ``no_auth`` (like opencode_zen).
        Call ``clear_force_provider()`` to restore normal DB-backed routing.
        """
        self._force_provider = provider
        self._force_model = model

    def clear_force_provider(self) -> None:
        """Restore normal DB-backed routing."""
        self._force_provider = None
        self._force_model = None

    # ── Model override (temp routing filter) ─────────────────────────────

    def set_forced_models(self, models: list[str]) -> None:
        """Restrict routing to only these model IDs (temporary override).

        Call ``clear_forced_models()`` to remove the restriction.
        """
        self._forced_models = list(models)
        self._forced_models_version += 1

    def clear_forced_models(self) -> None:
        """Remove the model restriction and route normally."""
        self._forced_models = []
        self._forced_models_version += 1

    @property
    def forced_models(self) -> list[str]:
        """Return the list of forced model IDs, or empty if unrestricted."""
        return list(self._forced_models)

    def get_quality_tier(self) -> int:
        """Return the current preferred quality tier (1=best)."""
        return self._quality_tier

    def set_quality_tier(self, tier: int) -> None:
        """Set the preferred quality tier at runtime."""
        if tier < MIN_QUALITY_TIER or tier > MAX_QUALITY_TIER:
            raise ValueError(
                f"quality_tier must be {MIN_QUALITY_TIER}-{MAX_QUALITY_TIER}"
            )
        if tier > self._max_fallback_tier:
            raise ValueError(
                f"quality_tier ({tier}) must not exceed max_fallback_tier ({self._max_fallback_tier})"
            )
        self._quality_tier = tier
        self._config_version += 1

    def get_max_fallback_tier(self) -> int:
        """Return the current max fallback tier."""
        return self._max_fallback_tier

    def set_max_fallback_tier(self, tier: int) -> None:
        """Set the max fallback tier at runtime."""
        if tier < MIN_QUALITY_TIER or tier > MAX_QUALITY_TIER:
            raise ValueError(
                f"max_fallback_tier must be {MIN_QUALITY_TIER}-{MAX_QUALITY_TIER}"
            )
        if tier < self._quality_tier:
            raise ValueError(
                f"max_fallback_tier ({tier}) must not be less than quality_tier ({self._quality_tier})"
            )
        self._max_fallback_tier = tier
        self._config_version += 1

    def _load_state(self, cap_scope: str) -> None:
        if cap_scope in self._loaded_cap_keys:
            return
        cursor, slot_counts = self.store.load_rotation_state(cap_scope)
        self._cursor[cap_scope] = cursor
        self._slot_count.update(slot_counts)
        self._loaded_cap_keys.add(cap_scope)

    def _persist_state(self, cap_scope: str) -> None:
        self.store.save_rotation_state(
            cap_scope,
            self._cursor.get(cap_scope, 0),
            self._slot_count,
        )

    def _ensure_order(
        self,
        cap_scope: str,
        capabilities: list[str],
        active_keys: list[dict[str, Any]],
        min_context: int | None = None,
        require_tools: bool | None = None,
        require_vision: bool | None = None,
    ) -> None:
        """Build or refresh the ordered key list for a capability context."""
        self._load_state(cap_scope)
        current = self._order.get(cap_scope, [])
        current_fmv = getattr(self, "_last_forced_version", None)
        current_cv = getattr(self, "_last_config_version", None)
        current_tf = getattr(self, "_last_tier_fallback", None)
        active_ids = {k["id"] for k in active_keys}
        if (
            set(current) == active_ids
            and current_fmv == self._forced_models_version
            and current_cv == self._config_version
            and current_tf == _tier_fallback_allowed()
        ):
            return
        self._last_forced_version = self._forced_models_version
        self._last_config_version = self._config_version
        self._last_tier_fallback = _tier_fallback_allowed()

        candidates: list[tuple[int, float, dict[str, Any]]] = []

        affinity_on = is_affinity_enabled()

        primary_pass = True

        while True:
            skip_forced = not primary_pass
            skip_affinity = not primary_pass

            for k in active_keys:
                if not k["is_active"]:
                    continue
                if not any(c in self.store.parse_capabilities(k) for c in capabilities):
                    continue
                cfg = self.configs.get(k["provider"], {})
                model = k["model"] or _resolve_model(cfg, cap_scope)

                # Forced model filter — skip only during primary pass
                if (
                    not skip_forced
                    and self._forced_models
                    and model not in self._forced_models
                ):
                    continue

                # Affinity filter — skip during fallback (optimization hint, not correctness)
                if (
                    not skip_affinity
                    and affinity_on
                    and model
                    and not is_key_available(k["id"], model)
                ):
                    continue

                # Model-level cooldown check — skip keys on cooldown for this model
                if model:
                    model_db_id = self.store.get_model_db_id(k["provider"], model)
                    if model_db_id is not None and self.store.check_model_cooldown(
                        k["id"], model_db_id
                    ):
                        continue

                # Feature filters (tools/vision/context) are request requirements — always applied
                features = _get_model_features(model)
                if min_context is not None and features:
                    if features.get("context", 0) < min_context:
                        continue
                if (
                    require_tools is True
                    and features
                    and not features.get("tools", False)
                ):
                    continue
                if (
                    require_vision is True
                    and features
                    and not features.get("vision", False)
                ):
                    continue

                # Tier filter is a user preference — always applied
                tier = get_model_tier(model)
                effective_max = (
                    self._max_fallback_tier
                    if _tier_fallback_allowed()
                    else self._quality_tier
                )
                if not (self._quality_tier <= tier <= effective_max):
                    continue

                score = _score_key(k, cfg)
                candidates.append((tier, score, k))

            if candidates or not primary_pass:
                break
            # Fallback: retry without forced_models and affinity restrictions
            primary_pass = False
            logger.info(
                "No keys matched primary filters — retrying without forced_models/affinity restrictions"
            )

        candidates.sort(key=lambda x: (-_key_priority(x[2]), x[0], -x[1]))
        ordered = [k for _, _, k in candidates]

        self._order[cap_scope] = [k["id"] for k in ordered]
        if cap_scope not in self._cursor:
            self._cursor[cap_scope] = 0
        else:
            self._cursor[cap_scope] %= max(len(self._order[cap_scope]), 1)
        for k in ordered:
            self._slot_count.setdefault(k["id"], 0)

    def get_best_key(
        self,
        capabilities: list[str] | str,
        subscriber_id: str = "unknown",
        min_context: int | None = None,
        require_tools: bool | None = None,
        require_vision: bool | None = None,
        uid: str | None = None,
    ) -> dict[str, Any] | None:
        """Select the best available key for the given capabilities."""
        # ── Force-provider override — bypass key DB entirely ────────────
        if self._force_provider:
            cfg = self.configs.get(self._force_provider, {})
            forced_model = self._force_model or cfg.get(
                "default_model", "deepseek-v4-flash-free"
            )
            caps = capabilities if isinstance(capabilities, list) else [capabilities]
            return {
                "key_id": -1,  # sentinel — DB-independent
                "provider": self._force_provider,
                "api_key": "",
                "base_url": cfg.get("base_url", ""),
                "model": forced_model,
                "capabilities": caps,
                "cap_key": "forced",
                "subscriber_id": subscriber_id,
                "openai_compatible": cfg.get("openai_compatible", True),
                "no_auth": cfg.get("no_auth", False),
                "extra_params": {},
                "requests_today": 0,
                "tokens_used_today": 0,
                "cycle_position": 1,
                "rotate_every": 1,
            }

        if isinstance(capabilities, str):
            capabilities = [capabilities]
        cap_scope = _cap_key(capabilities)
        active = self.store.get_active_keys(capabilities)
        if not active:
            return None

        # ── Slimey pin check — if uid pinned to a key, use it directly ──
        if uid:
            from .core.slimey import get_slimey_router

            sr = get_slimey_router()
            if sr.is_enabled():
                pin = sr.get_pin(uid)
                if pin:
                    pinned_provider, pinned_model, pinned_key_id, _ = pin
                    for k in active:
                        if (
                            k["id"] == pinned_key_id
                            and k["provider"] == pinned_provider
                        ):
                            if sr.is_qos_acceptable(
                                uid, pinned_provider, pinned_model
                            ):
                                cfg = self.configs.get(k["provider"], {})
                                try:
                                    extra = json.loads(
                                        k["extra_params"] or "{}"
                                    )
                                except json.JSONDecodeError:
                                    extra = {}
                                raw_base_url = (
                                    k.get("base_url_override")
                                    or cfg.get("base_url", "")
                                )
                                base_url = raw_base_url
                                if "{account_id}" in base_url:
                                    base_url = base_url.format(
                                        account_id=extra.get("account_id", "")
                                    )
                                return {
                                    "key_id": k["id"],
                                    "provider": k["provider"],
                                    "api_key": k["api_key"],
                                    "base_url": base_url,
                                    "model": k["model"]
                                    or _resolve_model(cfg, cap_scope),
                                    "capabilities": self.store.parse_capabilities(
                                        k
                                    ),
                                    "cap_key": cap_scope,
                                    "subscriber_id": subscriber_id,
                                    "openai_compatible": cfg.get(
                                        "openai_compatible", True
                                    ),
                                    "no_auth": cfg.get("no_auth", False),
                                    "extra_params": extra,
                                    "requests_today": k["requests_today"],
                                    "tokens_used_today": k["tokens_used_today"],
                                    "cycle_position": 1,
                                    "rotate_every": self.rotate_every,
                                }
                            # QoS unacceptable — unpin so next request
                            # falls through to normal routing.
                            sr.record_error(
                                uid, pinned_provider, pinned_model
                            )
                            break

        active_map = {k["id"]: k for k in active}
        self._ensure_order(
            cap_scope, capabilities, active, min_context, require_tools, require_vision
        )

        order = self._order.get(cap_scope, [])
        if not order:
            return None
        cursor = self._cursor.get(cap_scope, 0) % len(order)

        reset_done = False
        for _ in range(len(order) + 1):
            key_id = order[cursor % len(order)]
            if (
                key_id in active_map
                and self._slot_count.get(key_id, 0) < self.rotate_every
            ):
                best_key = active_map[key_id]
                model = best_key.get("model") or _resolve_model(
                    self.configs.get(best_key["provider"], {}), cap_scope
                )
                on_model_cooldown = False
                if model:
                    model_db_id = self.store.get_model_db_id(
                        best_key["provider"], model
                    )
                    if model_db_id is not None and self.store.check_model_cooldown(
                        key_id, model_db_id
                    ):
                        on_model_cooldown = True

                if not on_model_cooldown:
                    break
            cursor = (cursor + 1) % len(order)
            if not reset_done and cursor == self._cursor.get(cap_scope, 0) % len(order):
                for kid in order:
                    self._slot_count[kid] = 0
                reset_done = True
        else:
            return None

        self._cursor[cap_scope] = cursor
        best = active_map[order[cursor]]
        cfg = self.configs.get(best["provider"], {})
        try:
            extra = json.loads(best["extra_params"] or "{}")
        except json.JSONDecodeError:
            extra = {}

        raw_base_url = best.get("base_url_override") or cfg.get("base_url", "")
        base_url = raw_base_url
        if "{account_id}" in base_url:
            base_url = base_url.format(account_id=extra.get("account_id", ""))

        slot_pos = self._slot_count.get(best["id"], 0) + 1
        self._key_last_cap_key[best["id"]] = cap_scope

        return {
            "key_id": best["id"],
            "provider": best["provider"],
            "api_key": best["api_key"],
            "base_url": base_url,
            "model": best["model"] or _resolve_model(cfg, cap_scope),
            "capabilities": self.store.parse_capabilities(best),
            "cap_key": cap_scope,
            "subscriber_id": subscriber_id,
            "openai_compatible": cfg.get("openai_compatible", True),
            "no_auth": cfg.get("no_auth", False),
            "extra_params": extra,
            "requests_today": best["requests_today"],
            "tokens_used_today": best["tokens_used_today"],
            "cycle_position": slot_pos,
            "rotate_every": self.rotate_every,
        }

    def peek_current_key(
        self,
        capabilities: list[str] | str,
        min_context: int | None = None,
        require_tools: bool | None = None,
        require_vision: bool | None = None,
    ) -> dict[str, Any] | None:
        """Return the key that would be selected next without mutating state."""
        if isinstance(capabilities, str):
            capabilities = [capabilities]
        cap_scope = _cap_key(capabilities)
        active = self.store.get_active_keys(capabilities)
        if not active:
            return None

        active_map = {k["id"]: k for k in active}
        self._ensure_order(
            cap_scope, capabilities, active, min_context, require_tools, require_vision
        )

        order = self._order.get(cap_scope, [])
        if not order:
            return None
        cursor = self._cursor.get(cap_scope, 0) % len(order)
        slot_count = dict(self._slot_count)

        for _ in range(len(order) + 1):
            key_id = order[cursor % len(order)]
            if key_id in active_map and slot_count.get(key_id, 0) < self.rotate_every:
                best_key = active_map[key_id]
                model = best_key.get("model") or _resolve_model(
                    self.configs.get(best_key["provider"], {}), cap_scope
                )
                on_model_cooldown = False
                if model:
                    model_db_id = self.store.get_model_db_id(
                        best_key["provider"], model
                    )
                    if model_db_id is not None and self.store.check_model_cooldown(
                        key_id, model_db_id
                    ):
                        on_model_cooldown = True

                if not on_model_cooldown:
                    break
            cursor = (cursor + 1) % len(order)
        else:
            return None

        best = active_map[order[cursor]]
        cfg = self.configs.get(best["provider"], {})
        slot_pos = slot_count.get(best["id"], 0) + 1
        return {
            "key_id": best["id"],
            "provider": best["provider"],
            "model": best["model"] or _resolve_model(cfg, cap_scope),
            "capabilities": self.store.parse_capabilities(best),
            "requests_today": best["requests_today"],
            "tokens_used_today": best["tokens_used_today"],
            "cooldown_until": best.get("cooldown_until"),
            "cycle_position": slot_pos,
            "rotate_every": self.rotate_every,
        }

    def handle_429(  # noqa: PLR0913
        self,
        key_id: int,
        provider: str,
        headers: dict[str, Any] | None = None,
        subscriber_id: str = "unknown",
        model: str = "",
        http_method: str = "",
        path: str = "",
        is_streaming: bool = False,
    ) -> str:
        """Handle a 429 rate-limit response and set cooldown at both key and model level."""
        if key_id == -1:  # synthetic forced key — no DB state to manage
            return ""
        headers = headers or {}
        cooldown = extract_cooldown(provider, headers, was_429=True)
        if cooldown is None:
            cfg = self.configs.get(provider, {})
            cooldown = _fallback_from_config(cfg)()
        # Key-level cooldown (existing behaviour)
        self.store.record_usage(key_id, tokens=0, was_429=True, cooldown_until=cooldown)
        # Model-level cooldown — also record per-model-per-key
        if model:
            model_db_id = self.store.get_model_db_id(provider, model)
            if model_db_id is not None:
                self.store.record_model_cooldown(key_id, model_db_id, cooldown)
                # Auto-disable non-free models after 3 cooldowns from this provider
                self.store.auto_disable_if_threshold(model_db_id, provider, threshold=3)
        self._slot_count[key_id] = self._slot_count.get(key_id, 0) + 1
        cap_scope = self._key_last_cap_key.get(key_id, "")
        if cap_scope:
            self._persist_state(cap_scope)
        self.store.log_audit(
            subscriber_id=subscriber_id,
            key_id=key_id,
            provider=provider,
            model=model,
            success=False,
            error="429 rate limit",
            is_streaming=is_streaming,
            http_method=http_method,
            path=path,
        )
        return cooldown

    def handle_error(  # noqa: PLR0913
        self,
        key_id: int,
        provider: str,
        subscriber_id: str = "unknown",
        model: str = "",
        error: str = "",
        http_method: str = "",
        path: str = "",
        is_streaming: bool = False,
    ) -> None:
        """Handle a non-429 error (timeout, 5xx, connection error).

        Increments the slot counter so the rotator moves to the next key,
        but does NOT set a cooldown — the key remains available for the
        next request.  This prevents transient errors from falsely
        exhausting the key pool.
        """
        if key_id == -1:  # synthetic forced key — no DB state to manage
            return
        self._slot_count[key_id] = self._slot_count.get(key_id, 0) + 1
        cap_scope = self._key_last_cap_key.get(key_id, "")
        if cap_scope:
            self._persist_state(cap_scope)
        self.store.log_audit(
            subscriber_id=subscriber_id,
            key_id=key_id,
            provider=provider,
            model=model,
            success=False,
            error=error or "non-429 error",
            is_streaming=is_streaming,
            http_method=http_method,
            path=path,
        )

    def handle_success(  # noqa: PLR0913
        self,
        key_id: int,
        tokens_used: int,
        headers: dict[str, Any] | None = None,
        provider: str = "",
        tokens_in: int = 0,
        latency_ms: int = 0,
        subscriber_id: str = "unknown",
        model: str = "",
        http_method: str = "",
        path: str = "",
        is_streaming: bool = False,
    ) -> None:
        """Handle a successful API response, record usage and audit log."""
        if key_id == -1:  # synthetic forced key — no DB state to manage
            return
        headers = headers or {}
        cooldown = (
            extract_cooldown(provider, headers, was_429=False) if provider else None
        )
        self.store.record_usage(
            key_id, tokens=tokens_used, was_429=False, cooldown_until=cooldown
        )
        # Clear model-level cooldown on success so stale 429 counts don't
        # accumulate and trigger auto_disable_if_threshold() incorrectly.
        if model:
            model_db_id = self.store.get_model_db_id(provider, model)
            if model_db_id is not None:
                self.store.clear_model_cooldown(key_id, model_db_id)
        self._slot_count[key_id] = self._slot_count.get(key_id, 0) + 1
        cap_scope = self._key_last_cap_key.get(key_id, "")
        if cap_scope:
            self._persist_state(cap_scope)
        self.store.log_audit(
            subscriber_id=subscriber_id,
            key_id=key_id,
            provider=provider,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_used,
            latency_ms=latency_ms,
            success=True,
            is_streaming=is_streaming,
            http_method=http_method,
            path=path,
        )

    def skip_key(self, key_id: int) -> None:
        """Advance the slot counter for a key without recording an error or cooldown.

        Used when the circuit breaker or affinity blocks a key — still
        increment the counter so the rotator moves to the next key on
        the next ``get_best_key()`` call instead of returning the same
        blocked key repeatedly.
        """
        if key_id == -1:
            return
        self._slot_count[key_id] = self._slot_count.get(key_id, 0) + 1
        cap_scope = self._key_last_cap_key.get(key_id, "")
        if cap_scope:
            self._persist_state(cap_scope)

    def clear_caches(self) -> None:
        """Clear all cached ordering state.

        Call this when keys or cooldowns change externally (e.g., via health check UI).
        """
        self._order.clear()
        self._cursor.clear()
        self._slot_count.clear()
        self._loaded_cap_keys.clear()
        self._key_last_cap_key.clear()
        self._config_version += 1

    def get_earliest_retry(self, capabilities: list[str] | str) -> str | None:
        """Return the earliest cooldown expiry among matching keys, or None."""
        if isinstance(capabilities, str):
            capabilities = [capabilities]
        all_keys = self.store.get_all_keys()
        cooldowns = [
            k["cooldown_until"]
            for k in all_keys
            if k["is_active"]
            and k["cooldown_until"]
            and any(c in self.store.parse_capabilities(k) for c in capabilities)
        ]
        return min(cooldowns) if cooldowns else None
