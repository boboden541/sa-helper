"""Добавление полей фиксации коммитов ветки и метаданных стенда (ФТ-FNR14-03, ФТ-FNR14-05)."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Фиксация коммитов и статистики в ветке задачи
    op.add_column("task_branch", sa.Column("head_commit", sa.String(64), nullable=True))
    op.add_column("task_branch", sa.Column("merge_commit", sa.String(64), nullable=True))
    op.add_column("task_branch", sa.Column("diff_stats", pg.JSONB(), nullable=True))

    # 2. Метаданные валидности стенда у задачи/истории
    op.add_column("task", sa.Column("stand_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("task", sa.Column("stand_health_status", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("task", "stand_health_status")
    op.drop_column("task", "stand_verified_at")
    op.drop_column("task_branch", "diff_stats")
    op.drop_column("task_branch", "merge_commit")
    op.drop_column("task_branch", "head_commit")
