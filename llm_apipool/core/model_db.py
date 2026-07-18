"""Database operations for the provider-model registry.

Provides query / upsert helpers that operate on the ``models``,
``key_model_access``, and ``provider_catalog_sources`` tables.

All functions expect an open SQLite connection (``sqlite3.Row``
factory), or a ``KeyStore`` instance that exposes ``_conn()``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

MODEL_COLS = (
    "id",
    "platform",
    "model_id",
    "display_name",
    "context_window",
    "max_input_tokens",
    "max_output_tokens",
    "supports_vision",
    "supports_tools",
    "supports_streaming",
    "supports_function_calling",
    "is_free",
    "is_deprecated",
    "tier",
    "intelligence_rank",
    "speed_rank",
    "size_label",
    "monthly_token_budget",
    "rpm_limit",
    "rpd_limit",
    "tpm_limit",
    "tpd_limit",
    "owner",
    "raw_metadata",
    "enabled",
    "last_updated_at",
    "last_checked_at",
)


def upsert_model(
    conn: Any,
    provider: str,
    model_id: str,
    *,
    display_name: str | None = None,
    context_window: int | None = None,
    max_input_tokens: int | None = None,
    max_output_tokens: int | None = None,
    supports_vision: bool = False,
    supports_tools: bool = False,
    supports_streaming: bool = True,
    supports_function_calling: bool = False,
    is_free: bool = True,
    is_deprecated: bool = False,
    tier: int = 4,
    intelligence_rank: int = 999,
    speed_rank: int = 999,
    size_label: str = "Medium",
    rpm_limit: int | None = None,
    rpd_limit: int | None = None,
    tpm_limit: int | None = None,
    tpd_limit: int | None = None,
    monthly_token_budget: str = "",
    owner: str | None = None,
    raw_metadata: str | None = None,
) -> int:
    """Insert or update a model row. Returns the row id."""
    now_iso = datetime.now(UTC).isoformat()
    cur = conn.execute(
        """INSERT INTO models (
            platform, model_id, display_name,
            context_window, max_input_tokens, max_output_tokens,
            supports_vision, supports_tools, supports_streaming,
            supports_function_calling, is_free, is_deprecated,
            tier, intelligence_rank, speed_rank, size_label,
            monthly_token_budget, rpm_limit, rpd_limit,
            tpm_limit, tpd_limit, owner, raw_metadata,
            last_updated_at, last_checked_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(platform, model_id) DO UPDATE SET
            display_name         = COALESCE(excluded.display_name, models.display_name),
            context_window       = COALESCE(excluded.context_window, models.context_window),
            max_input_tokens     = COALESCE(excluded.max_input_tokens, models.max_input_tokens),
            max_output_tokens    = COALESCE(excluded.max_output_tokens, models.max_output_tokens),
            supports_vision      = COALESCE(excluded.supports_vision, models.supports_vision),
            supports_tools       = COALESCE(excluded.supports_tools, models.supports_tools),
            supports_streaming   = COALESCE(excluded.supports_streaming, models.supports_streaming),
            supports_function_calling = COALESCE(excluded.supports_function_calling, models.supports_function_calling),
            is_free              = COALESCE(excluded.is_free, models.is_free),
            is_deprecated        = COALESCE(excluded.is_deprecated, models.is_deprecated),
            tier                 = COALESCE(excluded.tier, models.tier),
            intelligence_rank    = COALESCE(excluded.intelligence_rank, models.intelligence_rank),
            speed_rank           = COALESCE(excluded.speed_rank, models.speed_rank),
            size_label           = COALESCE(excluded.size_label, models.size_label),
            monthly_token_budget = COALESCE(excluded.monthly_token_budget, models.monthly_token_budget),
            rpm_limit            = COALESCE(excluded.rpm_limit, models.rpm_limit),
            rpd_limit            = COALESCE(excluded.rpd_limit, models.rpd_limit),
            tpm_limit            = COALESCE(excluded.tpm_limit, models.tpm_limit),
            tpd_limit            = COALESCE(excluded.tpd_limit, models.tpd_limit),
            owner                = COALESCE(excluded.owner, models.owner),
            raw_metadata         = COALESCE(excluded.raw_metadata, models.raw_metadata),
            last_updated_at      = excluded.last_updated_at,
            last_checked_at      = excluded.last_checked_at
        """,
        (
            provider,
            model_id,
            display_name or model_id,
            context_window,
            max_input_tokens,
            max_output_tokens,
            int(supports_vision),
            int(supports_tools),
            int(supports_streaming),
            int(supports_function_calling),
            int(is_free),
            int(is_deprecated),
            tier,
            intelligence_rank,
            speed_rank,
            size_label,
            monthly_token_budget or "",
            rpm_limit,
            rpd_limit,
            tpm_limit,
            tpd_limit,
            owner,
            raw_metadata,
            now_iso,
            now_iso,
        ),
    )
    return cur.lastrowid


def link_key_to_model(
    conn: Any, key_id: int, model_db_id: int, *, priority: int = 0
) -> None:
    """Record that a key can access a model."""
    conn.execute(
        """INSERT OR IGNORE INTO key_model_access (key_id, model_db_id, is_active, priority)
           VALUES (?, ?, 1, ?)""",
        (key_id, model_db_id, priority),
    )


def unlink_key_from_model(conn: Any, key_id: int, model_db_id: int) -> None:
    """Remove the access link (set inactive rather than delete)."""
    conn.execute(
        "UPDATE key_model_access SET is_active = 0 WHERE key_id = ? AND model_db_id = ?",
        (key_id, model_db_id),
    )


def upsert_catalog_source(conn: Any, provider: str, **kw: Any) -> None:
    """Insert or update a provider catalog source record."""
    fields = {
        "models_endpoint": kw.get("models_endpoint"),
        "requires_api_key": int(kw.get("requires_api_key", True)),
        "free_detection_method": kw.get("free_detection_method"),
        "last_sync_at": kw.get("last_sync_at"),
        "sync_status": kw.get("sync_status", "pending"),
    }
    conn.execute(
        """INSERT INTO provider_catalog_sources
               (provider, models_endpoint, requires_api_key, free_detection_method, last_sync_at, sync_status)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(provider) DO UPDATE SET
               models_endpoint      = COALESCE(excluded.models_endpoint, provider_catalog_sources.models_endpoint),
               requires_api_key     = COALESCE(excluded.requires_api_key, provider_catalog_sources.requires_api_key),
               free_detection_method = COALESCE(excluded.free_detection_method, provider_catalog_sources.free_detection_method),
               last_sync_at         = COALESCE(excluded.last_sync_at, provider_catalog_sources.last_sync_at),
               sync_status          = excluded.sync_status
        """,
        (
            provider,
            fields["models_endpoint"],
            fields["requires_api_key"],
            fields["free_detection_method"],
            fields["last_sync_at"],
            fields["sync_status"],
        ),
    )


# ── Query helpers ──────────────────────────────────────────────────────────────


def get_models(
    conn: Any,
    *,
    provider: str | None = None,
    tier: int | None = None,
    free_only: bool = False,
    min_context: int | None = None,
    supports_tools: bool | None = None,
    supports_vision: bool | None = None,
    search: str | None = None,
    sort_by: str = "tier",
    limit: int = 200,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query the ``models`` table with optional filters.

    Returns deduplicated rows (by ``model_id``) enriched with provider
    and key-access information from a LEFT JOIN on ``key_model_access``.
    """
    where_clauses: list[str] = ["m.is_deprecated = 0"]
    params: list[Any] = []

    # Only show models from providers that have active keys in the pool
    where_clauses.append(
        "m.platform IN (SELECT DISTINCT provider FROM api_keys WHERE is_active = 1)"
    )

    if provider:
        where_clauses.append("m.platform = ?")
        params.append(provider)
    if tier is not None:
        where_clauses.append("m.tier = ?")
        params.append(tier)
    if free_only:
        where_clauses.append("m.is_free = 1")
    if min_context is not None:
        where_clauses.append("(m.context_window IS NULL OR m.context_window >= ?)")
        params.append(min_context)
    if supports_tools is not None:
        where_clauses.append("m.supports_tools = ?")
        params.append(1 if supports_tools else 0)
    if supports_vision is not None:
        where_clauses.append("m.supports_vision = ?")
        params.append(1 if supports_vision else 0)
    if search:
        where_clauses.append("(m.model_id LIKE ? OR m.display_name LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])

    sort_map = {
        "tier": "m.tier ASC, m.intelligence_rank DESC",
        "intelligence_rank": "m.intelligence_rank DESC",
        "speed_rank": "m.speed_rank DESC",
        "context_window": "m.context_window DESC NULLS LAST",
        "provider": "m.platform ASC",
        "model_id": "m.model_id ASC",
    }
    order = sort_map.get(sort_by, "m.tier ASC, m.intelligence_rank DESC")

    sql = f"""SELECT DISTINCT m.*, km.key_id, km.is_active AS key_available
              FROM models m
              LEFT JOIN key_model_access km ON km.model_db_id = m.id
              WHERE {" AND ".join(where_clauses)}
              ORDER BY {order}, m.model_id ASC
              LIMIT ? OFFSET ?"""
    params.extend([limit, offset])

    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_model_by_id(conn: Any, model_db_id: int) -> dict[str, Any] | None:
    """Return a single model row by its primary key."""
    row = conn.execute("SELECT * FROM models WHERE id = ?", (model_db_id,)).fetchone()
    return dict(row) if row else None


def get_model_by_provider_id(
    conn: Any, provider: str, model_id: str
) -> dict[str, Any] | None:
    """Return a single model row by provider + model_id."""
    row = conn.execute(
        "SELECT * FROM models WHERE platform = ? AND model_id = ?",
        (provider, model_id),
    ).fetchone()
    return dict(row) if row else None


def get_keys_for_model(conn: Any, model_db_id: int) -> list[dict[str, Any]]:
    """Return all keys that can access a given model."""
    rows = conn.execute(
        """SELECT ak.* FROM api_keys ak
           JOIN key_model_access kma ON kma.key_id = ak.id
           WHERE kma.model_db_id = ? AND kma.is_active = 1 AND ak.is_active = 1""",
        (model_db_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_models_for_key(conn: Any, key_id: int) -> list[dict[str, Any]]:
    """Return all models accessible by a given key."""
    rows = conn.execute(
        """SELECT m.* FROM models m
           JOIN key_model_access kma ON kma.model_db_id = m.id
           WHERE kma.key_id = ? AND kma.is_active = 1 AND m.is_deprecated = 0""",
        (key_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_sync_status(conn: Any, provider: str | None = None) -> list[dict[str, Any]]:
    """Return sync status for one or all providers."""
    if provider:
        rows = conn.execute(
            "SELECT * FROM provider_catalog_sources WHERE provider = ?",
            (provider,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM provider_catalog_sources ORDER BY provider"
        ).fetchall()
    return [dict(r) for r in rows]


def mark_sync_complete(conn: Any, provider: str) -> None:
    """Mark a provider sync as successful."""
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "UPDATE provider_catalog_sources SET last_sync_at = ?, sync_status = 'success' WHERE provider = ?",
        (now, provider),
    )


def mark_sync_failed(conn: Any, provider: str) -> None:
    """Mark a provider sync as failed."""
    conn.execute(
        "UPDATE provider_catalog_sources SET sync_status = 'failed' WHERE provider = ?",
        (provider,),
    )


__all__ = [
    "upsert_model",
    "link_key_to_model",
    "unlink_key_from_model",
    "upsert_catalog_source",
    "get_models",
    "get_model_by_id",
    "get_model_by_provider_id",
    "get_keys_for_model",
    "get_models_for_key",
    "get_sync_status",
    "mark_sync_complete",
    "mark_sync_failed",
]
