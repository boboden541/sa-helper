"""ФТ-ah-27: запреты агентов — событие «запрет», повторные нарушения → blocked."""

from __future__ import annotations

import contextlib

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from repository.models import Assignment, Chronicle, Task, TaskType, User
from usecase.task.create_task import CreateTaskInput, create_task
from usecase.task.transition import TransitionDenied, apply_transition


def _inp(**kw):
    base = dict(project_mnemonic="AH", type_key="common_task", title="Права агента",
                priority="medium", author_tag="by_human")
    base.update(kw)
    return CreateTaskInput(**base)


async def _status(session, code, status):
    await session.execute(sa.update(Task).where(Task.code == code).values(status_key=status))
    await session.commit()


async def _system_agent(session) -> User:
    return (await session.execute(sa.select(User).where(User.name == "system"))).scalar_one()


async def _assign(session, agent: User, status_key: str):
    type_id = (await session.execute(
        sa.select(TaskType.id).where(TaskType.key == "common_task"))).scalar_one()
    await session.execute(pg_insert(Assignment).values(
        task_type_id=type_id, status_key=status_key, user_id=agent.id, mode="replacement"
    ).on_conflict_do_nothing())
    await session.commit()


async def test_agent_denied_outside_own_status(session, actor_id):
    """Переход со статуса, где агент не назначен, отклоняется + событие «запрет»."""
    actor = await session.get(User, actor_id)
    t = await create_task(session, actor, _inp())
    await _status(session, t.code, "todo")
    agent = await _system_agent(session)  # назначений нет
    with pytest_raises_denied():
        await apply_transition(session, agent, t.code, "in_progress")
    denied = (await session.execute(
        sa.select(Chronicle).where(Chronicle.task_id == (await _tid(session, t.code)),
                                   Chronicle.event_type == "denied"))).scalar_one()
    assert "не назначен" in denied.message


async def test_agent_denied_canceled(session, actor_id):
    actor = await session.get(User, actor_id)
    t = await create_task(session, actor, _inp())
    await _status(session, t.code, "todo")
    agent = await _system_agent(session)
    await _assign(session, agent, "todo")
    with pytest_raises_denied():
        await apply_transition(session, agent, t.code, "canceled")  # отмена — только человек


async def test_agent_can_transition_within_own_status(session, actor_id):
    """Валидное ребро своего статуса — разрешено (взятие в работу)."""
    actor = await session.get(User, actor_id)
    t = await create_task(session, actor, _inp())
    await _status(session, t.code, "todo")
    # чеклист разработчика создан (вход в in progress требует созданного)
    from repository.models import Checklist, ChecklistItem

    tid = await _tid(session, t.code)
    chk = Checklist(task_id=tid, kind="developer")
    session.add(chk)
    await session.flush()
    session.add(ChecklistItem(checklist_id=chk.id, position=0, kind="item",
                              text="настроить окружение", status="todo"))
    await session.commit()

    agent = await _system_agent(session)
    await _assign(session, agent, "todo")
    task = await apply_transition(session, agent, t.code, "in_progress")
    assert task.status_key == "in_progress"


async def test_repeat_violation_blocks_task(session, actor_id):
    """Повторные нарушения → blocked (ФТ-ah-27)."""
    actor = await session.get(User, actor_id)
    t = await create_task(session, actor, _inp())
    await _status(session, t.code, "todo")
    agent = await _system_agent(session)  # без назначений

    for _ in range(2):
        with pytest_raises_denied():
            await apply_transition(session, agent, t.code, "in_progress")

    task = (await session.execute(
        sa.select(Task).where(Task.code == t.code))).scalar_one()
    assert task.status_key == "blocked"
    assert "нарушени" in (task.blocked_reason or "")
    auto_event = (await session.execute(
        sa.select(Chronicle).where(Chronicle.task_id == task.id,
                                   Chronicle.author_kind == "auto",
                                   Chronicle.rule_code == "DENY"))).scalar_one()
    assert "Автоблокировка" in auto_event.message


async def _tid(session, code):
    return (await session.execute(
        sa.select(Task.id).where(Task.code == code))).scalar_one()


import contextlib  # noqa: E402


@contextlib.contextmanager
def pytest_raises_denied():
    with pytest.raises(TransitionDenied):
        yield
