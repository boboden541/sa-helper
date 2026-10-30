"""Чеклисты карточки: текстовый формат `- ~ x + !` и `#`–`#####` (ФТ-ah-9, B3).

Парсер и перезапись элементов перенесены из контроллера journal (расщепление B2);
контроллер только проверяет kind, находит задачу и возвращает ответ.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from repository.models import Task, User

STATUS_BY_MARK = {"-": "todo", "~": "in_progress", "x": "closed",
                  "+": "done", "!": "failed"}


def parse_lines(lines: str) -> list[dict]:
    """Текст → список элементов: `#`–`#####` заголовки, `метка текст` пункты."""
    import re

    out: list[dict] = []
    for raw in lines.splitlines():
        line = raw.strip()
        if not line:
            continue
        heading = re.match(r"^(#{1,5})\s+(.*)$", line)
        if heading:
            out.append({"kind": "heading", "level": len(heading.group(1)),
                        "text": heading.group(2), "status": None})
        else:
            item = re.match(r"^([~+x!\-])\s+(.*)$", line)
            status = STATUS_BY_MARK.get(item.group(1), "todo") if item else "todo"
            text = item.group(2) if item else line
            out.append({"kind": "item", "level": None, "text": text, "status": status})
    return out


async def put_checklist(session: AsyncSession, actor: User, task: Task,
                        kind: str, lines: str) -> int:
    """Перезаписывает элементы чеклиста `kind` из текста; пишет событие в хронику.
    Возвращает число занятых строк (позиция последнего элемента + 1)."""
    import sqlalchemy as sa

    from repository.models import Checklist, ChecklistItem, Chronicle

    chk = (await session.execute(
        sa.select(Checklist).where(Checklist.task_id == task.id, Checklist.kind == kind)
    )).scalar_one_or_none()
    if chk is None:
        chk = Checklist(task_id=task.id, kind=kind)
        session.add(chk)
        await session.flush()
    await session.execute(sa.delete(ChecklistItem).where(ChecklistItem.checklist_id == chk.id))

    position = 0
    for element in parse_lines(lines):
        if element["kind"] == "heading":
            session.add(ChecklistItem(checklist_id=chk.id, position=position,
                                      kind="heading", level=element["level"],
                                      text=element["text"]))
        else:
            session.add(ChecklistItem(checklist_id=chk.id, position=position,
                                      kind="item", text=element["text"],
                                      status=element["status"]))
        position += 1
    session.add(Chronicle(task_id=task.id, event_type="field", author_id=actor.id,
                          author_kind="agent" if actor.user_type == "agent" else "human",
                          message=f"Чеклист {kind} обновлён ({position} строк)"))
    await session.commit()
    return position
