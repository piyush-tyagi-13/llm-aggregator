"""Bulk auto-import API keys with format-based provider detection.

Endpoints
---------
* ``POST /api/keys/auto-import`` — analyse raw key text, test ambiguous keys,
  return structured results.  Does NOT persist anything.
* ``POST /api/keys/commit-import`` — accept analysed results (possibly with
  user overrides) and persist the keys.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from llm_apipool.core.key_detection import analyse_bulk
from llm_apipool.key_checker import check_key_against_provider

logger = logging.getLogger(__name__)


class _AutoImportRequest(BaseModel):
    text: str


class _CommitImportRequest(BaseModel):
    keys: list[dict[str, Any]]
    """Each entry::

        {"key": "...", "provider": "...", "base_url_override": str | None,
         "model": str | None, "capabilities": list[str] | None}
    """


def _create_bulk_import_router(
    store: Any | None = None,
    configs: dict[str, Any] | None = None,
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/keys/auto-import")
    async def auto_import(req: _AutoImportRequest) -> dict[str, Any]:
        """Analyse raw key text and return structured detection results.

        Steps
        -----
        1. Parse each line as a key.
        2. Classify by format (auto / probe / unknown).
        3. For **probe** keys (``sk-*`` with multiple possible providers):
           test each candidate with a lightweight API call.
        4. Return results grouped by status.
        """
        if configs is None:
            return {"error": "Provider configs not available", "keys": []}

        classified = analyse_bulk(req.text, configs)

        # Separate by status
        auto_keys = [k for k in classified if k["status"] == "auto"]
        probe_keys = [k for k in classified if k["status"] == "probe"]
        unknown_keys = [k for k in classified if k["status"] == "unknown"]
        skipped = [k for k in classified if k["status"] == "skip"]

        # Probe each ambiguous key against all candidates
        probed: list[dict[str, Any]] = []
        for entry in probe_keys:
            key = entry["key"]
            candidates = entry["candidates"]
            results = await _probe_key(key, candidates, configs)
            passing = [r for r in results if r["success"]]
            probed.append(
                {
                    "key": key,
                    "candidates": candidates,
                    "probed": results,
                    "status": "confirmed"
                    if len(passing) == 1
                    else ("ambiguous" if len(passing) > 1 else "unknown"),
                    "detected_provider": passing[0]["provider"]
                    if len(passing) == 1
                    else None,
                }
            )

        return {
            "keys": {
                "auto": auto_keys,
                "probed": probed,
                "unknown": unknown_keys,
                "skipped": skipped,
            },
            "summary": {
                "total": len(auto_keys) + len(probe_keys) + len(unknown_keys),
                "auto": len(auto_keys),
                "confirmed": sum(1 for p in probed if p["status"] == "confirmed"),
                "ambiguous": sum(1 for p in probed if p["status"] == "ambiguous"),
                "unknown": len(unknown_keys)
                + sum(1 for p in probed if p["status"] == "unknown"),
            },
        }

    @router.post("/api/keys/commit-import")
    async def commit_import(req: _CommitImportRequest) -> dict[str, Any]:
        """Persist the analysed keys (with any user overrides).

        Each entry **must** have at minimum ``key`` and ``provider``.
        Optional fields: ``base_url_override``, ``model``, ``capabilities``.
        """
        if store is None:
            return {"success": False, "error": "Store not available", "imported": 0}

        imported = 0
        errors: list[dict[str, str]] = []

        for entry in req.keys:
            api_key = entry.get("key", "").strip()
            provider = entry.get("provider", "").strip()
            if not api_key or not provider:
                errors.append(
                    {"key": api_key[:12] + "…", "error": "Missing key or provider"}
                )
                continue

            try:
                store.register_key(
                    provider=provider,
                    api_key=api_key,
                    capabilities=entry.get("capabilities"),
                    model=entry.get("model"),
                    base_url_override=entry.get("base_url_override"),
                )
                imported += 1
            except Exception as exc:
                errors.append({"key": api_key[:12] + "…", "error": str(exc)[:120]})

        return {
            "success": len(errors) == 0,
            "imported": imported,
            "errors": errors,
        }

    return router


# ── Probing ───────────────────────────────────────────────────────────

_PROBE_TIMEOUT = 8.0
_PROBE_CONCURRENCY = 6


async def _probe_key(
    key: str,
    candidates: list[str],
    configs: dict[str, Any],
) -> list[dict[str, Any]]:
    """Test *key* against each *candidate* provider.

    Returns list of ``{"provider": str, "success": bool, "detail": str}``.
    """
    semaphore = asyncio.Semaphore(_PROBE_CONCURRENCY)

    async def _test(provider: str) -> dict[str, Any]:
        async with semaphore:
            try:
                prov, ok, detail = await check_key_against_provider(
                    provider,
                    key,
                    timeout=_PROBE_TIMEOUT,
                    configs=configs,
                )
                return {"provider": prov, "success": ok, "detail": detail[:100]}
            except Exception as exc:
                return {
                    "provider": provider,
                    "success": False,
                    "detail": f"checker error: {exc}",
                }

    tasks = [_test(p) for p in candidates]
    results = await asyncio.gather(*tasks)
    results.sort(key=lambda r: (not r["success"], r["provider"]))
    return results


__all__ = ["_create_bulk_import_router"]
