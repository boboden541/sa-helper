"""Массовый отказ провайдера: пауза конвейера по подключению (ФТ-ah-35).

Несколько подряд неудач на одном подключении → задачи ждут (не блокируются
по одной), предупреждение «провайдер недоступен» — уведомление + журнал.
"""

from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from repository.models import AgentProfile

_THRESHOLD = 3
_PAUSE = dt.timedelta(minutes=10)

# состояние в процессе демона: connection_id -> (подряд неудач, пауза до)
_state: dict[str, tuple[int, dt.datetime | None]] = {}


def record_failure(connection_id: str | None) -> None:
    key = connection_id or "default"
    failures, _ = _state.get(key, (0, None))
    _state[key] = (failures + 1, None)


def record_success(connection_id: str | None) -> None:
    _state.pop(connection_id or "default", None)


async def paused_connections(session: AsyncSession) -> set[str]:
    """Подключения на паузе; истёкшие — снимаются автоматически."""
    now = dt.datetime.now(dt.timezone.utc)
    for key, (failures, until) in list(_state.items()):
        if failures >= _THRESHOLD and (until is None or until > now):
            if until is None:
                _state[key] = (failures, now + _PAUSE)
            continue
        if until is not None and until <= now:
            _state.pop(key, None)
    return {k for k, (f, u) in _state.items() if f >= _THRESHOLD}


async def maybe_trip(session: AsyncSession, connection_id: str | None) -> bool:
    """При достижении порога — пауза подключения + уведомление (однократно)."""
    key = connection_id or "default"
    failures, _ = _state.get(key, (0, None))
    if failures < _THRESHOLD:
        return False
    if _state.get(key, (0, None))[1] is not None:
        return True  # уже на паузе
    now = dt.datetime.now(dt.timezone.utc)
    _state[key] = (failures, now + _PAUSE)
    from usecase.journal.notifications import raise_event

    await raise_event(
        session, "SYSTEM", "provider_or_path_down",
        f"Провайдер недоступен: {failures} подряд неудачных запусков — "
        "конвейер по подключению приостановлен на 10 минут",
        tech_detail=f"connection={key}")
    await session.commit()
    return True
