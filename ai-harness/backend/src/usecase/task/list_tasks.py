"""Выдача списка задач: фильтры, триграммный поиск, правила очереди (ФТ-ah-4, НФТ-ah-1)."""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from domain.model.enums import PRIORITY_RANK
from repository.models import (
    FlowStatus,
    FlowVersion,
    Project,
    Task,
    TaskRun,
    TaskType,
    User,
)


@dataclass
class TaskCard:
    code: str
    title: str
    priority: str
    type: str
    status_key: str
    project: str = ""  # мнемоника проекта (фильтр доски/списка, счётчики панели)
    psi_path: str | None = None
    repo_path: str | None = None
    story_code: str | None = None
    tags: list[str] = field(default_factory=list)
    agent: dict | None = None
    tokens_used: int = 0  # сумма токенов всех прогонов (формат «1300К»)
    tokens_input: int = 0  # разбивка: вход
    tokens_output: int = 0  # разбивка: выход
    tokens_cache: int = 0  # разбивка: кэш
    gate: dict = field(default_factory=lambda: {"allowed": [], "denied": []})


def build_query(projects: list[str] | None = None,
                types: list[str] | None = None,
                q: str | None = None,
                exclude_terminal: bool = False):
    """SELECT задач с сортировкой очереди: приоритет → баги выше задач → старые выше (ФТ-ah-4).

    exclude_terminal (решение владельца 28.10.2026): доска запрашивает без
    терминальных статусов, список — целиком; терминальность — по flow-версии
    самой задачи."""
    type_t = TaskType.__table__
    flow_status_t = FlowStatus.__table__
    flow_version_t = FlowVersion.__table__
    # код истории задачи (доска группирует задачи в полосы по storyCode)
    story_t = sa.alias(Task.__table__)
    story_sq = (
        sa.select(story_t.c.code)
        .where(story_t.c.id == Task.story_id)
        .correlate(Task).scalar_subquery()
    )

    proj_t = Project.__table__
    # суммарный расход токенов по всем прогонам задачи (решение владельца 27.10.2026);
    # разбивка вход/выход/кэш — для раскрытия по клику (фича 30.10.2026)
    def _tok_sq(cols):
        return sa.select(sa.func.coalesce(sa.func.sum(cols), 0)) \
            .where(TaskRun.task_id == Task.id).correlate(Task).scalar_subquery()
    query = (
        sa.select(
            Task,
            type_t.c.key.label("type_key"),
            User.name.label("agent_name"),
            proj_t.c.mnemonic.label("project_mnemonic"),
            story_sq.label("story_code"),
            _tok_sq(TaskRun.input_tokens + TaskRun.output_tokens + TaskRun.cache_tokens).label("tokens_used"),
            _tok_sq(TaskRun.input_tokens).label("tokens_input"),
            _tok_sq(TaskRun.output_tokens).label("tokens_output"),
            _tok_sq(TaskRun.cache_tokens).label("tokens_cache"),
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

    if exclude_terminal:
        # терминальность — по АКТУАЛЬНОЙ версии flow типа задачи
        # (решение владельца 28.10.2026: задачи всегда живут на current)
        cur_fv = (
            sa.select(flow_version_t.c.id)
            .where(flow_version_t.c.task_type_id == Task.task_type_id,
                   flow_version_t.c.is_current.is_(True),
                   flow_version_t.c.is_published.is_(True))
            .correlate(Task).scalar_subquery()
        )
        query = query.outerjoin(
            flow_status_t,
            sa.and_(flow_status_t.c.flow_version_id == cur_fv,
                    flow_status_t.c.status_key == Task.status_key),
        ).where(sa.or_(flow_status_t.c.is_terminal.is_(None),
                       flow_status_t.c.is_terminal.is_(False)))
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
    exclude_terminal: bool = False,
) -> tuple[int, list[TaskCard]]:
    """Возвращает (total, карточки) по фильтрам и правилам очереди (ФТ-ah-4)."""
    base = build_query(projects=projects, types=types, q=q,
                       exclude_terminal=exclude_terminal)
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
            psi_path=row.Task.psi_path,
            repo_path=row.Task.repo_path,
            story_code=row.story_code,
            agent={"name": row.agent_name} if row.agent_name else None,
            tokens_used=int(row.tokens_used or 0),
            tokens_input=int(row.tokens_input or 0),
            tokens_output=int(row.tokens_output or 0),
            tokens_cache=int(row.tokens_cache or 0),
        )
        for row in rows
    ]
    return total, cards
