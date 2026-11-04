"""Версионирование эталона постановки (решение владельца 03.11.2026).

Эталон задачи = описание из БД harness (task.ref_hash — sha256, task.ref_version —
человекочитаемая версия). Эталон истории = описание + состав и постановки детей:
любое их изменение поднимает ref_version истории.

План работы (чеклист) несёт source_ref_version — «какой версией эталона заверен».
План устарел ⟺ source_ref_version < ref_version: факт сравнения чисел, не
догадка агента. psi-чеклист заверяется регистрацией версии документа,
остальные чеклисты — обновлением (put_checklist).
"""

from __future__ import annotations

import hashlib

import sqlalchemy as sa
from repository.models import Checklist, Chronicle, Task, TaskType
from sqlalchemy.ext.asyncio import AsyncSession


def desc_hash(text: str | None) -> str:
    """sha256 описания из БД — решает «менялось ли содержание» без парсинга."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


async def is_story(session: AsyncSession, task: Task) -> bool:
    return (
        await session.execute(sa.select(TaskType.key).where(TaskType.id == task.task_type_id))
    ).scalar_one_or_none() == "story"


async def bump_reference(session: AsyncSession, task: Task, cause: str) -> int:
    """Эталон задачи изменился: версия +1, событие в хроники (rule REF)."""
    task.ref_version = (task.ref_version or 1) + 1
    session.add(
        Chronicle(
            task_id=task.id,
            event_type="field",
            author_kind="auto",
            rule_code="REF",
            message=f"Эталон постановки → v{task.ref_version} ({cause}); "
            "зависимые чеклисты подлежат пересмотру",
        )
    )
    return task.ref_version


async def on_description_changed(session: AsyncSession, task: Task) -> None:
    """Хук patch_task: содержание описания изменилось — хэш/версия задачи и
    версия эталона родительской истории (постановка ребёнка — часть её эталона)."""
    new_hash = desc_hash(task.description_md)
    if task.ref_hash is not None and new_hash == task.ref_hash:
        return
    task.ref_hash = new_hash
    await bump_reference(session, task, "изменено описание")
    if task.story_id is not None:
        story = await session.get(Task, task.story_id)
        if story is not None:
            await bump_reference(session, story, f"изменена постановка задачи {task.code}")


async def psi_plan_ref_version(session: AsyncSession, story_id) -> int | None:
    """Версия эталона, которой заверён psi-план (None — плана нет)."""
    return (
        await session.execute(
            sa.select(Checklist.source_ref_version).where(
                Checklist.task_id == story_id, Checklist.kind == "psi"
            )
        )
    ).scalar_one_or_none()
