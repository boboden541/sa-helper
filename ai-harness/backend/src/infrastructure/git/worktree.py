"""Git-контур: ветки задач, worktree, слияние перед done (СТ §4.3.2, ФТ-ah-37).

Кроссплатформенно: только pathlib + subprocess со списком аргументов;
worktree внутри пути проекта (тот же диск — требование git worktree).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path


class GitError(Exception):
    def __init__(self, message: str, stderr: str = "") -> None:
        super().__init__(message)
        self.stderr = stderr


async def _git(args: list[str], cwd: Path | None = None) -> str:
    proc = await asyncio.create_subprocess_exec(
        "git", *args, cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed", err.decode(errors="replace"))
    return out.decode(errors="replace").strip()


def worktree_path_for(project_path: str, task_code: str) -> Path:
    return Path(project_path) / ".harness" / "worktrees" / task_code


async def ensure_task_worktree(project_path: str, task_code: str,
                               base_branch: str = "main") -> Path:
    """Создаёт ветку task/<code> от базовой при первом входе в работу;
    повторный вход продолжает ту же ветку (ФТ-ah-37)."""
    root = Path(project_path)
    branch = f"task/{task_code}"
    wt = worktree_path_for(project_path, worktree_code(task_code))
    wt.parent.mkdir(parents=True, exist_ok=True)
    if wt.exists() and (wt / ".git").exists():
        return wt
    # кроссплатформенные настройки worktree
    await _git(["config", "core.longpaths", "true"], cwd=root)
    exists = await _git(["branch", "--list", branch], cwd=root)
    if not exists.strip():
        await _git(["branch", branch, base_branch], cwd=root)
    await _git(["worktree", "add", str(wt), branch], cwd=root)
    await _git(["config", "core.autocrlf", "false"], cwd=wt)
    return wt


def worktree_code(task_code: str) -> str:
    return task_code  # AH-12 безопасен как имя каталога на обеих ОС


async def commit_all(worktree: Path, message: str, author: str) -> str | None:
    """Коммитит все изменения в worktree; None — нечего коммитить."""
    await _git(["add", "-A"], cwd=worktree)
    status = await _git(["status", "--porcelain"], cwd=worktree)
    if not status.strip():
        return None
    await _git(["-c", f"user.name={author}", "-c", "user.email=harness@local",
                "commit", "-m", message], cwd=worktree)
    return await _git(["rev-parse", "HEAD"], cwd=worktree)


async def merge_task_branch(project_path: str, task_code: str,
                            base_branch: str = "main") -> None:
    """Слияние task/<code> в базовую перед done; конфликт → GitError (→ blocked)."""
    root = Path(project_path)
    branch = f"task/{task_code}"
    # слияние через временный checkout базовой ветки в основном репозитории
    current = await _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=root)
    if current != base_branch:
        # работа в основном репо не предполагается, но уважаем текущую ветку
        await _git(["checkout", base_branch], cwd=root)
    try:
        await _git(["merge", "--no-ff", "-m", f"Merge {branch}", branch], cwd=root)
    except GitError:
        await _git(["merge", "--abort"], cwd=root)
        raise
    finally:
        if current != base_branch:
            await _git(["checkout", current], cwd=root)


async def merge_has_conflict(project_path: str, task_code: str,
                             base_branch: str = "main") -> bool:
    try:
        await merge_task_branch(project_path, task_code, base_branch)
        return False
    except GitError:
        return True


async def remove_task_worktree(project_path: str, task_code: str) -> None:
    wt = worktree_path_for(project_path, worktree_code(task_code))
    root = Path(project_path)
    if wt.exists():
        await _git(["worktree", "remove", "--force", str(wt)], cwd=root)
    # ветку сохраняем: артефактный контракт — одна задача, одна ветка (ФТ-ah-37)
