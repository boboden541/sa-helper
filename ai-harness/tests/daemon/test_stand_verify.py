"""Телеметрия стенда (ФТ-FNR14-05; фикс анализа 06.11.2026): перед стартом
прогона демон опрашивает сервисы манифеста .harness/stand.json и пишет
task.stand_verified_at / stand_health_status (раньше колонки были мёртвыми)."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
def stand_repo(tmp_path: Path) -> Path:
    root = tmp_path / "stand-proj"
    root.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(root)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t"], cwd=root, check=True, capture_output=True
    )
    (root / "README.md").write_text("demo\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "init"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return root


async def _stand_row(_test_db, project_dir: Path | None) -> tuple:
    """Прогон с FakeRunner (отчёт provider_unreachable — путь без побочных
    эффектов): до runner.run демон обязан вызвать _verify_stand."""
    from daemon.runner.agent_runner import FakeRunner, RunReport
    from daemon.scheduler.scheduler import Daemon

    eng = create_async_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with async_sessionmaker(eng)() as s:
            await s.execute(
                sa.text(
                    "TRUNCATE task, task_run, task_run_log, task_comment, chronicle "
                    "RESTART IDENTITY CASCADE"
                )
            )
            await s.execute(sa.text("UPDATE project SET next_number = 1"))
            if project_dir is not None:
                await s.execute(
                    sa.text("UPDATE project SET path = :p WHERE mnemonic='AH'"),
                    {"p": str(project_dir)},
                )
            code = (
                await s.execute(
                    sa.text(
                        "INSERT INTO task (id, project_id, code, task_type_id, title, "
                        "description_md, status_key, flow_version_id, priority, author_id, "
                        "retry_count) "
                        "SELECT gen_random_uuid(), p.id, 'AH-' || p.next_number, tt.id, "
                        "'Стенд-тест', '', 'in_progress', fv.id, 'medium', u.id, 3 "
                        'FROM project p, task_type tt, flow_version fv, "user" u '
                        "WHERE p.mnemonic='AH' AND tt.key='common_task' "
                        "AND fv.task_type_id = tt.id AND fv.is_current AND fv.is_published "
                        "AND u.name='Алексей' RETURNING code"
                    )
                )
            ).scalar_one()
            agent = (
                await s.execute(sa.text("SELECT id FROM \"user\" WHERE name='Разработчик'"))
            ).scalar_one()
            run = (
                await s.execute(
                    sa.text(
                        "INSERT INTO task_run (id, task_id, agent_id, status_key, attempt_no) "
                        "VALUES (gen_random_uuid(), "
                        "(SELECT id FROM task WHERE code='AH-1'), :a, 'in_progress', 1) "
                        "RETURNING id"
                    ),
                    {"a": str(agent)},
                )
            ).scalar_one()
            await s.commit()
        daemon = Daemon(async_sessionmaker(eng, expire_on_commit=False), FakeRunner())

        def script(req):
            return RunReport(
                status="failed",
                summary_md="сбой сети",
                outcome_code="provider_unreachable",
            )

        daemon.runner = FakeRunner(script=script)
        await daemon._run_task(code, str(agent), "in_progress", {}, str(run))

        async with async_sessionmaker(eng)() as s:
            row = (
                await s.execute(
                    sa.text(
                        "SELECT stand_verified_at, stand_health_status FROM task WHERE code='AH-1'"
                    )
                )
            ).one()
        return row
    finally:
        await eng.dispose()


async def test_stand_down_reported(_test_db, stand_repo):
    """Сервис манифеста на закрытом порту → stand_health_status='down'."""
    port = 21999  # политика 21000-29999; ничем не занят (проверяется ниже)
    reader = None
    try:
        reader = await asyncio.start_server(lambda r, w: None, "127.0.0.1", port)
    except OSError:
        pytest.fail(f"порт {port} занят — тест недетерминирован")
    reader.close()
    await reader.wait_closed()

    stand_repo.joinpath(".harness").mkdir(exist_ok=True)
    (stand_repo / ".harness" / "stand.json").write_text(
        json.dumps({"services": {"core": {"type": "api", "base_url": f"http://127.0.0.1:{port}"}}}),
        encoding="utf-8",
    )
    verified_at, status = await _stand_row(_test_db, stand_repo)
    assert verified_at is not None, "stand_verified_at должен проставиться"
    assert status == "down", f"закрытый порт → down, стал {status}"


async def test_stand_up_reported(_test_db, stand_repo):
    """Живой TCP-порт → 'up'."""
    server = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    stand_repo.joinpath(".harness").mkdir(exist_ok=True)
    (stand_repo / ".harness" / "stand.json").write_text(
        json.dumps({"services": {"core": {"type": "api", "base_url": f"http://127.0.0.1:{port}"}}}),
        encoding="utf-8",
    )
    try:
        verified_at, status = await _stand_row(_test_db, stand_repo)
        assert status == "up", f"живой порт → up, стал {status}"
    finally:
        server.close()
        await server.wait_closed()


async def test_stand_no_manifest_keeps_null(_test_db, tmp_path: Path):
    """Манифеста нет → телеметрия не пишется (колонки NULL)."""
    verified_at, status = await _stand_row(_test_db, tmp_path / "пусто")
    assert verified_at is None and status is None


async def test_stand_bad_manifest_unknown(_test_db, stand_repo):
    """Нечитаемый JSON → stand_health_status='unknown' (не up, не down)."""
    stand_repo.joinpath(".harness").mkdir(exist_ok=True)
    (stand_repo / ".harness" / "stand.json").write_text("{не json", encoding="utf-8")
    verified_at, status = await _stand_row(_test_db, stand_repo)
    assert verified_at is not None
    assert status == "unknown"
