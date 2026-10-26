"""Контроллер переходов: transitions + force + карточка с гейтами (СТ §4.2.1)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_actor, get_session
from api.middleware.errors import ApiError
from domain.model.validators import DomainError
from domain.transition.engine import Subject, allowed_targets
from domain.transition.graph import load_graph
from repository.models import Task, User
from usecase.task.gates import load_gate_data
from usecase.task.rights import assigned_statuses
from usecase.task.transition import TransitionDenied, apply_force, apply_transition

router = APIRouter(prefix="/api/v1/tasks", tags=["transitions"])


class TransitionIn(BaseModel):
    to: str
    reason: str | None = None
    model_config = ConfigDict(extra="forbid")


class ForceIn(BaseModel):
    to: str
    reason: str | None = None
    model_config = ConfigDict(extra="forbid")


class TransitionResult(BaseModel):
    applied: bool
    reason: str | None = None


async def _load_task_or_404(session: AsyncSession, code: str) -> Task:
    task = (await session.execute(
        sa_select_task(code)
    )).scalar_one_or_none()
    if task is None:
        raise ApiError(404, f"Задача {code} не найдена")
    return task


def sa_select_task(code: str):
    import sqlalchemy as sa

    return sa.select(Task).where(Task.code == code.upper())


def _human_subject() -> Subject:
    return Subject(kind="human")


@router.post("/{code}/transitions", response_model=TransitionResult)
async def transition_view(code: str, payload: TransitionIn,
                          session: AsyncSession = Depends(get_session),
                          actor: User = Depends(get_actor)):
    task = await _load_task_or_404(session, code)
    try:
        await apply_transition(session, actor, task.code, payload.to)
    except TransitionDenied as denied:
        if denied.status_code == 403:
            raise ApiError(403, denied.reason)
        return TransitionResult(applied=False, reason=denied.reason)
    except DomainError as err:
        raise ApiError(400, err.message, tech=err.tech)
    return TransitionResult(applied=True)


@router.post("/{code}/force", response_model=TransitionResult)
async def force_view(code: str, payload: ForceIn,
                     session: AsyncSession = Depends(get_session),
                     actor: User = Depends(get_actor)):
    task = await _load_task_or_404(session, code)
    try:
        await apply_force(session, actor, task.code, payload.to, payload.reason or "")
    except TransitionDenied as denied:
        raise ApiError(denied.status_code, denied.reason)
    return TransitionResult(applied=True)


class GateOut(BaseModel):
    allowed: list[str]
    denied: list[dict]


class TaskCardOut(BaseModel):
    code: str
    title: str
    priority: str
    type: str
    statusKey: str = Field(alias="statusKey")
    tags: list[str] = []
    descriptionMd: str = Field(alias="descriptionMd")
    storyCode: str | None = Field(default=None, alias="storyCode")
    psiPath: str | None = Field(default=None, alias="psiPath")
    gate: GateOut
    createdAt: str
    updatedAt: str
    blockedReason: str | None = None
    relations: list[dict] = []
    model_config = ConfigDict(populate_by_name=True)


@router.get("/{code}", response_model=TaskCardOut)
async def card_view(code: str,
                    session: AsyncSession = Depends(get_session),
                    actor: User = Depends(get_actor)):
    import sqlalchemy as sa

    from domain.model.enums import PRIORITY_RANK  # noqa: F401
    from repository.models import Project, TaskTag, Tag

    task = await _load_task_or_404(session, code)
    type_key = (await session.execute(
        sa.text("SELECT key FROM task_type WHERE id = :id"),
        {"id": str(task.task_type_id)},
    )).scalar_one()

    graph = await load_graph(session, task.flow_version_id)
    gates = await load_gate_data(session, task)
    subject: Subject
    if actor.user_type == "agent" and not actor.is_chat_bot:
        subject = Subject(kind="agent", user_id=str(actor.id),
                          assigned_statuses=await assigned_statuses(
                              session, actor.id, task.task_type_id))
    else:
        subject = _human_subject()
    decisions = allowed_targets(graph, task.status_key, subject, gates)

    tags = (await session.execute(
        sa.select(Tag.label).join(TaskTag, TaskTag.tag_id == Tag.id)
        .where(TaskTag.task_id == task.id)
    )).scalars().all()

    from repository.models import TaskRelation

    relations = (await session.execute(
        sa.select(TaskRelation.id, TaskRelation.kind, Task.code, Task.title)
        .join(Task, Task.id == TaskRelation.to_task)
        .where(TaskRelation.from_task == task.id))).all()
    rel_out = [{"id": str(rid), "kind": k, "code": rc, "title": rt}
               for rid, k, rc, rt in relations]
    story_code = None
    if task.story_id:
        story_code = (await session.execute(
            sa.select(Task.code).where(Task.id == task.story_id)
        )).scalar_one_or_none()

    return TaskCardOut(
        code=task.code, title=task.title, priority=task.priority, type=type_key,
        statusKey=task.status_key, tags=list(tags), descriptionMd=task.description_md,
        storyCode=story_code, psiPath=task.psi_path,
        gate=GateOut(
            allowed=[to for to, d in decisions.items() if d.allowed],
            denied=[{"to": to, "reason": d.reason}
                    for to, d in decisions.items() if not d.allowed],
        ),
        createdAt=task.created_at.isoformat(), updatedAt=task.updated_at.isoformat(),
        blockedReason=task.blocked_reason, relations=rel_out,
    )
