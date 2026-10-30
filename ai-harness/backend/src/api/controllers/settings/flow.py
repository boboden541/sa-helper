"""Flow-конструктор: draft/validate/publish/reset, пресеты, типы задач,
alias-колонки, привязка статусов (расщепление settings.py, B1)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_actor, get_session
from api.middleware.errors import ApiError
from domain.model.validators import DomainError
from repository.models import TaskType, User
from usecase.settings import flow as flow_uc

router = APIRouter()


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


@router.post("/flows/{type_key}/publish")
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
                     actor: User = Depends(get_actor),
                     payload: dict | None = None):
    """Сброс к встроенному пресету. Тело (опционально): {"migrations":
    {"удалённый_статус": "приёмник"}} — приёмники для задач «в полёте»."""
    try:
        migrations = (payload or {}).get("migrations") or None
        fv = await flow_uc.reset_builtin(session, type_key, actor, migrations=migrations)
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


class StatusAliasIn(BaseModel):
    statusKey: str
    aliasColumnId: str | None = None
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


@router.patch("/flows/{type_key}/status-alias")
async def flow_status_alias(type_key: str, payload: StatusAliasIn,
                            session: AsyncSession = Depends(get_session),
                            actor: User = Depends(get_actor)):
    """Назначение статуса колонке в текущей версии (colmap-панель, ФТ-ah-67)."""
    import sqlalchemy as sa

    from repository.models import FlowStatus, FlowVersion
    from usecase.journal.settings_journal import record_and_commit

    ttype = (await session.execute(sa.select(TaskType).where(TaskType.key == type_key))).scalar_one_or_none()
    if ttype is None:
        raise ApiError(400, f"Тип {type_key} не найден")
    fv = (await session.execute(sa.select(FlowVersion).where(
        FlowVersion.task_type_id == ttype.id, FlowVersion.is_current.is_(True),
        FlowVersion.is_published.is_(True)))).scalar_one_or_none()
    if fv is None:
        raise ApiError(400, "Нет опубликованной версии flow")
    st = (await session.execute(sa.select(FlowStatus).where(
        FlowStatus.flow_version_id == fv.id, FlowStatus.status_key == payload.statusKey))).scalar_one_or_none()
    if st is None:
        raise ApiError(400, f"Статус {payload.statusKey!r} не найден")
    old_col = str(st.alias_column_id or "")
    new_col = payload.aliasColumnId or ""
    if old_col == new_col:
        return {"ok": True, "changed": False}
    st.alias_column_id = payload.aliasColumnId or None
    from domain.transition.graph import invalidate_cache
    invalidate_cache()
    await record_and_commit(session, actor.id, "board",
                            f"Статус «{st.label}» → колонка",
                            [{"field": "alias", "old": old_col[:8], "new": new_col[:8]}])
    return {"ok": True, "changed": True}


@router.get("/all-statuses")
async def flow_all_statuses(session: AsyncSession = Depends(get_session),
                            actor: User = Depends(get_actor)):
    """Все статусы всех типов с alias-привязками — для colmap-панели."""
    import sqlalchemy as sa

    from repository.models import FlowStatus, FlowVersion, TaskType

    types = (await session.execute(sa.select(TaskType).order_by(TaskType.id))).scalars().all()
    out = []
    for tt in types:
        fv = (await session.execute(sa.select(FlowVersion).where(
            FlowVersion.task_type_id == tt.id, FlowVersion.is_current.is_(True),
            FlowVersion.is_published.is_(True)))).scalar_one_or_none()
        if fv is None:
            continue
        sts = (await session.execute(sa.select(FlowStatus).where(
            FlowStatus.flow_version_id == fv.id).order_by(FlowStatus.id))).scalars().all()
        out.append({"type": tt.key, "typeLabel": tt.label,
                    "statuses": [{"key": s.status_key, "label": s.label,
                                  "terminal": bool(s.is_terminal),
                                  "aliasColumnId": str(s.alias_column_id or "")} for s in sts]})
    return out
