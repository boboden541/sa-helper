"""AC-4.3.2.1–3: ветки задач, worktree, слияние перед done."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from infrastructure.git.worktree import (
    GitError,
    ensure_task_worktree,
    merge_task_branch,
    worktree_path_for,
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    def git(*args):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "init", "-b", "main", str(root)], check=True, capture_output=True)
    (root / "README.md").write_text("demo\n", encoding="utf-8")
    git("add", ".")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "init")
    return root


async def test_branch_created_once_and_reused(repo):
    """AC-4.3.2.1: первый вход создаёт ветку, повторный не дублирует."""
    wt = await ensure_task_worktree(str(repo), "AH-7", "main")
    assert (wt / ".git").exists()
    assert worktree_path_for(str(repo), "AH-7") == wt
    # файл агента в worktree живёт на ветке задачи
    (wt / "feature.txt").write_text("x\n", encoding="utf-8")
    # повторный вход возвращает тот же worktree, изменений ветки нет
    wt2 = await ensure_task_worktree(str(repo), "AH-7", "main")
    assert wt2 == wt


async def test_merge_before_done(repo):
    wt = await ensure_task_worktree(str(repo), "AH-8", "main")
    (wt / "feature.txt").write_text("изменение\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=wt, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-m", "work"], cwd=wt, check=True, capture_output=True)
    await merge_task_branch(str(repo), "AH-8", "main")
    readme = (repo / "README.md").read_text(encoding="utf-8")
    assert (repo / "feature.txt").exists()  # слияние попало в базовую


async def test_merge_conflict_raises(repo):
    """AC-4.3.2.2: конфликт → GitError (демон переводит в blocked)."""
    wt = await ensure_task_worktree(str(repo), "AH-9", "main")
    (wt / "README.md").write_text("task version\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=wt, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-m", "task edit"], cwd=wt, check=True, capture_output=True)
    # базовая ушла вперёд с конфликтом
    subprocess.run(["git", "checkout", "main"], cwd=repo, check=True, capture_output=True)
    (repo / "README.md").write_text("base version\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-m", "base edit"], cwd=repo, check=True, capture_output=True)
    with pytest.raises(GitError):
        await merge_task_branch(str(repo), "AH-9", "main")


def test_task_repo_root_formula():
    """Единая формула корня целевого репозитория (анализ 30.10.2026): cwd
    прогона без worktree, worktree и слияние считали корень по-разному —
    cwd прогона терял repo_path (мультирепозиторий 29.10.2026)."""
    from infrastructure.paths import task_repo_root

    assert task_repo_root("/ws/proj", None) == "/ws/proj"
    assert task_repo_root("/ws/proj", "tc-admin") == "/ws/proj/tc-admin"
    assert task_repo_root("/ws/proj/", "a/b") == "/ws/proj/a/b"
    assert task_repo_root("", "x") == "/x"


async def test_merge_refuses_dirty_checkout(repo):
    """Слияние не трогает грязную рабочую копию человека (анализ 30.10.2026):
    раньше checkout базовой в грязном репо давал ложный «конфликт слияния»
    и сжигал попытки без вины агента."""
    from infrastructure.git.worktree import merge_task_branch

    subprocess.run(["git", "checkout", "-b", "task/AH-10", "main"],
                   cwd=repo, check=True, capture_output=True)
    # грязь = изменение отслеживаемого файла; untracked (.harness и пр.) не считаем
    (repo / "README.md").write_text("human edits\n", encoding="utf-8")
    with pytest.raises(GitError, match="не чиста"):
        await merge_task_branch(str(repo), "AH-10", "main")


async def test_merge_ignores_untracked_files(repo):
    """Untracked-файлы в живой копии (например .harness/worktrees) слиянию
    не мешают — проверка чистоты смотрит только отслеживаемые файлы."""
    (repo / "notes.txt").write_text("untracked\n", encoding="utf-8")
    wt = await ensure_task_worktree(str(repo), "AH-11", "main")
    (wt / "feature.txt").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=wt, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-m", "work"], cwd=wt, check=True, capture_output=True)
    await merge_task_branch(str(repo), "AH-11", "main")
    assert (repo / "feature.txt").exists()
