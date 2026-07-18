"""OpenAI-compatible HTTP proxy for llm-apipool.

Re-exports :func:`make_app` from :mod:`llm_apipool.api.app` for backward
compatibility. All route logic has been extracted to ``api/routes/``.
"""

from __future__ import annotations

from llm_apipool.api.app import make_app

# Legacy symbols kept for test backward compatibility
_APIPOOL_MODEL_ID = "LLM-Apipool"
_APIPOOL_MODEL_OWNER = "llm-apipool"


def _mask_key(api_key: str) -> str:
    if len(api_key) <= 8:
        return "****" + api_key[-4:] if len(api_key) > 4 else "****"
    return api_key[:4] + "****" + api_key[-4:]


__all__ = ["make_app", "_APIPOOL_MODEL_ID", "_APIPOOL_MODEL_OWNER", "_mask_key"]
