"""Tier fallback toggle — runtime override that controls whether the
rotator falls through model tiers (1→2→3→4) when higher-tier keys are
exhausted.

Defaults to *enabled* (backward compatible).  When disabled the rotator
will only consider keys from *quality_tier* (the preferred tier), not
falling back through max_fallback_tier.
"""

from __future__ import annotations

import os

_TIER_FALLBACK_OVERRIDE: list[bool | None] = [None]


def is_tier_fallback_enabled() -> bool:
    """Check whether tier fallback is active.

    Returns the runtime override if set (via ``set_tier_fallback_enabled``),
    otherwise falls back to the ``LLM_TIER_FALLBACK_ENABLED`` env var
    (default ``True``).
    """
    override = _TIER_FALLBACK_OVERRIDE[0]
    if override is not None:
        return override
    raw = os.environ.get("LLM_TIER_FALLBACK_ENABLED", "").strip().lower()
    if raw in ("off", "false", "0", "no"):
        return False
    return True


def set_tier_fallback_enabled(val: bool) -> None:
    """Override the env toggle at runtime (e.g. from the settings API)."""
    _TIER_FALLBACK_OVERRIDE[0] = val


__all__ = ["is_tier_fallback_enabled", "set_tier_fallback_enabled"]
