"""Free vs paid model detection for 40+ providers.

Strategies (in priority order):

1. **Explicit flag** in the provider API response (``free``, ``free_tier``)
2. **Model ID patterns** (``:free``, ``-free`` suffixes)
3. **Provider-specific rules** (all Groq = free, all OpenAI = paid, etc.)
4. **Hardcoded catalog** fallback (from ``free_models_catalog.json``)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

# ── Provider rule table ────────────────────────────────────────────────────────
#   True  → all models from this provider are free-tier
#   False → all models from this provider are paid (no free tier)
#   callable(raw_model) → dynamic check based on the raw API response

PROVIDER_RULES: dict[str, bool | Callable[[dict[str, Any]], bool]] = {
    # ── 100 % free tier ──────────────────────────────────────────────────────
    "groq": True,
    "cerebras": True,
    "google": True,  # Gemini models free tier
    "pollinations": True,  # Anon usage free
    "ollama": True,  # Ollama Cloud free tier
    "kilo": True,  # Kilo Gateway free tier (anon)
    "ovh": True,  # OVH AI Endpoints free tier
    "llm7": True,  # LLM7 free tier
    "opencode": True,  # OpenCode Zen promo
    "paxsenix": True,  # Paxsenix free tier
    "scaleway": True,  # Scaleway free tier
    "zhipu": True,  # Zhipu free tier
    "alibaba": True,  # Alibaba free tier
    "sambanova": True,  # SambaNova free tier
    "cloudflare": True,  # Cloudflare Workers AI free tier
    "huggingface": True,  # HF Inference Router free tier
    "github_models": True,  # GitHub Models free tier
    "agnes_ai": True,  # Agnes AI free tier
    "freellmapi": True,  # FreeLLMAPI gateway free tier
    # ── Mixed: check model ID or response ────────────────────────────────────
    "mistral": lambda m: "free" in m.get("id", "").lower(),
    "openrouter": lambda m: bool(m.get("pricing", {}).get("free", False)),
    "cohere": False,  # Cohere free tier is limited — not all models
    "nvidia": False,  # NVIDIA NIM eval-only, not all free
    "nvidia_nim": False,
    # ── Mostly paid / credits-based ─────────────────────────────────────────
    "openai": False,
    "anthropic": False,
    "deepseek": False,
    "replicate": False,
    "together": False,
    "fireworks": False,
    "deepinfra": False,
    "baseten": False,
    "nebius": False,
    "novita": False,
    "ai21": False,
    "upstage": False,
    "nlpcloud": False,
    "modal": False,
    "inference_net": False,
    "hyperbolic": False,
    "vercel": False,
    "lepton": False,
    "interfaze": False,
}


def _load_free_catalog() -> set[str]:
    """Load the hardcoded free-model catalog JSON, if present."""
    catalog_path = (
        Path(__file__).resolve().parent.parent / "config" / "free_models_catalog.json"
    )
    if not catalog_path.exists():
        return set()
    try:
        data = json.loads(catalog_path.read_text())
        return set(data.get("free_models", []))
    except (json.JSONDecodeError, Exception):
        return set()


_FREE_CATALOG: set[str] | None = None


def _get_free_catalog() -> set[str]:
    global _FREE_CATALOG
    if _FREE_CATALOG is None:
        _FREE_CATALOG = _load_free_catalog()
    return _FREE_CATALOG


# ── Free patterns in model IDs ─────────────────────────────────────────────────

_FREE_PATTERNS = (
    ":free",
    "-free",
    "free-",
    "-free-",
    ":free-tier",
    "-free-tier",
    "free_trial",
    "trial",
    "gemini-2.0-flash",
    "gemini-2.5-flash",  # Google free models explicitly
)


def detect_free_model(provider: str, raw_model: dict[str, Any]) -> bool:
    """Return ``True`` if *raw_model* is available on a free tier.

    Uses strategies in priority order:
    1. Explicit ``free`` flag in response
    2. Model ID patterns
    3. Provider-specific rule
    4. Hardcoded free-model catalog
    """
    # Strategy 1: explicit flag in the API response
    if raw_model.get("free") or raw_model.get("free_tier") or raw_model.get("is_free"):
        return True
    if raw_model.get("pricing"):
        pricing = raw_model["pricing"]
        if isinstance(pricing, dict) and pricing.get("free"):
            return True

    # Strategy 2: model ID patterns
    model_id = str(raw_model.get("id", "")).lower()
    if any(p in model_id for p in _FREE_PATTERNS):
        return True

    # Strategy 3: provider-specific rule
    rule = PROVIDER_RULES.get(provider)
    if callable(rule):
        return rule(raw_model)
    if isinstance(rule, bool):
        return rule

    # Strategy 4: hardcoded catalog fallback
    catalog = _get_free_catalog()
    if model_id in catalog:
        return True

    return False


def reload_catalog() -> int:
    """Force reload the free-models catalog from disk. Returns count."""
    global _FREE_CATALOG
    _FREE_CATALOG = _load_free_catalog()
    return len(_FREE_CATALOG)


__all__ = ["detect_free_model", "reload_catalog"]
