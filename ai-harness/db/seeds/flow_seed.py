"""Публикация встроенных пресетов flow: YAML → задача типов, версии v1 (is_current).

Используется seed'ом и (в этапе 4) контуром публикации из библиотеки пресетов.
"""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from repository.models import (
    AliasColumn, FlowStatus, FlowTransition, FlowVersion, Project, TaskType, User,
)

PRESETS_DIR = Path(__file__).resolve().parent / "flow_presets"

# Глобальные alias-колонки доски (постановка, «Общий alias для статусов»)
ALIAS_COLUMNS = [
    # (ключ в YAML, label, color, position)
    ("pending", "На рассмотрении", "#9aa0a6", 1),
    # Восстановлена 30.10.2026: докстринг обещает «девять колонок», позиция 2
    # пустовала, а на живой базе владельца «Бэклог» есть (создан вручную) —
    # колонка потерялась в сиде, e2e (01: ≥9 колонок) на свежем сиде падали
    ("backlog", "Бэклог", "#8792a3", 2),
    ("todo", "К работе", "#4c8dff", 3),
    ("progress", "В работе", "#1a73e8", 4),
    ("review", "На ревью", "#a142f4", 5),
    ("testing", "На тестировании", "#f9ab00", 6),
    ("done", "Готово", "#1e8e3e", 7),
    ("canceled", "Отменено", "#5f6368", 8),
    ("blocked", "Заблокировано", "#d93025", 9),
]


async def ensure_alias_columns(session: AsyncSession) -> dict[str, AliasColumn]:
    """Создаёт девять alias-колонок один раз; возвращает маппинг ключ → колонка."""
    existing = {
        c.label: c for c in (await session.execute(sa.select(AliasColumn))).scalars()
    }
    mapping: dict[str, AliasColumn] = {}
    for key, label, color, position in ALIAS_COLUMNS:
        col = existing.get(label)
        if col is None:
            col = AliasColumn(label=label, color=color, position=position)
            session.add(col)
            await session.flush()
        mapping[key] = col
    return mapping


async def publish_preset(
    session: AsyncSession,
    task_type: TaskType,
    definition: dict,
    author: User,
    version: int | None = None,
) -> FlowVersion:
    """Публикует YAML-определение как новую текущую версию flow типа.

    Без валидации (полная валидация — этап 4, domain/flowvalidation); пресет
    встроенный и заведомо корректен.
    """
    if version is None:
        version = (await session.execute(
            sa.select(sa.func.coalesce(sa.func.max(FlowVersion.version), 0))
            .where(FlowVersion.task_type_id == task_type.id)
        )).scalar_one() + 1

    # снимаем is_current с предыдущих
    await session.execute(
        sa.update(FlowVersion)
        .where(FlowVersion.task_type_id == task_type.id, FlowVersion.is_current.is_(True))
        .values(is_current=False)
    )
    fv = FlowVersion(
        task_type_id=task_type.id, version=version, is_current=True,
        is_published=True, created_by=author.id,
    )
    session.add(fv)
    await session.flush()

    columns = await ensure_alias_columns(session)
    for st in definition["statuses"]:
        session.add(FlowStatus(
            flow_version_id=fv.id,
            status_key=st["key"],
            label=st["label"],
            stage_desc=st.get("stage_desc"),
            checklist_gate=st.get("gate"),
            is_entry=bool(st.get("entry")),
            is_terminal=bool(st.get("terminal")),
            is_blocking=bool(st.get("blocking")),
            alias_column_id=columns[st["alias"]].id,
        ))
    await session.flush()
    for tr in definition["transitions"]:
        session.add(FlowTransition(
            flow_version_id=fv.id,
            from_status=tr["from"], to_status=tr["to"],
            runner=tr["runner"], display=tr["display"],
            cond_checklist=tr.get("cond_checklist", True),
            cond_links=tr.get("cond_links", True),
            cond_artifact=tr.get("cond_artifact", False),
            rule_code=tr.get("rule"),
        ))
    await session.flush()
    return fv


async def seed_builtin_flows(session: AsyncSession, system_user: User) -> None:
    """Создаёт 5 встроенных типов задач и публикует их версии v1 (идемпотентно)."""
    from domain.model.enums import BUILTIN_TASK_TYPES

    for type_key, label in BUILTIN_TASK_TYPES:
        ttype = (await session.execute(
            sa.select(TaskType).where(TaskType.key == type_key)
        )).scalar_one_or_none()
        if ttype is None:
            ttype = TaskType(key=type_key, label=label, is_builtin=True)
            session.add(ttype)
            await session.flush()

        has_version = (await session.execute(
            sa.select(sa.func.count()).select_from(FlowVersion)
            .where(FlowVersion.task_type_id == ttype.id, FlowVersion.is_published.is_(True))
        )).scalar_one()
        if has_version:
            continue

        preset_path = PRESETS_DIR / f"{type_key}.yaml"
        definition = yaml.safe_load(preset_path.read_text(encoding="utf-8"))
        session.add(FlowPresetRow(name=f"Встроенный: {label}", description=f"Пресет {type_key}",
                                  is_builtin=True,
                                  definition=preset_path.read_text(encoding="utf-8")))
        await publish_preset(session, ttype, definition, system_user)
    await session.commit()


from repository.models import FlowPreset as FlowPresetRow  # noqa: E402
