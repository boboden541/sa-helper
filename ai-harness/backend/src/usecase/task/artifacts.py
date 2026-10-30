"""Артефакты этапов: отчёты с версиями (ФТ-ah-38, B3).

Запись перенесена из контроллера journal (расщепление B2); контроллер
проверяет kind, находит задачу и возвращает ответ.
"""

from __future__ import annotations

import sqlalchemy as sa

from sqlalchemy.ext.asyncio import AsyncSession

from repository.models import Task, User


async def add_artifact(session: AsyncSession, actor: User, task: Task,
                       kind: str, body_md: str) -> int:
    """Новая версия артефакта `kind` + событие в хронику; возвращает номер версии."""
    from repository.models import Chronicle, TaskArtifact

    version = (await session.execute(
        sa.select(sa.func.coalesce(sa.func.max(TaskArtifact.version), 0))
        .where(TaskArtifact.task_id == task.id, TaskArtifact.kind == kind))).scalar_one() + 1
    session.add(TaskArtifact(task_id=task.id, kind=kind, version=version,
                             body_md=body_md, created_by=actor.id))
    session.add(Chronicle(task_id=task.id, event_type="field", author_id=actor.id,
                          author_kind="agent" if actor.user_type == "agent" else "human",
                          message=f"Артефакт {kind} v{version} добавлен"))
    await session.commit()
    return version
