"""Initial schema - track version 1 of llm-apipool DB.

Revision ID: 0001
Revises:
Create Date: 2026-06-20
"""

from __future__ import annotations
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # api_keys table - initial schema (without model, capabilities, base_url_override)
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("api_key", sa.Text(), nullable=False),
        sa.Column("extra_params", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("is_active", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "tokens_used_today", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "tokens_used_month", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("requests_today", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("requests_month", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_429_at", sa.Text(), nullable=True),
        sa.Column("cooldown_until", sa.Text(), nullable=True),
        sa.Column("daily_reset_date", sa.Text(), nullable=True),
        sa.Column("monthly_reset_month", sa.Text(), nullable=True),
        sa.Column(
            "added_at",
            sa.Text(),
            nullable=False,
            server_default=sa.text("datetime('now')"),
        ),
        sa.Column("last_used_at", sa.Text(), nullable=True),
        sa.UniqueConstraint("provider", "api_key", name="uq_provider_api_key"),
    )

    # rotation_state table - initial schema (with "category" column, not "cap_key")
    op.create_table(
        "rotation_state",
        sa.Column("category", sa.Text(), primary_key=True),
        sa.Column("cursor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.Text(),
            nullable=True,
            server_default=sa.text("datetime('now')"),
        ),
    )

    # rotation_slot_counts table
    op.create_table(
        "rotation_slot_counts",
        sa.Column("key_id", sa.Integer(), primary_key=True),
        sa.Column("slot_count", sa.Integer(), nullable=False, server_default="0"),
    )

    # Initial indexes
    op.create_index("idx_api_keys_provider", "api_keys", ["provider"])
    op.create_index("idx_api_keys_active", "api_keys", ["is_active"])
    op.create_index("idx_api_keys_cooldown", "api_keys", ["cooldown_until"])
    op.create_index("idx_api_keys_requests_today", "api_keys", ["requests_today"])
    op.create_index("idx_rotation_state_cap_key", "rotation_state", ["category"])


def downgrade() -> None:
    op.drop_index("idx_rotation_state_cap_key", table_name="rotation_state")
    op.drop_index("idx_api_keys_requests_today", table_name="api_keys")
    op.drop_index("idx_api_keys_cooldown", table_name="api_keys")
    op.drop_index("idx_api_keys_active", table_name="api_keys")
    op.drop_index("idx_api_keys_provider", table_name="api_keys")
    op.drop_table("rotation_slot_counts")
    op.drop_table("rotation_state")
    op.drop_table("api_keys")
