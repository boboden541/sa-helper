"""Окно хранения сырых строк живого лога прогона (runlog.retention_days).

Единый источник и для демона (_retention_tick удаляет строки старше окна),
и для API (поле logPruned в /tasks/{code}/runs) — раньше окно было захардкожено
в демоне семёркой, и при смене политики интерфейс остался бы нечестным.
"""

from __future__ import annotations

import sqlalchemy as sa
from domain.model.validators import DomainError
from repository.models import AppSetting
from sqlalchemy.ext.asyncio import AsyncSession

RETENTION_DAYS_KEY = "runlog.retention_days"
RETENTION_DAYS_DEFAULT = 7


async def retention_days(session: AsyncSession) -> int:
    """Эффективное окно в днях. Мусор/пусто/отсутствие ключа — дефолт, < 1 — 1:
    опечатка оператора не должна вычищать таблицу целиком (устойчивость как у
    daemon/config.py:retry_pauses_minutes, анализ 11.11.2026)."""
    value = (
        await session.execute(
            sa.select(AppSetting.value).where(AppSetting.key == RETENTION_DAYS_KEY)
        )
    ).scalar_one_or_none()
    try:
        days = int(value) if value is not None else RETENTION_DAYS_DEFAULT
    except (TypeError, ValueError):
        days = RETENTION_DAYS_DEFAULT
    return max(1, days)


async def set_retention_days(session: AsyncSession, days: int) -> None:
    """Upsert окна (паттерн pipeline.pause): честный отказ на мусор и < 1."""
    if not isinstance(days, int) or days < 1:
        raise DomainError("Окно хранения логов — целое число дней, не меньше 1")
    row = (
        await session.execute(sa.select(AppSetting).where(AppSetting.key == RETENTION_DAYS_KEY))
    ).scalar_one_or_none()
    if row:
        row.value = str(days)
    else:
        session.add(AppSetting(key=RETENTION_DAYS_KEY, value=str(days)))
