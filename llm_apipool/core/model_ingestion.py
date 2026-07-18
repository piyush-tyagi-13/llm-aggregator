"""Fetch, normalise, and sync model data from provider ``/v1/models`` endpoints.

Public API
----------
- ``sync_provider_models(store, provider, configs, key_id=None)``
- ``fetch_provider_models(base_url, api_key, provider_name)``
- ``normalize_model(provider, raw_model)``
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx

from llm_apipool.core.free_detection import detect_free_model
from llm_apipool.core.model_db import (
    link_key_to_model,
    mark_sync_complete,
    mark_sync_failed,
    upsert_catalog_source,
    upsert_model,
)

logger = logging.getLogger(__name__)


def _parse_extra(raw: str) -> dict[str, Any]:
    """Safely parse a JSON ``extra_params`` column value."""
    if not raw:
        return {}
    try:
        return json.loads(raw) if isinstance(raw, str) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


# ── Per-provider endpoint overrides ────────────────────────────────────────────

PROVIDER_ENDPOINTS: dict[str, str] = {
    "google": "https://generativelanguage.googleapis.com/v1beta/models",
    "pollinations": "https://text.pollinations.ai/models",
    "ollama": "https://ollama.ai/api/tags",
    "inference_net": "https://api.inference.net/v1/models",
    "llm7": "https://api.llm7.io/v1/models",
    "groq": "https://api.groq.com/openai/v1/models",
    "cerebras": "https://api.cerebras.ai/v1/models",
    "mistral": "https://api.mistral.ai/v1/models",
    "cohere": "https://api.cohere.ai/v1/models",
    "opencode_zen": "https://opencode.ai/zen/v1/models",
    "paxsenix": "https://api.paxsenix.org/v1/models",
    "openrouter": "https://openrouter.ai/api/v1/models",
    "deepinfra": "https://api.deepinfra.com/v1/models",
    "fireworks": "https://api.fireworks.ai/inference/v1/models",
    "together": "https://api.together.xyz/v1/models",
    "sambanova": "https://api.sambanova.ai/v1/models",
    "huggingface": "https://api-inference.huggingface.co/models",
    "replicate": "https://api.replicate.com/v1/models",
    "nvidia": "https://api.nvcf.nvidia.com/v2/nvcf/models",
    "github": "https://models.inference.ai.azure.com/models",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4/models",
    "alibaba": "https://dashscope.aliyuncs.com/api/v1/services/models",
}

PROVIDER_HEADERS: dict[str, dict[str, str]] = {
    "google": {"Content-Type": "application/json"},
    "pollinations": {},
    "ollama": {},
}


async def fetch_provider_models(
    base_url: str,
    api_key: str | None = None,
    provider_name: str = "",
) -> list[dict[str, Any]]:
    """Call a provider's ``/v1/models`` (or custom) endpoint and return the raw model list.

    Handles both OpenAI-style (``{data: [...]}``) and non-standard response
    shapes. Returns an empty list on any error.
    """
    endpoint = PROVIDER_ENDPOINTS.get(provider_name)
    if endpoint is None:
        base = base_url.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]  # avoid double /v1/ when base_url already ends in /v1
        url = f"{base}/v1/models"
    else:
        url = endpoint

    headers: dict[str, str] = dict(PROVIDER_HEADERS.get(provider_name, {}))
    if api_key:
        if provider_name == "google":
            headers["x-goog-api-key"] = api_key
        else:
            headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        # 404 on a guessed URL (no explicit PROVIDER_ENDPOINTS entry) is
        # expected — the provider may not expose a model listing endpoint.
        # Log at DEBUG level instead of WARNING to reduce noise.
        if exc.response.status_code == 404 and provider_name not in PROVIDER_ENDPOINTS:
            logger.debug(
                "fetch_provider_models(%s): %s (no models endpoint)", provider_name, exc
            )
        else:
            logger.warning("fetch_provider_models(%s) failed: %s", provider_name, exc)
        return []
    except Exception as exc:
        logger.warning("fetch_provider_models(%s) failed: %s", provider_name, exc)
        return []

    # Normalize response shape to a list of dicts
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("data", "models", "results", "model_ids"):
            val = data.get(key)
            if isinstance(val, list):
                return val
    return []


# ── Normalisation ──────────────────────────────────────────────────────────────


def _ensure_str(val: Any) -> str:
    if isinstance(val, str):
        return val
    if isinstance(val, (int, float)):
        return str(val)
    return ""


def _ensure_int(val: Any, default: int | None = None) -> int | None:
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def normalize_model(
    provider: str,
    raw_model: dict[str, Any],
    tier_map: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Normalise an arbitrary provider model dict into our schema.

    Handles OpenAI, OpenRouter, Google, Groq, Hugging Face, Replicate,
    and other common shapes.
    """
    model_id = _ensure_str(
        raw_model.get("id") or raw_model.get("name") or raw_model.get("model_id", "")
    )
    display_name = _ensure_str(
        raw_model.get("display_name")
        or raw_model.get("name")
        or raw_model.get("id")
        or model_id
    )
    owner = _ensure_str(raw_model.get("owned_by") or raw_model.get("owner") or "")

    context = _ensure_int(
        raw_model.get("context_window")
        or raw_model.get("context_length")
        or raw_model.get("max_input_tokens")
        or raw_model.get("input_token_limit")
        or raw_model.get("max_context_tokens")
    )
    max_in = _ensure_int(
        raw_model.get("max_input_tokens") or raw_model.get("max_input_length")
    )
    max_out = _ensure_int(
        raw_model.get("max_output_tokens") or raw_model.get("max_tokens")
    )

    is_free = detect_free_model(provider, raw_model)
    is_deprecated = bool(
        raw_model.get("deprecated") or raw_model.get("is_deprecated", False)
    )

    # Check against known-deprecated list from model_quality.json
    if not is_deprecated and tier_map:
        deprecated_set = getattr(normalize_model, "_deprecated_set", None)
        if deprecated_set is None:
            try:
                _mq_path = (
                    Path(__file__).resolve().parent.parent
                    / "config"
                    / "model_quality.json"
                )
                _mq = json.loads(_mq_path.read_text())
                deprecated_set = set(_mq.get("deprecated", []))
            except Exception:
                deprecated_set = set()
            normalize_model._deprecated_set = deprecated_set
        if model_id in deprecated_set or display_name in deprecated_set:
            is_deprecated = True

    # Tier: lookup from tier_map (model_quality.json) or use FreeLLMAPI-style rules
    tier = 4
    if tier_map:
        for candidate in (model_id, display_name):
            t = tier_map.get(candidate)
            if t is not None:
                tier = t
                break

    supported_features = raw_model.get("capabilities") or raw_model.get("features")
    if isinstance(supported_features, dict):
        supports_vision = bool(
            supported_features.get("vision")
            or supported_features.get("image_input", False)
        )
        supports_tools = bool(
            supported_features.get("tools")
            or supported_features.get("function_calling", False)
            or supported_features.get("tools_calling", False)
        )
        supports_streaming = not bool(supported_features.get("streaming") is False)
        supports_function_calling = bool(
            supported_features.get("function_calling")
            or supported_features.get("tools", False)
        )
    elif isinstance(supported_features, list):
        fset = {f.lower().replace(" ", "_") for f in supported_features}
        supports_vision = "vision" in fset or "image_input" in fset
        supports_tools = "tools" in fset or "function_calling" in fset
        supports_streaming = "streaming" not in {
            f.lower() for f in supported_features if f.lower().startswith("no_stream")
        }
        supports_function_calling = "function_calling" in fset
    else:
        supports_vision = bool(
            raw_model.get("supports_vision") or raw_model.get("vision", False)
        )
        supports_tools = bool(
            raw_model.get("supports_tools") or raw_model.get("tools", False)
        )
        supports_streaming = bool(raw_model.get("supports_streaming", True))
        supports_function_calling = bool(
            raw_model.get("supports_function_calling")
            or raw_model.get("function_calling", False)
        )

    rpm = _ensure_int(
        raw_model.get("rpm")
        or raw_model.get("rpm_limit")
        or raw_model.get("requests_per_minute")
    )
    rpd = _ensure_int(raw_model.get("rpd") or raw_model.get("rpd_limit"))
    tpm = _ensure_int(
        raw_model.get("tpm")
        or raw_model.get("tpm_limit")
        or raw_model.get("tokens_per_minute")
    )
    tpd = _ensure_int(raw_model.get("tpd") or raw_model.get("tpd_limit"))

    return {
        "provider": provider,
        "model_id": model_id,
        "display_name": display_name,
        "context_window": context,
        "max_input_tokens": max_in,
        "max_output_tokens": max_out,
        "supports_vision": supports_vision,
        "supports_tools": supports_tools,
        "supports_streaming": supports_streaming,
        "supports_function_calling": supports_function_calling,
        "is_free": is_free,
        "is_deprecated": is_deprecated,
        "tier": tier,
        "owner": owner or provider,
        "rpm_limit": rpm,
        "rpd_limit": rpd,
        "tpm_limit": tpm,
        "tpd_limit": tpd,
        "raw_metadata": json.dumps(raw_model, default=str),
    }


# ── Sync orchestration ─────────────────────────────────────────────────────────


async def sync_provider_models(
    store: Any,
    provider: str,
    configs: dict[str, Any],
    key_id: int | None = None,
    tier_map: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Fetch models from *provider*, upsert into DB, and link *key_id*.

    Called when:
    - A new key is added for the provider
    - Periodic refresh (cron / manual CLI)
    - Web UI triggers a sync

    Returns a summary dict with the number of models upserted and errors.
    """
    provider_cfg = configs.get(provider, {})
    base_url = provider_cfg.get("base_url", "")
    api_key = None
    extra_params: dict[str, Any] = {}

    if key_id is not None:
        key_row = store.get_key_by_id(key_id)
        if key_row:
            api_key = key_row.get("api_key") or None
            base_url = key_row.get("base_url_override") or base_url
            extra_params = _parse_extra(key_row.get("extra_params", "{}"))
    else:
        # Try any active key for this provider
        keys = store.get_all_keys()
        for k in keys:
            if k["provider"] == provider and k.get("is_active"):
                api_key = k["api_key"]
                base_url = k.get("base_url_override") or base_url
                extra_params = _parse_extra(k.get("extra_params", "{}"))
                key_id = k["id"]
                break

    # Resolve URL templates like {account_id} from extra_params
    if "{account_id}" in base_url:
        base_url = base_url.format(account_id=extra_params.get("account_id", ""))

    raw_models = await fetch_provider_models(base_url, api_key, provider)

    if not raw_models:
        logger.warning("sync_provider_models(%s): no models returned", provider)
        with store._conn() as conn:
            mark_sync_failed(conn, provider)
        return {
            "provider": provider,
            "models_upserted": 0,
            "error": "no_models_returned",
        }

    upserted = 0
    with store._conn() as conn:
        for raw in raw_models:
            normalized = normalize_model(provider, raw, tier_map=tier_map)
            model_db_id = upsert_model(conn, **normalized)
            if key_id is not None:
                link_key_to_model(conn, key_id, model_db_id)
            upserted += 1

        upsert_catalog_source(
            conn,
            provider,
            models_endpoint=PROVIDER_ENDPOINTS.get(
                provider, f"{base_url.rstrip('/')}/v1/models"
            ),
            requires_api_key=bool(api_key),
            free_detection_method="auto",
            sync_status="success",
        )
        mark_sync_complete(conn, provider)

    logger.info("sync_provider_models(%s): %d models upserted", provider, upserted)
    return {"provider": provider, "models_upserted": upserted, "error": None}


async def sync_all_providers(
    store: Any,
    configs: dict[str, Any],
    tier_map: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Sync models for every configured provider that has at least one active key."""
    results: list[dict[str, Any]] = []
    keys = store.get_all_keys()
    seen_providers: set[str] = set()

    for k in keys:
        prov = k["provider"]
        if not k.get("is_active") or prov in seen_providers:
            continue
        seen_providers.add(prov)
        result = await sync_provider_models(
            store, prov, configs, k["id"], tier_map=tier_map
        )
        results.append(result)

    return results


__all__ = [
    "fetch_provider_models",
    "normalize_model",
    "sync_provider_models",
    "sync_all_providers",
]
