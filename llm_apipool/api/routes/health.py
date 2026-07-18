from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse


def _create_health_router(store: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    async def health() -> dict[str, Any]:
        keys = store.get_all_keys()
        active = sum(1 for k in keys if k["is_active"])
        return {
            "status": "ok",
            "keys_total": len(keys),
            "keys_active": active,
        }

    @router.get("/audit")
    async def audit_summary(days: int = 7) -> list[dict[str, Any]]:
        return store.get_audit_summary(days=days)

    @router.post("/health/check")
    async def health_check_trigger() -> dict[str, Any]:
        from llm_apipool.core.health import check_all_keys

        await check_all_keys(store)
        return {"success": True, "message": "Health check triggered"}

    @router.get("/stats")
    async def stats() -> dict[str, Any]:
        from llm_apipool.core.metrics import get_metrics

        return get_metrics().snapshot()

    @router.get("/metrics")
    async def metrics_prometheus() -> PlainTextResponse:
        from llm_apipool.core.metrics import get_metrics

        return PlainTextResponse(
            content=get_metrics().format_prometheus(),
            media_type="text/plain; version=0.0.4",
        )

    @router.get("/circuit-breakers")
    async def circuit_breakers() -> list[dict[str, Any]]:
        from llm_apipool.core.circuit_breaker import get_circuit_breaker

        return get_circuit_breaker().snapshot()

    return router


__all__ = ["_create_health_router"]
