"""Core router with Thompson sampling for FreeLLMAPI-style intelligent routing.

Strategy definitions and tuning constants are loaded from
``config/default_strategies.json`` via ConfigLoader — not hardcoded here.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from ..config.loader import load_settings

_settings = load_settings()

# Strategy names — loaded from default_strategies.json (data, not code)
VALID_STRATEGIES: list[str] = _settings.valid_strategies

# Penalty tracking — loaded from config with env-var override
PENALTY_PER_429 = _settings.router.penalty_per_429
MAX_PENALTY = _settings.router.max_penalty
DECAY_INTERVAL_MS = _settings.router.decay_interval_ms
DECAY_AMOUNT = _settings.router.decay_amount


# ── Penalty tracking ─────────────────────────────────────────────────────────
_rate_limit_penalties: dict[int, dict[str, Any]] = {}


def record_rate_limit_hit(model_db_id: int) -> None:
    """Record a 429 for a model — increases its penalty so it sinks in priority."""
    now = time.time()
    existing = _rate_limit_penalties.get(model_db_id)
    if existing:
        decay_steps = int((now - existing["last_hit"]) / (DECAY_INTERVAL_MS / 1000))
        existing["penalty"] = max(0, existing["penalty"] - decay_steps * DECAY_AMOUNT)
        existing["count"] += 1
        existing["last_hit"] = now
        existing["penalty"] = min(existing["penalty"] + PENALTY_PER_429, MAX_PENALTY)
    else:
        _rate_limit_penalties[model_db_id] = {
            "count": 1,
            "last_hit": now,
            "penalty": PENALTY_PER_429,
        }


def record_success(model_db_id: int) -> None:
    """Record a success for a model — reduces its penalty so it rises back up."""
    existing = _rate_limit_penalties.get(model_db_id)
    if existing:
        existing["penalty"] = max(0, existing["penalty"] - 1)
        if existing["penalty"] == 0:
            del _rate_limit_penalties[model_db_id]


def get_penalty(model_db_id: int) -> float:
    """Get the current penalty for a model (with time-based decay)."""
    entry = _rate_limit_penalties.get(model_db_id)
    if not entry:
        return 0

    elapsed = time.time() - entry["last_hit"]
    decay_steps = int(elapsed / (DECAY_INTERVAL_MS / 1000))
    decayed = max(0, entry["penalty"] - decay_steps * DECAY_AMOUNT)
    if decayed == 0:
        del _rate_limit_penalties[model_db_id]
        return 0
    return float(decayed)


def get_all_penalties() -> list[dict[str, Any]]:
    """Get current penalties for all models (for the API/dashboard)."""
    result = []
    for model_db_id, entry in list(_rate_limit_penalties.items()):
        penalty = get_penalty(model_db_id)
        if penalty > 0:
            result.append(
                {
                    "model_db_id": model_db_id,
                    "count": entry["count"],
                    "penalty": penalty,
                }
            )
    return sorted(result, key=lambda x: x["penalty"], reverse=True)


# ── Runtime state ──────────────────────────────────────────────────────────────
_current_strategy: str = _settings.default_strategy
_custom_weights: CustomWeights | None = None


def set_custom_weights_obj(weights: CustomWeights) -> None:
    global _custom_weights
    _custom_weights = weights


def get_custom_weights_obj() -> CustomWeights | None:
    return _custom_weights


# ── Routing strategy management ────────────────────────────────────────────────
def get_routing_strategy() -> str:
    return _current_strategy


def set_routing_strategy(strategy: str) -> None:
    global _current_strategy
    if strategy not in VALID_STRATEGIES:
        raise ValueError(f"Unknown routing strategy: {strategy}")
    _current_strategy = strategy


@dataclass
class CustomWeights:
    """Custom weight vector for routing."""

    reliability: float = 0.5
    speed: float = 0.25
    intelligence: float = 0.25


def get_custom_weights() -> CustomWeights:
    stored = get_custom_weights_obj()
    if stored is not None:
        return stored
    return CustomWeights(reliability=0.5, speed=0.25, intelligence=0.25)


def set_custom_weights(weights: CustomWeights) -> None:
    total = weights.reliability + weights.speed + weights.intelligence
    if total <= 0:
        raise ValueError("Custom weights must sum to a positive value")
    if not all(
        isinstance(v, (int, float)) and v >= 0
        for v in (weights.reliability, weights.speed, weights.intelligence)
    ):
        raise ValueError("Custom weights must be non-negative numbers")
    normalized = CustomWeights(
        reliability=weights.reliability / total,
        speed=weights.speed / total,
        intelligence=weights.intelligence / total,
    )
    set_custom_weights_obj(normalized)


def weights_for(strategy: str) -> CustomWeights | None:
    """Get weights for a strategy."""
    if strategy == "priority":
        return None
    if strategy == "custom":
        return get_custom_weights()
    from .scoring import _get_bandit_presets

    preset = _get_bandit_presets().get(strategy)
    if preset:
        return CustomWeights(
            reliability=preset.reliability,
            speed=preset.speed,
            intelligence=preset.intelligence,
        )
    return CustomWeights(reliability=0.5, speed=0.25, intelligence=0.25)


# ── Intelligence composite ───────────────────────────────────────────────────
_TIER_VALUE: dict[str, int] = {"Frontier": 4, "Large": 3, "Medium": 2, "Small": 1}


def intelligence_composite(size_label: str, intelligence_rank: int) -> float:
    """Composite intelligence: size_label is the cross-provider capability tier."""
    tier = _TIER_VALUE.get(size_label, 0)
    return tier * 1000 - intelligence_rank
