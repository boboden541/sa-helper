"""Единая точка запросов «актуальная (current+published) версия flow».

Раньше это условие было продублировано в 8 местах (transition, list_tasks,
context_bundle, контроллеры settings/flow + projects, eve) — расхождение
любого из них тихо рассинхронизирует правила конвейера (анализ 03.11.2026).
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from repository.models import FlowVersion


def current_flow_version_sq(task_type_id_col):
    """Скалярный подзапрос id актуальной версии по колонке типа задачи
    (для запросов по таблице task — list_tasks, projects: одна JOIN-ветка,
    явный correlate по Task убирает неоднозначность FROM)."""
    from repository.models import Task

    fv = FlowVersion.__table__
    return (
        sa.select(fv.c.id)
        .where(fv.c.task_type_id == task_type_id_col,
               fv.c.is_current.is_(True), fv.c.is_published.is_(True))
        .correlate(Task)
        .scalar_subquery()
    )


async def current_flow_version_id(session: AsyncSession, task_type_id) -> uuid.UUID | None:
    """Id актуальной версии flow типа задачи; None — не публиковалась."""
    return (await session.execute(sa.select(FlowVersion.id).where(
        FlowVersion.task_type_id == task_type_id,
        FlowVersion.is_current.is_(True), FlowVersion.is_published.is_(True))
    )).scalar_one_or_none()
