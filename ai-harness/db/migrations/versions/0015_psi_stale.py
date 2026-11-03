"""«ПСИ устарел» — контур управления изменениями требований (решение владельца 03.11).

Требования изменились (описание истории правлено, добавлена дочерняя задача)
после того, как документ ПСИ уже составлен → psi_stale=true: заметка человеку
в блоке ПСИ и сигнал ПСИ-составителю «нужна новая версия с «Что изменилось»».
Новая версия документа снимает отметку; на статусе in_testing отметка
снимает паузу между прогонами — актуализация идёт без 15-минутных простоев.
"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("task", sa.Column("psi_stale", sa.Boolean(), nullable=False,
                                    server_default=sa.text("false")))


def downgrade() -> None:
    op.drop_column("task", "psi_stale")
