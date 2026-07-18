"""Key checker: auto-detect provider by testing an API key against providers.

Probing flow
------------
1. ``check_key_against_provider`` is called for each candidate provider.
2. It builds a minimal completion request (1 user message: ``"test"``).
3. For ``openai_compatible`` providers, it sends a POST to the
   provider's ``base_url + /chat/completions`` with a short timeout (8s).
4. For Cohere, it calls ``v1/chat``; for Cloudflare, it uses the
   Accounts API to run a test prompt via the configured default model.
5. A **success** means the endpoint returned HTTP 200 — this confirms
   the key is valid for that provider.
6. Results feed into the bulk-import probing logic in
   ``llm_apipool/api/routes/bulk_import.py`` which uses
   ``asyncio.gather`` with a semaphore (concurrency: 6) to probe
   all candidates for each ambiguous key.

Notes
-----
* Only providers with ``openai_compatible: true`` and a configured
  ``default_model`` are probed (plus cohere, cloudflare).
* The probing is read-only — no keys are stored or modified.
* A key that passes for multiple providers is marked "ambiguous"
  and the user must pick one during commit-import.
"""

from __future__ import annotations


import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, cast

import httpx

from llm_apipool.providers.base import CompletionResult

logger = logging.getLogger(__name__)


_TEST_MESSAGES = [{"role": "user", "content": "test"}]
_CHECK_TIMEOUT = 8.0
_CHECK_CONCURRENCY = 6


def _provider_config_path() -> Path:
    return Path(__file__).parent / "config" / "providers.json"


def load_provider_configs() -> dict[str, Any]:
    with _provider_config_path().open(encoding="utf-8") as f:
        providers = json.load(f)["providers"]
    if not isinstance(providers, dict):
        raise ValueError("providers.json must contain a providers object")
    return cast(dict[str, Any], providers)


def _testable_providers(configs: dict[str, Any] | None = None) -> list[str]:
    data = configs or load_provider_configs()
    providers: list[str] = []
    for provider, cfg in data.items():
        # Skip providers that don't require auth (no_auth: true)
        if cfg.get("no_auth"):
            continue
        if cfg.get("openai_compatible") and cfg.get("default_model"):
            providers.append(provider)
            continue
        if provider in {"cohere", "cloudflare"}:
            providers.append(provider)
    return providers


def _build_key_data(
    provider: str, key: str, configs: dict[str, Any] | None = None
) -> dict[str, Any]:
    data = configs or load_provider_configs()
    cfg = data[provider]
    base_url = str(cfg["base_url"])

    if provider == "cloudflare":
        account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID")
        if not account_id:
            raise ValueError("CLOUDFLARE_ACCOUNT_ID is required for Cloudflare checks")
        base_url = base_url.format(account_id=account_id)

    return {
        "provider": provider,
        "api_key": key,
        "model": cfg["default_model"],
        "base_url": base_url,
        "openai_compatible": bool(cfg.get("openai_compatible")),
        "capabilities": cfg.get("capabilities", ["general_purpose"]),
        "no_auth": bool(cfg.get("no_auth", False)),
    }


async def _call_provider(
    provider: str, key: str, timeout: float, configs: dict[str, Any]
) -> CompletionResult:
    key_data = _build_key_data(provider, key, configs)

    if provider == "cohere":
        from llm_apipool.providers.cohere import complete

        async with asyncio.timeout(timeout):
            result = await complete(key_data, _TEST_MESSAGES, stream=False)
        if not isinstance(result, CompletionResult):
            return CompletionResult(
                text="",
                tokens_used=0,
                was_429=False,
                error="provider returned a stream",
            )
        return result

    if provider == "cloudflare":
        from llm_apipool.providers.cloudflare import complete

        async with asyncio.timeout(timeout):
            result = await complete(key_data, _TEST_MESSAGES, stream=False)
        if not isinstance(result, CompletionResult):
            return CompletionResult(
                text="",
                tokens_used=0,
                was_429=False,
                error="provider returned a stream",
            )
        return result

    from llm_apipool.providers.openai_compat import complete

    async with asyncio.timeout(timeout):
        result = await complete(key_data, _TEST_MESSAGES, stream=False)

    if not isinstance(result, CompletionResult):
        return CompletionResult(
            text="", tokens_used=0, was_429=False, error="provider returned a stream"
        )
    return result


async def check_key_against_provider(
    provider: str,
    key: str,
    timeout: float = _CHECK_TIMEOUT,
    configs: dict[str, Any] | None = None,
) -> tuple[str, bool, str]:
    data = configs or load_provider_configs()
    if provider not in data:
        return provider, False, "unknown provider"

    try:
        result = await _call_provider(provider, key, timeout, data)
    except asyncio.TimeoutError:
        return provider, False, "timeout"
    except httpx.HTTPError as e:
        return provider, False, f"http error: {type(e).__name__}: {e}"
    except ValueError as e:
        return provider, False, str(e)
    except (ImportError, TypeError, KeyError) as e:
        return provider, False, f"checker error: {type(e).__name__}: {e}"

    if result.error is None:
        text = result.text or "empty response"
        return provider, True, text[:80]

    return provider, False, result.error[:120]


async def auto_detect_provider(
    key: str,
    candidates: list[str] | None = None,
    timeout: float = _CHECK_TIMEOUT,
    max_concurrent: int = _CHECK_CONCURRENCY,
    configs: dict[str, Any] | None = None,
) -> list[tuple[str, bool, str]]:
    data = configs or load_provider_configs()
    providers = candidates or _testable_providers(data)
    semaphore = asyncio.Semaphore(max_concurrent)

    async def limited_check(provider: str) -> tuple[str, bool, str]:
        async with semaphore:
            return await check_key_against_provider(provider, key, timeout, data)

    results = await asyncio.gather(*(limited_check(provider) for provider in providers))
    results.sort(key=lambda item: (not item[1], item[0]))
    return list(results)


def detect_provider_sync(
    key: str,
    candidates: list[str] | None = None,
    timeout: float = _CHECK_TIMEOUT,
    max_concurrent: int = _CHECK_CONCURRENCY,
) -> list[tuple[str, bool, str]]:
    return asyncio.run(auto_detect_provider(key, candidates, timeout, max_concurrent))


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print(
            "Usage: python -m llm_apipool.key_checker <api_key> [provider1,provider2,...]"
        )
        raise SystemExit(1)

    api_key = sys.argv[1]
    selected = None
    if len(sys.argv) > 2:
        selected = [p.strip() for p in sys.argv[2].split(",")]

    print(
        f"Testing key: {api_key[:8]}****{api_key[-4:] if len(api_key) > 12 else api_key}"
    )
    print(f"Against {len(selected) if selected else 'all testable'} providers...")

    results = detect_provider_sync(api_key, selected)

    print("\nResults:")
    for provider, success, detail in results:
        status = "✓" if success else "✗"
        print(f"  {status} {provider}: {detail}")
