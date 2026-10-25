"""Загрузка данных гейтов задачи: чеклисты, жёсткие связи, артефакты, ПСИ."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from domain.transition.engine import ChecklistState, GateData
from repository.models import Checklist, ChecklistItem, Task, TaskRelation


async def load_gate_data(session: AsyncSession, task: Task) -> GateData:
    checklists: dict[str, ChecklistState] = {}
    rows = (await session.execute(
        sa.select(Checklist.kind, ChecklistItem.status)
        .join(ChecklistItem, ChecklistItem.checklist_id == Checklist.id)
        .where(Checklist.task_id == task.id, ChecklistItem.kind == "item")
    )).all()
    for kind, status in rows:
        st = checklists.setdefault(kind, ChecklistState(exists=True))
        total = st.total + 1
        # открытые — todo/in_progress; failed считается отдельно (семантика макета)
        open_count = st.open + (1 if status in ("todo", "in_progress") else 0)
        failed = st.failed + (1 if status == "failed" else 0)
        checklists[kind] = ChecklistState(exists=True, total=total, open=open_count, failed=failed)
    # созданный, но пустой чеклист — «существует»
    kinds = (await session.execute(
        sa.select(Checklist.kind).where(Checklist.task_id == task.id)
    )).scalars()
    for kind in kinds:
        checklists.setdefault(kind, ChecklistState(exists=True))

    # жёсткие связи: каноническая запись (this blocked_by other) — other не закрыт
    blockers = (await session.execute(
        sa.select(Task.code, Task.title)
        .join(TaskRelation, TaskRelation.to_task == Task.id)
        .where(TaskRelation.from_task == task.id, TaskRelation.kind == "blocked_by",
               Task.status_key.notin_(("done", "canceled")))
    )).all()

    return GateData(
        checklists=checklists,
        open_blockers=tuple((code, title) for code, title in blockers),
    )
