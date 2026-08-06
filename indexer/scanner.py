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

# Single-suffix extensions (compared against Path.suffix)
IGNORED_EXTENSIONS = {
    ".map", ".pyc", ".pyo", ".class",
    ".jar", ".war", ".dll", ".exe", ".so", ".dylib",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
    ".mp4", ".mp3", ".wav", ".avi", ".mov",
    ".zip", ".tar", ".gz", ".rar", ".7z",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".db", ".sqlite", ".sqlite3",
}

# Composite suffixes — must be matched against the full file name (name.endswith),
# because Path.suffix only returns the final extension (".min.js" -> ".js").
IGNORED_FILENAME_SUFFIXES = (
    ".min.js", ".min.mjs", ".min.css",
    ".js.map", ".css.map", ".mjs.map",
    ".bundle.js", ".bundle.css", ".chunk.js",
    "-min.js", "-min.css",
    ".d.ts",
)

MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 MB

# Generated/minified code heuristic — language-agnostic, no project naming.
# Bundles pack everything onto very long lines; flag files whose mean line
# length exceeds the threshold (sampled from the file head for speed).
GENERATED_AVG_LINE_LEN = 400
GENERATED_SAMPLE_BYTES = 64 * 1024


def _is_ignored_filename(name: str) -> bool:
    """Check composite-suffix ignore list against the full file name."""
    lower = name.lower()
    return any(lower.endswith(suffix) for suffix in IGNORED_FILENAME_SUFFIXES)


def _looks_generated(filepath: Path) -> bool:
    """Heuristic for minified/generated code: very high average line length."""
    try:
        with open(filepath, "rb") as fh:
            sample = fh.read(GENERATED_SAMPLE_BYTES)
    except OSError:
        return False
    if not sample:
        return False
    line_count = sample.count(b"\n") + 1
    return (len(sample) / line_count) > GENERATED_AVG_LINE_LEN

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

    if _is_ignored_filename(filename):
        return None
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

            if _is_ignored_filename(filename):
                continue
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

            # Drop minified/generated bundles that slipped past the name filter.
            if lang == "javascript" and _looks_generated(filepath):
                continue

            rel_path = str(filepath.relative_to(root))
            results.append((str(filepath), lang, rel_path))

    return results


def detect_stack(project_path: str) -> dict[str, int]:
    """Detect programming language stack and file counts for a project."""
    files = scan(project_path)
    counts: dict[str, int] = {}
    for _, lang, _ in files:
        if lang not in ("config", "cron"):
            counts[lang] = counts.get(lang, 0) + 1
    return counts

