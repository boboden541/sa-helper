"""Кроссплатформенный смоук (macOS / Windows Git Bash): весь стек за один прогон.

Только stdlib + subprocess (списки аргументов, pathlib — без bashism):
 1. docker compose up postgres (ждать healthcheck)
 2. alembic upgrade head на dev-БД
 3. seed (идемпотентно)
 4. поднять API, проверить /api/v1/tasks, создание, Eve, очередь
 5. сборку фронтенда не трогаем (npm run build — отдельно)
Запуск: python scripts/smoke.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


def run(cmd: list[str], **kw) -> int:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=ROOT, **kw).returncode


def wait_http(url: str, timeout: float = 30) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def main() -> int:
    if run([PY, "scripts/dev.py", "up"]) != 0:
        return 1
    if run([PY, "-m", "alembic", "upgrade", "head"]) != 0:
        return 2
    run([PY, "-m", "db.seeds.seed_dev"])

    env = {**os.environ}
    api = subprocess.Popen([PY, "-m", "uvicorn", "main:app", "--port", "8124"],
                           cwd=ROOT / "backend" / "src", env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not wait_http("http://localhost:8124/api/v1/tasks"):
            print("FAIL: API не поднялся")
            return 3
        for path in ("/api/v1/notifications", "/api/v1/queue",
                     "/api/v1/alias-columns", "/api/v1/projects",
                     "/api/v1/matrix/common_task", "/api/v1/settings-journal"):
            with urllib.request.urlopen(f"http://localhost:8124{path}") as r:
                assert r.status == 200, path
        print("SMOKE OK: API отвечает на всех контурах")
        return 0
    finally:
        api.terminate()


if __name__ == "__main__":
    sys.exit(main())
