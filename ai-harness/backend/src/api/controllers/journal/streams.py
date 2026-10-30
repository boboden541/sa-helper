"""SSE-потоки: события интерфейса, живая карточка, живой лог прогона
(расщепление journal.py, B2)."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends

from api.deps import actor_snapshot
from repository.models import User

router = APIRouter()


# ---------- живые события интерфейса (решение владельца 27.10.2026) ----------

@router.get("/activity/stream")
async def activity_stream(actor: User = Depends(actor_snapshot)):
    """SSE: задачи «агент работает сейчас» — индикаторы на доске, в списке, в шапке.
    Каждые 2 с — снапшот (изменился → событие); через ~30 мин поток закрывается,
    EventSource переподключается сам."""
    import asyncio

    from fastapi.responses import StreamingResponse

    from usecase.journal.live import activity_snapshot

    from database import get_sessionmaker

    async def gen():
        last = ""
        for _ in range(900):
            async with get_sessionmaker()() as s:
                items = await activity_snapshot(s)
            payload = json.dumps({"tasks": items}, ensure_ascii=False)
            if payload != last:
                last = payload
                yield f"data: {payload}\n\n"
            else:
                yield ": keep-alive\n\n"
            await asyncio.sleep(2.0)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"X-Accel-Buffering": "no",
                                      "Cache-Control": "no-cache"})


@router.get("/tasks/{code}/live")
async def task_live_stream(code: str, actor: User = Depends(actor_snapshot)):
    """SSE карточки: активный прогон (агент, минуты, токены), новые строки лога
    и новые записи хроники — события run / log / chronicle, end в конце цикла."""
    import asyncio
    import datetime as dt

    import sqlalchemy as sa

    from fastapi.responses import StreamingResponse

    from repository.models import Task
    from usecase.journal.live import chronicle_after, log_after, task_activity

    async def gen():
        from database import get_sessionmaker

        after: dt.datetime | None = dt.datetime.now(dt.timezone.utc)
        seen: set[str] = set()
        last_seq = 0
        last_run = ""
        for _ in range(600):  # ~15 мин по 1.5 с
            async with get_sessionmaker()() as s:
                task = (await s.execute(
                    sa.select(Task).where(Task.code == code.upper()))).scalar_one_or_none()
                if task is None:
                    yield "event: end\ndata: not-found\n\n"
                    return
                act = await task_activity(s, task.id)
                if act is not None:
                    payload = json.dumps(act, ensure_ascii=False)
                    if payload != last_run:
                        last_run = payload
                        yield f"event: run\ndata: {payload}\n\n"
                    for line in await log_after(s, act["runId"], last_seq):
                        last_seq = line["seq"]
                        yield f"event: log\ndata: {json.dumps(line, ensure_ascii=False)}\n\n"
                else:
                    if last_run:  # прогон закончился — снимаем живой индикатор карточки
                        yield "event: run\ndata: {}\n\n"
                    last_run = ""
                    last_seq = 0
                items, after = await chronicle_after(s, task.id, after, seen)
                for it in items:
                    yield f"event: chronicle\ndata: {json.dumps(it, ensure_ascii=False)}\n\n"
            yield ": keep-alive\n\n"
            await asyncio.sleep(1.5)
        yield "event: end\ndata: cycle\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"X-Accel-Buffering": "no",
                                      "Cache-Control": "no-cache"})


@router.get("/tasks/{code}/run-log/stream")
async def run_log_stream(code: str, actor: User = Depends(actor_snapshot)):
    # session-зависимости здесь НЕТ сознательно: она прожила бы весь стрим
    # (idle-in-transaction до 30 минут); генератор открывает свежие сессии сам
    """SSE-поток живого лога активного прогона: строки появляются по мере работы агента.
    Отдаёт заголовок X-Accel-Buffering: no — nginx не буферизует этот ответ."""
    import asyncio

    import sqlalchemy as sa

    from fastapi.responses import StreamingResponse

    from repository.models import Task, TaskRun, TaskRunLog

    async def gen():
        from database import get_sessionmaker

        last = 0
        idle = 0
        while True:
            async with get_sessionmaker()() as s:
                task = (await s.execute(
                    sa.select(Task).where(Task.code == code.upper()))).scalar_one_or_none()
                if task is None:
                    yield "event: end\ndata: not-found\n\n"
                    return
                run = (await s.execute(
                    sa.select(TaskRun)
                    .where(TaskRun.task_id == task.id, TaskRun.finished_at.is_(None))
                    .order_by(TaskRun.started_at.desc()).limit(1))).scalar_one_or_none()
                if run is None:
                    idle += 1
                    if idle > 30:  # ~1 мин без активного прогона — закрываем поток
                        yield "event: end\ndata: no-active-run\n\n"
                        return
                    yield ": idle\n\n"
                    await asyncio.sleep(2.0)
                    continue
                idle = 0
                run_id = str(run.id)
                rows = (await s.execute(
                    sa.select(TaskRunLog)
                    .where(TaskRunLog.run_id == run.id, TaskRunLog.seq > last)
                    .order_by(TaskRunLog.seq).limit(200))).scalars().all()
                for r in rows:
                    last = r.seq
                    payload = {"seq": r.seq, "kind": r.kind, "text": r.text,
                               "data": r.data, "at": r.created_at.isoformat()}
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"X-Accel-Buffering": "no",
                                      "Cache-Control": "no-cache"})
