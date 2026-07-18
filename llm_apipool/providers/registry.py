"""Provider registry — maps platform names to ``BaseProvider`` adapter classes.

Usage::

    from llm_apipool.providers.registry import register, get_provider, list_providers

    @register
    class MyProvider(BaseProvider):
        platform = "my_platform"
        name = "My Provider"
        ...
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .base import BaseProvider

_registry: dict[str, type[BaseProvider]] = {}
_instances: dict[str, BaseProvider] = {}
_discovered = False


def register(cls: type[BaseProvider]) -> type[BaseProvider]:
    """Decorate a ``BaseProvider`` subclass to register it in the global registry.

    The class must have a ``platform`` attribute (used as the lookup key).
    """
    platform = getattr(cls, "platform", None)
    if not platform:
        msg = f"{cls.__name__} must define a `platform` attribute"
        raise ValueError(msg)
    if platform in _registry and _registry[platform] is not cls:
        msg = f"Provider '{platform}' is already registered to {_registry[platform].__name__}"
        raise ValueError(msg)
    _registry[platform] = cls
    return cls


def get_provider(platform: str) -> BaseProvider | None:
    """Return a cached instance of the provider for *platform*, or ``None``."""
    _ensure_discovered()
    cls = _registry.get(platform)
    if cls is None:
        return None
    if platform not in _instances:
        _instances[platform] = cls()
    return _instances[platform]


def has_provider(platform: str) -> bool:
    """Check whether *platform* has a registered provider."""
    _ensure_discovered()
    return platform in _registry


def list_providers() -> list[str]:
    """Return sorted platform names of all registered providers."""
    _ensure_discovered()
    return sorted(_registry)


def unregister(platform: str) -> None:
    """Remove a provider from the registry (used in tests)."""
    _registry.pop(platform, None)
    _instances.pop(platform, None)


def _ensure_discovered() -> None:
    """Lazy-import all adapter modules so their ``@register`` decorators fire."""
    global _discovered
    if _discovered:
        return
    _discovered = True

    # Import native provider modules (not generated from config)
    _import_module("llm_apipool.providers.cloudflare")
    _import_module("llm_apipool.providers.cohere")
    _import_module("llm_apipool.providers.openai_compat")

    # Auto-discover adapters in providers/adapters/
    _discover_adapters()

    # Register all OpenAI-compatible providers from providers.json config
    # (skips any already registered manually or via adapter files)
    _auto_register_config_providers()


def _auto_register_config_providers() -> None:
    """Register every OpenAI-compatible provider from ``providers.json``."""
    try:
        from .adapters.factory import auto_register_providers

        auto_register_providers()
    except ImportError:
        pass


def _import_module(dotted: str) -> Any | None:
    """Try importing a module by dotted path, return the module or ``None``."""
    try:
        return importlib.import_module(dotted)
    except ImportError:
        return None


def _discover_adapters() -> None:
    """Scan ``providers/adapters/`` for Python modules and import them."""
    try:
        pkg = importlib.import_module("llm_apipool.providers.adapters")
        for _finder, name, _ispkg in pkgutil.iter_modules(pkg.__path__):
            _import_module(f"llm_apipool.providers.adapters.{name}")
    except (ImportError, AttributeError):
        pass
