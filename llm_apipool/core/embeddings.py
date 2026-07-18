from __future__ import annotations

from typing import Any

EMBEDDING_FAMILIES: dict[str, dict[str, Any]] = {
    "gemini-embedding-001": {
        "providers": [{"platform": "google", "model_id": "text-embedding-004"}],
        "dimensions": 3072,
        "max_input_tokens": 2048,
    },
    "text-embedding-3-large": {
        "providers": [{"platform": "github", "model_id": "text-embedding-3-large"}],
        "dimensions": 3072,
        "max_input_tokens": 8191,
    },
    "text-embedding-3-small": {
        "providers": [{"platform": "github", "model_id": "text-embedding-3-small"}],
        "dimensions": 1536,
        "max_input_tokens": 8191,
    },
    "bge-m3": {
        "providers": [
            {"platform": "cloudflare", "model_id": "@cf/baai/bge-m3"},
            {"platform": "huggingface", "model_id": "BAAI/bge-m3"},
        ],
        "dimensions": 1024,
        "max_input_tokens": 8192,
    },
}


def get_default_family() -> str:
    return "gemini-embedding-001"


def list_embeddings() -> dict[str, Any]:
    return {
        "default_family": get_default_family(),
        "families": [
            {
                "family": family,
                "dimensions": data["dimensions"],
                "max_input_tokens": data["max_input_tokens"],
                "is_default": family == get_default_family(),
                "providers": data["providers"],
            }
            for family, data in EMBEDDING_FAMILIES.items()
        ],
    }


def get_embeddings_usage() -> dict[str, Any]:
    return {"families": []}
