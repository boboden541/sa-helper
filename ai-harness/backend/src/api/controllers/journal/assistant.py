"""Чат Eve: сообщения, SSE-поток, стоп-кнопка, force, история
(расщепление journal.py, B2)."""

from __future__ import annotations

import contextlib
import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_actor, get_session
from repository.models import User
from usecase.assistant import eve as eve_uc

from api.controllers.journal._common import _400, log

router = APIRouter()


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
            log.warning("Eve stream failed", exc_info=True)
            result = {"reply": "Внутренняя ошибка — попробуйте ещё раз"}
        queue.put_nowait({"type": "done", **result})

    async def gen():
        yield f"data: {json.dumps({'type': 'start', 'turn': turn}, ensure_ascii=False)}\n\n"
        task = asyncio.create_task(run())
        try:
            while True:
                event = await queue.get()
                kind = event.pop("type", "done")
                body = json.dumps({"type": kind, **event}, ensure_ascii=False)
                yield f"data: {body}\n\n"
                if kind == "done":
                    break
        finally:
            # клиент отключился — фоновая задача не должна остаться навсегда
            if not task.done():
                task.cancel()
            with contextlib.suppress(Exception):
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
