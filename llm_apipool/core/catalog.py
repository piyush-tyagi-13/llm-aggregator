"""Static model catalog — local read-only model lookups from ``providers.json``.

No premium / live-catalog sync.  This is the simplified (offline) version of
FreeLLMAPI's ``catalog-sync.ts`` — no network, no license keys, no signatures.

Model catalogues are synced live from provider /v1/models endpoints and stored
in the DB.  This module only provides fallback metadata lookups when the DB
hasn't been populated yet.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import model_metadata

_cache_providers: dict[str, Any] | None = None


def _load_config() -> dict[str, Any]:
    """Load and cache ``providers.json``."""
    global _cache_providers
    if _cache_providers is not None:
        return _cache_providers
    config_path = Path(__file__).resolve().parent.parent / "config" / "providers.json"
    try:
        data = json.loads(config_path.read_text())
        _cache_providers = data if isinstance(data, dict) else {"providers": {}}
    except (FileNotFoundError, json.JSONDecodeError):
        _cache_providers = {"providers": {}}
    return _cache_providers


def get_model_info(platform: str, model_id: str) -> dict[str, Any] | None:
    """Return model metadata for a specific provider model.

    Checks ``providers.json`` for the provider config, then falls back to the
    runtime ``model_metadata`` cache.  Model-specific hardcoded lists are no
    longer used — all models come from live sync.
    """
    config = _load_config()
    providers = config.get("providers", {})
    prov = providers.get(platform)
    if prov is None:
        return model_metadata.get_model_features(model_id)

    limits = prov.get("limits", {})
    return {
        "platform": platform,
        "model_id": model_id,
        "display_name": model_id,
        "context_window": limits.get("max_context_tokens", 8192),
        "supports_vision": False,
        "supports_tools": True,
        "rpm_limit": limits.get("rpm"),
        "rpd_limit": limits.get("rpd"),
        "tpm_limit": limits.get("tpm"),
        "tpd_limit": limits.get("tpd"),
        "intelligence_rank": 999,
        "size_label": "Medium",
        "base_url": prov.get("base_url", ""),
    }


def list_models(platform: str | None = None) -> list[dict[str, Any]]:
    """List known models from provider config.  Only returns minimal metadata.

    Full model catalogues come from live sync — this function is a fallback
    for when the DB hasn't been populated yet, or for offline lookup.
    """
    config = _load_config()
    providers = config.get("providers", {})
    result: list[dict[str, Any]] = []

    for prov_name, prov in providers.items():
        if platform is not None and prov_name != platform:
            continue
        limits = prov.get("limits", {})
        default_model = prov.get("default_model", "")
        if default_model:
            result.append(
                {
                    "platform": prov_name,
                    "model_id": default_model,
                    "display_name": default_model,
                    "context_window": limits.get("max_context_tokens", 8192),
                    "supports_vision": False,
                    "supports_tools": True,
                    "rpm_limit": limits.get("rpm"),
                    "rpd_limit": limits.get("rpd"),
                    "tpm_limit": limits.get("tpm"),
                    "tpd_limit": limits.get("tpd"),
                    "is_default": True,
                }
            )

    return result


def list_providers() -> list[dict[str, Any]]:
    """List all configured providers with their basic metadata."""
    config = _load_config()
    providers = config.get("providers", {})
    return [
        {
            "name": p_name,
            "base_url": prov.get("base_url", ""),
            "openai_compatible": prov.get("openai_compatible", False),
            "default_model": prov.get("default_model", ""),
            "model_count": 0,  # models come from live sync, not config
        }
        for p_name, prov in sorted(providers.items())
    ]


def get_provider_config(platform: str) -> dict[str, Any] | None:
    """Return the full provider config dict from ``providers.json``, if found."""
    config = _load_config()
    return config.get("providers", {}).get(platform)
