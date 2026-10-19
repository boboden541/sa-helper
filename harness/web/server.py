"""Веб-приложение витрины AI Harness на БД (порция R2 миграции на SQLite).

Состояние Story/задач/комментариев/команд — в harness.db (слой db.py);
файлы воркспейса остаются только для runtime-артефактов (stream-логи
стадий, вложения, ask.pending). Markdown — формат контента (карточка,
комментарии рендерятся в канон «- [ts | author] text»).

Маршруты: / и /assets/* — frontend/dist; /classic — legacy UI;
/api/* — JSON API (проекты, stories, state, задачи, команды, комментарии);
/events — SSE (инкремент по курсору events.id).

Запуск:
    python3 harness/web/server.py [--project-name имя] [--workspace путь] [--db путь]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote
from pathlib import Path

sys_path = str(Path(__file__).resolve().parents[1])
if sys_path not in __import__("sys").path:
    __import__("sys").path.insert(0, sys_path)
import state_machine as sm  # noqa: E402
import cards  # noqa: E402
import db as dbmod  # noqa: E402

WEB_DIR = Path(__file__).resolve().parent
DIST_DIR = WEB_DIR / "frontend" / "dist"
CLASSIC_HTML = WEB_DIR / "classic" / "index.html"

STATIC_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript",
                ".css": "text/css", ".svg": "image/svg+xml", ".png": "image/png",
                ".ico": "image/x-icon", ".json": "application/json",
                ".woff2": "font/woff2", ".map": "application/json",
                ".pdf": "application/pdf", ".csv": "text/csv",
                ".txt": "text/plain; charset=utf-8", ".md": "text/markdown; charset=utf-8",
                ".log": "text/plain; charset=utf-8", ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg"}

ATTACHMENT_NAME_RE = re.compile(r"[^A-Za-z0-9._\-Ѐ-ӿ]+")
TASK_ID_RE = re.compile(r"T\d+")

STATE: dict = {"conn": None, "default_project": None, "claude_bin": "claude"}

# Разрешённые перемещения по колонкам (канон v3; цели через команды демону)
MOVE_MAP = {
    ("PROPOSED", "BACKLOG"): "TASK_{tid}_ACCEPT",
    ("DONE", "IMPLEMENTING"): "TASK_{tid}_REQUEST_CHANGES",
    ("BLOCKED", "IMPLEMENTING"): "TASK_{tid}_RETRY",
    ("NEEDS_HUMAN", "IMPLEMENTING"): "TASK_{tid}_RETRY",
    ("REVIEW", "DONE"): "TASK_{tid}_FORCE_APPROVE",
    ("READY", "ABORTED"): "TASK_{tid}_ABORT",
    ("IMPLEMENTING", "ABORTED"): "TASK_{tid}_ABORT",
    ("REVIEW", "ABORTED"): "TASK_{tid}_ABORT",
    ("BLOCKED", "ABORTED"): "TASK_{tid}_ABORT",
    ("NEEDS_HUMAN", "ABORTED"): "TASK_{tid}_ABORT",
}

ACTION_FLAGS = {
    sm.EV_REQUEST_CHANGES: "REQUEST_CHANGES",
    sm.EV_FORCE_APPROVE: "FORCE_APPROVE",
    sm.EV_RETRY: "RETRY",
    sm.EV_RESUME_WORK: "RESUME_WORK",
    sm.EV_ABORT: "ABORT",
}


def conn() -> "dbmod.sqlite3.Connection":
    return STATE["conn"]


def task_actions(task: dict) -> list[str]:
    """Кнопки задачи по машине состояний + PAUSE/RESUME (канон v3)."""
    tid = task.get("id") or task.get("tid")
    actions: list[str] = []
    for event in sm.allowed_events({"pipeline": task.get("pipeline")}):
        flag = ACTION_FLAGS.get(event)
        if flag:
            actions.append(f"TASK_{tid}_{flag}")
    actions.append(f"TASK_{tid}_" + ("RESUME_WORK" if task.get("paused") else "PAUSE"))
    return actions


def _move_targets(pipeline: str) -> list[str]:
    return sorted({to for (frm, to) in MOVE_MAP if frm == pipeline})


def pipeline_of(task: dict) -> str:
    m = {"PLANNED": "BACKLOG", "APPROVED": "READY", "TDD_RED": "IMPLEMENTING",
         "TDD_GREEN": "IMPLEMENTING", "GATES": "IMPLEMENTING",
         "AGENT_REVIEW": "REVIEW", "ESCALATED_BLOCKED": "NEEDS_HUMAN"}
    return task.get("pipeline") or m.get(task.get("v2_status") or "", "BACKLOG")


# ─── вид данных: manifest-view (совместимость с фронтендом) ────────────────

def _usage_view(row) -> dict:
    return {"tokens_in": row["usage_tokens_in"], "tokens_out": row["usage_tokens_out"],
            "tokens_total": row["usage_tokens_total"], "cost_usd": row["usage_cost_usd"],
            "sessions": row["usage_sessions"]}


def task_view(conn, story_id: int, tid: str) -> dict | None:
    """Задача в форме старого манифеста + вычисляемые поля витрины."""
    t = dbmod.read_task(conn, story_id, tid)
    if not t:
        return None
    task = {
        "id": t["tid"], "title": t["title"], "description": t["description"],
        "system": t["system"], "phase": t["phase"], "branch": t["branch"],
        "worktree": t["worktree"], "pipeline": t["pipeline"],
        "status": t["v2_status"], "origin": t["origin"], "owner": t["owner"],
        "paused": bool(t["paused"]), "skip_review": bool(t["skip_review"]),
        "decomposed": bool(t["decomposed"]), "blocked_from": t["blocked_from"],
        "retries": t["retries"], "review_iterations": t["review_iterations"],
        "review_verdict": t["review_verdict"], "blocked_reason": t["blocked_reason"],
        "iteration_count": t["iteration_count"], "session_id": t["session_id"],
        "pipeline_since": t["pipeline_since"],
        "usage": _usage_view(t if isinstance(t, dict) else dict(t)),
        "depends_on": t["depends_on"],
        "acceptance_criteria": [{"id": a["ac_id"], "desc": a["desc"],
                                 "status": a["status"], "test": a["test"]}
                                for a in t["acceptance_criteria"]],
        "gates": t["gates"],
        "card_version": t["card_version"],
    }
    task["pipeline"] = pipeline_of(task)
    task["actions"] = task_actions(task)
    task["can_ask"] = bool(t.get("session_id"))
    task["checklist"] = cards.checklist_progress(t.get("card_md") or "")
    task["description"] = cards.card_preview(t.get("card_md") or "",
                                             t.get("description") or "")
    task["move_targets"] = _move_targets(task["pipeline"])
    task["live"] = _live_view(conn, story_id, tid)
    return task


def _live_view(conn, story_id: int, tid: str) -> dict | None:
    """Живость стадии из sessions (R3 заполнит данными; мигрированные — без живости)."""
    rows = [r for r in dbmod.live_sessions(conn, story_id) if r["tid"] == tid]
    if not rows:
        return None
    r = rows[-1]
    age = 0
    if r["last_beat_at"]:
        try:
            from datetime import datetime
            beat = datetime.fromisoformat(r["last_beat_at"])
            age = max(0, int((datetime.now().astimezone() - beat).total_seconds()))
        except ValueError:
            age = 0
    return {"hb_age_s": age, "running": bool(r["alive"]), "stage": r["stage"]}


def manifest_view(conn, story_id: int) -> dict:
    """Story в форме старого manifest.json (совместимость фронтенда)."""
    story = conn.execute("SELECT * FROM stories WHERE id=?", (story_id,)).fetchone()
    tasks = [task_view(conn, story_id, r["tid"])
             for r in conn.execute("SELECT tid FROM tasks WHERE story_id=? ORDER BY"
                                   " CAST(SUBSTR(tid,2) AS INTEGER)", (story_id,))]
    return {
        "fnr_id": story["fnr"],
        "story_title": story["story_title"],
        "source_document": story["source_name"],
        "status": story["status"],
        "epic_branch": story["epic_branch"],
        "workspace": story["workspace"],
        "paused": bool(story["paused"]),
        "tasks": [t for t in tasks if t],
    }


def flags_view(conn, story_id: int) -> list[str]:
    """Вид .flags/ для фронтенда: имена отложенных команд + PAUSE из состояния."""
    return sorted(dbmod.pending_flags_view(conn, story_id))


def read_state(conn, story_id: int) -> dict:
    return {"manifest": manifest_view(conn, story_id),
            "flags": flags_view(conn, story_id),
            "comments_fp": len(dbmod.list_comments(conn, story_id))}


def _stories_payload(conn, project_id: int) -> dict:
    """Портфель Story (бывший list_stories)."""
    out = []
    for s in conn.execute("SELECT * FROM stories WHERE project_id=? ORDER BY id",
                          (project_id,)):
        sid = int(s["id"])
        counts: dict[str, int] = {}
        for r in conn.execute("SELECT pipeline, COUNT(*) c FROM tasks WHERE story_id=?"
                              " GROUP BY pipeline", (sid,)):
            counts[r["pipeline"]] = r["c"]
        usage = conn.execute(
            "SELECT COALESCE(SUM(usage_tokens_in),0) i, COALESCE(SUM(usage_tokens_out),0) o,"
            " COALESCE(SUM(usage_tokens_total),0) t, COALESCE(SUM(usage_cost_usd),0) c"
            " FROM tasks WHERE story_id=?", (sid,)).fetchone()
        task_rows = []
        for tr in conn.execute("SELECT tid FROM tasks WHERE story_id=? ORDER BY"
                               " CAST(SUBSTR(tid,2) AS INTEGER)", (sid,)):
            t = dbmod.read_task(conn, sid, tr["tid"])
            if not t:
                continue
            task_rows.append({
                "id": t["tid"], "title": t["title"],
                "pipeline": pipeline_of(t), "status": t["v2_status"],
                "system": t["system"], "origin": t["origin"],
                "branch": t["branch"], "paused": bool(t["paused"]),
                "phase": t["phase"],
                "description": cards.card_preview(t.get("card_md") or "",
                                                  t.get("description") or ""),
                "usage": _usage_view(t),
                "plan_done": cards.checklist_progress(t.get("card_md") or "")["done"],
                "plan_total": cards.checklist_progress(t.get("card_md") or "")["total"],
                "live": (_live_view(conn, sid, t["tid"]) or {}).get("running")
                        if t["pipeline"] in ("IMPLEMENTING", "REVIEW") else None,
            })
        out.append({
            "fnr": s["fnr"],
            "title": s["story_title"] or s["fnr"],
            "status": s["status"],
            "tasks": len(task_rows),
            "counts": counts,
            "usage": {"tokens_in": usage["i"], "tokens_out": usage["o"],
                      "tokens_total": usage["t"], "cost_usd": usage["c"]},
            "task_list": task_rows,
            "handoff_pending": s["status"] == "PENDING_HANDOFF",
            "handoff_failed": False,
            "manifest_ok": True,
        })
    return {"stories": out}


# ─── пути runtime-артефактов (логи, вложения, pending) ─────────────────────

def harness_dir(project_row, fnr: str) -> Path:
    return Path(project_row["path"]) / "sa_documentation" / "FNR" / fnr / "harness"


def _last_session_summary(hdir: Path, task_id: str) -> str:
    """Итог последней сессии: финал result-события stream-логов (файлы .run)."""
    run_dir = hdir / ".run"
    logs = sorted(run_dir.glob(f"{task_id}_*_*.log"), key=lambda p: p.stat().st_mtime)
    for log_path in reversed(logs):
        try:
            content = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in reversed(content.splitlines()):
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("type") == "result":
                dur = round(d.get("duration_ms", 0) / 60000, 1)
                txt = " ".join(str(d.get("result") or "").split())
                stage = log_path.name.split("_")[1]
                return (f"сессия «{stage}» ({dur} мин): {txt[:400]}"
                        + ("…" if len(txt) > 400 else ""))
    return "итог последней сессии не найден"


def _readable_tail(path: Path, max_events: int = 60) -> str:
    """Stream-json сессии -> человекочитаемая хроника (как в v3)."""
    try:
        tail = path.read_bytes()[-524288:].decode("utf-8", errors="replace")
    except OSError:
        return "(лог недоступен)"
    lines: list[str] = []
    duration_min = None
    result_text = None
    for raw in tail.splitlines():
        try:
            d = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if d.get("type") == "assistant":
            for b in d.get("message", {}).get("content", []):
                if b.get("type") == "text" and b.get("text", "").strip():
                    txt = " ".join(b["text"].split())
                    lines.append("🤖 " + (txt[:220] + ("…" if len(txt) > 220 else "")))
                elif b.get("type") == "tool_use":
                    name = b.get("name", "?")
                    inp = b.get("input") or {}
                    detail = (inp.get("description") or inp.get("file_path")
                              or inp.get("pattern")
                              or str(inp.get("command") or ""))[:90]
                    lines.append(f"🔧 {name}: {detail}" if detail else f"🔧 {name}")
        elif d.get("type") == "result":
            duration_min = round(d.get("duration_ms", 0) / 60000, 1)
            result_text = " ".join(str(d.get("result") or "").split())
    if duration_min is not None:
        lines.append(f"🏁 Сессия завершена ({duration_min} мин).")
        if result_text:
            lines.append("Итог сессии: " + result_text[:400] +
                         ("…" if len(result_text) > 400 else ""))
    return "\n".join(lines[-max_events:]) or "(событий не найдено)"


def comments_as_md(conn, story_id: int, tid: str) -> str:
    """Журнал задачи в каноне «- [ts | author] text» (контракт фронтенда)."""
    lines = [f"- [{c['ts']} | {c['author']}] {c['body']}"
             for c in dbmod.list_comments(conn, story_id, tid)]
    return "\n".join(lines)


def _ask_agent(project_row, fnr: str, task_id: str, session_id: str, question: str) -> None:
    """Вопрос агенту задачи: claude --resume <sid>; ответ — в comments (БД)."""
    hdir = harness_dir(project_row, fnr)
    run_dir = hdir / ".run"
    run_dir.mkdir(parents=True, exist_ok=True)
    pending = run_dir / f"{task_id}_ask.pending"
    pending.write_text(question, encoding="utf-8")
    story = db_story_by_fnr(project_row, fnr)
    dbmod.append_comment(STATE["conn"], int(story["id"]), task_id, "human", question)
    try:
        fnr_root = hdir.parents[3] if len(hdir.parents) > 3 else hdir.parent
        if not (fnr_root / ".claude").is_dir():
            fnr_root = hdir.parent
        result = subprocess.run(
            [STATE["claude_bin"], "--resume", session_id, "-p", question],
            cwd=str(fnr_root), capture_output=True, text=True, timeout=600,
            stdin=subprocess.DEVNULL)
        answer = (result.stdout or "").strip() or "(агент не вернул ответ)"
    except (OSError, subprocess.SubprocessError) as exc:
        answer = f"(ошибка чата: {exc})"
    finally:
        pending.unlink(missing_ok=True)
    dbmod.append_comment(STATE["conn"], int(story["id"]), task_id, "agent", answer)


def db_story_by_fnr(project_row, fnr: str):
    return dbmod.get_story(STATE["conn"], int(project_row["id"]), fnr)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return {}

    def _serve_static(self, rel: str) -> bool:
        target = (DIST_DIR / rel).resolve()
        if not str(target).startswith(str(DIST_DIR)) or not target.is_file():
            return False
        ctype = STATIC_TYPES.get(target.suffix, "application/octet-stream")
        self._send(200, target.read_bytes(), ctype)
        return True

    def _route(self) -> tuple[str, dict]:
        path, _, query = self.path.partition("?")
        return path, {k: v[-1] for k, v in parse_qs(query).items()}

    def _project(self, params: dict):
        """Проект из ?project=; без параметра — единственный/дефолтный."""
        name = params.get("project") or STATE.get("default_project")
        if name:
            row = dbmod.get_project(conn(), name)
            if row:
                return row
        rows = dbmod.list_projects(conn())
        return rows[0] if len(rows) == 1 else None

    def _story(self, project_row, params: dict):
        fnr = params.get("fnr")
        if not fnr:
            return None
        return dbmod.get_story(conn(), int(project_row["id"]), fnr)

    # обёртка: любая непойманная ошибка → JSON 500, соединение не рвём
    def _safe(self, method) -> None:
        try:
            method()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            traceback.print_exc()
            try:
                self._send(500, json.dumps(
                    {"error": f"внутренняя ошибка сервера: {exc}"},
                    ensure_ascii=False).encode("utf-8"), "application/json")
            except Exception:
                pass

    def do_GET(self) -> None:
        self._safe(self._do_GET)

    def do_POST(self) -> None:
        self._safe(self._do_POST)

    def do_DELETE(self) -> None:
        self._safe(self._do_DELETE)

    def _do_GET(self) -> None:
        path, params = self._route()
        project = self._project(params)
        c = conn()
        if path in ("/", "/index.html"):
            index = DIST_DIR / "index.html"
            if index.is_file():
                self._send(200, index.read_bytes(), "text/html; charset=utf-8")
            elif CLASSIC_HTML.is_file():
                self._send(200, CLASSIC_HTML.read_bytes(), "text/html; charset=utf-8")
            else:
                self._send(200, b"<h1>Frontend not built</h1>"
                                b"<p>cd frontend &amp;&amp; npm ci &amp;&amp; npm run build</p>",
                           "text/html; charset=utf-8")
        elif path == "/classic":
            if CLASSIC_HTML.is_file():
                self._send(200, CLASSIC_HTML.read_bytes(), "text/html; charset=utf-8")
            else:
                self._send(404, b"no classic ui", "text/html; charset=utf-8")
        elif path.startswith("/assets/") and self._serve_static(path.lstrip("/")):
            return
        elif path == "/favicon.ico" and self._serve_static("favicon.ico"):
            return
        elif path == "/api/projects":
            out = []
            for p in dbmod.list_projects(c):
                pid = int(p["id"])
                stories = _stories_payload(c, pid)["stories"]
                usage = {"tokens_in": 0, "tokens_out": 0, "tokens_total": 0, "cost_usd": 0.0}
                task_count = 0
                for s in stories:
                    task_count += s["tasks"]
                    for k in usage:
                        usage[k] = round(usage[k] + float((s.get("usage") or {}).get(k) or 0), 4)
                out.append({"name": p["name"], "path": p["path"], "stories": stories,
                            "task_count": task_count, "usage": usage})
            self._send(200, json.dumps({"projects": out},
                       ensure_ascii=False).encode("utf-8"), "application/json")
        elif path == "/api/stories":
            if project is None:
                self._send(200, b'{"stories":[]}', "application/json")
                return
            self._send(200, json.dumps(_stories_payload(c, int(project["id"])),
                       ensure_ascii=False).encode("utf-8"), "application/json")
        elif path == "/api/state":
            story = self._story(project, params) if project else None
            if story is None:
                self._send(404, b'{"error":"no such story"}', "application/json")
                return
            self._send(200, json.dumps(read_state(c, int(story["id"])),
                       ensure_ascii=False).encode("utf-8"), "application/json")
        elif path.startswith("/api/task/"):
            task_id = path.rsplit("/", 1)[1]
            story = self._story(project, params) if project else None
            if story is None or not TASK_ID_RE.fullmatch(task_id):
                self._send(404, b'{"error":"no such story"}', "application/json")
                return
            sid = int(story["id"])
            task = task_view(c, sid, task_id)
            if task is None:
                self._send(404, b'{"error":"no such task"}', "application/json")
                return
            hdir = harness_dir(project, story["fnr"])
            problem = None
            if task["pipeline"] in ("BLOCKED", "NEEDS_HUMAN"):
                problem = {
                    "reason": task.get("blocked_reason") or "",
                    "last_result": _last_session_summary(hdir, task_id),
                    "findings": [f for f in task.get("findings", [])
                                 if f.get("resolution") != "resolved"],
                    "retries": task.get("retries") or 0,
                    "review_iterations": task.get("review_iterations") or 0,
                    "blocked_from": task.get("blocked_from"),
                }
            options = dbmod.steward_options_get(c, sid, task_id)
            run_dir = hdir / ".run"
            doc = {
                "task": task,
                "card_md": c.execute("SELECT card_md FROM tasks WHERE story_id=? AND tid=?",
                                     (sid, task_id)).fetchone()["card_md"] or "",
                "options": options,
                "problem": problem,
                "comments_md": comments_as_md(c, sid, task_id),
                "ask_pending": (run_dir / f"{task_id}_ask.pending").exists(),
                "checklist_sections": cards.parse_checklist_sections(
                    c.execute("SELECT card_md FROM tasks WHERE story_id=? AND tid=?",
                              (sid, task_id)).fetchone()["card_md"] or ""),
            }
            self._send(200, json.dumps(doc, ensure_ascii=False).encode("utf-8"),
                       "application/json")
        elif path.startswith("/api/timeline/"):
            task_id = path.rsplit("/", 1)[1]
            story = self._story(project, params) if project else None
            if story is None or not TASK_ID_RE.fullmatch(task_id):
                self._send(400, b'{"error":"bad task id"}', "application/json")
                return
            entries = dbmod.timeline(c, int(story["id"]), task_id)
            self._send(200, json.dumps({"entries": entries},
                       ensure_ascii=False).encode("utf-8"), "application/json")
        elif path == "/api/attachments":
            story = self._story(project, params) if project else None
            task_id = params.get("task", "")
            if story is None or not TASK_ID_RE.fullmatch(task_id):
                self._send(400, b'{"error":"bad task id"}', "application/json")
                return
            rows = c.execute("SELECT name FROM attachments WHERE story_id=? AND tid=?"
                             " ORDER BY name", (int(story["id"]), task_id)).fetchall()
            self._send(200, json.dumps({"files": [r["name"] for r in rows]},
                       ensure_ascii=False).encode("utf-8"), "application/json")
        elif path.startswith("/api/attachment/"):
            rest = [unquote(x) for x in path.split("/")[3:]]
            story = self._story(project, params) if project else None
            if story is None or len(rest) != 2:
                self._send(400, b'{"error":"bad attachment path"}', "application/json")
                return
            fdir = harness_dir(project, story["fnr"]) / "attachments" / rest[0]
            target = (fdir / rest[1]).resolve()
            if not str(target).startswith(str(fdir.resolve())) or not target.is_file():
                self._send(404, b'{"error":"not found"}', "application/json")
                return
            ctype = STATIC_TYPES.get(target.suffix, "application/octet-stream")
            self._send(200, target.read_bytes(), ctype)
        elif path.startswith("/api/log/"):
            task_id = path.rsplit("/", 1)[1]
            story = self._story(project, params) if project else None
            if story is None or not TASK_ID_RE.fullmatch(task_id):
                self._send(400, b'{"error":"bad task id"}', "application/json")
                return
            body = {"log": "", "file": None}
            sess = c.execute(
                "SELECT log_path FROM sessions WHERE story_id=? AND tid=?"
                " ORDER BY id DESC LIMIT 1", (int(story["id"]), task_id)).fetchone()
            log_file = Path(sess["log_path"]) if sess and sess["log_path"] else None
            if log_file is None:
                logs = sorted((harness_dir(project, story["fnr"]) / ".run").glob(
                    f"{task_id}_*_*.log")) if harness_dir(project, story["fnr"]).is_dir() else []
                log_file = logs[-1] if logs else None
            if log_file and Path(log_file).is_file():
                body = {"log": _readable_tail(Path(log_file)),
                        "file": Path(log_file).name,
                        "mtime": Path(log_file).stat().st_mtime}
            self._send(200, json.dumps(body, ensure_ascii=False).encode("utf-8"),
                       "application/json")
        elif path == "/api/steward/chat":
            prow = dbmod.get_project(c, params.get("project") or "")
            if prow is None:
                self._send(400, b'{"error":"need project"}', "application/json")
                return
            pid = int(prow["id"])
            messages = [dict(r) for r in c.execute(
                "SELECT ts, author, body AS text FROM steward_messages"
                " WHERE project_id=? ORDER BY id", (pid,))]
            pending = bool(dbmod.steward_get_state(c, pid).get("pending"))
            self._send(200, json.dumps({"messages": messages, "pending": pending},
                       ensure_ascii=False).encode("utf-8"), "application/json")
        elif path == "/events":
            self._sse(project)
        else:
            self._send(404, b'{"error":"not found"}', "application/json")

    def _sse(self, project) -> None:
        """SSE: пуш при появлении новых событий (курсор events.id)."""
        c = conn()
        pid = int(project["id"]) if project is not None else None
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        last_sent: str | None = None
        last_event = 0
        try:
            while True:
                row = c.execute("SELECT COALESCE(MAX(id),0) m FROM events").fetchone()
                fresh = int(row["m"])
                if fresh != last_event or last_sent is None:
                    last_event = fresh
                    if pid is not None:
                        payload = json.dumps(_stories_payload(c, pid), ensure_ascii=False)
                    else:
                        payload = json.dumps({"stories": []}, ensure_ascii=False)
                    if payload != last_sent:
                        self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                        self.wfile.flush()
                        last_sent = payload
                time.sleep(1)
        except OSError:
            pass

    def _do_POST(self) -> None:
        path, params = self._route()
        project = self._project(params)
        c = conn()
        if path.startswith("/api/task/") and path.endswith("/move"):
            story = self._story(project, params) if project else None
            task_id = path.split("/")[3]
            if story is None or not TASK_ID_RE.fullmatch(task_id):
                self._send(404, b'{"error":"no such task"}', "application/json")
                return
            sid = int(story["id"])
            target = str(self._json_body().get("to") or "").strip()
            task = dbmod.read_task(c, sid, task_id, with_card=False)
            frm = pipeline_of(task) if task else ""
            flag_tpl = MOVE_MAP.get((frm, target))
            if not flag_tpl:
                self._send(400, json.dumps(
                    {"error": f"переход {frm} → {target} недопустим"},
                    ensure_ascii=False).encode("utf-8"), "application/json")
                return
            name = flag_tpl.format(tid=task_id)
            dbmod.insert_command(c, sid, name, by="human")
            dbmod.append_event(c, sid, task_id,
                               f"{task_id}: человек перемещает {frm} → {target} ({name})",
                               actor="human", kind="flag")
            self._send(200, b'{"ok":true}', "application/json")
        elif path.startswith("/api/task/") and path.endswith("/card"):
            story = self._story(project, params) if project else None
            task_id = path.split("/")[3]
            if story is None or not TASK_ID_RE.fullmatch(task_id):
                self._send(404, b'{"error":"no such task"}', "application/json")
                return
            sid = int(story["id"])
            body = self._json_body()
            card_md = str(body.get("card_md") or "")
            force = bool(body.get("force"))
            expect_version = body.get("expect_version")
            if not card_md.strip():
                self._send(400, '{"error":"нужен card_md"}'.encode("utf-8"),
                           "application/json")
                return
            if not force and any(s["alive"] for s in dbmod.live_sessions(c, sid)):
                self._send(409, json.dumps(
                    {"error": "сессия задачи жива — правка карточки может "
                              "затереться агентом; подтвердите силу",
                     "running": True}, ensure_ascii=False)
                    .encode("utf-8"), "application/json")
                return
            ok, version = dbmod.task_set_card(
                c, sid, task_id, card_md,
                int(expect_version) if expect_version is not None else None)
            if not ok:
                self._send(409, json.dumps(
                    {"error": "карточка изменена кем-то другим — перечитайте",
                     "card_version": version}, ensure_ascii=False)
                    .encode("utf-8"), "application/json")
                return
            dbmod.append_comment(c, sid, task_id, "human",
                                 "**Карточка обновлена** через витрину "
                                 f"(описание задачи — единый источник; стало: {len(card_md)} симв.)")
            dbmod.append_event(c, sid, task_id, f"{task_id}: карточка обновлена человеком",
                               actor="human", kind="card")
            self._send(200, json.dumps({"ok": True, "card_version": version},
                       ensure_ascii=False).encode("utf-8"), "application/json")
        elif path.startswith("/api/attachment/") and project is not None:
            story = self._story(project, params)
            rest = [unquote(x) for x in path.split("/")[3:]]
            if story is None or len(rest) != 2:
                self._send(400, b'{"error":"bad attachment path"}', "application/json")
                return
            safe = ATTACHMENT_NAME_RE.sub("_", rest[1]).strip("._") or "file.bin"
            adir = harness_dir(project, story["fnr"]) / "attachments" / rest[0]
            adir.mkdir(parents=True, exist_ok=True)
            length = int(self.headers.get("Content-Length", 0))
            (adir / safe).write_bytes(self.rfile.read(length))
            sid = int(story["id"])
            c.execute("INSERT OR IGNORE INTO attachments(story_id, tid, name, path,"
                      " created_at) VALUES (?,?,?,?,?)",
                      (sid, rest[0], safe, str(adir / safe), dbmod.now_iso()))
            c.commit()
            dbmod.append_event(c, sid, rest[0], f"{rest[0]}: вложение добавлено: {safe}",
                               actor="human", kind="attachment")
            self._send(200, b'{"ok":true}', "application/json")
        elif path == "/api/projects":
            body = self._json_body()
            name = str(body.get("name") or "").strip()
            ppath = str(body.get("path") or "").strip()
            if not name or not Path(ppath).is_dir():
                self._send(400, '{"ok":false,"error":"нужны имя и существующий каталог"}'.encode("utf-8"),
                           "application/json")
                return
            dbmod.upsert_project(c, name, str(Path(ppath).resolve()))
            self._send(200, b'{"ok":true}', "application/json")
        elif path == "/api/steward/message":
            body = self._json_body()
            msg = str(body.get("text") or "").strip()
            project = dbmod.get_project(c, params.get("project") or "")
            if project is None or not msg:
                self._send(400, b'{"error":"need project and text"}', "application/json")
                return
            pid = int(project["id"])
            st = dbmod.steward_get_state(c, pid)
            if st.get("pending"):
                self._send(429, b'{"error":"steward is thinking"}', "application/json")
                return
            dbmod.steward_append(c, pid, "human", msg)
            dbmod.steward_set_pending(c, pid, True, msg)
            threading.Thread(target=_steward_turn, args=(project, msg), daemon=True).start()
            self._send(200, b'{"ok":true,"pending":true}', "application/json")
        elif path == "/api/story":
            body = self._json_body()
            if project is None:
                self._send(400, b'{"error":"need project"}', "application/json")
                return
            title = str(body.get("title") or "").strip()
            source = str(body.get("source") or "").strip()
            if not title or not source:
                self._send(400, '{"error":"нужны title и source"}'.encode("utf-8"), "application/json")
                return
            source_path = Path(source)
            if source_path.is_file():
                source_md = source_path.read_text(encoding="utf-8", errors="replace")
                source_name = source_path.name
            else:
                source_md, source_name = source, "system_requirements.md"
            sid = dbmod.create_story(c, int(project["id"]), None, title,
                                     source_md, source_name)
            story = c.execute("SELECT fnr FROM stories WHERE id=?", (sid,)).fetchone()
            dbmod.append_event(c, sid, None,
                               f"{story['fnr']}: Story создана человеком — демон построит план",
                               actor="human", kind="handoff")
            self._send(200, json.dumps({"ok": True, "info": story["fnr"]},
                       ensure_ascii=False).encode("utf-8"), "application/json")
        elif path.startswith("/api/story/") and path.endswith("/task"):
            fnr = path[len("/api/story/"):-len("/task")]
            story = dbmod.get_story(c, int(project["id"]), fnr) if project else None
            if story is None:
                self._send(404, '{"ok":false,"error":"нет такой Story"}'.encode("utf-8"),
                           "application/json")
                return
            body = self._json_body()
            if not str(body.get("title") or "").strip():
                self._send(400, '{"ok":false,"error":"нужен title"}'.encode("utf-8"),
                           "application/json")
                return
            payload = {k: str(body[k]).strip()
                       for k in ("title", "description", "system") if body.get(k)}
            dbmod.insert_command(c, int(story["id"]), "task.new", payload, by="human")
            self._send(200, b'{"ok":true,"queued":true}', "application/json")
        elif path.startswith("/api/flag/"):
            name = path.rsplit("/", 1)[1]
            story = self._story(project, params) if project else None
            if story is None:
                self._send(404, b'{"error":"no story"}', "application/json")
                return
            if not re.fullmatch(r"[A-Za-z0-9_]+(\.json)?", name):
                self._send(400, b'{"error":"bad flag name"}', "application/json")
                return
            sid = int(story["id"])
            if name.endswith(".json"):
                payload = self._json_body()
                kind = "task.edit_desc" if name.startswith("TASK_EDIT_") else name[:-5]
                dbmod.insert_command(c, sid, kind, payload, by="human")
            elif name == "PAUSE":
                dbmod.story_pause(c, sid, True)
                dbmod.append_event(c, sid, None, "Story: пауза конвейера (человек)",
                                   actor="human", kind="flag")
            else:
                dbmod.insert_command(c, sid, name, by="human")
            self._send(200, b'{"ok":true}', "application/json")
        elif path.startswith("/api/comment/"):
            task_id = path.rsplit("/", 1)[1]
            text = (self._json_body().get("text") or "").strip()
            story = self._story(project, params) if project else None
            if story is None or not TASK_ID_RE.fullmatch(task_id) or not text:
                self._send(400, b'{"error":"need task id and text"}', "application/json")
                return
            sid = int(story["id"])
            dbmod.append_comment(c, sid, task_id, "human", text)
            is_attention = False
            task = dbmod.read_task(c, sid, task_id, with_card=False)
            if task and task["pipeline"] in ("NEEDS_HUMAN", "BLOCKED"):
                is_attention = True
                dbmod.insert_command(c, sid, f"TASK_{task_id}_RETRY", by="human")
            elif task and task["pipeline"] == "DONE":
                dbmod.insert_command(c, sid, f"TASK_{task_id}_REQUEST_CHANGES", by="human")
            dbmod.append_event(c, sid, task_id, f"{task_id}: комментарий человека",
                               actor="human", kind="comment")
            self._send(200, b'{"ok":true,"retried":true}' if is_attention
                       else b'{"ok":true}', "application/json")
        elif path.startswith("/api/ask/"):
            task_id = path.rsplit("/", 1)[1]
            question = (self._json_body().get("text") or "").strip()
            story = self._story(project, params) if project else None
            if story is None or not TASK_ID_RE.fullmatch(task_id) or not question:
                self._send(400, b'{"error":"need task id and text"}', "application/json")
                return
            task = dbmod.read_task(c, int(story["id"]), task_id, with_card=False)
            session_id = (task or {}).get("session_id")
            if not session_id:
                self._send(409, b'{"error":"task has no session yet"}', "application/json")
                return
            hdir = harness_dir(project, story["fnr"])
            if (hdir / ".run" / f"{task_id}_ask.pending").exists():
                self._send(429, b'{"error":"question already running"}', "application/json")
                return
            threading.Thread(target=_ask_agent,
                             args=(project, story["fnr"], task_id, session_id, question),
                             daemon=True).start()
            self._send(200, b'{"ok":true,"pending":true}', "application/json")
        else:
            self._send(404, b'{"error":"not found"}', "application/json")

    def _do_DELETE(self) -> None:
        path, params = self._route()
        c = conn()
        if path.startswith("/api/flag/"):
            name = path.rsplit("/", 1)[1]
            story = self._story(self._project(params), params) if self._project(params) else None
            if story is None:
                self._send(404, b'{"error":"no story"}', "application/json")
                return
            sid = int(story["id"])
            if not re.fullmatch(r"[A-Za-z0-9_]+(\.json)?", name):
                self._send(400, b'{"error":"bad flag name"}', "application/json")
                return
            if name == "PAUSE":
                dbmod.story_pause(c, sid, False)
                dbmod.append_event(c, sid, None, "Story: пауза снята (человек)",
                                   actor="human", kind="flag")
            else:
                dbmod.delete_pending_command(c, sid, name)
            self._send(200, b'{"ok":true}', "application/json")
        else:
            self._send(404, b'{"error":"not found"}', "application/json")


def _steward_turn(project_row, message: str) -> None:
    """Один ход Steward: /steward <сообщение> или --resume; ответ в БД."""
    c = conn()
    pid = int(project_row["id"])
    workspace = Path(project_row["path"])
    sdir = workspace / "sa_documentation" / "harness" / "steward"
    sdir.mkdir(parents=True, exist_ok=True)
    session_file = sdir / "session"
    st = dbmod.steward_get_state(c, pid)
    try:
        if st.get("session_id"):
            args = [STATE["claude_bin"], "--resume", st["session_id"],
                    "--output-format", "json", "-p", message]
        else:
            args = [STATE["claude_bin"], "--output-format", "json",
                    "-p", f"/steward {message}"]
        result = subprocess.run(args, cwd=str(workspace), capture_output=True,
                                text=True, timeout=900, stdin=subprocess.DEVNULL)
        answer = ""
        try:
            doc = json.loads(result.stdout or "{}")
            answer = str(doc.get("result") or "").strip()
            if doc.get("session_id") and not st.get("session_id"):
                dbmod.steward_set_session(c, pid, str(doc["session_id"]))
        except json.JSONDecodeError:
            answer = (result.stdout or "").strip()
        if result.returncode != 0 and not answer:
            answer = f"(ошибка Steward: {result.stderr[:300]})"
        dbmod.steward_append(c, pid, "steward",
                             answer or "(пустой ответ — сессия вернулась без текста)")
    except (OSError, subprocess.SubprocessError) as exc:
        dbmod.steward_append(c, pid, "steward", f"(ошибка запуска: {exc})")
    finally:
        dbmod.steward_set_pending(c, pid, False)


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Harness dashboard (SQLite)")
    parser.add_argument("--workspace", help="воркспейс: регистрируется/берётся из БД")
    parser.add_argument("--project-name", default="",
                        help="имя проекта для --workspace")
    parser.add_argument("--port", type=int, default=4040)
    parser.add_argument("--bind", default="127.0.0.1",
                        help="адрес привязки (в Docker: 0.0.0.0)")
    parser.add_argument("--claude-bin", default="claude",
                        help="бинарь claude для чата задачи (тесты: заглушка)")
    parser.add_argument("--db", default=None, help="путь к БД (HARNESS_DB)")
    args = parser.parse_args()
    STATE["conn"] = dbmod.connect(args.db) if args.db else dbmod.connect()
    STATE["claude_bin"] = args.claude_bin
    if args.workspace:
        wsp = Path(args.workspace).resolve()
        name = args.project_name or wsp.name
        dbmod.upsert_project(STATE["conn"], name, str(wsp))
        STATE["default_project"] = name
    print(f"AI Harness dashboard (SQLite): http://127.0.0.1:{args.port}"
          f"  [{dbmod.db_path()}]")
    try:
        server = ThreadingHTTPServer((args.bind, args.port), Handler)
    except OSError as exc:
        print(f"не удалось занять порт {args.port}: {exc}")
        raise SystemExit(1)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
