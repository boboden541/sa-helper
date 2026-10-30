"""Прогоны задач: перехват у агента (ФТ-ah-32, B3).

Логика перенесена из контроллера journal (расщепление B2).
"""

from __future__ import annotations

import sqlalchemy as sa

from sqlalchemy.ext.asyncio import AsyncSession

from domain.model.validators import DomainError
from repository.models import Task, User


async def interrupt(session: AsyncSession, actor: User, task: Task, reason: str):
    """Перехват задачи у агента человеком: прогон помечается прерванным,
    резерв снимается; демон на следующем тике убивает процесс агента.
    Возвращает прерванный прогон; без активного прогона — DomainError."""
    import datetime as dt

    from repository.models import Chronicle, TaskRun

    run = (await session.execute(
        sa.select(TaskRun)
        .where(TaskRun.task_id == task.id, TaskRun.finished_at.is_(None))
        .order_by(TaskRun.started_at.desc()).limit(1))).scalar_one_or_none()
    if run is None:
        raise DomainError("Активного прогона нет — перехватывать нечего")
    now = dt.datetime.now(dt.timezone.utc)
    run.finished_at = now
    run.outcome = "interrupted"
    run.detail = f"перехват человеком: {reason}"[:500]
    task.reserved_by = None
    task.reserved_at = None
    task.heartbeat_at = None
    session.add(Chronicle(task_id=task.id, event_type="agent", author_id=actor.id,
                          author_kind="human",
                          message=f"Прогон прерван человеком: {reason}"[:500]))
    await session.commit()
    return run
