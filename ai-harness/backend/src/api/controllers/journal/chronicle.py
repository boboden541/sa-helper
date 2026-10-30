"""Хроники задачи, уведомления, комментарии (расщепление journal.py, B2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_actor, get_session
from api.middleware.errors import ApiError
from repository.models import User
from usecase.journal import chronicle as chronicle_uc
from usecase.journal import notifications as notif_uc

router = APIRouter()


@router.get("/tasks/{code}/chronicle")
async def chronicle_view(code: str, type: str | None = None,
                         session: AsyncSession = Depends(get_session),
                         actor: User = Depends(get_actor)):
    import sqlalchemy as sa

    from repository.models import Task

    task = (await session.execute(
        sa.select(Task).where(Task.code == code.upper()))).scalar_one_or_none()
    if task is None:
        raise ApiError(404, f"Задача {code} не найдена")
    return {"items": await chronicle_uc.list_for_task(session, task.id, event_type=type)}


@router.get("/notifications")
async def notifications_view(session: AsyncSession = Depends(get_session),
                             actor: User = Depends(get_actor)):
    return {"items": await notif_uc.list_open(session)}


# ---------- Комментарии (ФТ-ah-11) ----------

@router.get("/tasks/{code}/comments")
async def comments_get(code: str, session: AsyncSession = Depends(get_session),
                       actor: User = Depends(get_actor)):
    import sqlalchemy as sa

    from repository.models import Task, TaskComment

    task = (await session.execute(sa.select(Task).where(Task.code == code.upper()))).scalar_one_or_none()
    if task is None:
        raise ApiError(404, f"Задача {code} не найдена")
    rows = (await session.execute(
        sa.select(TaskComment, User.name).join(User, User.id == TaskComment.author_id)
        .where(TaskComment.task_id == task.id)
        .order_by(TaskComment.created_at))).all()
    return [{"id": str(c.id), "author": name, "body": c.body,
             "at": c.created_at.isoformat()} for c, name in rows]


class CommentIn(BaseModel):
    body: str
    model_config = ConfigDict(extra="forbid")


@router.post("/tasks/{code}/comments")
async def comments_add(code: str, payload: CommentIn,
                       session: AsyncSession = Depends(get_session),
                       actor: User = Depends(get_actor)):
    import sqlalchemy as sa

    from repository.models import Task, TaskComment

    if not payload.body.strip():
        raise ApiError(400, "Комментарий пуст")
    task = (await session.execute(sa.select(Task).where(Task.code == code.upper()))).scalar_one_or_none()
    if task is None:
        raise ApiError(404, f"Задача {code} не найдена")
    c = TaskComment(task_id=task.id, author_id=actor.id, body=payload.body.strip())
    session.add(c)
    await session.commit()
    return {"id": str(c.id)}
