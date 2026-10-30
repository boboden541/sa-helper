"""Артефакты этапов: отчёты с версиями (ФТ-ah-38; расщепление journal.py, B2;
запись — в usecase/task/artifacts.py, B3)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_actor, get_session
from api.middleware.errors import ApiError
from repository.models import User
from usecase.task import artifacts as artifacts_uc

router = APIRouter()


# ---------- Артефакты этапов (ФТ-ah-38): отчёты с версиями ----------

@router.get("/tasks/{code}/artifacts/{kind}")
async def artifact_get(code: str, kind: str,
                       session: AsyncSession = Depends(get_session),
                       actor: User = Depends(get_actor)):
    import sqlalchemy as sa

    from repository.models import Task, TaskArtifact

    if kind not in ("dev_report", "review_report", "qa_report"):
        raise ApiError(400, "Неизвестный вид артефакта")
    task = (await session.execute(sa.select(Task).where(Task.code == code.upper()))).scalar_one_or_none()
    if task is None:
        raise ApiError(404, f"Задача {code} не найдена")
    rows = (await session.execute(
        sa.select(TaskArtifact).where(TaskArtifact.task_id == task.id, TaskArtifact.kind == kind)
        .order_by(TaskArtifact.version))).scalars().all()
    return {"versions": [{"version": r.version, "bodyMd": r.body_md,
                           "at": r.created_at.isoformat()} for r in rows]}


class ArtifactIn(BaseModel):
    body_md: str = Field(alias="bodyMd")
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


@router.post("/tasks/{code}/artifacts/{kind}")
async def artifact_add(code: str, kind: str, payload: ArtifactIn,
                       session: AsyncSession = Depends(get_session),
                       actor: User = Depends(get_actor)):
    import sqlalchemy as sa

    from repository.models import Task

    if kind not in ("dev_report", "review_report", "qa_report"):
        raise ApiError(400, "Неизвестный вид артефакта")
    task = (await session.execute(sa.select(Task).where(Task.code == code.upper()))).scalar_one_or_none()
    if task is None:
        raise ApiError(404, f"Задача {code} не найдена")
    version = await artifacts_uc.add_artifact(session, actor, task, kind, payload.body_md)
    return {"version": version}
