"""Журнал настроек: кто/когда/что, полный диф, секреты масками (ФТ-ah-64)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from repository.models import SettingsJournal


async def record(session: AsyncSession, who_id, entity: str, summary: str,
                 diff: list[dict]) -> None:
    """diff: [{"field": ..., "old": ..., "new": ...}] — секреты маскируются вызывающим."""
    session.add(SettingsJournal(who_id=who_id, entity=entity, summary=summary, diff=diff))


async def record_and_commit(session: AsyncSession, who_id, entity: str, summary: str,
                            diff: list[dict]) -> None:
    await record(session, who_id, entity, summary, diff)
    await session.commit()
