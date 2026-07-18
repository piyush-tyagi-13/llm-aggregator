from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from llm_apipool.core.utils import mask_key


class _KeyUpdate(BaseModel):
    model: str | None = None
    api_key: str | None = None
    provider: str | None = None
    capabilities: list[str] | None = None
    context_size: int | None = None
    accuracy_score: int | None = None
    speed_score: int | None = None
    reliability_score: int | None = None
    group_name: str | None = None
    is_sticky_enabled: bool | None = None
    sticky_ttl_hours: int | None = None
    priority: int | None = None


class _KeyCreate(BaseModel):
    provider: str
    api_key: str
    capabilities: list[str] | None = None
    model: str | None = None
    base_url_override: str | None = None
    context_size: int | None = None
    accuracy_score: int = 50
    speed_score: int = 50
    reliability_score: int = 50
    group_name: str = "default"


def _create_keys_router(
    store: Any, configs: dict[str, Any], rotator: Any | None = None
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/keys")
    async def list_keys(active_only: bool = False) -> list[dict[str, Any]]:
        keys = store.get_all_keys()
        if active_only:
            keys = [k for k in keys if k["is_active"]]
        for key in keys:
            if "api_key" in key:
                key["api_key"] = mask_key(key["api_key"])
        return keys

    @router.post("/api/keys")
    async def create_key(data: _KeyCreate) -> dict[str, Any]:
        result = store.register_key(
            provider=data.provider,
            api_key=data.api_key,
            capabilities=data.capabilities,
            model=data.model,
            base_url_override=data.base_url_override,
            context_size=data.context_size,
            accuracy_score=data.accuracy_score,
            speed_score=data.speed_score,
            reliability_score=data.reliability_score,
            group_name=data.group_name,
        )
        if isinstance(result, dict) and "api_key" in result:
            result["api_key"] = mask_key(result["api_key"])
        return result

    @router.patch("/api/keys/{key_id}")
    async def update_key(key_id: int, data: _KeyUpdate) -> dict[str, Any]:
        if any(x is not None for x in [data.model, data.api_key, data.provider]):
            store.update_key(
                key_id, model=data.model, api_key=data.api_key, provider=data.provider
            )
        if any(
            s is not None
            for s in [data.accuracy_score, data.speed_score, data.reliability_score]
        ):
            store.update_key_scores(
                key_id,
                accuracy_score=data.accuracy_score,
                speed_score=data.speed_score,
                reliability_score=data.reliability_score,
            )
        if data.group_name is not None:
            store.update_key_group(key_id, data.group_name)
        if data.is_sticky_enabled is not None:
            store.update_key_sticky(
                key_id, data.is_sticky_enabled, data.sticky_ttl_hours or 1
            )
        if data.priority is not None:
            store.update_priority(key_id, data.priority)
        return {"success": True, "message": f"Key {key_id} updated"}

    @router.patch("/api/keys/{key_id}/priority")
    async def update_priority_endpoint(key_id: int, priority: int) -> dict[str, Any]:
        store.update_priority(key_id, priority)
        return {"success": True, "message": f"Key {key_id} priority set to {priority}"}

    @router.delete("/api/keys/{key_id}")
    async def delete_key_endpoint(key_id: int) -> dict[str, Any]:
        deleted = store.delete_key(key_id)
        if deleted:
            return {"success": True, "message": f"Key {key_id} deleted"}
        return {"success": False, "message": f"Key {key_id} not found"}

    @router.post("/api/keys/{key_id}/activate")
    async def activate_key_endpoint(key_id: int) -> dict[str, Any]:
        store.activate_key(key_id)
        return {"success": True, "message": f"Key {key_id} activated"}

    @router.post("/api/keys/{key_id}/deactivate")
    async def deactivate_key_endpoint(key_id: int) -> dict[str, Any]:
        store.deactivate_key(key_id)
        return {"success": True, "message": f"Key {key_id} deactivated"}

    @router.post("/api/keys/{key_id}/clear-cooldown")
    async def clear_cooldown_endpoint(key_id: int) -> dict[str, Any]:
        store.clear_cooldown(key_id)
        if rotator:
            rotator._config_version += 1
        return {"success": True, "message": f"Cooldown cleared for key {key_id}"}

    @router.post("/api/keys/clear-all-cooldowns")
    async def clear_all_cooldowns_endpoint() -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        with store._conn() as conn:
            conn.execute(
                "UPDATE api_keys SET cooldown_until = NULL WHERE cooldown_until > ?",
                (now,),
            )
            conn.execute(
                "UPDATE model_cooldowns SET cooldown_until = NULL, cooldown_count = 0 WHERE cooldown_until > ?",
                (now,),
            )
        if rotator:
            rotator.clear_caches()
        return {"success": True, "message": "All expired cooldowns cleared"}

    @router.post("/api/health-check")
    async def manual_health_check_endpoint() -> dict[str, Any]:
        import asyncio
        from llm_apipool.key_checker import check_key_against_provider

        if rotator:
            rotator.clear_caches()

        keys = store.get_all_keys()
        active = [k for k in keys if k.get("is_active")]
        healthy_count = 0
        error_count = 0

        async def check_key(k: dict[str, Any]) -> None:
            nonlocal healthy_count, error_count
            provider = k["provider"]
            api_key = k.get("api_key", "")
            try:
                _, success, _ = await check_key_against_provider(provider, api_key)
                if success:
                    healthy_count += 1
                    if k.get("cooldown_until"):
                        store.clear_cooldown(k["id"])
                else:
                    error_count += 1
            except Exception:
                error_count += 1
                if k.get("cooldown_until"):
                    store.clear_cooldown(k["id"])

        await asyncio.gather(*[check_key(k) for k in active])
        return {
            "success": True,
            "message": f"Health check complete: {healthy_count} healthy, {error_count} failed",
            "healthy": healthy_count,
            "failed": error_count,
        }

    @router.get("/api/providers")
    async def list_providers() -> dict[str, Any]:
        return {"providers": sorted(configs.keys())}

    @router.post("/api/test-key")
    async def test_key(provider: str = "", api_key: str = "") -> dict[str, Any]:
        import asyncio
        from llm_apipool.key_checker import check_key_against_provider

        if not provider or not api_key:
            return {"healthy": False, "detail": "Provider and API key required"}
        async with asyncio.timeout(10):
            prov, success, detail = await check_key_against_provider(provider, api_key)
        return {"healthy": success, "detail": detail}

    return router


__all__ = ["_create_keys_router"]
