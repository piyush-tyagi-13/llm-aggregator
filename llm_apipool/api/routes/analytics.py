from __future__ import annotations

from typing import Any

from fastapi import APIRouter


def _create_analytics_router(store: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/api/analytics/overview")
    async def analytics_overview(days: int = 7) -> dict[str, Any]:
        keys = store.get_all_keys()
        return {
            "total_keys": len(keys),
            "active_keys": sum(1 for k in keys if k.get("is_active")),
            "days_analyzed": days,
        }

    @router.get("/api/analytics/providers")
    async def analytics_providers(days: int = 7) -> dict[str, Any]:
        from llm_apipool.core.router import get_all_penalties

        return {"penalties": get_all_penalties()}

    return router


__all__ = ["_create_analytics_router"]
