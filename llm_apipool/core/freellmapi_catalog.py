"""FreeLLMAPI model catalog — separate DB of verified free models.

Fetches the curated free-model catalog from the FreeLLMAPI project
(https://freellmapi.co) and stores it in its own SQLite database,
independent from the main ``keys.db``.

The FreeLLMAPI catalog contains models from providers with confirmed
free tiers — so you can trust that anything in this list is *really* free.
Users can also add their own custom free models, and toggle individual
models or entire providers on/off.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Provider name mapping: FreeLLMAPI → llm-apipool
_PROVIDER_MAP = {
    "github": "github_models",
}

# ── Config ──────────────────────────────────────────────────────────────────────

_FREE_MODELS_DB_ENV = "FREE_MODELS_DB"
_FREELLMAPI_CATALOG_URL_ENV = "FREELLMAPI_CATALOG_URL"
_DEFAULT_CATALOG_URL = "https://api.freellmapi.co/v1/latest"
_FETCH_TIMEOUT_S = 20

# ── DB helpers ──────────────────────────────────────────────────────────────────


def _get_db_path() -> Path:
    """Resolve the free-models DB path (separate from ``keys.db``)."""
    env = os.environ.get(_FREE_MODELS_DB_ENV)
    if env:
        return Path(env)
    return Path.home() / ".llm-apipool" / "free_models.db"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS free_models (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    platform          TEXT NOT NULL,
    model_id          TEXT NOT NULL,
    display_name      TEXT NOT NULL DEFAULT '',
    intelligence_rank INTEGER NOT NULL DEFAULT 999,
    speed_rank        INTEGER NOT NULL DEFAULT 999,
    size_label        TEXT NOT NULL DEFAULT 'Medium',
    context_window    INTEGER,
    supports_vision   INTEGER NOT NULL DEFAULT 0,
    supports_tools    INTEGER NOT NULL DEFAULT 0,
    rpm_limit         INTEGER,
    rpd_limit         INTEGER,
    tpm_limit         INTEGER,
    tpd_limit         INTEGER,
    monthly_token_budget TEXT NOT NULL DEFAULT '',
    enabled           INTEGER NOT NULL DEFAULT 1,
    provider_enabled  INTEGER NOT NULL DEFAULT 1,
    is_custom         INTEGER NOT NULL DEFAULT 0,
    tier              INTEGER NOT NULL DEFAULT 4,
    catalog_version   TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(platform, model_id)
);

CREATE TABLE IF NOT EXISTS catalog_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def init_db(conn: sqlite3.Connection) -> None:
    """Ensure the free-models tables exist."""
    conn.executescript(_SCHEMA)
    conn.commit()


def get_connection() -> sqlite3.Connection:
    """Open (and init) the free-models database."""
    db_path = _get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    init_db(conn)
    return conn


# ── Sync from FreeLLMAPI ────────────────────────────────────────────────────────


def _catalog_url() -> str:
    return os.environ.get(_FREELLMAPI_CATALOG_URL_ENV, _DEFAULT_CATALOG_URL)


def fetch_catalog() -> tuple[list[dict[str, Any]], str] | tuple[None, str]:
    """Fetch the FreeLLMAPI model catalog over HTTP(S).

    Returns ``(models_list, version_string)``, or ``(None, "")`` if the
    fetch fails.
    """

    url = _catalog_url()
    logger.info("Fetching FreeLLMAPI catalog from %s", url)
    try:
        resp = httpx.get(url, timeout=_FETCH_TIMEOUT_S)
        resp.raise_for_status()
        body = resp.json()
    except Exception as exc:
        logger.warning("FreeLLMAPI catalog fetch failed: %s", exc)
        return None, ""

    if not isinstance(body, dict):
        return body if isinstance(body, list) else [], ""
    models = body.get("models", [])
    version = str(body.get("version", "unknown"))
    logger.info(
        "Fetched %d models (version=%s) from FreeLLMAPI catalog", len(models), version
    )
    return models, version


def _assign_tier(intel_rank: int) -> int:
    """Map FreeLLMAPI intelligence rank (1-based position) to our 4-tier system.

    Lower rank = more intelligent. With ~85 total models:
      Top 12%  (rank <= 10)  → Tier 1
      Next 24% (rank <= 30)  → Tier 2
      Next 36% (rank <= 60)  → Tier 3
      Bottom 28% (rank 61+)  → Tier 4
    """
    if intel_rank <= 10:
        return 1
    if intel_rank <= 30:
        return 2
    if intel_rank <= 60:
        return 3
    return 4


def sync_catalog(conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    """Fetch the FreeLLMAPI catalog and upsert into the separate DB.

    Returns a summary dict with counts and status.
    """
    close = conn is None
    if conn is None:
        conn = get_connection()
    try:
        models, version = fetch_catalog()
        if models is None:
            return {"ok": False, "action": "fetch_failed", "count": 0}

        now_iso = datetime.now(UTC).isoformat()
        processed = 0
        seen_keys: set[tuple[str, str]] = set()

        for m in models:
            platform = _PROVIDER_MAP.get(m.get("platform", ""), m.get("platform", ""))
            model_id = m.get("modelId", "")
            if not platform or not model_id:
                continue

            intel_rank = m.get("intelligenceRank", 999) or 999
            speed_rank = m.get("speedRank", 999) or 999

            limits = m.get("limits") or {}
            tier = _assign_tier(intel_rank)

            conn.execute(
                """INSERT INTO free_models (
                    platform, model_id, display_name,
                    intelligence_rank, speed_rank, size_label,
                    context_window, supports_vision, supports_tools,
                    rpm_limit, rpd_limit, tpm_limit, tpd_limit,
                    monthly_token_budget, tier, catalog_version,
                    updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(platform, model_id) DO UPDATE SET
                    display_name      = COALESCE(excluded.display_name, free_models.display_name),
                    intelligence_rank = excluded.intelligence_rank,
                    speed_rank        = excluded.speed_rank,
                    size_label        = COALESCE(excluded.size_label, free_models.size_label),
                    context_window    = COALESCE(excluded.context_window, free_models.context_window),
                    supports_vision   = excluded.supports_vision,
                    supports_tools    = excluded.supports_tools,
                    rpm_limit         = excluded.rpm_limit,
                    rpd_limit         = excluded.rpd_limit,
                    tpm_limit         = excluded.tpm_limit,
                    tpd_limit         = excluded.tpd_limit,
                    monthly_token_budget = COALESCE(excluded.monthly_token_budget, free_models.monthly_token_budget),
                    tier              = excluded.tier,
                    catalog_version   = excluded.catalog_version,
                    updated_at        = excluded.updated_at
                """,
                (
                    platform,
                    model_id,
                    m.get("displayName", "") or model_id,
                    intel_rank,
                    speed_rank,
                    m.get("sizeLabel", "Medium") or "Medium",
                    m.get("contextWindow"),
                    1 if m.get("supportsVision") else 0,
                    1 if m.get("supportsTools") else 0,
                    limits.get("rpm"),
                    limits.get("rpd"),
                    limits.get("tpm"),
                    limits.get("tpd"),
                    m.get("monthlyTokenBudget") or "",
                    tier,
                    version,
                    now_iso,
                ),
            )
            seen_keys.add((platform, model_id))
            processed += 1

        # Remove stale non-custom entries not in the current catalog
        if seen_keys:
            placeholders = ",".join(["(?,?)"] * len(seen_keys))
            flat = [v for pair in seen_keys for v in pair]
            conn.execute(
                f"DELETE FROM free_models WHERE is_custom = 0 AND (platform, model_id) NOT IN ({placeholders})",
                flat,
            )

        conn.execute(
            "INSERT OR REPLACE INTO catalog_meta (key, value) VALUES ('last_version', ?)",
            (version,),
        )
        conn.execute(
            "INSERT OR REPLACE INTO catalog_meta (key, value) VALUES ('last_sync_at', ?)",
            (now_iso,),
        )
        conn.commit()

        logger.info(
            "FreeLLMAPI catalog sync: %d processed (version=%s)",
            processed,
            version,
        )
        return {
            "ok": True,
            "action": "synced",
            "version": version,
            "total": len(models),
        }
    finally:
        if close:
            conn.close()


def sync_free_models_to_main_db(store: Any) -> int:
    """Upsert all enabled FreeLLMAPI catalog models into the main ``models`` table.

    This unifies the two free-model systems: after a FreeLLMAPI catalog sync,
    every verified-free model is also upserted into the main ``keys.db`` so
    the dashboard and proxy can discover them alongside provider-synced models.

    Models are inserted with ``is_free = 1`` and ``enabled = 1``.  If a model
    already exists in the main DB (e.g. from a provider model sync), only
    the ``is_free`` and ``tier`` fields are updated — other fields (like
    ``context_window``, ``capabilities``) from the provider sync take
    precedence (via ``COALESCE`` in ``upsert_model``).

    Returns the number of models upserted.
    """
    from llm_apipool.core.model_db import upsert_model  # avoid circular import

    free_models = get_free_models(enabled_only=True)
    if not free_models:
        logger.debug("sync_free_models_to_main_db: no free models to sync")
        return 0

    conn = store._conn()
    count = 0
    for fm in free_models:
        try:
            upsert_model(
                conn,
                fm["platform"],
                fm["model_id"],
                display_name=fm.get("display_name") or fm["model_id"],
                context_window=fm.get("context_window"),
                supports_vision=bool(fm.get("supports_vision")),
                supports_tools=bool(fm.get("supports_tools")),
                is_free=True,
                tier=fm.get("tier", 4),
                intelligence_rank=fm.get("intelligence_rank", 999),
                speed_rank=fm.get("speed_rank", 999),
                size_label=fm.get("size_label", "Medium"),
                rpm_limit=fm.get("rpm_limit"),
                rpd_limit=fm.get("rpd_limit"),
                tpm_limit=fm.get("tpm_limit"),
                tpd_limit=fm.get("tpd_limit"),
                monthly_token_budget=fm.get("monthly_token_budget", ""),
            )
            count += 1
        except Exception:
            logger.exception(
                "Failed to upsert free model %s/%s",
                fm["platform"],
                fm["model_id"],
            )

    logger.info("sync_free_models_to_main_db: %d models upserted", count)
    return count


# ── Query helpers ───────────────────────────────────────────────────────────────


def get_free_models(
    conn: sqlite3.Connection | None = None,
    *,
    platform: str | None = None,
    enabled_only: bool = False,
    search: str | None = None,
    custom_only: bool = False,
) -> list[dict[str, Any]]:
    """List free models from the separate DB.

    Returns dicts with all columns.
    """
    close = conn is None
    if conn is None:
        conn = get_connection()
    try:
        clauses: list[str] = []
        params: list[Any] = []

        if platform:
            clauses.append("platform = ?")
            params.append(platform)
        if enabled_only:
            clauses.append("enabled = 1 AND provider_enabled = 1")
        if custom_only:
            clauses.append("is_custom = 1")
        if search:
            clauses.append("(model_id LIKE ? OR display_name LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])

        where = ""
        if clauses:
            where = "WHERE " + " AND ".join(clauses)

        rows = conn.execute(
            f"SELECT * FROM free_models {where} ORDER BY platform ASC, tier ASC, intelligence_rank DESC",
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        if close:
            conn.close()


def get_free_model_set(conn: sqlite3.Connection | None = None) -> set[tuple[str, str]]:
    """Return a set of ``(platform, model_id)`` tuples for all enabled free models.

    Useful for fast cross-referencing with the main models table.
    """
    close = conn is None
    if conn is None:
        conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT platform, model_id FROM free_models WHERE enabled = 1 AND provider_enabled = 1"
        ).fetchall()
        return {(r["platform"], r["model_id"]) for r in rows}
    finally:
        if close:
            conn.close()


def get_free_models_summary(conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    """Return summary stats about the free models catalog."""
    close = conn is None
    if conn is None:
        conn = get_connection()
    try:
        total = conn.execute("SELECT COUNT(*) AS c FROM free_models").fetchone()["c"]
        custom = conn.execute(
            "SELECT COUNT(*) AS c FROM free_models WHERE is_custom = 1"
        ).fetchone()["c"]
        enabled = conn.execute(
            "SELECT COUNT(*) AS c FROM free_models WHERE enabled = 1 AND provider_enabled = 1"
        ).fetchone()["c"]
        providers = conn.execute(
            "SELECT COUNT(DISTINCT platform) AS c FROM free_models"
        ).fetchone()["c"]

        last_sync = conn.execute(
            "SELECT value FROM catalog_meta WHERE key = 'last_sync_at'"
        ).fetchone()
        version = conn.execute(
            "SELECT value FROM catalog_meta WHERE key = 'last_version'"
        ).fetchone()

        return {
            "total": total,
            "custom": custom,
            "enabled": enabled,
            "providers": providers,
            "last_sync_at": last_sync["value"] if last_sync else None,
            "version": version["value"] if version else None,
        }
    finally:
        if close:
            conn.close()


def get_providers(conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    """List distinct providers and their model counts."""
    close = conn is None
    if conn is None:
        conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT
                platform,
                COUNT(*) AS model_count,
                SUM(CASE WHEN enabled = 1 AND provider_enabled = 1 THEN 1 ELSE 0 END) AS enabled_count,
                SUM(CASE WHEN is_custom = 1 THEN 1 ELSE 0 END) AS custom_count
               FROM free_models
               GROUP BY platform
               ORDER BY platform ASC"""
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        if close:
            conn.close()


# ── Mutations ────────────────────────────────────────────────────────────────────


def toggle_free_model(
    platform: str,
    model_id: str,
    enabled: bool,
    conn: sqlite3.Connection | None = None,
) -> bool:
    """Enable or disable a single free model."""
    close = conn is None
    if conn is None:
        conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE free_models SET enabled = ?, updated_at = ? WHERE platform = ? AND model_id = ?",
            (1 if enabled else 0, datetime.now(UTC).isoformat(), platform, model_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        if close:
            conn.close()


def toggle_provider(
    platform: str,
    enabled: bool,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Enable or disable all models for a provider. Returns count updated."""
    close = conn is None
    if conn is None:
        conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE free_models SET provider_enabled = ?, updated_at = ? WHERE platform = ?",
            (1 if enabled else 0, datetime.now(UTC).isoformat(), platform),
        )
        conn.commit()
        return cur.rowcount
    finally:
        if close:
            conn.close()


def add_custom_free_model(
    platform: str,
    model_id: str,
    *,
    display_name: str | None = None,
    context_window: int | None = None,
    supports_vision: bool = False,
    supports_tools: bool = False,
    tier: int = 4,
    conn: sqlite3.Connection | None = None,
) -> bool:
    """Add a user-defined model to the free list."""
    close = conn is None
    if conn is None:
        conn = get_connection()
    try:
        now = datetime.now(UTC).isoformat()
        try:
            conn.execute(
                """INSERT INTO free_models (
                    platform, model_id, display_name,
                    context_window, supports_vision, supports_tools,
                    is_custom, tier, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,1,?,?,?)""",
                (
                    platform,
                    model_id,
                    display_name or model_id,
                    context_window,
                    1 if supports_vision else 0,
                    1 if supports_tools else 0,
                    tier,
                    now,
                    now,
                ),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            # Already exists — just mark as custom-enabled
            conn.execute(
                """UPDATE free_models SET
                    is_custom = 1, enabled = 1, tier = ?,
                    updated_at = ?
                WHERE platform = ? AND model_id = ?""",
                (tier, now, platform, model_id),
            )
            conn.commit()
            return True
    finally:
        if close:
            conn.close()


def remove_custom_free_model(
    platform: str,
    model_id: str,
    conn: sqlite3.Connection | None = None,
) -> bool:
    """Remove a user-defined free model from the list."""
    close = conn is None
    if conn is None:
        conn = get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM free_models WHERE platform = ? AND model_id = ? AND is_custom = 1",
            (platform, model_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        if close:
            conn.close()


__all__ = [
    "get_connection",
    "init_db",
    "fetch_catalog",
    "sync_catalog",
    "get_free_models",
    "get_free_model_set",
    "get_free_models_summary",
    "get_providers",
    "toggle_free_model",
    "toggle_provider",
    "add_custom_free_model",
    "remove_custom_free_model",
]
