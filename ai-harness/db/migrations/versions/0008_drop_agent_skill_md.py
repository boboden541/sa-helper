"""Удаление свободного текста у агента: методологии — скиллы, персона — имя+роль (решение владельца 27.10.2026).

Кастомные инструкции перед дропом выгружаются в архив инструментов
(<agents.tools_dir>/_archive/agent-instructions/).

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _archive_custom_instructions() -> None:
    """Шаг 3 решения владельца: чужие тексты не теряются — уходят в архив файлов."""
    conn = op.get_bind()
    rows = conn.execute(sa.text(
        'SELECT u.name, ap.skill_md FROM agent_profile ap '
        'JOIN "user" u ON u.id = ap.user_id '
        "WHERE ap.skill_md IS NOT NULL AND btrim(ap.skill_md) <> ''")).fetchall()
    if not rows:
        return
    tools = conn.execute(sa.text(
        "SELECT value FROM app_setting WHERE key = 'agents.tools_dir'")).scalar_one_or_none()
    if not tools or not tools.strip():
        print("0008: agents.tools_dir не задан — инструкции не архивированы (колонка удаляется)")
        return
    from infrastructure.paths import host_to_container

    base = host_to_container(tools.rstrip("/") + "/_archive/agent-instructions")
    try:
        os.makedirs(base, exist_ok=True)
    except OSError as err:
        print(f"0008: архив инструкций недоступен ({err}) — колонка удаляется без архива")
        return
    taken = set(os.listdir(base))
    for name, text in rows:
        slug = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name).strip().replace(" ", "_") or "agent"
        fname = slug + ".md"
        while fname in taken:
            fname = slug + "_" + uuid.uuid4().hex[:6] + ".md"
        taken.add(fname)
        with open(os.path.join(base, fname), "w", encoding="utf-8") as f:
            f.write(f"# Инструкция агента «{name}»\n\n"
                    "Заархивирована при удалении поля skill_md (решение владельца 27.10.2026):\n"
                    "методологии переехали в скиллы реестра, персона агента — роль.\n\n" + text + "\n")
    print(f"0008: заархивировано инструкций: {len(rows)} → {base}")


def upgrade() -> None:
    _archive_custom_instructions()
    op.drop_column("agent_profile", "skill_md")


def downgrade() -> None:
    # данные не восстанавливаются (архив — файлами в папке инструментов)
    op.add_column("agent_profile", sa.Column("skill_md", sa.Text(), nullable=True))
