"""Явное назначение скиллов из реестра инструментов на агента (вариант 4, решение владельца 27.10.2026).

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_profile", sa.Column("skills", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("agent_profile", "skills")
