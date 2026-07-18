"""FastAPI application package for llm-apipool.

Provides the OpenAI-compatible proxy API with all routes organized
into separate modules following the FreeLLMAPI architecture.
"""

from __future__ import annotations


from llm_apipool.api.app import make_app

__all__ = ["make_app"]
