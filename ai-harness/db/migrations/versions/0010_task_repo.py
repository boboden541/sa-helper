"""task.repo_path — целевой репозиторий задачи в мультирепозитории проекта (ФТ владельца 29.10.2026).

Проект может быть папкой мультирепозитория (СТ «Сущность проект»); задача
указывает, в каком репозитории нужна доработка: repo_path — путь относительно
корня проекта ('tc-admin'). NULL = корень проекта (одиночный репозиторий)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("task", sa.Column("repo_path", sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column("task", "repo_path")
