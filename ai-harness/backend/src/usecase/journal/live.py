"""Живые данные интерфейса: активные прогоны, токены, новые записи хроники
(решение владельца 27.10.2026).

Чистые выборки без IO-состояния; из них собраны SSE-потоки:
GET /api/v1/activity/stream — «агент работает сейчас» для доски, списка и шапки;
GET /api/v1/tasks/{code}/live — карточка: прогон, токены (например «1300К»),
строки лога и новые записи хроники в реальном времени.
"""

from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from repository.models import Chronicle, Task, TaskRun, TaskRunLog, User

STALE_SECONDS = 120  # пульс потерян (§4.3.1)


def _total(run: TaskRun) -> int:
    return (run.input_tokens or 0) + (run.output_tokens or 0) + (run.cache_tokens or 0)


def _item(run: TaskRun, code: str, title: str, agent: str, now: dt.datetime) -> dict:
    hb = run.heartbeat_at
    return {"code": code, "title": title, "agent": agent,
            "minutes": int((now - run.started_at).total_seconds() // 60),
            "stale": hb is not None and (now - hb).total_seconds() > STALE_SECONDS,
            "input": run.input_tokens or 0, "output": run.output_tokens or 0,
            "cache": run.cache_tokens or 0, "total": _total(run)}


async def activity_snapshot(session: AsyncSession) -> list[dict]:
    """Все задачи, над которыми прямо сейчас работает агент (доска, список, шапка)."""
    now = dt.datetime.now(dt.timezone.utc)
    rows = (await session.execute(
        sa.select(TaskRun, Task.code, Task.title, User.name)
        .join(Task, Task.id == TaskRun.task_id)
        .join(User, User.id == TaskRun.agent_id)
        .where(TaskRun.finished_at.is_(None))
        .order_by(TaskRun.started_at))).all()
    return [_item(run, code, title, agent, now)
            for run, code, title, agent in rows]


async def task_activity(session: AsyncSession, task_id) -> dict | None:
    """Активный прогон одной задачи (карточка, живая шапка и хроника)."""
    now = dt.datetime.now(dt.timezone.utc)
    row = (await session.execute(
        sa.select(TaskRun, User.name)
        .join(User, User.id == TaskRun.agent_id)
        .where(TaskRun.task_id == task_id, TaskRun.finished_at.is_(None))
        .order_by(TaskRun.started_at.desc()).limit(1))).first()
    if row is None:
        return None
    run, agent = row
    item = _item(run, "", "", agent, now)
    item["runId"] = str(run.id)
    return item


async def chronicle_after(session: AsyncSession, task_id,
                          after: dt.datetime | None, seen: set[str]
                          ) -> tuple[list[dict], dt.datetime | None]:
    """Записи хроники новее watermark; seen отсекает повторы в ту же секунду."""
    q = sa.select(Chronicle).where(Chronicle.task_id == task_id)
    if after is not None:
        q = q.where(Chronicle.created_at > after)
    rows = (await session.execute(q.order_by(Chronicle.created_at).limit(50))).scalars().all()
    out: list[dict] = []
    for c in rows:
        if str(c.id) in seen:
            continue
        seen.add(str(c.id))
        out.append({"id": str(c.id), "type": c.event_type, "authorKind": c.author_kind,
                    "ruleCode": c.rule_code, "message": c.message,
                    "at": c.created_at.isoformat()})
    return out, (rows[-1].created_at if rows else after)


async def log_after(session: AsyncSession, run_id, after_seq: int) -> list[dict]:
    """Новые строки живого лога активного прогона (для строки «что делает сейчас»)."""
    rows = (await session.execute(
        sa.select(TaskRunLog)
        .where(TaskRunLog.run_id == run_id, TaskRunLog.seq > after_seq)
        .order_by(TaskRunLog.seq).limit(50))).scalars().all()
    return [{"seq": r.seq, "kind": r.kind, "text": r.text} for r in rows]
