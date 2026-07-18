"""Rate limit tracking for RPM/RPD/TPM/TPD with penalty decay."""

from __future__ import annotations

import time

from ..key_store import KeyStore

# Cooldown constants (matching FreeLLMAPI)
PAYMENT_REQUIRED_COOLDOWN_MS = 30 * 60 * 1000  # 30 minutes in ms


def can_make_request(
    store: KeyStore,
    platform: str,
    model_id: str,
    key_id: int,
    limits: dict[str, int | None],
) -> bool:
    """Check if a request can be made given RPM/RPD limits."""
    now_ms = int(time.time() * 1000)
    rpm = limits.get("rpm")
    rpd = limits.get("rpd")

    if rpm:
        minute_ago = now_ms - 60000
        with store._conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM rate_limit_usage WHERE platform = ? AND model_id = ? AND key_id = ? AND kind = 'request' AND created_at_ms > ?",
                (platform, model_id, key_id, minute_ago),
            ).fetchone()[0]
            if count >= rpm:
                return False

    if rpd:
        day_ago = now_ms - 24 * 60 * 60 * 1000
        with store._conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM rate_limit_usage WHERE platform = ? AND model_id = ? AND key_id = ? AND kind = 'request' AND created_at_ms > ?",
                (platform, model_id, key_id, day_ago),
            ).fetchone()[0]
            if count >= rpd:
                return False

    return True


def can_use_tokens(
    store: KeyStore,
    platform: str,
    model_id: str,
    key_id: int,
    estimated_tokens: int,
    limits: dict[str, int | None],
) -> bool:
    """Check if tokens can be used given TPM/TPD limits."""
    now_ms = int(time.time() * 1000)
    tpm = limits.get("tpm")
    tpd = limits.get("tpd")

    if tpm:
        minute_ago = now_ms - 60000
        with store._conn() as conn:
            used = (
                conn.execute(
                    "SELECT SUM(tokens) FROM rate_limit_usage WHERE platform = ? AND model_id = ? AND key_id = ? AND kind = 'tokens' AND created_at_ms > ?",
                    (platform, model_id, key_id, minute_ago),
                ).fetchone()[0]
                or 0
            )
            if used + estimated_tokens > tpm:
                return False

    if tpd:
        day_ago = now_ms - 24 * 60 * 60 * 1000
        with store._conn() as conn:
            used = (
                conn.execute(
                    "SELECT SUM(tokens) FROM rate_limit_usage WHERE platform = ? AND model_id = ? AND key_id = ? AND kind = 'tokens' AND created_at_ms > ?",
                    (platform, model_id, key_id, day_ago),
                ).fetchone()[0]
                or 0
            )
            if used + estimated_tokens > tpd:
                return False

    return True


def is_on_cooldown(store: KeyStore, platform: str, model_id: str, key_id: int) -> bool:
    """Check if a key is currently on cooldown for a model."""
    now_ms = int(time.time() * 1000)
    with store._conn() as conn:
        row = conn.execute(
            "SELECT expires_at_ms FROM rate_limit_cooldowns WHERE platform = ? AND model_id = ? AND key_id = ?",
            (platform, model_id, key_id),
        ).fetchone()
        if row and row[0] > now_ms:
            return True
    return False


def can_use_provider(store: KeyStore, platform: str, key_id: int) -> bool:
    """Check if provider key is active and healthy."""
    with store._conn() as conn:
        row = conn.execute(
            "SELECT status, enabled FROM api_keys WHERE id = ? AND platform = ?",
            (key_id, platform),
        ).fetchone()
        if not row:
            return False
        status, enabled = row
        return enabled and status in ("healthy", "unknown")


def record_request(
    store: KeyStore,
    platform: str,
    model_id: str,
    key_id: int,
    kind: str = "request",
) -> None:
    """Record a request or token usage."""
    now_ms = int(time.time() * 1000)
    now_iso = time.strftime("%Y-%m-%d %H:%M:%S")
    with store._conn() as conn:
        conn.execute(
            "INSERT INTO rate_limit_usage (platform, model_id, key_id, kind, tokens, created_at_ms, created_at) VALUES (?, ?, ?, ?, 0, ?, ?)",
            (platform, model_id, key_id, kind, now_ms, now_iso),
        )


def set_cooldown(
    store: KeyStore,
    platform: str,
    model_id: str,
    key_id: int,
    expires_at_ms: int,
) -> None:
    """Set a cooldown for a platform/model/key combination."""
    now_iso = time.strftime("%Y-%m-%d %H:%M:%S")
    with store._conn() as conn:
        conn.execute(
            """INSERT INTO rate_limit_cooldowns (platform, model_id, key_id, expires_at_ms, created_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(platform, model_id, key_id) DO UPDATE SET expires_at_ms = excluded.expires_at_ms""",
            (platform, model_id, key_id, expires_at_ms, now_iso),
        )


def get_cooldown_duration_for_limit(
    platform: str,
    model_id: str,
    key_id: int,
    limits: dict[str, int | None],
) -> int:
    """Calculate cooldown duration based on limits (fallback when no Retry-After)."""
    rpd = limits.get("rpd")
    if rpd:
        return 6 * 60 * 60 * 1000  # 6 hours
    return 30 * 60 * 1000  # 30 minutes
