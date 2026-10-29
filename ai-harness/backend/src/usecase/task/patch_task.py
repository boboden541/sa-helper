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

    if "psiPath" in fields and fields["psiPath"] is not None:
        new_psi = str(fields["psiPath"]).strip()[:500] or None
        if new_psi != task.psi_path:
            task.psi_path = new_psi
            events.append("изменён путь сохранения ПСИ")

    if "tags" in fields and fields["tags"] is not None:
        from domain.model.enums import AUTHOR_TAGS
        from domain.model.validators import validate_tags
        from repository.models import Tag, TaskTag

        labels = validate_tags("by_human", fields["tags"])  # авторский гарантируется
        if "by_ai" in fields["tags"]:
            # агент-автор: by_human из запроса игнорируется, авторский тег восстанавливается
            labels = sorted({l for l in labels if l != "by_human"} | {"by_ai"})
        current = (await session.execute(
            sa.select(Tag.label).join(TaskTag, TaskTag.tag_id == Tag.id)
            .where(TaskTag.task_id == task.id))).scalars().all()
        if set(labels) != set(current):
            await session.execute(sa.delete(TaskTag).where(TaskTag.task_id == task.id))
            for label in labels:
                tag = (await session.execute(sa.select(Tag).where(Tag.label == label))).scalar_one_or_none()
                if tag is None:
                    tag = Tag(label=label, is_author=label in AUTHOR_TAGS)
                    session.add(tag)
                    await session.flush()
                session.add(TaskTag(task_id=task.id, tag_id=tag.id))
            events.append("теги изменены")
            # осиротевшие теги удаляются (ФТ-ah-6)
            for label in set(current) - set(labels):
                orphans = (await session.execute(
                    sa.select(sa.func.count()).select_from(TaskTag)
                    .join(Tag, Tag.id == TaskTag.tag_id)
                    .where(Tag.label == label))).scalar_one()
                if orphans == 0:
                    await session.execute(sa.delete(Tag).where(Tag.label == label))

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
