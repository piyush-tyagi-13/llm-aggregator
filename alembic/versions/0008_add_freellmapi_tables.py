"""Add FreeLLMAPI tables for full model catalog and analytics.

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-22
"""

from __future__ import annotations
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    # ── Models table ───────────────────────────────────────────────────────────
    # Stores all available models with their limits and capabilities
    op.create_table(
        "models",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("intelligence_rank", sa.Integer(), nullable=False),
        sa.Column("speed_rank", sa.Integer(), nullable=False),
        sa.Column("size_label", sa.Text(), nullable=False, server_default=""),
        sa.Column("monthly_token_budget", sa.Text(), nullable=False, server_default=""),
        sa.Column("rpm_limit", sa.Integer(), nullable=True),
        sa.Column("rpd_limit", sa.Integer(), nullable=True),
        sa.Column("tpm_limit", sa.Integer(), nullable=True),
        sa.Column("tpd_limit", sa.Integer(), nullable=True),
        sa.Column("context_window", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("supports_vision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("supports_tools", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("platform", "model_id", name="uq_platform_model"),
    )

    # ── Fallback config ───────────────────────────────────────────────────────
    # Per-model priority in the routing chain
    op.create_table(
        "fallback_config",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "model_db_id", sa.Integer(), sa.ForeignKey("models.id"), nullable=False
        ),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("model_db_id", name="uq_model_fallback"),
    )

    # ── Profiles ───────────────────────────────────────────────────────────────
    # Named routing profiles (alternative fallback chains)
    op.create_table(
        "profiles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("emoji", sa.Text(), nullable=False, server_default=""),
        sa.Column("color", sa.Text(), nullable=False, server_default="#6366f1"),
        sa.Column("type", sa.Text(), nullable=False, server_default="custom"),
        sa.Column("is_favorite", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("auto_sort", sa.Text(), nullable=True),
        sa.Column("layout_config", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.Text(),
            nullable=False,
            server_default=sa.text("datetime('now')"),
        ),
    )

    # ── Profile models ───────────────────────────────────────────────────────
    # Models within a profile with their own priority
    op.create_table(
        "profile_models",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "profile_id", sa.Integer(), sa.ForeignKey("profiles.id"), nullable=False
        ),
        sa.Column(
            "model_db_id", sa.Integer(), sa.ForeignKey("models.id"), nullable=False
        ),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("profile_id", "model_db_id", name="uq_profile_model"),
    )

    # ── Requests table ─────────────────────────────────────────────────────────
    # For analytics: per-request logging
    op.create_table(
        "requests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("key_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ttfb_ms", sa.Integer(), nullable=True),
        sa.Column("requested_model", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.Text(),
            nullable=False,
            server_default=sa.text("datetime('now')"),
        ),
        sa.Column("request_type", sa.Text(), nullable=False, server_default="chat"),
    )

    # ── Rate limit usage ───────────────────────────────────────────────────────
    op.create_table(
        "rate_limit_usage",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("key_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.Text(),
            nullable=False,
            server_default=sa.text("datetime('now')"),
        ),
    )

    # ── Rate limit cooldowns ───────────────────────────────────────────────────
    op.create_table(
        "rate_limit_cooldowns",
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("key_id", sa.Integer(), nullable=False),
        sa.Column("expires_at_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.Text(),
            nullable=False,
            server_default=sa.text("datetime('now')"),
        ),
        sa.PrimaryKeyConstraint("platform", "model_id", "key_id"),
    )

    # ── Provider quota state ───────────────────────────────────────────────────
    op.create_table(
        "provider_quota_state",
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("key_id", sa.Integer(), nullable=False),
        sa.Column("quota_pool_key", sa.Text(), nullable=False),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("limit_value", sa.Integer(), nullable=True),
        sa.Column("remaining_value", sa.Integer(), nullable=True),
        sa.Column("reset_at", sa.Text(), nullable=True),
        sa.Column(
            "reset_strategy", sa.Text(), nullable=False, server_default="unknown"
        ),
        sa.Column("source", sa.Text(), nullable=False, server_default="probe"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "observed_at",
            sa.Text(),
            nullable=False,
            server_default=sa.text("datetime('now')"),
        ),
        sa.Column(
            "updated_at",
            sa.Text(),
            nullable=False,
            server_default=sa.text("datetime('now')"),
        ),
        sa.PrimaryKeyConstraint("platform", "key_id", "quota_pool_key", "metric"),
    )

    # ── Provider quota observations ─────────────────────────────────────────────
    op.create_table(
        "provider_quota_observations",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("key_id", sa.Integer(), nullable=False),
        sa.Column("provider_account_id", sa.Text(), nullable=True),
        sa.Column("model_id", sa.Text(), nullable=True),
        sa.Column("quota_pool_key", sa.Text(), nullable=False),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("limit_value", sa.Integer(), nullable=True),
        sa.Column("remaining_value", sa.Integer(), nullable=True),
        sa.Column("reset_at", sa.Text(), nullable=True),
        sa.Column("retry_after_ms", sa.Integer(), nullable=True),
        sa.Column(
            "reset_strategy", sa.Text(), nullable=False, server_default="unknown"
        ),
        sa.Column("source", sa.Text(), nullable=False, server_default="probe"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("raw_json", sa.Text(), nullable=True),
        sa.Column("endpoint", sa.Text(), nullable=True),
        sa.Column(
            "observed_at",
            sa.Text(),
            nullable=False,
            server_default=sa.text("datetime('now')"),
        ),
        sa.Column(
            "created_at",
            sa.Text(),
            nullable=False,
            server_default=sa.text("datetime('now')"),
        ),
    )

    # ── Embedding models ───────────────────────────────────────────────────────
    op.create_table(
        "embedding_models",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("family", sa.Text(), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("max_input_tokens", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quota_label", sa.Text(), nullable=True),
    )

    # ── Settings table (generic key/value) ──────────────────────────────────────
    op.create_table(
        "settings",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
    )

    # ── Indexes ────────────────────────────────────────────────────────────────
    op.create_index("idx_models_platform", "models", ["platform"])
    op.create_index("idx_models_enabled", "models", ["enabled"])
    op.create_index("idx_fallback_config_priority", "fallback_config", ["priority"])
    op.create_index("idx_requests_created_at", "requests", ["created_at"])
    op.create_index("idx_requests_platform", "requests", ["platform"])
    op.create_index("idx_requests_key_id", "requests", ["key_id"])
    op.create_index(
        "idx_rate_limit_usage_lookup",
        "rate_limit_usage",
        ["platform", "model_id", "key_id", "kind", "created_at_ms"],
    )
    op.create_index(
        "idx_rate_limit_cooldowns_expires", "rate_limit_cooldowns", ["expires_at_ms"]
    )
    op.create_index(
        "idx_provider_quota_state_platform",
        "provider_quota_state",
        ["platform", "key_id", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_provider_quota_state_platform", table_name="provider_quota_state"
    )
    op.drop_index("idx_rate_limit_cooldowns_expires", table_name="rate_limit_cooldowns")
    op.drop_index("idx_rate_limit_usage_lookup", table_name="rate_limit_usage")
    op.drop_index("idx_requests_key_id", table_name="requests")
    op.drop_index("idx_requests_platform", table_name="requests")
    op.drop_index("idx_requests_created_at", table_name="requests")
    op.drop_index("idx_fallback_config_priority", table_name="fallback_config")
    op.drop_index("idx_models_enabled", table_name="models")
    op.drop_index("idx_models_platform", table_name="models")

    op.drop_table("settings")
    op.drop_table("embedding_models")
    op.drop_table("provider_quota_observations")
    op.drop_table("provider_quota_state")
    op.drop_table("rate_limit_cooldowns")
    op.drop_table("rate_limit_usage")
    op.drop_table("requests")
    op.drop_table("profile_models")
    op.drop_table("profiles")
    op.drop_table("fallback_config")
    op.drop_table("models")
