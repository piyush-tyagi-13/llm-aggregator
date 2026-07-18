"""API routes for the FreeLLMAPI model catalog (separate DB).

All endpoints are prefixed with ``/api/freemodels`` and protected by the
dashboard auth middleware.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from llm_apipool.core.freellmapi_catalog import (
    add_custom_free_model,
    get_free_models,
    get_free_models_summary,
    get_providers,
    remove_custom_free_model,
    sync_catalog,
    sync_free_models_to_main_db,
    toggle_free_model,
    toggle_provider,
)

logger = logging.getLogger(__name__)


def _create_freemodels_router(store: Any | None = None) -> APIRouter:
    router = APIRouter(prefix="/api/freemodels")

    # ── GET /api/freemodels — list all free models ───────────────────────────
    @router.get("")
    async def list_freemodels(
        platform: str | None = None,
        search: str | None = None,
        enabled_only: bool = False,
        custom_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Return all models from the FreeLLMAPI catalog DB."""
        return get_free_models(
            platform=platform,
            search=search,
            enabled_only=enabled_only,
            custom_only=custom_only,
        )

    # ── GET /api/freemodels/providers — list providers ───────────────────────
    @router.get("/providers")
    async def list_providers() -> list[dict[str, Any]]:
        """Return distinct providers with model counts."""
        return get_providers()

    # ── GET /api/freemodels/summary — stats ──────────────────────────────────
    @router.get("/summary")
    async def summary() -> dict[str, Any]:
        """Return summary stats about the free models catalog."""
        return get_free_models_summary()

    # ── POST /api/freemodels/sync — trigger sync ────────────────────────────
    class _SyncResponse(BaseModel):
        ok: bool
        action: str
        version: str = ""
        total: int = 0
        error: str = ""

    @router.post("/sync")
    async def trigger_sync() -> _SyncResponse:
        """Fetch the latest catalog from FreeLLMAPI and upsert.

        Also syncs verified-free models into the main ``models`` table
        so they become discoverable by the proxy and dashboard alongside
        provider-synced models.
        """
        result = sync_catalog()
        if result.get("ok") and store is not None:
            try:
                main_count = sync_free_models_to_main_db(store)
            except Exception:
                logger.exception("Failed to sync free models to main DB")
                main_count = 0
        else:
            main_count = 0
        return _SyncResponse(
            ok=result.get("ok", False),
            action=result.get("action", "error"),
            version=result.get("version", ""),
            total=result.get("total", 0) + main_count,
            error=result.get("error", ""),
        )

    # ── POST /api/freemodels/toggle — toggle a model ────────────────────────
    class _ToggleRequest(BaseModel):
        platform: str
        model_id: str
        enabled: bool

    @router.post("/toggle")
    async def toggle(req: _ToggleRequest) -> dict[str, Any]:
        """Enable or disable a single free model."""
        ok = toggle_free_model(req.platform, req.model_id, req.enabled)
        return {"success": ok}

    # ── PUT /api/freemodels/provider — toggle an entire provider ────────────
    class _ToggleProviderRequest(BaseModel):
        platform: str
        enabled: bool

    @router.put("/provider")
    async def toggle_provider_ep(req: _ToggleProviderRequest) -> dict[str, Any]:
        """Enable or disable all models for a provider."""
        count = toggle_provider(req.platform, req.enabled)
        return {"success": True, "updated": count}

    # ── POST /api/freemodels/custom — add a custom free model ───────────────
    class _AddCustomRequest(BaseModel):
        platform: str
        model_id: str
        display_name: str | None = None
        context_window: int | None = None
        supports_vision: bool = False
        supports_tools: bool = False
        tier: int = 4

    @router.post("/custom")
    async def add_custom(req: _AddCustomRequest) -> dict[str, Any]:
        """Add a user-defined model to the free list."""
        ok = add_custom_free_model(
            req.platform,
            req.model_id,
            display_name=req.display_name,
            context_window=req.context_window,
            supports_vision=req.supports_vision,
            supports_tools=req.supports_tools,
            tier=req.tier,
        )
        return {"success": ok}

    # ── DELETE /api/freemodels/custom — remove a custom model ───────────────
    class _RemoveCustomRequest(BaseModel):
        platform: str
        model_id: str

    @router.delete("/custom")
    async def remove_custom(req: _RemoveCustomRequest) -> dict[str, Any]:
        """Remove a user-defined free model."""
        ok = remove_custom_free_model(req.platform, req.model_id)
        return {"success": ok}

    return router


__all__ = ["_create_freemodels_router"]
