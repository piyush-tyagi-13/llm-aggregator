"""Aggregated model catalog endpoint — backed by the ``models`` DB table.

Falls back to static ``providers.json`` when the database hasn't been
populated yet (e.g. before the first model sync).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel

from llm_apipool.core.model_db import get_models

# ── Delete model scope ──────────────────────────────────────────────────────


class _DeleteModelRequest(BaseModel):
    model_id: str
    scope: str  # 'global', 'provider', 'key'
    platform: str | None = None
    key_id: int | None = None


class _RecoverDisabledRequest(BaseModel):
    disabled_id: int | None = None
    model_db_id: int | None = None
    platform: str | None = None


_APIPOOL_MODEL_ID = "LLM-Apipool"
_APIPOOL_MODEL_OWNER = "llm-apipool"
_GATEWAY_IDS = [f"g{i}" for i in range(1, 20)]


def _serialize(row: dict[str, Any]) -> dict[str, Any]:
    """
    Convert a DB model row to an OpenAI-compatible model dict.
    Includes FreeLLMAPI-standard fields: ``name``, ``context_length``,
    ``available``, ``unavailable_reason``.
    """
    cw = row.get("context_window")
    enabled = bool(row.get("enabled", True))
    return {
        "id": row["model_id"],
        "object": "model",
        "created": 0,
        "owned_by": row["platform"],
        "name": row.get("display_name") or row["model_id"],
        # OpenAI-standard context window
        "context_window": cw,
        # OpenRouter-style field alias (clients read either)
        "context_length": cw,
        # Availability — FreeLLMAPI-style
        "available": enabled,
        "unavailable_reason": None
        if enabled
        else ("disabled" if "enabled" in row else "no_key"),
        # llm-apipool custom enrichment
        "provider": row["platform"],
        "max_input_tokens": row.get("max_input_tokens"),
        "max_output_tokens": row.get("max_output_tokens"),
        "supports_tools": bool(row.get("supports_tools", False)),
        "supports_vision": bool(row.get("supports_vision", False)),
        "supports_streaming": bool(row.get("supports_streaming", True)),
        "supports_function_calling": bool(row.get("supports_function_calling", False)),
        "is_free": bool(row.get("is_free", True)),
        "tier": row.get("tier", 4),
        "intelligence_rank": row.get("intelligence_rank", 999),
        "speed_rank": row.get("speed_rank", 999),
        "size_label": row.get("size_label", "Medium"),
        "limits": {
            "rpm": row.get("rpm_limit"),
            "rpd": row.get("rpd_limit"),
            "tpm": row.get("tpm_limit"),
            "tpd": row.get("tpd_limit"),
        },
    }


def _list_from_config(
    configs: dict[str, Any], store: Any | None = None
) -> list[dict[str, Any]]:
    """Return pool models from config as a fallback when the DB is empty.

    Only returns the pool alias and gateway IDs — model catalogues are
    fetched live from provider /v1/models endpoints and stored in the DB.
    """
    data: list[dict[str, Any]] = [
        {
            "id": _APIPOOL_MODEL_ID,
            "object": "model",
            "owned_by": _APIPOOL_MODEL_OWNER,
            "created": 0,
        },
    ]
    for gid in _GATEWAY_IDS:
        data.append(
            {"id": gid, "object": "model", "owned_by": "llm-apipool", "created": 0}
        )
    return data


def _create_models_router(
    configs: dict[str, Any],
    store: Any | None = None,
    sync_fn: Callable[[], Awaitable[None]] | None = None,
) -> APIRouter:
    router = APIRouter()

    @router.get("/v1/models")
    async def list_models(
        provider: str | None = Query(None, description="Filter by provider"),
        tier: int | None = Query(None, description="Filter by quality tier (1-4)"),
        free_only: bool = Query(False, description="Only free-tier models"),
        min_context: int | None = Query(None, description="Minimum context window"),
        supports_tools: bool | None = Query(
            None, description="Filter for tool support"
        ),
        supports_vision: bool | None = Query(
            None, description="Filter for vision support"
        ),
        search: str | None = Query(None, description="Search model ID or display name"),
        sort_by: str = Query("tier", description="Sort field"),
        limit: int = Query(200, ge=1, le=1000),
        offset: int = Query(0, ge=0),
        enrich: bool = True,
        anthropic_version: Annotated[
            str | None, Header(include_in_schema=False)
        ] = None,
    ) -> Any:
        # Trigger background model sync so models stay fresh without manual intervention
        if sync_fn is not None:
            asyncio.create_task(sync_fn())

        # Content negotiation: when the caller speaks Anthropic (Claude Code
        # sends anthropic-version), return Anthropic-shaped model listing.
        if anthropic_version:
            models_data = _list_from_config(configs, store=store)
            if store is not None:
                try:
                    rows = get_models(store._conn())
                    if rows:
                        models_data = rows
                except Exception:
                    pass

            antr_data = [
                {
                    "type": "model",
                    "id": "auto",
                    "display_name": "Auto (router picks the best available model)",
                    "created_at": "2026-01-01T00:00:00Z",
                },
            ]
            for m in models_data:
                if isinstance(m, dict):
                    mid = m.get("model_id") or m.get("id", "")
                    name = m.get("display_name") or mid
                    antr_data.append(
                        {
                            "type": "model",
                            "id": mid,
                            "display_name": name,
                            "created_at": "2026-01-01T00:00:00Z",
                        }
                    )
            return {
                "data": antr_data,
                "has_more": False,
                "first_id": antr_data[0]["id"] if antr_data else None,
                "last_id": antr_data[-1]["id"] if antr_data else None,
            }

        data: list[dict[str, Any]] = []
        if store is not None:
            try:
                rows = get_models(
                    store._conn(),
                    provider=provider,
                    tier=tier,
                    free_only=free_only,
                    min_context=min_context,
                    supports_tools=supports_tools,
                    supports_vision=supports_vision,
                    search=search,
                    sort_by=sort_by,
                    limit=limit,
                    offset=offset,
                )
                if rows:
                    data = [_serialize(r) for r in rows]
            except Exception:
                pass
        if not data:
            # Fallback: return pool alias + gateway IDs (no hardcoded models).
            data = _list_from_config(configs, store=store)

        # Always include the pool alias and gateway models at the front
        preamble = [
            {
                "id": _APIPOOL_MODEL_ID,
                "object": "model",
                "owned_by": _APIPOOL_MODEL_OWNER,
                "created": 0,
            },
        ]
        for gid in _GATEWAY_IDS:
            preamble.append(
                {"id": gid, "object": "model", "owned_by": "llm-apipool", "created": 0}
            )

        seen = {e["id"] for e in preamble}
        deduped = preamble + [e for e in data if e["id"] not in seen]

        return {"object": "list", "data": deduped}

    # ── Dashboard models endpoint ───────────────────────────────────────────
    @router.get("/api/models")
    async def dashboard_models(
        provider: str | None = None,
        tier: int | None = None,
        search: str | None = None,
        sort_by: str = "tier",
        enabled_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Return all models from the DB enriched with computed scores.

        Also triggers a background model sync so the dashboard stays current
        without requiring manual intervention.
        """
        # Trigger background model sync so models stay fresh
        if sync_fn is not None:
            asyncio.create_task(sync_fn())

        from llm_apipool.core.model_db import get_models

        if store is None:
            return []

        rows = get_models(
            store._conn(),
            provider=provider,
            tier=tier,
            search=search,
            sort_by=sort_by,
            limit=5000,
            offset=0,
        )
        if not rows:
            return []

        # Gather per-model usage stats from requests table for reliability/speed
        usage_stats: dict[str, dict[str, float]] = {}
        try:
            cur = store._conn()
            usage_rows = cur.execute(
                "SELECT model_id, platform, COUNT(*) as total_reqs, "
                "SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successes, "
                "AVG(CASE WHEN status = 'success' AND latency_ms > 0 THEN latency_ms ELSE NULL END) as avg_latency_ms "
                "FROM requests "
                "WHERE model_id IS NOT NULL AND model_id != '' "
                "GROUP BY model_id, platform"
            ).fetchall()
            for r in usage_rows:
                key = f"{r['platform']}:{r['model_id']}"
                usage_stats[key] = {
                    "total_requests": r["total_reqs"],
                    "successes": r["successes"],
                    "failures": r["total_reqs"] - r["successes"],
                    "avg_latency_ms": r["avg_latency_ms"] or 0,
                }
        except Exception:
            pass

        # Gather per-model reliability from audit_log
        reliability_stats: dict[str, dict[str, float]] = {}
        try:
            cur = store._conn()
            audit_rows = cur.execute("""
                SELECT
                    model,
                    provider,
                    COUNT(*) as total,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successes
                FROM audit_log
                WHERE model IS NOT NULL AND model != ''
                GROUP BY model, provider
            """).fetchall()
            for r in audit_rows:
                key = f"{r['provider']}:{r['model']}"
                total = r["total"]
                s = r["successes"]
                reliability_stats[key] = {
                    "total": total,
                    "successes": s,
                    "failures": total - s,
                    "reliability": s / total if total > 0 else 0,
                }
        except Exception:
            pass

        result = []
        # Compute min/max intelligence_rank for normalization
        intel_ranks = [r.get("intelligence_rank", 999) or 999 for r in rows]
        min_intel = min(intel_ranks) if intel_ranks else 0
        max_intel = max(intel_ranks) if intel_ranks else 999
        intel_range = max_intel - min_intel or 1

        for r in rows:
            platform = r.get("platform", "")
            model_id = r.get("model_id", "")
            usage_key = f"{platform}:{model_id}"
            audit_key = f"{platform}:{model_id}"

            usage = usage_stats.get(usage_key, {})
            reliability = reliability_stats.get(audit_key, {})

            # Intelligence score: invert rank so lower rank = higher score
            intel_rank = r.get("intelligence_rank", 999) or 999
            intelligence = 1 - (intel_rank - min_intel) / intel_range

            # Speed score: invert avg_latency_ms (lower latency = higher score)
            avg_lat = usage.get("avg_latency_ms", 0)
            speed = max(0, 1 - (avg_lat / 30000)) if avg_lat else 0.5

            # Reliability score
            rel = reliability.get("reliability", 0.5)

            result.append(
                {
                    "id": r["id"],
                    "platform": platform,
                    "model_id": model_id,
                    "display_name": r.get("display_name") or model_id,
                    "tier": r.get("tier", 4),
                    "intelligence_rank": intel_rank,
                    "speed_rank": r.get("speed_rank", 999),
                    "size_label": r.get("size_label", "Medium"),
                    "enabled": bool(r.get("enabled", True)),
                    "context_window": r.get("context_window"),
                    "supports_vision": bool(r.get("supports_vision", False)),
                    "supports_tools": bool(r.get("supports_tools", False)),
                    "supports_streaming": bool(r.get("supports_streaming", True)),
                    "is_free": bool(r.get("is_free", True)),
                    "is_deprecated": bool(r.get("is_deprecated", False)),
                    "intelligence_score": round(intelligence, 3),
                    "speed_score": round(speed, 3),
                    "reliability_score": round(rel, 3),
                    "total_requests": int(usage.get("total_requests", 0)),
                }
            )

        return result

    # ── Manual model sync ───────────────────────────────────────────────────
    @router.post("/api/models/sync")
    async def sync_models() -> dict[str, Any]:
        """Trigger an immediate background model sync for all active providers."""
        if sync_fn is not None:
            asyncio.create_task(sync_fn())
            return {"success": True, "message": "Model sync triggered"}
        return {"success": False, "message": "Model sync service not available"}

    # ── Toggle model enabled/disabled ───────────────────────────────────────
    class _ToggleModelRequest(BaseModel):
        model_id: str
        platform: str
        enabled: bool

    @router.post("/api/models/toggle")
    async def toggle_model(req: _ToggleModelRequest) -> dict[str, Any]:
        if store is None:
            return {"success": False, "error": "store not available"}
        try:
            with store._conn() as conn:
                conn.execute(
                    "UPDATE models SET enabled = ? WHERE platform = ? AND model_id = ?",
                    (1 if req.enabled else 0, req.platform, req.model_id),
                )
            return {"success": True}
        except Exception as exc:
            from llm_apipool.api.errors import error_response, SERVER_ERROR

            return error_response(500, str(exc), SERVER_ERROR)

    # ── Delete model with scope ─────────────────────────────────────────
    @router.post("/api/models/delete")
    async def delete_model(req: _DeleteModelRequest) -> dict[str, Any]:
        if store is None:
            return {"success": False, "error": "store not available"}
        try:
            model_db_id = store.get_model_db_id(req.platform or "", req.model_id)
            if model_db_id is None and req.scope != "global":
                return {
                    "success": False,
                    "error": f"model {req.model_id} not found for provider {req.platform}",
                }
            if model_db_id is None and req.scope == "global":
                with store._conn() as conn:
                    conn.execute(
                        "UPDATE models SET enabled = 0 WHERE model_id = ?",
                        (req.model_id,),
                    )
                return {"success": True, "scope": "global", "model_id": req.model_id}

            store.disable_model(
                model_db_id=model_db_id,
                model_id=req.model_id,
                platform=req.platform if req.scope in ("provider",) else None,
                key_id=req.key_id if req.scope == "key" else None,
                reason="user",
            )
            return {"success": True, "scope": req.scope, "model_id": req.model_id}
        except Exception as exc:
            from llm_apipool.api.errors import error_response, SERVER_ERROR

            return error_response(500, str(exc), SERVER_ERROR)

    # ── Disabled models list ────────────────────────────────────────────
    @router.get("/api/models/disabled")
    async def list_disabled_models() -> list[dict[str, Any]]:
        if store is None:
            return []
        return store.get_disabled_models()

    # ── Recover disabled model ──────────────────────────────────────────
    @router.post("/api/models/recover")
    async def recover_model(req: _RecoverDisabledRequest) -> dict[str, Any]:
        if store is None:
            return {"success": False, "error": "store not available"}
        try:
            if req.disabled_id:
                ok = store.recover_disabled_model(req.disabled_id)
                return {"success": ok, "disabled_id": req.disabled_id}
            if req.model_db_id:
                store.recover_model(req.model_db_id, platform=req.platform)
                return {"success": True, "model_db_id": req.model_db_id}
            return {"success": False, "error": "provide disabled_id or model_db_id"}
        except Exception as exc:
            from llm_apipool.api.errors import error_response, SERVER_ERROR

            return error_response(500, str(exc), SERVER_ERROR)

    # ── Cooldown info ───────────────────────────────────────────────────
    @router.get("/api/models/cooldowns")
    async def list_cooldowns(model_db_id: int | None = None) -> list[dict[str, Any]]:
        if store is None:
            return []
        with store._conn() as conn:
            if model_db_id:
                rows = conn.execute(
                    """
                    SELECT mc.*, k.provider, k.api_key,
                           m.model_id, m.platform as model_platform
                    FROM model_cooldowns mc
                    JOIN api_keys k ON k.id = mc.key_id
                    JOIN models m ON m.id = mc.model_db_id
                    WHERE mc.model_db_id = ?
                    ORDER BY mc.cooldown_count DESC
                """,
                    (model_db_id,),
                ).fetchall()
            else:
                rows = conn.execute("""
                    SELECT mc.*, k.provider, k.api_key,
                           m.model_id, m.platform as model_platform
                    FROM model_cooldowns mc
                    JOIN api_keys k ON k.id = mc.key_id
                    JOIN models m ON m.id = mc.model_db_id
                    ORDER BY mc.updated_at DESC
                    LIMIT 200
                """).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d["api_key"] = d["api_key"][:8] + "..." if d.get("api_key") else None
                result.append(d)
            return result

    # ── Available models (free + keyed) — Free-first view ─────────────────
    @router.get("/api/models/available")
    async def available_models(
        free_only: bool = True,
        provider: str | None = None,
        tier: int | None = None,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return models the user can actually use — free models linked to
        their active keys.

        This is the **primary** model view: instead of showing every model
        that exists anywhere, it only shows models the user has a key for
        that are either:
        - Verified free (in the FreeLLMAPI catalog), or
        - Marked ``is_free = 1`` in the main DB

        Each result includes the key that unlocks it and a ``free_verified_by``
        field indicating how we know it's free.
        """
        if store is None:
            return []

        # ── 1. Build a set of (platform, model_id) from FreeLLMAPI catalog ──
        from llm_apipool.core.freellmapi_catalog import get_free_model_set

        free_catalog_set = get_free_model_set()

        # ── 2. Query models linked to active keys ────────────────────────
        conn = store._conn()
        clauses: list[str] = [
            "m.is_deprecated = 0",
            "ak.is_active = 1",
            "kma.is_active = 1",
        ]
        params: list[Any] = []

        if free_only:
            clauses.append("m.is_free = 1")
        if provider:
            clauses.append("m.platform = ?")
            params.append(provider)
        if tier is not None:
            clauses.append("m.tier = ?")
            params.append(tier)
        if search:
            clauses.append("(m.model_id LIKE ? OR m.display_name LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])

        sql = f"""SELECT DISTINCT m.*, ak.id AS key_id,
                  SUBSTR(ak.api_key, 1, 4) || '****' || SUBSTR(ak.api_key, -4) AS key_preview,
                  ak.provider
                  FROM models m
                  JOIN key_model_access kma ON kma.model_db_id = m.id
                  JOIN api_keys ak ON ak.id = kma.key_id
                  WHERE {" AND ".join(clauses)}
                  ORDER BY m.tier ASC, m.intelligence_rank DESC
                  LIMIT 500"""

        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]

        # ── 3. Enrich with free verification, health, usage stats ────────
        # Gather cooldown info
        cooldown_rows = conn.execute("""
            SELECT mc.key_id, mc.model_db_id, mc.cooldown_until
            FROM model_cooldowns mc
            WHERE mc.cooldown_until > datetime('now')
        """).fetchall()
        cooldown_map: dict[int, str] = {}
        for cr in cooldown_rows:
            cooldown_map[cr["key_id"]] = cr["cooldown_until"]

        result: list[dict[str, Any]] = []
        for r in rows:
            platform = r.get("platform", "")
            model_id = r.get("model_id", "")
            catalog_key = (platform, model_id)
            verified = catalog_key in free_catalog_set

            result.append(
                {
                    "id": r["id"],
                    "platform": platform,
                    "model_id": model_id,
                    "display_name": r.get("display_name") or model_id,
                    "tier": r.get("tier", 4),
                    "intelligence_rank": r.get("intelligence_rank", 999),
                    "context_window": r.get("context_window"),
                    "supports_vision": bool(r.get("supports_vision", False)),
                    "supports_tools": bool(r.get("supports_tools", False)),
                    "is_free": True,
                    "free_verified_by": "freellmapi" if verified else "detection",
                    "key_id": r["key_id"],
                    "key_preview": r["key_preview"],
                    "health": "cooldown" if r["key_id"] in cooldown_map else "healthy",
                    "cooldown_until": cooldown_map.get(r["key_id"]),
                    "size_label": r.get("size_label", "Medium"),
                }
            )

        return result

    # ── Unlockable models (FreeLLMAPI catalog, no matching key) ───────────
    @router.get("/api/models/unlockable")
    async def unlockable_models() -> list[dict[str, Any]]:
        """Return free models from the FreeLLMAPI catalog that the user
        could use if they added a key for the provider.

        Grouped by provider so the dashboard can show "Add an Anthropic
        key to unlock 8 more free models".
        """
        if store is None:
            return []

        from llm_apipool.core.freellmapi_catalog import get_free_models

        free_models = get_free_models(enabled_only=True)

        # Providers the user already has keys for
        conn = store._conn()
        active_providers = {
            r["provider"]
            for r in conn.execute(
                "SELECT DISTINCT provider FROM api_keys WHERE is_active = 1"
            ).fetchall()
        }

        # Group free models by provider, skipping those the user has keys for
        provider_map: dict[str, list[dict[str, Any]]] = {}
        for fm in free_models:
            plat = fm["platform"]
            if plat in active_providers:
                continue
            if plat not in provider_map:
                provider_map[plat] = []
            if len(provider_map[plat]) < 5:  # top 5 samples per provider
                provider_map[plat].append(
                    {
                        "model_id": fm["model_id"],
                        "display_name": fm.get("display_name") or fm["model_id"],
                        "tier": fm.get("tier", 4),
                        "intelligence_rank": fm.get("intelligence_rank", 999),
                        "context_window": fm.get("context_window"),
                    }
                )

        result = []
        for plat, samples in provider_map.items():
            result.append(
                {
                    "provider": plat,
                    "model_count": len(
                        [fm for fm in free_models if fm["platform"] == plat]
                    ),
                    "samples": samples,
                }
            )

        result.sort(key=lambda x: -x["model_count"])
        return result

    return router


__all__ = ["_create_models_router"]
