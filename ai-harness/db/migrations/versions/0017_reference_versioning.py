"""Версионирование эталона постановки (решение владельца 03.11.2026).

Полная замена булева psi_stale: task.ref_version растёт при каждом изменении
содержания эталона (описание задачи; для истории — ещё состав и постановки
детей), task.ref_hash — sha256 описания из БД harness. Чеклист.source_ref_version —
«какой версией эталона план заверен». План устарел ⟺ stamp < ref_version:
факт вычисляется, а не угадывается агентом.
"""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("task", sa.Column("ref_version", sa.Integer(), nullable=False,
                                    server_default="1"))
    op.add_column("task", sa.Column("ref_hash", sa.String(64), nullable=True))
    op.add_column("checklist", sa.Column("source_ref_version", sa.Integer(), nullable=True))
    op.execute("UPDATE checklist SET source_ref_version = 1")
    op.drop_column("task", "psi_stale")


def downgrade() -> None:
    op.add_column("task", sa.Column("psi_stale", sa.Boolean(), nullable=False,
                                    server_default="false"))
    op.drop_column("checklist", "source_ref_version")
    op.drop_column("task", "ref_hash")
    op.drop_column("task", "ref_version")
