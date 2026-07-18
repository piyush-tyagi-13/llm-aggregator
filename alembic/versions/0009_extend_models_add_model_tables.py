"""Extend models table with provider-model fields, add key_model_access & provider_catalog_sources.

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-24
"""

from __future__ import annotations
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    # ── Extend models table ──────────────────────────────────────────────────
    op.add_column("models", sa.Column("max_input_tokens", sa.Integer(), nullable=True))
    op.add_column("models", sa.Column("max_output_tokens", sa.Integer(), nullable=True))
    op.add_column(
        "models",
        sa.Column(
            "supports_streaming", sa.Integer(), nullable=False, server_default="1"
        ),
    )
    op.add_column(
        "models",
        sa.Column(
            "supports_function_calling",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "models", sa.Column("is_free", sa.Integer(), nullable=False, server_default="1")
    )
    op.add_column(
        "models",
        sa.Column("is_deprecated", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "models", sa.Column("tier", sa.Integer(), nullable=False, server_default="4")
    )
    op.add_column("models", sa.Column("owner", sa.Text(), nullable=True))
    op.add_column("models", sa.Column("raw_metadata", sa.Text(), nullable=True))
    op.add_column(
        "models",
        sa.Column(
            "last_updated_at",
            sa.Text(),
            nullable=False,
            server_default=sa.text("datetime('now')"),
        ),
    )
    op.add_column("models", sa.Column("last_checked_at", sa.Text(), nullable=True))

    # ── key_model_access ──────────────────────────────────────────────────────
    op.create_table(
        "key_model_access",
        sa.Column("key_id", sa.Integer(), sa.ForeignKey("api_keys.id"), nullable=False),
        sa.Column(
            "model_db_id", sa.Integer(), sa.ForeignKey("models.id"), nullable=False
        ),
        sa.Column("is_active", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("key_id", "model_db_id"),
    )

    # ── provider_catalog_sources ──────────────────────────────────────────────
    op.create_table(
        "provider_catalog_sources",
        sa.Column("provider", sa.Text(), primary_key=True),
        sa.Column("models_endpoint", sa.Text(), nullable=True),
        sa.Column("requires_api_key", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("free_detection_method", sa.Text(), nullable=True),
        sa.Column("last_sync_at", sa.Text(), nullable=True),
        sa.Column("sync_status", sa.Text(), nullable=False, server_default="pending"),
    )

    # ── Indexes ───────────────────────────────────────────────────────────────
    op.create_index("idx_models_tier", "models", ["tier"])
    op.create_index("idx_models_free", "models", ["is_free"])
    op.create_index("idx_models_context", "models", ["context_window"])
    op.create_index("idx_key_model_access_key", "key_model_access", ["key_id"])
    op.create_index("idx_key_model_access_model", "key_model_access", ["model_db_id"])


def downgrade() -> None:
    op.drop_index("idx_key_model_access_model", table_name="key_model_access")
    op.drop_index("idx_key_model_access_key", table_name="key_model_access")
    op.drop_index("idx_models_context", table_name="models")
    op.drop_index("idx_models_free", table_name="models")
    op.drop_index("idx_models_tier", table_name="models")

    op.drop_table("provider_catalog_sources")
    op.drop_table("key_model_access")

    op.drop_column("models", "last_checked_at")
    op.drop_column("models", "last_updated_at")
    op.drop_column("models", "raw_metadata")
    op.drop_column("models", "owner")
    op.drop_column("models", "tier")
    op.drop_column("models", "is_deprecated")
    op.drop_column("models", "is_free")
    op.drop_column("models", "supports_function_calling")
    op.drop_column("models", "supports_streaming")
    op.drop_column("models", "max_output_tokens")
    op.drop_column("models", "max_input_tokens")
