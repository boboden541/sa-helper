"""Коды причин прогонов и намерения Eve в БД.

1) task_run.reason_code — машиночитаемый код исхода/отказа прогона
   (timeout_work, turns_limit, soft_turns, no_report,
   checklist_not_closed…). До этого планировщик распознавал ситуации
   подстроками в detail («чек-лист», «Мягкий лимит ходов»,
   «Reached maximum number of turns») — смена формулировки в раннере
   молча меняла семантику исхода (анализ 03.11.2026).
2) eve_intent — намерения «намерение → да» чата Eve жили в памяти
   процесса (_INTENTS): рестарт backend терял ожидающие подтверждения,
   второй uvicorn-воркер их не видел.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("task_run", sa.Column("reason_code", sa.String(32), nullable=True))
    op.create_table(
        "eve_intent",
        sa.Column("user_id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("eve_intent")
    op.drop_column("task_run", "reason_code")
