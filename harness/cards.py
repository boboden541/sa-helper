"""Парсеры карточек задач (markdown-канон) — общий для сервера, адаптера, мигратора.

Переехали из web/server.py (R1 миграции на БД): сервер, sahelper и db_migrate
используют один и тот же канон чек-листов и превью описания.
"""

from __future__ import annotations

import re

CHECKBOX_RE = re.compile(r"^\s*-\s+\[( |~|x|r|b|f)\]\s*(.*)$", re.MULTILINE)
SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
# канон состояний чек-листа (6): пробел/~/x/r/b/f
STATE_NAMES = {" ": "todo", "~": "inprog", "x": "done",
               "r": "review", "b": "blocked", "f": "failed"}
# секция «Что сделать» — источник превью (единое описание задачи)
CARD_DESC_RE = re.compile(r"^##\s+Что сделать\s*\n\n(.*?)(?=^##\s|\Z)", re.S | re.M)


def parse_checklist_sections(card_md: str) -> list[dict]:
    """Чек-лист карточки: секции с элементами и прогрессом.

    Секция = «## Заголовок», после которого встречается ≥1 чекбокса. Строка-
    продолжение (с отступом, до следующего элемента) приклеивается к тексту
    элемента; обычный абзац после списка — нет.
    """
    sections = []
    current = None
    pending_title = "Чек-лист"
    last_item = None
    for line in (card_md or "").splitlines():
        head = re.match(r"^##\s+(.+?)\s*$", line.strip())
        if head:
            current = None
            last_item = None
            pending_title = head.group(1)
            continue
        box = re.match(r"^\s*-\s+\[( |~|x|r|b|f)\]\s*(.*)$", line)
        if box:
            if current is None:
                current = {"title": pending_title, "items": []}
                sections.append(current)
            last_item = {"state": STATE_NAMES.get(box.group(1), "todo"),
                         "text": box.group(2).strip()}
            current["items"].append(last_item)
            continue
        if last_item is not None and line[:1] in (" ", "\t") and line.strip():
            last_item["text"] += " " + line.strip()
    for s in sections:
        s["done"] = sum(1 for i in s["items"] if i["state"] == "done")
        wip_states = ("inprog", "review", "blocked", "failed")
        s["wip"] = sum(1 for i in s["items"] if i["state"] in wip_states)
        s["total"] = len(s["items"])
    return sections


def checklist_progress(card_md: str) -> dict:
    """Суммарный прогресс чек-листов карточки (для канбан-карточки)."""
    sections = parse_checklist_sections(card_md)
    total = sum(s["total"] for s in sections)
    done = sum(s["done"] for s in sections)
    wip = sum(s["wip"] for s in sections)
    return {"total": total, "done": done, "in_progress": wip}


def card_preview(card_md: str, fallback: str = "", limit: int = 280) -> str:
    """Выжимка карточки для доски/поиска: секция «Что сделать», иначе первый
    абзац (не заголовок/таблица/код/чекбокс), иначе fallback из манифеста."""
    src = card_md or ""
    m = CARD_DESC_RE.search(src)
    text = ""
    if m:
        text = m.group(1)
    else:
        for para in re.split(r"\n\s*\n", src):
            para = para.strip()
            if para and not para.startswith(("#", "|", "```", "- [")):
                text = para
                break
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text or fallback
