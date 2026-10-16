"""CLI-клиент API витрины для Steward (диспетчер конвейера, порция H1).

Один узкий вход вместо curl: allowlist-правило для headless-сессии —
`Bash(python3 harness/steward_api.py:*)` — покрывает все действия диспетчера
и ничего больше (curl в интернет запрещён по умолчанию).

Использование:
    python3 harness/steward_api.py stories
    python3 harness/steward_api.py state FNR_8
    python3 harness/steward_api.py task FNR_8 T3
    python3 harness/steward_api.py timeline FNR_8 T3
    python3 harness/steward_api.py log FNR_8 T3
    python3 harness/steward_api.py create-story '{"title": "...", "source": "..."}'
    python3 harness/steward_api.py create-task FNR_8 '{"title": "...", ...}'
    python3 harness/steward_api.py flag FNR_8 TASK_T3_RETRY
    python3 harness/steward_api.py comment FNR_8 T3 "текст"

Базовый URL: env HARNESS_API, по умолчанию http://127.0.0.1:4040.
Только stdlib; stdout — ответ сервера (JSON) или ошибка с кодом.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("HARNESS_API", "http://127.0.0.1:4040").rstrip("/")


def call(method: str, path: str, body: dict | None = None) -> tuple[int, str]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, method=method, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return res.status, res.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


USAGE = __doc__ or ""


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(USAGE)
        return 2
    cmd, rest = args[0], args[1:]

    if cmd == "stories":
        code, body = call("GET", "/api/stories")
    elif cmd == "state" and rest:
        code, body = call("GET", f"/api/state?fnr={rest[0]}")
    elif cmd == "task" and len(rest) >= 2:
        code, body = call("GET", f"/api/task/{rest[1]}?fnr={rest[0]}")
    elif cmd == "timeline" and len(rest) >= 2:
        code, body = call("GET", f"/api/timeline/{rest[1]}?fnr={rest[0]}")
    elif cmd == "log" and len(rest) >= 2:
        code, body = call("GET", f"/api/log/{rest[1]}?fnr={rest[0]}")
    elif cmd == "create-story" and rest:
        code, body = call("POST", "/api/story", json.loads(rest[0]))
    elif cmd == "create-task" and len(rest) >= 2:
        code, body = call("POST", f"/api/story/{rest[0]}/task", json.loads(rest[1]))
    elif cmd == "flag" and len(rest) >= 2:
        code, body = call("POST", f"/api/flag/{rest[1]}?fnr={rest[0]}")
    elif cmd == "comment" and len(rest) >= 3:
        code, body = call("POST", f"/api/comment/{rest[1]}?fnr={rest[0]}",
                          {"text": " ".join(rest[2:])})
    else:
        print(USAGE)
        return 2

    print(body if body else f"HTTP {code}")
    return 0 if code < 400 else 1


if __name__ == "__main__":
    sys.exit(main())
