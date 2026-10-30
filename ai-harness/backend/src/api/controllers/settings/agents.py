"""Агенты: CRUD, клон, глобальная папка инструментов, матрица назначений
(расщепление settings.py, B1)."""

from __future__ import annotations

import sqlalchemy as sa

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_actor, get_session
from api.middleware.errors import ApiError
from domain.model.validators import DomainError
from repository.models import AgentProfile, TaskType, User
from usecase.settings import agents as agents_uc

router = APIRouter()


# ---------- агенты и матрица ----------

class AgentIn(BaseModel):
    name: str | None = None
    role: str | None = None
    connection_id: str | None = Field(default=None, alias="connectionId")
    model: str | None = None  # модель прогона («мост», 27.10.2026)
    allowed_tools: list[str] | None = Field(default=None, alias="allowedTools")
    mcp_servers: dict | None = Field(default=None, alias="mcpServers")
    agent_dir: str | None = Field(default=None, alias="agentDir")
    skills: list[str] | None = None  # скиллы из реестра инструментов (вариант 4)
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


@router.get("/agents")
async def agents_list(session: AsyncSession = Depends(get_session),
                      actor: User = Depends(get_actor)):
    import sqlalchemy as sa

    rows = (await session.execute(
        sa.select(User, AgentProfile)
        .join(AgentProfile, AgentProfile.user_id == User.id)
        .where(User.is_service.is_(False)))).all()
    return [{"id": str(u.id), "name": u.name, "role": p.role,
             "connectionId": str(p.connection_id or ""),
             "isPreset": p.is_preset, "model": p.model or "",
             "allowedTools": p.allowed_tools or [], "mcpServers": p.mcp_servers,
             "agentDir": p.agent_dir or "", "skills": p.skills or []} for u, p in rows]


@router.post("/agents")
async def agents_create(payload: AgentIn, session: AsyncSession = Depends(get_session),
                        actor: User = Depends(get_actor)):
    try:
        user = await agents_uc.create_agent(session, payload.model_dump())
    except DomainError as err:
        raise ApiError(400, err.message)
    return {"id": str(user.id), "name": user.name}


@router.post("/agents/{agent_id}/clone")
async def agents_clone(agent_id: str, session: AsyncSession = Depends(get_session),
                       actor: User = Depends(get_actor)):
    """Быстрый старт: клон агента — копия скилла для правки под свою роль (ФТ-ah-62)."""
    import uuid as uuid_mod

    import sqlalchemy as sa

    from repository.models import AgentProfile

    src_user = await session.get(User, uuid_mod.UUID(agent_id))
    src_profile = (await session.execute(
        sa.select(AgentProfile).where(AgentProfile.user_id == src_user.id)
    )).scalar_one_or_none() if src_user else None
    if src_profile is None:
        raise ApiError(404, "Агент не найден")
    base = f"{src_user.name} (копия)"
    name = base
    n = 2
    while (await session.execute(sa.select(sa.func.count()).select_from(User)
                                 .where(User.name == name))).scalar_one():
        name = f"{base} {n}"
        n += 1
    user = User(name=name, user_type="agent")
    session.add(user)
    await session.flush()
    session.add(AgentProfile(user_id=user.id, role=src_profile.role,
                             connection_id=src_profile.connection_id,
                             is_preset=False,
                             model=src_profile.model,
                             allowed_tools=src_profile.allowed_tools,
                             mcp_servers=src_profile.mcp_servers,
                             agent_dir=src_profile.agent_dir))
    await session.commit()
    return {"id": str(user.id), "name": name}


@router.patch("/agents/{agent_id}")
async def agents_update(agent_id: str, payload: AgentIn,
                        session: AsyncSession = Depends(get_session),
                        actor: User = Depends(get_actor)):
    import uuid as uuid_mod

    try:
        # exclude_unset: присланное значение применяется (в т.ч. null/"" = сброс),
        # отсутствующее не трогается; exclude_none не годится — им нельзя очистить поле
        await agents_uc.update_agent(session, uuid_mod.UUID(agent_id),
                                     payload.model_dump(exclude_unset=True))
    except DomainError as err:
        raise ApiError(400, err.message)
    return {"ok": True}


@router.delete("/agents/{agent_id}")
async def agents_delete(agent_id: str, session: AsyncSession = Depends(get_session),
                        actor: User = Depends(get_actor)):
    import uuid as uuid_mod

    try:
        await agents_uc.delete_agent(session, uuid_mod.UUID(agent_id))
    except DomainError as err:
        raise ApiError(400, err.message)
    return {"ok": True}


@router.get("/agents-tools-dir")
async def agents_tools_dir_get(session: AsyncSession = Depends(get_session),
                               actor: User = Depends(get_actor)):
    """Глобальная папка инструментов — один путь на все проекты (решение владельца 27.10.2026)."""
    import os

    import sqlalchemy as sa

    from infrastructure.paths import host_to_container
    from repository.models import AppSetting

    val = (await session.execute(
        sa.select(AppSetting.value).where(AppSetting.key == "agents.tools_dir")
    )).scalar_one_or_none() or ""
    return {"toolsDir": val,
            "found": bool(val) and os.path.isdir(host_to_container(val))}


@router.put("/agents-tools-dir")
async def agents_tools_dir_set(payload: dict, session: AsyncSession = Depends(get_session),
                               actor: User = Depends(get_actor)):
    import os

    import sqlalchemy as sa

    from infrastructure.paths import host_to_container
    from repository.models import AppSetting

    val = (payload.get("toolsDir") or "").strip()
    if val and not os.path.isdir(host_to_container(val)):
        raise ApiError(400, f"Папка инструментов не найдена: {val} — укажите существующую "
                            "(например папку .claude, куда SA-Helper установлен install.sh)")
    row = (await session.execute(
        sa.select(AppSetting).where(AppSetting.key == "agents.tools_dir"))).scalar_one_or_none()
    old = row.value if row else ""
    if row is None:
        session.add(AppSetting(key="agents.tools_dir", value=val))
    else:
        row.value = val
    from usecase.journal.settings_journal import record_and_commit

    await record_and_commit(session, actor.id, "agents",
                            "Изменена глобальная папка инструментов",
                            [{"field": "agents.tools_dir", "old": old, "new": val}])
    return {"ok": True, "toolsDir": val}


@router.post("/agents/{agent_id}/reset")
async def agents_reset(agent_id: str, session: AsyncSession = Depends(get_session),
                       actor: User = Depends(get_actor)):
    import uuid as uuid_mod

    try:
        await agents_uc.reset_preset_agent(session, uuid_mod.UUID(agent_id))
    except DomainError as err:
        raise ApiError(400, err.message)
    return {"ok": True}


class MatrixIn(BaseModel):
    statusKey: str
    entries: list[dict]
    model_config = ConfigDict(extra="forbid")


@router.put("/matrix/{type_key}/{status_key}")
async def matrix_set(type_key: str, status_key: str, payload: MatrixIn,
                     session: AsyncSession = Depends(get_session),
                     actor: User = Depends(get_actor)):
    import uuid as uuid_mod

    type_id = (await session.execute(
        sa.select(TaskType.id).where(TaskType.key == type_key))).scalar_one_or_none()
    if type_id is None:
        raise ApiError(400, f"Тип {type_key} не найден")
    try:
        entries = [{**e, "user_id": uuid_mod.UUID(str(e["userId"]))} for e in payload.entries]
    except (ValueError, KeyError):
        raise ApiError(400, "Некорректный userId в назначениях")
    try:
        await agents_uc.set_assignments(session, type_id, status_key, entries)
    except DomainError as err:
        raise ApiError(400, err.message)
    return {"ok": True}


@router.get("/matrix/{type_key}")
async def matrix_get(type_key: str, session: AsyncSession = Depends(get_session),
                     actor: User = Depends(get_actor)):
    """Матрица назначений: статусы актуальной версии flow → исполнители (ФТ-ah-63)."""
    import sqlalchemy as sa

    from repository.models import Assignment, TaskType, User

    ttype = (await session.execute(
        sa.select(TaskType).where(TaskType.key == type_key))).scalar_one_or_none()
    if ttype is None:
        raise ApiError(400, f"Тип {type_key} не найден")
    rows = (await session.execute(
        sa.select(Assignment.status_key, Assignment.user_id, Assignment.mode,
                  Assignment.position, User.name, User.user_type)
        .join(User, User.id == Assignment.user_id)
        .where(Assignment.task_type_id == ttype.id)
        .order_by(Assignment.status_key, Assignment.position))).all()
    matrix: dict[str, list[dict]] = {}
    for status_key, user_id, mode, position, name, user_type in rows:
        matrix.setdefault(status_key, []).append({
            "userId": str(user_id), "name": name, "userType": user_type,
            "mode": mode, "position": position})
    return {"type": type_key, "matrix": matrix}
