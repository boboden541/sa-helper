"""Контроллеры настроек: flow, пресеты, провайдеры, агенты/матрица, проекты, пользователи."""

from __future__ import annotations

import sqlalchemy as sa

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_actor, get_session
from api.middleware.errors import ApiError
from domain.model.validators import DomainError
from repository.models import AgentProfile, Project, TaskType, User
from usecase.settings import agents as agents_uc
from usecase.settings import connections as conn_uc
from usecase.settings import flow as flow_uc
from usecase.settings import projects as projects_uc

router = APIRouter(prefix="/api/v1", tags=["settings"])


def _domain(fn):
    async def wrapper(*args, **kw):
        try:
            return await fn(*args, **kw)
        except DomainError as err:
            raise ApiError(err.status if hasattr(err, "status") else 400,
                           err.message, tech=err.tech)
    return wrapper


# ---------- flow ----------

class DraftIn(BaseModel):
    statuses: list[dict]
    transitions: list[dict]
    model_config = ConfigDict(extra="forbid")


class PublishIn(BaseModel):
    migrations: dict[str, str] | None = None
    model_config = ConfigDict(extra="forbid")


@router.get("/flows/{type_key}")
async def get_flow(type_key: str, session: AsyncSession = Depends(get_session),
                   actor: User = Depends(get_actor)):
    import sqlalchemy as sa

    from repository.models import FlowStatus, FlowTransition

    try:
        draft = await flow_uc.get_draft(session, type_key)
    except DomainError as err:
        raise ApiError(400, err.message)
    statuses = (await session.execute(
        sa.select(FlowStatus).where(FlowStatus.flow_version_id == draft.id)
        .order_by(FlowStatus.status_key))).scalars().all()
    transitions = (await session.execute(
        sa.select(FlowTransition).where(FlowTransition.flow_version_id == draft.id))).scalars().all()
    return {
        "type": type_key,
        "version": draft.version,
        "isPublished": draft.is_published,
        "statuses": [{"key": s.status_key, "label": s.label, "stageDesc": s.stage_desc,
                      "gate": s.checklist_gate, "entry": s.is_entry, "terminal": s.is_terminal,
                      "blocking": s.is_blocking, "aliasColumnId": str(s.alias_column_id or "")}
                     for s in statuses],
        "transitions": [{"from": t.from_status, "to": t.to_status, "runner": t.runner,
                         "display": t.display, "rule": t.rule_code} for t in transitions],
    }


@router.put("/flows/{type_key}/draft")
async def save_draft(type_key: str, payload: DraftIn,
                     session: AsyncSession = Depends(get_session),
                     actor: User = Depends(get_actor)):
    try:
        draft = await flow_uc.save_draft(session, type_key, payload.model_dump())
    except DomainError as err:
        raise ApiError(400, err.message)
    return {"version": draft.version, "isPublished": draft.is_published}


@router.get("/flows/{type_key}/validate")
async def flow_validate(type_key: str, session: AsyncSession = Depends(get_session),
                        actor: User = Depends(get_actor)):
    """Предварительная валидация рабочей копии без публикации (publish-panel, AC 3.7)."""
    import sqlalchemy as sa

    from domain.flowvalidation.validator import FlowDraft, validate_draft
    from repository.models import FlowStatus, FlowTransition

    draft = await flow_uc.get_draft(session, type_key)
    statuses = (await session.execute(
        sa.select(FlowStatus).where(FlowStatus.flow_version_id == draft.id))).scalars().all()
    transitions = (await session.execute(
        sa.select(FlowTransition).where(FlowTransition.flow_version_id == draft.id))).scalars().all()
    result = validate_draft(FlowDraft(
        statuses=[{"key": s.status_key, "label": s.label, "alias": "x",
                   "is_entry": s.is_entry, "is_terminal": s.is_terminal} for s in statuses],
        transitions=[{"from": t.from_status, "to": t.to_status, "runner": t.runner,
                      "display": t.display} for t in transitions]))
    return {"errors": result.errors, "warnings": result.warnings, "ok": result.ok}


@router.get("/pipeline-status")
async def pipeline_status(session: AsyncSession = Depends(get_session),
                          actor: User = Depends(get_actor)):
    """Глобальные предупреждения конвейера (warnbar, ФТ-ah-35/49/70)."""
    import os

    warnings: list[dict] = []
    no_active = (await session.execute(sa.text(
        "SELECT count(*) FROM connection WHERE is_active"))).scalar_one()
    if not no_active:
        warnings.append({"level": "warn",
                         "message": "ИИ-провайдер не подключён: агенты конвейера не запустятся",
                         "goto": "#settings/providers"})
    broken = (await session.execute(sa.text(
        "SELECT mnemonic FROM project WHERE is_archived = false"))).scalars().all()
    for mnemonic in broken:
        row = (await session.execute(sa.text(
            "SELECT path FROM project WHERE mnemonic = :m"), {"m": mnemonic})).scalar_one_or_none()
        if row and not (os.path.isdir(row) and os.access(row, os.W_OK)):
            warnings.append({"level": "danger",
                             "message": f"Путь проекта {mnemonic} недоступен: конвейер приостановлен",
                             "goto": "#settings/projects"})
    return {"warnings": warnings}


# ---------- провайдеры ----------
async def publish_flow(type_key: str, payload: PublishIn | None = None,
                       session: AsyncSession = Depends(get_session),
                       actor: User = Depends(get_actor)):
    try:
        fv = await flow_uc.publish(session, type_key, actor,
                                   migrations=payload.migrations if payload else None)
    except DomainError as err:
        raise ApiError(400, err.message, tech=err.tech)
    return {"version": fv.version, "isCurrent": fv.is_current}


@router.get("/presets")
async def presets_list(session: AsyncSession = Depends(get_session),
                       actor: User = Depends(get_actor)):
    presets = await flow_uc.list_presets(session)
    return [{"id": str(p.id), "name": p.name, "description": p.description,
             "isBuiltin": p.is_builtin} for p in presets]


class PresetIn(BaseModel):
    name: str
    yaml: str
    description: str | None = None
    model_config = ConfigDict(extra="forbid")


@router.post("/presets")
async def presets_create(payload: PresetIn, session: AsyncSession = Depends(get_session),
                         actor: User = Depends(get_actor)):
    try:
        p = await flow_uc.import_preset(session, payload.name, payload.yaml,
                                        payload.description)
    except DomainError as err:
        raise ApiError(400, err.message)
    return {"id": str(p.id), "name": p.name}


@router.post("/flows/{type_key}/reset")
async def flow_reset(type_key: str, session: AsyncSession = Depends(get_session),
                     actor: User = Depends(get_actor)):
    try:
        fv = await flow_uc.reset_builtin(session, type_key, actor)
    except DomainError as err:
        raise ApiError(400, err.message)
    return {"version": fv.version}


class TaskTypeIn(BaseModel):
    key: str
    label: str
    clone_from: str = Field(default="common_task", alias="cloneFrom")
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


@router.post("/task-types")
async def task_types_create(payload: TaskTypeIn,
                            session: AsyncSession = Depends(get_session),
                            actor: User = Depends(get_actor)):
    """Мастер «+ тип задачи»: тип + flow из пресета-основы, без программирования (ФТ-ah-57)."""
    import re

    import sqlalchemy as sa
    import yaml

    from db.seeds.flow_seed import PRESETS_DIR, publish_preset
    from domain.model.validators import DomainError
    from repository.models import TaskType

    if not re.match(r"^[a-z0-9_]+$", payload.key or ""):
        raise ApiError(400, "Ключ типа: строчные латиница, цифры, _")
    if (await session.execute(sa.select(sa.func.count()).select_from(TaskType)
                              .where(TaskType.key == payload.key))).scalar_one():
        raise ApiError(400, f"Тип {payload.key!r} уже существует")
    base = (await session.execute(sa.select(TaskType)
            .where(TaskType.key == payload.clone_from))).scalar_one_or_none()
    if base is None:
        raise ApiError(400, f"Пресет-основа {payload.clone_from!r} не найдена")
    preset_path = PRESETS_DIR / f"{payload.clone_from}.yaml"
    if not preset_path.exists():
        raise ApiError(400, "Встроенный пресет-основа не найден")

    ttype = TaskType(key=payload.key, label=payload.label.strip()[:64] or payload.key,
                     is_builtin=False)
    session.add(ttype)
    await session.flush()
    definition = yaml.safe_load(preset_path.read_text(encoding="utf-8"))
    try:
        await publish_preset(session, ttype, definition, actor)
    except DomainError as err:
        raise ApiError(400, err.message)
    await session.commit()  # publish_preset только готовит изменения — фиксируем здесь
    return {"key": ttype.key, "label": ttype.label}


# ---------- alias-колонки ----------

@router.get("/alias-columns")
async def alias_columns(session: AsyncSession = Depends(get_session),
                        actor: User = Depends(get_actor)):
    import sqlalchemy as sa

    from repository.models import AliasColumn

    cols = (await session.execute(
        sa.select(AliasColumn).order_by(AliasColumn.position))).scalars().all()
    return [{"id": str(c.id), "label": c.label, "color": c.color,
             "position": c.position} for c in cols]


class AliasColumnIn(BaseModel):
    label: str
    color: str | None = None
    position: int | None = None
    model_config = ConfigDict(extra="forbid")


@router.post("/alias-columns")
async def alias_columns_create(payload: AliasColumnIn,
                               session: AsyncSession = Depends(get_session),
                               actor: User = Depends(get_actor)):
    """Создание alias-колонки (режим правки доски / редактор flow, ФТ-ah-66)."""
    import sqlalchemy as sa

    from repository.models import AliasColumn
    from usecase.journal.settings_journal import record_and_commit

    position = payload.position if payload.position is not None else (
        (await session.execute(sa.select(sa.func.coalesce(sa.func.max(AliasColumn.position), 0)))
         ).scalar_one() + 1)
    col = AliasColumn(label=payload.label.strip()[:32],
                      color=payload.color or "#888888", position=position)
    session.add(col)
    await record_and_commit(session, actor.id, "board",
                            f"Создана колонка «{col.label}»",
                            [{"field": "label", "old": None, "new": col.label}])
    return {"id": str(col.id), "label": col.label, "color": col.color, "position": col.position}


@router.patch("/alias-columns/{column_id}")
async def alias_columns_update(column_id: str, payload: AliasColumnIn,
                               session: AsyncSession = Depends(get_session),
                               actor: User = Depends(get_actor)):
    """Переименование/цвет/порядок колонки; изменения — в журнал настроек (ФТ-ah-66)."""
    import uuid as uuid_mod

    import sqlalchemy as sa

    from repository.models import AliasColumn
    from usecase.journal.settings_journal import record_and_commit

    col = await session.get(AliasColumn, uuid_mod.UUID(column_id))
    if col is None:
        raise ApiError(404, "Колонка не найдена")
    diff = []
    if payload.label and payload.label != col.label:
        diff.append({"field": "label", "old": col.label, "new": payload.label.strip()[:32]})
        col.label = payload.label.strip()[:32]
    if payload.color and payload.color != col.color:
        diff.append({"field": "color", "old": col.color, "new": payload.color})
        col.color = payload.color
    if payload.position is not None and payload.position != col.position:
        diff.append({"field": "position", "old": col.position, "new": payload.position})
        col.position = payload.position
    if diff:
        await record_and_commit(session, actor.id, "board",
                                f"Правка колонки «{col.label}»", diff)
    return {"id": str(col.id), "label": col.label, "color": col.color, "position": col.position}


@router.delete("/alias-columns/{column_id}")
async def alias_columns_delete(column_id: str,
                               session: AsyncSession = Depends(get_session),
                               actor: User = Depends(get_actor)):
    """Удаление запрещено, пока к колонке привязан хоть один статус (ФТ-ah-66)."""
    import uuid as uuid_mod

    import sqlalchemy as sa

    from repository.models import AliasColumn, FlowStatus
    from usecase.journal.settings_journal import record_and_commit

    col = await session.get(AliasColumn, uuid_mod.UUID(column_id))
    if col is None:
        raise ApiError(404, "Колонка не найдена")
    bound = (await session.execute(sa.select(sa.func.count()).select_from(FlowStatus)
                                   .where(FlowStatus.alias_column_id == col.id))).scalar_one()
    if bound:
        raise ApiError(400, f"Колонка используется: к ней привязано {bound} статусов — сначала снимите привязки")
    await session.delete(col)
    await record_and_commit(session, actor.id, "board",
                            f"Удалена колонка «{col.label}»",
                            [{"field": "label", "old": col.label, "new": None}])
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


# ---------- агенты и матрица ----------

class AgentIn(BaseModel):
    name: str | None = None
    role: str | None = None
    skill_md: str | None = Field(default=None, alias="skillMd")
    connection_id: str | None = Field(default=None, alias="connectionId")
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
             "skillMd": p.skill_md, "connectionId": str(p.connection_id or ""),
             "isPreset": p.is_preset} for u, p in rows]


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
                             skill_md=src_profile.skill_md,
                             connection_id=src_profile.connection_id,
                             is_preset=False))
    await session.commit()
    return {"id": str(user.id), "name": name}


@router.patch("/agents/{agent_id}")
async def agents_update(agent_id: str, payload: AgentIn,
                        session: AsyncSession = Depends(get_session),
                        actor: User = Depends(get_actor)):
    import uuid as uuid_mod

    try:
        await agents_uc.update_agent(session, uuid_mod.UUID(agent_id),
                                     payload.model_dump(exclude_none=True))
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


@router.get("/users")
async def users_list(session: AsyncSession = Depends(get_session),
                     actor: User = Depends(get_actor)):
    """Единый список людей и агентов (ФТ-ah-72) — матрица назначений и адресаты."""
    import sqlalchemy as sa

    rows = (await session.execute(
        sa.select(User).where(User.is_service.is_(False))
        .order_by(User.user_type, User.name))).scalars().all()
    return [{"id": str(u.id), "name": u.name, "userType": u.user_type,
             "isChatBot": u.is_chat_bot} for u in rows]


# ---------- проекты ----------

class ProjectIn(BaseModel):
    name: str | None = None
    mnemonic: str | None = None
    path: str | None = None
    baseBranch: str | None = None
    description: str | None = None
    model_config = ConfigDict(extra="forbid")


@router.get("/projects")
async def projects_list(session: AsyncSession = Depends(get_session),
                        actor: User = Depends(get_actor)):
    import sqlalchemy as sa

    rows = (await session.execute(sa.select(Project).order_by(Project.mnemonic))).scalars().all()
    return [{"id": str(p.id), "name": p.name, "mnemonic": p.mnemonic, "path": p.path,
             "baseBranch": p.base_branch, "isArchived": p.is_archived,
             "description": p.description} for p in rows]


@router.post("/projects")
async def projects_create(payload: ProjectIn,
                          session: AsyncSession = Depends(get_session),
                          actor: User = Depends(get_actor)):
    try:
        p = await projects_uc.create_project(session, projects_uc.ProjectInput(
            name=payload.name or "", mnemonic=payload.mnemonic or "",
            path=payload.path or "", base_branch=payload.baseBranch or "main",
            description=payload.description))
    except DomainError as err:
        raise ApiError(400, err.message, tech=err.tech)
    return {"id": str(p.id), "mnemonic": p.mnemonic}


@router.patch("/projects/{project_id}")
async def projects_update(project_id: str, payload: ProjectIn,
                          session: AsyncSession = Depends(get_session),
                          actor: User = Depends(get_actor)):
    import uuid as uuid_mod

    try:
        await projects_uc.update_project(session, uuid_mod.UUID(project_id),
                                         payload.model_dump(exclude_none=True))
    except DomainError as err:
        raise ApiError(400, err.message)
    return {"ok": True}


@router.post("/projects/{project_id}/archive")
async def projects_archive(project_id: str, archived: bool = True,
                           session: AsyncSession = Depends(get_session),
                           actor: User = Depends(get_actor)):
    import uuid as uuid_mod

    try:
        await projects_uc.set_archived(session, uuid_mod.UUID(project_id), archived)
    except DomainError as err:
        raise ApiError(400, err.message)
    return {"ok": True}


@router.delete("/projects/{project_id}")
async def projects_delete(project_id: str, session: AsyncSession = Depends(get_session),
                          actor: User = Depends(get_actor)):
    import uuid as uuid_mod

    try:
        await projects_uc.delete_project(session, uuid_mod.UUID(project_id))
    except DomainError as err:
        raise ApiError(400, err.message)
    return {"ok": True}


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
