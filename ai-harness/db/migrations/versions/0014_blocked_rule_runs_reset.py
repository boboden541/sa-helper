"""Правило автоблокировки + сброс счётчика прогонов при выходе из blocked.

Инцидент VITRINA-1 (ночь 02→03.11.2026): история, заблокированная по своей
вине (исчерпание попыток/лимит прогонов), воскресала правилом M2 «из blocked»
каждый тик — blocked → qa ready → in testing → blocked. Гейт: M2 поднимает
историю из blocked только когда блокер был «детский» (M5).

Ручной выход из blocked не сбрасывал счётчик прогонов (daemon.max_runs_per_task
считал все прогоны задачи подряд) — владелец физически не мог вернуть задачу
в работу: runs_reset_at фиксирует момент «человек разобрался».
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("task", sa.Column("blocked_rule", sa.String(16), nullable=True))
    op.add_column("task", sa.Column("runs_reset_at", sa.DateTime(timezone=True),
                                    nullable=True))


def downgrade() -> None:
    op.drop_column("task", "runs_reset_at")
    op.drop_column("task", "blocked_rule")
