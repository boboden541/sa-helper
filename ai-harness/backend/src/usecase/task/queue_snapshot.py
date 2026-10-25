"""Снимок очереди автомата «сейчас» (ПТ-ah-20, вкладка «Очередь»)."""

from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from repository.models import Task, User


async def snapshot(session: AsyncSession) -> dict:
    now = dt.datetime.now(dt.timezone.utc)
    working = (await session.execute(
        sa.select(Task.code, Task.status_key, Task.reserved_at, User.name)
        .join(User, User.id == Task.reserved_by)
        .where(Task.reserved_by.is_not(None))
        .order_by(Task.reserved_at))).all()
    waiting = (await session.execute(
        sa.select(Task.code, Task.status_key, Task.retry_count)
        .where(Task.reserved_by.is_(None),
               Task.status_key.notin_(("pending", "backlog", "todo", "done", "canceled")))
        .order_by(Task.priority, Task.created_at).limit(50))).all()
    blocked = (await session.execute(
        sa.select(Task.code, Task.blocked_reason)
        .where(Task.status_key == "blocked")
        .order_by(Task.updated_at.desc()).limit(50))).all()
    return {
        "working": [{"code": c, "status": s, "agent": a,
                     "minutes": int((now - r).total_seconds() // 60) if r else None}
                    for c, s, r, a in working],
        "waiting": [{"code": c, "status": s, "attempts": n} for c, s, n in waiting],
        "blocked": [{"code": c, "reason": r} for c, r in blocked],
    }
