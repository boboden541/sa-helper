"""Связи между задачами: do_after / blocked_by (БФТ: блок «Связанные», B3).

Логика перенесена из контроллера tasks; контроллер проверяет kind,
находит задачу-источник и маппит ошибки на HTTP-коды.
"""

from __future__ import annotations

import sqlalchemy as sa

from sqlalchemy.ext.asyncio import AsyncSession

from domain.model.validators import DomainError
from repository.models import Task, TaskRelation
from usecase.task.patch_task import ApiNotFound


async def add(session: AsyncSession, task: Task, *, to_code: str, kind: str) -> TaskRelation:
    """Связывает задачу с `to_code`; дубликат и самосвязь — DomainError,
    нет задачи-приёмника — ApiNotFound. Возвращает созданную связь."""
    other = (await session.execute(
        sa.select(Task).where(Task.code == to_code.upper()))).scalar_one_or_none()
    if other is None:
        raise ApiNotFound(to_code)
    if other.id == task.id:
        raise DomainError("Нельзя связать задачу с собой")
    dup = (await session.execute(
        sa.select(sa.func.count()).select_from(TaskRelation)
        .where(TaskRelation.from_task == task.id, TaskRelation.to_task == other.id,
               TaskRelation.kind == kind))).scalar_one()
    if dup:
        raise DomainError("Такая связь уже есть")
    rel = TaskRelation(from_task=task.id, to_task=other.id, kind=kind)
    session.add(rel)
    await session.commit()
    return rel


async def delete(session: AsyncSession, task: Task, relation_id: str) -> TaskRelation | None:
    """Удаляет связь задачи (только исходящую — from_task); None — связи нет."""
    import uuid as uuid_mod

    rel = (await session.execute(
        sa.select(TaskRelation).where(TaskRelation.id == uuid_mod.UUID(relation_id),
                                      TaskRelation.from_task == task.id))).scalar_one_or_none()
    if rel is None:
        return None
    await session.execute(sa.delete(TaskRelation).where(TaskRelation.id == rel.id))
    await session.commit()
    return rel
