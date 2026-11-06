"""Контроллер переходов: transitions + force + карточка с гейтами (СТ §4.2.1)."""

from __future__ import annotations

from domain.model.validators import DomainError
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from repository.models import Task, User
from sqlalchemy.ext.asyncio import AsyncSession
from usecase.task.transition import TransitionDenied, apply_force, apply_transition

from api.deps import get_actor, get_session
from api.dto.task_dto import TaskCardOut
from api.middleware.errors import ApiError

router = APIRouter(prefix="/api/v1/tasks", tags=["transitions"])


class TransitionIn(BaseModel):
    to: str
    reason: str | None = None
    # ФТ-FNR15-07: ручной переход требует комментария (что сделано, почему перевод)
    comment: str = ""
    model_config = ConfigDict(extra="forbid")


class ForceIn(BaseModel):
    to: str
    reason: str | None = None
    model_config = ConfigDict(extra="forbid")


class TransitionResult(BaseModel):
    applied: bool
    reason: str | None = None


async def _load_task_or_404(session: AsyncSession, code: str) -> Task:
    task = (await session.execute(sa_select_task(code))).scalar_one_or_none()
    if task is None:
        raise ApiError(404, f"Задача {code} не найдена")
    return task


def sa_select_task(code: str):
    import sqlalchemy as sa

    return sa.select(Task).where(Task.code == code.upper())


@router.post("/{code}/transitions", response_model=TransitionResult)
async def transition_view(
    code: str,
    payload: TransitionIn,
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(get_actor),
):
    task = await _load_task_or_404(session, code)
    # ФТ-FNR15-07: ручной переход без комментария отклоняется (след «что сделано»
    # обязателен); агентские переходы комментирует система (выжимка отчёта)
    if not payload.comment.strip():
        raise ApiError(400, "Укажите комментарий: что сделано и почему переводите")
    try:
        await apply_transition(session, actor, task.code, payload.to, comment=payload.comment)
    except TransitionDenied as denied:
        if denied.status_code == 403:
            raise ApiError(403, denied.reason)
        return TransitionResult(applied=False, reason=denied.reason)
    except DomainError as err:
        raise ApiError(400, err.message, tech=err.tech)
    return TransitionResult(applied=True)


@router.post("/{code}/force", response_model=TransitionResult)
async def force_view(
    code: str,
    payload: ForceIn,
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(get_actor),
):
    task = await _load_task_or_404(session, code)
    try:
        await apply_force(session, actor, task.code, payload.to, payload.reason or "")
    except TransitionDenied as denied:
        raise ApiError(denied.status_code, denied.reason)
    return TransitionResult(applied=True)


@router.get("/{code}", response_model=TaskCardOut)
async def card_view(
    code: str, session: AsyncSession = Depends(get_session), actor: User = Depends(get_actor)
):
    """Карточка: сборка в usecase/task/card_view (анализ 03.11.2026)."""
    from usecase.task.card_view import build_task_card

    try:
        return await build_task_card(session, code, actor)
    except DomainError as err:
        raise ApiError(404, err.message) from err
