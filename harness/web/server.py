"""Веб-приложение витрины AI Harness (v3, порция G1).

Бэкенд — Python stdlib (эволюция ui/ui_server.py): те же API-эндпоинты плюс
раздача собранного React-приложения (frontend/dist) и классического UI
(/classic). Ноль Python-зависимостей; Node нужен только для сборки фронтенда.

Маршруты:
  /            → frontend/dist (React-приложение; fallback — classic)
  /classic     → classic/index.html (прежний однофайловый UI)
  /api/*       → JSON API (state, stories, task, log, flags, comment, ask, story)
  /events      → SSE

Запуск:
    python3 harness/web/server.py --workspace <корень воркспейса> [--port 4040]
    python3 harness/web/server.py --harness <путь к FNR_N/harness>
"""


from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote
from pathlib import Path

sys_path = str(Path(__file__).resolve().parents[1])
if sys_path not in __import__("sys").path:
    __import__("sys").path.insert(0, sys_path)
import state_machine as sm  # noqa: E402  (та же политика кнопок, что у демона)

STATE: dict = {"harness": None, "workspace": None, "claude_bin": "claude",
               "projects": {}}   # name -> path (порция J: реестр проектов)

REGISTRY_PATH = Path.home() / ".sa-helper" / "workspaces.json"


def load_registry() -> dict:
    """Реестр проектов: ~/.sa-helper/workspaces.json — [{"name", "path"}]."""
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        items = data.get("workspaces", data) if isinstance(data, dict) else data
        return {i["name"]: str(i["path"]) for i in items
                if isinstance(i, dict) and i.get("name") and i.get("path")}
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return {}


def add_project(name: str, path: str) -> tuple[bool, str]:
    safe = name.strip()
    target = Path(path).expanduser()
    if not safe or not target.is_dir():
        return False, "нужны имя и существующий каталог"
    registry = load_registry()
    registry[safe] = str(target.resolve())
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(
        {"workspaces": [{"name": k, "path": v} for k, v in sorted(registry.items())]},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    STATE["projects"][safe] = str(target.resolve())
    return True, safe


def resolve_workspace(project: str | None) -> Path | None:
    """Каталог воркспейса по имени проекта (или одиночный --workspace)."""
    if STATE.get("projects"):
        path = STATE["projects"].get(project or "")
        return Path(path) if path else None
    return STATE.get("workspace")
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

ATTACHMENT_NAME_RE = re.compile(r"[^A-Za-z0-9._\-\u0400-\u04FF]+")
# Разрешённые перемещения задачи по колонкам (порция H-UX): цель -> действие.
# Идут через те же флаги, что и кнопки — машину состояний не обойти.
MOVE_MAP = {
    ("PROPOSED", "BACKLOG"): "TASK_{tid}_ACCEPT",
    ("DONE", "IMPLEMENTING"): "TASK_{tid}_REQUEST_CHANGES",
    ("BLOCKED", "IMPLEMENTING"): "TASK_{tid}_RETRY",
    ("NEEDS_HUMAN", "IMPLEMENTING"): "TASK_{tid}_RETRY",
    ("REVIEW", "DONE"): "TASK_{tid}_FORCE_APPROVE",
}


def _move_targets(pipeline: str) -> list[str]:
    return sorted({to for (frm, to) in MOVE_MAP if frm == pipeline})


TIMELINE_RE = re.compile(r"^\s*-\s+\[([^\]]+?)\s*\|\s*\w+\]\s*(.*)$")


def log_event(harness: Path, message: str) -> None:
    """Запись демона/сервера в журнал событий (тот же формат, что у orchestrator)."""
    logs = harness / "logs"
    logs.mkdir(exist_ok=True)
    line = f"- [{time.strftime('%Y-%m-%d %H:%M:%S')} | daemon] {message}\n"
    with (logs / "events.log").open("a", encoding="utf-8") as fh:
        fh.write(line)


def _attachments_dir(harness: Path, task_id: str) -> Path:
    return harness / "attachments" / task_id


def _timeline_entries(harness: Path, task_id: str) -> list[dict]:
    """События задачи из журнала демона (logs/events.log) по порядку."""
    entries: list[dict] = []
    log_path = harness / "logs" / "events.log"
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return entries
    for line in lines:
        m = TIMELINE_RE.match(line)
        if not m:
            continue
        text = line.rstrip().split("] ", 1)[-1]
        if not text.startswith(f"{task_id}:"):
            continue
        entries.append({"ts": m.group(1), "text": text[len(f"{task_id}:"):].strip()})
    return entries


def _serve_static(self, rel: str) -> bool:
    """Раздать файл из dist; False — файла нет."""
    target = (DIST_DIR / rel).resolve()
    if not str(target).startswith(str(DIST_DIR)) or not target.is_file():
        return False
    ctype = STATIC_TYPES.get(target.suffix, "application/octet-stream")
    self._send(200, target.read_bytes(), ctype)
    return True

# события машины состояний → флаги задач (демон забирает .flags/TASK_...)
ACTION_FLAGS = {
    sm.EV_REQUEST_CHANGES: "REQUEST_CHANGES",
    sm.EV_FORCE_APPROVE: "FORCE_APPROVE",
    sm.EV_RETRY: "RETRY",
    sm.EV_RESUME_WORK: "RESUME_WORK",
    sm.EV_ABORT: "ABORT",
}


def _run_dir(harness: Path | None = None) -> Path:
    return (harness or STATE["harness"]) / ".run"


def resolve_workspace(project: str | None) -> Path | None:
    if STATE.get("projects"):
        path = STATE["projects"].get(project or "")
        return Path(path) if path else None
    return STATE.get("workspace")


def _harness_of(project: str | None, fnr: str | None) -> Path | None:
    """Каталог harness по (проект, FNR) или активный (--harness, одиночный режим)."""
    ws = resolve_workspace(project)
    if ws:
        return ws / "sa_documentation" / "FNR" / (fnr or "") / "harness"
    return STATE["harness"]


_STORIES_CACHE: dict = {}


def list_stories(workspace: Path) -> list[dict]:
    """Stories воркспейса (кэш 2с — SSE и опросы бьют часто)."""
    ws = workspace
    key = str(ws)
    cached = _STORIES_CACHE.get(key)
    if cached and time.time() - cached[0] < 2.0:
        return cached[1]
    stories = []
    for harness in sorted(ws.glob("sa_documentation/FNR/FNR_*/harness")):
        fnr = harness.parent.name
        manifest = {}
        try:
            manifest = json.loads((harness / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = {}
        tasks = manifest.get("tasks", [])
        counts: dict[str, int] = {}
        for t in tasks:
            counts[t.get("pipeline") or "—"] = counts.get(t.get("pipeline") or "—", 0) + 1
        card_cache: dict[str, str] = {}
        task_rows = []
        for t in tasks:
            tid = t.get("id", "")
            if tid not in card_cache:
                cp, _ = find_task_files(harness, tid)
                card_cache[tid] = cp.read_text(encoding="utf-8", errors="replace") \
                    if cp and cp.exists() else ""
            chk = checklist_progress(card_cache[tid])
            task_rows.append({
                "id": tid, "title": t.get("title", ""),
                "pipeline": t.get("pipeline") or "",
                "status": t.get("status", ""), "system": t.get("system", ""),
                "origin": t.get("origin", "plan"),
                "usage": t.get("usage"),
                "plan_done": chk["done"], "plan_total": chk["total"],
                "live": (_live_status(harness, tid) or {}).get("running")
                        if t.get("pipeline") in ("IMPLEMENTING", "REVIEW") else None,
            })
        usage_agg = {"tokens_in": 0, "tokens_out": 0, "tokens_total": 0,
                     "cost_usd": 0.0}
        for t in tasks:
            u = t.get("usage") or {}
            for k in usage_agg:
                usage_agg[k] = round(usage_agg[k] + float(u.get(k) or 0), 4)
        stories.append({
            "fnr": fnr,
            "title": manifest.get("story_title") or manifest.get("source_document") or fnr,
            "status": manifest.get("status", "—"),
            "tasks": len(tasks),
            "counts": counts,
            "usage": usage_agg,
            "task_list": task_rows,
            "handoff_pending": (harness / ".flags" / "HANDOFF").exists(),
            "handoff_failed": (harness / ".run" / "handoff_failed").exists(),
            "manifest_ok": bool(manifest),
        })
    _STORIES_CACHE[key] = (time.time(), stories)
    return stories





CHECKBOX_RE = re.compile(r"^\s*-\s+\[( |~|x|r|b|f)\]\s*(.*)$", re.MULTILINE)
SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
STATE_NAMES = {" ": "todo", "~": "inprog", "x": "done",
               "r": "review", "b": "blocked", "f": "failed"}


def parse_checklist_sections(card_md: str) -> list[dict]:
    """Чек-лист карточки как UI-компонент: секции с элементами и прогрессом.

    Секция = «## Заголовок», после которого встречается ≥1 чекбокс. Строка-
    продолжение (с отступом, до следующего элемента) приклеивается к тексту
    элемента; обычный абзац после списка — нет.
    """
    sections: list[dict] = []
    current: dict | None = None
    pending_title = "Чек-лист"
    last_item: dict | None = None
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
        s["wip"] = sum(1 for i in s["items"]
                       if i["state"] in ("inprog", "review", "blocked", "failed"))
        s["total"] = len(s["items"])
    return sections


def _last_session_summary(harness: Path, task_id: str) -> str:
    """Итог последней сессии задачи: финал result-события её stream-логов."""
    logs = sorted((harness / ".run").glob(f"{task_id}_*_*.log"),
                  key=lambda p: p.stat().st_mtime)
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
    """Stream-json сессии -> человекочитаемая хроника (то, что видно в UI).

    Сырой JSONL остаётся в файле; в витрину отдаётся расшифровка: тексты
    агента, его инструменты, финал сессии. Длительность и итог — из события
    result. Только последние max_events событий.
    """
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


def pid_alive(pid: int) -> bool:
    try:
        if os.name == "nt":
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                                 capture_output=True, text=True, check=False)
            return str(pid) in out.stdout
        os.kill(pid, 0)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def _live_status(harness: Path, tid: str) -> dict | None:
    """Живость стадии: возраст heartbeat и последнее действие агента из stream-лога.

    None — свежих heartbeat нет (стадия не запускалась/давно). last_action —
    последний tool-вызов или фраза агента (хвост 64 КБ, парсинг без LLM).
    """
    run_dir = harness / ".run"
    if not run_dir.is_dir():
        return None
    hbs = sorted(run_dir.glob(f"{tid}_*.hb"), key=lambda p: p.stat().st_mtime)
    if not hbs:
        return None
    newest = hbs[-1]
    age = int(time.time() - newest.stat().st_mtime)
    if age > 7200:  # стадия закончилась больше 2ч назад — не «живость», а история
        return None
    # честность: живость определяет ПРОЦЕСС (pid-файл), а не свежесть hb —
    # hb замирает в момент смерти процесса и ещё ~2 мин выглядит «свежим»
    running = False
    stage = newest.stem.split("_", 1)[1]
    pid_file = run_dir / f"{newest.stem.split('_')[0]}_{stage}.pid"
    if pid_file.exists():
        try:
            running = pid_alive(int(pid_file.read_text(encoding="utf-8").strip()))
        except (OSError, ValueError):
            running = False
    out: dict = {"hb_age_s": age, "running": running}
    logs = sorted(run_dir.glob(f"{tid}_{stage}_*.log"),
                  key=lambda p: p.stat().st_mtime)
    if logs:
        try:
            tail = logs[-1].read_bytes()[-65536:].decode("utf-8", errors="replace")
        except OSError:
            tail = ""
        last_tool = last_text = None
        for line in tail.splitlines():
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("type") == "assistant":
                for b in d.get("message", {}).get("content", []):
                    if b.get("type") == "tool_use":
                        name = b.get("name", "")
                        inp = b.get("input") or {}
                        detail = inp.get("description") or inp.get("file_path") or \
                            str(inp.get("command") or inp.get("pattern") or "")[:60]
                        last_tool = f"{name}: {str(detail)[:80]}" if detail else name
                    elif b.get("type") == "text" and b.get("text", "").strip():
                        last_text = " ".join(b["text"].split())[:100]
        out["last_action"] = last_tool or last_text
    return out


def checklist_progress(card_md: str) -> dict:
    """Суммарный прогресс чек-листов карточки (для канбан-карточки)."""
    sections = parse_checklist_sections(card_md)
    return {"total": sum(s["total"] for s in sections),
            "done": sum(s["done"] for s in sections),
            "in_progress": sum(s["wip"] for s in sections)}


def task_actions(task: dict) -> list[str]:
    """Доступные человеку действия задачи (имена флагов), по машине состояний."""
    actions: list[str] = []
    for event in sm.allowed_events({"pipeline": task.get("pipeline")}):
        flag = ACTION_FLAGS.get(event)
        if flag:
            actions.append(f"TASK_{task.get('id')}_{flag}")
    actions.append(f"TASK_{task.get('id')}_" + ("RESUME_WORK" if task.get("paused") else "PAUSE"))
    return actions


def read_state(harness: Path) -> dict:
    """Snapshot of manifest + flags; never raises on transient states."""
    manifest: dict = {}
    try:
        manifest = json.loads((harness / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    flags_dir = harness / ".flags"
    flags = sorted(p.name for p in flags_dir.glob("*")) if flags_dir.is_dir() else []
    # отпечаток комментариев: любое дописывание тоже выталкивает SSE-событие
    comments_dir = harness / "comments"
    comments_fp = 0
    if comments_dir.is_dir():
        for p in comments_dir.glob("*.md"):
            try:
                comments_fp += p.stat().st_mtime_ns % 1_000_003
            except OSError:
                pass
    card_cache: dict[str, str] = {}
    for t in manifest.get("tasks", []):
        t["actions"] = task_actions(t)
        t["can_ask"] = bool(t.get("session_id"))
        tid = t.get("id", "")
        if tid not in card_cache:
            card_path, _ = find_task_files(harness, tid)
            card_cache[tid] = card_path.read_text(encoding="utf-8", errors="replace") \
                if card_path and card_path.exists() else ""
        t["checklist"] = checklist_progress(card_cache[tid])
        t["live"] = _live_status(harness, tid)
        t["move_targets"] = _move_targets(t.get("pipeline") or "")
    return {"manifest": manifest, "flags": flags, "comments_fp": comments_fp}


def find_task_files(harness: Path, task_id: str) -> tuple[Path | None, Path]:
    """Locate tasks/<id>_*.md and comments/<id>.md for a task id."""
    comments_path = harness / "comments" / f"{task_id}.md"
    card = None
    tasks_dir = harness / "tasks"
    if tasks_dir.is_dir():
        for p in sorted(tasks_dir.glob(f"{task_id}_*.md")) or sorted(tasks_dir.glob(f"{task_id}.md")):
            card = p
            break
    return card, harness / "comments" / f"{task_id}.md"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:  # keep the console quiet
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
        """Раздать файл из dist; False — файла нет."""
        target = (DIST_DIR / rel).resolve()
        if not str(target).startswith(str(DIST_DIR)) or not target.is_file():
            return False
        ctype = STATIC_TYPES.get(target.suffix, "application/octet-stream")
        self._send(200, target.read_bytes(), ctype)
        return True

    def _route(self) -> tuple[str, dict]:
        path, _, query = self.path.partition("?")
        return path, {k: v[-1] for k, v in parse_qs(query).items()}

    def do_GET(self) -> None:
        path, params = self._route()
        project = params.get("project")
        harness = _harness_of(project, params.get("fnr"))
        if path in ("/", "/index.html"):
            index = DIST_DIR / "index.html"
            if index.is_file():
                self._send(200, index.read_bytes(), "text/html; charset=utf-8")
            elif CLASSIC_HTML.is_file():
                self._send(200, CLASSIC_HTML.read_bytes(), "text/html; charset=utf-8")
            else:
                self._send(200, b"<h1>Frontend not built</h1><p>cd frontend && npm ci && npm run build</p>",
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
        elif path == "/api/steward/chat":
            if STATE.get("workspace") is None:
                self._send(400, b'{"error":"need workspace"}', "application/json")
                return
            ws = resolve_workspace(project)
            chat = _steward_dir(ws) / "chat.md"
            raw = chat.read_text(encoding="utf-8", errors="replace") if chat.exists() else ""
            messages = []
            for line in raw.split("\n"):
                m = re.match(r"^\s*-\s+\[([^\]]+?)\s*\|\s*([^\]]+?)\s*\]\s*(.*)$", line)
                if m:
                    messages.append({"ts": m.group(1), "author": m.group(2), "text": m.group(3)})
                elif messages and line.strip():
                    messages[-1]["text"] += "\n" + line
            pending = (_steward_dir(ws) / ".pending").exists()
            self._send(200, json.dumps({"messages": messages, "pending": pending},
                                       ensure_ascii=False).encode("utf-8"), "application/json")
        elif path == "/api/stories":
            ws = resolve_workspace(project)
            self._send(200, json.dumps({"stories": list_stories(ws) if ws else []},
                                       ensure_ascii=False).encode("utf-8"), "application/json")
        elif path == "/api/projects":
            projects = []
            for name in STATE["projects"]:
                ws = resolve_workspace(name)
                s_list = list_stories(ws) if ws else []
                usage = {"tokens_in": 0, "tokens_out": 0, "tokens_total": 0, "cost_usd": 0.0}
                task_count = 0
                for s in s_list:
                    task_count += s["tasks"]
                    for k in usage:
                        usage[k] = round(usage[k] + float((s.get("usage") or {}).get(k) or 0), 4)
                projects.append({"name": name, "path": STATE["projects"][name],
                                 "stories": s_list, "task_count": task_count, "usage": usage})
            self._send(200, json.dumps({"projects": projects},
                                       ensure_ascii=False).encode("utf-8"), "application/json")
        elif path == "/api/state":
            if harness is None or not harness.is_dir():
                self._send(404, b'{"error":"no such story"}', "application/json")
                return
            self._send(200, json.dumps(read_state(harness), ensure_ascii=False).encode("utf-8"), "application/json")
        elif path.startswith("/api/task/"):
            task_id = path.rsplit("/", 1)[1]
            if not re.fullmatch(r"T\d+", task_id):
                self._send(400, b'{"error":"bad task id"}', "application/json")
                return
            card_path, comments_path = find_task_files(harness, task_id)
            state = read_state(harness) if harness and harness.is_dir() else {"manifest": {}}
            task = next((t for t in state["manifest"].get("tasks", []) if t.get("id") == task_id), {})
            card_md = card_path.read_text(encoding="utf-8", errors="replace") \
                if card_path and card_path.exists() else ""
            options = None
            problem = None
            if ws := resolve_workspace(project):
                opt_path = (ws / "sa_documentation" / "harness" / "steward"
                            / "options" / f"{task_id}.json")
                try:
                    options = json.loads(opt_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    options = None
                if task.get("pipeline") in ("BLOCKED", "NEEDS_HUMAN"):
                    problem = {
                        "reason": task.get("blocked_reason") or "",
                        "last_result": _last_session_summary(harness, task_id),
                        "findings": [f for f in (task.get("findings") or [])
                                     if f.get("resolution") != "resolved"],
                        "retries": task.get("retries") or 0,
                        "review_iterations": task.get("review_iterations") or 0,
                        "blocked_from": task.get("blocked_from"),
                    }
            doc = {
                "task": task,
                "card_md": card_md,
                "options": options,
                "problem": problem,
                "comments_md": comments_path.read_text(encoding="utf-8", errors="replace") if comments_path.exists() else "",
                "ask_pending": (_run_dir(harness) / f"{task_id}_ask.pending").exists(),
                "checklist_sections": parse_checklist_sections(card_md),
            }
            self._send(200, json.dumps(doc, ensure_ascii=False).encode("utf-8"), "application/json")
        elif path.startswith("/api/timeline/"):
            task_id = path.rsplit("/", 1)[1]
            if harness is None or not re.fullmatch(r"T\d+", task_id):
                self._send(400, b'{"error":"bad task id"}', "application/json")
                return
            entries = _timeline_entries(harness, task_id)
            self._send(200, json.dumps({"entries": entries},
                                       ensure_ascii=False).encode("utf-8"), "application/json")
        elif path.startswith("/api/attachment/"):
            # GET /api/attachment/<T<k>>/<имя файла>?fnr= — отдать файл
            rest = [unquote(x) for x in path.split("/")[3:]]
            if harness is None or len(rest) != 2:
                self._send(400, b'{"error":"bad attachment path"}', "application/json")
                return
            target = (_attachments_dir(harness, rest[0]) / rest[1]).resolve()
            if not str(target).startswith(str(_attachments_dir(harness, rest[0]).resolve())) \
                    or not target.is_file():
                self._send(404, b'{"error":"not found"}', "application/json")
                return
            ctype = STATIC_TYPES.get(target.suffix, "application/octet-stream")
            self._send(200, target.read_bytes(), ctype)
        elif path == "/api/attachments" and harness is not None:
            task_id = params.get("task", "")
            adir = _attachments_dir(harness, task_id)
            names = sorted(x.name for x in adir.iterdir()) if adir.is_dir() else []
            self._send(200, json.dumps({"files": names}, ensure_ascii=False)
                       .encode("utf-8"), "application/json")
        elif path.startswith("/api/log/"):
            task_id = path.rsplit("/", 1)[1]
            if not re.fullmatch(r"T\d+", task_id) or harness is None:
                self._send(400, b'{"error":"bad task id"}', "application/json")
                return
            logs = sorted(_run_dir(harness).glob(f"{task_id}_*_*.log")) if _run_dir(harness).is_dir() else []
            body = {"log": "", "file": None}
            if logs:
                body = {"log": _readable_tail(logs[-1]),
                        "file": logs[-1].name,
                        "mtime": logs[-1].stat().st_mtime}
            self._send(200, json.dumps(body, ensure_ascii=False).encode("utf-8"),
                       "application/json")
        elif path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            last: str | None = None
            try:
                while True:
                    if STATE.get("workspace"):
                        state = json.dumps({"stories": list_stories()}, ensure_ascii=False)
                    else:
                        state = json.dumps(read_state(STATE["harness"]), ensure_ascii=False)
                    if state != last:
                        self.wfile.write(f"data: {state}\n\n".encode("utf-8"))
                        self.wfile.flush()
                        last = state
                    time.sleep(1)
            except OSError:
                pass
        else:
            self._send(404, b'{"error":"not found"}', "application/json")

    def do_POST(self) -> None:
        path, params = self._route()
        project = params.get("project")
        harness = _harness_of(project, params.get("fnr"))
        if path.startswith("/api/task/") and path.endswith("/move") and harness is not None:
            task_id = path.split("/")[3]
            target = str(self._json_body().get("to") or "").strip()
            state = read_state(harness)
            task = next((t for t in state["manifest"].get("tasks", [])
                         if t.get("id") == task_id), None)
            frm = pipeline_of(task) if task else ""
            if task is None:
                self._send(404, b'{"error":"no such task"}', "application/json")
                return
            flag_tpl = MOVE_MAP.get((frm, target))
            if not flag_tpl:
                self._send(400, json.dumps(
                    {"error": f"переход {frm} → {target} недопустим"},
                    ensure_ascii=False).encode("utf-8"), "application/json")
                return
            flag = flag_tpl.format(tid=task_id)
            (harness / ".flags" / flag).touch()
            log_event(harness, f"{task_id}: человек перемещает {frm} → {target} (флаг {flag})")
            self._send(200, b'{"ok":true}', "application/json")
        elif path.startswith("/api/attachment/") and harness is not None:
            # POST /api/attachment/<T<k>>/<имя>?fnr= — сохранить файл (raw body)
            rest = [unquote(x) for x in path.split("/")[3:]]
            if len(rest) != 2:
                self._send(400, b'{"error":"bad attachment path"}', "application/json")
                return
            safe = ATTACHMENT_NAME_RE.sub("_", rest[1]).strip("._") or "file.bin"
            adir = _attachments_dir(harness, rest[0])
            adir.mkdir(parents=True, exist_ok=True)
            length = int(self.headers.get("Content-Length", 0))
            (adir / safe).write_bytes(self.rfile.read(length))
            log_event(harness, f"{rest[0]}: вложение добавлено человеком: {safe}")
            self._send(200, b'{"ok":true}', "application/json")
        elif path == "/api/projects":
            # POST /api/projects — добавить проект (имя + существующий каталог)
            body = self._json_body()
            ok, info = add_project(str(body.get("name") or "").strip(),
                                   str(body.get("path") or "").strip())
            self._send(200 if ok else 400,
                       json.dumps({"ok": ok, "info": info}, ensure_ascii=False)
                       .encode("utf-8"), "application/json")
        elif path == "/api/steward/message":
            body = self._json_body()
            msg = str(body.get("text") or "").strip()
            if STATE.get("workspace") is None or not msg:
                self._send(400, b'{"error":"need workspace and text"}', "application/json")
                return
            ws = resolve_workspace(project)
            sdir = _steward_dir(ws)
            if (sdir / ".pending").exists():
                self._send(429, b'{"error":"steward is thinking"}', "application/json")
                return
            _steward_chat_append(ws, "human", msg)
            threading.Thread(target=_steward_turn,
                             args=(ws, msg), daemon=True).start()
            self._send(200, b'{"ok":true,"pending":true}', "application/json")
        elif path == "/api/story":
            body = self._json_body()
            ws = resolve_workspace(project)
            ok, info = ("", "") if ws is None else (None, None)
            if ws is None:
                self._send(400, b'{"error":"need project"}', "application/json")
                return
            ok, info = create_story(ws, str(body.get("title") or "").strip(),
                                    str(body.get("source") or "").strip())
            self._send(200 if ok else 400,
                       json.dumps({"ok": ok, "info": info}, ensure_ascii=False).encode("utf-8"),
                       "application/json")
        elif path.startswith("/api/story/") and path.endswith("/task"):
            # ручная Task в Story: UI не пишет манифест — кладёт payload-флаг,
            # демон создаёт карточку и запись (один писатель)
            fnr = path[len("/api/story/"):-len("/task")]
            harness = _harness_of(fnr)
            if harness is None or not harness.is_dir():
                self._send(404, '{"ok":false,"error":"нет такой Story"}'.encode("utf-8"), "application/json")
                return
            body = self._json_body()
            title = str(body.get("title") or "").strip()
            if not title:
                self._send(400, '{"ok":false,"error":"нужен title"}'.encode("utf-8"), "application/json")
                return
            flags_dir = harness / ".flags"
            flags_dir.mkdir(exist_ok=True)
            payload = {"title": title,
                       "description": str(body.get("description") or "").strip()}
            if body.get("system"):
                payload["system"] = str(body["system"]).strip()
            (flags_dir / f"TASK_NEW_{int(time.time() * 1000)}.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            self._send(200, b'{"ok":true,"queued":true}', "application/json")
        elif path.startswith("/api/story/") and path.endswith("/task"):
            fnr = path.split("/")[3]
            target = _harness_of(fnr)
            if target is None or not target.is_dir():
                self._send(404, b'{"error":"no such story"}', "application/json")
                return
            body = self._json_body()
            if not str(body.get("title") or "").strip():
                self._send(400, b'{"error":"need title"}', "application/json")
                return
            flags_dir = target / ".flags"
            flags_dir.mkdir(exist_ok=True)
            payload = {k: body[k] for k in ("title", "description", "system",
                                            "depends_on", "acceptance") if body.get(k)}
            (flags_dir / f"TASK_NEW_{int(time.time() * 1000)}.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            self._send(200, b'{"ok":true}', "application/json")
        elif path.startswith("/api/flag/"):
            name = path.rsplit("/", 1)[1]
            if harness is None:
                self._send(404, b'{"error":"no story"}', "application/json")
                return
            if not re.fullmatch(r"[A-Za-z0-9_]+(\.json)?", name):
                self._send(400, b'{"error":"bad flag name"}', "application/json")
                return
            flags_dir = harness / ".flags"
            flags_dir.mkdir(exist_ok=True)
            if name.endswith(".json"):
                # payload-флаг (TASK_EDIT_<id>.json): тело запроса — содержимое
                body = self._json_body()
                (flags_dir / name).write_text(
                    json.dumps(body, ensure_ascii=False), encoding="utf-8")
            else:
                (flags_dir / name).touch()
            self._send(200, b'{"ok":true}', "application/json")
        elif path.startswith("/api/comment/"):
            task_id = path.rsplit("/", 1)[1]
            text = (self._json_body().get("text") or "").strip()
            if not re.fullmatch(r"T\d+", task_id) or not text or harness is None:
                self._send(400, b'{"error":"need task id and text"}', "application/json")
                return
            _, comments_path = find_task_files(harness, task_id)
            comments_path.parent.mkdir(exist_ok=True)
            ts = time.strftime("%Y-%m-%d %H:%M")
            with comments_path.open("a", encoding="utf-8") as fh:
                fh.write(f"- [{ts} | human] {text}\n")
            self._send(200, b'{"ok":true}', "application/json")
        elif path.startswith("/api/ask/"):
            task_id = path.rsplit("/", 1)[1]
            question = (self._json_body().get("text") or "").strip()
            if not re.fullmatch(r"T\d+", task_id) or not question:
                self._send(400, b'{"error":"need task id and text"}', "application/json")
                return
            if harness is None:
                self._send(404, b'{"error":"no story"}', "application/json")
                return
            task = next((t for t in read_state(harness)["manifest"].get("tasks", [])
                         if t.get("id") == task_id), {})
            session_id = task.get("session_id")
            if not session_id:
                self._send(409, b'{"error":"task has no session yet"}', "application/json")
                return
            if (_run_dir(harness) / f"{task_id}_ask.pending").exists():
                self._send(429, b'{"error":"question already running"}', "application/json")
                return
            threading.Thread(target=_ask_agent,
                             args=(harness, task_id, session_id, question), daemon=True).start()
            self._send(200, b'{"ok":true,"pending":true}', "application/json")
        else:
            self._send(404, b'{"error":"not found"}', "application/json")

    def do_DELETE(self) -> None:
        if self.path.startswith("/api/flag/"):
            name = self.path.rsplit("/", 1)[1]
            try:
                (harness / ".flags" / name).unlink()
            except OSError:
                pass
            self._send(200, b'{"ok":true}', "application/json")
        else:
            self._send(404, b'{"error":"not found"}', "application/json")


def _ask_agent(harness: Path, task_id: str, session_id: str, question: str) -> None:
    """Вопрос агенту задачи: claude --resume <sid>; ответ — в журнал задачи."""
    run_dir = _run_dir(harness)
    run_dir.mkdir(exist_ok=True)
    pending = run_dir / f"{task_id}_ask.pending"
    pending.write_text(question, encoding="utf-8")
    ts = time.strftime("%Y-%m-%d %H:%M")
    comments = harness / "comments" / f"{task_id}.md"
    comments.parent.mkdir(exist_ok=True)
    with comments.open("a", encoding="utf-8") as fh:
        fh.write(f"- [{ts} | human] {question}\n")
    try:
        # канон компоновки: <workspace>/sa_documentation/FNR_N/harness →
        # корень воркспейса (там .claude/commands); при другом раскладе — рядом
        fnr_root = harness.parents[3] if len(harness.parents) > 3 else harness.parent
        if not (fnr_root / ".claude").is_dir():
            fnr_root = harness.parent
        result = subprocess.run(
            [STATE["claude_bin"], "--resume", session_id, "-p", question],
            cwd=str(fnr_root), capture_output=True, text=True, timeout=600,
            stdin=subprocess.DEVNULL)
        answer = (result.stdout or "").strip() or "(агент не вернул ответ)"
    except (OSError, subprocess.SubprocessError) as exc:
        answer = f"(ошибка чата: {exc})"
    finally:
        pending.unlink(missing_ok=True)
    ts = time.strftime("%Y-%m-%d %H:%M")
    with comments.open("a", encoding="utf-8") as fh:
        fh.write(f"- [{ts} | agent] {answer}\n")


def _steward_dir(workspace: Path) -> Path:
    d = workspace / "sa_documentation" / "harness" / "steward"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _steward_chat_append(workspace: Path, author: str, text: str) -> None:
    chat = _steward_dir(workspace) / "chat.md"
    ts = time.strftime("%Y-%m-%d %H:%M")
    with chat.open("a", encoding="utf-8") as fh:
        fh.write(f"- [{ts} | {author}] {text}\n")


def _steward_turn(workspace: Path, message: str) -> None:
    """Один ход Steward: /steward <сообщение> (первый ход) или --resume."""
    sdir = _steward_dir(workspace)
    pending = sdir / ".pending"
    pending.write_text(message, encoding="utf-8")
    session_file = sdir / "session"
    try:
        if session_file.exists():
            args = [STATE["claude_bin"], "--resume",
                    session_file.read_text(encoding="utf-8").strip(),
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
            if doc.get("session_id") and not session_file.exists():
                session_file.write_text(doc["session_id"], encoding="utf-8")
        except json.JSONDecodeError:
            answer = (result.stdout or "").strip()
        if result.returncode != 0 and not answer:
            answer = f"(ошибка Steward: {result.stderr[:300]})"
        _steward_chat_append(workspace, "steward",
                             answer or "(пустой ответ — сессия вернулась без текста)")
    except (OSError, subprocess.SubprocessError) as exc:
        _steward_chat_append(workspace, "steward", f"(ошибка запуска: {exc})")
    finally:
        pending.unlink(missing_ok=True)


def create_story(ws: Path, title: str, source: str) -> tuple[bool, str]:
    """Новая Story из витрины (порция F): каркас FNR_N + СТ + handoff-флаг.

    План строит демон, запуская /impl-handoff; файлы — единственный интерфейс
    между витриной и конвейером (UI не пишет манифесты).
    """
    if not ws:
        return False, "не указан проект"
    if not title or not source:
        return False, "нужны title и source (текст или путь к СТ)"
    existing = [int(d.name[4:]) for d in ws.glob("sa_documentation/FNR/FNR_*")
                if re.fullmatch(r"FNR_\d+", d.name)]
    fnr = f"FNR_{max(existing, default=0) + 1}"
    fnr_dir = ws / "sa_documentation" / "FNR" / fnr
    try:
        source_path = Path(source)
        if source_path.is_file():
            source_text = source_path.read_text(encoding="utf-8", errors="replace")
            source_name = source_path.name
        else:
            source_text, source_name = source, "system_requirements.md"
        (fnr_dir / "harness" / ".flags").mkdir(parents=True, exist_ok=True)
        (fnr_dir / source_name).write_text(source_text, encoding="utf-8")
        (fnr_dir / "harness" / ".flags" / "HANDOFF").write_text(
            json.dumps({"title": title}, ensure_ascii=False), encoding="utf-8")
        (fnr_dir / "harness" / ".run").mkdir(exist_ok=True)
    except OSError as exc:
        return False, f"не удалось создать Story: {exc}"
    print(f"Story {fnr} создана: {title} — демон построит план (/impl-handoff)")
    return True, fnr


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Harness Live Dashboard (stdlib only)")
    parser.add_argument("--harness", help="путь к каталогу FNR_N/harness (одна Story)")
    parser.add_argument("--workspace",
                        help="корень воркспейса: портфель Stories + /api/story")
    parser.add_argument("--project-name", default="",
                        help="имя проекта в портфеле (по умолчанию — имя каталога)")
    parser.add_argument("--port", type=int, default=4040)
    parser.add_argument("--bind", default="127.0.0.1",
                        help="адрес привязки (в Docker: 0.0.0.0)")
    parser.add_argument("--claude-bin", default="claude",
                        help="бинарь claude для чата задачи (тесты: заглушка)")
    args = parser.parse_args()
    if args.workspace:
        wsp = Path(args.workspace).resolve()
        STATE["workspace"] = wsp
        STATE["projects"][args.project_name or wsp.name] = str(wsp)
    else:
        for name, path in load_registry().items():
            STATE["projects"][name] = path
    if args.harness:
        STATE["harness"] = Path(args.harness).resolve()
    STATE["claude_bin"] = args.claude_bin
    server = ThreadingHTTPServer((args.bind, args.port), Handler)
    print(f"AI Harness dashboard: http://127.0.0.1:{args.port}  ({STATE['harness']})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
