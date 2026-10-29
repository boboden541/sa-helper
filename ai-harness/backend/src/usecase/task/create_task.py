"""Создание задачи: task-code, модерация pending, теги, хроники (ФТ-ah-2, ФТ-ah-19)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from domain.model.enums import AUTHOR_TAGS
from domain.model.validators import DomainError, validate_description, validate_tags, validate_title
from repository.models import Chronicle, Notification, Project, Tag, Task, TaskTag, TaskType, User


@dataclass
class CreateTaskInput:
    project_mnemonic: str
    type_key: str
    title: str
    priority: str
    author_tag: str
    tags: list[str] = field(default_factory=list)
    description_md: str = ""
    story_code: str | None = None
    psi_path: str | None = None  # путь сохранения psi.md (только истории; null — дефолт .harness/psi/<код>/)
    repo_path: str | None = None  # целевой репозиторий в мультирепозитории проекта (относительный путь)
    # Модерация состоялась в чате Eve (ФТ-ah-19, третье исключение); проставляет только контур Eve
    eve_confirmed: bool = False


@dataclass
class CreatedTask:
    code: str
    status: str
    id: uuid.UUID


async def _one_or_none(session: AsyncSession, model, **filters):
    return (await session.execute(sa.select(model).filter_by(**filters))).scalar_one_or_none()


async def create_task(session: AsyncSession, actor: User, data: CreateTaskInput) -> CreatedTask:
    title = validate_title(data.title)
    description = validate_description(data.description_md or "")
    tags = validate_tags(data.author_tag, data.tags)
    if data.priority not in ("low", "medium", "high", "critical"):
        raise DomainError(
            "Приоритет обязателен и выбирается из списка: low, medium, high, critical",
            field="priority",
        )

    project = await _one_or_none(session, Project, mnemonic=data.project_mnemonic.upper())
    if project is None:
        raise DomainError(f"Проект {data.project_mnemonic!r} не найден", field="projectId")
    if project.is_archived:
        raise DomainError("Проект в архиве: создание задач недоступно", field="projectId")

    ttype = await _one_or_none(session, TaskType, key=data.type_key)
    if ttype is None:
        raise DomainError(f"Тип задачи {data.type_key!r} не найден", field="type")

    flow_version = (
        await session.execute(
            sa.select(sa.column("id"))
            .select_from(sa.table("flow_version"))
            .where(
                sa.column("task_type_id") == ttype.id,
                sa.column("is_current").is_(True),
                sa.column("is_published").is_(True),
            )
        )
    ).first()
    if flow_version is None:
        raise DomainError(
            f"У типа {data.type_key!r} нет опубликованной версии flow — опубликуйте её в настройках",
            field="type",
        )

    story: Task | None = None
    if data.story_code:
        story = await _one_or_none(session, Task, code=data.story_code.upper())
        if story is None:
            raise DomainError(f"История {data.story_code!r} не найдена", field="storyCode")

    author_is_agent = actor.user_type == "agent"

    # Модерация (ФТ-ah-19): pending по умолчанию; три исключения минуют его:
    #  1) подзадачи декомпозиции истории (агент + указана история);
    #  2) баг при родителе in testing;
    #  3) задача, подтверждённая «да» в чате Eve.
    skip_moderation = (
        (author_is_agent and story is not None)
        or (data.type_key == "bug" and story is not None and story.status_key == "in_testing")
        or data.eve_confirmed
    )
    start_status = "todo" if skip_moderation else "pending"

    # task-code: транзакционное выделение номера, номера не переиспользуются (ФТ-ah-2)
    next_number = (
        await session.execute(
            sa.update(Project)
            .where(Project.id == project.id)
            .values(next_number=Project.next_number + 1)
            .returning(Project.next_number)
        )
    ).scalar_one()

    # next_number seeded как 1 = «номер следующей задачи»; RETURNING вернул уже
    # инкрементированное значение, поэтому фактический номер — на единицу меньше
    allocated_number = next_number - 1

    task = Task(
        project_id=project.id,
        code=f"{project.mnemonic}-{allocated_number}",
        task_type_id=ttype.id,
        title=title,
        description_md=description,
        status_key=start_status,
        flow_version_id=flow_version.id,
        priority=data.priority,
        story_id=story.id if story else None,
        psi_path=(data.psi_path or None) if data.type_key == "story" else None,
        repo_path=await _validate_repo_path(project, data.repo_path),
        author_id=actor.id,
    )
    session.add(task)
    await session.flush()

    for label in tags:
        tag = await _one_or_none(session, Tag, label=label)
        if tag is None:
            try:
                # гонка «две задачи с новым тегом»: проигравшая сторона берёт существующий
                async with session.begin_nested():
                    tag = Tag(label=label, is_author=label in AUTHOR_TAGS)
                    session.add(tag)
                    await session.flush()
            except IntegrityError:
                tag = await _one_or_none(session, Tag, label=label)
                if tag is None:
                    raise
        session.add(TaskTag(task_id=task.id, tag_id=tag.id))

    session.add(
        Chronicle(
            task_id=task.id,
            event_type="transition",
            author_id=actor.id,
            author_kind="agent" if author_is_agent else "human",
            message=f"Задача создана, стартовый статус «{start_status}»",
        )
    )
    if not skip_moderation:
        session.add(
            Notification(
                code=task.code,
                event_key="pending_moderation",
                message=f"Задача {task.code} ждёт модерации: подтвердите или отклоните предложение",
            )
        )

    await session.commit()
    return CreatedTask(code=task.code, status=start_status, id=task.id)


async def _validate_repo_path(project, repo_path: str | None) -> str | None:
    """Целевой репозиторий задачи в мультирепозитории проекта (решение владельца
    29.10.2026): относительный путь, обязан быть git-репозиторием внутри папки
    проекта и не выходить за её пределы."""
    if not repo_path:
        return None
    from pathlib import Path

    from domain.model.validators import DomainError
    from infrastructure.paths import expand_host

    clean = repo_path.strip().strip("/")
    root = Path(expand_host(project.path)).resolve()
    candidate = (root / clean).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as err:
        raise DomainError("Репозиторий задачи должен лежать внутри папки проекта") from err
    if not (candidate / ".git").exists():
        raise DomainError(f"«{clean}» — не git-репозиторий внутри проекта (нет .git); "
                          "укажите подпапку с репозиторием")
    return clean
