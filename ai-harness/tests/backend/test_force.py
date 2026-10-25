"""AC-4.2.1.3 / ФТ-ah-28: форс — причина обязательна, только человек, запись в хроники."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from repository.models import Chronicle, Task, User
from usecase.task.create_task import CreateTaskInput, create_task
from usecase.task.transition import TransitionDenied, apply_force
from api.middleware.errors import ApiError


def _inp(**kw):
    base = dict(project_mnemonic="AH", type_key="common_task", title="Форс",
                priority="medium", author_tag="by_human")
    base.update(kw)
    return CreateTaskInput(**base)


async def test_force_without_reason_rejected(session, actor_id):
    actor = await session.get(User, actor_id)
    t = await create_task(session, actor, _inp())
    with pytest.raises(TransitionDenied) as exc:
        await apply_force(session, actor, t.code, "todo", "")
    assert "причина" in exc.value.reason.lower()


async def test_force_from_any_status_with_reason(session, actor_id):
    """Единственный способ вернуть из терминальных (ФТ-ah-28)."""
    actor = await session.get(User, actor_id)
    t = await create_task(session, actor, _inp())
    await session.execute(sa.update(Task).where(Task.code == t.code)
                          .values(status_key="done"))
    await session.commit()
    task = await apply_force(session, actor, t.code, "todo",
                             "решение по архитектуре пересчёта")
    assert task.status_key == "todo"
    ev = (await session.execute(
        sa.select(Chronicle).where(Chronicle.task_id == task.id,
                                   Chronicle.event_type == "force")
    )).scalar_one()
    assert "ручное вмешательство" in ev.message and "решение по архитектуре" in ev.message


async def test_force_by_agent_forbidden(session, actor_id):
    actor = await session.get(User, actor_id)
    t = await create_task(session, actor, _inp())
    agent = (await session.execute(
        sa.select(User).where(User.name == "system"))).scalar_one()
    with pytest.raises(TransitionDenied) as exc:
        await apply_force(session, agent, t.code, "todo", "агент хочет форс")
    assert "только человеку" in exc.value.reason
