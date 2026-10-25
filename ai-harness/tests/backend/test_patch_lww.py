"""ФТ-ah-8 / решение 3.1-9 / AC-4.1.2.4: правка атрибутов, LWW, события «поле»."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from domain.model.validators import DomainError
from usecase.task.create_task import CreateTaskInput, create_task
from usecase.task.patch_task import patch_task


def _inp(**kw):
    base = dict(project_mnemonic="AH", type_key="common_task", title="Правка",
                priority="medium", author_tag="by_human", description_md="Старое описание")
    base.update(kw)
    return CreateTaskInput(**base)


async def _get_task(session, code):
    from repository.models import Task

    return (await session.execute(sa.select(Task).where(Task.code == code))).scalar_one()


async def test_patch_updates_and_writes_field_events(session, actor_id):
    from repository.models import Chronicle, User

    actor = await session.get(User, actor_id)
    t = await create_task(session, actor, _inp())

    result = await patch_task(session, actor, t.code, {"title": "Новое название",
                                                       "priority": "critical"})
    assert result.task.title == "Новое название"
    assert result.task.priority == "critical"

    events = (await session.execute(
        sa.select(Chronicle.message).where(Chronicle.task_id == result.task.id,
                                           Chronicle.event_type == "field")
    )).scalars().all()
    assert "название изменено" in events and "приоритет изменён" in events


async def test_lww_conflict_flag(session, actor_id):
    """Правка без актуальной версии применяется; ответ помечает конфликт (решение 3.1-9)."""
    from repository.models import User

    actor = await session.get(User, actor_id)
    t = await create_task(session, actor, _inp())
    stale = (await _get_task(session, t.code)).updated_at

    other = (await session.execute(
        sa.select(User).where(User.name == "system")
    )).scalar_one()
    await patch_task(session, other, t.code, {"title": "Чужая правка"})

    result = await patch_task(session, actor, t.code, {"title": "Моя правка"},
                              if_updated_at=stale)
    assert result.task.title == "Моя правка"  # LWW: применяется
    assert result.changed_by_other is True    # баннер клиенту


async def test_patch_invalid_title_raises(session, actor_id):
    from repository.models import User

    actor = await session.get(User, actor_id)
    t = await create_task(session, actor, _inp())
    with pytest.raises(DomainError):
        await patch_task(session, actor, t.code, {"title": ""})
