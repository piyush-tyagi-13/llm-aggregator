"""Periodic background model-sync from provider /v1/models endpoints.

Keeps the ``models`` table up-to-date as providers add/remove models
or change context lengths, speed ranks, etc. Uses the same upsert_model()
path as the manual ``llm-apipool sync-models`` CLI command, so context
windows and capabilities are refreshed on every cycle.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from llm_apipool.core.model_ingestion import sync_provider_models
from llm_apipool.key_store import KeyStore

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────
DEFAULT_INTERVAL_SECONDS = 3600  # 1 hour


class ModelSyncService:
    """Periodically sync models from all active providers.

    Usage::

        service = ModelSyncService(store, configs, interval_seconds=3600)
        asyncio.create_task(service.run())
        ...
        service.stop()
    """

    def __init__(
        self,
        store: KeyStore,
        configs: dict[str, Any],
        interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
    ) -> None:
        self._store = store
        self._configs = configs
        self._interval = interval_seconds
        self._stopped = False

        # Load tier map from model_quality.json
        self._tier_map: dict[str, int] = {}
        tier_path = (
            Path(__file__).resolve().parent.parent / "config" / "model_quality.json"
        )
        if tier_path.exists():
            try:
                quality = json.loads(tier_path.read_text())
                for tier_name, models in quality.items():
                    try:
                        tier_str = tier_name.lower().replace("tier", "").strip()
                        tier_num = int(tier_str) if tier_str.isdigit() else 4
                    except (ValueError, IndexError):
                        tier_num = 4
                    for m in models if isinstance(models, list) else []:
                        self._tier_map[m] = tier_num
            except (json.JSONDecodeError, Exception):
                logger.warning("Failed to load model_quality.json tier map")

    async def run(self) -> None:
        """Run model sync in a loop until stopped."""
        logger.info("Model sync service started (interval=%ds)", self._interval)
        while not self._stopped:
            try:
                await self._sync_all()
            except Exception:
                logger.exception("Model sync cycle failed")
            await asyncio.sleep(self._interval)
        logger.info("Model sync service stopped")

    def stop(self) -> None:
        """Signal the service to stop at the next cycle boundary."""
        self._stopped = True

    async def _sync_all(self) -> None:
        """Sync models for every provider that has at least one active key."""
        keys = self._store.get_all_keys()
        active_providers: set[str] = set()
        for k in keys:
            if k.get("is_active"):
                active_providers.add(k["provider"])

        if not active_providers:
            logger.debug("No active providers to sync models for")
            return

        logger.info(
            "Syncing models for %d active provider(s)...", len(active_providers)
        )

        results: list[dict[str, Any]] = []

        async def sync_one(provider: str) -> None:
            result = await sync_provider_models(
                self._store,
                provider,
                self._configs,
                key_id=None,
                tier_map=self._tier_map,
            )
            results.append(result)

        await asyncio.gather(*[sync_one(p) for p in active_providers])

        total = sum(r.get("models_upserted", 0) for r in results)
        errors = [r for r in results if r.get("error")]
        if errors:
            logger.warning(
                "Model sync complete: %d models upserted, %d error(s)",
                total,
                len(errors),
            )
        else:
            logger.info("Model sync complete: %d models upserted", total)


__all__ = ["ModelSyncService"]
