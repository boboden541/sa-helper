"""AC-4.1.1.1: миграции применяются на чистой БД, откатываются, повтор идемпотентен."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import text as sa_text
from sqlalchemy.exc import IntegrityError

ROOT = Path(__file__).resolve().parents[2]
VENV = ROOT / ".venv" / "bin"
MIG_DB = "ai_harness_mig_test"


async def _pg_exec(sql: str) -> None:
    import asyncpg

    conn = await asyncpg.connect("postgresql://harness:harness@localhost:5433/ai_harness")
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


@pytest.mark.skipif(not (VENV / "alembic").exists(), reason="alembic не в venv")
async def test_upgrade_downgrade_reupgrade():
    await _pg_exec(f'DROP DATABASE IF EXISTS "{MIG_DB}"')
    await _pg_exec(f'CREATE DATABASE "{MIG_DB}"')
    env = {**os.environ,
           "TEST_DATABASE_URL": f"postgresql+asyncpg://harness:harness@localhost:5433/{MIG_DB}"}

    def run(*args):
        return subprocess.run([str(VENV / "alembic"), *args], cwd=ROOT, env=env,
                              capture_output=True, text=True)

    up1 = run("upgrade", "head")
    assert up1.returncode == 0, up1.stderr
    up2 = run("upgrade", "head")
    assert up2.returncode == 0 and "Running upgrade" not in up2.stdout, up2.stdout
    down = run("downgrade", "base")
    assert down.returncode == 0, down.stderr
    up3 = run("upgrade", "head")
    assert up3.returncode == 0, up3.stderr

    await _pg_exec(f'DROP DATABASE IF EXISTS "{MIG_DB}"')


async def test_mnemonic_of_deleted_project_not_reusable(session):
    """AC-4.1.1.3: мнемоника удалённого проекта отклоняется (dead_mnemonic)."""
    from repository.models import DeadMnemonic, Project

    await session.execute(sa.text(
        "INSERT INTO project (id, name, mnemonic, path) "
        "VALUES (gen_random_uuid(), 'Тестовый', 'ZZ', '/tmp') "
        "ON CONFLICT DO NOTHING"
    ))
    await session.execute(sa.insert(DeadMnemonic).values(mnemonic="ZZ"))
    await session.commit()
    with pytest.raises(IntegrityError):
        dup = Project(name="Дубль", mnemonic="ZZ", path="/tmp")
        session.add(dup)
        await session.flush()
    await session.rollback()


async def test_check_constraints_reject_bad_values(session):
    """AC-4.1.1.4: недопустимые priority отклоняются ограничением."""
    from repository.models import Task

    project_id = (await session.execute(
        sa_text("SELECT id FROM project WHERE mnemonic='AH'")
    )).scalar_one()
    type_id = (await session.execute(
        sa_text("SELECT id FROM task_type WHERE key='common_task'")
    )).scalar_one()
    fv_id = (await session.execute(
        sa_text("SELECT id FROM flow_version WHERE is_current AND is_published LIMIT 1")
    )).scalar_one()
    author = (await session.execute(
        sa_text("SELECT id FROM \"user\" WHERE name='Алексей'")
    )).scalar_one()

    bad = Task(project_id=project_id, code="AH-999", task_type_id=type_id,
               title="Плохой приоритет", description_md="", status_key="todo",
               flow_version_id=fv_id, priority="urgent", author_id=author)
    session.add(bad)
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()
