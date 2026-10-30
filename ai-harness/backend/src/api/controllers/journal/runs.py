"""Очередь и прогоны: снапшот очереди, история прогонов, лог, перехват
(расщепление journal.py, B2; логика перехвата — в usecase/task/runs.py, B3)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_actor, get_session
from api.middleware.errors import ApiError
from repository.models import User
from usecase.task import runs as runs_uc
from usecase.task.queue_snapshot import snapshot

from api.controllers.journal._common import _400

router = APIRouter()


# ---------- очередь ----------

@router.get("/queue")
async def queue_view(session: AsyncSession = Depends(get_session),
                     actor: User = Depends(get_actor)):
    return await snapshot(session)


# ---------- живые логи прогонов агента (решение владельца 26.10.2026) ----------

def _run_out(r) -> dict:
    import datetime as dt

    running = r.TaskRun.finished_at is None
    hb = r.TaskRun.heartbeat_at
    stale = running and hb is not None and (
        dt.datetime.now(dt.timezone.utc) - hb).total_seconds() > 120
    tr = r.TaskRun
    return {"id": str(tr.id), "attempt": tr.attempt_no,
            "statusKey": tr.status_key,
            "running": running, "stale": stale,
            "outcome": tr.outcome,
            "agent": r.agent_name,
            "input": tr.input_tokens or 0, "output": tr.output_tokens or 0,
            "cache": tr.cache_tokens or 0,
            "tokens": (tr.input_tokens or 0) + (tr.output_tokens or 0) + (tr.cache_tokens or 0),
            "startedAt": tr.started_at.isoformat(),
            "heartbeatAt": hb.isoformat() if hb else None,
            "finishedAt": tr.finished_at.isoformat() if tr.finished_at else None}


@router.get("/tasks/{code}/runs")
async def task_runs(code: str, session: AsyncSession = Depends(get_session),
                    actor: User = Depends(get_actor)):
    """История прогонов задачи (попытки, исходы, пульс) — панель «вкладка Агент»."""
    import sqlalchemy as sa

    from repository.models import Task, TaskRun

    task = (await session.execute(sa.select(Task).where(Task.code == code.upper()))).scalar_one_or_none()
    if task is None:
        raise ApiError(404, f"Задача {code} не найдена")
    rows = (await session.execute(
        sa.select(TaskRun, User.name.label("agent_name"))
        .join(User, User.id == TaskRun.agent_id)
        .where(TaskRun.task_id == task.id)
        .order_by(TaskRun.started_at.desc()).limit(50))).all()
    return [_run_out(r) for r in rows]


@router.get("/runs/{run_id}/log")
@_400
async def run_log(run_id: str, after: int = 0, session: AsyncSession = Depends(get_session),
                  actor: User = Depends(get_actor)):
    """Строки лога прогона с номером больше `after` (фолбэк-поллинг для панели)."""
    import sqlalchemy as sa

    from repository.models import TaskRunLog

    rows = (await session.execute(
        sa.select(TaskRunLog)
        .where(TaskRunLog.run_id == run_id, TaskRunLog.seq > after)
        .order_by(TaskRunLog.seq).limit(500))).scalars().all()
    return {"items": [{"seq": r.seq, "kind": r.kind, "text": r.text, "data": r.data,
                       "at": r.created_at.isoformat()} for r in rows],
            "last": rows[-1].seq if rows else after}


class InterruptIn(BaseModel):
    reason: str = Field(alias="reason")
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


@router.post("/tasks/{code}/interrupt")
@_400
async def task_interrupt(code: str, payload: InterruptIn,
                         session: AsyncSession = Depends(get_session),
                         actor: User = Depends(get_actor)):
    """Перехват задачи у агента человеком (ФТ-ah-32): прогон помечается прерванным,
    резерв снимается; демон на следующем тике убивает процесс агента."""
    import sqlalchemy as sa

    from repository.models import Task

    task = (await session.execute(sa.select(Task).where(Task.code == code.upper()))).scalar_one_or_none()
    if task is None:
        raise ApiError(404, f"Задача {code} не найдена")
    run = await runs_uc.interrupt(session, actor, task, payload.reason)
    return {"ok": True, "runId": str(run.id)}
