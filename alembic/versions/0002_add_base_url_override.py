"""Add base_url_override column to api_keys.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-20
"""

from __future__ import annotations
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("api_keys", sa.Column("base_url_override", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("api_keys", "base_url_override")
