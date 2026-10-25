"""Контур flow: рабочая копия, публикация с валидацией, миграции, пресеты (СТ §4.4.1)."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from domain.flowvalidation.validator import FlowDraft, validate_draft
from domain.model.validators import DomainError
from domain.transition.graph import invalidate_cache
from repository.models import (
    Chronicle, FlowPreset, FlowStatus, FlowTransition, FlowVersion, Notification,
    Task, TaskType, User,
)
from usecase.journal.settings_journal import record_and_commit

PRESETS_DIR = uuid.UUID(int=0)  # placeholder, реальный путь импортируется лениво


async def _type_by_key(session: AsyncSession, type_key: str) -> TaskType:
    ttype = (await session.execute(
        sa.select(TaskType).where(TaskType.key == type_key))).scalar_one_or_none()
    if ttype is None:
        raise DomainError(f"Тип задачи {type_key!r} не найден", field="type")
    return ttype


async def get_current(session: AsyncSession, type_key: str) -> FlowVersion:
    ttype = await _type_by_key(session, type_key)
    fv = (await session.execute(
        sa.select(FlowVersion).where(
            FlowVersion.task_type_id == ttype.id,
            FlowVersion.is_current.is_(True), FlowVersion.is_published.is_(True))
    )).scalar_one_or_none()
    if fv is None:
        raise DomainError(f"У типа {type_key} нет опубликованной версии flow")
    return fv


async def get_draft(session: AsyncSession, type_key: str) -> FlowVersion:
    """Рабочая копия: единственная неопубликованная версия типа; создаётся
    копированием текущей при первом начале правки (решение 25.10.2026)."""
    ttype = await _type_by_key(session, type_key)
    draft = (await session.execute(
        sa.select(FlowVersion).where(
            FlowVersion.task_type_id == ttype.id, FlowVersion.is_published.is_(False))
    )).scalar_one_or_none()
    if draft is not None:
        return draft
    current = await get_current(session, type_key)
    next_version = (await session.execute(
        sa.select(sa.func.max(FlowVersion.version))
        .where(FlowVersion.task_type_id == ttype.id))).scalar_one() + 1
    draft = FlowVersion(task_type_id=ttype.id, version=next_version,
                        is_current=False, is_published=False, created_by=current.created_by)
    session.add(draft)
    await session.flush()
    for st in (await session.execute(
            sa.select(FlowStatus).where(FlowStatus.flow_version_id == current.id))).scalars():
        session.add(FlowStatus(
            flow_version_id=draft.id, status_key=st.status_key, label=st.label,
            stage_desc=st.stage_desc, checklist_gate=st.checklist_gate,
            is_entry=st.is_entry, is_terminal=st.is_terminal,
            is_blocking=st.is_blocking, alias_column_id=st.alias_column_id))
    for tr in (await session.execute(
            sa.select(FlowTransition).where(FlowTransition.flow_version_id == current.id))).scalars():
        session.add(FlowTransition(
            flow_version_id=draft.id, from_status=tr.from_status, to_status=tr.to_status,
            runner=tr.runner, display=tr.display, cond_checklist=tr.cond_checklist,
            cond_links=tr.cond_links, cond_artifact=tr.cond_artifact,
            rule_code=tr.rule_code))
    await session.commit()
    return draft


async def save_draft(session: AsyncSession, type_key: str, definition: dict) -> FlowVersion:
    """Перезаписывает рабочую копию (граф и таблица редактируют одну копию)."""
    draft = await get_draft(session, type_key)
    await session.execute(sa.delete(FlowStatus).where(FlowStatus.flow_version_id == draft.id))
    await session.execute(sa.delete(FlowTransition).where(FlowTransition.flow_version_id == draft.id))
    await session.flush()
    for st in definition["statuses"]:
        session.add(FlowStatus(
            flow_version_id=draft.id, status_key=st["key"], label=st["label"],
            stage_desc=st.get("stage_desc"), checklist_gate=st.get("gate"),
            is_entry=bool(st.get("entry")), is_terminal=bool(st.get("terminal")),
            is_blocking=bool(st.get("blocking")),
            alias_column_id=st.get("alias_column_id")))
    await session.flush()
    for tr in definition["transitions"]:
        session.add(FlowTransition(
            flow_version_id=draft.id, from_status=tr["from"], to_status=tr["to"],
            runner=tr["runner"], display=tr.get("display", ""),
            cond_checklist=tr.get("cond_checklist", True),
            cond_links=tr.get("cond_links", True),
            cond_artifact=tr.get("cond_artifact", False),
            rule_code=tr.get("rule")))
    await session.commit()
    return draft


def _draft_to_validator(draft: FlowVersion, statuses: list[FlowStatus],
                        transitions: list[FlowTransition]) -> FlowDraft:
    return FlowDraft(
        statuses=[{"key": s.status_key, "label": s.label, "alias": str(s.alias_column_id or ""),
                   "is_entry": s.is_entry, "is_terminal": s.is_terminal}
                  for s in statuses],
        transitions=[{"from": t.from_status, "to": t.to_status, "runner": t.runner,
                      "display": t.display} for t in transitions],
    )


async def publish(session: AsyncSession, type_key: str, who: User,
                  migrations: dict[str, str] | None = None) -> FlowVersion:
    """Публикация: валидация → версия становится текущей; задачи «в полёте»
    со статусами вне новой версии мигрируют на приёмники (ФТ-ah-56)."""
    draft = await get_draft(session, type_key)
    statuses = list((await session.execute(
        sa.select(FlowStatus).where(FlowStatus.flow_version_id == draft.id))).scalars())
    transitions = list((await session.execute(
        sa.select(FlowTransition).where(FlowTransition.flow_version_id == draft.id))).scalars())

    result = validate_draft(_draft_to_validator(draft, statuses, transitions))
    if not result.ok:
        raise DomainError(
            "Публикация отклонена: " + "; ".join(result.errors),
            tech="\n".join(result.errors) + ("\nПредупреждения: " + "; ".join(result.warnings)
                                             if result.warnings else ""))

    current = await get_current(session, type_key)
    prev_status_keys = set((await session.execute(
        sa.select(FlowStatus.status_key)
        .where(FlowStatus.flow_version_id == current.id))).scalars())
    new_keys = {s.status_key for s in statuses}
    removed = prev_status_keys - new_keys

    # проверка приёмников ДО мутаций: отказ не оставляет сессию грязной
    migrations = dict(migrations or {})
    if removed:
        # приёмники нужны только для статусов, где есть задачи «в полёте»
        occupied = set((await session.execute(
            sa.select(Task.status_key)
            .where(Task.flow_version_id == current.id,
                   Task.status_key.in_(removed)))).scalars())
        missing = [s for s in occupied if s not in migrations]
        if missing:
            raise DomainError(
                "Публикация удаляет статусы с задачами «в полёте»: назначьте статус-приёмники для "
                + ", ".join(sorted(missing)),
                tech=f"removed={sorted(removed)}, migrations={migrations}")

    await session.execute(sa.update(FlowVersion)
                          .where(FlowVersion.task_type_id == draft.task_type_id,
                                 FlowVersion.is_current.is_(True))
                          .values(is_current=False))
    draft.is_published = True
    draft.is_current = True
    await session.flush()
    invalidate_cache()

    # миграция задач «в полёте» (ФТ-ah-56, раздел 14)
    migrated = 0
    if removed:
        in_flight = (await session.execute(
            sa.select(Task).where(Task.flow_version_id == current.id,
                                  Task.status_key.in_(removed)))).scalars().all()
        for task in in_flight:
            old_status = task.status_key
            task.flow_version_id = draft.id
            task.status_key = migrations[old_status]
            session.add(Chronicle(
                task_id=task.id, event_type="transition", author_kind="auto",
                rule_code="MIG",
                message=f"Миграция flow: статус «{old_status}» → «{task.status_key}» "
                        f"(публикация v{draft.version})"))
            await session.execute(
                sa.update(Notification)
                .where(Notification.code == task.code,
                       Notification.resolved_at.is_(None))
                .values(resolved_at=sa.func.now()))
            migrated += 1

    await record_and_commit(
        session, who.id, "flow",
        f"Опубликовано {type_key} v{draft.version}"
        + (f", мигрировано задач: {migrated}" if migrated else ""),
        [{"field": "version", "old": current.version, "new": draft.version}])
    return draft


async def list_presets(session: AsyncSession) -> list[FlowPreset]:
    return list((await session.execute(
        sa.select(FlowPreset).order_by(FlowPreset.name))).scalars())


async def import_preset(session: AsyncSession, name: str, definition_yaml: str,
                        description: str | None = None) -> FlowPreset:
    """Импорт YAML-пресета (ФТ-ah-57): валиден по тем же правилам."""
    definition = yaml.safe_load(definition_yaml)
    result = validate_draft(FlowDraft(
        statuses=[{**s, "alias": s.get("alias", "x")} for s in definition["statuses"]],
        transitions=definition["transitions"]))
    if not result.ok:
        raise DomainError("Пресет не прошёл валидацию: " + "; ".join(result.errors))
    preset = FlowPreset(name=name, description=description,
                        definition=definition_yaml, is_builtin=False)
    session.add(preset)
    await session.commit()
    return preset


async def reset_builtin(session: AsyncSession, type_key: str, who: User) -> FlowVersion:
    """Сброс к встроенному пресету — через новую версию, история не переписывается."""
    from db.seeds.flow_seed import PRESETS_DIR

    path = PRESETS_DIR / f"{type_key}.yaml"
    if not path.exists():
        raise DomainError(f"Встроенный пресет {type_key!r} не найден")
    definition = yaml.safe_load(path.read_text(encoding="utf-8"))
    await get_draft(session, type_key)  # гарантирует наличие черновой механики версий
    ttype = await _type_by_key(session, type_key)
    draft = (await session.execute(
        sa.select(FlowVersion).where(
            FlowVersion.task_type_id == ttype.id,
            FlowVersion.is_published.is_(False)))).scalar_one()
    await save_draft(session, type_key, definition)
    return await publish(session, type_key, who)
