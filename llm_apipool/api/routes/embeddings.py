from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from llm_apipool.api.errors import INVALID_REQUEST_ERROR, ROUTING_ERROR, error_response
from llm_apipool.core.embeddings import (
    EMBEDDING_FAMILIES,
    get_default_family,
    list_embeddings,
)


class _EmbeddingsRequest(BaseModel):
    model: str | None = "auto"
    input: str | list[str] | None = None


def _create_embeddings_router(store: Any) -> APIRouter:  # noqa: C901
    router = APIRouter()

    @router.post("/v1/embeddings")
    async def embeddings_endpoint(req: _EmbeddingsRequest) -> Any:
        model = req.model or "auto"
        if model == "auto":
            model = get_default_family()

        if model not in EMBEDDING_FAMILIES:
            return error_response(
                400, f"Unknown embedding model family: {model}", INVALID_REQUEST_ERROR
            )

        family = EMBEDDING_FAMILIES[model]
        input_text = req.input

        if isinstance(input_text, str):
            input_text = [input_text]

        for provider_config in family["providers"]:
            provider = provider_config["platform"]
            model_id = provider_config["model_id"]
            key_data = store.get_active_keys()
            matching_key = next(
                (k for k in key_data if k.get("provider") == provider), None
            )
            if not matching_key:
                continue

            try:
                import httpx

                embedding_input = input_text[:1] if input_text else [""]
                api_key = matching_key["api_key"] or ""
                if provider == "google":
                    headers = {}
                    if api_key:
                        headers["x-goog-api-key"] = api_key
                    async with httpx.AsyncClient() as client:
                        resp = await client.post(
                            "https://generativelanguage.googleapis.com/v1beta/openai/embeddings",
                            headers=headers,
                            json={"model": model_id, "input": embedding_input},
                            timeout=30.0,
                        )
                    resp.raise_for_status()
                    data = resp.json()
                    return {
                        "object": "list",
                        "data": [
                            {"embedding": data["data"][0]["embedding"], "index": 0}
                        ],
                        "model": model,
                        "usage": {
                            "prompt_tokens": len(embedding_input),
                            "total_tokens": len(embedding_input),
                        },
                    }
            except Exception:
                continue

        return error_response(
            503, f"No available provider for embedding family: {model}", ROUTING_ERROR
        )

    @router.get("/api/embeddings")
    async def list_embeddings_endpoint() -> dict[str, Any]:
        return list_embeddings()

    @router.get("/api/embeddings/usage")
    async def embeddings_usage_endpoint() -> dict[str, Any]:
        from llm_apipool.core.embeddings import get_embeddings_usage

        return get_embeddings_usage()

    return router


__all__ = [
    "_create_embeddings_router",
    "list_embeddings",
    "get_default_family",
    "EMBEDDING_FAMILIES",
]
