"""ФТ-FNR14-09: жёсткий гейт стенда на запуске — при лежащем стенде прогон
in_testing не стартует (попытки не горят), эпизод в хронику пишется один раз.
Дополняет телеметрию (ФТ-FNR14-05) жёстким слоем на демоне."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from daemon.scheduler.scheduler import Daemon

_GATE_DIR: Path | None = None


@pytest.fixture
def gate_repo(tmp_path: Path) -> Path:
    root = tmp_path / "gate-proj"
    root.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(root)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t"], cwd=root, check=True, capture_output=True
    )
    return root


def _manifest(repo: Path, url: str) -> None:
    (repo / ".harness").mkdir(exist_ok=True)
    (repo / ".harness" / "stand.json").write_text(
        json.dumps({"services": {"core": {"type": "api", "base_url": url}}}),
        encoding="utf-8",
    )


def _mk_task(eng) -> str:
    async def go():
        async with async_sessionmaker(eng)() as s:
            await s.execute(
                sa.text(
                    "TRUNCATE task, task_run, task_run_log, task_comment, chronicle "
                    "RESTART IDENTITY CASCADE"
                )
            )
            await s.execute(sa.text("UPDATE project SET next_number = 1"))
            await s.execute(
                sa.text("UPDATE project SET path = :p WHERE mnemonic='AH'"),
                {"p": str(_GATE_DIR)},
            )
            code = (
                await s.execute(
                    sa.text(
                        "INSERT INTO task (id, project_id, code, task_type_id, title, "
                        "description_md, status_key, flow_version_id, priority, author_id) "
                        "SELECT gen_random_uuid(), p.id, 'AH-1', tt.id, 'Гейт-тест', '', "
                        "'in_testing', fv.id, 'medium', u.id "
                        'FROM project p, task_type tt, flow_version fv, "user" u '
                        "WHERE p.mnemonic='AH' AND tt.key='story' "
                        "AND fv.task_type_id = tt.id AND fv.is_current AND fv.is_published "
                        "AND u.name='Алексей' RETURNING code"
                    )
                )
            ).scalar_one()
            await s.commit()
            return code

    return go()


async def test_stand_down_blocks_and_notifies_once(_test_db, gate_repo):
    from daemon.runner.agent_runner import FakeRunner

    global _GATE_DIR
    _GATE_DIR = gate_repo
    eng = create_async_engine(os.environ["TEST_DATABASE_URL"])
    try:
        _manifest(gate_repo, "http://127.0.0.1:21999")  # закрытый порт
        await _mk_task(eng)
        daemon = Daemon(async_sessionmaker(eng, expire_on_commit=False), FakeRunner())
        async with async_sessionmaker(eng)() as s:
            row = (
                await s.execute(sa.text("SELECT id, project_id FROM task WHERE code='AH-1'"))
            ).one()
            task = SimpleNamespace(id=row.id, project_id=row.project_id, repo_path=None)
            assert await daemon._stand_down(s, task) is True
            assert await daemon._stand_down(s, task) is True
            chron = (
                await s.execute(
                    sa.text("SELECT count(*) FROM chronicle WHERE task_id = :i"),
                    {"i": str(task.id)},
                )
            ).scalar_one()
        assert chron == 1, f"эпизод пишется один раз, было {chron}"
    finally:
        await eng.dispose()
        _GATE_DIR = None
