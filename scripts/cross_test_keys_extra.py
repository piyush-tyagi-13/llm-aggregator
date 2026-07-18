#!/usr/bin/env python3
"""Extended testing for unmatched keys and edge cases."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import httpx

DB_PATH = Path.home() / ".llm-apipool" / "keys.db"

# Additional providers to test (including no_auth ones that may accept keys,
# non-OpenAI-compatible ones, and ones we missed)
EXTRA_PROVIDERS = [
    # no_auth providers - test if they also accept keys
    ("pollinations", "https://text.pollinations.ai/openai", "openai"),
    ("opencode_zen", "https://opencode.ai/zen/v1", "deepseek-v4-flash-free"),
    ("kilo_gateway", "https://api.kilogateway.com/v1", "llama-3.3-70b-instruct"),
    (
        "ovh_ai",
        "https://endpoints.ai.cloud.ovh.net/api/v1",
        "Meta-Llama-3.3-70B-Instruct",
    ),
    ("llm7", "https://api.llm7.com/v1", "llama-3.3-70b"),
    # Non-OpenAI-compatible
    ("cohere", "https://api.cohere.com/v2", "command-r-plus-08-2024"),
    # DNS resolution issues - test with alternative endpoints
    (
        "nebius_alt",
        "https://api.studio.nebius.ai/v1",
        "meta-llama/Meta-Llama-3.1-70B-Instruct",
    ),
    # Azure OpenAI - for AQ. prefixed keys
    ("azure_openai", "https://models.inference.ai.azure.com", "gpt-4o-mini"),
]

# Re-test specific keys against paxsenix more carefully
PAXSENIX_ONLY = [
    ("paxsenix", "https://api.paxsenix.org/v1", "claude-sonnet-4-6"),
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
            "body": text[:300].decode(errors="replace"),
        }
    except httpx.TimeoutException:
        return {"key_id": key_id, "provider": provider, "status": 0, "body": "timeout"}
    except httpx.ConnectError:
        return {
            "key_id": key_id,
            "provider": provider,
            "status": 0,
            "body": "connect_err",
        }
    except Exception as e:
        return {
            "key_id": key_id,
            "provider": provider,
            "status": 0,
            "body": f"{type(e).__name__}",
        }


async def main():
    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute(
        "SELECT id, api_key FROM api_keys WHERE provider='pollinations' ORDER BY id"
    ).fetchall()
    conn.close()

    keys_by_id = {r[0]: r[1] for r in rows}

    async with httpx.AsyncClient(limits=httpx.Limits(max_connections=20)) as client:
        # Test ALL keys against EXTRA providers
        print("=== EXTRA PROVIDER TESTS ===")
        for provider, base_url, model in EXTRA_PROVIDERS:
            print(f"\n--- Testing {provider} ({base_url}) ---")
            tasks = []
            for key_id, api_key in rows:
                tasks.append(
                    test_one(client, provider, base_url, model, api_key, key_id)
                )
            results = await asyncio.gather(*tasks)
            for r in results:
                status = r["status"]
                if status == 200:
                    print(f"  ✅ ID {r['key_id']:>3d}: {r['body'][:120]}")
                elif status == 429:
                    print(f"  🔶 ID {r['key_id']:>3d}: RATE LIMITED")
                elif status in (401, 403):
                    pass  # expected for wrong keys
                elif status != 0:
                    print(
                        f"  ❓ ID {r['key_id']:>3d}: HTTP {status} — {r['body'][:120]}"
                    )

        # Re-test specific key groups
        print("\n\n=== TARGETED PAXSENIX TEST (hash.id keys) ===")
        hash_id_keys = [
            (k, v)
            for k, v in keys_by_id.items()
            if "." in v[:30] and "acv" not in v[:5]
        ]
        for key_id, api_key in hash_id_keys:
            r = await test_one(
                client,
                "paxsenix",
                "https://api.paxsenix.org/v1",
                "claude-sonnet-4-6",
                api_key,
                key_id,
            )
            icon = {200: "✅", 429: "🔶", 0: "⏱️"}.get(r["status"], "❓")
            print(f"  {icon} ID {key_id:>3d}: HTTP {r['status']} — {r['body'][:120]}")

        print("\n\n=== TARGETED: no_auth providers with AQ./acv- keys ===")
        for provider, base_url, model in [
            (
                "kilo_gateway",
                "https://api.kilogateway.com/v1",
                "llama-3.3-70b-instruct",
            ),
            (
                "ovh_ai",
                "https://endpoints.ai.cloud.ovh.net/api/v1",
                "Meta-Llama-3.3-70B-Instruct",
            ),
        ]:
            print(f"\n--- {provider} ---")
            for key_id, api_key in rows:
                if key_id in (73, 77, 78, 79, 80, 81, 82):
                    continue  # already known Mistral
                r = await test_one(client, provider, base_url, model, api_key, key_id)
                if r["status"] not in (0, 401, 403):
                    icon = {200: "✅", 429: "🔶"}.get(r["status"], "❓")
                    print(
                        f"  {icon} ID {key_id:>3d}: HTTP {r['status']} — {r['body'][:120]}"
                    )


if __name__ == "__main__":
    asyncio.run(main())
