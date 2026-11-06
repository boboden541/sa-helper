"""ФНР-15: карта покрытия «пункт ПСИ ↔ задача», признак переноса и ревизия менеджера."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Карта покрытия: задача, которую верифицирует пункт (ФТ-FNR15-01)
    op.add_column(
        "checklist_item",
        sa.Column("linked_task_id", pg.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_checklist_item_linked_task",
        "checklist_item",
        "task",
        ["linked_task_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_checklist_item_linked_task", "checklist_item", ["linked_task_id"])

    # 2. Признак механического переноса (ФТ-FNR15-03)
    op.add_column(
        "checklist_item",
        sa.Column("carried_from_version", sa.Integer(), nullable=True),
    )

    # 3. Ревизия «ПСИ-редактора» (ФТ-FNR15-08): номер одобренной версии + состояние
    op.add_column("checklist", sa.Column("manager_review_version", sa.Integer(), nullable=True))
    op.add_column("checklist", sa.Column("manager_review_state", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("checklist", "manager_review_state")
    op.drop_column("checklist", "manager_review_version")
    op.drop_column("checklist_item", "carried_from_version")
    op.drop_index("ix_checklist_item_linked_task", table_name="checklist_item")
    op.drop_constraint("fk_checklist_item_linked_task", "checklist_item", type_="foreignkey")
    op.drop_column("checklist_item", "linked_task_id")
