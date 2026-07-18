#!/usr/bin/env python3
"""Cross-test keys assigned to pollinations against all other providers.
Tests all 41 keys in parallel and produces a compact summary.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path

import httpx

DB_PATH = Path.home() / ".llm-apipool" / "keys.db"

# OpenAI-compatible providers that accept keys
PROVIDERS = [
    ("groq", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    ("cerebras", "https://api.cerebras.ai/v1", "llama3.3-70b"),
    ("sambanova", "https://api.sambanova.ai/v1", "Meta-Llama-3.3-70B-Instruct"),
    ("mistral", "https://api.mistral.ai/v1", "mistral-large-latest"),
    (
        "openrouter",
        "https://openrouter.ai/api/v1",
        "meta-llama/llama-3.3-70b-instruct:free",
    ),
    (
        "google",
        "https://generativelanguage.googleapis.com/v1beta/openai/",
        "gemini-2.0-flash",
    ),
    (
        "nvidia_nim",
        "https://integrate.api.nvidia.com/v1",
        "nvidia/llama-3.1-nemotron-70b-instruct",
    ),
    ("github_models", "https://models.inference.ai.azure.com", "gpt-4o-mini"),
    ("zhipu", "https://open.bigmodel.cn/api/paas/v4", "glm-4-flash"),
    (
        "huggingface_router",
        "https://router.huggingface.co/hf-inference/v1",
        "meta-llama/Llama-3.3-70B-Instruct",
    ),
    ("interfaze", "https://api.interfaze.ai/v1", "interfaze/interfaze-beta"),
    (
        "together",
        "https://api.together.xyz/v1",
        "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    ),
    (
        "fireworks",
        "https://api.fireworks.ai/inference/v1",
        "accounts/fireworks/models/llama-v3p3-70b-instruct",
    ),
    (
        "deepinfra",
        "https://api.deepinfra.com/v1/openai",
        "deepseek-ai/DeepSeek-V4-Flash",
    ),
    ("scaleway", "https://api.scaleway.ai/v1", "llama-3.3-70b-instruct"),
    ("nebius", "https://api.nebius.ai/v1", "meta-llama/Meta-Llama-3.1-70B-Instruct"),
    ("novita", "https://api.novita.ai/v3/openai", "meta-llama/llama-3.3-70b-instruct"),
    ("ai21", "https://api.ai21.com/studio/v1", "jamba-1.5-large"),
    ("upstage", "https://api.upstage.ai/v1", "solar-pro"),
    ("alibaba", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
    ("hyperbolic", "https://api.hyperbolic.xyz/v1", "deepseek-ai/DeepSeek-V3-0324"),
    ("openai", "https://api.openai.com/v1", "gpt-4o-mini"),
    ("deepseek", "https://api.deepseek.com/v1", "deepseek-chat"),
    ("paxsenix", "https://api.paxsenix.org/v1", "claude-sonnet-4-6"),
    ("inference_net", "https://api.inference.net/v1", "meta-llama-3-70b-instruct"),
]


async def test_one(
    client: httpx.AsyncClient,
    provider: str,
    base_url: str,
    model: str,
    api_key: str,
    key_id: int,
) -> dict:
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "Say: ok"}],
        "max_tokens": 5,
    }

    try:
        resp = await client.post(url, headers=headers, json=body, timeout=8.0)
        text = await resp.aread()
        return {
            "key_id": key_id,
            "provider": provider,
            "status": resp.status_code,
            "body": text[:200].decode(errors="replace"),
        }
    except httpx.TimeoutException:
        return {
            "key_id": key_id,
            "provider": provider,
            "status": 999,
            "body": "timeout",
        }
    except httpx.ConnectError as e:
        return {
            "key_id": key_id,
            "provider": provider,
            "status": 998,
            "body": f"connect_err: {e!s}",
        }
    except Exception as e:
        return {
            "key_id": key_id,
            "provider": provider,
            "status": 997,
            "body": f"{type(e).__name__}: {e!s}",
        }


def classify(status: int, body: str) -> str:
    """Classify result: MATCH, LIKELY, or NO."""
    if status == 200:
        return "MATCH"
    if status == 429:
        return "LIKELY"
    if status in (997, 998, 999):
        return "NET_ERR"
    return "NO"


async def test_key_all_providers(
    sem: asyncio.Semaphore, client: httpx.AsyncClient, key_id: int, api_key: str
) -> dict:
    async with sem:
        tasks = [test_one(client, p, b, m, api_key, key_id) for p, b, m in PROVIDERS]
        results = await asyncio.gather(*tasks)

    key_preview = api_key[:25]
    matches = [r for r in results if classify(r["status"], r["body"]) == "MATCH"]
    likely = [r for r in results if classify(r["status"], r["body"]) == "LIKELY"]

    return {
        "key_id": key_id,
        "preview": key_preview,
        "length": len(api_key),
        "prefix": api_key[:6] + ("..." if len(api_key) > 20 else ""),
        "matches": [
            {"p": r["provider"], "s": r["status"], "b": r["body"][:100]}
            for r in matches
        ],
        "likely": [
            {"p": r["provider"], "s": r["status"], "b": r["body"][:100]} for r in likely
        ],
        "all": results,
    }


async def main():
    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute(
        "SELECT id, api_key FROM api_keys WHERE provider='pollinations' ORDER BY id"
    ).fetchall()
    conn.close()

    print(f"Testing {len(rows)} keys against {len(PROVIDERS)} providers...\n")

    sem = asyncio.Semaphore(5)  # 5 keys at a time

    async with httpx.AsyncClient(
        limits=httpx.Limits(max_connections=30, max_keepalive_connections=10),
    ) as client:
        tasks = [
            test_key_all_providers(sem, client, key_id, api_key)
            for key_id, api_key in rows
        ]
        all_results = await asyncio.gather(*tasks)

    # Summary table
    print(f"{'ID':>4s} {'PREFIX':30s} {'LEN':>4s} {'MATCHES':50s} {'LIKELY':30s}")
    print("-" * 120)
    for r in all_results:
        match_str = ", ".join(f"{m['p']}({m['s']})" for m in r["matches"]) or "-"
        likely_str = ", ".join(f"{m['p']}({m['s']})" for m in r["likely"]) or "-"
        print(
            f"{r['key_id']:>4d} {r['prefix']:30s} {r['length']:>4d} {match_str:50s} {likely_str:30s}"
        )

    # Detailed results for anything with a match or likely
    print("\n\n=== DETAILED RESULTS (keys with MATCH or LIKELY) ===")
    for r in all_results:
        if r["matches"] or r["likely"]:
            print(f"\n--- Key ID {r['key_id']} ({r['preview']}...) ---")
            for m in r["matches"]:
                print(f"  ✅ MATCH: {m['p']} (HTTP {m['s']}) — {m['b'][:120]}")
            for m in r["likely"]:
                print(f"  🔶 LIKELY: {m['p']} (HTTP {m['s']}) — {m['b'][:120]}")

    # Summary statistics
    total = len(all_results)
    matched = sum(1 for r in all_results if r["matches"])
    likely_total = sum(1 for r in all_results if r["likely"])
    no_match = sum(1 for r in all_results if not r["matches"] and not r["likely"])

    print("\n\n=== SUMMARY ===")
    print(f"Total keys: {total}")
    print(f"With MATCH (200 OK): {matched}")
    print(f"With LIKELY (429 rate-limit): {likely_total}")
    print(f"No match found: {no_match}")

    # Save full results
    out_path = Path("/tmp/cross_test_results.json")
    # Make results serializable
    serializable = []
    for r in all_results:
        serializable.append(
            {
                "key_id": r["key_id"],
                "preview": r["preview"],
                "length": r["length"],
                "prefix": r["prefix"],
                "matches": r["matches"],
                "likely": r["likely"],
            }
        )
    out_path.write_text(json.dumps(serializable, indent=2))
    print(f"\nFull results saved to {out_path}")


if __name__ == "__main__":
    t0 = time.time()
    asyncio.run(main())
    print(f"\nElapsed: {time.time() - t0:.1f}s")
