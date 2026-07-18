"""Periodic background health checks for registered provider keys.

Spins up a background task that probes every active key at a configurable
interval by making a lightweight API call (usually a model list or a
minimal chat completion). Keys that respond successfully are marked
``healthy``; keys that fail are marked ``error`` or ``invalid`` and the
rotator skips them automatically.

This is the key reliability differentiator — dead keys are detected within
minutes instead of wasting requests on them.
"""

from __future__ import annotations


import asyncio
import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from llm_apipool.key_store import KeyStore

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────
DEFAULT_INTERVAL_SECONDS = 300  # 5 minutes
HEALTH_TIMEOUT_SECONDS = 15


# ── Probe implementation ─────────────────────────────────────────────────────


def _parse_extra(raw: str) -> dict[str, Any]:
    """Safely parse a JSON ``extra_params`` column value."""
    if not raw:
        return {}
    try:
        return json.loads(raw) if isinstance(raw, str) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


_API_KEY_PATTERN = re.compile(
    r"(?:sk-[A-Za-z0-9]{10,}|hf_[A-Za-z0-9]{10,}|acv-[A-Za-z0-9]{10,}|"
    r"gsk_[A-Za-z0-9]{10,}|[A-Za-z0-9]{30,})"
)


def _mask_key(text: str) -> str:
    """Mask any API-key-like strings in the error text to avoid leaking secrets."""
    return _API_KEY_PATTERN.sub(lambda m: m.group()[:6] + "*****", text)


async def _probe_key(
    provider: str,
    api_key: str,
    base_url: str | None,
    extra_params: dict[str, Any] | None = None,
) -> str | None:
    """Probe a single key by listing models via the provider's API.

    Returns ``None`` if healthy, or an error message string if unhealthy.
    """
    import aiohttp

    base = (base_url or "").rstrip("/") or _default_base(provider)
    # Resolve URL templates like {account_id} from extra_params
    if "{account_id}" in base and extra_params:
        base = base.format(account_id=extra_params.get("account_id", ""))
    url = f"{base}/models"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=HEALTH_TIMEOUT_SECONDS),
            ) as resp:
                if resp.status == 200:
                    return None
                if resp.status in (401, 403):
                    text = _mask_key(await resp.text())
                    return f"auth_error ({resp.status}): {text[:200]}"
                return f"http_{resp.status}"
    except asyncio.TimeoutError:
        return "timeout (15s)"
    except Exception as exc:
        return f"connection_error: {_mask_key(str(exc))}"[:200]


def _default_base(provider: str) -> str:
    """Return a reasonable default base URL for well-known providers."""
    bases = {
        "groq": "https://api.groq.com/openai/v1",
        "cerebras": "https://api.cerebras.ai/v1",
        "mistral": "https://api.mistral.ai/v1",
        "openrouter": "https://openrouter.ai/api/v1",
        "google": "https://generativelanguage.googleapis.com/v1beta",
        "sambanova": "https://api.sambanova.ai/v1",
        "github_models": "https://models.inference.ai.azure.com",
        "huggingface": "https://api-inference.huggingface.co/v1",
        "replicate": "https://api.replicate.com/v1",
        "cohere": "https://api.cohere.ai/v1",
        "anthropic": "https://api.anthropic.com/v1",
        "openai": "https://api.openai.com/v1",
        "deepseek": "https://api.deepseek.com/v1",
        "cloudflare": "https://api.cloudflare.com/client/v4/accounts/_/ai/run",
    }
    return bases.get(provider, "https://api.openai.com/v1")


# ── Background task ──────────────────────────────────────────────────────────


class HealthCheckService:
    """Periodically probes all active keys and updates their status in the DB.

    Usage::

        hc = HealthCheckService(store)
        task = asyncio.create_task(hc.run())
        # ...
        task.cancel()
    """

    def __init__(
        self,
        store: KeyStore,
        interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
    ) -> None:
        self._store = store
        self._interval = interval_seconds
        self._stopped = False

    async def run(self) -> None:
        """Run health checks in a loop until stopped."""
        logger.info("Health check service started (interval=%ds)", self._interval)
        while not self._stopped:
            try:
                await self._check_all()
            except Exception:
                logger.exception("Health check cycle failed")
            await asyncio.sleep(self._interval)
        logger.info("Health check service stopped")

    def stop(self) -> None:
        """Signal the service to stop at the next cycle boundary."""
        self._stopped = True

    async def _check_all(self) -> None:
        """Probe every active key and update its status in the store."""
        keys = self._store.get_all_keys()
        active = [k for k in keys if k.get("is_active")]

        if not active:
            logger.debug("No active keys to health-check")
            return

        logger.info("Health-checking %d active key(s)...", len(active))

        results: list[tuple[int, str, str | None, str | None, str, str | None]] = []

        async def check_key(k: dict[str, Any]) -> None:
            provider = k["provider"]
            api_key = k.get("api_key", "")
            base_url = k.get("base_url_override")
            extra_params = _parse_extra(k.get("extra_params", "{}"))
            error = await _probe_key(
                provider, api_key, base_url, extra_params=extra_params
            )
            has_key_cooldown = k.get("cooldown_until")
            results.append(
                (
                    k["id"],
                    "healthy" if error is None else "error",
                    error,
                    has_key_cooldown,
                    provider,
                    k.get("model"),
                )
            )

        await asyncio.gather(*[check_key(k) for k in active])

        now = datetime.now(UTC).isoformat()
        healthy_count = 0
        for key_id, status, error, has_key_cooldown, provider, model in results:
            self._store.update_key_status(
                key_id,
                status=status,
                last_checked_at=now,
            )
            if status == "healthy":
                healthy_count += 1
                if has_key_cooldown:
                    self._store.clear_cooldown(key_id)
                    logger.info(
                        "Key #%d health check passed - cooldown cleared", key_id
                    )
            elif error:
                logger.warning("Key #%d health check FAILED: %s", key_id, error)

        logger.info("Health check complete: %d/%d healthy", healthy_count, len(active))


__all__ = ["HealthCheckService", "_probe_key"]
