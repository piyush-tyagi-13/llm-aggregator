from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from llm_apipool.api.errors import INVALID_REQUEST_ERROR, error_response
from llm_apipool.key_store import KeyStore


_CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"
_MODEL_QUALITY_PATH = _CONFIG_DIR / "model_quality.json"

_lock = threading.Lock()


def _tier_name_to_num(tier_name: str) -> int | None:
    """Convert 'tier1' → 1, 'tier2' → 2, etc. Returns None for unknown."""
    if tier_name.startswith("tier") and tier_name[4:].isdigit():
        return int(tier_name[4:])
    return None


def _sync_tier_to_db(model_id: str, tier_name: str) -> None:
    """Sync a model's tier assignment to the DB models table.

    Updates every row where model_id matches (models can exist under
    multiple providers).
    """
    tier_num = _tier_name_to_num(tier_name)
    if tier_num is None:
        return
    try:
        store = KeyStore()
        with store._conn() as conn:
            conn.execute(
                "UPDATE models SET tier = ? WHERE model_id = ?",
                (tier_num, model_id),
            )
    except Exception:
        pass  # DB sync is best-effort


def _load_tiers() -> dict[str, list[str]]:
    with _MODEL_QUALITY_PATH.open() as f:
        return json.load(f)


def _save_tiers(data: dict[str, list[str]]) -> None:
    with _MODEL_QUALITY_PATH.open("w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


class _TiersResponse(BaseModel):
    tiers: dict[str, list[str]]


class _MoveModelRequest(BaseModel):
    model: str
    from_tier: str
    to_tier: str


def _create_tiers_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/tiers")
    async def get_tiers() -> _TiersResponse:
        with _lock:
            tiers = _load_tiers()
        return _TiersResponse(tiers=tiers)

    @router.put("/api/tiers")
    async def update_tiers(req: _TiersResponse) -> dict[str, Any]:
        with _lock:
            current = _load_tiers()
            for tier_key, models in req.tiers.items():
                if tier_key in current:
                    current[tier_key] = models
            _save_tiers(current)
        return {"success": True, "message": "Tiers updated"}

    @router.post("/api/tiers/move-model")
    async def move_model(req: _MoveModelRequest) -> dict[str, Any]:
        with _lock:
            tiers = _load_tiers()
            if req.to_tier not in tiers:
                return error_response(
                    400,
                    f"Invalid target tier: {req.to_tier}. Valid: {list(tiers.keys())}",
                    INVALID_REQUEST_ERROR,
                )
            for tier_key in tiers:
                if req.model in tiers[tier_key]:
                    tiers[tier_key].remove(req.model)
            if req.model not in tiers[req.to_tier]:
                tiers[req.to_tier].append(req.model)
            _save_tiers(tiers)
        # Sync tier change to DB models table (best-effort)
        _sync_tier_to_db(req.model, req.to_tier)
        return {"success": True, "message": f"Moved '{req.model}' to {req.to_tier}"}

    return router


__all__ = ["_create_tiers_router"]
