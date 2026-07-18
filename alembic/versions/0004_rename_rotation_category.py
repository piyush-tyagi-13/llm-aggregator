"""Rename category column to cap_key in rotation_state table.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-20
"""

from __future__ import annotations
from typing import Sequence, Union

from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("rotation_state", "category", new_column_name="cap_key")


def downgrade() -> None:
    op.alter_column("rotation_state", "cap_key", new_column_name="category")
