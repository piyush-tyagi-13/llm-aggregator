"""3-mode fallback chain settings model with independent config per mode.

Modes:
  - fallback: Normal model caching/fallback (default)
  - sticky:   Stick to same model for UID
  - slimey:   QoS-based TTFT+throughput routing
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FallbackModeConfig:
    """Independent config for each fallback mode."""

    enabled: bool = False
    quality_tier: int = 1
    max_fallback_tier: int = 4
    tier_fallback_enabled: bool = True
    strategy: str = "balanced"
    affinity_enabled: bool = False
    sticky_enabled: bool = False
    max_attempts_same_key: int = 3
    max_attempts_same_provider: int = 3
    max_attempts_all_providers: int = 3
    cooldown_on_failure_ms: int = 1800000

    # Slimey-specific (only used in slimey mode)
    max_ttft_ms: int = 5000
    min_throughput: int = 10


class FallbackModes:
    """Manages 3 fallback chain modes."""

    MODE_FALLBACK = "fallback"  # Normal model caching/fallback
    MODE_STICKY = "sticky"  # Stick to same model for UID
    MODE_SLIMEY = "slimey"  # QoS-based TTFT+throughput routing

    def __init__(self) -> None:
        self._active_mode: str = self.MODE_FALLBACK
        self._modes: dict[str, FallbackModeConfig] = {
            self.MODE_FALLBACK: FallbackModeConfig(enabled=True),
            self.MODE_STICKY: FallbackModeConfig(
                enabled=False, sticky_enabled=True
            ),
            self.MODE_SLIMEY: FallbackModeConfig(
                enabled=False, affinity_enabled=True
            ),
        }

    def get_active_mode(self) -> str:
        return self._active_mode

    def set_active_mode(self, mode: str) -> None:
        if mode not in self._modes:
            raise ValueError(f"Invalid fallback mode: {mode}")
        self._active_mode = mode

    def get_mode_config(self, mode: str) -> FallbackModeConfig:
        return self._modes[mode]

    def update_mode_config(self, mode: str, **kwargs: Any) -> None:
        cfg = self._modes[mode]
        for k, v in kwargs.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)

    def get_all_configs(self) -> dict[str, dict[str, Any]]:
        return {k: vars(v) for k, v in self._modes.items()}

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_mode": self._active_mode,
            "modes": self.get_all_configs(),
        }


_fallback_modes = FallbackModes()


def get_fallback_modes() -> FallbackModes:
    return _fallback_modes
