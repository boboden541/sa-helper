"""AI-Harness dev-утилита: единая точка команд для macOS и Windows (Git Bash).

Только stdlib: docker вызывается через subprocess списком аргументов,
пути — через pathlib. Запуск: python scripts/dev.py <команда> [аргументы].
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = ["docker", "compose"]


def run(cmd: list[str], **kw) -> int:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=ROOT, **kw).returncode


def compose(*args: str) -> int:
    return run([*COMPOSE, *args])


def need_env() -> None:
    env = ROOT / ".env"
    example = ROOT / ".env.example"
    if not env.exists() and example.exists():
        env.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        print("Создан .env из .env.example — задайте AI_HARNESS_TOKEN_KEY перед работой с провайдерами.")


def wait_postgres() -> None:
    """Ждём healthcheck postgres (compose --wait сам ждёт, это запасной путь)."""
    r = subprocess.run(
        [*COMPOSE, "exec", "-T", "postgres", "pg_isready", "-U", "harness", "-d", "ai_harness"],
        cwd=ROOT, capture_output=True,
    )
    if r.returncode != 0:
        compose("up", "-d", "--wait", "postgres")


def cmd_up(args) -> int:
    need_env()
    return compose("up", "-d", "--wait", "postgres")


def cmd_down(args) -> int:
    return compose("down")


def cmd_migrate(args) -> int:
    rc = cmd_up(args)
    if rc:
        return rc
    return run([sys.executable, "-m", "alembic", "upgrade", "head"])


def cmd_revision(args) -> int:
    msg = " ".join(args.message) if args.message else "auto"
    return run([sys.executable, "-m", "alembic", "revision", "--autogenerate", "-m", msg])


def cmd_downgrade(args) -> int:
    target = args.target or "-1"
    return run([sys.executable, "-m", "alembic", "downgrade", target])


def cmd_seed(args) -> int:
    return run([sys.executable, "-m", "db.seeds.seed_dev"])


def cmd_test(args) -> int:
    rest = args.rest or []
    return run([sys.executable, "-m", "pytest", *rest])


def cmd_run_api(args) -> int:
    return run([sys.executable, "-m", "uvicorn", "main:app", "--reload", "--port", str(args.port)],
               cwd=ROOT / "backend" / "src")


def cmd_run_daemon(args) -> int:
    return run([sys.executable, "-m", "daemon.main"])


def cmd_run_web(args) -> int:
    return run(["npm", "run", "dev"], cwd=ROOT / "frontend")


def cmd_check_path(args) -> int:
    """Проверка пути проекта: существует и доступен на запись (ФТ-ah-46)."""
    p = Path(args.path)
    ok = p.is_dir() and os.access(p, os.W_OK)
    print(f"{'OK' if ok else 'НЕДОСТУПЕН'}: {p}")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="AI-Harness dev-утилита")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("up", help="поднять postgres").set_defaults(func=cmd_up)
    sub.add_parser("down", help="остановить контейнеры").set_defaults(func=cmd_down)
    sub.add_parser("migrate", help="применить миграции").set_defaults(func=cmd_migrate)
    p = sub.add_parser("revision", help="новая миграция (autogenerate)")
    p.add_argument("message", nargs="*").set_defaults(func=cmd_revision)
    p = sub.add_parser("downgrade", help="откатить миграции")
    p.add_argument("target", nargs="?").set_defaults(func=cmd_downgrade)
    sub.add_parser("seed", help="наполнить БД справочниками и dev-данными").set_defaults(func=cmd_seed)
    p = sub.add_parser("test", help="pytest (аргументы после --)")
    p.add_argument("rest", nargs=argparse.REMAINDER).set_defaults(func=cmd_test)
    p = sub.add_parser("run-api", help="uvicorn backend")
    p.add_argument("--port", type=int, default=8000).set_defaults(func=cmd_run_api)
    sub.add_parser("run-daemon", help="запустить демон").set_defaults(func=cmd_run_daemon)
    sub.add_parser("run-web", help="vite frontend").set_defaults(func=cmd_run_web)
    p = sub.add_parser("check-path", help="проверить путь проекта")
    p.add_argument("path").set_defaults(func=cmd_check_path)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
