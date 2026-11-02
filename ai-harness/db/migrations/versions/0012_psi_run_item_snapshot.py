"""Psi-протокол — снапшот: item_id не должен держать FK на чеклист (02.11.2026).

Регистрация ПСИ VITRINA-1: обновление psi-чеклиста блокировалось FK
psi_run_item.item_id → checklist_item — протоколы прогонов должны переживать
пересборку чеклиста (снапшот хранит текст копией).
"""

from __future__ import annotations

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("fk_psi_run_item_item_id_checklist_item",
                       "psi_run_item", type_="foreignkey")
    op.create_foreign_key(
        "fk_psi_run_item_item_id_checklist_item", "psi_run_item",
        "checklist_item", ["item_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint("fk_psi_run_item_item_id_checklist_item",
                       "psi_run_item", type_="foreignkey")
    op.create_foreign_key(
        "fk_psi_run_item_item_id_checklist_item", "psi_run_item",
        "checklist_item", ["item_id"], ["id"])
