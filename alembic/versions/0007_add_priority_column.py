"""Add priority column for key ordering.

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-22
"""

from __future__ import annotations
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("idx_api_keys_priority", "api_keys", ["priority"])


def downgrade() -> None:
    op.drop_index("idx_api_keys_priority", table_name="api_keys")
    op.drop_column("api_keys", "priority")
