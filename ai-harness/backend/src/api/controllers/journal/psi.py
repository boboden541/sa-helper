"""ПСИ: документ, прогоны, привязка багов, новый цикл (расщепление journal.py, B2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from repository.models import User
from sqlalchemy.ext.asyncio import AsyncSession
from usecase.story import psi as psi_uc

from api.controllers.journal._common import _400
from api.deps import get_actor, get_session

router = APIRouter()


# ---------- ПСИ ----------


class PsiSectionIn(BaseModel):
    heading: str = ""
    items: list[dict] = []
    model_config = ConfigDict(extra="forbid")


class PsiCreateIn(BaseModel):
    sections: list[PsiSectionIn]
    preambleMd: str | None = None  # шапка идеального ПСИ: «что реализовано», словарик, правила
    model_config = ConfigDict(extra="forbid")


class PsiRunIn(BaseModel):
    results: list[dict]
    model_config = ConfigDict(extra="forbid")


@router.get("/stories/{code}/psi")
@_400
async def psi_get(
    code: str, session: AsyncSession = Depends(get_session), actor: User = Depends(get_actor)
):
    return await psi_uc.get_document(session, code)


@router.post("/stories/{code}/psi")
@_400
async def psi_create(
    code: str,
    payload: PsiCreateIn,
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(get_actor),
):
    version = await psi_uc.create_version(
        session,
        code,
        actor,
        [s.model_dump() for s in payload.sections],
        preamble_md=payload.preambleMd,
    )
    return {"version": version}


class PsiItemIn(BaseModel):
    position: int  # документный номер пункта П.N (счёт только по пунктам, без заголовков)
    passed: bool
    actual: str = ""
    model_config = ConfigDict(extra="forbid")


@router.post("/stories/{code}/psi/items")
@_400
async def psi_mark_item(
    code: str,
    payload: PsiItemIn,
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(get_actor),
):
    """Поэтапная отметка пункта ПСИ по ходу прогона (решение владельца 04.11.2026):
    вердикт сразу в БД — переживает обрыв сессии, гейт M6 видит живую картину."""
    return await psi_uc.mark_item(
        session, code, actor, payload.position, payload.passed, payload.actual
    )


@router.post("/stories/{code}/psi/runs")
@_400
async def psi_run(
    code: str,
    payload: PsiRunIn,
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(get_actor),
):
    return await psi_uc.run_psi(session, code, actor, payload.results)


@router.post("/stories/{code}/psi/rework")
@_400
async def psi_rework(
    code: str,
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(get_actor),
):
    """ФТ-FNR14-06: сброс заверенности плана ПСИ. История остаётся на qa_ready,
    пока составитель не зарегистрирует новую версию документа (M3 ждёт)."""
    return await psi_uc.mark_rework(session, code, actor)


class PsiLinkTaskIn(BaseModel):
    position: int
    taskCode: str
    model_config = ConfigDict(extra="forbid")


@router.post("/stories/{code}/psi/link-task")
@_400
async def psi_link_task(
    code: str,
    payload: PsiLinkTaskIn,
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(get_actor),
):
    """ФТ-FNR15-01: карта покрытия «пункт ПСИ ↔ задача» (идемпотентно)."""
    return await psi_uc.link_task(session, code, actor, payload.position, payload.taskCode)


class PsiReviewIn(BaseModel):
    verdict: bool
    note: str = ""
    model_config = ConfigDict(extra="forbid")


@router.post("/stories/{code}/psi/review")
@_400
async def psi_review(
    code: str,
    payload: PsiReviewIn,
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(get_actor),
):
    """ФТ-FNR15-08: вердикт «ПСИ-редактора». approved открывает ребро M3b
    (psi_review → in_testing); rejected — M3c (возврат на qa_ready)."""
    return await psi_uc.set_manager_review(session, code, actor, payload.verdict, payload.note)


class PsiLinkIn(BaseModel):
    position: int
    bugCode: str
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


@router.post("/stories/{code}/psi/link-bug")
@_400
async def psi_link(
    code: str,
    payload: PsiLinkIn,
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(get_actor),
):
    await psi_uc.link_bug(session, code, payload.position, payload.bugCode)
    return {"ok": True}


@router.post("/stories/{code}/psi/new-cycle")
@_400
async def psi_new_cycle(
    code: str, session: AsyncSession = Depends(get_session), actor: User = Depends(get_actor)
):
    return {"reset": await psi_uc.new_cycle(session, code)}
