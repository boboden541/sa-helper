"""Контроллер задач: GET/POST/PATCH /api/v1/tasks (СТ §4.1.2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.dto.task_dto import TaskCardOut, TaskCreateIn, TaskListOut, TaskPatchIn
from api.deps import get_actor, get_session
from repository.models import User
from usecase.task.create_task import CreateTaskInput, create_task
from usecase.task.list_tasks import list_tasks
from usecase.task.patch_task import ApiNotFound, patch_task

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


def _card_out(c) -> TaskCardOut:
    return TaskCardOut(
        code=c.code, title=c.title, priority=c.priority, type=c.type,
        statusKey=c.status_key, storyCode=c.story_code, tags=c.tags, agent=c.agent,
    )


@router.get("", response_model=TaskListOut)
async def list_tasks_view(
    project: list[str] | None = Query(default=None),
    type: list[str] | None = Query(default=None),
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(get_actor),
):
    total, cards = await list_tasks(session, projects=project, types=type, q=q,
                                    limit=limit, offset=offset)
    return TaskListOut(total=total, items=[_card_out(c) for c in cards])


@router.post("", response_model=TaskCardOut)
async def create_task_view(payload: TaskCreateIn,
                           session: AsyncSession = Depends(get_session),
                           actor: User = Depends(get_actor)):
    created = await create_task(session, actor, CreateTaskInput(
        project_mnemonic=payload.project_id,
        type_key=payload.type,
        title=payload.title,
        priority=payload.priority,
        author_tag=payload.author_tag,
        tags=payload.tags,
        description_md=payload.description_md,
        story_code=payload.story_code,
    ))
    task = await _get_task_by_code(session, created.code)
    return _card_out(_to_card(task))


async def _get_task_by_code(session, code):
    import sqlalchemy as sa
    from repository.models import Task
    return (await session.execute(sa.select(Task).where(Task.code == code))).scalar_one_or_none()


def _to_card(task) -> TaskCard:
    from usecase.task.list_tasks import TaskCard
    return TaskCard(code=task.code, title=task.title, priority=task.priority,
                    type="", status_key=task.status_key)


@router.patch("/{code}", response_model=TaskCardOut)
async def patch_task_view(code: str, payload: TaskPatchIn,
                          session: AsyncSession = Depends(get_session),
                          actor: User = Depends(get_actor)):
    try:
        result = await patch_task(session, actor, code, payload.model_dump(exclude_none=True, by_alias=True),
                                  if_updated_at=payload.if_updated_at)
    except ApiNotFound:
        raise ApiError(404, f"Задача {code} не найдена")
    return _card_out(_to_card(result.task))


from api.middleware.errors import ApiError  # noqa: E402
