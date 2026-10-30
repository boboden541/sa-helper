"""Реестр инструментов: скан, чтение и обратная запись артефактов
(расщепление settings.py, B1)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_actor, get_session
from api.middleware.errors import ApiError
from domain.model.validators import DomainError
from repository.models import User

router = APIRouter()


@router.post("/tools/scan")
async def tools_scan(session: AsyncSession = Depends(get_session),
                     actor: User = Depends(get_actor)):
    """Сканирует глобальную папку инструментов и синхронизирует реестр (вариант 4)."""
    from usecase.settings import tools as tools_uc

    try:
        return await tools_uc.scan(session)
    except DomainError as err:
        raise ApiError(400, err.message)


@router.get("/tools")
async def tools_list(session: AsyncSession = Depends(get_session),
                     actor: User = Depends(get_actor)):
    """Реестр инструментов + живой статус синка с диском."""
    from usecase.settings import tools as tools_uc

    try:
        return await tools_uc.list_artifacts(session)
    except DomainError as err:
        raise ApiError(400, err.message)


@router.get("/tools/{kind}/{name}")
async def tools_read(kind: str, name: str, session: AsyncSession = Depends(get_session),
                     actor: User = Depends(get_actor)):
    """Содержимое файла артефакта (только чтение — файлы не изменяются)."""
    from usecase.settings import tools as tools_uc

    try:
        return await tools_uc.read_artifact(session, kind, name)
    except DomainError as err:
        raise ApiError(400, err.message)


@router.put("/tools/{kind}/{name}")
async def tools_write(kind: str, name: str, payload: dict,
                      session: AsyncSession = Depends(get_session),
                      actor: User = Depends(get_actor)):
    """Обратная запись (вариант 4: два входа — файл и веб) с оптимистической блокировкой."""
    from usecase.settings import tools as tools_uc

    try:
        return await tools_uc.write_artifact(session, actor.id, kind, name,
                                             (payload or {}).get("content") or "")
    except DomainError as err:
        raise ApiError(400, err.message)
