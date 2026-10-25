"""Хроники: одна запись на событие; тяжёлое — отдельно с ретеншном (ФТ-ah-43/44)."""

from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from domain.model.validators import DomainError
from repository.models import Chronicle, ChroniclePayload


async def append(session: AsyncSession, task_id, event_type: str, author_kind: str,
                 message: str, *, author_id=None, rule_code: str | None = None,
                 payload: str | None = None, retention_days: int = 90) -> Chronicle:
    if event_type not in ("field", "transition", "force", "agent", "denied", "psi", "bug"):
        raise DomainError(f"Неизвестный тип события {event_type!r}")
    if author_kind == "auto" and not rule_code:
        raise DomainError("Запись автомата требует номер правила",
                          tech="author_kind=auto without rule_code")
    payload_id = None
    if payload:
        pid = (await session.execute(
            sa.insert(ChroniclePayload)
            .values(body=payload,
                    expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=retention_days))
            .returning(ChroniclePayload.id))).scalar_one()
        payload_id = pid
    entry = Chronicle(task_id=task_id, event_type=event_type, author_kind=author_kind,
                      author_id=author_id, rule_code=rule_code, message=message,
                      payload_id=payload_id)
    session.add(entry)
    return entry


async def list_for_task(session: AsyncSession, task_id, event_type: str | None = None,
                        limit: int = 200) -> list[dict]:
    query = sa.select(Chronicle).where(Chronicle.task_id == task_id)
    if event_type:
        query = query.where(Chronicle.event_type == event_type)
    rows = (await session.execute(
        query.order_by(Chronicle.created_at.desc()).limit(limit))).scalars().all()
    return [{"id": str(c.id), "type": c.event_type, "authorKind": c.author_kind,
             "ruleCode": c.rule_code, "message": c.message,
             "hasPayload": c.payload_id is not None, "at": c.created_at.isoformat()}
            for c in rows]


async def purge_expired_payloads(session: AsyncSession) -> int:
    """Ретеншн тяжёлого содержимого: просроченные payload'ы удаляются,
    лёгкие записи живут (ФТ-ah-44); запуск из демона раз в сутки."""
    # сначала обнуляем ссылки в лёгких записях — они живут бессрочно (ФТ-ah-44)
    expired = sa.select(ChroniclePayload.id).where(
        ChroniclePayload.expires_at < sa.func.now()).scalar_subquery()
    await session.execute(sa.update(Chronicle)
                          .where(Chronicle.payload_id.in_(expired))
                          .values(payload_id=None))
    result = await session.execute(sa.delete(ChroniclePayload)
                                   .where(ChroniclePayload.expires_at < sa.func.now()))
    await session.commit()
    return result.rowcount or 0
