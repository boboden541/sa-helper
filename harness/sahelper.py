#!/usr/bin/env python3
"""Адаптер агентов к БД витрины (порция R4): единственная дверь сессий к состоянию.

Роль всегда «session»: v3-домен (pipeline, retries, ...) и потребление команд
запрещены на уровне слоя db.py. Конфликт card_version → exit 3.

Запуск: python3 harness/sahelper.py <команда> ... (cwd = корень воркспейса;
проект резолвится по пути, Story — по FNR-аргументу). Вывод — JSON на stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys_path = str(Path(__file__).resolve().parent)
if sys_path not in __import__("sys").path:
    __import__("sys").path.insert(0, sys_path)
import db as dbmod  # noqa: E402
import cards  # noqa: E402
import state_machine as sm  # noqa: E402

EXIT_OK, EXIT_ERROR, EXIT_USAGE, EXIT_CONFLICT = 0, 1, 2, 3


def out(data) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def die(msg: str, code: int = EXIT_ERROR):
    print(json.dumps({"error": msg}, ensure_ascii=False), flush=True)
    sys.exit(code)


def resolve_project(conn, ws_arg: str | None):
    ws = Path(ws_arg or Path.cwd()).resolve()
    row = dbmod.get_project_by_path(conn, str(ws))
    if row:
        return row
    name = ws.name
    pid = dbmod.upsert_project(conn, name, str(ws))
    return dbmod.get_project(conn, name)


def resolve_story(conn, project_id: int, fnr: str):
    row = dbmod.get_story(conn, project_id, fnr)
    if row is None:
        die(f"нет такой Story: {fnr}")
    return row


def cmd_state(a, conn, pid):
    proj = resolve_project(conn, a.workspace)
    story = resolve_story(conn, int(proj["id"]), a.fnr)
    sid = int(story["id"])
    tasks = []
    for r in conn.execute("SELECT tid FROM tasks WHERE story_id=? ORDER BY"
                          " CAST(SUBSTR(tid,2) AS INTEGER)", (sid,)):
        t = dbmod.read_task(conn, sid, r["tid"], with_card=False)
        tasks.append({
            "id": t["tid"], "title": t["title"], "pipeline": t["pipeline"],
            "status": t["v2_status"], "system": t["system"], "phase": t["phase"],
            "depends_on": t["depends_on"], "paused": bool(t["paused"]),
            "skip_review": bool(t["skip_review"]), "origin": t["origin"],
            "decomposed": bool(t["decomposed"]), "branch": t["branch"],
            "worktree": t["worktree"], "iteration_count": t["iteration_count"],
            "blocked_reason": t["blocked_reason"],
            "actions": _actions(t),
        })
    out({"fnr": story["fnr"], "status": story["status"],
         "story_title": story["story_title"], "auto_review_strategy": story["auto_review_strategy"],
         "circuit_breaker": {"max_iterations_per_task": story["circuit_breaker_max"]},
         "paused": bool(story["paused"]), "flags": sorted(dbmod.pending_flags_view(conn, sid)),
         "systems": [dict(r) for r in conn.execute(
             "SELECT name, path, stack, preset, data_only, bootstrap, build_cmd, test_cmd,"
             " lint_cmd, tests, guidelines FROM story_systems WHERE story_id=?", (sid,))],
         "tasks": tasks})


def _actions(t: dict) -> list[str]:
    acts = []
    for e in sm.allowed_events({"pipeline": t["pipeline"]}):
        flag = {"request_changes": "REQUEST_CHANGES", "force_approve": "FORCE_APPROVE",
                "retry": "RETRY", "resume_work": "RESUME_WORK", "abort": "ABORT"}.get(e)
        if flag:
            acts.append(f"TASK_{t['tid']}_{flag}")
    return acts


def cmd_task(a, conn, pid):
    proj = resolve_project(conn, a.workspace)
    story = resolve_story(conn, int(proj["id"]), a.fnr)
    t = dbmod.read_task(conn, int(story["id"]), a.task)
    if t is None:
        die(f"нет такой задачи: {a.task}")
    t["comments"] = dbmod.list_comments(conn, int(story["id"]), a.task)
    out(t)


def cmd_card(a, conn, pid):
    proj = resolve_project(conn, a.workspace)
    story = resolve_story(conn, int(proj["id"]), a.fnr)
    row = conn.execute("SELECT card_md, card_version FROM tasks WHERE story_id=? AND tid=?",
                       (int(story["id"]), a.task)).fetchone()
    if row is None:
        die(f"нет такой задачи: {a.task}")
    out({"card_md": row["card_md"] or "", "card_version": row["card_version"]})


def cmd_card_set(a, conn, pid):
    proj = resolve_project(conn, a.workspace)
    story = resolve_story(conn, int(proj["id"]), a.fnr)
    sid = int(story["id"])
    body = sys.stdin.read() if a.file == "-" else Path(a.file).read_text(encoding="utf-8")
    ok, version = dbmod.task_set_card(conn, sid, a.task, body,
                                      expect_version=a.expect_version)
    if not ok:
        out({"error": "конфликт версии карточки — перечитайте", "card_version": version})
        sys.exit(EXIT_CONFLICT)
    dbmod.append_comment(conn, sid, a.task, "agent",
                         "Карточка обновлена сессией (канон секций сохранён).")
    dbmod.append_event(conn, sid, a.task, f"{a.task}: карточка обновлена сессией",
                       actor="session", kind="card")
    out({"ok": True, "card_version": version})


def cmd_checklist_set(a, conn, pid):
    proj = resolve_project(conn, a.workspace)
    story = resolve_story(conn, int(proj["id"]), a.fnr)
    sid = int(story["id"])
    row = conn.execute("SELECT card_md, card_version FROM tasks WHERE story_id=? AND tid=?",
                       (sid, a.task)).fetchone()
    if row is None:
        die(f"нет такой задачи: {a.task}")
    section_body = sys.stdin.read() if a.file == "-" else Path(a.file).read_text(encoding="utf-8")
    card = row["card_md"] or ""
    lines = card.splitlines()
    # заменить секцию «## <title>» до следующего «## » (или конца)
    start = end = None
    for i, ln in enumerate(lines):
        if ln.strip() == f"## {a.section}":
            start = i
        elif start is not None and ln.startswith("## "):
            end = i
            break
    block = f"## {a.section}\n\n{section_body.strip()}\n"
    if start is None:
        new_card = card.rstrip() + "\n\n" + block
    else:
        end = end if end is not None else len(lines)
        new_card = "\n".join(lines[:start]) + "\n" + block + "\n".join(lines[end:])
    ok, version = dbmod.task_set_card(conn, sid, a.task, new_card,
                                      expect_version=a.expect_version)
    if not ok:
        out({"error": "конфликт версии карточки — перечитайте", "card_version": version})
        sys.exit(EXIT_CONFLICT)
    out({"ok": True, "card_version": version,
         "sections": [s["title"] for s in cards.parse_checklist_sections(new_card)]})


def cmd_story_init(a, conn, pid):
    proj = resolve_project(conn, a.workspace)
    sid = dbmod.create_story(conn, int(proj["id"]), a.fnr, a.title or "", a.source or "")
    if a.status_planned:
        with dbmod.tx(conn):
            conn.execute("UPDATE stories SET status='PLANNED', created_by='impl-handoff',"
                         " updated_at=? WHERE id=? AND status='PENDING_HANDOFF'",
                         (dbmod.now_iso(), sid))
    out({"ok": True, "story_id": sid,
         "fnr": conn.execute("SELECT fnr FROM stories WHERE id=?", (sid,)).fetchone()["fnr"]})


def cmd_story_status(a, conn, pid):
    proj = resolve_project(conn, a.workspace)
    story = resolve_story(conn, int(proj["id"]), a.fnr)
    if a.status != "AWAITING_APPROVAL":
        die("сессия вправе ставить только AWAITING_APPROVAL (однократно после PLANNED)")
    if not dbmod.story_set_status(conn, int(story["id"]), a.status, by="session"):
        die("переход недоступен (нужен статус PLANNED)")
    dbmod.append_event(conn, int(story["id"]), None,
                       f"{a.fnr}: план готов, ждёт утверждения человеком",
                       actor="session", kind="handoff")
    out({"ok": True, "status": a.status})


def cmd_story_set(a, conn, pid):
    proj = resolve_project(conn, a.workspace)
    story = resolve_story(conn, int(proj["id"]), a.fnr)
    fields = {}
    for k in ("story_title", "epic_branch", "workspace", "auto_mode",
              "auto_review_strategy"):
        v = getattr(a, k, None)
        if v is not None:
            fields[k] = v
    dbmod.story_init(conn, int(story["id"]), fields)
    out({"ok": True})


def cmd_task_create(a, conn, pid):
    proj = resolve_project(conn, a.workspace)
    story = resolve_story(conn, int(proj["id"]), a.fnr)
    spec = json.loads(a.spec or "{}")
    tid = dbmod.task_create(conn, int(story["id"]), spec, origin=a.origin)
    dbmod.append_event(conn, int(story["id"]), tid,
                       f"{tid}: задача создана сессией ({a.origin})", actor="session",
                       kind="task")
    out({"ok": True, "id": tid})


def cmd_task_set(a, conn, pid):
    proj = resolve_project(conn, a.workspace)
    story = resolve_story(conn, int(proj["id"]), a.fnr)
    sid = int(story["id"])
    patch = {}
    if a.status:
        v2 = ("PLANNED", "APPROVED", "TDD_RED", "TDD_GREEN", "GATES",
              "AGENT_REVIEW", "DONE", "ESCALATED_BLOCKED", "ABORTED")
        if a.status not in v2:
            die(f"неизвестный v2-статус: {a.status}")
        patch["status"] = a.status
    if a.iteration_count is not None:
        patch["iteration_count"] = int(a.iteration_count)
    if a.decomposed:
        # владение переходное: сессия декомпозиции помечает факт при pipeline=PROPOSED
        row = conn.execute("SELECT pipeline, origin FROM tasks WHERE story_id=? AND tid=?",
                           (sid, a.task)).fetchone()
        if row is None:
            die(f"нет такой задачи: {a.task}")
        if row["pipeline"] != "PROPOSED" or row["origin"] != "manual":
            die("decomposed ставит только сессия декомпозиции на PROPOSED/manual")
        patch["_decomposed"] = 1
    if a.description is not None:
        patch["_description"] = a.description
    if not patch:
        die("нечего применять: --status/--iteration-count/--decomposed/--description")
    v3 = {k: v for k, v in patch.items() if k.startswith("_")}
    v2 = {k: v for k, v in patch.items() if not k.startswith("_")}
    if v2 and not dbmod.task_set_v2(conn, sid, a.task, v2):
        die(f"нет такой задачи: {a.task}")
    for k, v in v3.items():
        col = "decomposed" if k == "_decomposed" else "description"
        with dbmod.tx(conn):
            conn.execute(f"UPDATE tasks SET {col}=?, updated_at=? WHERE story_id=? AND tid=?",
                         (v, dbmod.now_iso(), sid, a.task))
    out({"ok": True})


def cmd_ac_set(a, conn, pid):
    proj = resolve_project(conn, a.workspace)
    story = resolve_story(conn, int(proj["id"]), a.fnr)
    sid = int(story["id"])
    with dbmod.tx(conn):
        if a.desc is not None:
            conn.execute(
                "INSERT INTO acceptance_criteria(story_id, tid, ac_id, seq, desc_md, status)"
                " VALUES (?,?,?,?,?,'PENDING')"
                " ON CONFLICT(story_id, tid, ac_id) DO UPDATE SET desc_md=excluded.desc_md",
                (sid, a.task, a.ac_id, a.seq, a.desc))
        if a.status:
            hit = conn.execute("SELECT 1 FROM acceptance_criteria WHERE story_id=? AND"
                               " tid=? AND ac_id=?", (sid, a.task, a.ac_id)).fetchone()
            if not hit:
                die(f"AC {a.ac_id} не найден у {a.task}")
            conn.execute("UPDATE acceptance_criteria SET status=? WHERE story_id=?"
                         " AND tid=? AND ac_id=?", (a.status, sid, a.task, a.ac_id))
    out({"ok": True})


def cmd_gates_set(a, conn, pid):
    proj = resolve_project(conn, a.workspace)
    story = resolve_story(conn, int(proj["id"]), a.fnr)
    sid = int(story["id"])
    for gate in ("build", "test", "lint", "coverage", "review"):
        state = getattr(a, gate, None)
        if state:
            with dbmod.tx(conn):
                conn.execute("INSERT INTO gates(story_id, tid, gate, state, updated_at)"
                             " VALUES (?,?,?,?,?)"
                             " ON CONFLICT(story_id, tid, gate) DO UPDATE SET"
                             " state=excluded.state, updated_at=excluded.updated_at",
                             (sid, a.task, gate, state, dbmod.now_iso()))
    out({"ok": True})


def cmd_doc_set(a, conn, pid):
    proj = resolve_project(conn, a.workspace)
    story = resolve_story(conn, int(proj["id"]), a.fnr)
    body = sys.stdin.read() if a.file == "-" else Path(a.file).read_text(encoding="utf-8")
    dbmod.doc_set(conn, int(story["id"]), a.kind, body, tid=a.tid)
    dbmod.append_event(conn, int(story["id"]), a.tid,
                       f"документ {a.kind} обновлён сессией", actor="session", kind="doc")
    out({"ok": True})


def cmd_docs(a, conn, pid):
    proj = resolve_project(conn, a.workspace)
    story = resolve_story(conn, int(proj["id"]), a.fnr)
    sid = int(story["id"])
    rows = conn.execute("SELECT tid, kind, body_md FROM documents WHERE story_id=?"
                        " AND (? IS NULL OR kind=?) ORDER BY kind",
                        (sid, a.kind, a.kind)).fetchall()
    out([{**{"kind": r["kind"], "tid": r["tid"]},
          "body_md": r["body_md"] if not a.body_only else r["body_md"][:400]}
         for r in rows])


def cmd_comment_add(a, conn, pid):
    proj = resolve_project(conn, a.workspace)
    story = resolve_story(conn, int(proj["id"]), a.fnr)
    if a.author not in ("agent", "reviewer", "steward"):
        die("автор сессии: agent | reviewer | steward")
    dbmod.append_comment(conn, int(story["id"]), a.task, a.author, a.text)
    out({"ok": True})


def cmd_verdict_set(a, conn, pid):
    proj = resolve_project(conn, a.workspace)
    story = resolve_story(conn, int(proj["id"]), a.fnr)
    blocking = json.loads(a.blocking) if a.blocking else []
    advisory = json.loads(a.advisory) if a.advisory else []
    dbmod.verdict_add(conn, int(story["id"]), a.task, int(a.iteration), a.status,
                      blocking, advisory)
    dbmod.append_comment(conn, int(story["id"]), a.task, "reviewer",
                         f"**Вердикт: {a.status}** — blocking: {len(blocking)}, "
                         f"advisory: {len(advisory)} (итерация {a.iteration})")
    dbmod.append_event(conn, int(story["id"]), a.task,
                       f"{a.task}: вердикт ревью {a.status} (итерация {a.iteration})",
                       actor="session", kind="review")
    out({"ok": True})


def cmd_flag(a, conn, pid):
    proj = resolve_project(conn, a.workspace)
    story = resolve_story(conn, int(proj["id"]), a.fnr)
    name = a.name
    import re as _re
    if name != "APPROVE_PLAN" and not _re.fullmatch(
            r"TASK_T\d+_(REQUEST_CHANGES|FORCE_APPROVE|RETRY|RESUME_WORK|PAUSE|ABORT|SKIP_REVIEW|ACCEPT|REJECT)", name):
        die("допустимы APPROVE_PLAN и TASK_<id>_<ДЕЙСТВИЕ>")
    payload = json.loads(a.payload) if a.payload else None
    dbmod.insert_command(conn, int(story["id"]), name, payload, by="agent")
    out({"ok": True, "queued": name})


def cmd_story_create(a, conn, pid):
    source_path = Path(a.source)
    if source_path.is_file():
        source_md = source_path.read_text(encoding="utf-8", errors="replace")
    else:
        source_md = a.source
    sid = dbmod.create_story(conn, pid, None, a.title, source_md)
    fnr = conn.execute("SELECT fnr FROM stories WHERE id=?", (sid,)).fetchone()["fnr"]
    out({"ok": True, "fnr": fnr})


def cmd_flags(a, conn, pid):
    proj = resolve_project(conn, a.workspace)
    story = resolve_story(conn, int(proj["id"]), a.fnr)
    sid = int(story["id"])
    story_row = conn.execute("SELECT status, paused FROM stories WHERE id=?", (sid,)).fetchone()
    out({"pending": sorted(dbmod.pending_flags_view(conn, sid)),
         "story_status": story_row["status"],
         "paused": bool(story_row["paused"])})


def cmd_comments(a, conn, pid):
    proj = resolve_project(conn, a.workspace)
    story = resolve_story(conn, int(proj["id"]), a.fnr)
    out(dbmod.list_comments(conn, int(story["id"]), a.task))


def cmd_timeline(a, conn, pid):
    proj = resolve_project(conn, a.workspace)
    story = resolve_story(conn, int(proj["id"]), a.fnr)
    out(dbmod.timeline(conn, int(story["id"]), a.task))


def cmd_validate(a, conn, pid):
    proj = resolve_project(conn, a.workspace)
    story = resolve_story(conn, int(proj["id"]), a.fnr)
    out(dbmod.validate_story(conn, int(story["id"])))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sahelper", description="Адаптер агентов к БД витрины")
    p.add_argument("--workspace", default=None, help="корень воркспейса (по умолчанию cwd)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("stories"); s.set_defaults(fn=lambda a, c, pid: out([
        dict(r) for r in c.execute(
            "SELECT fnr, story_title, status FROM stories WHERE project_id=? ORDER BY id",
            (int(pid),))]))
    s = sub.add_parser("state"); s.add_argument("fnr"); s.set_defaults(fn=cmd_state)
    s = sub.add_parser("task"); s.add_argument("fnr"); s.add_argument("task")
    s.set_defaults(fn=cmd_task)
    s = sub.add_parser("card"); s.add_argument("fnr"); s.add_argument("task")
    s.set_defaults(fn=cmd_card)
    s = sub.add_parser("card-set"); s.add_argument("fnr"); s.add_argument("task")
    s.add_argument("--file", required=True); s.add_argument("--expect-version", type=int, default=None)
    s.set_defaults(fn=cmd_card_set)
    s = sub.add_parser("checklist-set"); s.add_argument("fnr"); s.add_argument("task")
    s.add_argument("--section", required=True); s.add_argument("--file", required=True)
    s.add_argument("--expect-version", type=int, default=None)
    s.set_defaults(fn=cmd_checklist_set)
    s = sub.add_parser("story-init"); s.add_argument("--fnr", default=None)
    s.add_argument("--title", default=""); s.add_argument("--source", default="")
    s.add_argument("--status-planned", action="store_true")
    s.set_defaults(fn=cmd_story_init)
    s = sub.add_parser("story-status"); s.add_argument("fnr"); s.add_argument("status")
    s.set_defaults(fn=cmd_story_status)
    s = sub.add_parser("story-set"); s.add_argument("fnr")
    s.add_argument("--story-title", default=None); s.add_argument("--epic-branch", default=None)
    s.add_argument("--workspace", dest="workspace_field", default=None)
    s.add_argument("--auto-mode", default=None); s.add_argument("--auto-review-strategy", default=None)
    s.set_defaults(fn=_story_set_adapter)
    s = sub.add_parser("task-create"); s.add_argument("fnr"); s.add_argument("spec")
    s.add_argument("--origin", default="plan", choices=["plan", "agent"])
    s.set_defaults(fn=cmd_task_create)
    s = sub.add_parser("task-set"); s.add_argument("fnr"); s.add_argument("task")
    s.add_argument("--status", default=None); s.add_argument("--iteration-count", default=None)
    s.add_argument("--decomposed", action="store_true")
    s.add_argument("--description", default=None)
    s.set_defaults(fn=cmd_task_set)
    s = sub.add_parser("ac-set"); s.add_argument("fnr"); s.add_argument("task"); s.add_argument("ac_id")
    s.add_argument("--desc", default=None); s.add_argument("--status", default=None)
    s.add_argument("--seq", type=int, default=0)
    s.set_defaults(fn=cmd_ac_set)
    s = sub.add_parser("gates-set"); s.add_argument("fnr"); s.add_argument("task")
    for g in ("build", "test", "lint", "coverage", "review"):
        s.add_argument(f"--{g}", default=None)
    s.set_defaults(fn=cmd_gates_set)
    s = sub.add_parser("doc-set"); s.add_argument("fnr"); s.add_argument("--kind", required=True)
    s.add_argument("--file", required=True); s.add_argument("--tid", default=None)
    s.set_defaults(fn=cmd_doc_set)
    s = sub.add_parser("docs"); s.add_argument("fnr"); s.add_argument("--kind", default=None)
    s.add_argument("--body-only", action="store_true")
    s.set_defaults(fn=cmd_docs)
    s = sub.add_parser("comment-add"); s.add_argument("fnr"); s.add_argument("task")
    s.add_argument("--author", default="agent"); s.add_argument("--text", required=True)
    s.set_defaults(fn=cmd_comment_add)
    s = sub.add_parser("verdict-set"); s.add_argument("fnr"); s.add_argument("task")
    s.add_argument("--status", required=True, choices=["APPROVED", "CHANGES_REQUESTED"])
    s.add_argument("--iteration", required=True); s.add_argument("--blocking", default=None)
    s.add_argument("--advisory", default=None)
    s.set_defaults(fn=cmd_verdict_set)
    s = sub.add_parser("flag"); s.add_argument("fnr"); s.add_argument("name")
    s.add_argument("--payload", default=None)
    s.set_defaults(fn=cmd_flag)
    s = sub.add_parser("flags"); s.add_argument("fnr"); s.set_defaults(fn=cmd_flags)
    s = sub.add_parser("story-create")
    s.add_argument("--title", required=True); s.add_argument("--source", required=True)
    s.set_defaults(fn=cmd_story_create)
    s = sub.add_parser("comments"); s.add_argument("fnr"); s.add_argument("task")
    s.set_defaults(fn=cmd_comments)
    s = sub.add_parser("timeline"); s.add_argument("fnr"); s.add_argument("task")
    s.set_defaults(fn=cmd_timeline)
    s = sub.add_parser("validate"); s.add_argument("fnr"); s.set_defaults(fn=cmd_validate)
    return p


def _story_set_adapter(a, conn, pid):
    a.story_title = a.story_title
    a.epic_branch = a.epic_branch
    a.workspace = a.workspace_field
    a.auto_mode = int(a.auto_mode) if a.auto_mode is not None else None
    a.auto_review_strategy = a.auto_review_strategy
    cmd_story_set(a, conn, pid)


def main() -> None:
    parser = build_parser()
    a = parser.parse_args()
    conn = dbmod.connect(os.environ.get("HARNESS_DB"))
    proj = resolve_project(conn, a.workspace)
    a.fn(a, conn, int(proj["id"]))


if __name__ == "__main__":
    main()
