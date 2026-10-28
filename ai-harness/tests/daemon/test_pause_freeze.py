"""Пауза конвейера замораживает автоматику статусов (решение владельца
28.10.2026 «подержать задачу в конкретном статусе»): на паузе задача на
рабочем статусе без агента НЕ блокируется; после снятия — блокируется."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from daemon.scheduler.scheduler import Daemon


def _maker(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


async def _task_on_work_status(eng) -> str:
    """Задача in_progress без назначенного агента (проект/тип из сидов)."""
    async with _maker(eng)() as s:
        await s.execute(sa.text(
            "TRUNCATE task, task_run, task_tag, tag, chronicle, notification, "
            "assignment RESTART IDENTITY CASCADE"))
        await s.execute(sa.text("UPDATE project SET next_number = 1"))
        await s.execute(sa.text(
            "INSERT INTO task (id, project_id, code, task_type_id, title, description_md, "
            "status_key, flow_version_id, priority, author_id) "
            "SELECT gen_random_uuid(), p.id, 'AH-' || p.next_number, tt.id, 'Тест паузы', '', "
            "'in_progress', fv.id, 'medium', u.id "
            "FROM project p, task_type tt, flow_version fv, \"user\" u "
            "WHERE p.mnemonic='AH' AND tt.key='common_task' "
            "AND fv.task_type_id = tt.id AND fv.is_current AND fv.is_published "
            "AND u.name='Алексей' RETURNING code"))
        code = (await s.execute(sa.text(
            "SELECT code FROM task ORDER BY created_at DESC LIMIT 1"))).scalar_one()
        await s.execute(sa.text(
            "UPDATE project SET next_number = next_number + 1 WHERE mnemonic='AH'"))
        await s.commit()
        return code


async def test_pause_freezes_status_automata(_test_db):
    from daemon.runner.agent_runner import FakeRunner

    # герметично: свой движок на цикле теста + dispose в конце,
    # иначе тики оставляют незакрытые транзакции и вешают соседние тесты
    eng = create_async_engine(
        "postgresql+asyncpg://harness:harness@localhost:5433/ai_harness_test")
    try:
        code = await _task_on_work_status(eng)
        daemon = Daemon(_maker(eng), FakeRunner())

        # пауза: автоблокировка не исполняется — задача держится в работе
        async with _maker(eng)() as s:
            await s.execute(sa.text(
                "INSERT INTO app_setting (key, value) VALUES ('daemon.paused', 'true') "
                "ON CONFLICT (key) DO UPDATE SET value = 'true'"))
            await s.commit()
        await daemon.tick()
        st = (await _maker(eng)().execute(sa.text(
            "SELECT status_key FROM task WHERE code = :c"), {"c": code})).scalar_one()
        assert st == "in_progress", f"на паузе статус должен держаться, стал {st}"

        # пауза снята: автоблокировка догоняет — нет агента → blocked
        async with _maker(eng)() as s:
            await s.execute(sa.text(
                "UPDATE app_setting SET value='false' WHERE key='daemon.paused'"))
            await s.commit()
        await daemon.tick()
        st = (await _maker(eng)().execute(sa.text(
            "SELECT status_key FROM task WHERE code = :c"), {"c": code})).scalar_one()
        assert st == "blocked", f"после паузы нужна автоблокировка, стал {st}"
    finally:
        await eng.dispose()
        # убить брошенные транзакции тестовой базы — иначе они держат
        # блокировки на task и вешают TRUNCATE следующих тестов
        import asyncpg

        aconn = await asyncpg.connect(
            "postgresql://harness:harness@localhost:5433/ai_harness")
        try:
            await aconn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = 'ai_harness_test' AND pid <> pg_backend_pid() "
                "AND state = 'idle in transaction'")
        finally:
            await aconn.close()
        async with _maker(_test_db)() as s:
            await s.execute(sa.text(
                "UPDATE app_setting SET value='false' WHERE key='daemon.paused'"))
            await s.commit()
