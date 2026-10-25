"""Правка атрибутов задачи: частичные изменения, LWW, события «поле» (ФТ-ah-8, решение 3.1-9)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from domain.model.validators import DomainError, validate_description, validate_title
from repository.models import Chronicle, Task, User


@dataclass
class PatchResult:
    task: Task
    changed_by_other: bool


async def patch_task(
    session: AsyncSession,
    actor: User,
    code: str,
    fields: dict,
    if_updated_at: datetime | None = None,
) -> PatchResult:
    """Частичное обновление: название, описание, приоритет.

    Каждое изменение — событие «поле» в хроники (ФТ-ah-43); ответ несёт свежую копию
    карточки и флаг конфликта для баннера «карточка обновлена другим участником» (решение 3.1-9).
    """
    task = (await session.execute(sa.select(Task).where(Task.code == code.upper()))).scalar_one_or_none()
    if task is None:
        raise ApiNotFound(code)

    changed_by_other = (
        if_updated_at is not None and task.updated_at is not None and task.updated_at != if_updated_at
    )

    events: list[str] = []
    if "title" in fields and fields["title"] is not None:
        new_title = validate_title(fields["title"])
        if new_title != task.title:
            task.title = new_title
            events.append("название изменено")
    if "descriptionMd" in fields and fields["descriptionMd"] is not None:
        new_desc = validate_description(fields["descriptionMd"])
        if new_desc != task.description_md:
            task.description_md = new_desc
            events.append("описание изменено")
    if "priority" in fields and fields["priority"] is not None:
        if fields["priority"] not in ("low", "medium", "high", "critical"):
            raise DomainError("Недопустимый приоритет", field="priority")
        if fields["priority"] != task.priority:
            task.priority = fields["priority"]
            events.append("приоритет изменён")

    if events:
        task.updated_at = datetime.now(task.updated_at.tzinfo) if task.updated_at.tzinfo else datetime.now()
        for message in events:
            session.add(
                Chronicle(
                    task_id=task.id,
                    event_type="field",
                    author_id=actor.id,
                    author_kind="agent" if actor.user_type == "agent" else "human",
                    message=message,
                )
            )
    await session.commit()
    return PatchResult(task=task, changed_by_other=changed_by_other)


class ApiNotFound(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(f"Задача {code} не найдена")
        self.code = code
