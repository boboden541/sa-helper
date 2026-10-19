
"""Harness test/build runner: executes a command in a repo and returns structured JSON.

The harness slash-commands (/impl-*) need machine-readable build/test results:
counts, per-test failures with file/line/error type — not raw log walls.
This tool runs the command, parses pytest stdout (or a JUnit XML report),
and prints a single JSON document to stdout. Raw command output goes to
stderr (or a --log file), so the model reads the digest, never the wall.

Usage:
    python3 harness/runner.py --cwd <repo> --mode test \
        [--cmd "<override command>"] [--junit <path>] [--timeout 600] [--log <path>]

Exit code mirrors the underlying command (2 = runner's own error, JSON
describes it). Cross-platform: macOS/Linux and Windows Git Bash; stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

# Windows process-group handling (no-op constants on POSIX)
IS_WINDOWS = sys.platform == "win32"
if IS_WINDOWS:
    CREATE_NEW_PROCESS_GROUP = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
else:
    CREATE_NEW_PROCESS_GROUP = 0


def run_cmd(cwd: str, cmd: str, timeout: int, log_path: str | None = None) -> dict:
    """Run ``cmd`` in ``cwd``, capture output, kill the whole tree on timeout.

    Returns a dict with exit_code, duration, raw output and error info;
    parsing into summary/failures is the caller's job.
    """
    started = time.monotonic()
    kwargs: dict = {
        "cwd": cwd,
        "shell": True,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    # Own process group/tree so a timeout kills children too (maven daemons,
    # pytest plugins that spawn servers).
    if IS_WINDOWS:
        kwargs["creationflags"] = CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True

    timed_out = False
    error: dict | None = None
    exit_code: int | None = None
    output = ""
    try:
        proc = subprocess.Popen(cmd, **kwargs)
        try:
            output, _ = proc.communicate(timeout=timeout)
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_tree(proc)
            output, _ = proc.communicate()
            exit_code = proc.returncode if proc.returncode is not None else -1
            error = {
                "type": "TimeoutError",
                "message": f"Команда превысила лимит {timeout}s и была остановлена",
            }
    except (OSError, ValueError) as exc:
        # spawn failure (missing shell, bad cwd, command not found on win32)
        exit_code = 2
        error = {"type": type(exc).__name__, "message": str(exc)}

    duration = round(time.monotonic() - started, 2)
    if log_path:
        try:
            with open(log_path, "w", encoding="utf-8") as fh:
                fh.write(output)
        except OSError as exc:  # log is a convenience, never fatal
            print(f"runner: не удалось записать лог {log_path}: {exc}", file=sys.stderr)
    else:
        sys.stderr.write(output)

    return {
        "cmd": cmd,
        "exit_code": exit_code,
        "duration_s": duration,
        "timed_out": timed_out,
        "error": error,
        "raw_output": output,
    }


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill the process and all its children, portably."""
    if IS_WINDOWS:
        # taskkill /T walks the child tree; best-effort, ignore absence
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            check=False,
        )
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)  # start_new_session делает pid == pgid
        except (ProcessLookupError, PermissionError, AttributeError):
            proc.kill()


def parse_pytest_output(text: str) -> tuple[dict, list[dict]]:
    """Parse pytest stdout into (summary, failures).

    Handles the short summary tail (``5 failed, 10 passed, ... in 3.4s``),
    ``FAILED path::test - Type: message`` lines (requires -rf) and the
    FAILURES section (``_ test _`` headers with ``E   Type: message``).
    """
    summary = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    # Финальная строка counts: "==== 3 failed, 10 passed in 1.2s ====" или "2 failed in 0.06s"
    for m in re.finditer(r"^\s*(.*?)\s+in\s+[\d\.]+s\s*$", text, re.MULTILINE):
        counts = re.findall(r"(\d+)\s+(failed|passed|error|errors|skipped|xfailed|xpassed)", m.group(1))
        if not counts:
            continue
        for num, kind in counts:
            key = "errors" if kind in ("error", "errors") else kind
            if key in summary:
                summary[key] = int(num)  # последняя строка сводки — итоговая
    total = sum(summary.values())

    failures: list[dict] = []
    by_nodeid: dict[str, dict] = {}

    # Секция FAILURES — richest data: полный E-месседж и файл:строка
    parts = re.split(r"_{5,}\s+(.+?)\s+_{5,}", text)
    for name, chunk in zip(parts[1::2], parts[2::2]):
        chunk_name = name.strip()
        loc = re.search(r"([\w./\\-]+\.py):(\d+):", chunk)
        err = re.search(r"^E\s+(?:[\w.]+\s*:\s*)?([\w.]+(?:Error|Exception|Interrupted))\s*:\s*(.*)$", chunk, re.MULTILINE)
        if not (err or loc):
            continue
        nodeid = _match_nodeid(chunk_name, text)
        err_type, message = _split_error(err.group(1) + ": " + err.group(2) if err else "")
        by_nodeid[nodeid or chunk_name] = {
            "test": nodeid or chunk_name,
            "file": loc.group(1) if loc else None,
            "line": int(loc.group(2)) if loc else None,
            "error_type": err_type or "AssertionError",
            "message": message or "см. сырой лог (stderr/--log)",
        }

    # Короткая сводка (FAILED nodeid - Type: msg) — дополнение: покрывает то,
    # чего нет в FAILURES-секции (например, при --tb=no), и сообщает ERROR-узлы.
    for m in re.finditer(r"^(FAILED|ERROR)\s+(\S+?)(?:\s+-\s+(.*))?$", text, re.MULTILINE):
        kind, nodeid, rest = m.group(1), m.group(2), m.group(3) or ""
        if nodeid in by_nodeid:
            continue
        err_type, message = _split_error(rest)
        by_nodeid[nodeid] = {
            "test": nodeid,
            "file": _file_of_nodeid(nodeid),
            "line": None,
            "error_type": err_type if kind == "FAILED" else "ERROR",
            "message": message,
        }

    failures = list(by_nodeid.values())
    return {**summary, "total": total}, failures


def _split_error(rest: str) -> tuple[str, str]:
    """Split 'AssertionError: boom' into ('AssertionError', 'boom')."""
    m = re.match(r"\s*([\w.]+(?:Error|Exception|Interrupted|Failure))\s*:?\s*(.*)", rest, re.DOTALL)
    if m:
        return m.group(1), m.group(2).strip()
    return ("AssertionError", rest.strip()) if rest.strip() else ("Unknown", "")


def _file_of_nodeid(nodeid: str) -> str | None:
    return nodeid.split("::", 1)[0] if "::" in nodeid else None


def _match_nodeid(chunk_name: str, text: str) -> str | None:
    """Best-effort: find the FAILED nodeid whose last component matches the
    FAILURES-section header (pytest truncates long names in headers)."""
    short = chunk_name.split(" ")[0]
    for m in re.finditer(r"^FAILED\s+(\S+)", text, re.MULTILINE):
        if m.group(1).split("::")[-1].split("[")[0] == short.split("::")[-1].split("[")[0]:
            return m.group(1)
    return None


def parse_junit_xml(path: str) -> tuple[dict, list[dict]]:
    """Parse JUnit XML report(s) (pytest/surefire/xUnit) into (summary, failures).

    ``path`` may be a glob (e.g. ``target/surefire-reports/TEST-*.xml``);
    results of all matching files are merged.
    """
    import glob as _glob

    files = sorted(_glob.glob(path)) or [path]  # glob не совпал — пусть ET ругнётся внятно
    summary = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    failures: list[dict] = []
    for path in files:
        s, f = _parse_junit_file(path)
        for k in ("passed", "failed", "errors", "skipped"):
            summary[k] += s[k]
        failures.extend(f)
    summary["total"] = sum(summary[k] for k in ("passed", "failed", "errors", "skipped"))
    return summary, failures


def _parse_junit_file(path: str) -> tuple[dict, list[dict]]:
    tree = ET.parse(path)
    root = tree.getroot()
    suites = [root] if root.tag == "testsuite" else root.findall(".//testsuite")
    summary = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    failures: list[dict] = []
    for suite in suites:
        n_tests = int(suite.get("tests", 0))
        n_fail = int(suite.get("failures", 0))
        n_err = int(suite.get("errors", 0))
        n_skip = int(suite.get("skipped", 0)) + int(suite.get("disabled", 0))
        summary["passed"] += n_tests - n_fail - n_err - n_skip
        summary["failed"] += n_fail
        summary["errors"] += n_err
        summary["skipped"] += n_skip
        for case in suite.iter("testcase"):
            node = case.find("failure") if case.find("failure") is not None else case.find("error")
            if node is None:
                continue
            message = (node.get("message") or "").strip()
            err_type = node.get("type") or ""
            if not err_type:
                head = message.split("\n")[0]
                m = re.match(r"\s*([\w.]+(?:Error|Exception|Failure))\s*:?", head)
                err_type = m.group(1) if m else ("ERROR" if node.tag == "error" else "AssertionError")
            cls = case.get("classname") or ""
            name = case.get("name") or ""
            failures.append(
                {
                    "test": f"{cls}.{name}" if cls else name,
                    "file": case.get("file"),
                    "line": int(case.get("line")) if (case.get("line") or "").isdigit() else None,
                    "error_type": err_type,
                    "message": message.split("\n")[0],
                }
            )
    return summary, failures


def parse_coverage_xml(path: str, changed: list[str]) -> dict:
    """Parse coverage.py or jacoco XML → overall line-rate + per-file for changed files.

    Возвращает {"overall_line_rate": float, "files": {path: line_rate}}; файл сопоставляется
    changed-списку по подстроке (пути в отчётах бывают относительными).
    """
    root = ET.parse(path).getroot()
    files: dict[str, float] = {}

    if root.tag == "coverage":  # coverage.py: <coverage line-rate=".."><class filename=".." line-rate="..">
        try:
            overall = float(root.get("line-rate", 0))
        except ValueError:
            overall = 0.0
        for cls in root.iter("class"):
            fn = cls.get("filename")
            if fn:
                try:
                    files[fn] = float(cls.get("line-rate", 0))
                except ValueError:
                    pass
    else:  # jacoco: <report><package name="a/b"><sourcefile name="X.py"><counter type="LINE" .../>
        counters = root.findall(".//counter")
        top = counters[-1] if counters else None
        overall = 0.0
        if top is not None and top.get("type") == "LINE":
            mi, ci = int(top.get("missed", 0)), int(top.get("covered", 0))
            overall = ci / (mi + ci) if (mi + ci) else 0.0
        for sf in root.iter("sourcefile"):
            name = sf.get("name")
            if not name:
                continue
            line_counters = [c for c in sf.findall("counter") if c.get("type") == "LINE"]
            if not line_counters:
                continue
            mi, ci = int(line_counters[0].get("missed", 0)), int(line_counters[0].get("covered", 0))
            files[name] = ci / (mi + ci) if (mi + ci) else 0.0

    matched = {fn: rate for fn, rate in files.items() if any(c in fn or fn in c for c in changed)} if changed else files
    return {"overall_line_rate": round(overall, 3), "files": matched}


def main() -> int:
    parser = argparse.ArgumentParser(description="Harness runner: run + parse build/test command")
    parser.add_argument("--cwd", required=True, help="рабочая директория команды (репозиторий)")
    parser.add_argument("--mode", choices=["build", "test", "lint"], default="test")
    parser.add_argument("--cmd", help="переопределить команду (иначе берётся из workspaces.yaml вызывающей стороной)")
    parser.add_argument("--junit", help="путь/glob к JUnit XML (pytest/surefire) — парсить его, а не stdout")
    parser.add_argument("--coverage", help="coverage XML (coverage.py или jacoco) — добавить сводку покрытия")
    parser.add_argument("--changed", help="изменённые файлы через запятую (для фильтрации покрытия)")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--log", help="куда записать сырой вывод (иначе дублируется в stderr)")
    args = parser.parse_args()

    if not args.cmd:
        print(
            json.dumps({"error": {"type": "UsageError", "message": "--cmd обязателен"}}, ensure_ascii=False),
            file=sys.stdout,
        )
        return 2

    result = run_cmd(args.cwd, args.cmd, args.timeout, args.log)
    exit_code = result["exit_code"] if result["exit_code"] is not None else 1

    summary, failures = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0, "total": 0}, []
    if args.mode == "test" and not result["error"]:
        parsed = False
        if args.junit:
            try:
                summary, failures = parse_junit_xml(args.junit)
                parsed = True
            except (ET.ParseError, OSError):
                pass  # отчёта нет (тесты не дошли до записи) — фолбэк на stdout ниже
        if not parsed:
            try:
                summary, failures = parse_pytest_output(result["raw_output"])
            except ET.ParseError as exc:
                result["error"] = {"type": "ParseError", "message": f"не удалось распарсить отчёт: {exc}"}

    doc = {
        "mode": args.mode,
        "cwd": args.cwd,
        "cmd": result["cmd"],
        "exit_code": exit_code,
        "duration_s": result["duration_s"],
        "timed_out": result["timed_out"],
        "summary": summary if args.mode == "test" else None,
        "failures": failures,
    }
    if args.coverage:
        try:
            changed = [c for c in (args.changed or "").split(",") if c]
            doc["coverage"] = parse_coverage_xml(args.coverage, changed)
        except (ET.ParseError, OSError) as exc:
            doc["coverage"] = {"error": f"не удалось распарсить coverage: {exc}"}
    if result["error"]:
        doc["error"] = result["error"]
    print(json.dumps(doc, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
