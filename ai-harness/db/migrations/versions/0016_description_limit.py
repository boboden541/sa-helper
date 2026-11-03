"""Лимит описания 150 000 (решение владельца 03.11.2026, было 20 000).

Инцидент VITRINA-1: полная постановка СТ-документа (77 854 симв.) не
помещалась в поле — обходной путь «полный текст в хронике». Проверка
_ck_task_desc_len поднимается синхронно с валидатором.
"""

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_task_desc_len", "task", type_="check")
    op.create_check_constraint("ck_task_desc_len", "task",
                               "char_length(description_md) <= 150000")


def downgrade() -> None:
    op.drop_constraint("ck_task_desc_len", "task", type_="check")
    op.create_check_constraint("ck_task_desc_len", "task",
                               "char_length(description_md) <= 20000")
