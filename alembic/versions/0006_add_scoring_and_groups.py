"""Add scoring fields and group support for web dashboard.

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-22
"""

from __future__ import annotations
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add scoring and group columns to api_keys table
    op.add_column("api_keys", sa.Column("context_size", sa.Integer(), nullable=True))
    op.add_column(
        "api_keys",
        sa.Column("accuracy_score", sa.Integer(), nullable=False, server_default="50"),
    )
    op.add_column(
        "api_keys",
        sa.Column("speed_score", sa.Integer(), nullable=False, server_default="50"),
    )
    op.add_column(
        "api_keys",
        sa.Column(
            "reliability_score", sa.Integer(), nullable=False, server_default="50"
        ),
    )
    op.add_column(
        "api_keys",
        sa.Column("group_name", sa.Text(), nullable=False, server_default="default"),
    )
    op.add_column(
        "api_keys",
        sa.Column(
            "is_sticky_enabled", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "api_keys",
        sa.Column("sticky_ttl_hours", sa.Integer(), nullable=False, server_default="1"),
    )

    # Add indexes for group_name and sticky sessions
    op.create_index("idx_api_keys_group", "api_keys", ["group_name"])
    op.create_index("idx_api_keys_sticky", "api_keys", ["is_sticky_enabled"])


def downgrade() -> None:
    op.drop_index("idx_api_keys_sticky", table_name="api_keys")
    op.drop_index("idx_api_keys_group", table_name="api_keys")
    op.drop_column("api_keys", "sticky_ttl_hours")
    op.drop_column("api_keys", "is_sticky_enabled")
    op.drop_column("api_keys", "group_name")
    op.drop_column("api_keys", "reliability_score")
    op.drop_column("api_keys", "speed_score")
    op.drop_column("api_keys", "accuracy_score")
    op.drop_column("api_keys", "context_size")
