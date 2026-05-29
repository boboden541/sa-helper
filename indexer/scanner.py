"""File tree scanner — walks project directory and collects parseable files."""

from __future__ import annotations

import os
from pathlib import Path

IGNORED_DIRS = {
    "node_modules", "vendor", ".git", "dist", "build", "__pycache__",
    ".next", "target", ".idea", ".vscode", ".cache", ".tox", "venv",
    ".venv", "env", ".env", ".eggs", "eggs", "htmlcov", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "coverage", "out", "bin", "obj",
    ".gradle", ".mvn", ".dart_tool", "indexer", ".neo4j",
}

IGNORED_EXTENSIONS = {
    ".min.js", ".min.css", ".map", ".pyc", ".pyo", ".class",
    ".jar", ".war", ".dll", ".exe", ".so", ".dylib",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
    ".mp4", ".mp3", ".wav", ".avi", ".mov",
    ".zip", ".tar", ".gz", ".rar", ".7z",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".db", ".sqlite", ".sqlite3",
}

MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 MB

FILENAME_TO_LANG = {
    "crontab": "cron",
    "Cronfile": "cron",
    ".env": "config",
    ".env.local": "config",
    ".env.production": "config",
    ".env.development": "config",
}

EXTENSION_TO_LANG = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "javascript",
    ".tsx": "javascript",
    ".java": "java",
    ".php": "php",
    ".go": "go",
    ".sql": "sql_ddl",
    ".yml": "config",
    ".yaml": "config",
    ".ini": "config",
    ".conf": "config",
    ".env": "config",
    ".xml": "config",
    ".json": "config",
    ".toml": "config",
    ".cron": "cron",
}


def is_supported_file(rel_path: str) -> str | None:
    """Check if a relative file path is supported. Returns language or None."""
    filepath = Path(rel_path)
    ext = filepath.suffix.lower()
    filename = filepath.name

    if ext in IGNORED_EXTENSIONS:
        return None
    return EXTENSION_TO_LANG.get(ext) or FILENAME_TO_LANG.get(filename)


def scan(project_path: str) -> list[tuple[str, str]]:
    """Walk project tree and return list of (absolute_path, language)."""
    root = Path(project_path).resolve()
    results = []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d not in IGNORED_DIRS and not d.startswith(".")
        ]

        for filename in filenames:
            filepath = Path(dirpath) / filename
            ext = filepath.suffix.lower()

            if ext in IGNORED_EXTENSIONS:
                continue

            lang = EXTENSION_TO_LANG.get(ext) or FILENAME_TO_LANG.get(filename)
            if lang is None:
                continue

            try:
                if filepath.stat().st_size > MAX_FILE_SIZE:
                    continue
            except OSError:
                continue

            rel_path = str(filepath.relative_to(root))
            results.append((str(filepath), lang, rel_path))

    return results
