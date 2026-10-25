"""AC-4.2.1.2 / ФТ-ah-7: жёсткая связь blocked_by держит и человека, и агента."""

from __future__ import annotations

import sqlalchemy as sa

from repository.models import Checklist, ChecklistItem, Task, TaskRelation, User
from usecase.task.create_task import CreateTaskInput, create_task
from usecase.task.transition import TransitionDenied, apply_transition


def _inp(**kw):
    base = dict(project_mnemonic="AH", type_key="common_task", title="Связи",
                priority="high", author_tag="by_human")
    base.update(kw)
    return CreateTaskInput(**base)


async def _status(session, code, status):
    await session.execute(sa.update(Task).where(Task.code == code).values(status_key=status))
    await session.commit()


async def _ensure_dev_checklist(session, code):
    from repository.models import Checklist, ChecklistItem, Task

    tid = (await session.execute(sa.select(Task.id).where(Task.code == code))).scalar_one()
    chk = Checklist(task_id=tid, kind="developer")
    session.add(chk)
    await session.flush()
    session.add(ChecklistItem(checklist_id=chk.id, position=0, kind="item",
                              text="шаг", status="todo"))
    await session.commit()


async def test_blocked_by_denies_human_and_agent(session, actor_id):
    actor = await session.get(User, actor_id)
    blocker = await create_task(session, actor, _inp(title="Блокер"))
    blocked = await create_task(session, actor, _inp(title="Заблокированная"))
    await _status(session, blocked.code, "todo")

    await session.execute(sa.insert(TaskRelation).values(
        from_task=(await session.execute(
            sa.select(Task.id).where(Task.code == blocked.code))).scalar_one(),
        to_task=(await session.execute(
            sa.select(Task.id).where(Task.code == blocker.code))).scalar_one(),
        kind="blocked_by"))
    await session.commit()
    await _ensure_dev_checklist(session, blocked.code)

    from usecase.task.transition import TransitionDenied
    try:
        await apply_transition(session, actor, blocked.code, "in_progress")
        raise AssertionError("человека пустили при blocked by")
    except TransitionDenied as d:
        assert "blocked by" in d.reason and blocker.code in d.reason

    # агент тоже
    from domain.transition.engine import Subject
    from usecase.task.gates import load_gate_data
    from domain.transition.graph import load_graph
    from domain.transition.engine import check_edge

    task = (await session.execute(
        sa.select(Task).where(Task.code == blocked.code))).scalar_one()
    graph = await load_graph(session, task.flow_version_id)
    gates = await load_gate_data(session, task)
    agent_subject = Subject(kind="agent", user_id="x",
                            assigned_statuses=frozenset({"todo"}))
    decision = check_edge(graph, "todo", "in_progress", agent_subject, gates)
    assert not decision.allowed and "blocked by" in decision.reason


async def test_done_blocker_releases(session, actor_id):
    actor = await session.get(User, actor_id)
    blocker = await create_task(session, actor, _inp(title="Блокер закрывается"))
    blocked = await create_task(session, actor, _inp(title="Освобождённая"))
    await _status(session, blocker.code, "done")
    await _status(session, blocked.code, "todo")

    await session.execute(sa.insert(TaskRelation).values(
        from_task=(await session.execute(
            sa.select(Task.id).where(Task.code == blocked.code))).scalar_one(),
        to_task=(await session.execute(
            sa.select(Task.id).where(Task.code == blocker.code))).scalar_one(),
        kind="blocked_by"))
    await session.commit()

    await _ensure_dev_checklist(session, blocked.code)
    task = await apply_transition(session, actor, blocked.code, "in_progress")
    assert task.status_key == "in_progress"


async def test_soft_link_does_not_block(session, actor_id):
    """Мягкая связь do after — только предупреждение и понижение в очереди."""
    actor = await session.get(User, actor_id)
    first = await create_task(session, actor, _inp(title="Первая"))
    second = await create_task(session, actor, _inp(title="Вторая"))
    await _status(session, second.code, "todo")
    await session.execute(sa.insert(TaskRelation).values(
        from_task=(await session.execute(
            sa.select(Task.id).where(Task.code == second.code))).scalar_one(),
        to_task=(await session.execute(
            sa.select(Task.id).where(Task.code == first.code))).scalar_one(),
        kind="do_after"))
    await session.commit()
    await _ensure_dev_checklist(session, second.code)
    task = await apply_transition(session, actor, second.code, "in_progress")
    assert task.status_key == "in_progress"
