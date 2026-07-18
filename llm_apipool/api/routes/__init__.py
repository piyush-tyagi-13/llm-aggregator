"""API route modules for llm-apipool proxy.

Each module exposes a factory function ``_create_*_router`` that accepts
shared dependencies (store, rotator, configs) and returns a configured
``APIRouter`` instance.
"""

from __future__ import annotations


from . import analytics
from . import chat
from . import embeddings
from . import health
from . import keys
from . import models
from . import responses
from . import settings
from . import tiers

__all__ = [
    "analytics",
    "chat",
    "embeddings",
    "health",
    "keys",
    "models",
    "responses",
    "settings",
    "tiers",
]
