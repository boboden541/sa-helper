"""Контроллеры этапа 5: хроники, уведомления, ПСИ, Eve, очередь (СТ §4.5, §5.6)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_actor, get_session
from api.middleware.errors import ApiError
from domain.model.validators import DomainError
from repository.models import User
from usecase.assistant import eve as eve_uc
from usecase.journal import chronicle as chronicle_uc
from usecase.journal import notifications as notif_uc
from usecase.story import psi as psi_uc
from usecase.task.queue_snapshot import snapshot

router = APIRouter(prefix="/api/v1", tags=["journal"])


def _400(fn):
    async def wrapper(*args, **kw):
        try:
            return await fn(*args, **kw)
        except DomainError as err:
            raise ApiError(400, err.message, tech=err.tech)
    return wrapper


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


# ---------- ПСИ ----------

class PsiSectionIn(BaseModel):
    heading: str = ""
    items: list[dict] = []
    model_config = ConfigDict(extra="forbid")


class PsiCreateIn(BaseModel):
    sections: list[PsiSectionIn]
    model_config = ConfigDict(extra="forbid")


class PsiRunIn(BaseModel):
    results: list[dict]
    model_config = ConfigDict(extra="forbid")


@router.get("/stories/{code}/psi")
@_400
async def psi_get(code: str, session: AsyncSession = Depends(get_session),
                  actor: User = Depends(get_actor)):
    return await psi_uc.get_document(session, code)


@router.post("/stories/{code}/psi")
@_400
async def psi_create(code: str, payload: PsiCreateIn,
                     session: AsyncSession = Depends(get_session),
                     actor: User = Depends(get_actor)):
    version = await psi_uc.create_version(
        session, code, actor,
        [s.model_dump() for s in payload.sections])
    return {"version": version}


@router.post("/stories/{code}/psi/runs")
@_400
async def psi_run(code: str, payload: PsiRunIn,
                  session: AsyncSession = Depends(get_session),
                  actor: User = Depends(get_actor)):
    return await psi_uc.run_psi(session, code, actor, payload.results)


class PsiLinkIn(BaseModel):
    position: int
    bugCode: str
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


@router.post("/stories/{code}/psi/link-bug")
@_400
async def psi_link(code: str, payload: PsiLinkIn,
                   session: AsyncSession = Depends(get_session),
                   actor: User = Depends(get_actor)):
    await psi_uc.link_bug(session, code, payload.position, payload.bugCode)
    return {"ok": True}


@router.post("/stories/{code}/psi/new-cycle")
@_400
async def psi_new_cycle(code: str, session: AsyncSession = Depends(get_session),
                        actor: User = Depends(get_actor)):
    return {"reset": await psi_uc.new_cycle(session, code)}


# ---------- Eve ----------

class MessageIn(BaseModel):
    text: str
    screenTaskCode: str | None = None
    model_config = ConfigDict(extra="forbid")


@router.post("/assistant/messages")
async def assistant_message(payload: MessageIn,
                            session: AsyncSession = Depends(get_session),
                            actor: User = Depends(get_actor)):
    return await eve_uc.handle_message(session, actor, payload.text,
                                       payload.screenTaskCode)


@router.post("/assistant/force")
@_400
async def assistant_force(code: str, to: str, reason: str,
                          session: AsyncSession = Depends(get_session),
                          actor: User = Depends(get_actor)):
    return await eve_uc.plan_force(session, actor, code, to, reason)


@router.get("/assistant/history")
async def assistant_history(session: AsyncSession = Depends(get_session),
                            actor: User = Depends(get_actor)):
    return {"items": await eve_uc.history(session, actor)}


# ---------- очередь ----------

@router.get("/queue")
async def queue_view(session: AsyncSession = Depends(get_session),
                     actor: User = Depends(get_actor)):
    return await snapshot(session)
