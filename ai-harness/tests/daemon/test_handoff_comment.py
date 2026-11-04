"""[handoff]-комментарий демона: сессия кончилась без отчёта агента — след
пишет демон от имени агента (решение владельца 04.11.2026)."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from daemon.runner.agent_runner import FakeRunner, RunReport
from daemon.scheduler.scheduler import Daemon

URL = "postgresql+asyncpg://harness:harness@localhost:5433/ai_harness_test"
CFG = {"daemon.timeout_start_seconds": "5", "daemon.timeout_work_seconds": "10"}


async def _mk_run(eng):
    """Задача на qa_ready (не-git статус — без worktree) + прогон с логом."""
    async with async_sessionmaker(eng)() as s:
        await s.execute(
            sa.text(
                "TRUNCATE task, task_run, task_run_log, task_comment, chronicle, "
                "assignment RESTART IDENTITY CASCADE"
            )
        )
        await s.execute(sa.text("UPDATE project SET next_number = 1"))
        tid, code = (
            await s.execute(
                sa.text(
                    "INSERT INTO task (id, project_id, code, task_type_id, title, "
                    "description_md, status_key, flow_version_id, priority, author_id) "
                    "SELECT gen_random_uuid(), p.id, 'AH-' || p.next_number, tt.id, "
                    "'Handoff-тест', '', 'qa_ready', fv.id, 'medium', u.id "
                    'FROM project p, task_type tt, flow_version fv, "user" u '
                    "WHERE p.mnemonic='AH' AND tt.key='common_task' "
                    "AND fv.task_type_id = tt.id AND fv.is_current AND fv.is_published "
                    "AND u.name='Алексей' RETURNING id, code"
                )
            )
        ).one()
        agent = (
            await s.execute(sa.text("SELECT id FROM \"user\" WHERE name='Тестировщик'"))
        ).scalar_one()
        run = (
            await s.execute(
                sa.text(
                    "INSERT INTO task_run (id, task_id, agent_id, status_key, attempt_no) "
                    "VALUES (gen_random_uuid(), :t, :a, 'qa_ready', 1) RETURNING id"
                ),
                {"t": str(tid), "a": str(agent)},
            )
        ).scalar_one()
        await s.execute(
            sa.text(
                "INSERT INTO task_run_log (id, run_id, seq, kind, text) VALUES "
                "(gen_random_uuid(), :r, 1, 'tool', 'Edit psi.md — правка группы Г8'), "
                "(gen_random_uuid(), :r, 2, 'thinking', 'сверяю редакции эталона')"
            ),
            {"r": str(run)},
        )
        await s.commit()
    return str(code), str(agent), str(run), str(tid)


async def test_handoff_comment(_test_db):
    eng = create_async_engine(URL)
    try:
        code, agent, run, tid = await _mk_run(eng)
        daemon = Daemon(async_sessionmaker(eng, expire_on_commit=False), FakeRunner())

        def script(req):
            return RunReport(status="failed", summary_md="смена сессии", outcome_code="soft_turns")

        daemon.runner = FakeRunner(script=script)
        await daemon._run_task(code, agent, "qa_ready", CFG, run)
        res = await async_sessionmaker(eng)().execute(
            sa.text("SELECT body FROM task_comment ORDER BY created_at LIMIT 1")
        )
        body = res.scalar_one()
        assert "[handoff]" in body and "мягким лимитом" in body and "Edit psi.md" in body

        # агент сам отписался — handoff не пишется, живёт только его комментарий
        async with async_sessionmaker(eng)() as s:
            run2 = (
                await s.execute(
                    sa.text(
                        "INSERT INTO task_run (id, task_id, agent_id, status_key, attempt_no) "
                        "VALUES (gen_random_uuid(), :t, :a, 'qa_ready', 2) RETURNING id"
                    ),
                    {"t": tid, "a": agent},
                )
            ).scalar_one()
            await s.commit()

        def script2(req):
            return RunReport(
                status="success",
                summary_md="готово",
                comments=["Сам отписался в карточке"],
            )

        daemon.runner = FakeRunner(script=script2)
        await daemon._run_task(code, agent, "qa_ready", CFG, str(run2))
        res = await async_sessionmaker(eng)().execute(
            sa.text("SELECT body FROM task_comment ORDER BY created_at")
        )
        rows = res.scalars().all()
        assert len([b for b in rows if "[handoff]" in b]) == 1
        assert any("Сам отписался" in b for b in rows)
    finally:
        await eng.dispose()
