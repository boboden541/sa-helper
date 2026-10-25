"""AC-4.3.1.1 / НФТ-ah-6: две копии демона не дают двойного резервирования."""

from __future__ import annotations

import asyncio

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from daemon.runner.reservation import reserve_task
from repository.models import Assignment, Task, TaskType, User


def _maker(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


async def _seed_ready(_test_db, n=1000):
    async with _maker(_test_db)() as s:
        type_id = (await s.execute(
            sa.select(TaskType.id).where(TaskType.key == "common_task"))).scalar_one()
        agent = (await s.execute(sa.select(User).where(User.name == "system"))).scalar_one()
        await s.execute(sa.text("TRUNCATE task, task_run, task_tag, tag, chronicle, notification RESTART IDENTITY CASCADE"))
        await s.execute(sa.text("UPDATE project SET next_number = 1"))
        await s.execute(sa.insert(Assignment).values(
            task_type_id=type_id, status_key="in_progress", user_id=agent.id))
        await s.execute(sa.text(
            "INSERT INTO task (id, project_id, code, task_type_id, title, description_md, "
            "status_key, flow_version_id, priority, author_id) "
            "SELECT gen_random_uuid(), p.id, 'AH-' || (1000 + g), :t, 'Готов ' || g, '', "
            "'in_progress', fv.id, 'medium', u.id "
            "FROM project p, task_type t, flow_version fv, \"user\" u, "
            "generate_series(1, :n) g "
            "WHERE p.mnemonic='AH' AND t.key='common_task' AND fv.task_type_id = t.id "
            "AND fv.is_current "
            "AND u.name='Алексей'"), {"t": str(type_id), "n": n})
        await s.commit()
        return agent.id


async def test_two_daemons_zero_double_take(_test_db):
    """1000 готовых задач, две «копии демона» в разных порядках обхода —
    каждая задача взята ровно один раз, двойных активных прогонов нет."""
    agent_id = await _seed_ready(_test_db, 1000)
    maker = _maker(_test_db)

    async def daemon_copy(reverse: bool) -> int:
        won = 0
        async with maker() as s:
            ids = (await s.execute(
                sa.select(Task.id).where(Task.status_key == "in_progress",
                                         Task.reserved_by.is_(None))
                .order_by(Task.code))).scalars().all()
        if reverse:
            ids = list(reversed(ids))
        for tid in ids:
            async with maker() as s:
                if await reserve_task(s, tid, agent_id, "in_progress"):
                    won += 1
        return won

    won_a, won_b = await asyncio.gather(daemon_copy(False), daemon_copy(True))

    async with maker() as s:
        total_wins = won_a + won_b
        reserved = (await s.execute(
            sa.select(sa.func.count()).select_from(Task)
            .where(Task.reserved_by == agent_id))).scalar_one()
        double_runs = (await s.execute(sa.text(
            "SELECT count(*) FROM (SELECT task_id FROM task_run "
            "WHERE finished_at IS NULL GROUP BY task_id HAVING count(*) > 1) d"
        ))).scalar_one()
    assert total_wins == 1000          # каждая задача взята ровно один раз
    assert reserved == 1000
    assert double_runs == 0            # ни одной задачи с двумя активными прогонами
