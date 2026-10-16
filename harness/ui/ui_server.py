"""Local live dashboard for the AI Harness contour (v2 §8).

One-command, zero-dependency viewer: the agent never knows about browsers or
sockets — it only reads/writes manifest.json, tasks/, comments/ and .flags/.
The server:

  GET  /                → index.html (kanban, dark)
  GET  /api/state       → {manifest, flags} JSON snapshot
  GET  /events          → SSE stream; pushes state on every change (1s poll)
  GET  /api/task/<id>   → {task, card_md, comments_md} — task detail view
  POST /api/flag/<NAME> → create .flags/<NAME> (APPROVE_PLAN, PAUSE, APPROVE_T2, ...)
  DELETE /api/flag/<NAME> → remove the flag
  POST /api/comment/<id> → append a human comment to comments/<id>.md
                           (body: {"text": "..."}; agent comments use the same file)

Binds 127.0.0.1 only (no firewall prompts, no external exposure). Manifest is
written by the agent atomically (tmp + rename), so a reader sees either the old
or the new document — a transient parse miss is skipped until the next tick.
Comments live in comments/T<k>.md (append-only markdown), NOT in the manifest:
both the agent and a human may append without racing the manifest writer.

Usage:
    python3 harness/ui/ui_server.py --harness <path/to/FNR_N/harness> [--port 4040]

Cross-platform (macOS/Linux and Windows Git Bash); stdlib only.
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
from pathlib import Path

sys_path = str(Path(__file__).resolve().parents[1])
if sys_path not in __import__("sys").path:
    __import__("sys").path.insert(0, sys_path)
import state_machine as sm  # noqa: E402  (та же политика кнопок, что у демона)

STATE: dict = {"harness": None, "claude_bin": "claude"}

# события машины состояний → флаги задач (демон забирает .flags/TASK_...)
ACTION_FLAGS = {
    sm.EV_REQUEST_CHANGES: "REQUEST_CHANGES",
    sm.EV_FORCE_APPROVE: "FORCE_APPROVE",
    sm.EV_RETRY: "RETRY",
    sm.EV_RESUME_WORK: "RESUME_WORK",
    sm.EV_ABORT: "ABORT",
}


def _run_dir() -> Path:
    return STATE["harness"] / ".run"


CHECKBOX_RE = re.compile(r"^\s*-\s+\[( |~|x)\]\s*(.*)$", re.MULTILINE)
SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
STATE_NAMES = {" ": "todo", "~": "wip", "x": "done"}


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
        box = re.match(r"^\s*-\s+\[( |~|x)\]\s*(.*)$", line)
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
        s["wip"] = sum(1 for i in s["items"] if i["state"] == "wip")
        s["total"] = len(s["items"])
    return sections


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


def read_state() -> dict:
    """Snapshot of manifest + flags; never raises on transient states."""
    harness: Path = STATE["harness"]
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
            card_path, _ = find_task_files(tid)
            card_cache[tid] = card_path.read_text(encoding="utf-8", errors="replace") \
                if card_path and card_path.exists() else ""
        t["checklist"] = checklist_progress(card_cache[tid])
        t["live"] = _live_status(STATE["harness"], tid)
    return {"manifest": manifest, "flags": flags, "comments_fp": comments_fp}


def find_task_files(task_id: str) -> tuple[Path | None, Path]:
    """Locate tasks/<id>_*.md and comments/<id>.md for a task id."""
    harness: Path = STATE["harness"]
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

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            body = (Path(__file__).parent / "index.html").read_bytes()
            self._send(200, body, "text/html; charset=utf-8")
        elif self.path == "/api/state":
            self._send(200, json.dumps(read_state(), ensure_ascii=False).encode("utf-8"), "application/json")
        elif self.path.startswith("/api/task/"):
            task_id = self.path.rsplit("/", 1)[1]
            if not re.fullmatch(r"T\d+", task_id):
                self._send(400, b'{"error":"bad task id"}', "application/json")
                return
            card_path, comments_path = find_task_files(task_id)
            task = next((t for t in read_state()["manifest"].get("tasks", []) if t.get("id") == task_id), {})
            card_md = card_path.read_text(encoding="utf-8", errors="replace") \
                if card_path and card_path.exists() else ""
            doc = {
                "task": task,
                "card_md": card_md,
                "comments_md": comments_path.read_text(encoding="utf-8", errors="replace") if comments_path.exists() else "",
                "ask_pending": (_run_dir() / f"{task_id}_ask.pending").exists(),
                "checklist_sections": parse_checklist_sections(card_md),
            }
            self._send(200, json.dumps(doc, ensure_ascii=False).encode("utf-8"), "application/json")
        elif self.path.startswith("/api/log/"):
            task_id = self.path.rsplit("/", 1)[1]
            if not re.fullmatch(r"T\d+", task_id):
                self._send(400, b'{"error":"bad task id"}', "application/json")
                return
            logs = sorted(_run_dir().glob(f"{task_id}_*_*.log")) if _run_dir().is_dir() else []
            body = {"log": "", "file": None}
            if logs:
                body = {"log": _readable_tail(logs[-1]),
                        "file": logs[-1].name,
                        "mtime": logs[-1].stat().st_mtime}
            self._send(200, json.dumps(body, ensure_ascii=False).encode("utf-8"),
                       "application/json")
        elif self.path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            last: str | None = None
            try:
                while True:
                    state = json.dumps(read_state(), ensure_ascii=False)
                    if state != last:
                        self.wfile.write(f"data: {state}\n\n".encode("utf-8"))
                        self.wfile.flush()
                        last = state
                    time.sleep(1)
            except OSError:
                pass  # клиент отключился
        else:
            self._send(404, b'{"error":"not found"}', "application/json")

    def do_POST(self) -> None:
        if self.path.startswith("/api/flag/"):
            name = self.path.rsplit("/", 1)[1]
            if not name.replace("_", "").isalnum():
                self._send(400, b'{"error":"bad flag name"}', "application/json")
                return
            flags_dir = STATE["harness"] / ".flags"
            flags_dir.mkdir(exist_ok=True)
            (flags_dir / name).touch()
            self._send(200, b'{"ok":true}', "application/json")
        elif self.path.startswith("/api/comment/"):
            task_id = self.path.rsplit("/", 1)[1]
            text = (self._json_body().get("text") or "").strip()
            if not re.fullmatch(r"T\d+", task_id) or not text:
                self._send(400, b'{"error":"need task id and text"}', "application/json")
                return
            _, comments_path = find_task_files(task_id)
            comments_path.parent.mkdir(exist_ok=True)
            ts = time.strftime("%Y-%m-%d %H:%M")
            with comments_path.open("a", encoding="utf-8") as fh:
                fh.write(f"- [{ts} | human] {text}\n")
            self._send(200, b'{"ok":true}', "application/json")
        elif self.path.startswith("/api/ask/"):
            task_id = self.path.rsplit("/", 1)[1]
            question = (self._json_body().get("text") or "").strip()
            if not re.fullmatch(r"T\d+", task_id) or not question:
                self._send(400, b'{"error":"need task id and text"}', "application/json")
                return
            task = next((t for t in read_state()["manifest"].get("tasks", [])
                         if t.get("id") == task_id), {})
            session_id = task.get("session_id")
            if not session_id:
                self._send(409, b'{"error":"task has no session yet"}', "application/json")
                return
            if (_run_dir() / f"{task_id}_ask.pending").exists():
                self._send(429, b'{"error":"question already running"}', "application/json")
                return
            threading.Thread(target=_ask_agent,
                             args=(task_id, session_id, question), daemon=True).start()
            self._send(200, b'{"ok":true,"pending":true}', "application/json")
        else:
            self._send(404, b'{"error":"not found"}', "application/json")

    def do_DELETE(self) -> None:
        if self.path.startswith("/api/flag/"):
            name = self.path.rsplit("/", 1)[1]
            try:
                (STATE["harness"] / ".flags" / name).unlink()
            except OSError:
                pass
            self._send(200, b'{"ok":true}', "application/json")
        else:
            self._send(404, b'{"error":"not found"}', "application/json")


def _ask_agent(task_id: str, session_id: str, question: str) -> None:
    """Вопрос агенту задачи: claude --resume <sid>; ответ — в журнал задачи."""
    harness: Path = STATE["harness"]
    run_dir = _run_dir()
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


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Harness Live Dashboard (stdlib only)")
    parser.add_argument("--harness", required=True, help="путь к каталогу FNR_N/harness")
    parser.add_argument("--port", type=int, default=4040)
    parser.add_argument("--claude-bin", default="claude",
                        help="бинарь claude для чата задачи (тесты: заглушка)")
    args = parser.parse_args()
    STATE["harness"] = Path(args.harness).resolve()
    STATE["claude_bin"] = args.claude_bin
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"AI Harness dashboard: http://127.0.0.1:{args.port}  ({STATE['harness']})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
