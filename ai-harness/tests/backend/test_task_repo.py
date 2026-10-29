"""repo_path задачи: целевой репозиторий в мультирепозитории проекта (29.10.2026)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from domain.model.validators import DomainError
from usecase.task.create_task import CreateTaskInput, _validate_repo_path, create_task
def _mkproject(session, path: Path, mnemonic: str):
    from repository.models import Project

    project = Project(mnemonic=mnemonic, name=mnemonic, path=str(path),
                      base_branch="main", next_number=1)
    session.add(project)
    return project


def _mkrepo(root: Path, name: str) -> Path:
    repo = root / name
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    return repo


async def test_validate_repo_path_requires_git(session, tmp_path: Path):
    """repo_path обязан быть git-репозиторием внутри папки проекта; выход за
    пределы папки и не-git подпапка отклоняются."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    _mkrepo(workspace, "tc-admin")
    (workspace / "not-a-repo").mkdir()

    project = _mkproject(session, workspace, "WSX")
    await session.flush()

    assert await _validate_repo_path(project, "tc-admin") == "tc-admin"
    assert await _validate_repo_path(project, None) is None
    with pytest.raises(DomainError, match="не git-репозиторий"):
        await _validate_repo_path(project, "not-a-repo")
    with pytest.raises(DomainError, match="внутри папки проекта"):
        await _validate_repo_path(project, "../outside")


async def test_create_task_with_repo(session, actor_id, tmp_path: Path):
    """Задача создаётся с repo_path; в БД сохраняется; невалидный — DomainError."""
    workspace = tmp_path / "ws2"
    workspace.mkdir()
    _mkrepo(workspace, "tc-admin")
    _mkproject(session, workspace, "WS2")
    await session.flush()

    from repository.models import User

    human = await session.get(User, actor_id)
    created = await create_task(session, human, CreateTaskInput(
        project_mnemonic="WS2", type_key="common_task", title="С репозиторием",
        priority="medium", author_tag="by_human", repo_path="tc-admin"))

    from sqlalchemy import text as stext

    row = (await session.execute(stext(
        "SELECT repo_path FROM task WHERE code = :c"), {"c": created.code})).scalar()
    assert row == "tc-admin"

    with pytest.raises(DomainError, match="не git-репозиторий"):
        await create_task(session, human, CreateTaskInput(
            project_mnemonic="WS2", type_key="common_task", title="Плохой репо",
            priority="medium", author_tag="by_human", repo_path="нет-такого"))
