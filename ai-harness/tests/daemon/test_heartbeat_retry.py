"""AC-4.3.1.2/3: потеря heartbeat и лестница ретраев 1→5→15 с блокировкой."""

from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from daemon.runner.reservation import release_reservation, reserve_task
from repository.models import Assignment, Task, TaskRun, TaskType, User


def _maker(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


async def _ready_task(_test_db, status="in_progress"):
    async with _maker(_test_db)() as s:
        # daemon-тесты не используют session-фикстуру — чистим операционные таблицы сами
        await s.execute(sa.text(
            "TRUNCATE task, task_run, task_tag, tag, chronicle, notification, "
            "task_relation, checklist, checklist_item, task_assignee RESTART IDENTITY CASCADE"))
        await s.execute(sa.text("UPDATE project SET next_number = 1"))
        await s.commit()
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
            "AND fv.is_current AND u.name='Алексей' "
            "RETURNING code"), {"st": status})
        code = (await s.execute(sa.text(
            "SELECT code FROM task ORDER BY created_at DESC LIMIT 1"))).scalar_one()
        await s.execute(sa.text("UPDATE project SET next_number = next_number + 1 "
                                "WHERE mnemonic='AH'"))
        await s.commit()
        return agent.id, code


async def test_stale_heartbeat_released_and_counted(_test_db):
    """Остановка агента после резерва: через порог резерв снят, попытка неудачна."""
    agent_id, code = await _ready_task(_test_db)
    maker = _maker(_test_db)
    async with maker() as s:
        task = (await s.execute(sa.select(Task).where(Task.code == code))).scalar_one()
        assert await reserve_task(s, task.id, agent_id, "in_progress")
        # агент умер: heartbeat протух на 3+ интервала
        await s.execute(sa.text(
            "UPDATE task_run SET heartbeat_at = now() - interval '310 seconds' "
            "WHERE finished_at IS NULL"))
        await s.execute(sa.text(
            "UPDATE task SET heartbeat_at = now() - interval '310 seconds' "
            "WHERE reserved_by IS NOT NULL"))
        await s.commit()

    from daemon.scheduler.scheduler import Daemon

    daemon = Daemon(maker, runner=None)
    async with maker() as s:
        lost = await daemon._sweep_dead_runs(s, {})
        assert lost == 1
        task = (await s.execute(sa.select(Task).where(Task.code == code))).scalar_one()
        assert task.reserved_by is None              # резерв снят
        assert task.retry_count == 1                 # попытка неудачна
        run = (await s.execute(sa.select(TaskRun)
                               .where(TaskRun.task_id == task.id))).scalar_one()
        assert run.outcome == "failed" and run.finished_at is not None


async def test_exhausted_attempts_block_task(_test_db):
    """ФТ-ah-34: после max_attempts задача blocked «требуется участие человека»."""
    agent_id, code = await _ready_task(_test_db)
    maker = _maker(_test_db)
    async with maker() as s:
        task = (await s.execute(sa.select(Task).where(Task.code == code))).scalar_one()
        task.retry_count = 3  # исчерпано
        await s.commit()

    from daemon.scheduler.scheduler import Daemon

    daemon = Daemon(maker, runner=None)
    async with maker() as s:
        launched = await daemon._launch_ready(s, {
            "daemon.tick_seconds": "30", "daemon.timeout_start_seconds": "300",
            "daemon.timeout_work_seconds": "1800", "daemon.max_attempts": "3",
            "daemon.retry_pauses_minutes": "1,5,15"})
        assert launched == 0
        task = (await s.execute(sa.select(Task).where(Task.code == code))).scalar_one()
        assert task.status_key == "blocked"
        assert "участие человека" in task.blocked_reason


async def test_retry_pause_grows(_test_db):
    """AC-4.3.1.3: после неудачи задача не берётся, пока не истекла пауза серии."""
    agent_id, code = await _ready_task(_test_db)
    maker = _maker(_test_db)
    async with maker() as s:
        task = (await s.execute(sa.select(Task).where(Task.code == code))).scalar_one()
        await reserve_task(s, task.id, agent_id, "in_progress")
        await release_reservation(s, task.id, "failed", "ошибка провайдера")
        task.retry_count = 1
        await s.commit()

    from daemon.scheduler.scheduler import Daemon

    daemon = Daemon(maker, runner=None)
    async with maker() as s:
        launched = await daemon._launch_ready(s, {
            "daemon.tick_seconds": "30", "daemon.timeout_start_seconds": "300",
            "daemon.timeout_work_seconds": "1800", "daemon.max_attempts": "3",
            "daemon.retry_pauses_minutes": "1,5,15"})
        assert launched == 0  # пауза 1 минута не истекла
