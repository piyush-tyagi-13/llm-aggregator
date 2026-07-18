"""Centralized configuration — reads all JSON config files and provides typed access.

Replaces scattered hardcoded constants across the codebase.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _config_dir() -> Path:
    return Path(__file__).resolve().parent


def _load_json(name: str) -> dict[str, Any]:
    path = _config_dir() / name
    with path.open() as f:
        return json.load(f)


# ── Dataclasses ──────────────────────────────────────────────────────────────


@dataclass
class StrategyWeights:
    """Weight vector for combining routing axes."""

    reliability: float = 0.5
    speed: float = 0.25
    intelligence: float = 0.25


@dataclass
class StrategyDef:
    """A named routing strategy."""

    description: str = ""
    weights: StrategyWeights | None = None


@dataclass
class FallbackConfig:
    """Fallback chain parameters."""

    max_attempts_same_key: int = 3
    max_attempts_same_provider: int = 3
    max_attempts_all_providers: int = 3
    cooldown_on_failure_ms: int = 1_800_000


@dataclass
class RouterConstants:
    """Router tuning parameters."""

    penalty_per_429: int = 3
    max_penalty: int = 10
    decay_interval_ms: int = 120_000
    decay_amount: int = 1


@dataclass
class HealthConfig:
    """Health checker tuning."""

    check_interval_ms: int = 300_000
    consecutive_failures_to_disable: int = 3


@dataclass
class HandoffConfig:
    """Context handoff tuning."""

    max_recent_messages: int = 12
    max_handoff_chars: int = 6000
    max_content_per_msg: int = 500
    session_ttl_ms: int = 10_800_000
    max_store_size: int = 500


@dataclass
class StickyConfig:
    """Sticky session tuning."""

    sticky_ttl_ms: int = 1_800_000
    max_sticky_entries: int = 500


@dataclass
class AppSettings:
    """Top-level settings aggregating all config domains."""

    default_strategy: str = "balanced"
    strategies: dict[str, StrategyDef] = field(default_factory=dict)
    fallback: FallbackConfig = field(default_factory=FallbackConfig)
    router: RouterConstants = field(default_factory=RouterConstants)
    health: HealthConfig = field(default_factory=HealthConfig)
    handoff: HandoffConfig = field(default_factory=HandoffConfig)
    sticky: StickyConfig = field(default_factory=StickyConfig)

    @property
    def valid_strategies(self) -> list[str]:
        return list(self.strategies.keys())

    @property
    def bandit_presets(self) -> dict[str, StrategyWeights]:
        return {
            name: s.weights
            for name, s in self.strategies.items()
            if s.weights is not None
        }


# ── Singleton loader ─────────────────────────────────────────────────────────

_settings: AppSettings | None = None


def load_settings() -> AppSettings:
    """Load (and cache) all configuration from JSON files."""
    global _settings
    if _settings is not None:
        return _settings

    raw = _load_json("default_strategies.json")

    strategies: dict[str, StrategyDef] = {}
    for name, s in raw.get("strategies", {}).items():
        w = s.get("weights")
        strategies[name] = StrategyDef(
            description=s.get("description", ""),
            weights=StrategyWeights(**w) if w else None,
        )

    fb = raw.get("fallback", {})
    fallback = FallbackConfig(
        max_attempts_same_key=fb.get("max_attempts_same_key", 3),
        max_attempts_same_provider=fb.get("max_attempts_same_provider", 3),
        max_attempts_all_providers=fb.get("max_attempts_all_providers", 3),
        cooldown_on_failure_ms=fb.get("cooldown_on_failure_ms", 1_800_000),
    )

    _settings = AppSettings(
        default_strategy=raw.get("default_strategy", "balanced"),
        strategies=strategies,
        fallback=fallback,
    )

    # Allow env-var overrides for key constants
    env = os.environ.get
    _settings.router.penalty_per_429 = int(env("LLM_ROUTER_PENALTY_PER_429", "3"))
    _settings.router.max_penalty = int(env("LLM_ROUTER_MAX_PENALTY", "10"))
    _settings.router.decay_interval_ms = int(
        env("LLM_ROUTER_DECAY_INTERVAL_MS", "120000")
    )
    _settings.health.check_interval_ms = int(
        env("LLM_HEALTH_CHECK_INTERVAL_MS", "300000")
    )
    _settings.handoff.session_ttl_ms = int(
        env("LLM_HANDOFF_SESSION_TTL_MS", "10800000")
    )
    _settings.sticky.sticky_ttl_ms = int(env("LLM_STICKY_TTL_MS", "1800000"))

    return _settings


def reload_settings() -> AppSettings:
    """Force reload from disk (for tests / hot-reload)."""
    global _settings
    _settings = None
    return load_settings()


def load_providers_config() -> dict[str, Any]:
    """Load the 42-provider definition file."""
    return _load_json("providers.json").get("providers", {})


__all__ = [
    "AppSettings",
    "StrategyWeights",
    "StrategyDef",
    "FallbackConfig",
    "RouterConstants",
    "HealthConfig",
    "HandoffConfig",
    "StickyConfig",
    "load_settings",
    "reload_settings",
    "load_providers_config",
]
