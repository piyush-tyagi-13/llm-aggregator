"""API routes for per-model effort/thinking parameter configuration."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from llm_apipool.core.model_effort import (
    clear_effort_config,
    clear_global_effort_level,
    get_all_effort_configs,
    get_effort_config,
    get_effort_presets,
    get_global_effort_level,
    set_effort_config,
    set_global_effort_level,
)


class _SetEffortRequest(BaseModel):
    model_key: str
    params: dict[str, Any]


class _DeleteEffortRequest(BaseModel):
    model_key: str


class _SetAllEffortRequest(BaseModel):
    level: str
    """Unified effort level: ``low``, ``medium``, or ``high``."""


def _create_effort_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/models/effort/presets")
    async def get_presets() -> dict[str, Any]:
        return get_effort_presets()

    @router.get("/api/models/effort")
    async def list_effort_configs() -> dict[str, Any]:
        return {"overrides": get_all_effort_configs()}

    # ── Specific routes (must come before the wildcard {model_key:path}) ──

    @router.post("/api/models/effort/set-all")
    async def set_all_effort(req: _SetAllEffortRequest) -> dict[str, Any]:
        """Set a unified effort level across all providers.

        Accepts ``low``, ``medium``, or ``high`` and maps it to the
        appropriate concrete parameters for each supported provider.
        """
        try:
            set_global_effort_level(req.level)
            return {"success": True, "level": req.level}
        except ValueError as e:
            from llm_apipool.api.errors import INVALID_REQUEST_ERROR, error_response

            return error_response(400, str(e), INVALID_REQUEST_ERROR)

    @router.get("/api/models/effort/global-level")
    async def get_global_effort() -> dict[str, Any]:
        """Get the current global effort level mapping (per-provider params)."""
        level = get_global_effort_level()
        return {"level": level} if level else {"level": None}

    @router.delete("/api/models/effort/global-level")
    async def delete_global_effort() -> dict[str, bool]:
        """Clear the global effort override."""
        clear_global_effort_level()
        return {"success": True}

    # ── Wildcard per-model routes ────────────────────────────────────────

    @router.get("/api/models/effort/{model_key:path}")
    async def get_model_effort(model_key: str) -> dict[str, Any]:
        config = get_effort_config(model_key)
        return {"model_key": model_key, "params": config}

    @router.put("/api/models/effort")
    async def set_model_effort(req: _SetEffortRequest) -> dict[str, bool]:
        set_effort_config(req.model_key, req.params)
        return {"success": True}

    @router.delete("/api/models/effort")
    async def delete_model_effort(req: _DeleteEffortRequest) -> dict[str, bool]:
        clear_effort_config(req.model_key)
        return {"success": True}

    return router


__all__ = ["_create_effort_router"]
