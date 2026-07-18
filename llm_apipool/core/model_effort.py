"""Per-model effort/config parameter injection system.

Each provider (and sometimes specific models within a provider) has different
parameter names for controlling reasoning/thinking/computation effort.
This module provides:

- A preset system mapping effort levels to concrete API params per provider.
- Persistent user overrides stored in ``model_effort.json``.
- Provider-specific parameter schemas (enum, boolean, integer).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from threading import Lock
from typing import Any, TypedDict, NotRequired

logger = logging.getLogger(__name__)

# ── Config file location ──────────────────────────────────────────────
_EFFORT_DIR = Path(
    os.environ.get("LLM_APIPOOL_CONFIG_DIR", Path.home() / ".llm-apipool")
)
_EFFORT_PATH = _EFFORT_DIR / "model_effort.json"

_lock = Lock()
_cache: dict[str, dict[str, Any]] | None = None


# Effort preset section
# Each entry describes a configurable parameter for a provider/model.
class EffortParam(TypedDict):
    type: str
    default: str | int | float | bool | None
    values: NotRequired[list[str]]
    label: NotRequired[str]
    description: NotRequired[str]
    min: NotRequired[int | float]
    max: NotRequired[int | float]
    depends_on: NotRequired[str]

EffortPreset = dict[str, EffortParam | dict[str, EffortParam]]

# Provider-level defaults and per-model overrides
EFFORT_PRESETS: dict[str, EffortPreset | dict[str, EffortPreset]] = {
    "openai": {
        "default": {
            "reasoning_effort": {
                "type": "enum",
                "values": ["low", "medium", "high"],
                "default": "medium",
                "label": "Reasoning Effort",
                "description": "How much reasoning the model should perform",
            },
        },
    },
    "github_models": {
        "default": {
            "reasoning_effort": {
                "type": "enum",
                "values": ["low", "medium", "high"],
                "default": "medium",
                "label": "Reasoning Effort",
                "description": "How much reasoning the model should perform",
            },
        },
    },
    "anthropic": {
        "default": {
            "thinking": {
                "type": "boolean",
                "default": False,
                "label": "Extended Thinking",
                "description": "Enable Claude's extended thinking capability",
            },
            "budget_tokens": {
                "type": "integer",
                "min": 1024,
                "max": 128_000,
                "default": 16_000,
                "label": "Thinking Budget (tokens)",
                "description": "Max tokens Claude can use for internal thinking",
                "depends_on": "thinking",
            },
        },
    },
    "google": {
        "default": {
            "thinking": {
                "type": "boolean",
                "default": False,
                "label": "Thinking",
                "description": "Enable thinking mode for Gemini models",
            },
        },
    },
    "deepseek": {
        "default": {
            "thinking": {
                "type": "boolean",
                "default": False,
                "label": "DeepThink",
                "description": "Enable chain-of-thought reasoning",
            },
        },
        "deepseek-reasoner": {
            "thinking": {
                "type": "boolean",
                "default": True,
                "label": "DeepThink",
                "description": "Enable chain-of-thought reasoning",
            },
        },
    },
    "xai": {
        "default": {
            "reasoning_effort": {
                "type": "enum",
                "values": ["low", "medium", "high"],
                "default": "medium",
                "label": "Reasoning Effort",
                "description": "How much reasoning Grok should perform",
            },
        },
    },
}


# ── Storage ───────────────────────────────────────────────────────────


def _load() -> dict[str, dict[str, Any]]:
    global _cache
    if _cache is not None:
        return _cache
    if not _EFFORT_PATH.exists():
        _cache = {"overrides": {}}
        return _cache
    try:
        with open(_EFFORT_PATH) as f:
            _cache = json.load(f)
    except (json.JSONDecodeError, OSError):
        _cache = {"overrides": {}}
    return _cache


def _save(data: dict[str, dict[str, Any]]) -> None:
    global _cache
    _cache = data
    _EFFORT_DIR.mkdir(parents=True, exist_ok=True)
    with open(_EFFORT_PATH, "w") as f:
        json.dump(data, f, indent=2)


def get_effort_config(model_key: str) -> dict[str, Any]:
    """Get the effort override for a specific ``provider:model_id`` key.

    Returns empty dict if no override is set.
    """
    data = _load()
    return dict(data.get("overrides", {}).get(model_key, {}))


def get_all_effort_configs() -> dict[str, dict[str, Any]]:
    """Get all effort overrides keyed by ``provider:model_id``."""
    data = _load()
    return dict(data.get("overrides", {}))


def set_effort_config(model_key: str, params: dict[str, Any]) -> None:
    """Set the effort override for a specific model.

    ``params`` should contain only the parameter keys/values that differ from
    the provider default (e.g. ``{"reasoning_effort": "high"}``).

    Pass an empty dict to clear the override.
    """
    with _lock:
        data = _load()
        if params:
            data.setdefault("overrides", {})[model_key] = params
        else:
            data.get("overrides", {}).pop(model_key, None)
        _save(data)


def clear_effort_config(model_key: str) -> None:
    """Remove the effort override for a model."""
    with _lock:
        data = _load()
        data.get("overrides", {}).pop(model_key, None)
        _save(data)


def clear_all_effort_configs() -> None:
    """Remove all effort overrides."""
    with _lock:
        _save({"overrides": {}})


# ── Global level (set-all) ─────────────────────────────────────────

_GLOBAL_EFFORT_KEY = "__global__"


def _unified_level_to_params(level: str) -> dict[str, dict[str, Any]]:
    """Map a unified effort level to concrete params per provider.

    Each provider has different parameter names and types for controlling
    reasoning/thinking.  This mapping translates a single unified level
    (``low``, ``medium``, ``high``) to the appropriate params for every
    known provider.
    """
    level = level.lower()
    if level not in ("low", "medium", "high"):
        raise ValueError(
            f"Unified effort level must be 'low', 'medium', or 'high', got {level!r}"
        )

    # Provider → param dict mapping
    MAPPING: dict[str, dict[str, Any]] = {
        "openai": {
            "low": {"reasoning_effort": "low"},
            "medium": {"reasoning_effort": "medium"},
            "high": {"reasoning_effort": "high"},
        },
        "github_models": {
            "low": {"reasoning_effort": "low"},
            "medium": {"reasoning_effort": "medium"},
            "high": {"reasoning_effort": "high"},
        },
        "xai": {
            "low": {"reasoning_effort": "low"},
            "medium": {"reasoning_effort": "medium"},
            "high": {"reasoning_effort": "high"},
        },
        "anthropic": {
            "low": {"thinking": False},
            "medium": {"thinking": True, "budget_tokens": 16_000},
            "high": {"thinking": True, "budget_tokens": 64_000},
        },
        "google": {
            "low": {"thinking": False},
            "medium": {"thinking": True},
            "high": {"thinking": True},
        },
        "deepseek": {
            "low": {"thinking": False},
            "medium": {"thinking": False},
            "high": {"thinking": True},
        },
    }

    return {provider: params[level] for provider, params in MAPPING.items()}


def set_global_effort_level(level: str) -> None:
    """Set a unified effort level across all known providers.

    Stores the resolved per-provider params under the global override key
    so that :func:`inject_effort_params` can apply them to any model.
    """
    params = _unified_level_to_params(level)
    with _lock:
        data = _load()
        data.setdefault("overrides", {})[_GLOBAL_EFFORT_KEY] = params
        _save(data)


def get_global_effort_level() -> dict[str, dict[str, Any]] | None:
    """Get the current global effort level mapping, or None."""
    data = _load()
    return data.get("overrides", {}).get(_GLOBAL_EFFORT_KEY)


def clear_global_effort_level() -> None:
    """Remove the global effort override."""
    with _lock:
        data = _load()
        data.get("overrides", {}).pop(_GLOBAL_EFFORT_KEY, None)
        _save(data)


# ── Presets helpers ─────────────────────────────────────────────────


def get_effort_presets() -> dict[str, Any]:
    """Get the full effort presets structure for the frontend.

    Returns::
        {
          "openai": {
            "default": { "reasoning_effort": { "type": "enum", ... } }
          },
          "openai": {
            "o1-mini": { "reasoning_effort": { ... } }   # per-model override
          }
        }
    """
    return EFFORT_PRESETS


def get_effort_params_for_model(provider: str, model_id: str) -> dict[str, EffortParam]:
    """Get the parameter schema for a specific model.

    Merges provider defaults with per-model overrides from presets.
    """
    provider_presets = EFFORT_PRESETS.get(provider, {})
    if isinstance(provider_presets, dict):
        defaults = provider_presets.get("default", {})
        model_overrides = provider_presets.get(model_id, {})
        if isinstance(defaults, dict) and isinstance(model_overrides, dict):
            return {**defaults, **model_overrides}
    return {}


# ── Injection ─────────────────────────────────────────────────────────


def inject_effort_params(
    provider: str,
    model_id: str,
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Mutate *kwargs* in-place with effort params for the given model.

    Checks both the override store and the presets to determine what to inject.
    Priority:  user per-model override ≻ global override ≻ preset default

    Returns *kwargs* for chaining.
    """
    model_key = f"{provider}:{model_id}"
    override = get_effort_config(model_key)
    global_override = get_global_effort_level()
    preset_params = get_effort_params_for_model(provider, model_id)

    merged: dict[str, Any] = {}
    for param_name, schema in preset_params.items():
        # Check per-model override first
        if override.get(param_name) is not None:
            merged[param_name] = override[param_name]
        # Then check global override (provider-level params)
        elif global_override and provider in global_override:
            gval = global_override[provider].get(param_name)
            if gval is not None:
                merged[param_name] = gval
        # Fall back to preset default
        elif schema.get("default") is not None:
            merged[param_name] = schema["default"]

    # Map internal param names to actual API param names per provider
    param_map = _get_param_map(provider)

    for internal_name, value in merged.items():
        api_name = param_map.get(internal_name, internal_name)

        if api_name == "thinking" and isinstance(value, bool):
            if provider == "google":
                kwargs["thinking_config"] = {
                    "thinking_mode": "enabled" if value else "disabled"
                }
            elif provider == "anthropic":
                kwargs["thinking"] = {"type": "enabled"} if value else None
                budget = override.get("budget_tokens") or preset_params.get(
                    "budget_tokens", {}
                ).get("default")
                if value and budget:
                    kwargs["thinking"]["budget_tokens"] = budget
            elif provider == "deepseek":
                if value:
                    kwargs[api_name] = value
            else:
                kwargs[api_name] = value
        else:
            kwargs[api_name] = value

    return kwargs


def _get_param_map(provider: str) -> dict[str, str]:
    """Map internal effort param names to API param names per provider.

    Most providers use the same name internally as in their API,
    but some need translation.
    """
    maps: dict[str, dict[str, str]] = {
        "google": {
            "thinking": "thinking_config",
        },
        "anthropic": {
            "thinking": "thinking",
            "budget_tokens": "budget_tokens",
        },
    }
    return maps.get(provider, {})


# ── Reload (for tests) ────────────────────────────────────────────────


def _reload_for_testing() -> None:
    global _cache
    _cache = None
