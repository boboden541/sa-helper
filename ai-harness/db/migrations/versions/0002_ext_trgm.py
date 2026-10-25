"""pg_trgm: триграммный нечёткий поиск (НФТ-ah-1) по названиям задач и тегам.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE INDEX IF NOT EXISTS idx_task_title_trgm ON task USING gin (title gin_trgm_ops)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_tag_label_trgm ON tag USING gin (label gin_trgm_ops)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_task_title_trgm")
    op.execute("DROP INDEX IF EXISTS idx_tag_label_trgm")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
