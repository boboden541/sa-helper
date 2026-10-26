"""Путь сохранения документа ПСИ у истории (решение владельца 27.10.2026).

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("task", sa.Column("psi_path", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("task", "psi_path")
