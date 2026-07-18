#!/usr/bin/env python3
"""Validate all API keys in the pool by testing them directly against their providers.

This script tests every key in the database to identify:
1. Keys that fail due to invalid/expired credentials (real API errors)
2. Keys that fail due to proxy/configuration issues
3. Provider connectivity issues

Usage:
    uv run python scripts/validate_keys.py [--verbose] [--proxy-url URL]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any

# Ensure the package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llm_apipool.key_store import KeyStore
from llm_apipool.api.app import _load_provider_configs


def _mask_key(api_key: str) -> str:
    """Mask API key for safe display."""
    if len(api_key) <= 8:
        return "****" + api_key[-4:] if len(api_key) > 4 else "****"
    return api_key[:4] + "****" + api_key[-_MASK_SHOW:]


_MASK_SHOW = 4
_CHECK_TIMEOUT = 10.0


async def _test_key_direct(
    provider: str, api_key: str, base_url: str, model: str, no_auth: bool
) -> tuple[bool, str]:
    """Test a key directly against the provider API.

    Returns (success, detail) tuple.
    """
    import httpx

    # Build headers - some providers are keyless
    headers = {"Content-Type": "application/json"}
    if not no_auth:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(_CHECK_TIMEOUT, connect=5.0)
        ) as client:
            start = time.perf_counter()
            resp = await client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "test"}],
                    "max_tokens": 5,
                },
            )
            elapsed = (time.perf_counter() - start) * 1000

            if resp.status_code == 200:
                data = resp.json()
                text = (
                    data.get("choices", [{}])[0].get("message", {}).get("content", "")
                )
                return True, f"OK ({elapsed:.0f}ms): {text[:50]}"
            if resp.status_code == 401:
                return False, f"HTTP 401 - Invalid/expired key ({elapsed:.0f}ms)"
            if resp.status_code == 403:
                return (
                    False,
                    f"HTTP 403 - Forbidden - key likely invalid ({elapsed:.0f}ms)",
                )
            if resp.status_code == 429:
                return False, f"HTTP 429 - Rate limited ({elapsed:.0f}ms)"
            return False, f"HTTP {resp.status_code} ({elapsed:.0f}ms): {resp.text[:80]}"

    except httpx.TimeoutException:
        return False, "timeout"
    except httpx.NetworkError as e:
        return False, f"network error: {str(e)[:60]}"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:60]}"


async def validate_all_keys(
    verbose: bool = False, proxy_url: str | None = None
) -> dict[str, Any]:
    """Validate all keys and return a summary report."""
    configs = _load_provider_configs()

    db_path = os.environ.get(
        "LLM_APIPOOL_DB", str(Path.home() / ".llm-apipool" / "keys.db")
    )
    if not Path(db_path).exists():
        return {"error": f"No DB found at {db_path}"}

    store = KeyStore(db_path=Path(db_path))
    keys = store.get_all_keys()

    by_provider: dict[str, list[dict[str, Any]]] = {}
    for key in keys:
        prov = key.get("provider", "unknown")
        if prov not in by_provider:
            by_provider[prov] = []
        by_provider[prov].append(key)

    results: dict[str, Any] = {
        "total_keys": len(keys),
        "providers_tested": 0,
        "keys_passed": 0,
        "keys_failed": 0,
        "provider_results": {},
    }

    print(f"Total keys in database: {len(keys)}")
    print(f"Providers: {len(by_provider)}")
    print("=" * 70)

    for provider in sorted(by_provider.keys()):
        provider_keys = by_provider[provider]
        cfg = configs.get(provider, {})

        # Skip providers without a default model
        default_model = cfg.get("default_model", "")
        if not default_model:
            print(f"\n{provider}: SKIPPED (no default_model configured)")
            continue

        base_url = cfg.get("base_url", "")
        no_auth = bool(cfg.get("no_auth", False))

        print(
            f"\n{provider}: Testing {len(provider_keys)} key(s)... (no_auth={no_auth})"
        )
        results["providers_tested"] += 1

        passed = 0
        failed = 0
        failures: list[str] = []

        for key in provider_keys:
            api_key = key["api_key"]
            model = key.get("model") or default_model

            success, detail = await _test_key_direct(
                provider, api_key, base_url, model, no_auth
            )

            if success:
                passed += 1
                status = "✓ PASS"
            else:
                failed += 1
                status = "✗ FAIL"
                failures.append(f"Key #{key['id']}: {detail}")

            if verbose or not success:
                masked = _mask_key(api_key)
                print(f"  {status} Key #{key['id']} {masked}: {detail}")

        results["keys_passed"] += passed
        results["keys_failed"] += failed
        results["provider_results"][provider] = {
            "total": len(provider_keys),
            "passed": passed,
            "failed": failed,
            "failures": failures if not verbose else None,
        }

        print(f"  Summary: {passed} passed, {failed} failed")

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate all API keys in the pool.")
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed output for each key",
    )
    parser.add_argument(
        "--proxy-url",
        type=str,
        default=None,
        help="Test via proxy endpoint instead of direct provider calls",
    )
    return asyncio.run(_main(parser.parse_args()))


async def _main(args: argparse.Namespace) -> int:
    results = await validate_all_keys(verbose=args.verbose, proxy_url=args.proxy_url)

    print("\n" + "=" * 70)
    print("FINAL SUMMARY")
    print("=" * 70)
    print(f"Total keys:    {results['total_keys']}")
    print(f"Providers:     {results['providers_tested']} tested")
    print(f"Keys passed:   {results['keys_passed']}")
    print(f"Keys failed:   {results['keys_failed']}")

    # Categorize failures
    key_invalid_errors = ["401", "403", "invalid", "expired"]
    proxy_suspects: list[str] = []
    key_invalid_suspects: list[str] = []

    for provider, data in results.get("provider_results", {}).items():
        if data["failed"] == 0:
            continue

        # If ALL keys for a provider fail, check the failure types
        if data["failed"] == data["total"] and data["total"] > 0:
            # Check if failures are consistently auth errors (key-related)
            failures = data.get("failures", [])
            if failures and all(
                any(err in f.lower() for err in key_invalid_errors) for f in failures
            ):
                key_invalid_suspects.append(provider)
            else:
                proxy_suspects.append(provider)

    if proxy_suspects:
        print(
            "\n⚠️  WARNING: The following providers have ALL keys failing - possible proxy/config issue:"
        )
        for p in proxy_suspects:
            print(f"  - {p}")
            data = results["provider_results"][p]
            if data.get("failures"):
                for f in data["failures"][:3]:  # Show first 3 failures
                    print(f"      {f}")

    if key_invalid_suspects:
        print(
            "\n⚠️  Keys failed with auth errors (invalid/expired keys, not proxy issue):"
        )
        for p in key_invalid_suspects:
            print(f"  - {p}")

    if results["keys_failed"] > 0:
        print(f"\n⚠️  {results['keys_failed']} keys failed validation")
        return 1

    print("\n✓ All keys validated successfully!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
