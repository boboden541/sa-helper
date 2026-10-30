"""Рубильник конвейера, предупреждения и журнал настроек
(расщепление settings.py, B1; логика — в usecase/settings/pipeline.py, B3)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_actor, get_session
from repository.models import User
from usecase.settings import pipeline as pipeline_uc

router = APIRouter()


@router.get("/pipeline-status")
async def pipeline_status(session: AsyncSession = Depends(get_session),
                          actor: User = Depends(get_actor)):
    """Глобальные предупреждения конвейера (warnbar, ФТ-ah-35/49/70)."""
    return await pipeline_uc.status(session)


# ---------- журнал настроек ----------

@router.get("/settings-journal")
async def settings_journal(session: AsyncSession = Depends(get_session),
                           actor: User = Depends(get_actor)):
    import sqlalchemy as sa

    from repository.models import SettingsJournal

    rows = (await session.execute(
        sa.select(SettingsJournal, User.name)
        .join(User, User.id == SettingsJournal.who_id)
        .order_by(SettingsJournal.created_at.desc()).limit(100))).all()
    return [{"who": name, "entity": j.entity, "summary": j.summary,
             "diff": j.diff, "at": str(j.created_at)} for j, name in rows]


# ---------- рубильник конвейера (решение владельца 26.10.2026) ----------------

class PipelinePauseIn(BaseModel):
    paused: bool
    reason: str | None = None
    model_config = ConfigDict(extra="forbid")


@router.get("/pipeline-paused")
async def pipeline_paused(session: AsyncSession = Depends(get_session),
                          actor: User = Depends(get_actor)):
    import sqlalchemy as sa

    from repository.models import AppSetting

    val = (await session.execute(
        sa.select(AppSetting.value).where(AppSetting.key == "daemon.paused"))).scalar_one_or_none()
    return {"paused": val == "true"}


@router.post("/pipeline-pause")
async def pipeline_pause(payload: PipelinePauseIn,
                         session: AsyncSession = Depends(get_session),
                         actor: User = Depends(get_actor)):
    """Пауза конвейера: демон не запускает новых агентов; активные прогоны
    прерываются перехватом (ФТ-ah-32). Чат Eve не затрагивается — он идёт
    через API, а не через демон; прогоны чат-ботов исключены из прерывания."""
    return await pipeline_uc.pause(session, actor, paused=payload.paused,
                                   reason=payload.reason)
