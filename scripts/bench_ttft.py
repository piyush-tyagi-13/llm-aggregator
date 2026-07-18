#!/usr/bin/env python3
"""Benchmark TTFT (Time To First Token) for provider completion calls.

Measures the round-trip time for a minimal completion call through the
provider dispatch pipeline.  Runs multiple iterations with both cold and
warm connection pools, outputting summary statistics.

Usage
-----
    uv run python scripts/bench_ttft.py [--iterations 5] [--provider groq]
    uv run python scripts/bench_ttft.py --all-providers  # test all with keys
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

# Ensure the package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _load_keys_from_db() -> dict[str, list[str]]:
    """Load active keys from the SQLite DB, grouped by provider."""
    from llm_apipool.key_store import KeyStore

    db_path = os.environ.get(
        "LLM_APIPOOL_DB", str(Path.home() / ".llm-apipool" / "keys.db")
    )
    if not Path(db_path).exists():
        print(f"  [SKIP] No DB found at {db_path}")
        return {}

    store = KeyStore(db_path=db_path)
    provider_keys: dict[str, list[str]] = {}
    for key in store.get_all_keys():
        if key.get("active", False):
            prov = key.get("provider", "")
            if prov not in provider_keys:
                provider_keys[prov] = []
            provider_keys[prov].append(key.get("api_key", ""))
    return provider_keys


def _get_providers_with_keys(
    target_provider: str | None,
    provider_keys: dict[str, list[str]],
    configs: dict[str, Any],
) -> list[tuple[str, str]]:
    """Return list of (provider, api_key) pairs to benchmark."""
    pairs: list[tuple[str, str]] = []
    for prov, keys in provider_keys.items():
        if target_provider and prov != target_provider:
            continue
        if prov not in configs:
            continue
        default_model = configs[prov].get("default_model")
        if not default_model:
            continue
        for key in keys[:1]:  # One key per provider
            pairs.append((prov, key))
    return pairs


async def _bench_single(
    provider: str,
    api_key: str,
    configs: dict[str, Any],
    iterations: int,
    warm: bool = False,
) -> list[float]:
    """Run *iterations* completion calls and return elapsed times in ms."""
    from llm_apipool.providers.dispatch import complete

    times: list[float] = []

    for i in range(iterations):
        # Use a minimal test message
        messages = [{"role": "user", "content": "Say exactly one word: hello"}]

        start = time.perf_counter()
        try:
            await complete(
                provider=provider,
                api_key=api_key,
                messages=messages,
                configs=configs,
            )
            elapsed = (time.perf_counter() - start) * 1000  # ms
            times.append(elapsed)

            if i == 0 and not warm:
                pass  # first call is always "cold"
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            times.append(elapsed)
            print(f"  [{provider}] iteration {i + 1} FAILED ({elapsed:.0f}ms): {e}")

    return times


def _print_stats(label: str, times: list[float]) -> None:
    """Print summary statistics for a set of measurements."""
    if not times:
        print(f"  {label}: no data")
        return
    print(f"  {label}:")
    print(f"    count:     {len(times)}")
    print(f"    min:       {min(times):8.1f} ms")
    print(f"    max:       {max(times):8.1f} ms")
    print(f"    mean:      {statistics.mean(times):8.1f} ms")
    if len(times) > 1:
        print(f"    median:    {statistics.median(times):8.1f} ms")
        print(f"    stdev:     {statistics.stdev(times):8.1f} ms")


def _load_configs(config_path: str | None = None) -> dict[str, Any]:
    """Load provider configs from providers.json."""
    if config_path is None:
        config_path = str(
            Path(__file__).resolve().parent.parent
            / "llm_apipool"
            / "config"
            / "providers.json"
        )
    with open(config_path) as f:
        return json.load(f)["providers"]


async def _main(args: argparse.Namespace) -> int:
    iterations = args.iterations
    target = args.provider

    print("=" * 60)
    print("TTFT Benchmark")
    print("=" * 60)
    print(f"Iterations:     {iterations}")
    print(f"Target:         {target or 'all providers with keys'}")
    print()

    # Load configs and keys
    configs = _load_configs()
    provider_keys = _load_keys_from_db()

    if not provider_keys:
        print("No API keys found in DB. Use LLM_APIPOOL_DB env var to point")
        print("to a key database, or import keys with `llm-apipool import`.")
        return 1

    pairs = _get_providers_with_keys(target, provider_keys, configs)
    if not pairs:
        print("No providers with keys found" + (f" for '{target}'" if target else ""))
        return 1

    print(f"Providers to benchmark: {len(pairs)}")
    for prov, key in pairs:
        masked = key[:8] + "..." + key[-4:] if len(key) > 12 else key[:4] + "..."
        print(f"  {prov:20s} {masked}")
    print()

    # Warm-up round — establish connection pools
    print("--- Warm-up (establish connection pools) ---")
    for prov, key in pairs:
        await _bench_single(prov, key, configs, 1, warm=True)
    print("  Done.\n")

    # Benchmark: cold call (first actual call after warm-up)
    print("--- Cold calls (first after warm-up) ---")
    cold_times: dict[str, list[float]] = {}
    for prov, key in pairs:
        t = await _bench_single(prov, key, configs, 1, warm=False)
        cold_times[prov] = t
        _print_stats(prov, t)

    # Benchmark: subsequent calls (connection reuse)
    print("\n--- Subsequent calls (connection reuse) ---")
    warm_times: dict[str, list[float]] = {}
    for prov, key in pairs:
        # Skip the first call (already measured as cold), do N-1 more
        extra = iterations - 1
        if extra < 1:
            extra = 1
        t = await _bench_single(prov, key, configs, extra, warm=True)
        warm_times[prov] = t
        _print_stats(prov, t)

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"{'Provider':20s} {'Cold (ms)':>12s} {'Warm (ms)':>12s} {'Speedup':>10s}")
    print("-" * 54)
    for prov, _ in pairs:
        cold_avg = statistics.mean(cold_times.get(prov, [0]))
        warm_avg = statistics.mean(warm_times.get(prov, [0]))
        speedup = cold_avg / warm_avg if warm_avg > 0 else 0
        print(f"{prov:20s} {cold_avg:10.1f}ms {warm_avg:10.1f}ms {speedup:8.1f}x")

    # --ci mode: fail if any provider gets worse (speedup < 0.8)
    if args.ci:
        failures: list[str] = []
        for prov, _ in pairs:
            cold_avg = statistics.mean(cold_times.get(prov, [0]))
            warm_avg = statistics.mean(warm_times.get(prov, [0]))
            speedup = cold_avg / warm_avg if warm_avg > 0 else 0
            if speedup < 0.8:
                failures.append(f"{prov}: speedup={speedup:.2f}x (threshold 0.8x)")
        if failures:
            print("\n[CI FAIL] Connection pooling regression detected:")
            for f in failures:
                print(f"  - {f}")
            return 1
        print("\n[CI PASS] All providers meet speedup threshold (>= 0.8x)")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark TTFT for provider completion calls."
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=5,
        help="Number of iterations per provider (default: 5)",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default=None,
        help="Benchmark a specific provider only",
    )
    parser.add_argument(
        "--ci",
        action="store_true",
        help="CI mode: fail if warm-pool speedup drops below 0.8x for any provider",
    )
    return asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
