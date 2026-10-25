"""ФТ-ah-2 task-code: монотонные номера, уникальность, номера не переиспользуются."""

from __future__ import annotations

import asyncio

import pytest

from usecase.task.create_task import CreateTaskInput, create_task


def _inp(**kw):
    base = dict(project_mnemonic="AH", type_key="common_task", title="Задача про оплату",
                priority="high", author_tag="by_human")
    base.update(kw)
    return CreateTaskInput(**base)


async def test_codes_sequential(session, actor_id):
    from repository.models import User

    actor = await session.get(User, actor_id)
    c1 = await create_task(session, actor, _inp(title="Первая"))
    c2 = await create_task(session, actor, _inp(title="Вторая"))
    assert (c1.code, c2.code) == ("AH-1", "AH-2")


async def test_codes_not_reused_after_delete(session, actor_id):
    """AC-4.1.2.3: после удаления AH-2 следующая — AH-3."""
    from repository.models import Task, User

    actor = await session.get(User, actor_id)
    c1 = await create_task(session, actor, _inp())
    c2 = await create_task(session, actor, _inp())
    task = (await session.execute(
        __import__("sqlalchemy").select(Task).where(Task.code == c2.code)
    )).scalar_one()
    await session.delete(task)
    await session.commit()
    c3 = await create_task(session, actor, _inp())
    assert c3.code == "AH-3"


async def test_parallel_creation_no_duplicates(_test_db, actor_id):
    """AC-4.1.1.2: два конкурентных соединения не дают дублей кода
    (каждый create_task коммитит свою транзакцию; второй UPDATE ждёт блокировки
    строки проекта и видит инкрементированный счётчик)."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from repository.models import User

    maker = async_sessionmaker(_test_db, expire_on_commit=False)
    async with maker() as s1, maker() as s2:
        actor1 = await s1.get(User, actor_id)
        actor2 = await s2.get(User, actor_id)
        r1, r2 = await asyncio.gather(
            create_task(s1, actor1, _inp(title="Из сессии 1")),
            create_task(s2, actor2, _inp(title="Из сессии 2")),
        )
    codes = [r1.code, r2.code]
    assert len(set(codes)) == 2, codes
    assert codes == sorted(codes, key=lambda c: int(c.split("-")[1]))
