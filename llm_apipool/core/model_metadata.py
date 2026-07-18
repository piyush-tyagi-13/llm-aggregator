"""Database-backed model metadata catalog.

All model capabilities (context window, vision, tools) are loaded from the
database ``models`` table — never hardcoded.  The module exports a small
functional API used by the rest of the system:

- refresh_from_db() — (re)load cache from DB
- filter_models() — filter by capability
- fetch_provider_models() — sync from remote provider endpoints
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_cache: dict[str, dict[str, Any]] = {}
"""``{model_name: {context, tools, vision, image_gen, tts, stt, platform}}``"""

_SOURCE_PROVIDERS: dict[str, dict[str, Any]] = {}
"""Cached dict of provider configs from providers.json."""


def _load_providers_config() -> dict[str, dict[str, Any]]:
    """Return the dict of provider configs from ``providers.json``.

    Results are cached after first load.
    """
    global _SOURCE_PROVIDERS
    if _SOURCE_PROVIDERS:
        return _SOURCE_PROVIDERS
    config_path = Path(__file__).resolve().parent.parent / "config" / "providers.json"
    try:
        data = json.loads(config_path.read_text())
        _SOURCE_PROVIDERS = (
            data if isinstance(data, dict) else data.get("providers", {})
        )
    except (FileNotFoundError, json.JSONDecodeError):
        _SOURCE_PROVIDERS = {}
    return _SOURCE_PROVIDERS


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def refresh_from_db(store: Any = None, db_path: str | None = None) -> int:
    """Load model metadata from the database into ``_cache``.

    Accepts either a *store* object (with ``get_all_models()``) or a
    *db_path* string for a direct SQLite connection.  Returns the number
    of models loaded (0 on failure).
    """
    global _cache
    _cache = {}

    import sqlite3

    if store is not None:
        try:
            rows = store.get_all_models()
        except Exception:
            return 0
        count = 0
        for row in rows:
            if not row.get("enabled"):
                continue
            model_id = row.get("model_id")
            if not model_id:
                continue
            _cache[model_id] = {
                "context": row.get("context_window") or 8192,
                "tools": bool(row.get("supports_tools")),
                "vision": bool(row.get("supports_vision")),
                "image_gen": bool(row.get("supports_image_generation")),
                "tts": bool(row.get("supports_tts")),
                "stt": bool(row.get("supports_stt")),
                "platform": row.get("platform", ""),
            }
            count += 1
        return count

    # Fallback: direct SQLite connection
    if db_path is None:
        new_db = Path.home() / ".llm-apipool" / "keys.db"
        old_db = Path.home() / ".llm-aggregator" / "keys.db"
        db_path = (
            str(new_db if new_db.exists() else old_db)
            if old_db.exists()
            else str(new_db)
        )

    conn = None
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT platform, model_id, context_window, supports_vision, supports_tools,
                   supports_image_generation, supports_tts, supports_stt
            FROM models WHERE enabled = 1
        """).fetchall()
        for row in rows:
            model_id = row["model_id"]
            _cache[model_id] = {
                "context": row["context_window"] or 8192,
                "tools": bool(row["supports_tools"]),
                "vision": bool(row["supports_vision"]),
                "image_gen": bool(row["supports_image_generation"]),
                "tts": bool(row["supports_tts"]),
                "stt": bool(row["supports_stt"]),
                "platform": row["platform"] or "",
            }
        return len(rows)
    except Exception:
        return 0
    finally:
        if conn is not None:
            conn.close()


def filter_models(
    supports_tools: bool = False,
    supports_vision: bool = False,
    min_context: int = 0,
) -> list[str]:
    """Return sorted list of model names matching *all* given criteria.

    Models are sorted by context window descending.
    """
    result: list[tuple[int, str]] = []
    for name, info in _cache.items():
        if supports_tools and not info["tools"]:
            continue
        if supports_vision and not info["vision"]:
            continue
        ctx = info.get("context", 0) or 0
        if ctx < min_context:
            continue
        result.append((ctx, name))
    result.sort(key=lambda x: -x[0])
    return [name for _, name in result]


async def fetch_provider_models() -> dict[str, list[dict[str, Any]]]:
    """Fetch available models from all configured providers via their API.

    Returns ``{provider_name: [model_dict, ...]}``.
    """
    if httpx is None:
        return {}

    providers = _load_providers_config()
    results: dict[str, list[dict[str, Any]]] = {}

    async with httpx.AsyncClient(timeout=15.0) as client:
        for prov_name, prov in providers.items():
            base = prov.get("base_url", "").rstrip("/")
            url = f"{base}/v1/models"
            api_key = prov.get("key") or prov.get("api_key", "")
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            try:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                results[prov_name] = data.get("data", [])
            except Exception:  # noqa: BLE001
                pass

    return results


# ---------------------------------------------------------------------------
# Initialisation (lazy — triggered on first access)
# ---------------------------------------------------------------------------


def get_model_features(model_name: str) -> dict[str, Any] | None:
    """Return cached features dict for *model_name*, or ``None``."""
    return _cache.get(model_name)


def ensure_cache() -> int:
    """Initialise the cache from the database if it is empty.

    Safe to call multiple times.  Returns the number of models loaded.
    """
    if _cache:
        return len(_cache)
    return refresh_from_db()
