"""ФТ-ah-4 / AC-4.1.2.1: правила очереди — приоритет, баги выше задач, старые выше."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from usecase.task.create_task import CreateTaskInput, create_task
from usecase.task.list_tasks import list_tasks


def _inp(**kw):
    base = dict(project_mnemonic="AH", type_key="common_task", title="Очередь",
                priority="medium", author_tag="by_human")
    base.update(kw)
    return CreateTaskInput(**base)


async def _set_created(session, code, created_at: datetime):
    from repository.models import Task

    await session.execute(sa.update(Task).where(Task.code == code)
                          .values(created_at=created_at))
    await session.commit()


async def test_equal_priority_older_first(session, actor_id):
    """При равных приоритетах выше задача с более ранней датой создания."""
    from repository.models import User

    actor = await session.get(User, actor_id)
    now = datetime.now(timezone.utc)
    newer = await create_task(session, actor, _inp(title="Новее"))
    older = await create_task(session, actor, _inp(title="Старее"))
    await _set_created(session, newer.code, now)
    await _set_created(session, older.code, now - timedelta(hours=1))

    _, cards = await list_tasks(session)
    assert [c.code for c in cards][:2] == [older.code, newer.code]


async def test_bug_low_above_common_low(session, actor_id):
    """Баг с low — выше common_task с low."""
    from repository.models import User

    actor = await session.get(User, actor_id)
    common = await create_task(session, actor, _inp(priority="low", title="Обычная low"))
    bug = await create_task(session, actor, _inp(type_key="bug", priority="low", title="Баг low"))

    _, cards = await list_tasks(session)
    assert [c.code for c in cards][:2] == [bug.code, common.code]


async def test_priority_beats_age_and_type(session, actor_id):
    """critical выше низких приоритетов независимо от возраста и типа."""
    from repository.models import User

    actor = await session.get(User, actor_id)
    old_low_bug = await create_task(session, actor, _inp(type_key="bug", priority="low"))
    fresh_critical = await create_task(session, actor, _inp(priority="critical"))
    await _set_created(session, old_low_bug.code,
                       datetime.now(timezone.utc) - timedelta(days=5))

    _, cards = await list_tasks(session)
    assert cards[0].code == fresh_critical.code
