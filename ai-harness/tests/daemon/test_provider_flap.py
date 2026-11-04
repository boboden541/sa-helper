"""Провайдер мигает — задачи ждут, не блокируются (ФТ-ah-35; 04.11.2026).

Пока сеть/API недоступны, сбои недоступности не сжигают попытки и не
приводят к AUTO_BLOCK «исчерпаны попытки»: задачи остаются на статусе
и возобновляются сами после восстановления."""

from __future__ import annotations

import os

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from daemon.runner.agent_runner import is_provider_unreachable


def test_provider_error_classification():
    assert is_provider_unreachable(
        "Claude Code returned an error result: API Error: Can't reach the API server "
        "— check your internet or DNS (EAI_AGAIN) (exit code: 1)"
    )
    assert is_provider_unreachable("fetch failed: getaddrinfo ENOTFOUND api.z.ai")
    assert not is_provider_unreachable("git error: merge conflict in README.md")
    assert not is_provider_unreachable("")


async def test_attempts_not_burned_and_no_autoblock(_test_db):
    from daemon.runner.agent_runner import FakeRunner, RunReport
    from daemon.scheduler.scheduler import Daemon

    eng = create_async_engine(
        os.environ.get(  # noqa: F821
            "TEST_DATABASE_URL",
            "postgresql+asyncpg://harness:harness@localhost:5433/ai_harness_test",
        )
    )
    try:
        async with async_sessionmaker(eng)() as s:
            await s.execute(
                sa.text(
                    "TRUNCATE task, task_run, task_run_log, task_comment, chronicle "
                    "RESTART IDENTITY CASCADE"
                )
            )
            await s.execute(sa.text("UPDATE project SET next_number = 1"))
            code = (
                await s.execute(
                    sa.text(
                        "INSERT INTO task (id, project_id, code, task_type_id, title, "
                        "description_md, status_key, flow_version_id, priority, author_id, "
                        "retry_count) "
                        "SELECT gen_random_uuid(), p.id, 'AH-' || p.next_number, tt.id, "
                        "'Флап-тест', '', 'in_progress', fv.id, 'medium', u.id, 3 "
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
            await s.execute(
                sa.text(
                    "INSERT INTO task_run (id, task_id, agent_id, status_key, attempt_no, "
                    "outcome, reason_code, finished_at) VALUES "
                    "(gen_random_uuid(), (SELECT id FROM task WHERE code='AH-1'), :a, "
                    "'in_progress', 1, 'failed', 'provider_unreachable', now())"
                ),
                {"a": str(agent)},
            )
            await s.commit()
        daemon = Daemon(async_sessionmaker(eng, expire_on_commit=False), FakeRunner())
        cfg = {
            "daemon.max_attempts": "3",
            "daemon.max_runs_per_task": "0",
            "daemon.timeout_start_seconds": "5",
            "daemon.timeout_work_seconds": "10",
        }

        def script(req):
            return RunReport(
                status="failed",
                summary_md="сбой сети",
                outcome_code="provider_unreachable",
            )

        daemon.runner = FakeRunner(script=script)
        await daemon._run_task(code, str(agent), "in_progress", cfg, str(run))

        async with async_sessionmaker(eng)() as s:
            row = (
                await s.execute(
                    sa.text("SELECT status_key, retry_count FROM task WHERE code='AH-1'")
                )
            ).one()
        # попытка не сжечётся и задача не уйдёт в blocked при retry_count>=max
        status, retry = row
        # прогон вернул provider_unreachable-отчёт → release с кодом, попытка сжигается
        # только отчётом с реальной виной агента; задача остаётся на статусе
        assert status == "in_progress", f"задача должна остаться, стала {status}"
        assert retry == 3, f"retry_count не должен расти, стал {retry}"
    finally:
        await eng.dispose()
