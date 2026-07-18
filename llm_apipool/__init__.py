"""
llm-apipool: Free-tier LLM API key pool manager with smart routing.
"""

from __future__ import annotations

try:
    from importlib.metadata import version as _version

    __version__ = _version("llm-apipool")
except Exception:  # pragma: no cover
    __version__ = "1.0.0"

from .api.app import make_app
from .core.catalog import get_model_info, list_models, list_providers
from .core.fallback import FallbackManager
from .core.health import check_all_keys
from .core.router import get_routing_strategy, set_routing_strategy
from .core.sticky import is_sticky_enabled, set_sticky_enabled
from .langchain_wrapper import AggregatorChat

__all__ = [
    "AggregatorChat",
    "FallbackManager",
    "check_all_keys",
    "get_model_info",
    "get_routing_strategy",
    "is_sticky_enabled",
    "list_models",
    "list_providers",
    "make_app",
    "set_routing_strategy",
    "set_sticky_enabled",
]
