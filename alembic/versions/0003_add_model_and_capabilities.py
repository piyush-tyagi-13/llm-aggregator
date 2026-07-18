"""Add model and capabilities columns to api_keys table.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-20
"""

from __future__ import annotations
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("api_keys", sa.Column("model", sa.Text(), nullable=True))
    op.add_column(
        "api_keys",
        sa.Column(
            "capabilities",
            sa.Text(),
            nullable=False,
            server_default='["general_purpose"]',
        ),
    )


def downgrade() -> None:
    op.drop_column("api_keys", "capabilities")
    op.drop_column("api_keys", "model")
