"""Контроллер задач: GET/POST/PATCH /api/v1/tasks (СТ §4.1.2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from api.dto.task_dto import TaskCardOut, TaskCreateIn, TaskListOut, TaskPatchIn
from api.deps import get_actor, get_session
from domain.model.validators import DomainError
from repository.models import User
from usecase.task import relations as relations_uc
from usecase.task.create_task import CreateTaskInput, create_task
from usecase.task.list_tasks import list_tasks
from usecase.task.patch_task import ApiNotFound, patch_task

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


def _card_out(c) -> TaskCardOut:
    return TaskCardOut(
        code=c.code, title=c.title, priority=c.priority, type=c.type,
        statusKey=c.status_key, storyCode=c.story_code, tags=c.tags, agent=c.agent,
        project=c.project, psiPath=c.psi_path, repoPath=c.repo_path, tokensUsed=c.tokens_used,
    )


@router.get("", response_model=TaskListOut)
async def list_tasks_view(
    project: list[str] | None = Query(default=None),
    type: list[str] | None = Query(default=None),
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    exclude_terminal: bool = Query(default=False, alias="excludeTerminal"),
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(get_actor),
):
    total, cards = await list_tasks(session, projects=project, types=type, q=q,
                                    limit=limit, offset=offset,
                                    exclude_terminal=exclude_terminal)
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
        psi_path=payload.psi_path,
        repo_path=payload.repo_path,
    ))
    task = await _get_task_by_code(session, created.code)
    return _card_out(_to_card(task))


async def _load_task_or_404(session, code):
    t = await _get_task_by_code(session, code.upper())
    if t is None:
        raise ApiError(404, f"Задача {code} не найдена")
    return t


async def _get_task_by_code(session, code):
    import sqlalchemy as sa
    from repository.models import Task
    return (await session.execute(sa.select(Task).where(Task.code == code))).scalar_one_or_none()


def _to_card(task) -> TaskCard:
    from usecase.task.list_tasks import TaskCard
    return TaskCard(code=task.code, title=task.title, priority=task.priority,
                    type="", status_key=task.status_key, psi_path=task.psi_path,
                       repo_path=task.repo_path)


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


# ---------- Связи между задачами (БФТ: блок «Связанные») + привязка к истории ----------

class RelationIn(BaseModel):
    toCode: str
    kind: str  # do_after | blocked_by
    model_config = ConfigDict(extra="forbid")


@router.post("/{code}/relations")
async def relation_add(code: str, payload: RelationIn,
                       session: AsyncSession = Depends(get_session),
                       actor: User = Depends(get_actor)):
    if payload.kind not in ("do_after", "blocked_by"):
        raise ApiError(400, "Тип связи: do_after или blocked_by")
    task = await _load_task_or_404(session, code)
    try:
        rel = await relations_uc.add(session, task, to_code=payload.toCode, kind=payload.kind)
    except ApiNotFound as err:
        raise ApiError(404, str(err))
    except DomainError as err:
        raise ApiError(400, err.message)
    return {"id": str(rel.id)}


@router.delete("/{code}/relations/{relation_id}")
async def relation_del(code: str, relation_id: str,
                       session: AsyncSession = Depends(get_session),
                       actor: User = Depends(get_actor)):
    task = await _load_task_or_404(session, code)
    rel = await relations_uc.delete(session, task, relation_id)
    if rel is None:
        raise ApiError(404, "Связь не найдена")
    return {"ok": True}


class StoryLinkIn(BaseModel):
    storyCode: str | None = None  # null — отвязать
    model_config = ConfigDict(extra="forbid")


@router.post("/{code}/story-link")
async def story_link(code: str, payload: StoryLinkIn,
                     session: AsyncSession = Depends(get_session),
                     actor: User = Depends(get_actor)):
    """Привязка/отвязка/перепривязка задачи к истории (решение владельца 26.10.2026).
    Пересчитывает зеркала обеих историй."""
    import sqlalchemy as sa

    from repository.models import Chronicle, Task, TaskType

    task = await _load_task_or_404(session, code)
    old_story_id = task.story_id
    if payload.storyCode:
        story = (await session.execute(
            sa.select(Task).where(Task.code == payload.storyCode.upper()))).scalar_one_or_none()
        if story is None:
            raise ApiError(404, f"История {payload.storyCode} не найдена")
        tkey = (await session.execute(
            sa.select(TaskType.key).where(TaskType.id == story.task_type_id))).scalar_one()
        if tkey != "story":
            raise ApiError(400, f"{story.code} — не история")
        if story.id == task.id:
            raise ApiError(400, "Нельзя привязать задачу к самой себе")
        task.story_id = story.id
        session.add(Chronicle(task_id=task.id, event_type="field", author_id=actor.id,
                              author_kind="human",
                              message=f"Задача привязана к истории {story.code}"))
    else:
        task.story_id = None
        if old_story_id:
            old = await session.get(Task, old_story_id)
            session.add(Chronicle(task_id=task.id, event_type="field", author_id=actor.id,
                                  author_kind="human",
                                  message=f"Задача отвязана от истории {old.code if old else '?'}"))
    await session.commit()

    from usecase.story.mirror import recompute_story_mirroring

    touched = []
    for sid in filter(None, {old_story_id, task.story_id}):
        st = await session.get(Task, sid)
        if st is not None:
            rule = await recompute_story_mirroring(session, st)
            if rule:
                touched.append(f"{st.code}:{rule}")
    return {"ok": True, "mirrored": touched}
