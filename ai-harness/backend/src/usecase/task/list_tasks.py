"""Выдача списка задач: фильтры, триграммный поиск, правила очереди (ФТ-ah-4, НФТ-ah-1)."""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from domain.model.enums import PRIORITY_RANK
from repository.models import Project, Task, TaskType, User


@dataclass
class TaskCard:
    code: str
    title: str
    priority: str
    type: str
    status_key: str
    project: str = ""  # мнемоника проекта (фильтр доски/списка, счётчики панели)
    story_code: str | None = None
    tags: list[str] = field(default_factory=list)
    agent: dict | None = None
    gate: dict = field(default_factory=lambda: {"allowed": [], "denied": []})


def build_query(projects: list[str] | None = None,
                types: list[str] | None = None,
                q: str | None = None):
    """SELECT задач с сортировкой очереди: приоритет → баги выше задач → старые выше (ФТ-ah-4)."""
    type_t = TaskType.__table__

    proj_t = Project.__table__
    query = (
        sa.select(
            Task,
            type_t.c.key.label("type_key"),
            User.name.label("agent_name"),
            proj_t.c.mnemonic.label("project_mnemonic"),
        )
        .join(type_t, type_t.c.id == Task.task_type_id)
        .outerjoin(User, User.id == Task.reserved_by)
        .outerjoin(proj_t, proj_t.c.id == Task.project_id)
        .order_by(
            sa.case(PRIORITY_RANK, value=Task.priority, else_=9),
            sa.case({"bug": 0}, value=type_t.c.key, else_=1),
            Task.created_at.asc(),
            Task.code.asc(),
        )
    )

    if projects:
        query = query.where(proj_t.c.mnemonic.in_([p.upper() for p in projects]))
    if types:
        query = query.where(type_t.c.key.in_(types))
    if q and q.strip():
        needle = q.strip()
        # Триграммный нечёткий поиск по названию + точный/префиксный по task-code (НФТ-ah-1)
        query = query.where(
            sa.or_(Task.title.ilike(f"%{needle}%"), Task.code.ilike(f"{needle}%"))
        )
    return query


async def list_tasks(
    session: AsyncSession,
    projects: list[str] | None = None,
    types: list[str] | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list[TaskCard]]:
    """Возвращает (total, карточки) по фильтрам и правилам очереди (ФТ-ah-4)."""
    base = build_query(projects=projects, types=types, q=q)
    total = (await session.execute(
        sa.select(sa.func.count()).select_from(base.subquery())
    )).scalar_one()
    rows = (await session.execute(base.limit(limit).offset(offset))).all()
    cards = [
        TaskCard(
            code=row.Task.code,
            title=row.Task.title,
            priority=row.Task.priority,
            type=row.type_key,
            status_key=row.Task.status_key,
            project=row.project_mnemonic or "",
            agent={"name": row.agent_name} if row.agent_name else None,
        )
        for row in rows
    ]
    return total, cards
