"""Намерения Eve «намерение → да» — хранение в БД (eve_intent, миграция 0013).

Память процесса (_INTENTS) теряла намерения при рестарте backend и не делила
их со вторым uvicorn-воркером (анализ 03.11.2026). Подтверждение живёт до
первого «да» или 10 минут (TTL в payload.expires).

Два контекста записи:
- async-контекст с сессией — save_intent/pop_intent;
- синхронный callback внутри SDK-сервера инструментов Eve-агента —
  persist_intent: fire-and-forget задача в текущем event-loop, своя сессия.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import re

import sqlalchemy as sa
from repository.models import EveIntent

log = logging.getLogger("eve_intents")

_TTL_MINUTES = 10
_CONFIRM_RE = re.compile(r"\s*(да|подтверждаю|yes)\s*", re.IGNORECASE)


def _with_expiry(intent: dict) -> tuple[dict, dt.datetime]:
    expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=_TTL_MINUTES)
    return {**intent, "expires": expires.isoformat()}, expires


async def save_intent(session, user_id, intent: dict) -> None:
    """Upsert намерения (одно открытое намерение на пользователя)."""
    payload, expires = _with_expiry(intent)
    row = await session.get(EveIntent, user_id)
    if row is not None:
        row.payload = payload
        row.expires_at = expires
    else:
        session.add(EveIntent(user_id=user_id, payload=payload, expires_at=expires))


async def pop_intent(session, user_id, text: str) -> dict | None:
    """«Да» → намерение достаётся и удаляется (одно использование)."""
    if not _CONFIRM_RE.fullmatch(text or ""):
        return None
    row = (await session.execute(
        sa.select(EveIntent).where(EveIntent.user_id == user_id))).scalar_one_or_none()
    if row is None:
        return None
    payload = row.payload or {}
    expires = payload.get("expires")
    if expires and dt.datetime.fromisoformat(expires) < dt.datetime.now(dt.timezone.utc):
        await session.delete(row)
        await session.commit()
        return None
    await session.delete(row)
    await session.commit()
    return payload


def persist_intent(user_id, intent: dict) -> None:
    """Синхронный callback: fire-and-forget задача в текущем event-loop."""
    def _run():
        from database import get_sessionmaker

        async def _async():
            async with get_sessionmaker()() as s:
                await save_intent(s, user_id, intent)
                await s.commit()

        asyncio.get_running_loop().create_task(_async())

    _run()
