"""Гейт PLAN_STALE: в done нельзя выйти с планом, не заверенным текущей
версией эталона (версионирование эталона, решение владельца 03.11.2026).
Выходы в blocked/canceled зеркалом и человеком не ограничивает."""

from __future__ import annotations

import sqlalchemy as sa
from repository.models import Checklist, Task, User
from usecase.task.create_task import CreateTaskInput, create_task


async def _story(session, actor, desc: str | None = None) -> Task:
    s = await create_task(
        session,
        actor,
        CreateTaskInput(
            project_mnemonic="AH",
            type_key="story",
            title="Гейт плана",
            priority="high",
            author_tag="by_human",
        ),
    )
    story = (await session.execute(sa.select(Task).where(Task.code == s.code))).scalar_one()
    story.status_key = "in_testing"
    if desc is not None:
        story.description_md = desc
    await session.commit()
    return story


async def _decide(session, task: Task, target: str):
    from domain.transition.engine import Subject, check_edge
    from domain.transition.graph import load_graph
    from usecase.task.gates import load_gate_data

    graph = await load_graph(session, None)
    from usecase.task.transition import task_flow_version_id

    graph = await load_graph(session, await task_flow_version_id(session, task))
    return check_edge(
        graph, task.status_key, target, Subject(kind="human"), await load_gate_data(session, task)
    )


async def _psi_stamp(session, story_id, version: int) -> None:
    await session.execute(
        sa.update(Checklist)
        .where(Checklist.task_id == story_id, Checklist.kind == "psi")
        .values(source_ref_version=version)
    )
    await session.commit()


async def test_story_done_denied_until_plan_fresh(session, actor_id):
    actor = await session.get(User, actor_id)
    story = await _story(session, actor, desc="Постановка")
    await session.execute(
        sa.insert(Checklist).values(
            id=sa.text("gen_random_uuid()"), task_id=story.id, kind="psi", source_ref_version=1
        )
    )
    await session.execute(
        sa.update(Task).where(Task.id == story.id).values(ref_version=2, ref_hash="x")
    )
    await session.commit()

    d = await _decide(session, story, "done")
    assert not d.allowed and d.code == "plan_stale", d.reason

    # заблокировано/отмена не ограничены — пути отступления открыты
    for target in ("blocked", "canceled"):
        d2 = await _decide(session, story, target)
        assert d2.allowed or d2.code != "plan_stale", target

    # заверка плана свежей версией → done разрешён
    await _psi_stamp(session, story.id, 2)
    d3 = await _decide(session, story, "done")
    assert d3.allowed or d3.code != "plan_stale", d3.reason


async def test_story_without_psi_plan_is_stale(session, actor_id):
    actor = await session.get(User, actor_id)
    story = await _story(session, actor)
    d = await _decide(session, story, "done")
    assert not d.allowed and d.code == "plan_stale", "psi-плана нет — done закрыт"


async def test_common_task_developer_plan_gate(session, actor_id):
    actor = await session.get(User, actor_id)
    s = await create_task(
        session,
        actor,
        CreateTaskInput(
            project_mnemonic="AH",
            type_key="common_task",
            title="Задача-гейт",
            priority="medium",
            author_tag="by_human",
        ),
    )
    task = (await session.execute(sa.select(Task).where(Task.code == s.code))).scalar_one()
    task.status_key = "in_testing"
    await session.execute(
        sa.insert(Checklist).values(
            id=sa.text("gen_random_uuid()"), task_id=task.id, kind="developer", source_ref_version=1
        )
    )
    await session.execute(
        sa.update(Task).where(Task.id == task.id).values(ref_version=3, ref_hash="y")
    )
    await session.commit()
    d = await _decide(session, task, "done")
    assert not d.allowed and d.code == "plan_stale", d.reason
    await session.execute(
        sa.update(Checklist)
        .where(Checklist.task_id == task.id, Checklist.kind == "developer")
        .values(source_ref_version=3)
    )
    await session.commit()
    d2 = await _decide(session, task, "done")
    assert d2.allowed or d2.code != "plan_stale", d2.reason
