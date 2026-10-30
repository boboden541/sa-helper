"""ПСИ: документ, прогоны, привязка багов, новый цикл (расщепление journal.py, B2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_actor, get_session
from repository.models import User
from usecase.story import psi as psi_uc

from api.controllers.journal._common import _400

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
        [s.model_dump() for s in payload.sections],
        preamble_md=payload.preambleMd)
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
