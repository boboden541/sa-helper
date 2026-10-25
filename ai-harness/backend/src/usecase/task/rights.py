"""Назначения агента в матрице — права на статусы (ФТ-ah-63)."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from repository.models import Assignment


async def assigned_statuses(session: AsyncSession, user_id, task_type_id) -> frozenset[str]:
    rows = (await session.execute(
        sa.select(Assignment.status_key).where(
            Assignment.user_id == user_id, Assignment.task_type_id == task_type_id)
    )).scalars()
    return frozenset(rows)
