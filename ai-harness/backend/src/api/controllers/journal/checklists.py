"""Чеклисты карточки: GET и PUT текстовым форматом (ФТ-ah-9; расщепление
journal.py, B2; парсер и запись — в usecase/journal/checklists.py, B3)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_actor, get_session
from api.middleware.errors import ApiError
from repository.models import User
from usecase.journal import checklists as checklists_uc

from api.controllers.journal._common import _400

router = APIRouter()


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
    import sqlalchemy as sa

    from repository.models import Task

    if kind not in ("developer", "reviewer", "tester", "psi"):
        raise ApiError(400, "Неизвестный тип чеклиста")
    task = (await session.execute(
        sa.select(Task).where(Task.code == code.upper()))).scalar_one_or_none()
    if task is None:
        raise ApiError(404, f"Задача {code} не найдена")
    lines = await checklists_uc.put_checklist(session, actor, task, kind, payload.lines)
    return {"ok": True, "lines": lines}
