"""Атомарное резервирование задачи демоном (НФТ-ah-6, AC-4.3.1.1).

Условный UPDATE: физически исключает двойное взятие двумя копиями демона —
проигравшая гонку получает rowcount=0.
"""

from __future__ import annotations

import datetime as dt
import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from repository.models import Task, TaskRun


async def reserve_task(session: AsyncSession, task_id: uuid.UUID, agent_id: uuid.UUID,
                       status_key: str, attempt_no: int = 1) -> bool:
    """True — резерв получен; False — занята другим демоном/агентом."""
    result = await session.execute(
        sa.update(Task)
        .where(Task.id == task_id, Task.reserved_by.is_(None),
               Task.status_key == status_key)
        .values(reserved_by=agent_id, reserved_at=dt.datetime.now(dt.timezone.utc),
                heartbeat_at=dt.datetime.now(dt.timezone.utc))
    )
    if result.rowcount != 1:
        await session.rollback()
        return False
    run = TaskRun(task_id=task_id, agent_id=agent_id, status_key=status_key,
                  attempt_no=attempt_no)
    session.add(run)
    await session.commit()
    return True


async def release_reservation(session: AsyncSession, task_id: uuid.UUID,
                              outcome: str, detail: str | None = None) -> None:
    """Завершает активный прогон агента и снимает резерв."""
    now = dt.datetime.now(dt.timezone.utc)
    await session.execute(
        sa.update(TaskRun)
        .where(TaskRun.task_id == task_id, TaskRun.finished_at.is_(None))
        .values(finished_at=now, outcome=outcome, detail=detail)
    )
    await session.execute(
        sa.update(Task)
        .where(Task.id == task_id)
        .values(reserved_by=None, reserved_at=None, heartbeat_at=None)
    )
    await session.commit()
