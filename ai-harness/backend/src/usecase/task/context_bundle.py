"""Контекстный бандл агента: скилл + постановка + чеклисты + хвост хроник (СТ §4.3.1)."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from repository.models import (
    Checklist, ChecklistItem, Chronicle, Tag, Task, TaskRelation, TaskTag, TaskType,
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
        f"\n## Постановка\n{task.description_md or '(описание пусто)'}",
    ]

    relations = (await session.execute(
        sa.select(TaskRelation.kind, Task.code, Task.title)
        .join(Task, Task.id == TaskRelation.to_task)
        .where(TaskRelation.from_task == task.id))).all()
    if relations:
        lines = [f"- {kind} {code} «{title}»" for kind, code, title in relations]
        parts.append("\n## Связи\n" + "\n".join(lines))

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
