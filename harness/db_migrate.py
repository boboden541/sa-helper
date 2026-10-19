"""Мигратор файлового воркспейса -> БД и обратно (порция R1).

import  -- файлы -> БД (идемпотентно по естественным ключам);
export  -- БД -> снапшот файлового дерева (бэкап/дифф/откат).

Запуск:
    python3 harness/db_migrate.py import --workspace <путь> [--project имя]
    python3 harness/db_migrate.py export --project имя --out <dir>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys_path = str(Path(__file__).resolve().parent)
if sys_path not in __import__("sys").path:
    __import__("sys").path.insert(0, sys_path)
import cards  # noqa: E402
import db as dbmod  # noqa: E402
import review_gate  # noqa: E402

COMMENT_RE = re.compile(r"^\s*-\s+\[([^\]]+?)\s*\|\s*([A-Za-z_]+)\]\s*(.*)$")
EVENT_RE = re.compile(r"^\s*-\s+\[([^\]]+?)\s*\|\s*([A-Za-z_]+)\]\s*(.*)$")

# md-документы стадии -> kind в таблице documents
DOC_KINDS = {
    "dossier.md": "dossier",
    "execution_plan.md": "execution_plan",
    "verification_report.md": "verification_report",
    "pr_draft.md": "pr_draft",
    "handoff_report.md": "handoff_report",
}


def _norm_author(a: str) -> str:
    a = (a or "").strip().lower()
    return a if a in ("human", "agent", "daemon", "reviewer", "steward") else "daemon"


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _find_card(harness: Path, tid: str) -> Path | None:
    tasks_dir = harness / "tasks"
    if not tasks_dir.is_dir():
        return None
    hits = sorted(tasks_dir.glob(f"{tid}_*.md")) or sorted(tasks_dir.glob(f"{tid}.md"))
    return hits[0] if hits else None


def import_workspace(conn, ws: Path, project_name: str | None = None) -> dict:
    """Файлы воркспейса -> БД. Идемпотентно: повторный запуск обновляет/дополняет."""
    ws = Path(ws).resolve()
    name = project_name or ws.name
    pid = dbmod.upsert_project(conn, name, str(ws))
    report = {"project": name, "stories": 0, "tasks": 0, "comments": 0,
              "events": 0, "reviews": 0, "documents": 0}
    registry = {}
    reg_path = Path.home() / ".sa-helper" / "workspaces.json"
    try:
        data = json.loads(reg_path.read_text(encoding="utf-8"))
        items = data.get("workspaces", data) if isinstance(data, dict) else data
        registry = {i["name"]: str(i["path"]) for i in items
                    if isinstance(i, dict) and i.get("name") and i.get("path")}
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        pass

    for harness in sorted(ws.glob("sa_documentation/FNR/FNR_*/harness")):
        fnr = harness.parent.name
        mfile = harness / "manifest.json"
        if not mfile.is_file():
            continue
        try:
            man = json.loads(mfile.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        story = dbmod.get_story(conn, pid, fnr)
        if story:
            sid = int(story["id"])
            with dbmod.tx(conn):
                conn.execute(
                    "UPDATE stories SET story_title=?, source_md=COALESCE(NULLIF(source_md,''),?),"
                    " source_name=?, status=COALESCE(NULLIF(?,''),status), updated_at=? WHERE id=?",
                    (man.get("story_title") or story["story_title"],
                     (ws / "sa_documentation" / "FNR" / fnr / (man.get("source_document") or "")).read_text(encoding="utf-8", errors="replace") if man.get("source_document") and not story["source_md"] else story["source_md"],
                     man.get("source_document") or story["source_name"],
                     man.get("status") or "", dbmod.now_iso(), sid))
        else:
            src = man.get("source_document") or ""
            src_path = ws / "sa_documentation" / "FNR" / fnr / src if src else None
            source_md = src_path.read_text(encoding="utf-8", errors="replace") if src_path and src_path.is_file() else ""
            sid = dbmod.create_story(conn, pid, fnr, man.get("story_title") or fnr, source_md, src)
            with dbmod.tx(conn):
                if man.get("status"):
                    conn.execute("UPDATE stories SET status=? WHERE id=?",
                                 (man["status"], sid))
        report["stories"] += 1
        for s in man.get("systems") or []:
            conn.execute(
                "INSERT INTO story_systems(story_id, name, path, stack, preset, data_only, bootstrap)"
                " VALUES (?,?,?,?,?,?,?)"
                " ON CONFLICT(story_id, name) DO UPDATE SET path=excluded.path,"
                " stack=excluded.stack, preset=excluded.preset, data_only=excluded.data_only,"
                " bootstrap=excluded.bootstrap",
                (sid, s.get("name"), s.get("path"), s.get("stack"), s.get("preset"),
                 1 if s.get("data_only") else 0, s.get("bootstrap")))
        pending_deps: list[tuple[int, str, list[str]]] = []
        for t in man.get("tasks") or []:
            tid = str(t.get("id") or "").strip()
            if not tid:
                continue
            card_p = _find_card(harness, tid)
            card_md = card_p.read_text(encoding="utf-8", errors="replace") if card_p else ""
            u = t.get("usage") or {}
            with dbmod.tx(conn):
                conn.execute(
                    "INSERT INTO tasks(story_id, tid, title, description, system, phase,"
                    " branch, worktree, v2_status, pipeline, origin, decomposed,"
                    " blocked_from, retries, review_iterations, retry_after_ts,"
                    " pipeline_since, paused, skip_review, owner, session_id,"
                    " review_verdict, blocked_reason, iteration_count,"
                    " usage_tokens_in, usage_tokens_out, usage_tokens_total,"
                    " usage_cost_usd, card_md, card_version, created_at, updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)"
                    " ON CONFLICT(story_id, tid) DO UPDATE SET"
                    " title=excluded.title, description=excluded.description,"
                    " system=excluded.system, phase=excluded.phase, branch=excluded.branch,"
                    " worktree=excluded.worktree, v2_status=excluded.v2_status,"
                    " pipeline=excluded.pipeline, origin=excluded.origin,"
                    " decomposed=excluded.decomposed, blocked_from=excluded.blocked_from,"
                    " retries=excluded.retries, review_iterations=excluded.review_iterations,"
                    " retry_after_ts=excluded.retry_after_ts,"
                    " pipeline_since=excluded.pipeline_since, paused=excluded.paused,"
                    " skip_review=excluded.skip_review, owner=excluded.owner,"
                    " session_id=excluded.session_id,"
                    " review_verdict=excluded.review_verdict,"
                    " blocked_reason=excluded.blocked_reason,"
                    " iteration_count=excluded.iteration_count,"
                    " usage_tokens_in=excluded.usage_tokens_in,"
                    " usage_tokens_out=excluded.usage_tokens_out,"
                    " usage_tokens_total=excluded.usage_tokens_total,"
                    " usage_cost_usd=excluded.usage_cost_usd",
                    (sid, tid, t.get("title") or tid, t.get("description") or "",
                     t.get("system"), t.get("phase") or "regular",
                     t.get("branch") or "", t.get("worktree"),
                     t.get("status") or "PLANNED",
                     t.get("pipeline") or "BACKLOG", t.get("origin") or "plan",
                     1 if t.get("decomposed") else 0, t.get("blocked_from"),
                     t.get("retries") or 0, t.get("review_iterations") or 0,
                     t.get("retry_after_ts"), t.get("pipeline_since"),
                     1 if t.get("paused") else 0, 1 if t.get("skip_review") else 0,
                     t.get("owner"), t.get("session_id"), t.get("review_verdict"),
                     t.get("blocked_reason"), t.get("iteration_count") or 0,
                     u.get("tokens_in") or 0, u.get("tokens_out") or 0,
                     u.get("tokens_total") or 0, u.get("cost_usd") or 0.0,
                     "", dbmod.now_iso(), dbmod.now_iso()))
                conn.execute(
                    "UPDATE tasks SET card_md=? WHERE story_id=? AND tid=?"
                    " AND (card_md IS NULL OR card_md='')",
                    (card_md, sid, tid))
            report["tasks"] += 1
            for ac in t.get("acceptance_criteria") or []:
                conn.execute(
                    "INSERT INTO acceptance_criteria(story_id, tid, ac_id, seq, desc_md, test, status)"
                    " VALUES (?,?,?,?,?,?,?)"
                    " ON CONFLICT(story_id, tid, ac_id) DO UPDATE SET desc_md=excluded.desc_md,"
                    " test=excluded.test, status=excluded.status",
                    (sid, tid, ac.get("id"), int(ac.get("seq") or 0),
                     ac.get("desc") or "", ac.get("test"), ac.get("status") or "PENDING"))
            pending_deps.append((sid, tid, [str(d) for d in (t.get("depends_on") or [])]))
            for fr in t.get("fr_ids") or []:
                conn.execute("INSERT OR IGNORE INTO task_frs(story_id, tid, fr_id)"
                             " VALUES (?,?,?)", (sid, tid, str(fr)))
            for g, st in (t.get("gates") or {}).items():
                conn.execute(
                    "INSERT INTO gates(story_id, tid, gate, state) VALUES (?,?,?,?)"
                    " ON CONFLICT(story_id, tid, gate) DO UPDATE SET state=excluded.state",
                    (sid, tid, g, st or "pending"))
        # зависимости — вторым проходом (FK требует существования обеих задач)
        for sid, tid, deps in pending_deps:
            for d in deps:
                conn.execute("INSERT OR IGNORE INTO task_deps(story_id, tid, dep_tid)"
                             " VALUES (?,?,?)", (sid, tid, d))

        # карточки, комментарии, события, ревью, документы, steward — после задач
        for cfile in sorted((harness / "comments").glob("T*.md")):
            tid = cfile.stem
            if not conn.execute("SELECT 1 FROM tasks WHERE story_id=? AND tid=?",
                                (sid, tid)).fetchone():
                continue
            n0 = report["comments"]
            for line in _read(cfile).splitlines():
                m = COMMENT_RE.match(line)
                if not m:
                    continue
                ts, author, body = m.group(1).strip(), _norm_author(m.group(2)), m.group(3).strip()
                if not body:
                    continue
                conn.execute(
                    "INSERT INTO comments(story_id, tid, ts, author, body)"
                    " SELECT ?,?,?,?,? WHERE NOT EXISTS (SELECT 1 FROM comments"
                    " WHERE story_id=? AND tid=? AND ts=? AND author=? AND body=?)",
                    (sid, tid, ts, author, body, sid, tid, ts, author, body))
                report["comments"] += 1
            _ = n0
        efile = harness / "logs" / "events.log"
        if efile.is_file():
            for line in _read(efile).splitlines():
                m = EVENT_RE.match(line)
                if not m:
                    continue
                ts, actor, text = m.group(1).strip(), _norm_author(m.group(2)), m.group(3).strip()
                tid = None
                mm = re.match(r"^(T\d+):", text)
                if mm:
                    tid = mm.group(1)
                conn.execute(
                    "INSERT INTO events(story_id, tid, ts, actor, kind, text)"
                    " SELECT ?,?,?,?, 'legacy', ? WHERE NOT EXISTS (SELECT 1 FROM events"
                    " WHERE story_id=? AND ts=? AND text=?)",
                    (sid, tid, ts, actor or "daemon", text, sid, ts, text))
                report["events"] += 1
        for rfile in sorted((harness / "reviews").glob("T*_*.md")):
            tid = rfile.name.split("_", 1)[0]
            if not conn.execute("SELECT 1 FROM tasks WHERE story_id=? AND tid=?",
                                (sid, tid)).fetchone():
                continue
            body = _read(rfile)
            with dbmod.tx(conn):
                conn.execute(
                    "INSERT INTO documents(story_id, tid, kind, body_md, updated_at)"
                    " VALUES (?,?,?,?,?)"
                    " ON CONFLICT(story_id, tid, kind) DO UPDATE SET body_md=excluded.body_md",
                    (sid, tid, "review", body, dbmod.now_iso()))
            report["documents"] += 1
            try:
                v = review_gate.parse_review_verdict(body)
            except Exception:
                v = None
            if v and v.get("status"):
                iteration = 0
                trow = conn.execute(
                    "SELECT review_iterations FROM tasks WHERE story_id=? AND tid=?",
                    (sid, tid)).fetchone()
                if trow and trow["review_iterations"]:
                    iteration = int(trow["review_iterations"])
                it = max(1, iteration)
                exists = conn.execute(
                    "SELECT 1 FROM review_verdicts WHERE story_id=? AND tid=? AND iteration=?",
                    (sid, tid, it)).fetchone()
                if not exists:
                    dbmod.verdict_add(conn, sid, tid, it,
                                      v.get("status"),
                                      v.get("blocking") or [], v.get("advisory") or [])
                    report["reviews"] += 1
        for fname, kind in DOC_KINDS.items():
            f = harness / fname
            if f.is_file():
                with dbmod.tx(conn):
                    conn.execute(
                        "INSERT INTO documents(story_id, tid, kind, body_md, updated_at)"
                        " VALUES (?,?,?,?,?)"
                        " ON CONFLICT(story_id, tid, kind) DO UPDATE SET body_md=excluded.body_md",
                        (sid, None, kind, _read(f), dbmod.now_iso()))
                report["documents"] += 1
        flags_dir = harness / ".flags"
        if flags_dir.is_dir():
            for f in flags_dir.iterdir():
                if f.name == "HANDOFF" or f.name.startswith("HANDOFF"):
                    continue
                if f.is_file() and not f.name.endswith(".json"):
                    conn.execute(
                        "INSERT INTO commands(story_id, name, created_by, created_at)"
                        " SELECT ?,?, 'human', ? WHERE NOT EXISTS (SELECT 1 FROM commands"
                        " WHERE story_id=? AND name=? AND consumed_at IS NULL)",
                        (sid, f.name, dbmod.now_iso(), sid, f.name))
                elif f.is_file():
                    try:
                        payload = json.loads(f.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        continue
                    kind = "task.new" if f.name.startswith("TASK_NEW_") else "task.edit_desc"
                    conn.execute(
                        "INSERT INTO commands(story_id, name, payload, created_by, created_at)"
                        " SELECT ?,?,?, 'human', ? WHERE NOT EXISTS (SELECT 1 FROM commands"
                        " WHERE story_id=? AND name=? AND consumed_at IS NULL)",
                        (sid, kind, json.dumps(payload, ensure_ascii=False),
                         dbmod.now_iso(), sid, kind))

        # steward-канал воркспейса (chat/session/options)
        sdir = ws / "sa_documentation" / "harness" / "steward"
        if sdir.is_dir():
            chat = sdir / "chat.md"
            if chat.is_file():
                for line in _read(chat).splitlines():
                    m = COMMENT_RE.match(line)
                    if not m:
                        continue
                    conn.execute(
                        "INSERT INTO steward_messages(project_id, ts, author, body)"
                        " SELECT ?,?,?,? WHERE NOT EXISTS (SELECT 1 FROM steward_messages"
                        " WHERE project_id=? AND ts=? AND author=? AND body=?)",
                        (pid, m.group(1).strip(), _norm_author(m.group(2)),
                         m.group(3).strip(), pid, m.group(1).strip(),
                         _norm_author(m.group(2)), m.group(3).strip()))
            sess = sdir / "session"
            if sess.is_file():
                sid_txt = _read(sess).strip()
                if sid_txt:
                    conn.execute(
                        "INSERT INTO steward_state(project_id, session_id) VALUES (?,?)"
                        " ON CONFLICT(project_id) DO UPDATE SET session_id=excluded.session_id",
                        (pid, sid_txt))
            opts = sdir / "options"
            if opts.is_dir():
                for f in opts.glob("T*.json"):
                    tid = f.stem
                    if conn.execute("SELECT 1 FROM tasks WHERE story_id=? AND tid=?",
                                    (sid, tid)).fetchone():
                        dbmod.steward_options_set(conn, sid, tid, _read(f))
    return report


def _manifest_of(conn, sid: int, fnr: str) -> dict:
    """Собрать манифест старого формата из БД (для экспорта/отката)."""
    story = conn.execute("SELECT * FROM stories WHERE id=?", (sid,)).fetchone()
    man: dict = {
        "fnr_id": fnr,
        "story_title": story["story_title"],
        "source_document": story["source_name"],
        "status": story["status"] if story["status"] != "PENDING_HANDOFF" else "PLANNED",
        "epic_branch": story["epic_branch"],
        "workspace": story["workspace"],
        "auto_mode": bool(story["auto_mode"]),
        "auto_review_strategy": story["auto_review_strategy"],
        "circuit_breaker": {"max_iterations_per_task": story["circuit_breaker_max"]},
        "tasks": [],
    }
    for row in conn.execute("SELECT tid FROM tasks WHERE story_id=? ORDER BY"
                            " CAST(SUBSTR(tid,2) AS INTEGER)", (sid,)):
        t = dbmod.read_task(conn, sid, row["tid"])
        man["tasks"].append({
            "id": t["tid"], "title": t["title"], "description": t["description"],
            "system": t["system"], "phase": t["phase"], "branch": t["branch"],
            "worktree": t["worktree"], "status": t["v2_status"],
            "pipeline": t["pipeline"], "origin": t["origin"],
            "decomposed": bool(t["decomposed"]), "blocked_from": t["blocked_from"],
            "retries": t["retries"], "review_iterations": t["review_iterations"],
            "retry_after_ts": t["retry_after_ts"], "pipeline_since": t["pipeline_since"],
            "paused": bool(t["paused"]), "skip_review": bool(t["skip_review"]),
            "owner": t["owner"], "session_id": t["session_id"],
            "review_verdict": t["review_verdict"], "blocked_reason": t["blocked_reason"],
            "iteration_count": t["iteration_count"],
            "usage": {"tokens_in": t["usage_tokens_in"], "tokens_out": t["usage_tokens_out"],
                      "tokens_total": t["usage_tokens_total"],
                      "cost_usd": t["usage_cost_usd"]},
            "depends_on": t["depends_on"], "fr_ids": t["fr_ids"],
            "acceptance_criteria": [{"id": a["ac_id"], "desc": a["desc"],
                                     "status": a["status"], "test": a["test"]}
                                    for a in t["acceptance_criteria"]],
            "gates": t["gates"],
            "findings": [{"id": f["fid"], "text": f["text"], "file": f["file"],
                          "resolution": f["resolution"]} for f in t["findings"]],
        })
    return man


def export_workspace(conn, project_name: str, out: Path) -> dict:
    """БД -> снапшот файлового дерева (бэкап/дифф/откат)."""
    out = Path(out)
    proj = dbmod.get_project(conn, project_name)
    if not proj:
        return {"error": f"проект {project_name} не найден"}
    pid = int(proj["id"])
    report = {"project": project_name, "stories": 0, "files": 0}
    for srow in dbmod.list_story_ids(conn, pid):
        fnr = srow["fnr"]
        sid = int(srow["id"])
        fdir = out / fnr / "harness"
        (fdir / "tasks").mkdir(parents=True, exist_ok=True)
        (fdir / "comments").mkdir(parents=True, exist_ok=True)
        (fdir / "logs").mkdir(parents=True, exist_ok=True)
        (fdir / "reviews").mkdir(parents=True, exist_ok=True)
        man = _manifest_of(conn, sid, fnr)
        (fdir / "manifest.json").write_text(
            json.dumps(man, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report["files"] += 1
        for trow in conn.execute("SELECT tid, card_md FROM tasks WHERE story_id=?", (sid,)):
            if trow["card_md"]:
                (fdir / "tasks" / f"{trow['tid']}.md").write_text(
                    trow["card_md"], encoding="utf-8")
                report["files"] += 1
        for c in dbmod.list_comments(conn, sid):
            tid = c.get("tid") or "STORY"
            if tid == "STORY":
                continue
            with (fdir / "comments" / f"{tid}.md").open("a", encoding="utf-8") as fh:
                body = c["body"].replace("\n", "\n  ")
                fh.write(f"- [{c['ts']} | {c['author']}] {body}\n")
                report["files"] += 1
        lines = [f"- [{e['ts']} | {e['actor']}] {e['text']}"
                 for e in dbmod.events_after(conn, sid, 0)]
        (fdir / "logs" / "events.log").write_text(
            "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        report["files"] += 1
        for drow in conn.execute(
                "SELECT tid, kind, body_md FROM documents WHERE story_id=?", (sid,)):
            if drow["kind"] == "review" and drow["tid"]:
                (fdir / "reviews" / f"{drow['tid']}_review.md").write_text(
                    drow["body_md"], encoding="utf-8")
            elif drow["kind"] in DOC_KINDS.values():
                name = [k for k, v in DOC_KINDS.items() if v == drow["kind"]][0]
                (fdir / name).write_text(drow["body_md"], encoding="utf-8")
            report["files"] += 1
        report["stories"] += 1
    sdir = out / "steward"
    sdir.mkdir(parents=True, exist_ok=True)
    chat_lines = [f"- [{r['ts']} | {r['author']}] {r['body']}" for r in conn.execute(
        "SELECT ts, author, body FROM steward_messages WHERE project_id=? ORDER BY id",
        (pid,))]
    (sdir / "chat.md").write_text("\n".join(chat_lines) + ("\n" if chat_lines else ""),
                                  encoding="utf-8")
    st = dbmod.steward_get_state(conn, pid)
    if st.get("session_id"):
        (sdir / "session").write_text(st["session_id"], encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Мигратор файлы <-> БД")
    sub = parser.add_subparsers(dest="cmd", required=True)
    imp = sub.add_parser("import", help="файлы воркспейса -> БД")
    imp.add_argument("--workspace", required=True)
    imp.add_argument("--project", default=None)
    exp = sub.add_parser("export", help="БД -> снапшот файлового дерева")
    exp.add_argument("--project", required=True)
    exp.add_argument("--out", required=True)
    exp.add_argument("--db", default=None, help="путь к БД (по умолчанию ~/.sa-helper/harness.db)")
    imp.add_argument("--db", default=None)
    args = parser.parse_args()
    conn = dbmod.connect(args.db) if args.db else dbmod.connect()
    if args.cmd == "import":
        print(json.dumps(import_workspace(conn, Path(args.workspace), args.project),
                         ensure_ascii=False, indent=2))
    else:
        print(json.dumps(export_workspace(conn, args.project, Path(args.out)),
                         ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
