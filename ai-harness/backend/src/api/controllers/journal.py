"""Контроллеры этапа 5: хроники, уведомления, ПСИ, Eve, очередь (СТ §4.5, §5.6)."""

from __future__ import annotations

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
        [s.model_dump() for s in payload.sections])
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
