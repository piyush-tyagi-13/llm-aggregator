"""Create audit_log table with indexes.

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-20
"""

from __future__ import annotations
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ts", sa.Text(), nullable=False),
        sa.Column("subscriber_id", sa.Text(), nullable=False, server_default="unknown"),
        sa.Column("key_id", sa.Integer(), nullable=True),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index("idx_audit_log_ts", "audit_log", ["ts"])
    op.create_index("idx_audit_log_subscriber", "audit_log", ["subscriber_id"])


def downgrade() -> None:
    op.drop_index("idx_audit_log_subscriber", table_name="audit_log")
    op.drop_index("idx_audit_log_ts", table_name="audit_log")
    op.drop_table("audit_log")
