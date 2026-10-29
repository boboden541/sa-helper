"""Контекстный бандл агента: скилл + постановка + чеклисты + хвост хроник (СТ §4.3.1)."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from repository.models import (
    Checklist, ChecklistItem, Chronicle, Project, Tag, Task, TaskRelation, TaskTag,
    TaskType,
)


async def build_context_md(session: AsyncSession, task: Task) -> str:
    type_key = (await session.execute(
        sa.select(TaskType.key).where(TaskType.id == task.task_type_id))).scalar_one()
    tags = (await session.execute(
        sa.select(Tag.label).join(TaskTag, TaskTag.tag_id == Tag.id)
        .where(TaskTag.task_id == task.id))).scalars().all()

    parts = [
        f"Задача {task.code} [{type_key}] — {task.title}",
        f"Статус: {task.status_key}; приоритет: {task.priority}; теги: {', '.join(tags)}",
        *( [f"Репозиторий доработки: {task.repo_path} (worktree и ветка task/<код> — в нём)"]
           if task.repo_path else [] ),
        f"\n## Постановка\n{task.description_md or '(описание пусто)'}",
    ]

    relations = (await session.execute(
        sa.select(TaskRelation.kind, Task.code, Task.title)
        .join(Task, Task.id == TaskRelation.to_task)
        .where(TaskRelation.from_task == task.id))).all()
    if relations:
        lines = [f"- {kind} {code} «{title}»" for kind, code, title in relations]
        parts.append("\n## Связи\n" + "\n".join(lines))

    # индекс задач проекта: коды соседей для declarations связей (relations_updates)
    siblings = (await session.execute(
        sa.select(Task.code, Task.title, Task.status_key)
        .join(Project, Project.id == Task.project_id)
        .where(Task.project_id == task.project_id,
               Task.status_key.notin_(("done", "canceled")), Task.id != task.id)
        .order_by(Task.code).limit(40))).all()
    if siblings:
        lines = [f"- {code} «{title}» — {status}" for code, title, status in siblings]
        parts.append("\n## Задачи проекта (для связей: что сначала, что потом, кто кого блокирует)\n"
                     + "\n".join(lines))

    # Допустимые переходы из текущего статуса: агент предлагает только их,
    # не догадывается о ключах статусов (инцидент AH-130: агент выдумал
    # «testing» вместо qa_ready — движок честно отказал, попытка сгорела)
    from repository.models import FlowStatus, FlowTransition, FlowVersion

    edges = (await session.execute(
        sa.select(FlowTransition.to_status, FlowTransition.runner, FlowTransition.display,
                  FlowStatus.label)
        .join(FlowVersion, FlowVersion.id == FlowTransition.flow_version_id)
        .join(FlowStatus, (FlowStatus.flow_version_id == FlowTransition.flow_version_id)
              & (FlowStatus.status_key == FlowTransition.to_status))
        .where(FlowVersion.task_type_id == task.task_type_id,
               FlowVersion.is_current.is_(True), FlowVersion.is_published.is_(True),
               FlowTransition.from_status == task.status_key))).all()
    if edges:
        lines = [f"- → {to} «{label}» — исполнитель: {runner}"
                 + (f" ({display})" if display else "") for to, runner, display, label in edges]
        parts.append("\n## Куда можно предлагать переход (только эти ключи статусов)\n"
                     + "\n".join(lines))

    checks = (await session.execute(
        sa.select(Checklist.kind, ChecklistItem.position, ChecklistItem.text,
                  ChecklistItem.status)
        .join(ChecklistItem, ChecklistItem.checklist_id == Checklist.id)
        .where(Checklist.task_id == task.id)
        .order_by(Checklist.kind, ChecklistItem.position))).all()
    if checks:
        lines = [f"- [{status}] {position}. {text}" for kind, position, text, status in checks]
        parts.append("\n## Чеклисты\n" + "\n".join(lines))

    tail = (await session.execute(
        sa.select(Chronicle.message)
        .where(Chronicle.task_id == task.id)
        .order_by(Chronicle.created_at.desc()).limit(20))).scalars().all()
    if tail:
        parts.append("\n## Хроника (последние события)\n" +
                     "\n".join(f"- {m}" for m in reversed(tail)))

    return "\n".join(parts)
