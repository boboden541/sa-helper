"""Workspace scanner: discovers git repos and drafts a workspaces.yaml.

/impl-bootstrap needs a declarative registry of systems (repos, stacks,
build/test commands). Filling it by hand is tedious and error-prone; this
tool walks the workspace, detects stacks by marker files and prints a YAML
draft to stdout. The human reviews/corrects the draft, then the agent saves
it as workspaces.yaml at the workspace root (v2 §4.1.1: the file is never
written without explicit confirmation).

Deterministic stdlib-only detection; YAML is emitted manually (no PyYAML).

Usage:
    python3 harness/workspace_scan.py [workspace_dir]     # default: cwd
"""

from __future__ import annotations

import json
import os
import re
import sys

MAX_DEPTH = 2  # v2 §4.1.1: find . -maxdepth 2 -name .git

JAVA_MARKERS = ("pom.xml", "build.gradle", "build.gradle.kts")
PYTHON_MARKERS = ("pyproject.toml", "requirements.txt", "setup.py")
NODE_MARKERS = ("package.json",)
PHP_MARKERS = ("composer.json",)
DOTNET_MARKERS = (".sln",)

TEST_DIR_NAMES = ("tests", "test", "src/test", "src-test", "__tests__")


def find_repos(workspace: str) -> list[str]:
    """Return directories containing .git (up to MAX_DEPTH)."""
    repos: list[str] = []
    for root, dirs, files in os.walk(workspace):
        depth = os.path.relpath(root, workspace).count(os.sep)
        if depth >= MAX_DEPTH:
            dirs[:] = []
            continue
        # Сначала проверка (как есть), потом фильтрация скрытых каталогов
        if ".git" in dirs or ".git" in files:
            repos.append(root)
            dirs[:] = []  # внутрь репозитория не проваливаемся
            continue
        dirs[:] = [d for d in dirs if not d.startswith(".")]
    return sorted(repos)


def detect_stack(repo: str) -> dict:
    """Detect stack, data-only status, docker and test presence by markers."""
    names = set(os.listdir(repo))
    stack: str | None = None
    preset: str | None = None
    data_only = False

    if any(m in names for m in JAVA_MARKERS):
        stack, preset = "java-maven", "java"
    elif any(m in names for m in PYTHON_MARKERS):
        stack, preset = "python", "python"
    elif any(m in names for m in NODE_MARKERS):
        stack, preset = "node", "typescript"
    elif any(m in names for m in PHP_MARKERS):
        stack, preset = "php", "php"
    elif _has_deep(repo, ".sqlproj"):
        # SSDT-проект базы данных (DDL, без исполняемого кода)
        stack, preset, data_only = "mssql-ssdt", "mssql-ssdt", True
    elif any(n.endswith(".csproj") or n.endswith(".vbproj") for n in names) or _has_deep(repo, ".csproj"):
        stack, preset = "dotnet", "csharp"
    elif any(n.endswith(".sln") for n in names):
        # .sln без csproj/sqlproj + каталоги DDL (dbo/Security) → тоже SSDT
        if {"dbo", "Security", "Storage"} & names:
            stack, preset, data_only = "mssql-ssdt", "mssql-ssdt", True
        else:
            stack, preset = "dotnet-sln", None

    has_tests = any(_has_dir(repo, t) for t in TEST_DIR_NAMES) or "pytest.ini" in names or "conftest.py" in names
    docker = [f for f in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml", "dc.sh") if f in names]
    guidelines = next((f for f in ("CLAUDE.md", "AGENTS.md", "CONTRIBUTING.md") if f in names), None)

    return {
        "stack": stack or "unknown",
        "preset": preset,
        "data_only": data_only,
        "tests": has_tests,
        "docker": docker,
        "guidelines": guidelines,
        "java_release": _java_release(repo) if stack == "java-maven" else None,
        "python_hint": _python_hint(repo) if stack == "python" else None,
    }


def _has_dir(repo: str, rel: str) -> bool:
    return os.path.isdir(os.path.join(repo, *rel.split("/")))


def _has_deep(repo: str, suffix: str, depth: int = 3) -> bool:
    for root, dirs, _files in os.walk(repo):
        if os.path.relpath(root, repo).count(os.sep) >= depth:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        if any(n.endswith(suffix) for n in _files):
            return True
    return False


def _java_release(repo: str) -> str | None:
    """Read java.release / maven.compiler.release property from pom.xml."""
    pom = os.path.join(repo, "pom.xml")
    if not os.path.isfile(pom):
        return None
    try:
        text = open(pom, encoding="utf-8", errors="replace").read(200_000)
    except OSError:
        return None
    m = re.search(r"<(java\.release|maven\.compiler\.release|java\.version|maven\.compiler\.source)>([^<]+)<", text)
    return m.group(2) if m else None


def _python_hint(repo: str) -> str | None:
    """Best-effort python version from Dockerfile (FROM python:X...)."""
    for candidate in ("Dockerfile", "Dockerfile.core", "deploy/local/Dockerfile.core"):
        path = os.path.join(repo, *candidate.split("/"))
        if os.path.isfile(path):
            try:
                head = open(path, encoding="utf-8", errors="replace").read(4000)
            except OSError:
                continue
            m = re.search(r"FROM\s+python:(\d+(?:\.\d+)?)", head)
            if m:
                return m.group(1)
    return None


def _yaml_str(value: str) -> str:
    """Quote a string for YAML output."""
    if value == "-" or re.fullmatch(r"[A-Za-z0-9_./-]+", value):
        return value
    return "'" + value.replace("'", "''") + "'"


def draft_yaml(workspace: str, repos: list[str]) -> str:
    """Render the human-reviewable workspaces.yaml draft."""
    lines = [
        'version: "1.0"',
        f"workspace: {_yaml_str(os.path.abspath(workspace))}",
        "defaults:",
        "  timeout_s: 600",
        "  # Перед сохранением: проверь команды ниже (образы docker, скоуп тестов),",
        "  # заполни '-' там, где команда не применима, и добавь prerequisites",
        "  # для систем с внешними зависимостями (VPN, приватные репозитории, settings.xml).",
        "systems:",
    ]
    for repo in repos:
        name = os.path.basename(repo.rstrip(os.sep))
        info = detect_stack(repo)
        rel = os.path.relpath(repo, workspace)
        lines.append(f"  {name}:")
        lines.append(f"    path: {_yaml_str(rel)}")
        lines.append(f"    stack: {_yaml_str(info['stack'])}")
        if info["preset"]:
            lines.append(f"    preset: {_yaml_str(info['preset'])}")
        if info["data_only"]:
            lines.append("    data_only: true")
        if info["java_release"]:
            lines.append(f"    java_release: {_yaml_str(info['java_release'])}")
        if info["python_hint"]:
            lines.append(f"    python_hint: {_yaml_str(info['python_hint'])}")
        if info["docker"]:
            lines.append(f"    docker: [{', '.join(_yaml_str(d) for d in info['docker'])}]")
        # Сборка/тесты — черновик; человек подтверждает (v2 §4.1.1)
        if info["data_only"]:
            lines.append("    build_cmd: '-'  # data-only: сборка не применима")
            lines.append("    test_cmd: '-'   # data-only: тесты не применимы")
        elif info["stack"] == "java-maven":
            img = f"maven:3.8-openjdk-{info['java_release'] or '11'}"
            lines.append(f"    build_cmd: \"docker run --rm -v $PWD:/ws -w /ws -v $HOME/.m2:/root/.m2 {img} mvn -q compile\"")
            lines.append("    test_cmd: \"TODO: mvn test (образ и скоуп уточни; см. notes)\"")
        elif info["stack"] == "python":
            tag = f"python:{info['python_hint'] or '3.12'}-slim"
            lines.append("    build_cmd: '-'")
            lines.append(f"    test_cmd: \"TODO: docker run -v $PWD:/app -w /app {tag} pytest (образ и скоуп уточни)\"")
        else:
            lines.append('    build_cmd: "TODO"')
            lines.append('    test_cmd: "TODO"')
        lines.append(f"    tests: {'true' if info['tests'] else 'false'}  # {'—' if info['tests'] else 'no test suite: характеризационная задача первой (v2 §7 п. 3)'}")
        if info["guidelines"]:
            lines.append(f"    guidelines: {_yaml_str(info['guidelines'])}")
        lines.append("    notes: TODO  # prerequisites: VPN/приватные репо/сервисы, от которых зависят сборка и тесты")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    workspace = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    if not os.path.isdir(workspace):
        print(json.dumps({"error": {"type": "UsageError", "message": f"нет каталога: {workspace}"}}, ensure_ascii=False))
        return 2
    repos = find_repos(workspace)
    if "--json" in sys.argv:
        print(json.dumps({"workspace": os.path.abspath(workspace), "repos": [os.path.relpath(r, workspace) for r in repos]}, ensure_ascii=False, indent=2))
    else:
        print(draft_yaml(workspace, repos))
    print(f"# найдено репозиториев: {len(repos)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
