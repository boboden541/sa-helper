"""Мост путей «компьютер ↔ контейнер» (решение владельца 26.10.2026).

Пользователь указывает путь КАК НА КОМПЬЮТЕРЕ (/Users/raliev/Проекты/foo или ~/foo).
Контейнеры видят домашнюю директорию в /app/host-home, поэтому все файловые
операции выполняются по преобразованному пути; в БД хранится путь-как-на-хосте.
Вне контейнера (тесты/запуск на хосте) переменные не заданы — тождественное
отображение.
"""

from __future__ import annotations

import os
from pathlib import Path


def _roots() -> tuple[Path, Path] | None:
    host = os.getenv("HARNESS_HOST_HOME")
    cont = os.getenv("HARNESS_CONTAINER_HOME")
    if host and cont:
        return Path(host), Path(cont)
    return None


def expand_host(path: str) -> Path:
    """~ раскрывается в домашнюю директорию КОМПЬЮТЕРА, а не контейнера."""
    p = path.strip()
    host = os.getenv("HARNESS_HOST_HOME")
    if p == "~" or p.startswith("~/"):
        if host:
            p = host + p[1:]
        p = os.path.expanduser(p)
    return Path(p)


def host_to_container(path: str) -> str:
    roots = _roots()
    if roots is None:
        return path
    host, cont = roots
    try:
        p = expand_host(path).resolve()
        hp = Path(host).resolve()
        if p == hp or hp in p.parents:
            return str(cont / p.relative_to(hp))
    except (ValueError, OSError):
        pass
    return path
