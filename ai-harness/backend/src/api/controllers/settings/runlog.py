"""Окно хранения сырых строк живого лога прогона (решение владельца 26.11.2026:
ключ runlog.retention_days, дефолт 7; читают и демон, и /tasks/{code}/runs).

Контроллер только парсит вход и отдаёт ответ (расщепление B1;
логика — в usecase/settings/runlog.py, B3; DomainError → 400 глобальным
domain_error_handler, как у остальных settings-эндпоинтов).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from repository.models import User
from sqlalchemy.ext.asyncio import AsyncSession
from usecase.settings import runlog as runlog_uc

from api.deps import get_actor, get_session

router = APIRouter()


@router.get("/runlog-retention")
async def runlog_retention(
    session: AsyncSession = Depends(get_session), actor: User = Depends(get_actor)
):
    return {"days": await runlog_uc.retention_days(session)}


class RunlogRetentionIn(BaseModel):
    days: int = Field(alias="days")
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


@router.post("/runlog-retention")
async def runlog_retention_set(
    payload: RunlogRetentionIn,
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(get_actor),
):
    """Установка окна: нецелое/мусорное days отсекается pydantic'ом, < 1 —
    DomainError из usecase (глобально → 400)."""
    await runlog_uc.set_retention_days(session, payload.days)
    await session.commit()
    return {"ok": True, "days": payload.days}
