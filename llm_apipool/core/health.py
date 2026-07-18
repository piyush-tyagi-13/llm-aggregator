"""Health check module — automatic probing and manual health checks."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from ..key_store import KeyStore

from ..config.loader import load_settings

logger = logging.getLogger(__name__)

_health_settings = load_settings().health
CHECK_INTERVAL_MS = _health_settings.check_interval_ms
CONSECUTIVE_FAILURES_TO_DISABLE = _health_settings.consecutive_failures_to_disable

_failure_counts: dict[int, int] = {}
_checker_task: asyncio.Task[None] | None = None
_checker_running = False


async def probe_key(
    store: KeyStore,
    provider: str,
    api_key: str,
    model_id: str | None = None,
) -> tuple[bool, str]:
    from ..providers.registry import get_provider

    prov = get_provider(provider)
    if prov is None:
        return False, f"No provider registered for '{provider}'"

    try:
        is_valid = await prov.validate_key(api_key)
        if is_valid:
            return True, "Key validated successfully"
        return False, "Key rejected by provider (invalid or expired)"
    except Exception as exc:
        return False, f"Probe transport error: {exc}"


async def check_key_health(store: KeyStore, key_id: int) -> str:
    key = None
    for k in store.get_all_keys():
        if k["id"] == key_id:
            key = k
            break

    if key is None:
        return "error"

    api_key = key.get("api_key", "")
    provider = key.get("provider", "")
    status, detail = await probe_key(store, provider, api_key, key.get("model"))

    now_iso = time.strftime("%Y-%m-%d %H:%M:%S")

    if status:
        _failure_counts.pop(key_id, None)
        store.update_key_status(key_id, "healthy", last_checked_at=now_iso)
        return "healthy"

    if "transport error" in detail.lower() or "timeout" in detail.lower():
        store.update_key_status(key_id, "error", last_checked_at=now_iso)
        return "error"

    count = _failure_counts.get(key_id, 0) + 1
    _failure_counts[key_id] = count

    if count >= CONSECUTIVE_FAILURES_TO_DISABLE:
        store.update_key_status(
            key_id, "invalid", enabled=False, last_checked_at=now_iso
        )
        _failure_counts.pop(key_id, None)
    else:
        store.update_key_status(key_id, "invalid", last_checked_at=now_iso)

    return "invalid"


async def check_all_keys(store: KeyStore) -> None:
    keys = store.get_all_keys()
    enabled_keys = [k for k in keys if k.get("is_active")]

    logger.info("Checking %d keys...", len(enabled_keys))
    for key in enabled_keys:
        await check_key_health(store, key["id"])
    logger.info("Check complete.")


async def _checker_loop(store: KeyStore) -> None:
    global _checker_running
    _checker_running = True
    try:
        while _checker_running:
            await check_all_keys(store)
            await asyncio.sleep(CHECK_INTERVAL_MS / 1000)
    except asyncio.CancelledError:
        pass
    finally:
        _checker_running = False


def start_health_checker(store: KeyStore) -> None:
    global _checker_task
    if _checker_task is not None and not _checker_task.done():
        return
    _checker_task = asyncio.ensure_future(_checker_loop(store))


def stop_health_checker() -> None:
    global _checker_running, _checker_task
    _checker_running = False
    if _checker_task is not None:
        _checker_task.cancel()
        _checker_task = None


def get_health_status(store: KeyStore) -> dict[str, Any]:
    keys = store.get_all_keys()
    return {
        "keys": [
            {
                "id": k["id"],
                "provider": k["provider"],
                "status": k.get("status", "unknown"),
                "last_checked_at": k.get("last_checked_at"),
                "is_active": k["is_active"],
                "model": k.get("model"),
            }
            for k in keys
        ],
        "checker_running": _checker_running,
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def clear_failure_counts() -> None:
    _failure_counts.clear()


# update_key_status is now defined on KeyStore directly
