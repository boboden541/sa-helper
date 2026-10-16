"""Manifest validator: mechanical checks for FNR_N/harness/manifest.json.

/impl-plan (или /impl-handoff) генерирует манифест; этот инструмент проверяет
его до человеческого шлюза, чтобы дрейф схемы не дошёл до /impl-run и демона.
Проверки:
  - обязательные поля верхнего уровня и канонические статусы (v2 §10);
  - DAG задач: depends_on существуют, циклов нет;
  - именование: epic-ветка и ветки/worktree задач;
  - трассируемость: форматы FR-*/AC-*, критерии непустые;
  - системы, упомянутые задачами, объявлены.
v3 (handoff_pipeline_design.md §3.2, все поля опциональны — документы v2
остаются валидными):
  - task.pipeline — статус конвейера (state_machine.PIPELINE_STATUSES),
    согласованность с v2-статусом (consistent_v2);
  - task.blocked_from / retries / review_iterations / paused / skip_review /
    session_id / owner / findings — поля демона и ревью-петли.

stdout: single JSON {"valid": bool, "errors": [...], "warnings": [...]}.
Exit code: 0 valid, 1 invalid, 2 usage error. stdlib only, cross-platform.

Usage:
    python3 harness/manifest_check.py --file <path/to/manifest.json>
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import state_machine as sm  # noqa: E402

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


def _validate_pipeline_fields(tid: str, t: dict) -> list[str]:
    """Поля конвейера v3 (все опциональны; документы v2 валидны без них)."""
    errors: list[str] = []
    pipeline = t.get("pipeline")
    if "pipeline" in t and pipeline not in sm.PIPELINE_STATUSES:
        errors.append(f"{tid}: pipeline='{pipeline}' вне канона {sorted(sm.PIPELINE_STATUSES)}")
        return errors
    if pipeline:
        v2_status = t.get("status", "")
        if v2_status and not sm.consistent_v2(pipeline, v2_status):
            errors.append(f"{tid}: pipeline='{pipeline}' не согласован со status='{v2_status}' "
                          f"(ожидается {sorted(sm.V2_SET_FOR_PIPELINE.get(pipeline, set()))})")
    if "blocked_from" in t and t["blocked_from"] not in (None, *sm.RESUMABLE):
        errors.append(f"{tid}: blocked_from='{t['blocked_from']}' вне канона {sorted(sm.RESUMABLE)}|null")
    for field in ("retries", "review_iterations"):
        if field in t and (not isinstance(t[field], int) or isinstance(t[field], bool) or t[field] < 0):
            errors.append(f"{tid}: {field} должен быть целым ≥ 0")
    for field in ("paused", "skip_review"):
        if field in t and not isinstance(t[field], bool):
            errors.append(f"{tid}: {field} должен быть булевым")
    if "owner" in t and t["owner"] not in ("ai", "human"):
        errors.append(f"{tid}: owner='{t['owner']}' вне канона (ai|human)")
    if "origin" in t and t["origin"] not in ("plan", "manual", "agent"):
        errors.append(f"{tid}: origin='{t['origin']}' вне канона (plan|manual|agent)")
    if t.get("origin") == "agent" and "pipeline" not in t:
        errors.append(f"{tid}: агентская задача требует pipeline (PROPOSED до решения человека)")
    if "session_id" in t and not isinstance(t["session_id"], str):
        errors.append(f"{tid}: session_id должен быть строкой")
    findings = t.get("findings")
    if findings is not None:
        if not isinstance(findings, list):
            errors.append(f"{tid}: findings должен быть массивом")
        else:
            for i, f in enumerate(findings):
                if not isinstance(f, dict) or not (f.get("id") or "").strip() or not (f.get("text") or "").strip():
                    errors.append(f"{tid}: findings[{i}] требует непустые id и text")
                elif f.get("resolution", "open") not in ("open", "resolved", "still_blocking"):
                    errors.append(f"{tid}: findings[{i}].resolution вне канона (open|resolved|still_blocking)")
    return errors


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
    if "story_title" in doc and not str(doc.get("story_title") or "").strip():
        errors.append("story_title должен быть непустой строкой (канон v3)")
    if "auto_mode" in doc and not isinstance(doc["auto_mode"], bool):
        errors.append("auto_mode должен быть булевым (конвейер v3)")
    if "created_by" in doc and doc["created_by"] not in ("impl-plan", "impl-handoff"):
        warnings.append(f"created_by='{doc['created_by']}' вне канона (impl-plan|impl-handoff)")
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
        errors += _validate_pipeline_fields(tid, t)

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
