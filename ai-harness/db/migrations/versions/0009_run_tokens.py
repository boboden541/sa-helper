"""Токены прогона: task_run хранит расход по каждому ходу агента (решение владельца 27.10.2026).

Ревизия 0009: input_tokens / output_tokens / cache_tokens — накопительно за прогон;
раннер обновляет строку абсолютными значениями на каждом ходе SDK (идемпотентно).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for col in ("input_tokens", "output_tokens", "cache_tokens"):
        op.add_column("task_run",
                      sa.Column(col, sa.BigInteger(), nullable=False, server_default="0"))


def downgrade() -> None:
    for col in ("cache_tokens", "output_tokens", "input_tokens"):
        op.drop_column("task_run", col)
