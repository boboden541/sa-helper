"""Массовый отказ провайдера: пауза конвейера по подключению (ФТ-ah-35).

Несколько подряд неудач на одном подключении → задачи ждут (не блокируются
по одной), предупреждение «провайдер недоступен» — уведомление + журнал.

Состояние предохранителя — в БД (app_setting, ключ circuit:<connection_id>,
значение JSON-строка): раньше жило в памяти процесса — рестарт демона молча
снимал паузу, вторая копия демона её не видела (анализ 03.11.2026).
"""

from __future__ import annotations

import datetime as dt
import json

import sqlalchemy as sa
from repository.models import AppSetting

_THRESHOLD = 3
_PAUSE = dt.timedelta(minutes=10)


def _key(connection_id: str | None) -> str:
    return f"circuit:{connection_id or 'default'}"


def _load(row: AppSetting | None) -> dict:
    try:
        return json.loads(row.value) if row is not None else {}
    except Exception:  # noqa: BLE001 — битое значение = «нет состояния»
        return {}


async def record_failure(session, connection_id: str | None) -> None:
    """Подряд неудач +1 (коммит — за вызывающим)."""
    key = _key(connection_id)
    row = (await session.execute(
        sa.select(AppSetting).where(AppSetting.key == key))).scalar_one_or_none()
    failures = _load(row).get("failures", 0)
    payload = json.dumps({"failures": failures + 1})
    if row is None:
        session.add(AppSetting(key=key, value=payload))
    else:
        row.value = payload


async def record_success(session, connection_id: str | None) -> None:
    """Успех обнуляет серию неудач подключения."""
    await session.execute(sa.delete(AppSetting).where(AppSetting.key == _key(connection_id)))


async def paused_connections(session) -> set[str]:
    """Подключения на паузе; истёкшие — снимаются на чтении."""
    now = dt.datetime.now(dt.timezone.utc)
    out: set[str] = set()
    rows = (await session.execute(sa.select(AppSetting).where(
        AppSetting.key.like("circuit:%")))).scalars().all()
    for row in rows:
        conn_id = row.key.removeprefix("circuit:")
        state = _load(row)
        failures = int(state.get("failures", 0))
        until_raw = state.get("paused_until")
        until = dt.datetime.fromisoformat(until_raw) if until_raw else None
        if failures < _THRESHOLD or until is None:
            continue
        if until > now:
            out.add(conn_id)
        else:
            await session.execute(sa.delete(AppSetting).where(AppSetting.key == row.key))
            await session.commit()
    return out


async def maybe_trip(session, connection_id: str | None) -> bool:
    """Порог набран → пауза подключения + уведомление (однократно)."""
    key = _key(connection_id)
    row = (await session.execute(
        sa.select(AppSetting).where(AppSetting.key == key))).scalar_one_or_none()
    failures = int(_load(row).get("failures", 0))
    if failures < _THRESHOLD:
        return False
    if _load(row).get("paused_until"):
        return True  # уже на паузе
    now = dt.datetime.now(dt.timezone.utc)
    until = now + _PAUSE
    payload = json.dumps({"failures": failures, "paused_until": until.isoformat()})
    if row is None:
        session.add(AppSetting(key=key, value=payload))
    else:
        row.value = payload
    from usecase.journal.notifications import raise_event

    await raise_event(
        session, "SYSTEM", "provider_or_path_down",
        f"Провайдер недоступен: {failures} подряд неудачных запусков — "
        "конвейер по подключению приостановлен на 10 минут",
        tech_detail=f"connection={key}")
    await session.commit()
    return True
