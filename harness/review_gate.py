"""Review-gate конвейера v3 (handoff_pipeline_design.md §3.4).

Детерминированный разбор машиночитаемого вердикта ревью и чистое решение
петли доработки — без LLM. Ревьюер пишет в `reviews/T<k>.md` блок:

    ## Verdict (machine-readable)
    status: APPROVED | CHANGES_REQUESTED
    blocking:
    - <id|-> | file: <путь:строка> | text: <замечание>
    advisory:
    - ...
    previous:
    - <id>: resolved | still_blocking

`id` опционален — при отсутствии вычисляется хешем (file|text), что даёт
стабильные ID находок между итерациями (учат closure_first). `previous` тоже
опционален: если ревьюер не заполнил, демон сам сверит blocking с находками
прошлой итерации в манифесте (по id).
"""

from __future__ import annotations

import hashlib
import re

import state_machine as sm

VERDICT_HEADER = "## Verdict (machine-readable)"
STATUS_LINE_RE = re.compile(r"^status:\s*(APPROVED|CHANGES_REQUESTED)\s*$", re.MULTILINE)
LIST_KEY_RE = re.compile(r"^(blocking|advisory|previous):\s*$")
ITEM_RE = re.compile(r"^-\s+(.*)$")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def finding_id(file: str, text: str) -> str:
    """Стабильный ID находки: хеш (file|text) — переживает итерации доработки."""
    return hashlib.sha1(f"{_normalize(file)}|{_normalize(text)}".encode("utf-8")).hexdigest()[:12]


def _section_lines(md_text: str) -> list[str]:
    """Строки блока вердикта (до следующего '## ' или конца файла)."""
    idx = md_text.find(VERDICT_HEADER)
    if idx < 0:
        return []
    lines = md_text[idx:].splitlines()[1:]
    body: list[str] = []
    for line in lines:
        if line.startswith("## "):
            break
        body.append(line)
    return body


def parse_review_verdict(md_text: str | None) -> dict | None:
    """Разобрать вердикт. None — блока нет (файл в старом формате)."""
    if not md_text:
        return None
    lines = _section_lines(md_text)
    status_match = STATUS_LINE_RE.search("\n".join(lines))
    if not status_match:
        return None
    verdict: dict = {"status": status_match.group(1), "blocking": [], "advisory": [],
                     "previous": {}}
    current: str | None = None
    for line in lines:
        key = LIST_KEY_RE.match(line.strip())
        if key:
            current = key.group(1)
            continue
        item = ITEM_RE.match(line.strip())
        if not item or current is None:
            continue
        payload = item.group(1)
        if current == "previous":
            pid, _, pstatus = payload.partition(":")
            if pstatus.strip() in ("resolved", "still_blocking"):
                verdict["previous"][pid.strip()] = pstatus.strip()
            continue
        parts = [p.strip() for p in payload.split("|")]
        fid = parts[0] if parts and parts[0] not in ("", "-") else None
        file_part = next((p[len("file:"):].strip() for p in parts
                          if p.startswith("file:")), "")
        text_part = next((p[len("text:"):].strip() for p in parts
                          if p.startswith("text:")),
                         parts[-1] if parts else "")
        if not text_part:
            continue
        if not fid:
            fid = finding_id(file_part, text_part)
        verdict[current].append({"id": fid, "file": file_part, "text": text_part})
    return verdict


def review_gate(task: dict, verdict: dict, strategy: str = "closure_first",
                review_iterations_max: int = 3) -> dict:
    """Чистое решение ревью-петли.

    task: задача манифеста (findings прошлой итерации, review_iterations).
    verdict: результат parse_review_verdict().
    strategy: closure_first (по умолчанию) — петля останавливается, когда
        прежние находки закрыты, а ревьюер нашёл новые (иначе исполнитель и
        ревьюер могут топтаться вечно); full_re_review — доработка на любой
        blocking до лимита итераций.

    Возвращает {event, reason, findings}:
      event — EV_REVIEW_APPROVED | EV_REVIEW_CHANGES | EV_REVIEW_STALLED;
      findings — новый массив task.findings (blocking=open, ушедшие=resolved).
    """
    blocking = verdict.get("blocking", [])
    iterations = int(task.get("review_iterations") or 0)
    old_findings = {f.get("id"): f for f in (task.get("findings") or [])}

    # previous: явный из вердикта или авто-сверка с прошлыми находками по id
    previous = dict(verdict.get("previous") or {})
    new_ids = {f["id"] for f in blocking}
    if not previous:
        for fid, old in old_findings.items():
            previous[fid] = "still_blocking" if fid in new_ids else "resolved"

    if verdict.get("status") == "APPROVED" or not blocking:
        resolved = [{**f, "resolution": "resolved"} for f in old_findings.values()]
        return {"event": sm.EV_REVIEW_APPROVED,
                "reason": f"вердикт APPROVED ({len(resolved)} прежних находок закрыто)",
                "findings": resolved}

    findings = []
    for f in blocking:
        resolution = "still_blocking" if previous.get(f["id"]) == "still_blocking" else "open"
        findings.append({**f, "resolution": resolution})
    for fid, old in old_findings.items():
        if fid not in new_ids:
            findings.append({**old, "resolution": "resolved"})

    if iterations >= review_iterations_max:
        return {"event": sm.EV_REVIEW_STALLED,
                "reason": f"лимит итераций ревью ({review_iterations_max}) исчерпан",
                "findings": findings}
    if strategy == "closure_first" and previous:
        still = [fid for fid, st in previous.items() if st == "still_blocking"]
        closed = len(previous) - len(still)
        if not still and closed > 0:
            new_count = sum(1 for f in findings if f["resolution"] == "open")
            return {"event": sm.EV_REVIEW_STALLED,
                    "reason": f"closure_first: прежние находки закрыты ({closed}), "
                              f"но появились новые блокирующие ({new_count}) — нужен человек",
                    "findings": findings}
    return {"event": sm.EV_REVIEW_CHANGES,
            "reason": f"blocking находок: {len(blocking)} → доработка",
            "findings": findings}
