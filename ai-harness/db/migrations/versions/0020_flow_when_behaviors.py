"""ФНР-16: семантика процессов в данных — when на рёбрах, behaviors/kind на статусах."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ФТ-FNR16-02: условия автопереходов (конъюнкция имён предикатов)
    op.add_column(
        "flow_transition",
        sa.Column("when", pg.JSONB(), nullable=False, server_default="[]"),
    )
    # ФТ-FNR16-03: флаги поведения и класс стадии на статусах
    op.add_column(
        "flow_status",
        sa.Column("behaviors", pg.JSONB(), nullable=False, server_default="[]"),
    )
    op.add_column("flow_status", sa.Column("kind", sa.String(24), nullable=True))
    # порядок стадии = порядок статуса в версии (детерминированный приоритет зеркал)
    op.add_column("flow_status", sa.Column("position", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("flow_status", "position")
    op.drop_column("flow_status", "kind")
    op.drop_column("flow_status", "behaviors")
    op.drop_column("flow_transition", "when")
