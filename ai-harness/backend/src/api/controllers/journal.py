"""Контроллеры этапа 5: хроники, уведомления, ПСИ, Eve, очередь (СТ §4.5, §5.6)."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_actor, get_session
from api.middleware.errors import ApiError
from domain.model.validators import DomainError
from repository.models import User
from usecase.assistant import eve as eve_uc
from usecase.journal import chronicle as chronicle_uc
from usecase.journal import notifications as notif_uc
from usecase.story import psi as psi_uc
from usecase.task.queue_snapshot import snapshot

router = APIRouter(prefix="/api/v1", tags=["journal"])


def _400(fn):
    import functools

    @functools.wraps(fn)  # сохраняем сигнатуру — иначе FastAPI требует query args/kw
    async def wrapper(*args, **kw):
        try:
            return await fn(*args, **kw)
        except DomainError as err:
            raise ApiError(400, err.message, tech=err.tech)
    return wrapper


@router.get("/tasks/{code}/chronicle")
async def chronicle_view(code: str, type: str | None = None,
                         session: AsyncSession = Depends(get_session),
                         actor: User = Depends(get_actor)):
    import sqlalchemy as sa

    from repository.models import Task

    task = (await session.execute(
        sa.select(Task).where(Task.code == code.upper()))).scalar_one_or_none()
    if task is None:
        raise ApiError(404, f"Задача {code} не найдена")
    return {"items": await chronicle_uc.list_for_task(session, task.id, event_type=type)}


@router.get("/notifications")
async def notifications_view(session: AsyncSession = Depends(get_session),
                             actor: User = Depends(get_actor)):
    return {"items": await notif_uc.list_open(session)}


# ---------- ПСИ ----------

class PsiSectionIn(BaseModel):
    heading: str = ""
    items: list[dict] = []
    model_config = ConfigDict(extra="forbid")


class PsiCreateIn(BaseModel):
    sections: list[PsiSectionIn]
    preambleMd: str | None = None  # шапка идеального ПСИ: «что реализовано», словарик, правила
    model_config = ConfigDict(extra="forbid")


class PsiRunIn(BaseModel):
    results: list[dict]
    model_config = ConfigDict(extra="forbid")


@router.get("/stories/{code}/psi")
@_400
async def psi_get(code: str, session: AsyncSession = Depends(get_session),
                  actor: User = Depends(get_actor)):
    return await psi_uc.get_document(session, code)


@router.post("/stories/{code}/psi")
@_400
async def psi_create(code: str, payload: PsiCreateIn,
                     session: AsyncSession = Depends(get_session),
                     actor: User = Depends(get_actor)):
    version = await psi_uc.create_version(
        session, code, actor,
        [s.model_dump() for s in payload.sections],
        preamble_md=payload.preambleMd)
    return {"version": version}


@router.post("/stories/{code}/psi/runs")
@_400
async def psi_run(code: str, payload: PsiRunIn,
                  session: AsyncSession = Depends(get_session),
                  actor: User = Depends(get_actor)):
    return await psi_uc.run_psi(session, code, actor, payload.results)


class PsiLinkIn(BaseModel):
    position: int
    bugCode: str
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


@router.post("/stories/{code}/psi/link-bug")
@_400
async def psi_link(code: str, payload: PsiLinkIn,
                   session: AsyncSession = Depends(get_session),
                   actor: User = Depends(get_actor)):
    await psi_uc.link_bug(session, code, payload.position, payload.bugCode)
    return {"ok": True}


@router.post("/stories/{code}/psi/new-cycle")
@_400
async def psi_new_cycle(code: str, session: AsyncSession = Depends(get_session),
                        actor: User = Depends(get_actor)):
    return {"reset": await psi_uc.new_cycle(session, code)}


# ---------- Eve ----------

class MessageIn(BaseModel):
    text: str
    screenTaskCode: str | None = None
    model_config = ConfigDict(extra="forbid")


@router.post("/assistant/messages")
async def assistant_message(payload: MessageIn,
                            session: AsyncSession = Depends(get_session),
                            actor: User = Depends(get_actor)):
    return await eve_uc.handle_message(session, actor, payload.text,
                                       payload.screenTaskCode)


@router.post("/assistant/messages/stream")
async def assistant_message_stream(payload: MessageIn,
                                   session: AsyncSession = Depends(get_session),
                                   actor: User = Depends(get_actor)):
    """SSE-поток формирования ответа Eve (решение владельца 28.10.2026):
    события progress (что делает агент), delta (куски ответа), done (итог
    с action/intent для интерфейса). Детерминированные ветки отвечают
    одним done без прогресса."""
    import asyncio

    from fastapi.responses import StreamingResponse

    import uuid as uuid_mod

    from usecase.assistant import eve_agent

    turn = uuid_mod.uuid4().hex
    eve_agent.register_turn(turn)
    queue: asyncio.Queue = asyncio.Queue()

    def emit(event: dict) -> None:
        queue.put_nowait(event)

    async def run():
        try:
            result = await eve_uc.handle_message(session, actor, payload.text,
                                                 payload.screenTaskCode, emit=emit,
                                                 turn_id=turn)
        except Exception as err:  # noqa: BLE001 — ошибка уходит в чат
            result = {"reply": f"Внутренняя ошибка: {err}"}
        queue.put_nowait({"type": "done", **result})

    async def gen():
        yield f"data: {json.dumps({'type': 'start', 'turn': turn}, ensure_ascii=False)}\n\n"
        task = asyncio.create_task(run())
        while True:
            event = await queue.get()
            kind = event.pop("type", "done")
            body = json.dumps({"type": kind, **event}, ensure_ascii=False)
            yield f"data: {body}\n\n"
            if kind == "done":
                break
        await task

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"X-Accel-Buffering": "no",
                                      "Cache-Control": "no-cache"})


class TurnAbortIn(BaseModel):
    turn: str
    model_config = ConfigDict(extra="forbid")


@router.post("/assistant/messages/abort")
async def assistant_message_abort(payload: TurnAbortIn,
                                  actor: User = Depends(get_actor)):
    """Стоп-кнопка чата Eve: прерывает формирующийся ответ (решение 28.10.2026)."""
    from usecase.assistant import eve_agent

    return {"ok": eve_agent.request_abort(payload.turn)}


@router.post("/assistant/force")
@_400
async def assistant_force(code: str, to: str, reason: str,
                          session: AsyncSession = Depends(get_session),
                          actor: User = Depends(get_actor)):
    return await eve_uc.plan_force(session, actor, code, to, reason)


@router.get("/assistant/history")
async def assistant_history(session: AsyncSession = Depends(get_session),
                            actor: User = Depends(get_actor)):
    return {"items": await eve_uc.history(session, actor)}


# ---------- очередь ----------

@router.get("/queue")
async def queue_view(session: AsyncSession = Depends(get_session),
                     actor: User = Depends(get_actor)):
    return await snapshot(session)


# ---------- чеклисты карточки (ФТ-ah-9) ----------

@router.get("/tasks/{code}/checklists/{kind}")
@_400
async def checklist_get(code: str, kind: str,
                        session: AsyncSession = Depends(get_session),
                        actor: User = Depends(get_actor)):
    import sqlalchemy as sa

    from repository.models import Checklist, ChecklistItem, Task

    if kind not in ("developer", "reviewer", "tester", "psi"):
        raise ApiError(400, "Неизвестный тип чеклиста")
    task = (await session.execute(
        sa.select(Task).where(Task.code == code.upper()))).scalar_one_or_none()
    if task is None:
        raise ApiError(404, f"Задача {code} не найдена")
    items: list[dict] = []
    chk = (await session.execute(
        sa.select(Checklist).where(Checklist.task_id == task.id, Checklist.kind == kind)
    )).scalar_one_or_none()
    if chk is not None:
        rows = (await session.execute(
            sa.select(ChecklistItem).where(ChecklistItem.checklist_id == chk.id)
            .order_by(ChecklistItem.position))).scalars().all()
        items = [{"position": i.position, "kind": i.kind, "text": i.text,
                  "status": i.status, "level": i.level} for i in rows]
    return {"kind": kind, "items": items}


class ChecklistPutIn(BaseModel):
    lines: str
    model_config = ConfigDict(extra="forbid")


@router.put("/tasks/{code}/checklists/{kind}")
@_400
async def checklist_put(code: str, kind: str, payload: ChecklistPutIn,
                        session: AsyncSession = Depends(get_session),
                        actor: User = Depends(get_actor)):
    """Текстовый формат `- ~ x + !` и `#`–`#####` — парсинг на backend (ФТ-ah-9)."""
    import re

    import sqlalchemy as sa

    from repository.models import Checklist, ChecklistItem, Task

    if kind not in ("developer", "reviewer", "tester", "psi"):
        raise ApiError(400, "Неизвестный тип чеклиста")
    task = (await session.execute(
        sa.select(Task).where(Task.code == code.upper()))).scalar_one_or_none()
    if task is None:
        raise ApiError(404, f"Задача {code} не найдена")

    chk = (await session.execute(
        sa.select(Checklist).where(Checklist.task_id == task.id, Checklist.kind == kind)
    )).scalar_one_or_none()
    if chk is None:
        chk = Checklist(task_id=task.id, kind=kind)
        session.add(chk)
        await session.flush()
    await session.execute(sa.delete(ChecklistItem).where(ChecklistItem.checklist_id == chk.id))

    from repository.models import Chronicle

    position = 0
    for raw in payload.lines.splitlines():
        line = raw.strip()
        if not line:
            continue
        heading = re.match(r"^(#{1,5})\s+(.*)$", line)
        if heading:
            session.add(ChecklistItem(checklist_id=chk.id, position=position,
                                      kind="heading", level=len(heading.group(1)),
                                      text=heading.group(2)))
        else:
            item = re.match(r"^([~+x!\-])\s+(.*)$", line)
            status = {"-": "todo", "~": "in_progress", "x": "closed",
                      "+": "done", "!": "failed"}.get(item.group(1), "todo") if item else "todo"
            text = item.group(2) if item else line
            session.add(ChecklistItem(checklist_id=chk.id, position=position,
                                      kind="item", text=text, status=status))
        position += 1
    session.add(Chronicle(task_id=task.id, event_type="field", author_id=actor.id,
                          author_kind="agent" if actor.user_type == "agent" else "human",
                          message=f"Чеклист {kind} обновлён ({position} строк)"))
    await session.commit()
    return {"ok": True, "lines": position}


# ---------- Комментарии (ФТ-ah-11) ----------

@router.get("/tasks/{code}/comments")
async def comments_get(code: str, session: AsyncSession = Depends(get_session),
                       actor: User = Depends(get_actor)):
    import sqlalchemy as sa

    from repository.models import Task, TaskComment

    task = (await session.execute(sa.select(Task).where(Task.code == code.upper()))).scalar_one_or_none()
    if task is None:
        raise ApiError(404, f"Задача {code} не найдена")
    rows = (await session.execute(
        sa.select(TaskComment, User.name).join(User, User.id == TaskComment.author_id)
        .where(TaskComment.task_id == task.id)
        .order_by(TaskComment.created_at))).all()
    return [{"id": str(c.id), "author": name, "body": c.body,
             "at": c.created_at.isoformat()} for c, name in rows]


class CommentIn(BaseModel):
    body: str
    model_config = ConfigDict(extra="forbid")


@router.post("/tasks/{code}/comments")
async def comments_add(code: str, payload: CommentIn,
                       session: AsyncSession = Depends(get_session),
                       actor: User = Depends(get_actor)):
    import sqlalchemy as sa

    from repository.models import Task, TaskComment

    if not payload.body.strip():
        raise ApiError(400, "Комментарий пуст")
    task = (await session.execute(sa.select(Task).where(Task.code == code.upper()))).scalar_one_or_none()
    if task is None:
        raise ApiError(404, f"Задача {code} не найдена")
    c = TaskComment(task_id=task.id, author_id=actor.id, body=payload.body.strip())
    session.add(c)
    await session.commit()
    return {"id": str(c.id)}


# ---------- Артефакты этапов (ФТ-ah-38): отчёты с версиями ----------

@router.get("/tasks/{code}/artifacts/{kind}")
async def artifact_get(code: str, kind: str,
                       session: AsyncSession = Depends(get_session),
                       actor: User = Depends(get_actor)):
    import sqlalchemy as sa

    from repository.models import Task, TaskArtifact

    if kind not in ("dev_report", "review_report", "qa_report"):
        raise ApiError(400, "Неизвестный вид артефакта")
    task = (await session.execute(sa.select(Task).where(Task.code == code.upper()))).scalar_one_or_none()
    if task is None:
        raise ApiError(404, f"Задача {code} не найдена")
    rows = (await session.execute(
        sa.select(TaskArtifact).where(TaskArtifact.task_id == task.id, TaskArtifact.kind == kind)
        .order_by(TaskArtifact.version))).scalars().all()
    return {"versions": [{"version": r.version, "bodyMd": r.body_md,
                           "at": r.created_at.isoformat()} for r in rows]}


class ArtifactIn(BaseModel):
    body_md: str = Field(alias="bodyMd")
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


@router.post("/tasks/{code}/artifacts/{kind}")
async def artifact_add(code: str, kind: str, payload: ArtifactIn,
                       session: AsyncSession = Depends(get_session),
                       actor: User = Depends(get_actor)):
    import sqlalchemy as sa

    from repository.models import Task, TaskArtifact

    if kind not in ("dev_report", "review_report", "qa_report"):
        raise ApiError(400, "Неизвестный вид артефакта")
    task = (await session.execute(sa.select(Task).where(Task.code == code.upper()))).scalar_one_or_none()
    if task is None:
        raise ApiError(404, f"Задача {code} не найдена")
    version = (await session.execute(
        sa.select(sa.func.coalesce(sa.func.max(TaskArtifact.version), 0))
        .where(TaskArtifact.task_id == task.id, TaskArtifact.kind == kind))).scalar_one() + 1
    from repository.models import Chronicle

    session.add(TaskArtifact(task_id=task.id, kind=kind, version=version,
                             body_md=payload.body_md, created_by=actor.id))
    session.add(Chronicle(task_id=task.id, event_type="field", author_id=actor.id,
                          author_kind="agent" if actor.user_type == "agent" else "human",
                          message=f"Артефакт {kind} v{version} добавлен"))
    await session.commit()
    return {"version": version}


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


# ---------- живые события интерфейса (решение владельца 27.10.2026) ----------

@router.get("/activity/stream")
async def activity_stream(actor: User = Depends(get_actor)):
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
async def task_live_stream(code: str, actor: User = Depends(get_actor)):
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


@router.get("/tasks/{code}/run-log/stream")
async def run_log_stream(code: str, session: AsyncSession = Depends(get_session),
                         actor: User = Depends(get_actor)):
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
    import datetime as dt

    import sqlalchemy as sa

    from repository.models import Chronicle, Task, TaskRun

    task = (await session.execute(sa.select(Task).where(Task.code == code.upper()))).scalar_one_or_none()
    if task is None:
        raise ApiError(404, f"Задача {code} не найдена")
    run = (await session.execute(
        sa.select(TaskRun)
        .where(TaskRun.task_id == task.id, TaskRun.finished_at.is_(None))
        .order_by(TaskRun.started_at.desc()).limit(1))).scalar_one_or_none()
    if run is None:
        raise ApiError(400, "Активного прогона нет — перехватывать нечего")
    now = dt.datetime.now(dt.timezone.utc)
    run.finished_at = now
    run.outcome = "interrupted"
    run.detail = f"перехват человеком: {payload.reason}"[:500]
    task.reserved_by = None
    task.reserved_at = None
    task.heartbeat_at = None
    session.add(Chronicle(task_id=task.id, event_type="agent", author_id=actor.id,
                          author_kind="human",
                          message=f"Прогон прерван человеком: {payload.reason}"[:500]))
    await session.commit()
    return {"ok": True, "runId": str(run.id)}
