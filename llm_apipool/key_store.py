"""SQLite-backed key store for llm-apipool."""

from __future__ import annotations


import contextlib
import json
import logging
import os
import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TypedDict


class KeyRow(TypedDict, total=False):
    id: int
    provider: str
    api_key: str
    base_url_override: str | None
    capabilities: str
    model: str | None
    extra_params: str
    is_active: int
    status: str
    tokens_used_today: int
    tokens_used_month: int
    requests_today: int
    requests_month: int
    last_429_at: str | None
    cooldown_until: str | None
    daily_reset_date: str | None
    monthly_reset_month: str | None
    added_at: str
    last_used_at: str | None
    context_size: int | None
    accuracy_score: int
    speed_score: int
    reliability_score: int
    group_name: str
    is_sticky_enabled: int
    sticky_ttl_hours: int
    priority: int


class AuditEntry(TypedDict, total=False):
    id: int
    ts: str
    subscriber_id: str
    key_id: int | None
    provider: str | None
    model: str | None
    tokens_in: int
    tokens_out: int
    latency_ms: int
    success: int
    error: str | None
    is_streaming: int
    ttfb_ms: int
    http_status: int
    http_method: str
    path: str
    client_ip: str

from llm_apipool.core.encryption import (
    maybe_decrypt_key,
    maybe_encrypt_key,
    ensure_encryption_key,
)

logger = logging.getLogger(__name__)

_MASK_MIN_LEN = 8
_MASK_SHOW = 4


def _mask_key(api_key: str) -> str:
    """Mask an API key for safe logging: show last 4 chars only."""
    if len(api_key) <= _MASK_MIN_LEN:
        return "****" + api_key[-_MASK_SHOW:] if len(api_key) > _MASK_SHOW else "****"
    return api_key[:_MASK_SHOW] + "****" + api_key[-_MASK_SHOW:]


# DB lives at ~/.llm-apipool/keys.db by default; override via LLM_APIPOOL_DB env var
_NEW_DB_DEFAULT = Path.home() / ".llm-apipool" / "keys.db"
_OLD_DB_DEFAULT = Path.home() / ".llm-aggregator" / "keys.db"


def _resolve_db_path() -> Path:
    env = os.environ.get("LLM_APIPOOL_DB") or os.environ.get("LLM_APIPOOL_DB_LEGACY")
    if env:
        return Path(env)
    if _NEW_DB_DEFAULT.exists() and _OLD_DB_DEFAULT.exists():
        logger.warning(
            "Both %s and %s exist. Using %s.",
            _OLD_DB_DEFAULT,
            _NEW_DB_DEFAULT,
            _NEW_DB_DEFAULT,
        )
    if not _NEW_DB_DEFAULT.exists() and _OLD_DB_DEFAULT.exists():
        _NEW_DB_DEFAULT.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_OLD_DB_DEFAULT, _NEW_DB_DEFAULT)
    return _NEW_DB_DEFAULT


SCHEMA = """
CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    api_key TEXT NOT NULL,
    base_url_override TEXT,
    capabilities TEXT NOT NULL DEFAULT '["general_purpose"]',
    model TEXT,
    extra_params TEXT NOT NULL DEFAULT '{}',
    is_active INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'unknown',
    tokens_used_today INTEGER NOT NULL DEFAULT 0,
    tokens_used_month INTEGER NOT NULL DEFAULT 0,
    requests_today INTEGER NOT NULL DEFAULT 0,
    requests_month INTEGER NOT NULL DEFAULT 0,
    last_429_at TEXT,
    cooldown_until TEXT,
    daily_reset_date TEXT,
    monthly_reset_month TEXT,
    added_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_used_at TEXT,
    context_size INTEGER,
    accuracy_score INTEGER NOT NULL DEFAULT 50,
    speed_score INTEGER NOT NULL DEFAULT 50,
    reliability_score INTEGER NOT NULL DEFAULT 50,
    group_name TEXT NOT NULL DEFAULT 'default',
    is_sticky_enabled INTEGER NOT NULL DEFAULT 0,
    sticky_ttl_hours INTEGER NOT NULL DEFAULT 1,
    priority INTEGER NOT NULL DEFAULT 0,
    UNIQUE(provider, api_key)
);

CREATE TABLE IF NOT EXISTS rotation_state (
    cap_key TEXT PRIMARY KEY,
    cursor INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS rotation_slot_counts (
    key_id INTEGER NOT NULL PRIMARY KEY,
    slot_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sticky_sessions (
    session_id TEXT NOT NULL PRIMARY KEY,
    key_id INTEGER NOT NULL,
    provider TEXT NOT NULL,
    model TEXT,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT NOT NULL,
    subscriber_id TEXT NOT NULL DEFAULT 'unknown',
    key_id        INTEGER,
    provider      TEXT,
    model         TEXT,
    tokens_in     INTEGER DEFAULT 0,
    tokens_out    INTEGER DEFAULT 0,
    latency_ms    INTEGER DEFAULT 0,
    success       INTEGER DEFAULT 1,
    error         TEXT
);

CREATE TABLE IF NOT EXISTS models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    model_id TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    intelligence_rank INTEGER NOT NULL DEFAULT 999,
    speed_rank INTEGER NOT NULL DEFAULT 999,
    size_label TEXT NOT NULL DEFAULT 'Medium',
    context_window INTEGER,
    supports_vision INTEGER NOT NULL DEFAULT 0,
    supports_tools INTEGER NOT NULL DEFAULT 0,
    supports_image_generation INTEGER NOT NULL DEFAULT 0,
    supports_tts INTEGER NOT NULL DEFAULT 0,
    supports_stt INTEGER NOT NULL DEFAULT 0,
    rpm_limit INTEGER,
    rpd_limit INTEGER,
    tpm_limit INTEGER,
    tpd_limit INTEGER,
    monthly_token_budget TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    UNIQUE(platform, model_id)
);

CREATE TABLE IF NOT EXISTS fallback_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_db_id INTEGER NOT NULL REFERENCES models(id),
    priority INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    UNIQUE(model_db_id)
);

CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    emoji TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL DEFAULT '#6366f1',
    type TEXT NOT NULL DEFAULT 'custom',
    is_favorite INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0,
    auto_sort TEXT,
    layout_config TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS profile_models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    model_db_id INTEGER NOT NULL REFERENCES models(id) ON DELETE CASCADE,
    priority INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    UNIQUE(profile_id, model_db_id)
);

-- Auth tables (FreeLLMAPI-style)
-- Per-model-per-key cooldown tracking
CREATE TABLE IF NOT EXISTS model_cooldowns (
    key_id       INTEGER NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
    model_db_id  INTEGER NOT NULL REFERENCES models(id) ON DELETE CASCADE,
    cooldown_until TEXT,
    cooldown_count INTEGER NOT NULL DEFAULT 0,
    updated_at   TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (key_id, model_db_id)
);

-- Track disabled models for user/auto recovery
CREATE TABLE IF NOT EXISTS disabled_models (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    model_db_id  INTEGER NOT NULL REFERENCES models(id) ON DELETE CASCADE,
    model_id     TEXT NOT NULL,
    platform     TEXT,
    key_id       INTEGER REFERENCES api_keys(id) ON DELETE CASCADE,
    reason       TEXT NOT NULL DEFAULT 'user',  -- 'user' or 'auto_429'
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# Performance indexes for frequently queried columns
INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_api_keys_provider ON api_keys(provider)",
    "CREATE INDEX IF NOT EXISTS idx_api_keys_active ON api_keys(is_active)",
    "CREATE INDEX IF NOT EXISTS idx_api_keys_cooldown ON api_keys(cooldown_until)",
    "CREATE INDEX IF NOT EXISTS idx_api_keys_requests_today ON api_keys(requests_today)",
    "CREATE INDEX IF NOT EXISTS idx_api_keys_group ON api_keys(group_name)",
    "CREATE INDEX IF NOT EXISTS idx_api_keys_sticky ON api_keys(is_sticky_enabled)",
    "CREATE INDEX IF NOT EXISTS idx_rotation_state_cap_key ON rotation_state(cap_key)",
    "CREATE INDEX IF NOT EXISTS idx_audit_log_ts ON audit_log(ts)",
    "CREATE INDEX IF NOT EXISTS idx_audit_log_subscriber ON audit_log(subscriber_id)",
    "CREATE INDEX IF NOT EXISTS idx_models_platform ON models(platform)",
    "CREATE INDEX IF NOT EXISTS idx_models_enabled ON models(enabled)",
    "CREATE INDEX IF NOT EXISTS idx_models_capabilities ON models(supports_vision, supports_tools)",
    "CREATE INDEX IF NOT EXISTS idx_fallback_config_priority ON fallback_config(priority)",
    "CREATE INDEX IF NOT EXISTS idx_models_tier ON models(tier)",
    "CREATE INDEX IF NOT EXISTS idx_models_free ON models(is_free)",
    "CREATE INDEX IF NOT EXISTS idx_models_context ON models(context_window)",
    "CREATE INDEX IF NOT EXISTS idx_key_model_access_key ON key_model_access(key_id)",
    "CREATE INDEX IF NOT EXISTS idx_key_model_access_model ON key_model_access(model_db_id)",
    "CREATE INDEX IF NOT EXISTS idx_model_cooldowns_key ON model_cooldowns(key_id)",
    "CREATE INDEX IF NOT EXISTS idx_model_cooldowns_model ON model_cooldowns(model_db_id)",
    "CREATE INDEX IF NOT EXISTS idx_disabled_models_model ON disabled_models(model_db_id)",
    "CREATE INDEX IF NOT EXISTS idx_disabled_models_platform ON disabled_models(platform)",
]

MIGRATIONS = [
    "ALTER TABLE api_keys ADD COLUMN model TEXT",
    # capabilities column: migrate from legacy category column
    "ALTER TABLE api_keys ADD COLUMN capabilities TEXT",
    # rotation_state: rename category -> cap_key (SQLite 3.25+)
    "ALTER TABLE rotation_state RENAME COLUMN category TO cap_key",
    # audit_log table
    (
        "CREATE TABLE IF NOT EXISTS audit_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "ts TEXT NOT NULL, "
        "subscriber_id TEXT NOT NULL DEFAULT 'unknown', "
        "key_id INTEGER, "
        "provider TEXT, "
        "model TEXT, "
        "tokens_in INTEGER DEFAULT 0, "
        "tokens_out INTEGER DEFAULT 0, "
        "latency_ms INTEGER DEFAULT 0, "
        "success INTEGER DEFAULT 1, "
        "error TEXT)"
    ),
    "ALTER TABLE api_keys ADD COLUMN base_url_override TEXT",
    "ALTER TABLE api_keys ADD COLUMN status TEXT NOT NULL DEFAULT 'unknown'",
    "ALTER TABLE api_keys ADD COLUMN last_checked_at TEXT",
    # FreeLLMAPI-style tables (models, fallback_config, profiles, profile_models)
    # These are now created in SCHEMA above — this migration handles pre-existing DBs
    "CREATE TABLE IF NOT EXISTS models ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "platform TEXT NOT NULL, "
    "model_id TEXT NOT NULL, "
    "display_name TEXT NOT NULL DEFAULT '', "
    "intelligence_rank INTEGER NOT NULL DEFAULT 999, "
    "speed_rank INTEGER NOT NULL DEFAULT 999, "
    "size_label TEXT NOT NULL DEFAULT 'Medium', "
    "context_window INTEGER, "
    "supports_vision INTEGER NOT NULL DEFAULT 0, "
    "supports_tools INTEGER NOT NULL DEFAULT 0, "
    "supports_image_generation INTEGER NOT NULL DEFAULT 0, "
    "supports_tts INTEGER NOT NULL DEFAULT 0, "
    "supports_stt INTEGER NOT NULL DEFAULT 0, "
    "rpm_limit INTEGER, "
    "rpd_limit INTEGER, "
    "tpm_limit INTEGER, "
    "tpd_limit INTEGER, "
    "monthly_token_budget TEXT NOT NULL DEFAULT '', "
    "enabled INTEGER NOT NULL DEFAULT 1, "
    "UNIQUE(platform, model_id))",
    "CREATE TABLE IF NOT EXISTS fallback_config ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "model_db_id INTEGER NOT NULL REFERENCES models(id), "
    "priority INTEGER NOT NULL, "
    "enabled INTEGER NOT NULL DEFAULT 1, "
    "UNIQUE(model_db_id))",
    "CREATE TABLE IF NOT EXISTS profiles ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "name TEXT NOT NULL, "
    "emoji TEXT NOT NULL DEFAULT '', "
    "color TEXT NOT NULL DEFAULT '#6366f1', "
    "type TEXT NOT NULL DEFAULT 'custom', "
    "is_favorite INTEGER NOT NULL DEFAULT 0, "
    "sort_order INTEGER NOT NULL DEFAULT 0, "
    "auto_sort TEXT, "
    "layout_config TEXT, "
    "created_at TEXT NOT NULL DEFAULT (datetime('now')))",
    "CREATE TABLE IF NOT EXISTS profile_models ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE, "
    "model_db_id INTEGER NOT NULL REFERENCES models(id) ON DELETE CASCADE, "
    "priority INTEGER NOT NULL, "
    "enabled INTEGER NOT NULL DEFAULT 1, "
    "UNIQUE(profile_id, model_db_id))",
    # ── Extended model columns (0009) ────────────────────────────────────────
    "ALTER TABLE models ADD COLUMN max_input_tokens INTEGER",
    "ALTER TABLE models ADD COLUMN max_output_tokens INTEGER",
    "ALTER TABLE models ADD COLUMN supports_streaming INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE models ADD COLUMN supports_function_calling INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE models ADD COLUMN is_free INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE models ADD COLUMN is_deprecated INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE models ADD COLUMN tier INTEGER NOT NULL DEFAULT 4",
    "ALTER TABLE models ADD COLUMN owner TEXT",
    "ALTER TABLE models ADD COLUMN raw_metadata TEXT",
    "ALTER TABLE models ADD COLUMN last_updated_at TEXT NOT NULL DEFAULT (datetime('now'))",
    "ALTER TABLE models ADD COLUMN last_checked_at TEXT",
    # ── New model tables (0009) ──────────────────────────────────────────────
    "CREATE TABLE IF NOT EXISTS key_model_access ("
    "key_id INTEGER NOT NULL REFERENCES api_keys(id), "
    "model_db_id INTEGER NOT NULL REFERENCES models(id), "
    "is_active INTEGER NOT NULL DEFAULT 1, "
    "priority INTEGER NOT NULL DEFAULT 0, "
    "PRIMARY KEY(key_id, model_db_id))",
    "CREATE TABLE IF NOT EXISTS provider_catalog_sources ("
    "provider TEXT PRIMARY KEY, "
    "models_endpoint TEXT, "
    "requires_api_key INTEGER NOT NULL DEFAULT 1, "
    "free_detection_method TEXT, "
    "last_sync_at TEXT, "
    "sync_status TEXT NOT NULL DEFAULT 'pending')",
    # ── Cooldown & disabled model tables (0010) ──────────────────────────
    "CREATE TABLE IF NOT EXISTS model_cooldowns ("
    "key_id INTEGER NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE, "
    "model_db_id INTEGER NOT NULL REFERENCES models(id) ON DELETE CASCADE, "
    "cooldown_until TEXT, "
    "cooldown_count INTEGER NOT NULL DEFAULT 0, "
    "updated_at TEXT NOT NULL DEFAULT (datetime('now')), "
    "PRIMARY KEY (key_id, model_db_id))",
    "CREATE TABLE IF NOT EXISTS disabled_models ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "model_db_id INTEGER NOT NULL REFERENCES models(id) ON DELETE CASCADE, "
    "model_id TEXT NOT NULL, "
    "platform TEXT, "
    "key_id INTEGER REFERENCES api_keys(id) ON DELETE CASCADE, "
    "reason TEXT NOT NULL DEFAULT 'user', "
    "created_at TEXT NOT NULL DEFAULT (datetime('now')))",
    # ── Audit log enrichment columns ─────────────────────────────────────
    "ALTER TABLE audit_log ADD COLUMN is_streaming INTEGER DEFAULT 0",
    "ALTER TABLE audit_log ADD COLUMN ttfb_ms INTEGER DEFAULT 0",
    "ALTER TABLE audit_log ADD COLUMN http_status INTEGER DEFAULT 0",
    "ALTER TABLE audit_log ADD COLUMN http_method TEXT DEFAULT ''",
    "ALTER TABLE audit_log ADD COLUMN path TEXT DEFAULT ''",
    "ALTER TABLE audit_log ADD COLUMN client_ip TEXT DEFAULT ''",
]


class KeyStore:
    """SQLite-backed persistent key store."""

    def __init__(self, db_path: Path | None = None) -> None:
        """Initialize the key store."""
        self._db_path = db_path or _resolve_db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        # Warm the encryption key on startup — harmless when no key exists
        try:
            ensure_encryption_key()
        except (RuntimeError, OSError):
            pass

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            for migration in MIGRATIONS:
                try:
                    conn.execute(migration)
                except sqlite3.OperationalError as e:
                    logger.debug("Migration skipped (already applied): %s", e)
            for index in INDEXES:
                with contextlib.suppress(sqlite3.OperationalError):
                    conn.execute(index)

    # --- capability helpers ---

    @staticmethod
    def parse_capabilities(row: dict[str, Any]) -> list[str]:
        """Parse capabilities from a DB row."""
        caps = row.get("capabilities")
        if caps:
            try:
                parsed = json.loads(caps)
                if isinstance(parsed, list) and parsed:
                    return [str(c) for c in parsed]
            except (json.JSONDecodeError, TypeError):
                return [str(caps)]
        return ["general_purpose"]

    # --- key management ---

    @staticmethod
    def _decrypt_row(row: dict[str, Any]) -> dict[str, Any]:
        """Decrypt the api_key field in a row if it's encrypted."""
        if "api_key" in row:
            row["api_key"] = maybe_decrypt_key(
                row["api_key"], provider=row.get("provider", "")
            )
        return row

    def register_key(  # noqa: PLR0913
        self,
        provider: str,
        api_key: str,
        capabilities: list[str] | str | None = None,
        model: str | None = None,
        base_url_override: str | None = None,
        extra_params: dict[str, Any] | None = None,
        context_size: int | None = None,
        accuracy_score: int = 50,
        speed_score: int = 50,
        reliability_score: int = 50,
        group_name: str = "default",
        is_sticky_enabled: bool = False,
        sticky_ttl_hours: int = 1,
    ) -> dict[str, Any]:
        """Register a new API key in the store."""
        if capabilities is None:
            capabilities = ["general_purpose"]
        elif isinstance(capabilities, str):
            capabilities = [capabilities]
        # Before encrypting, check whether the same plaintext key exists
        # (encryption uses a random nonce so the UNIQUE constraint won't catch it)
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT id, api_key FROM api_keys WHERE provider = ?", (provider,)
            ).fetchall()
            for row in existing:
                stored_plain = maybe_decrypt_key(row["api_key"], provider=provider)
                if stored_plain == api_key:
                    return {
                        "success": False,
                        "message": f"Key already registered for {provider}. Deactivate existing key first.",
                    }

        encrypted_key = maybe_encrypt_key(api_key, provider=provider)
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO api_keys
                   (provider, api_key, base_url_override, capabilities, model, extra_params,
                    context_size, accuracy_score, speed_score, reliability_score,
                    group_name, is_sticky_enabled, sticky_ttl_hours)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    provider,
                    encrypted_key,
                    base_url_override or None,
                    json.dumps(capabilities),
                    model or None,
                    json.dumps(extra_params or {}),
                    context_size,
                    accuracy_score,
                    speed_score,
                    reliability_score,
                    group_name,
                    1 if is_sticky_enabled else 0,
                    sticky_ttl_hours,
                ),
            )
            caps_str = ", ".join(capabilities)
            return {
                "success": True,
                "message": f"Key registered for {provider} ({caps_str}) model={model or 'default'}",
            }

    def get_active_keys(self, capabilities: list[str] | str) -> list[dict[str, Any]]:
        """Return active, non-cooled-down keys that have ANY of the requested capabilities."""
        if isinstance(capabilities, str):
            capabilities = [capabilities]
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM api_keys
                   WHERE is_active = 1
                     AND (cooldown_until IS NULL OR cooldown_until < ?)
                   ORDER BY requests_today ASC""",
                (now,),
            ).fetchall()
        result = []
        for r in rows:
            row = self._decrypt_row(dict(r))
            key_caps = self.parse_capabilities(row)
            if any(c in key_caps for c in capabilities):
                result.append(row)
        return result

    def get_all_keys(self) -> list[dict[str, Any]]:
        """Return all registered keys."""
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM api_keys ORDER BY provider").fetchall()
            return [self._decrypt_row(dict(r)) for r in rows]

    def get_key_by_id(self, key_id: int) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM api_keys WHERE id = ?", (key_id,)
            ).fetchone()
            return self._decrypt_row(dict(row)) if row else None

    # ── Model registry helpers ───────────────────────────────────────────────

    def get_model_db_id(self, platform: str, model_id: str) -> int | None:
        """Resolve (platform, model_id) to a model's DB id. Returns None if not found."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id FROM models WHERE platform = ? AND model_id = ?",
                (platform, model_id),
            ).fetchone()
        return row["id"] if row else None

    def get_models_for_provider(self, provider: str) -> list[dict[str, Any]]:
        """Return all enabled models for a specific provider."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM models WHERE platform = ? AND enabled = 1 ORDER BY model_id",
                (provider,),
            ).fetchall()
            return [dict(r) for r in rows]

    def record_usage(
        self, key_id: int, tokens: int, was_429: bool, cooldown_until: str | None = None
    ) -> None:  # noqa: FBT001
        """Record token usage for a key and update counters."""
        now = datetime.now(UTC).isoformat()
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        month = datetime.now(UTC).strftime("%Y-%m")

        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM api_keys WHERE id = ?", (key_id,)
            ).fetchone()
            if not row:
                return
            row = dict(row)

            tokens_today = (
                row["tokens_used_today"] if row["daily_reset_date"] == today else 0
            )
            requests_today = (
                row["requests_today"] if row["daily_reset_date"] == today else 0
            )
            tokens_month = (
                row["tokens_used_month"] if row["monthly_reset_month"] == month else 0
            )
            requests_month = (
                row["requests_month"] if row["monthly_reset_month"] == month else 0
            )

            conn.execute(
                """UPDATE api_keys SET
                    tokens_used_today   = ?,
                    tokens_used_month   = ?,
                    requests_today      = ?,
                    requests_month      = ?,
                    last_used_at        = ?,
                    last_429_at         = CASE WHEN ? THEN ? ELSE last_429_at END,
                    cooldown_until      = ?,
                    daily_reset_date    = ?,
                    monthly_reset_month = ?
                WHERE id = ?""",
                (
                    tokens_today + tokens,
                    tokens_month + tokens,
                    requests_today + 1,
                    requests_month + 1,
                    now,
                    was_429,
                    now if was_429 else None,
                    cooldown_until,
                    today,
                    month,
                    key_id,
                ),
            )

    # ── Per-model-per-key cooldown tracking ─────────────────────────────

    def record_model_cooldown(
        self,
        key_id: int,
        model_db_id: int,
        cooldown_until: str | None = None,
    ) -> None:
        """Increment cooldown count for a (key, model) pair and set cooldown."""
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO model_cooldowns (key_id, model_db_id, cooldown_until, cooldown_count, updated_at)
                   VALUES (?, ?, ?, 1, ?)
                   ON CONFLICT(key_id, model_db_id) DO UPDATE SET
                       cooldown_until = excluded.cooldown_until,
                       cooldown_count = cooldown_count + 1,
                       updated_at = excluded.updated_at""",
                (key_id, model_db_id, cooldown_until, now),
            )

    def check_model_cooldown(self, key_id: int, model_db_id: int) -> bool:
        """Check if a specific (key, model) pair is on cooldown. True = still cooling down."""
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT cooldown_until FROM model_cooldowns WHERE key_id = ? AND model_db_id = ?",
                (key_id, model_db_id),
            ).fetchone()
            if not row or not row["cooldown_until"]:
                return False
            return row["cooldown_until"] > now

    def clear_model_cooldown(self, key_id: int, model_db_id: int) -> None:
        """Clear cooldown for a (key, model) pair."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE model_cooldowns SET cooldown_until = NULL, updated_at = datetime('now') WHERE key_id = ? AND model_db_id = ?",
                (key_id, model_db_id),
            )

    def get_model_cooldown_counts(self, model_db_id: int) -> dict[str, int]:
        """Return total and per-provider cooldown counts for a model."""
        with self._conn() as conn:
            # Total across all keys
            total = conn.execute(
                "SELECT COALESCE(SUM(cooldown_count), 0) as c FROM model_cooldowns WHERE model_db_id = ?",
                (model_db_id,),
            ).fetchone()["c"]
            # Per-key breakdown
            key_rows = conn.execute(
                """
                SELECT mc.key_id, mc.cooldown_count, k.provider
                FROM model_cooldowns mc
                LEFT JOIN api_keys k ON k.id = mc.key_id
                WHERE mc.model_db_id = ?
                ORDER BY mc.cooldown_count DESC
            """,
                (model_db_id,),
            ).fetchall()
            return {
                "total": total,
                "per_key": [
                    {
                        "key_id": r["key_id"],
                        "provider": r["provider"],
                        "count": r["cooldown_count"],
                    }
                    for r in key_rows
                ],
            }

    # ── Disabled models (user + auto) ───────────────────────────────────

    def disable_model(
        self,
        model_db_id: int,
        model_id: str,
        platform: str | None = None,
        key_id: int | None = None,
        reason: str = "user",
    ) -> None:
        """Disable a model with a given scope and record for recovery."""
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO disabled_models (model_db_id, model_id, platform, key_id, reason) VALUES (?, ?, ?, ?, ?)",
                (model_db_id, model_id, platform, key_id, reason),
            )
            if platform and not key_id:
                # Disable from entire provider
                conn.execute(
                    "UPDATE models SET enabled = 0 WHERE id = ? AND platform = ?",
                    (model_db_id, platform),
                )
            elif key_id:
                # Disable from specific key
                conn.execute(
                    "UPDATE key_model_access SET is_active = 0 WHERE key_id = ? AND model_db_id = ?",
                    (key_id, model_db_id),
                )
            else:
                # Global disable
                conn.execute(
                    "UPDATE models SET enabled = 0 WHERE model_id = ?",
                    (model_id,),
                )

    def auto_disable_if_threshold(
        self,
        model_db_id: int,
        platform: str,
        threshold: int = 3,
    ) -> bool:
        """Disable a non-free model from a provider if cooldown count >= threshold. Returns True if disabled."""
        with self._conn() as conn:
            # Check if model is non-free and has >= threshold cooldowns for this provider
            model_row = conn.execute(
                "SELECT model_id, is_free FROM models WHERE id = ?",
                (model_db_id,),
            ).fetchone()
            if not model_row or model_row["is_free"]:
                return False
            total_cooldowns = conn.execute(
                """
                SELECT COALESCE(SUM(mc.cooldown_count), 0) as c
                FROM model_cooldowns mc
                JOIN api_keys k ON k.id = mc.key_id
                WHERE mc.model_db_id = ? AND k.provider = ?
            """,
                (model_db_id, platform),
            ).fetchone()["c"]
            if total_cooldowns < threshold:
                return False
            # Disable the model for this provider
            conn.execute(
                "UPDATE models SET enabled = 0 WHERE id = ? AND platform = ?",
                (model_db_id, platform),
            )
            # Record as auto-disabled if not already recorded
            conn.execute(
                "INSERT OR IGNORE INTO disabled_models (model_db_id, model_id, platform, reason) VALUES (?, ?, ?, 'auto_429')",
                (model_db_id, model_row["model_id"], platform),
            )
            return True

    def get_disabled_models(self) -> list[dict[str, Any]]:
        """Return all disabled models with scope info."""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT d.*, m.model_id as original_model, m.platform as original_platform,
                       m.display_name, m.tier, m.is_free
                FROM disabled_models d
                LEFT JOIN models m ON m.id = d.model_db_id
                ORDER BY d.created_at DESC
            """).fetchall()
            return [dict(r) for r in rows]

    def recover_disabled_model(self, disabled_id: int) -> bool:
        """Recover a disabled model by its disabled_models row id. Returns True if recovered."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM disabled_models WHERE id = ?", (disabled_id,)
            ).fetchone()
            if not row:
                return False
            row = dict(row)
            if row["platform"] and not row["key_id"]:
                # Re-enable for this provider
                conn.execute(
                    "UPDATE models SET enabled = 1 WHERE id = ?",
                    (row["model_db_id"],),
                )
            elif row["key_id"]:
                # Re-enable for specific key
                conn.execute(
                    "UPDATE key_model_access SET is_active = 1 WHERE key_id = ? AND model_db_id = ?",
                    (row["key_id"], row["model_db_id"]),
                )
            else:
                # Global re-enable
                conn.execute(
                    "UPDATE models SET enabled = 1 WHERE model_id = ?",
                    (row["model_id"],),
                )
            conn.execute("DELETE FROM disabled_models WHERE id = ?", (disabled_id,))
            return True

    def recover_model(self, model_db_id: int, platform: str | None = None) -> int:
        """Re-enable a model globally or per-provider. Returns count of recovered rows."""
        with self._conn() as conn:
            if platform:
                conn.execute(
                    "UPDATE models SET enabled = 1 WHERE id = ? AND platform = ?",
                    (model_db_id, platform),
                )
                conn.execute(
                    "DELETE FROM disabled_models WHERE model_db_id = ? AND (platform = ? OR platform IS NULL)",
                    (model_db_id, platform),
                )
            else:
                conn.execute(
                    "UPDATE models SET enabled = 1 WHERE model_id = (SELECT model_id FROM models WHERE id = ?)",
                    (model_db_id,),
                )
                conn.execute(
                    "DELETE FROM disabled_models WHERE model_db_id = ?",
                    (model_db_id,),
                )
            return conn.total_changes

    # ── Key-level cooldown clear ─────────────────────────────────────────

    def clear_cooldown(self, key_id: int) -> None:
        """Clear a key's cooldown (after quota reset)."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE api_keys SET cooldown_until = NULL WHERE id = ?", (key_id,)
            )
            conn.execute(
                "UPDATE model_cooldowns SET cooldown_until = NULL, cooldown_count = 0 WHERE key_id = ?",
                (key_id,),
            )

    def update_key(
        self,
        key_id: int,
        model: str | None = None,
        api_key: str | None = None,
        provider: str | None = None,
    ) -> bool:
        """Update a key's model, api_key, and/or provider by ID. Returns True if updated."""
        with self._conn() as conn:
            if model is not None:
                conn.execute(
                    "UPDATE api_keys SET model = ? WHERE id = ?",
                    (model or None, key_id),
                )
            if api_key is not None:
                # Encrypt the key; use current provider for AAD (or new provider if also changing)
                current_provider = provider
                if current_provider is None:
                    row = conn.execute(
                        "SELECT provider FROM api_keys WHERE id = ?", (key_id,)
                    ).fetchone()
                    current_provider = row["provider"] if row else ""
                encrypted = maybe_encrypt_key(api_key, provider=current_provider)
                conn.execute(
                    "UPDATE api_keys SET api_key = ? WHERE id = ?", (encrypted, key_id)
                )
            if provider is not None:
                conn.execute(
                    "UPDATE api_keys SET provider = ? WHERE id = ?", (provider, key_id)
                )
        return bool(model is not None or api_key is not None or provider is not None)

    def deactivate_key(self, key_id: int) -> None:
        """Deactivate a key (soft delete)."""
        with self._conn() as conn:
            conn.execute("UPDATE api_keys SET is_active = 0 WHERE id = ?", (key_id,))

    def activate_key(self, key_id: int) -> bool:
        """Activate a key. Returns True if activated."""
        with self._conn() as conn:
            result = conn.execute(
                "UPDATE api_keys SET is_active = 1 WHERE id = ?", (key_id,)
            )
        return result.rowcount > 0

    def update_priority(self, key_id: int, priority: int) -> bool:
        """Update a key's priority value. Returns True if updated."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE api_keys SET priority = ? WHERE id = ?", (priority, key_id)
            )
        return True

    def update_key_status(
        self,
        key_id: int,
        status: str,
        enabled: bool | None = None,
        last_checked_at: str | None = None,
    ) -> None:
        """Update a key's health status and optionally its active state."""
        with self._conn() as conn:
            if enabled is not None:
                conn.execute(
                    "UPDATE api_keys SET status = ?, is_active = ?, last_checked_at = COALESCE(?, last_checked_at) WHERE id = ?",
                    (status, 1 if enabled else 0, last_checked_at, key_id),
                )
            else:
                conn.execute(
                    "UPDATE api_keys SET status = ?, last_checked_at = COALESCE(?, last_checked_at) WHERE id = ?",
                    (status, last_checked_at, key_id),
                )

    # --- audit log ---

    def log_audit(  # noqa: PLR0913
        self,
        subscriber_id: str,
        key_id: int,
        provider: str,
        model: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
        latency_ms: int = 0,
        success: bool = True,  # noqa: FBT001, FBT002
        error: str | None = None,
        is_streaming: bool = False,
        ttfb_ms: int = 0,
        http_status: int = 0,
        http_method: str = "",
        path: str = "",
        client_ip: str = "",
    ) -> None:
        """Log an API call to the audit trail."""
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO audit_log
                   (ts, subscriber_id, key_id, provider, model, tokens_in, tokens_out,
                    latency_ms, success, error, is_streaming, ttfb_ms, http_status,
                    http_method, path, client_ip)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    now,
                    subscriber_id,
                    key_id,
                    provider,
                    model,
                    tokens_in,
                    tokens_out,
                    latency_ms,
                    1 if success else 0,
                    error,
                    1 if is_streaming else 0,
                    ttfb_ms,
                    http_status,
                    http_method,
                    path,
                    client_ip,
                ),
            )

    def get_audit_log(
        self,
        subscriber_id: str | None = None,
        days: int = 7,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Return audit log entries, optionally filtered by subscriber."""
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        with self._conn() as conn:
            if subscriber_id:
                rows = conn.execute(
                    "SELECT * FROM audit_log WHERE ts > ? AND subscriber_id = ? ORDER BY ts DESC LIMIT ?",
                    (cutoff, subscriber_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM audit_log WHERE ts > ? ORDER BY ts DESC LIMIT ?",
                    (cutoff, limit),
                ).fetchall()
        return [dict(r) for r in rows]

    def get_audit_summary(self, days: int = 7) -> list[dict[str, Any]]:
        """Aggregate token/request counts grouped by subscriber_id."""
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT subscriber_id,
                          COUNT(*) as requests,
                          SUM(tokens_in) as tokens_in,
                          SUM(tokens_out) as tokens_out,
                          SUM(tokens_in + tokens_out) as tokens_total,
                          SUM(CASE WHEN success=0 THEN 1 ELSE 0 END) as errors
                   FROM audit_log
                   WHERE ts > ?
                   GROUP BY subscriber_id
                   ORDER BY tokens_total DESC""",
                (cutoff,),
            ).fetchall()
        return [dict(r) for r in rows]

    # --- rotation state persistence ---

    def save_rotation_state(
        self, cap_key: str, cursor: int, slot_counts: dict[int, int]
    ) -> None:
        """Persist rotation state for a capabilities group."""
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO rotation_state (cap_key, cursor, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(cap_key) DO UPDATE SET cursor=excluded.cursor, updated_at=excluded.updated_at",
                (cap_key, cursor, now),
            )
            for key_id, count in slot_counts.items():
                conn.execute(
                    "INSERT INTO rotation_slot_counts (key_id, slot_count) VALUES (?, ?) "
                    "ON CONFLICT(key_id) DO UPDATE SET slot_count=excluded.slot_count",
                    (key_id, count),
                )

    def load_rotation_state(self, cap_key: str) -> tuple[int, dict[int, int]]:
        """Load rotation state for a capabilities group."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT cursor FROM rotation_state WHERE cap_key = ?",
                (cap_key,),
            ).fetchone()
            cursor = row["cursor"] if row else 0

            rows = conn.execute(
                "SELECT key_id, slot_count FROM rotation_slot_counts"
            ).fetchall()
            slot_counts = {r["key_id"]: r["slot_count"] for r in rows}

        return cursor, slot_counts

    # --- settings persistence ---

    def save_setting(self, key: str, value: object) -> None:
        """Persist a single setting as JSON."""
        import json as _json

        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, _json.dumps(value)),
            )

    def load_all_settings(self) -> dict[str, object]:
        """Load all persisted settings from the DB."""
        import json as _json

        with self._conn() as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
        result: dict[str, object] = {}
        for r in rows:
            try:
                result[r["key"]] = _json.loads(r["value"])
            except (json.JSONDecodeError, TypeError):
                result[r["key"]] = r["value"]
        return result

    # --- score and group updates ---

    def update_key_scores(
        self,
        key_id: int,
        accuracy_score: int | None = None,
        speed_score: int | None = None,
        reliability_score: int | None = None,
    ) -> bool:
        """Update a key's scoring metrics. Returns True if updated."""
        ALLOWED_COLUMNS: frozenset[str] = frozenset({
            "accuracy_score", "speed_score", "reliability_score",
        })
        updates: list[str] = []
        values: list[Any] = []
        col_map = {
            "accuracy_score": accuracy_score,
            "speed_score": speed_score,
            "reliability_score": reliability_score,
        }
        for col, val in col_map.items():
            if val is not None:
                if col not in ALLOWED_COLUMNS:
                    raise ValueError(f"Column {col!r} is not allowed in UPDATE")
                updates.append(f"{col} = ?")
                values.append(val)
        if not updates:
            return False
        values.append(key_id)
        with self._conn() as conn:
            conn.execute(
                f"UPDATE api_keys SET {', '.join(updates)} WHERE id = ?",
                values,
            )
        return True

    def update_key_group(self, key_id: int, group_name: str) -> bool:
        """Update a key's group. Returns True if updated."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE api_keys SET group_name = ? WHERE id = ?", (group_name, key_id)
            )
        return True

    def update_key_sticky(
        self,
        key_id: int,
        enabled: bool,
        ttl_hours: int = 1,
    ) -> bool:
        """Update sticky session settings for a key. Returns True."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE api_keys SET is_sticky_enabled = ?, sticky_ttl_hours = ? WHERE id = ?",
                (1 if enabled else 0, ttl_hours, key_id),
            )
        return True

    def delete_key(self, key_id: int) -> bool:
        """Delete a key permanently. Returns True if deleted."""
        with self._conn() as conn:
            result = conn.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
        return result.rowcount > 0

    def get_keys_by_group(self, group_name: str) -> list[dict[str, Any]]:
        """Return all active keys in a specific group."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM api_keys WHERE is_active = 1 AND group_name = ? ORDER BY provider",
                (group_name,),
            ).fetchall()
        return [self._decrypt_row(dict(r)) for r in rows]

    # --- sticky session tracking ---

    def get_sticky_session(self, session_id: str) -> dict[str, Any] | None:
        """Get sticky session by ID, or None if not found/expired."""
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM sticky_sessions WHERE session_id = ? AND expires_at > ?",
                (session_id, now),
            ).fetchone()
        return dict(row) if row else None

    def create_sticky_session(
        self,
        session_id: str,
        key_id: int,
        provider: str,
        model: str | None,
        ttl_hours: int = 1,
    ) -> None:
        """Create or update a sticky session with TTL."""
        expires_at = (datetime.now(UTC) + timedelta(hours=ttl_hours)).isoformat()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO sticky_sessions (session_id, key_id, provider, model, expires_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(session_id) DO UPDATE SET
                       key_id = excluded.key_id,
                       provider = excluded.provider,
                       model = excluded.model,
                       expires_at = excluded.expires_at""",
                (session_id, key_id, provider, model, expires_at),
            )

    def clear_sticky_session(self, session_id: str) -> None:
        """Remove a sticky session."""
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM sticky_sessions WHERE session_id = ?", (session_id,)
            )

    def cleanup_expired_sessions(self) -> int:
        """Remove all expired sticky sessions. Returns count removed."""
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            result = conn.execute(
                "DELETE FROM sticky_sessions WHERE expires_at <= ?",
                (now,),
            )
        return result.rowcount

    # ── Model Catalog CRUD (see FreeLLMAPI models + fallback_config tables) ─

    def ensure_fallback_config(self) -> None:
        """Ensure every enabled model has a row in fallback_config."""
        with self._conn() as conn:
            missing = conn.execute("""
                SELECT m.id FROM models m
                LEFT JOIN fallback_config f ON m.id = f.model_db_id
                WHERE f.id IS NULL AND m.enabled = 1
                ORDER BY m.intelligence_rank ASC
            """).fetchall()

            if missing:
                max_priority = conn.execute(
                    "SELECT COALESCE(MAX(priority), 0) AS mx FROM fallback_config"
                ).fetchone()["mx"]
                for i, row in enumerate(missing):
                    conn.execute(
                        "INSERT INTO fallback_config (model_db_id, priority, enabled) VALUES (?, ?, 1)",
                        (row["id"], max_priority + i + 1),
                    )

    def seed_models_from_config(self, config_path: str | None = None) -> int:
        """Seed the models table from providers.json. Returns count of new models added."""
        from pathlib import Path

        if config_path is None:
            config_path = str(Path(__file__).parent / "config" / "providers.json")

        import json

        with Path(config_path).open() as f:
            configs = json.load(f).get("providers", {})

        count = 0
        with self._conn() as conn:
            existing = conn.execute("SELECT COUNT(*) as cnt FROM models").fetchone()[
                "cnt"
            ]
            if existing > 0:
                return 0

            stmt = "INSERT OR IGNORE INTO models (platform, model_id, display_name, intelligence_rank, size_label, context_window, supports_vision, supports_tools, enabled) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)"

            for provider, cfg in configs.items():
                models_list = cfg.get("models", [])
                for m_id in models_list:
                    model_lower = m_id.lower()
                    has_vision = (
                        1
                        if any(
                            v in model_lower
                            for v in [
                                "vision",
                                "vl",
                                "vlm",
                                "multimodal",
                                "gemini-2.0-flash",
                                "gemini-1.5-flash",
                            ]
                        )
                        else 0
                    )
                    has_tools = 1
                    ctx = cfg.get("limits", {}).get("max_context_tokens", 8192)
                    if isinstance(ctx, dict):
                        ctx = 8192
                    conn.execute(
                        stmt,
                        (
                            provider,
                            m_id,
                            m_id,
                            999,
                            "Medium",
                            ctx,
                            has_vision,
                            has_tools,
                        ),
                    )
                    count += 1

            # Inline ensure_fallback_config to use same connection/transaction
            missing = conn.execute("""
                SELECT m.id FROM models m
                LEFT JOIN fallback_config f ON m.id = f.model_db_id
                WHERE f.id IS NULL AND m.enabled = 1
                ORDER BY m.intelligence_rank ASC
            """).fetchall()
            if missing:
                max_priority = conn.execute(
                    "SELECT COALESCE(MAX(priority), 0) AS mx FROM fallback_config"
                ).fetchone()["mx"]
                for i, row in enumerate(missing):
                    conn.execute(
                        "INSERT INTO fallback_config (model_db_id, priority, enabled) VALUES (?, ?, 1)",
                        (row["id"], max_priority + i + 1),
                    )
        return count

    def add_model(
        self,
        platform: str,
        model_id: str,
        context_window: int | None = None,
        supports_vision: bool = False,
        supports_tools: bool = True,
    ) -> int | None:
        ctx = context_window or 8192
        with self._conn() as conn:
            try:
                cursor = conn.execute(
                    """INSERT INTO models (platform, model_id, display_name, context_window,
                                           supports_vision, supports_tools, enabled)
                       VALUES (?, ?, ?, ?, ?, ?, 1)""",
                    (
                        platform,
                        model_id,
                        model_id,
                        ctx,
                        1 if supports_vision else 0,
                        1 if supports_tools else 0,
                    ),
                )
                self.ensure_fallback_config()
                return cursor.lastrowid
            except sqlite3.IntegrityError:
                return None

    def get_all_models(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT m.*, f.priority, f.enabled as in_chain
                FROM models m
                LEFT JOIN fallback_config f ON m.id = f.model_db_id
                ORDER BY m.intelligence_rank ASC, m.platform ASC
            """).fetchall()
            return [dict(r) for r in rows]

    def get_enabled_models(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT f.model_db_id as id, f.priority, f.enabled as chain_enabled,
                       m.platform, m.model_id, m.display_name, m.intelligence_rank,
                       m.speed_rank, m.size_label, m.context_window,
                       m.supports_vision, m.supports_tools, m.rpm_limit, m.rpd_limit,
                       m.tpm_limit, m.tpd_limit
                FROM fallback_config f
                JOIN models m ON m.id = f.model_db_id AND m.enabled = 1
                WHERE f.enabled = 1
                ORDER BY f.priority ASC
            """).fetchall()
            return [dict(r) for r in rows]

    def update_model_capabilities(
        self,
        model_id: int,
        context_window: int | None = None,
        supports_vision: bool | None = None,
        supports_tools: bool | None = None,
    ) -> bool:
        ALLOWED_COLUMNS: frozenset[str] = frozenset({
            "context_window", "supports_vision", "supports_tools",
        })
        updates: list[str] = []
        values: list[Any] = []
        col_map = {
            "context_window": context_window,
            "supports_vision": supports_vision if supports_vision is None else (1 if supports_vision else 0),
            "supports_tools": supports_tools if supports_tools is None else (1 if supports_tools else 0),
        }
        for col, val in col_map.items():
            if val is not None:
                if col not in ALLOWED_COLUMNS:
                    raise ValueError(f"Column {col!r} is not allowed in UPDATE")
                updates.append(f"{col} = ?")
                values.append(val)
        if not updates:
            return False
        values.append(model_id)
        with self._conn() as conn:
            conn.execute(f"UPDATE models SET {', '.join(updates)} WHERE id = ?", values)
        return True

    def get_models_for_key(
        self,
        provider: str,
        key_model: str | None = None,
        min_context: int | None = None,
        require_tools: bool | None = None,
        require_vision: bool | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["m.platform = ?", "m.enabled = 1"]
        params: list[Any] = [provider]

        if key_model:
            clauses.append("m.model_id = ?")
            params.append(key_model)
        if min_context is not None:
            clauses.append("(m.context_window IS NULL OR m.context_window >= ?)")
            params.append(min_context)
        if require_tools:
            clauses.append("m.supports_tools = 1")
        if require_vision:
            clauses.append("m.supports_vision = 1")

        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM models WHERE {' AND '.join(clauses)} ORDER BY m.intelligence_rank ASC",
                params,
            ).fetchall()
            return [dict(r) for r in rows]

    # --- auth methods ---

    def _hash_password(self, password: str) -> str:
        """Hash password with scrypt."""
        import hashlib
        import secrets

        salt = secrets.token_hex(16)
        key = hashlib.scrypt(
            password.encode(), salt=salt.encode(), n=2**14, r=8, p=1, dklen=64
        )
        return f"scrypt${salt}${key.hex()}"

    def _verify_password(self, password: str, stored: str) -> bool:
        """Verify password against stored hash."""
        import hashlib
        import secrets

        try:
            algo, salt, key = stored.split("$")
            new_key = hashlib.scrypt(
                password.encode(), salt=salt.encode(), n=2**14, r=8, p=1, dklen=64
            )
            return secrets.compare_digest(key, new_key.hex())
        except (ValueError, TypeError):
            return False

    def create_admin_user(self, email: str, password: str) -> bool:
        """Create first admin user. Returns True if created, False if user exists."""
        with self._conn() as conn:
            # Check if any users exist
            existing = conn.execute("SELECT id FROM users LIMIT 1").fetchone()
            if existing:
                return False
            conn.execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?)",
                (email, self._hash_password(password)),
            )
            return True

    def authenticate(self, email: str, password: str) -> str | None:
        """Authenticate user. Returns session token or None."""
        import secrets
        from datetime import datetime, timedelta, timezone

        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, password_hash FROM users WHERE email = ?", (email,)
            ).fetchone()
            if not row or not self._verify_password(password, row["password_hash"]):
                return None
            token = secrets.token_urlsafe(32)
            expires = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
            conn.execute(
                "INSERT INTO sessions (user_id, token, expires_at) VALUES (?, ?, ?)",
                (row["id"], token, expires),
            )
            return token

    def validate_session(self, token: str) -> int | None:
        """Validate session token. Returns user_id or None."""
        from datetime import datetime, timezone

        with self._conn() as conn:
            row = conn.execute(
                "SELECT user_id, expires_at FROM sessions WHERE token = ?", (token,)
            ).fetchone()
            if not row:
                return None
            if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
                conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
                return None
            return row["user_id"]

    def logout(self, token: str) -> None:
        """Invalidate session."""
        with self._conn() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
