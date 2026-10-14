"""Manifest validator: mechanical checks for FNR_N/harness/manifest.json.

/impl-plan generates the manifest; this tool verifies it before the human
gate, so schema drift never reaches /impl-run. Checks:
  - required top-level fields and canonical status enums (v2 §10);
  - task DAG: depends_on references exist, no cycles;
  - naming: epic branch and per-task branches/worktrees;
  - traceability ids: FR-* and AC-* formats, acceptance criteria non-empty;
  - systems referenced by tasks are declared.

stdout: single JSON {"valid": bool, "errors": [...], "warnings": [...]}.
Exit code: 0 valid, 1 invalid, 2 usage error. stdlib only, cross-platform.

Usage:
    python3 harness/manifest_check.py --file <path/to/manifest.json>
"""

from __future__ import annotations

import argparse
import json
import re
import sys

TASK_STATUSES = {
    "PLANNED", "APPROVED", "TDD_RED", "TDD_GREEN", "GATES", "AGENT_REVIEW", "DONE",
    "ESCALATED_BLOCKED", "ABORTED",
}
TOP_STATUSES = {"PLANNED", "AWAITING_APPROVAL", "APPROVED", "IN_PROGRESS", "COMPLETED", "ABORTED"}
PHASES = {"contract", "producer", "consumer", "regular", "characterization"}
GATE_NAMES = {"build", "test", "lint", "coverage", "review"}

BRANCH_RE = re.compile(r"^harness/FNR-\d+-[a-z0-9][a-z0-9-]*(-t\d+)?$")
WORKTREE_RE = re.compile(r"^\.worktrees/FNR-\d+-t\d+$")
FR_RE = re.compile(r"^FR-\d+(\.\d+)*$")
AC_RE = re.compile(r"^AC-\d+(\.\d+)*\.\d+$")
TASK_ID_RE = re.compile(r"^T\d+$")

REQUIRED_TOP = ("fnr_id", "epic_branch", "status", "systems", "tasks")


def validate(doc: dict) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for a parsed manifest document."""
    errors: list[str] = []
    warnings: list[str] = []

    for field in REQUIRED_TOP:
        if field not in doc:
            errors.append(f"нет обязательного поля верхнего уровня: {field}")
    if errors:
        return errors, warnings

    if doc.get("status") not in TOP_STATUSES:
        errors.append(f"status='{doc.get('status')}' вне канона {sorted(TOP_STATUSES)}")
    if not BRANCH_RE.match(doc.get("epic_branch", "")):
        errors.append(f"epic_branch='{doc.get('epic_branch')}' не соответствует шаблону harness/FNR-<N>-<slug>")

    systems = {s.get("name"): s for s in doc.get("systems", []) if isinstance(s, dict)}
    if not systems:
        errors.append("systems пуст — план без систем невозможен")
    for name, s in systems.items():
        if s.get("bootstrap") not in (None, "ready", "ready_with_notes", "stop", "ready_data_only"):
            errors.append(f"systems[{name}].bootstrap='{s.get('bootstrap')}' вне канона")

    tasks = doc.get("tasks", [])
    if not tasks:
        errors.append("tasks пуст — план без задач не имеет смысла")

    seen_ids: set[str] = set()
    for t in tasks:
        tid = t.get("id", "?")
        if not TASK_ID_RE.match(str(tid)):
            errors.append(f"задача id='{tid}' не соответствует шаблону T<номер>")
            continue
        if tid in seen_ids:
            errors.append(f"дубликат id задачи: {tid}")
        seen_ids.add(tid)

    for t in tasks:
        tid = t.get("id", "?")
        if t.get("status") not in TASK_STATUSES:
            errors.append(f"{tid}: status='{t.get('status')}' вне канона {sorted(TASK_STATUSES)}")
        phase = t.get("phase", "regular")
        if phase not in PHASES:
            errors.append(f"{tid}: phase='{phase}' вне канона {sorted(PHASES)}")
        if not BRANCH_RE.match(t.get("branch", "")):
            errors.append(f"{tid}: branch='{t.get('branch')}' не соответствует шаблону")
        if t.get("status") in ("PLANNED", "APPROVED"):
            pass  # worktree появляется при старте задачи; для будущих может отсутствовать
        elif t.get("worktree") and not WORKTREE_RE.match(t["worktree"]):
            errors.append(f"{tid}: worktree='{t['worktree']}' не соответствует шаблону .worktrees/FNR-<N>-t<k>")
        if t.get("system") not in systems:
            errors.append(f"{tid}: система '{t.get('system')}' не объявлена в systems")
        frs = t.get("fr_ids") or []
        if not frs:
            errors.append(f"{tid}: нет привязки к требованиям (fr_ids пуст)")
        for fr in frs:
            if not FR_RE.match(str(fr)):
                errors.append(f"{tid}: FR-ID '{fr}' не соответствует шаблону FR-<номер задачи>")
        acs = t.get("acceptance_criteria") or []
        if not acs:
            errors.append(f"{tid}: критерии приёмки пусты — задача неприемлема")
        for ac in acs:
            if not AC_RE.match(str(ac.get("id", ""))):
                errors.append(f"{tid}: AC-ID '{ac.get('id')}' не соответствует шаблону AC-<задача>.<k>")
            if not (ac.get("desc") or "").strip():
                errors.append(f"{tid}: критерий {ac.get('id')} без формулировки")
            if ac.get("status") not in ("PENDING", "PASSED", "FAILED"):
                errors.append(f"{tid}: критерий {ac.get('id')} status='{ac.get('status')}' вне канона")
        gates = t.get("gates") or {}
        unknown = set(gates) - GATE_NAMES
        if unknown:
            warnings.append(f"{tid}: нестандартные гейты {sorted(unknown)} (допустимо, канон: {sorted(GATE_NAMES)})")

    # DAG: ссылки существуют, циклов нет
    graph: dict[str, list[str]] = {}
    for t in tasks:
        tid = t.get("id", "?")
        deps = t.get("depends_on") or []
        for d in deps:
            if d not in seen_ids:
                errors.append(f"{tid}: depends_on ссылается на несуществующую задачу '{d}'")
        graph[tid] = [d for d in deps if d in seen_ids]

    state: dict[str, int] = {}  # 0=в процессе, 1=готово

    def visit(node: str, stack: list[str]) -> None:
        if state.get(node) == 1:
            return
        if node in stack:
            cycle = " → ".join(stack[stack.index(node):] + [node])
            errors.append(f"цикл в DAG зависимостей: {cycle}")
            return
        for dep in graph.get(node, []):
            visit(dep, stack + [node])
        state[node] = 1

    for tid in graph:
        visit(tid, [])

    if doc.get("status") == "APPROVED" and any(t.get("status") == "PLANNED" for t in tasks):
        warnings.append("status=APPROVED, но часть задач ещё PLANNED (не APPROVED)")

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Валидатор manifest.json контура реализации")
    parser.add_argument("--file", required=True, help="путь к manifest.json")
    args = parser.parse_args()
    try:
        doc = json.load(open(args.file, encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"valid": False, "errors": [f"файл не читается/не JSON: {exc}"], "warnings": []}, ensure_ascii=False, indent=2))
        return 1
    errors, warnings = validate(doc)
    print(json.dumps({"valid": not errors, "errors": errors, "warnings": warnings}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
