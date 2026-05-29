"""Git utilities for incremental indexing — diff detection and commit tracking."""

from __future__ import annotations

import subprocess
from pathlib import Path


def get_head_commit(project_path: str) -> str | None:
    """Return current HEAD commit SHA, or None if not a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_path,
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def get_changed_files(
    project_path: str,
    since_commit: str,
) -> tuple[list[str], list[str]]:
    """
    Return (changed_paths, deleted_paths) — relative to project root.

    Compares since_commit..HEAD using git diff.
    """
    # All changed files (modified + added + renamed)
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{since_commit}..HEAD"],
        cwd=project_path,
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        return [], []

    all_changed = [p for p in result.stdout.strip().split("\n") if p]

    # Deleted files only
    result_del = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=D", f"{since_commit}..HEAD"],
        cwd=project_path,
        capture_output=True, text=True, timeout=30,
    )
    deleted = [p for p in result_del.stdout.strip().split("\n") if p] if result_del.returncode == 0 else []

    changed = [p for p in all_changed if p not in deleted]

    return changed, deleted


def is_git_repo(project_path: str) -> bool:
    """Check if directory is inside a git repository."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=project_path,
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0 and result.stdout.strip() == "true"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
