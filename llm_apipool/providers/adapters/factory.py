"""Provider adapter factory — auto-registers OpenAI-compatible providers from providers.json.

Eliminates 14 manually-maintained adapter files. Use::

    from llm_apipool.providers.adapters.factory import auto_register_providers
    auto_register_providers()

"""

from __future__ import annotations

from typing import Any

from ..base import BaseProvider
from ..registry import register
from ._base import OpenAICompatProvider


def _make_provider_class(
    platform: str,
    name: str,
    default_model: str,
    base_url: str,
    limits: dict[str, Any] | None = None,
) -> type[BaseProvider]:
    """Dynamically create an OpenAICompatProvider subclass for *platform*."""
    namespace = {
        "platform": platform,
        "name": name,
        "default_model": default_model,
        "base_url": base_url,
        "rpm_limit": (limits or {}).get("rpm"),
        "rpd_limit": (limits or {}).get("rpd"),
        "tpm_limit": (limits or {}).get("tpm"),
        "tpd_limit": (limits or {}).get("tpd"),
    }
    cls = type(f"{platform.capitalize()}Provider", (OpenAICompatProvider,), namespace)
    return register(cls)


def auto_register_providers(
    provider_configs: dict[str, Any] | None = None,
) -> dict[str, type[BaseProvider]]:
    """Scan ``providers.json`` and register every OpenAI-compatible provider.

    Returns a dict mapping platform → generated class (for introspection).
    """
    if provider_configs is None:
        from ...config.loader import load_providers_config

        provider_configs = load_providers_config()

    from ..registry import has_provider as _has_provider

    registered: dict[str, type[BaseProvider]] = {}
    for platform, conf in provider_configs.items():
        if not conf.get("openai_compatible", True):
            continue
        if platform in ("cloudflare", "cohere"):
            continue
        # Skip providers already registered via manual adapter files
        if _has_provider(platform):
            continue

        cls = _make_provider_class(
            platform=platform,
            name=conf.get("name", platform.replace("_", " ").title()),
            default_model=conf.get("default_model", ""),
            base_url=conf.get("base_url", ""),
            limits=conf.get("limits"),
        )
        registered[platform] = cls

    return registered


__all__ = ["auto_register_providers"]
