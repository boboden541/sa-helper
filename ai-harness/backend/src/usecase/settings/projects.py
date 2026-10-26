"""Проекты: создание/правка/архив/удаление (ФТ-ah-46, ФТ-ah-47)."""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from domain.model.validators import DomainError
from repository.models import DeadMnemonic, Project, Task

MNEMONIC_RE = re.compile(r"^[A-Z0-9]{2,10}$")


@dataclass
class ProjectInput:
    name: str
    mnemonic: str
    path: str
    base_branch: str = "main"
    description: str | None = None


def prepare_path(path: str) -> str:
    """Рабочая директория проекта — любая на диске (решение владельца 26.10.2026):
    указанную папку создаём, если её нет; существующие репозиторий/мультирепозиторий
    не трогаем; новой директории даём git-репозиторий с начальным коммитом, чтобы
    ветки задач и worktree агентов работали сразу."""
    import subprocess

    from infrastructure.paths import expand_host, host_to_container

    # в БД и на экране — путь КАК НА КОМПЬЮТЕРЕ; контейнерный — только для FS-операций
    user_path = Path(expand_host(path))
    p = Path(host_to_container(str(user_path)))
    if p.exists() and not p.is_dir():
        raise DomainError(f"Путь указывает на файл, а не на директорию: {p}",
                          tech="path is a file", field="path")
    if not p.exists():
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError as err:
            raise DomainError(f"Не удалось создать директорию {p}: {err}",
                              tech=str(err), field="path")
    if not os.access(p, os.W_OK):
        raise DomainError(f"Директория не для записи: {p}", tech="no write access",
                          field="path")

    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=p, capture_output=True, text=True)

    if git("rev-parse", "--git-dir").returncode != 0:
        init = git("init", "--initial-branch", "main")
        if init.returncode != 0:
            raise DomainError(f"git init не удался в {p}: {init.stderr.strip()}",
                              tech=init.stderr, field="path")
        head = git("rev-parse", "--verify", "HEAD")
        if head.returncode != 0:
            cfg = git("config", "user.email", "harness@local")
            cfg2 = git("config", "user.name", "AI Harness")
            first = git("commit", "--allow-empty", "-m",
                        "Начальный коммит: рабочая директория проекта AI-Harness")
            if first.returncode != 0:
                raise DomainError(f"Не удалось создать начальный коммит в {p}: "
                                  f"{first.stderr.strip()}", tech=first.stderr, field="path")
    return str(user_path)


async def create_project(session: AsyncSession, data: ProjectInput) -> Project:
    mnemonic = data.mnemonic.upper()
    if not MNEMONIC_RE.match(mnemonic):
        raise DomainError(
            "Мнемоника: 2–10 символов, ЗАГЛАВНЫЕ латиница и цифры",
            tech=f"mnemonic={mnemonic!r}", field="mnemonic")
    if (await session.execute(sa.select(sa.func.count()).select_from(DeadMnemonic)
                              .where(DeadMnemonic.mnemonic == mnemonic))).scalar_one():
        raise DomainError(
            f"Мнемоника {mnemonic} принадлежала удалённому проекту и не переиспользуется",
            field="mnemonic")
    if (await session.execute(sa.select(sa.func.count()).select_from(Project)
                              .where(Project.mnemonic == mnemonic))).scalar_one():
        raise DomainError(f"Мнемоника {mnemonic} уже занята", field="mnemonic")
    data.path = prepare_path(data.path)
    project = Project(name=data.name.strip()[:64], mnemonic=mnemonic, path=data.path,
                      base_branch=data.base_branch or "main", description=data.description)
    session.add(project)
    await session.commit()
    return project


async def update_project(session: AsyncSession, project_id: uuid.UUID,
                         fields: dict) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise DomainError("Проект не найден")
    if "mnemonic" in fields and fields["mnemonic"].upper() != project.mnemonic:
        raise DomainError("Мнемоника неизменна после создания", field="mnemonic")
    if "path" in fields and fields["path"] != project.path:
        project.path = prepare_path(fields["path"])
    if "name" in fields and fields["name"]:
        project.name = fields["name"].strip()[:64]
    if "description" in fields:
        project.description = fields["description"]
    if "baseBranch" in fields and fields["baseBranch"]:
        project.base_branch = fields["baseBranch"]
    await session.commit()
    return project


async def set_archived(session: AsyncSession, project_id: uuid.UUID,
                       archived: bool) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise DomainError("Проект не найден")
    project.is_archived = archived
    await session.commit()
    return project


async def delete_project(session: AsyncSession, project_id: uuid.UUID) -> None:
    """Жёсткое удаление — только без задач; мнемоника не переиспользуется (ФТ-ah-47)."""
    project = await session.get(Project, project_id)
    if project is None:
        raise DomainError("Проект не найден")
    tasks = (await session.execute(sa.select(sa.func.count()).select_from(Task)
                                   .where(Task.project_id == project_id))).scalar_one()
    if tasks:
        raise DomainError(
            f"Удаление невозможно: у проекта {tasks} задач — используйте архивирование")
    session.add(DeadMnemonic(mnemonic=project.mnemonic))
    await session.delete(project)
    await session.commit()
