"""Model tier classification system.

Assigns every known model to a quality tier (1-4) based on objective
capability rules:

- Tier 1 (Frontier)   → context >200K OR thinking/reasoning model
- Tier 2 (High-Perf)  → context 32-200K OR smaller reasoning/coding
- Tier 3 (Good OSS)   → context 8-32K, standard OSS models
- Tier 4 (Fallback)   → context <8K, very small / legacy models

The module also exposes a registry of 200+ popular models with their
capability metadata.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Model metadata entry
# ---------------------------------------------------------------------------

# context_window, thinking, tools, vision, coding
ModelMeta = tuple[int, bool, bool, bool, bool]


def _m(
    ctx: int,
    thinking: bool = False,
    tools: bool = False,
    vision: bool = False,
    coding: bool = False,
) -> ModelMeta:
    return (ctx, thinking, tools, vision, coding)


# ---------------------------------------------------------------------------
# Master model registry  (~220 models)
#
# Keys are the canonical model IDs as they appear in API calls.
# Aliases / alternative names are listed second.
# ---------------------------------------------------------------------------

_MODEL_REGISTRY: dict[str, ModelMeta] = {
    # ═══════════════════════════════════════════════════════════════════════
    # OpenAI
    # ═══════════════════════════════════════════════════════════════════════
    "gpt-4o": _m(128000, vision=True, tools=True),
    "gpt-4o-2024-08-06": _m(128000, vision=True, tools=True),
    "gpt-4o-mini": _m(128000, vision=True, tools=True),
    "gpt-4o-mini-2024-07-18": _m(128000, vision=True, tools=True),
    "gpt-4-turbo": _m(128000, vision=True, tools=True),
    "gpt-4-turbo-2024-04-09": _m(128000, vision=True, tools=True),
    "gpt-4": _m(8192, tools=True),
    "gpt-4-32k": _m(32768, tools=True),
    "gpt-3.5-turbo": _m(16385, tools=True),
    "gpt-3.5-turbo-0125": _m(16385, tools=True),
    "o1-preview": _m(128000, thinking=True),
    "o1-mini": _m(128000, thinking=True),
    "o1": _m(200000, thinking=True, vision=True),
    "o3-mini": _m(200000, thinking=True),
    "o3": _m(200000, thinking=True, vision=True),
    "o4-mini": _m(200000, thinking=True, vision=True, tools=True),
    "gpt-5-chat": _m(256000, thinking=True, vision=True, tools=True),
    # gpt-5 variants
    "gpt-5-high": _m(256000, thinking=True, vision=True, tools=True),
    "gpt-5-medium": _m(256000, thinking=True, vision=True, tools=True),
    # ═══════════════════════════════════════════════════════════════════════
    # Anthropic
    # ═══════════════════════════════════════════════════════════════════════
    "claude-3-opus-20240229": _m(200000, vision=True, tools=True),
    "claude-3-sonnet-20240229": _m(200000, vision=True, tools=True),
    "claude-3-haiku-20240307": _m(200000, vision=True, tools=True),
    "claude-3-5-sonnet-20241022": _m(200000, vision=True, tools=True),
    "claude-3-5-haiku-20241022": _m(200000, vision=True, tools=True),
    "claude-opus-4": _m(200000, thinking=True, vision=True, tools=True),
    "claude-sonnet-4-6": _m(200000, thinking=True, vision=True, tools=True),
    "claude-sonnet-4": _m(200000, thinking=True, vision=True, tools=True),
    "claude-haiku-4": _m(200000, thinking=True, vision=True, tools=True),
    "claude-opus-4-5": _m(200000, thinking=True, vision=True, tools=True),
    # ═══════════════════════════════════════════════════════════════════════
    # Google / Gemini
    # ═══════════════════════════════════════════════════════════════════════
    "gemini-2.0-flash": _m(1048576, vision=True, tools=True),
    "gemini-2.0-flash-lite": _m(1048576, vision=True, tools=True),
    "gemini-2.0-flash-001": _m(1048576, vision=True, tools=True),
    "gemini-2.5-flash": _m(1048576, thinking=True, vision=True, tools=True),
    "gemini-2.5-pro": _m(1048576, thinking=True, vision=True, tools=True),
    "gemini-2.5-pro-exp-03-25": _m(1048576, thinking=True, vision=True, tools=True),
    "gemini-2.0-flash-thinking-exp": _m(
        1048576, thinking=True, vision=True, tools=True
    ),
    "gemini-1.5-flash": _m(1048576, vision=True, tools=True),
    "gemini-1.5-flash-8b": _m(1048576, vision=True, tools=True),
    "gemini-1.5-pro": _m(1048576, vision=True, tools=True),
    "gemini-1.0-pro": _m(32768, tools=True),
    # ═══════════════════════════════════════════════════════════════════════
    # Meta / Llama
    # ═══════════════════════════════════════════════════════════════════════
    "Meta-Llama-3.1-405B-Instruct": _m(131072, tools=True),
    "meta-llama/Llama-3.1-405B-Instruct": _m(131072, tools=True),
    "Meta-Llama-3.3-70B-Instruct": _m(131072, tools=True),
    "meta-llama/Llama-3.3-70B-Instruct": _m(131072, tools=True),
    "meta-llama/Llama-3.3-70B-Instruct-Turbo": _m(131072, tools=True),
    "llama-3.3-70b-versatile": _m(131072, tools=True),
    "llama-3.3-70b-instruct": _m(131072, tools=True),
    "llama-3.3-70b": _m(131072, tools=True),
    "llama3.3-70b": _m(131072, tools=True),
    "@cf/meta/llama-3.3-70b-instruct-fp8-fast": _m(131072, tools=True),
    "meta-llama/llama-3.3-70b-instruct:free": _m(131072, tools=True),
    "accounts/fireworks/models/llama-v3p3-70b-instruct": _m(131072, tools=True),
    "Meta-Llama-3.1-70B-Instruct": _m(131072, tools=True),
    "meta-llama/Meta-Llama-3.1-70B-Instruct": _m(131072, tools=True),
    "llama-3.1-70b": _m(131072, tools=True),
    "meta-llama-3-70b-instruct": _m(8192, tools=True),
    "meta/meta-llama-3-70b-instruct": _m(8192, tools=True),
    "llama3-70b": _m(8192, tools=True),
    "finetuned-llama-3-70b": _m(8192, tools=True),
    "Meta-Llama-3.1-8B-Instruct": _m(131072, tools=True),
    "meta-llama/Llama-3.1-8B-Instruct": _m(131072, tools=True),
    "meta-llama/Meta-Llama-3.1-8B-Instruct": _m(131072, tools=True),
    "@cf/meta/llama-3.1-8b-instruct": _m(131072, tools=True),
    "accounts/fireworks/models/llama-v3p1-8b-instruct": _m(131072, tools=True),
    "Llama-3.1-8B-Instruct": _m(131072, tools=True),
    "llama-3.1-8b-instant": _m(131072, tools=True),
    "llama-3.1-8b-instruct": _m(131072, tools=True),
    "llama-3.1-8b": _m(131072, tools=True),
    "llama3.1-8b": _m(131072, tools=True),
    "llama-3-8b": _m(8192),
    "llama3.2-3b": _m(8192),
    "llama3.2-1b": _m(8192),
    "llama-3.2-3b": _m(8192),
    "llama-3.2-1b": _m(8192),
    "llama-3.2-11b-vision": _m(131072, vision=True),
    "llama-3.2-90b-vision": _m(131072, vision=True),
    "llama-3.2-11b": _m(131072),
    "llama-3.2-90b": _m(131072),
    # ═══════════════════════════════════════════════════════════════════════
    # Mistral
    # ═══════════════════════════════════════════════════════════════════════
    "mistral-large-latest": _m(131072, tools=True, coding=True),
    "mistral-large-2411": _m(131072, tools=True, coding=True),
    "mistral-small-latest": _m(32768, tools=True),
    "mistral-small-3.2-24b-instruct-2506": _m(32768, tools=True),
    "mistralai/Mistral-Small-3.2-24B-Instruct-2506": _m(32768, tools=True),
    "open-mistral-7b": _m(8192),
    "open-mixtral-8x7b": _m(32768, tools=True),
    "mixtral-8x7b-32768": _m(32768, tools=True),
    "mixtral-8x7b": _m(32768, tools=True),
    "Mixtral-8x7B-Instruct-v0.1": _m(32768, tools=True),
    "mixtral-8x22b": _m(65536, tools=True),
    "mistral-7b-instruct": _m(8192),
    "Mistral-7B-Instruct-v0.3": _m(8192),
    "mistralai/mistral-7b-instruct:free": _m(8192),
    "mistralai/mistral-7b-instruct": _m(8192),
    "mistralai/mistral-7b-instruct-v0.3": _m(8192),
    "mistral-7b": _m(8192),
    "mistral": _m(8192),
    "@cf/mistral/mistral-7b-instruct-v0.2-lora": _m(8192),
    "ministral-8b-2512": _m(131072),
    "Ministral-3B": _m(32768),
    "codestral-latest": _m(256000, coding=True),
    "codestral-2501": _m(256000, coding=True),
    "Codestral-25.01": _m(256000, coding=True),
    # ═══════════════════════════════════════════════════════════════════════
    # DeepSeek
    # ═══════════════════════════════════════════════════════════════════════
    "deepseek-ai/DeepSeek-V4-Pro": _m(128000, thinking=True, tools=True, coding=True),
    "deepseek-ai/DeepSeek-V4-Flash": _m(128000, thinking=True, tools=True),
    "deepseek-ai/DeepSeek-V3": _m(128000, thinking=True, tools=True),
    "deepseek-ai/DeepSeek-V3-0324": _m(128000, thinking=True, tools=True),
    "deepseek-ai/deepseek-r1-0528": _m(128000, thinking=True, tools=True),
    "DeepSeek-R1-0528": _m(128000, thinking=True, tools=True),
    "DeepSeek-V3": _m(128000, thinking=True, tools=True),
    "deepseek-chat": _m(128000, thinking=True, tools=True),
    "deepseek-reasoner": _m(128000, thinking=True, tools=True),
    "deepseek/deepseek-r1": _m(128000, thinking=True, tools=True),
    "accounts/fireworks/models/deepseek-v3p1": _m(128000, thinking=True, tools=True),
    "accounts/fireworks/models/kimi-k2-instruct-0905": _m(
        128000, thinking=True, tools=True, coding=True
    ),
    "deepseek-coder": _m(128000, coding=True),
    "deepseek-v4": _m(128000, thinking=True, tools=True, coding=True),
    "deepseek-r1-7b": _m(32768, thinking=True),
    # ═══════════════════════════════════════════════════════════════════════
    # Qwen / Alibaba
    # ═══════════════════════════════════════════════════════════════════════
    "Qwen/Qwen3-235B-A22B-Instruct-2507": _m(131072, thinking=True, tools=True),
    "qwen-3-235b": _m(131072, thinking=True, tools=True),
    "qwen3-235b-a22b-instruct-2507": _m(131072, thinking=True, tools=True),
    "qwen/qwen3-coder-480b-a35b-instruct": _m(
        131072, thinking=True, tools=True, coding=True
    ),
    "Qwen2.5-72B-Instruct": _m(131072, tools=True),
    "qwen/qwen-2.5-72b-instruct:free": _m(131072, tools=True),
    "Qwen/Qwen2.5-72B-Instruct": _m(131072, tools=True),
    "qwen2.5-72b": _m(131072, tools=True),
    "qwen2.5-7b": _m(32768, tools=True),
    "qwen2-72b": _m(131072, tools=True),
    "qwen-coder-7b": _m(32768, coding=True),
    "qwen/qwen3-32b": _m(32768, tools=True, thinking=True),
    "qwen/qwen3-coder:free": _m(32768, coding=True),
    "qwen-max": _m(32768, tools=True),
    "qwen-plus": _m(131072, tools=True),
    "qwen-turbo": _m(131072, tools=True),
    # ═══════════════════════════════════════════════════════════════════════
    # Cohere
    # ═══════════════════════════════════════════════════════════════════════
    "command-a-03-2025": _m(256000, tools=True, coding=True),
    "command-r-plus-08-2024": _m(128000, tools=True),
    "command-r-08-2024": _m(128000, tools=True),
    "command-r": _m(128000, tools=True),
    # ═══════════════════════════════════════════════════════════════════════
    # Google / Gemma
    # ═══════════════════════════════════════════════════════════════════════
    "gemma-4-31B-it": _m(8192, tools=True),
    "google/gemma-4-31B-it": _m(8192, tools=True),
    "google/gemma-3-27b-it:free": _m(8192, tools=True),
    "gemma-3-27b-it": _m(8192, tools=True),
    "gemma2-9b-it": _m(8192),
    # ═══════════════════════════════════════════════════════════════════════
    # NVIDIA
    # ═══════════════════════════════════════════════════════════════════════
    "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B": _m(131072, tools=True),
    "gpt-oss-120b": _m(131072, tools=True),
    "nvidia/llama-3.1-nemotron-70b-instruct": _m(131072, tools=True),
    "nvidia/llama-3.1-nemotron-70b-instruct:free": _m(131072, tools=True),
    "nvidia/nemotron-nano-9b-v2:free": _m(8192),
    "nvidia/nemotron-nano-9b-v2": _m(8192),
    "nvidia/llama-3.1-nemotron-nano-9b-v2": _m(8192),
    # ═══════════════════════════════════════════════════════════════════════
    # Microsoft / Phi
    # ═══════════════════════════════════════════════════════════════════════
    "microsoft/phi-4:free": _m(16384, tools=True),
    "microsoft/phi-4": _m(16384, tools=True),
    "Phi-4": _m(16384, tools=True),
    "microsoft/Phi-4-mini-instruct": _m(16384),
    "Phi-4-mini": _m(16384),
    "phi-3": _m(128000),
    "Phi-3.5-mini-instruct": _m(128000),
    # ═══════════════════════════════════════════════════════════════════════
    # Zhipu / GLM
    # ═══════════════════════════════════════════════════════════════════════
    "glm-4-plus": _m(128000, tools=True),
    "glm-5.2": _m(128000, thinking=True, tools=True),
    "glm-4-flash": _m(128000, tools=True),
    "glm-4v-plus": _m(128000, vision=True, tools=True),
    # ═══════════════════════════════════════════════════════════════════════
    # Other notable models
    # ═══════════════════════════════════════════════════════════════════════
    "kimi-k27-code": _m(128000, coding=True),
    "jamba-1.5-large": _m(256000, tools=True),
    "jamba-1.5-mini": _m(256000, tools=True),
    "jamba-instruct": _m(65536),
    "solar-pro": _m(32768, tools=True),
    "solar-mini": _m(32768),
    "agnes-1.0": _m(8192),
    "agnes-mini": _m(8192),
    "interfaze/interfaze-beta": _m(8192),
    # ═══════════════════════════════════════════════════════════════════════
    # OpenRouter community models (unique entries not in vendor sections)
    # ═══════════════════════════════════════════════════════════════════════
    "deepseek/deepseek-r1:free": _m(128000, thinking=True, tools=True),
    # (no unique Fireworks entries beyond those in vendor sections)
    # ═══════════════════════════════════════════════════════════════════════
    # Together / Perplexity / Other
    # ═══════════════════════════════════════════════════════════════════════
    "togethercomputer/llama-3.3-70b-instruct": _m(131072, tools=True),
    "togethercomputer/mixtral-8x22b-instruct": _m(65536, tools=True),
    "perplexity/llama-3.1-sonar-huge-128k": _m(131072, tools=True),
    "perplexity/llama-3.1-sonar-large-128k": _m(131072, tools=True),
    "perplexity/llama-3.1-sonar-small-128k": _m(131072, tools=True),
    # ═══════════════════════════════════════════════════════════════════════
    # Additional popular models
    # ═══════════════════════════════════════════════════════════════════════
    "claude-3-opus": _m(200000, vision=True, tools=True),
    "claude-3-sonnet": _m(200000, vision=True, tools=True),
    "claude-3-haiku": _m(200000, vision=True, tools=True),
    "claude-3-5-sonnet": _m(200000, vision=True, tools=True),
    "claude-3-5-haiku": _m(200000, vision=True, tools=True),
    "gemini-2.0-flash-exp": _m(1048576, vision=True, tools=True),
    "gemini-2.5-flash-preview": _m(1048576, thinking=True, vision=True, tools=True),
    "gemini-2.0-pro-exp": _m(1048576, vision=True, tools=True),
    "gpt-4o-2024-11-20": _m(128000, vision=True, tools=True),
    "gpt-4o-audiopreview": _m(128000, vision=True, tools=True),
    "o1-2024-12-17": _m(200000, thinking=True, vision=True),
    "deepseek-chat-v3-0324": _m(128000, thinking=True, tools=True),
    "deepseek-reasoner-r1-0528": _m(128000, thinking=True, tools=True),
    "qwen2.5-coder-32b": _m(32768, coding=True),
    "qwen2.5-coder-7b": _m(32768, coding=True),
    "codestral-2505": _m(256000, coding=True),
    "codestral-mamba": _m(256000, coding=True),
    "command-r7b": _m(128000, tools=True),
    "ministral-3b-2410": _m(32768),
    "ministral-8b-2410": _m(131072),
    "mistral-nemo": _m(128000, tools=True),
    "pixtral-12b": _m(128000, vision=True),
    "pixtral-large-2411": _m(128000, vision=True, tools=True),
    "reka-core": _m(131072, vision=True),
    "reka-flash": _m(32768, vision=True),
    "solar-1-mini": _m(32768),
    "solar-1-pro": _m(32768, tools=True),
    "claude-3-opus-4k": _m(4096, vision=True, tools=True),
    "gpt-4-1106-preview": _m(128000, tools=True),
    "gpt-4-vision-preview": _m(128000, vision=True),
    "gpt-4-0125-preview": _m(128000, tools=True),
    "gpt-4-turbo-preview": _m(128000, tools=True),
    "text-davinci-003": _m(4097),
    "text-davinci-002": _m(4097),
    "code-davinci-002": _m(8192, coding=True),
    "llama-guard-3-8b": _m(8192),
    "llama-guard-2-8b": _m(8192),
}


# ---------------------------------------------------------------------------
# Aliases: alternative names that resolve to the same canonical entry
# ---------------------------------------------------------------------------

_ALIASES: dict[str, str] = {
    "gpt-4o-2024-08-06": "gpt-4o",
    "gpt-4o-mini-2024-07-18": "gpt-4o-mini",
    "gpt-4-turbo-2024-04-09": "gpt-4-turbo",
    "gpt-3.5-turbo-0125": "gpt-3.5-turbo",
    "claude-sonnet-4-6": "claude-sonnet-4",
    "deepseek-ai/DeepSeek-V4-Pro": "deepseek-v4",
    "deepseek-ai/DeepSeek-V4-Flash": "deepseek-v4",
    "deepseek-ai/DeepSeek-V3": "DeepSeek-V3",
    "deepseek-ai/DeepSeek-V3-0324": "deepseek-chat",
    "deepseek-ai/deepseek-r1-0528": "DeepSeek-R1-0528",
    "mistral-large-2411": "mistral-large-latest",
    "codestral-2501": "codestral-latest",
    "Codestral-25.01": "codestral-latest",
    "command-r-08-2024": "command-r",
    "gemini-2.0-flash-001": "gemini-2.0-flash",
}

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_model_meta(model_name: str) -> ModelMeta | None:
    """Look up a model's capability metadata.

    Checks the main registry first, then aliases.  Returns ``None`` for
    unknown models.
    """
    if model_name in _MODEL_REGISTRY:
        return _MODEL_REGISTRY[model_name]
    canonical = _ALIASES.get(model_name)
    if canonical and canonical in _MODEL_REGISTRY:
        return _MODEL_REGISTRY[canonical]
    return None


def classify_tier(model_name: str) -> int:
    """Classify a model into quality tier 1-4.

    Rules (evaluated in order):

    1. Tier 1 (Frontier):
       - Context window > 200K tokens
       - Thinking / reasoning model
       - Flagship coding model (codestral, deepseek-v4, etc.)
       - Provider's flagship model

    2. Tier 2 (High-Performance):
       - Context window 32K-200K
       - Smaller reasoning / thinking models
       - Smaller coding / code models
       - Strong OSS models (70B+)

    3. Tier 3 (Good OSS):
       - Context window 8-32K
       - Smaller open-source models (7B-32B range)

    4. Tier 4 (Fallback):
       - Context window < 8K
       - Very small / legacy models
       - Unknown models default here
    """
    meta = get_model_meta(model_name)
    if meta is None:
        return 4  # unknown → worst tier

    ctx, thinking, tools, vision, coding = meta

    # ── Tier 1 rules ──────────────────────────────────────────────────────
    if thinking:
        return 1
    if ctx > 200_000:
        return 1
    if coding and ctx >= 128_000:
        return 1
    # Flagship models
    _flagship_prefixes = (
        "gpt-4o",
        "gpt-5",
        "o1-",
        "o3-",
        "o4-",
        "claude-opus",
        "claude-sonnet",
        "claude-3-5-sonnet",
        "gemini-2.5",
        "gemini-2.0-flash-thinking",
        "mistral-large",
        "codestral",
        "deepseek",
        "DeepSeek",
        "command-a",
        "Qwen/Qwen3-235B",
    )
    if model_name.startswith(_flagship_prefixes):
        return 1

    # ── Tier 2 rules ──────────────────────────────────────────────────────
    if ctx >= 32_000:
        return 2
    if coding:
        return 2
    if tools and ctx >= 16_000:
        return 2
    # 70B+ models generally perform well
    _strong_oss_patterns = ("70b", "72b", "90b", "120b", "235b", "405b", "480b")
    if any(p in model_name.lower() for p in _strong_oss_patterns):
        return 2

    # ── Tier 3 rules ──────────────────────────────────────────────────────
    if ctx >= 8_000:
        return 3

    # ── Tier 4 ────────────────────────────────────────────────────────────
    return 4


def tier_label(tier: int) -> str:
    return {1: "Frontier", 2: "High-Performance", 3: "Good OSS", 4: "Fallback"}.get(
        tier, "Unknown"
    )


def build_tier_map() -> dict[str, int]:
    result: dict[str, int] = {}
    for name in _MODEL_REGISTRY:
        result[name] = classify_tier(name)
    for alias, canonical in _ALIASES.items():
        if canonical in result:
            result[alias] = result[canonical]
    return result


def group_by_tier() -> dict[int, list[str]]:
    groups: dict[int, list[str]] = {1: [], 2: [], 3: [], 4: []}
    for name, meta in _MODEL_REGISTRY.items():
        t = classify_tier(name)
        groups.setdefault(t, []).append(name)
    return groups


def generate_model_quality_json() -> dict[str, list[str]]:
    tier_map = build_tier_map()
    groups: dict[str, list[str]] = {"tier1": [], "tier2": [], "tier3": [], "tier4": []}
    for name, tier in sorted(tier_map.items()):
        groups[f"tier{tier}"].append(name)
    return groups


__all__ = [
    "ModelMeta",
    "classify_tier",
    "tier_label",
    "get_model_meta",
    "build_tier_map",
    "group_by_tier",
    "generate_model_quality_json",
]
