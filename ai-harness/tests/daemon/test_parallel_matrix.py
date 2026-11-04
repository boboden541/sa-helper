"""Режим parallel матрицы назначений (AC-4.4.3.1) и коды причин прогонов.

До 03.11.2026 планировщик брал строго первую запись матрицы по position —
режим parallel читался, но не исполнялся: второй параллельный агент
никогда не запускался (анализ 03.11.2026, миграция 0013).
"""

from __future__ import annotations

import asyncio

import sqlalchemy as sa
from repository.models import Assignment, Task, TaskType, User
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from daemon.runner.reservation import release_reservation, reserve_task


def _maker(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


async def _seed_pair(_test_db):
    """История in_testing + два агента в матрице (режим parallel), как в сиде."""
    async with _maker(_test_db)() as s:
        # тесты на _test_db напрямую не получают truncate конфтеста — чистим сами
        await s.execute(
            sa.text(
                "TRUNCATE task, task_run, task_run_log, chronicle, notification, "
                "checklist, checklist_item, assignment RESTART IDENTITY CASCADE"
            )
        )
        type_id = (
            await s.execute(sa.select(TaskType.id).where(TaskType.key == "story"))
        ).scalar_one()
        psi = (await s.execute(sa.select(User).where(User.name == "ПСИ-составитель"))).scalar_one()
        tester = (await s.execute(sa.select(User).where(User.name == "Тестировщик"))).scalar_one()
        # назначения уже в сиде (ПСИ + Тестировщик, parallel на in_testing) —
        # идемпотентно подтверждаем режим и позиции
        await s.execute(
            pg_insert(Assignment)
            .values(
                [
                    {
                        "task_type_id": type_id,
                        "status_key": "in_testing",
                        "user_id": psi.id,
                        "mode": "parallel",
                        "position": 1,
                    },
                    {
                        "task_type_id": type_id,
                        "status_key": "in_testing",
                        "user_id": tester.id,
                        "mode": "parallel",
                        "position": 2,
                    },
                ]
            )
            .on_conflict_do_nothing()
        )
        await s.execute(
            sa.text(
                "INSERT INTO task (id, project_id, code, task_type_id, title, "
                "description_md, status_key, flow_version_id, priority, author_id) "
                "SELECT gen_random_uuid(), p.id, 'AH-9901', :t, 'История', '', "
                "'in_testing', fv.id, 'medium', u.id "
                'FROM project p, task_type t, flow_version fv, "user" u '
                "WHERE p.mnemonic='AH' AND t.key='story' AND fv.task_type_id = t.id "
                "AND fv.is_current AND u.name='Алексей'"
            ),
            {"t": str(type_id)},
        )
        await s.commit()
        return type_id, psi.id, tester.id


async def test_parallel_mode_launches_both_agents(_test_db):
    """parallel: оба назначенных агента получают свой прогон одновременно."""
    from daemon.scheduler.scheduler import Daemon

    _type_id, psi_id, tester_id = await _seed_pair(_test_db)
    maker = _maker(_test_db)
    daemon = Daemon(maker, runner=None)

    async with maker() as s:
        cfg = {
            "daemon.tick_seconds": "30",
            "daemon.max_attempts": "3",
            "daemon.timeout_start_seconds": "300",
            "daemon.timeout_work_seconds": "1800",
            "daemon.max_parallel": "4",
        }
        launched = await daemon._launch_ready(s, cfg)
        assert launched == 2, f"ожидали запуск обоих агентов, запущено {launched}"

        runs = (
            await s.execute(
                sa.text(
                    "SELECT agent_id, finished_at FROM task_run WHERE task_id = "
                    "(SELECT id FROM task WHERE code = 'AH-9901')"
                )
            )
        ).all()
        assert {str(r[0]) for r in runs} == {str(psi_id), str(tester_id)}
        for r in runs:
            assert r[1] is None  # оба активны

    # фоновые _go-задачи (runner=None → ошибочный путь) держат сессии —
    # гасим до конца теста, иначе teardown не дропнет БД
    for t in list(daemon._active.values()):
        t.cancel()
    await asyncio.gather(*daemon._active.values(), return_exceptions=True)


async def test_parallel_duplicate_reserve_guards(_test_db):
    """Двойное взятие тем же агентом в parallel ловится uq_task_run_active."""
    _type_id, psi_id, tester_id = await _seed_pair(_test_db)
    maker = _maker(_test_db)

    async with maker() as s:
        task_id = (await s.execute(sa.select(Task.id).where(Task.code == "AH-9901"))).scalar_one()
        r1 = await reserve_task(s, task_id, psi_id, "in_testing", mode="parallel")
        assert r1
        r2 = await reserve_task(s, task_id, psi_id, "in_testing", mode="parallel")
        assert not r2, "тот же агент не может взять второй прогон"
        r3 = await reserve_task(s, task_id, tester_id, "in_testing", mode="parallel")
        assert r3, "второй агент резервирует независимо"

        # release по прогону: соседний прогон продолжает жить
        await release_reservation(s, task_id, r1, "success")
        left = (
            await s.execute(
                sa.text("SELECT count(*) FROM task_run WHERE task_id = :t AND finished_at IS NULL"),
                {"t": str(task_id)},
            )
        ).scalar_one()
        assert left == 1, "соседний прогон должен остаться активным"

        # parallel не ставит эксклюзивный резерв задачи
        reserved = (
            await s.execute(
                sa.text("SELECT reserved_by FROM task WHERE id = :t"), {"t": str(task_id)}
            )
        ).scalar_one()
        assert reserved is None


async def test_exclusive_mode_single_agent(_test_db):
    """replacement: запускается только первый агент пары тип×статус."""
    from daemon.scheduler.scheduler import Daemon

    type_id, psi_id, tester_id = await _seed_pair(_test_db)
    async with _maker(_test_db)() as s:
        await s.execute(
            sa.text(
                "UPDATE assignment SET mode = 'replacement' WHERE task_type_id = :t "
                "AND status_key = 'in_testing'"
            ),
            {"t": str(type_id)},
        )
        await s.commit()

    maker = _maker(_test_db)
    daemon = Daemon(maker, runner=None)
    async with maker() as s:
        cfg = {
            "daemon.tick_seconds": "30",
            "daemon.max_attempts": "3",
            "daemon.timeout_start_seconds": "300",
            "daemon.timeout_work_seconds": "1800",
            "daemon.max_parallel": "4",
        }
        launched = await daemon._launch_ready(s, cfg)
        assert launched == 1, "в replacement запускается только первый агент"

        runs = (
            await s.execute(
                sa.text(
                    "SELECT agent_id FROM task_run WHERE task_id = "
                    "(SELECT id FROM task WHERE code = 'AH-9901')"
                )
            )
        ).all()
        assert len(runs) == 1
        assert str(runs[0][0]) == str(psi_id)  # первый по position

    for t in list(daemon._active.values()):
        t.cancel()
    await asyncio.gather(*daemon._active.values(), return_exceptions=True)
