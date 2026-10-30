"""ИИ-провайдеры: пресеты и подключения (расщепление settings.py, B1)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_actor, get_session
from api.middleware.errors import ApiError
from domain.model.validators import DomainError
from repository.models import User
from usecase.settings import connections as conn_uc

router = APIRouter()


@router.get("/provider-presets")
async def provider_presets_list(session: AsyncSession = Depends(get_session),
                                actor: User = Depends(get_actor)):
    """Пресеты провайдеров: подставляют протокол и URL в форму (ФТ-ah-59)."""
    presets = await conn_uc.list_presets(session)
    return [{"name": p.name, "protocol": p.protocol, "baseUrl": p.base_url} for p in presets]


# ---------- провайдеры ----------

class ConnectionIn(BaseModel):
    name: str | None = None
    protocol: str | None = None
    url: str | None = None
    model: str | None = None
    token: str | None = None
    model_config = ConfigDict(extra="forbid")


@router.get("/connections")
async def connections_list(session: AsyncSession = Depends(get_session),
                           actor: User = Depends(get_actor)):
    import sqlalchemy as sa

    from repository.models import Connection

    rows = (await session.execute(
        sa.select(Connection).order_by(Connection.created_at))).scalars().all()
    return [{"id": str(c.id), "name": c.name, "protocol": c.protocol, "url": c.url,
             "model": c.model, "tokenTail": c.token_tail, "checkStatus": c.check_status,
             "isActive": c.is_active, "checkedAt": str(c.checked_at or "")} for c in rows]


@router.post("/connections")
async def connections_create(payload: ConnectionIn,
                             session: AsyncSession = Depends(get_session),
                             actor: User = Depends(get_actor)):
    try:
        c = await conn_uc.create_connection(session, payload.model_dump())
    except DomainError as err:
        raise ApiError(400, err.message, tech=err.tech)
    return {"id": str(c.id), "checkStatus": c.check_status}


@router.patch("/connections/{connection_id}")
async def connections_update(connection_id: str, payload: ConnectionIn,
                             session: AsyncSession = Depends(get_session),
                             actor: User = Depends(get_actor)):
    import uuid as uuid_mod

    try:
        c = await conn_uc.update_connection(session, uuid_mod.UUID(connection_id),
                                            payload.model_dump(exclude_none=True))
    except DomainError as err:
        raise ApiError(400, err.message)
    return {"id": str(c.id), "checkStatus": c.check_status}


@router.post("/connections/check")
async def connections_check(payload: ConnectionIn,
                            session: AsyncSession = Depends(get_session),
                            actor: User = Depends(get_actor)):
    try:
        return await conn_uc.check_connection(session, payload.model_dump())
    except DomainError as err:
        raise ApiError(400, err.message, tech=err.tech)


@router.post("/connections/{connection_id}/activate")
async def connections_activate(connection_id: str,
                               session: AsyncSession = Depends(get_session),
                               actor: User = Depends(get_actor)):
    import uuid as uuid_mod

    try:
        await conn_uc.activate_connection(session, uuid_mod.UUID(connection_id))
    except DomainError as err:
        raise ApiError(400, err.message)
    return {"ok": True}


@router.delete("/connections/{connection_id}")
async def connections_delete(connection_id: str,
                             session: AsyncSession = Depends(get_session),
                             actor: User = Depends(get_actor)):
    import uuid as uuid_mod

    try:
        await conn_uc.delete_connection(session, uuid_mod.UUID(connection_id))
    except DomainError as err:
        raise ApiError(400, err.message)
    return {"ok": True}
