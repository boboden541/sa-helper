"""Токены прогона (решение владельца 27.10.2026): события usage раннера
попадают в task_run накопительно; строки живого лога от них не плодятся."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from daemon.runner.agent_runner import RunReport
from daemon.runner.reservation import reserve_task
from daemon.scheduler.scheduler import Daemon
from repository.models import Assignment, TaskRun, TaskType, User


def _maker(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


async def _ready_task(_test_db, status="review"):
    async with _maker(_test_db)() as s:
        await s.execute(sa.text(
            "TRUNCATE task, task_run, task_tag, tag, chronicle, notification, "
            "task_relation, checklist, checklist_item, task_assignee RESTART IDENTITY CASCADE"))
        await s.execute(sa.text("UPDATE project SET next_number = 1"))
        # остатки settings-тестов (активное подключение при пустом ключе тестов)
        # роняют _provider_for — тест не про провайдеров, глушим все подключения
        await s.execute(sa.text("UPDATE connection SET is_active = false"))
        type_id = (await s.execute(
            sa.select(TaskType.id).where(TaskType.key == "common_task"))).scalar_one()
        agent = (await s.execute(
            sa.select(User).where(User.name == "Разработчик"))).scalar_one_or_none()
        if agent is None:
            agent = (await s.execute(pg_insert(User).values(
                name="Разработчик", user_type="agent").returning(User))).scalar_one()
        await s.execute(pg_insert(Assignment).values(
            task_type_id=type_id, status_key=status, user_id=agent.id).on_conflict_do_nothing())
        await s.execute(sa.text(
            "INSERT INTO task (id, project_id, code, task_type_id, title, description_md, "
            "status_key, flow_version_id, priority, author_id) "
            "SELECT gen_random_uuid(), p.id, 'AH-' || next_number, t.id, 'Т', '', :st, fv.id, "
            "'medium', u.id FROM project p, task_type t, flow_version fv, \"user\" u "
            "WHERE p.mnemonic='AH' AND t.key='common_task' AND fv.task_type_id = t.id "
            "AND fv.is_current AND u.name='Алексей' RETURNING code"), {"st": status})
        code = (await s.execute(sa.text(
            "SELECT code FROM task ORDER BY created_at DESC LIMIT 1"))).scalar_one()
        await s.execute(sa.text("UPDATE project SET next_number = next_number + 1 "
                                "WHERE mnemonic='AH'"))
        await s.commit()
        return agent.id, code


class UsageRunner:
    """Раннер, отдающий два хода usage: накопительные значения растут."""

    def __init__(self) -> None:
        self.requests = []

    async def run(self, req):
        self.requests.append(req)
        await req.emit("usage", data={"input": 1000, "output": 400, "cache": 300,
                                      "total": 1700})
        await req.emit("usage", data={"input": 2600, "output": 900, "cache": 300,
                                      "total": 3800})
        return RunReport(status="success", summary_md="ок")


async def test_usage_events_accumulate_in_task_run(_test_db):
    agent_id, code = await _ready_task(_test_db)
    maker = _maker(_test_db)
    daemon = Daemon(maker, UsageRunner())
    cfg = {"daemon.timeout_start_seconds": "300", "daemon.timeout_work_seconds": "1800",
           "daemon.max_attempts": "3"}

    async with maker() as s:
        task_id = (await s.execute(
            sa.text("SELECT id FROM task WHERE code = :c"), {"c": code})).scalar_one()
        assert await reserve_task(s, task_id, agent_id, "review")

    await daemon._run_task(code, agent_id, "review", cfg)

    async with maker() as s:
        run = (await s.execute(sa.select(TaskRun).where(
            TaskRun.task_id == task_id))).scalars().one()
        assert (run.input_tokens, run.output_tokens, run.cache_tokens) == (2600, 900, 300)
        # события usage не создают строк живого лога — только итог прогона
        rows = (await s.execute(sa.text(
            "SELECT kind FROM task_run_log WHERE run_id = :r"),
            {"r": str(run.id)})).scalars().all()
        assert "usage" not in rows
