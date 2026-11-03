"""Коды отказов движка (TransitionDenied.code / Decision.code, миграция 0013).

Планировщик и targeted-retry решают по коду, а не подстроками текста
причины — смена формулировки больше не меняет семантику исхода
(анализ 03.11.2026).
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from repository.models import Checklist, ChecklistItem, Task, User
from usecase.task.create_task import CreateTaskInput, create_task
from usecase.task.transition import apply_transition


def _inp(**kw):
    base = dict(project_mnemonic="AH", type_key="common_task", title="Коды",
                priority="high", author_tag="by_human")
    base.update(kw)
    return CreateTaskInput(**base)


async def _to_status(session, code, status):
    await session.execute(sa.update(Task).where(Task.code == code).values(status_key=status))
    await session.commit()


async def test_denial_codes(_test_db):
    """Отказы движка несут машиночитаемый код в TransitionDenied."""
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from usecase.task.transition import TransitionDenied as TD

    maker = async_sessionmaker(_test_db, expire_on_commit=False)
    async with maker() as session:
        actor = (await session.execute(
            sa.select(User).where(User.name == "Алексей"))).scalar_one()
        t = await create_task(session, actor, _inp())
        await _to_status(session, t.code, "todo")
        with pytest.raises(TD) as exc:
            await apply_transition(session, actor, t.code, "in_progress")
        assert exc.value.code == "checklist_not_created"
        assert "не создан" in exc.value.reason

        # закрытый чеклист разработчика → ребро todo→in_progress допустимо;
        # уход вперёд требует закрытого чеклиста → checklist_not_closed
        chk = Checklist(task_id=t.id, kind="developer")
        session.add(chk)
        await session.flush()
        session.add(ChecklistItem(checklist_id=chk.id, position=0, kind="item",
                                  text="п1", status="in_progress"))
        await session.commit()
        # ребро todo→in_progress теперь легально (вход в работу требует
        # созданного чеклиста — он создан); идём дальше: in_progress→review_ready
        await apply_transition(session, actor, t.code, "in_progress")
        with pytest.raises(TD) as exc:
            await apply_transition(session, actor, t.code, "review_ready")
        assert exc.value.code == "checklist_not_closed"

        # psi_failed: вход истории в done при непройденном ПСИ
        from domain.transition.engine import GateData, Subject, check_edge
        from domain.transition.graph import load_graph
        from usecase.task.transition import task_flow_version_id

        story = await create_task(session, actor, _inp(type_key="story", title="История"))
        story = (await session.execute(
            sa.select(Task).where(Task.code == story.code))).scalar_one()
        graph = await load_graph(session, await task_flow_version_id(session, story))
        gates = GateData(psi_failed=2)
        d = check_edge(graph, "in_testing", "done", Subject(kind="human"), gates)
        assert not d.allowed and d.code == "psi_failed"
