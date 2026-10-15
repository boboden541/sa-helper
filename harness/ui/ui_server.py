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
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

STATE: dict = {"harness": None}


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
            doc = {
                "task": task,
                "card_md": card_path.read_text(encoding="utf-8", errors="replace") if card_path and card_path.exists() else "",
                "comments_md": comments_path.read_text(encoding="utf-8", errors="replace") if comments_path.exists() else "",
            }
            self._send(200, json.dumps(doc, ensure_ascii=False).encode("utf-8"), "application/json")
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


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Harness Live Dashboard (stdlib only)")
    parser.add_argument("--harness", required=True, help="путь к каталогу FNR_N/harness")
    parser.add_argument("--port", type=int, default=4040)
    args = parser.parse_args()
    STATE["harness"] = Path(args.harness).resolve()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"AI Harness dashboard: http://127.0.0.1:{args.port}  ({STATE['harness']})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
