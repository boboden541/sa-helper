"""Прогон: session_id SDK — для resume после сбоев «лимит ходов/таймаут» (30.10.2026).

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("task_run", sa.Column("session_id", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("task_run", "session_id")
