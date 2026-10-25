"""AC-4.2.1.1 / ФТ-ah-9: чеклист-гейты — создание на вход, закрытие на выход."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from repository.models import Checklist, ChecklistItem, Task, User
from usecase.task.create_task import CreateTaskInput, create_task
from usecase.task.transition import TransitionDenied, apply_transition


def _inp(**kw):
    base = dict(project_mnemonic="AH", type_key="common_task", title="Гейты",
                priority="high", author_tag="by_human")
    base.update(kw)
    return CreateTaskInput(**base)


async def _to_status(session, code, status):
    await session.execute(sa.update(Task).where(Task.code == code).values(status_key=status))
    await session.commit()


async def _create_checklist(session, task_id, kind, statuses: list[str]):
    """Чеклист один на вид (uq task_id+kind): создаём или заменяем пункты."""
    chk = (await session.execute(
        sa.select(Checklist).where(Checklist.task_id == task_id, Checklist.kind == kind)
    )).scalar_one_or_none()
    if chk is None:
        chk = Checklist(task_id=task_id, kind=kind)
        session.add(chk)
        await session.flush()
    else:
        await session.execute(
            sa.delete(ChecklistItem).where(ChecklistItem.checklist_id == chk.id))
    for i, s in enumerate(statuses):
        session.add(ChecklistItem(checklist_id=chk.id, position=i, kind="item",
                                  text=f"пункт {i}", status=s))
    await session.commit()


async def _denied_reason(session, actor, code, to) -> str:
    with pytest.raises(TransitionDenied) as exc:
        await apply_transition(session, actor, code, to)
    return exc.value.reason


async def test_enter_in_progress_requires_created_checklist(session, actor_id):
    """«Взять задачу в работу без созданного чеклиста нельзя» (ФТ-ah-9)."""
    actor = await session.get(User, actor_id)
    t = await create_task(session, actor, _inp())
    await _to_status(session, t.code, "todo")
    reason = await _denied_reason(session, actor, t.code, "in_progress")
    assert "не создан" in reason


async def test_forward_move_requires_closed_checklist(session, actor_id):
    """Выход из in progress вперёд — чеклист разработчика закрыт без failed."""
    actor = await session.get(User, actor_id)
    t = await create_task(session, actor, _inp())
    await _to_status(session, t.code, "in_progress")
    tid = (await session.execute(
        sa.select(Task.id).where(Task.code == t.code))).scalar_one()

    await _create_checklist(session, tid, "developer", ["done", "todo"])
    reason = await _denied_reason(session, actor, t.code, "review_ready")
    assert "не закрыто 1" in reason

    await _create_checklist(session, tid, "developer", ["done", "failed"])
    reason = await _denied_reason(session, actor, t.code, "review_ready")
    assert "неуспешные" in reason

    await _create_checklist(session, tid, "developer", ["done", "closed"])
    task = await apply_transition(session, actor, t.code, "review_ready")
    assert task.status_key == "review_ready"


async def test_gate_denial_reason_is_human_readable(session, actor_id):
    """Причина отказа человекочитаема и называет гейт (БТ-ah-6, два слоя языка)."""
    actor = await session.get(User, actor_id)
    t = await create_task(session, actor, _inp())
    await _to_status(session, t.code, "todo")
    reason = await _denied_reason(session, actor, t.code, "in_progress")
    assert "чек-лист разработчика" in reason
