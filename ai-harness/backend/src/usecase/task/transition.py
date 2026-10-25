"""Применение перехода/форса: движок → запись → хроники (СТ §4.2.1, ФТ-ah-28…32)."""

from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from domain.transition.engine import Subject, check_edge, check_force
from domain.transition.graph import load_graph
from domain.model.validators import DomainError
from repository.models import Chronicle, Task, User
from usecase.task.gates import load_gate_data
from usecase.task.rights import assigned_statuses


class TransitionDenied(Exception):
    """Отказ движка: applied=False с человекочитаемой причиной."""

    def __init__(self, reason: str, status_code: int = 200) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


async def _subject_for(session: AsyncSession, actor: User | None, task: Task,
                       kind: str | None = None) -> Subject:
    if kind:
        return Subject(kind=kind)
    if actor is None:
        return Subject(kind="auto")
    if actor.user_type == "agent":
        if actor.is_chat_bot:
            return Subject(kind="eve", user_id=str(actor.id))
        return Subject(
            kind="agent", user_id=str(actor.id),
            assigned_statuses=await assigned_statuses(session, actor.id, task.task_type_id),
        )
    return Subject(kind="human", user_id=str(actor.id))


async def _load_task(session: AsyncSession, code: str) -> Task:
    task = (await session.execute(
        sa.select(Task).where(Task.code == code.upper())
    )).scalar_one_or_none()
    if task is None:
        raise DomainError(f"Задача {code} не найдена", tech="task not found")
    return task


async def apply_transition(session: AsyncSession, actor: User | None, code: str,
                           to: str, *, subject_kind: str | None = None,
                           rule_code: str | None = None) -> Task:
    """Валидный переход по flow. Отказ по гейту → TransitionDenied (applied=False);
    отказ по правам агента → 403 + событие «запрет» (ФТ-ah-27); недопустимое ребро → 400."""
    task = await _load_task(session, code)
    subject = await _subject_for(session, actor, task, subject_kind)
    graph = await load_graph(session, task.flow_version_id)

    if graph.edge(task.status_key, to) is None:
        raise DomainError(
            f"Переход «{task.status_key}» → «{to}» не предусмотрен flow задачи",
            tech=f"edge missing, from={task.status_key}, to={to}",
        )

    gates = await load_gate_data(session, task)
    decision = check_edge(graph, task.status_key, to, subject, gates)
    if not decision.allowed:
        if subject.kind == "agent":
            await _record_denial(session, task, actor, decision.reason)
        raise TransitionDenied(decision.reason,
                               status_code=403 if subject.kind == "agent" else 200)

    prev_label = graph.statuses[task.status_key].label
    task.status_key = to
    task.retry_count = 0  # счётчик попыток сбрасывается при входе в статус (ФТ-ah-33)
    task.updated_at = dt.datetime.now(dt.timezone.utc)
    if task.reserved_by is not None:
        # перехват человеком/перевод: резерв снимается, агент прервёт работу (ФТ-ah-32)
        task.reserved_by = None
        task.reserved_at = None
        task.heartbeat_at = None

    session.add(Chronicle(
        task_id=task.id, event_type="transition",
        author_id=None if subject.kind == "auto" else (actor.id if actor else None),
        author_kind=subject.kind, rule_code=rule_code,
        message=f"Перевод: «{prev_label}» → «{graph.statuses[to].label}»"
                + (f" (правило {rule_code})" if rule_code else ""),
    ))
    from usecase.journal.notifications import on_transition

    task_for_hook = task
    task_for_hook.status_key = to
    await on_transition(session, task_for_hook, to)
    await session.commit()
    return task


async def apply_force(session: AsyncSession, actor: User, code: str, to: str,
                      reason: str) -> Task:
    """Форс-переход: только человек, причина обязательна, любой статус (ФТ-ah-28)."""
    task = await _load_task(session, code)
    subject = await _subject_for(session, actor, task)
    graph = await load_graph(session, task.flow_version_id)

    decision = check_force(graph, task.status_key, to, subject, reason)
    if not decision.allowed:
        raise TransitionDenied(decision.reason, status_code=403 if subject.kind in ("agent", "auto") else 400)

    prev_label = graph.statuses[task.status_key].label
    task.status_key = to
    task.retry_count = 0
    task.updated_at = dt.datetime.now(dt.timezone.utc)
    task.reserved_by = None
    task.reserved_at = None
    task.heartbeat_at = None
    session.add(Chronicle(
        task_id=task.id, event_type="force", author_id=actor.id,
        author_kind="human",
        message=f"Форс: «{prev_label}» → «{graph.statuses[to].label}» — {reason.strip()} "
                "(ручное вмешательство)",
    ))
    from usecase.journal.notifications import on_transition

    await on_transition(session, task, to)
    await session.commit()
    return task


async def _record_denial(session: AsyncSession, task: Task, actor: User | None,
                         reason: str) -> None:
    """Событие «запрет»; повторное нарушение → blocked (ФТ-ah-27)."""
    session.add(Chronicle(
        task_id=task.id, event_type="denied",
        author_id=actor.id if actor else None, author_kind="agent",
        message=f"Попытка агента отклонена: {reason}",
    ))
    denials = (await session.execute(
        sa.select(sa.func.count()).select_from(Chronicle)
        .where(Chronicle.task_id == task.id, Chronicle.event_type == "denied")
    )).scalar_one()
    if denials >= 2:
        task.status_key = "blocked"
        task.blocked_reason = "Повторные нарушения прав агента"
        session.add(Chronicle(
            task_id=task.id, event_type="transition", author_kind="auto",
            rule_code="DENY",
            message="Автоблокировка: повторные нарушения прав агента",
        ))
    await session.commit()
