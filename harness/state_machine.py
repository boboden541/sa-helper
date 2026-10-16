"""Машина состояний конвейера задач (v3 — handoff_pipeline_design.md §3.2).

Чистая функция без I/O: (pipeline, событие, контекст) → патч манифеста или отказ
с кодом. Одна реализация для демона (orchestrator.py), валидатора
(manifest_check.py) и витрины (какие кнопки действий активны). Только stdlib,
кроссплатформенно. Канон имён — английский; витрина переводит для человека.

Статусы (task.pipeline):

  BACKLOG       в плане, зависимости (depends_on) ещё не DONE/VERIFIED
  READY         зависимости готовы, ждёт свободный слот исполнителя
  IMPLEMENTING  идёт сессия исполнителя; внутренние фазы ведёт сессия
                (v2-поля status/phase: TDD_RED → TDD_GREEN → GATES)
  REVIEW        идёт независимая сессия ревью
  DONE          ревью APPROVED; ждёт сквозного verify
  VERIFIED      /impl-verify пройден; терминальный (PR-заготовка у человека)
  BLOCKED       внешняя помеха (окружение, лимиты); авто-retry с backoff
  NEEDS_HUMAN   петля ревью не сошлась / эскалация circuit breaker / человек
                запросил разбор
  ABORTED       терминальный; остановлен человеком

Пауза — НЕ статус (флаг `.flags/PAUSE` / task.paused, вступает на границе
итерации), как в v2. Аналогично v2-поле `status` остаётся внутренним состоянием
исполнителя; соответствие pipeline ↔ status проверяет consistent_v2().
"""

from __future__ import annotations

BACKLOG = "BACKLOG"
READY = "READY"
IMPLEMENTING = "IMPLEMENTING"
REVIEW = "REVIEW"
DONE = "DONE"
VERIFIED = "VERIFIED"
BLOCKED = "BLOCKED"
NEEDS_HUMAN = "NEEDS_HUMAN"
ABORTED = "ABORTED"

PIPELINE_STATUSES = {
    BACKLOG, READY, IMPLEMENTING, REVIEW, DONE, VERIFIED,
    BLOCKED, NEEDS_HUMAN, ABORTED,
}
TERMINAL = {VERIFIED, ABORTED}
# Статусы, из которых задача может уйти дальше по конвейеру
ACTIVE = PIPELINE_STATUSES - TERMINAL
# Статусы, из которых возможен возврат после BLOCKED / NEEDS_HUMAN
RESUMABLE = {READY, IMPLEMENTING, REVIEW}

# --- события ------------------------------------------------------------
# Префиксы: D: демон (автомат), X: сессия агента (результат стадии),
# A: человек (кнопка витрины / флаг).

EV_QUEUE_READY = "queue_ready"                  # D: зависимости готовы + план утверждён
EV_START = "start"                              # D: слот свободен (или A: start_task)
EV_IMPL_PASSED = "implementation_passed"        # X: AC PASSED + гейты зелёные
EV_IMPL_ESCALATED = "implementation_escalated"  # X: circuit breaker (4 итерации)
EV_IMPL_BLOCKED = "implementation_blocked"      # D: окружение/таймаут → backoff
EV_REVIEW_APPROVED = "review_approved"          # X: вердикт APPROVED
EV_REVIEW_CHANGES = "review_changes"            # X: CHANGES_REQUESTED (петля продолжается)
EV_REVIEW_STALLED = "review_stalled"            # D: петля не сошлась (closure/лимит)
EV_FORCE_APPROVE = "force_approve"              # A: принять despite findings
EV_REQUEST_CHANGES = "request_changes"          # A: вернуть с DONE (комментарий = задание)
EV_VERIFY_PASSED = "verify_passed"              # D: /impl-verify зелёный
EV_RETRY = "retry"                              # D: backoff истёк (или A: retry)
EV_BLOCKED_ESCALATED = "blocked_escalated"      # D: retries исчерпаны в BLOCKED
EV_RESUME_WORK = "resume_work"                  # A: разбор окончен — продолжить
EV_ABORT = "abort"                              # A: остановить задачу

# Таблица переходов. "to" — строка или callable(task_view, ctx) для редких
# динамических случаев (implementation_passed: REVIEW/DONE по skip_review).
_TRANSITIONS: dict[str, dict] = {
    EV_QUEUE_READY: {"from": {BACKLOG}, "to": READY},
    EV_START: {"from": {READY}, "to": IMPLEMENTING},
    EV_IMPL_PASSED: {"from": {IMPLEMENTING}, "to": None},  # динамически, см. transition()
    EV_IMPL_ESCALATED: {"from": {IMPLEMENTING}, "to": NEEDS_HUMAN},
    EV_IMPL_BLOCKED: {"from": {IMPLEMENTING}, "to": BLOCKED},
    EV_REVIEW_APPROVED: {"from": {REVIEW}, "to": DONE},
    EV_REVIEW_CHANGES: {"from": {REVIEW}, "to": IMPLEMENTING},
    EV_REVIEW_STALLED: {"from": {REVIEW}, "to": NEEDS_HUMAN},
    EV_FORCE_APPROVE: {"from": {REVIEW}, "to": DONE},
    EV_REQUEST_CHANGES: {"from": {DONE}, "to": IMPLEMENTING},
    EV_VERIFY_PASSED: {"from": {DONE}, "to": VERIFIED},
    EV_RETRY: {"from": {BLOCKED}, "to": None},        # to = blocked_from
    EV_BLOCKED_ESCALATED: {"from": {BLOCKED}, "to": NEEDS_HUMAN},
    EV_RESUME_WORK: {"from": {NEEDS_HUMAN}, "to": None},  # to = blocked_from
    EV_ABORT: {"from": ACTIVE, "to": ABORTED},
}


def transition(task_view: dict, event: str, ctx: dict | None = None) -> dict:
    """Применить событие к задаче.

    task_view: срез задачи (pipeline, skip_review, blocked_from, retries) —
        достаточно этих полей; лишние игнорируются.
    ctx: опциональные ограничения (зарезервировано для демона: retries_max и
        т.п.; машина сама стратегий не считает — решение о событии принимает
        вызывающий, машина проверяет легальность).

    Возвращает:
      {"ok": True, "patch": {...}}    — поля для слияния в задачу манифеста;
      {"ok": False, "code", "error"}  — отказ (не мутируй манифест).

    Патч всегда содержит pipeline (новый статус); побочные поля:
    blocked_from, retries, review_iterations. Времена (pipeline_since и т.п.)
    проставляет демон — машина время не трогает.
    """
    ctx = ctx or {}
    pipeline = task_view.get("pipeline")
    spec = _TRANSITIONS.get(event)
    if spec is None:
        return {"ok": False, "code": "unknown_event", "error": f"неизвестное событие '{event}'"}
    if pipeline not in spec["from"]:
        return {
            "ok": False,
            "code": "illegal_transition",
            "error": f"событие '{event}' недопустимо из статуса {pipeline} "
                     f"(разрешено из {sorted(spec['from'])})",
        }

    patch: dict = {}

    if event == EV_IMPL_PASSED:
        target = DONE if task_view.get("skip_review") else REVIEW
        patch["pipeline"] = target
    elif event in (EV_RETRY, EV_RESUME_WORK):
        back_to = task_view.get("blocked_from") or ctx.get("blocked_from")
        if back_to not in RESUMABLE:
            return {
                "ok": False,
                "code": "missing_field",
                "error": f"событие '{event}' требует blocked_from ∈ {sorted(RESUMABLE)}, "
                         f"получено {back_to!r}",
            }
        patch["pipeline"] = back_to
        patch["blocked_from"] = None
    elif event == EV_IMPL_BLOCKED:
        patch["pipeline"] = BLOCKED
        patch["blocked_from"] = IMPLEMENTING
        patch["retries"] = int(task_view.get("retries") or 0) + 1
    elif event == EV_REVIEW_CHANGES:
        patch["pipeline"] = IMPLEMENTING
        patch["review_iterations"] = int(task_view.get("review_iterations") or 0) + 1
    else:
        patch["pipeline"] = spec["to"]

    if event not in (EV_RETRY, EV_RESUME_WORK) and pipeline in (BLOCKED, NEEDS_HUMAN):
        # уход из BLOCKED/NEEDS_HUMAN мимо retry/resume (например, abort) —
        # поле-подсказка о возврате больше не актуально
        patch.setdefault("blocked_from", None)

    return {"ok": True, "patch": patch}


def allowed_events(task_view: dict) -> list[str]:
    """События, легальные для задачи в текущем статусе (кнопки витрины)."""
    pipeline = task_view.get("pipeline")
    result = []
    for event, spec in _TRANSITIONS.items():
        if pipeline in spec["from"]:
            # retry/resume показывает всегда из BLOCKED/NEEDS_HUMAN —
            # легальность blocked_from проверит transition()
            result.append(event)
    return sorted(result)


# --- соответствие v2 ----------------------------------------------------

# v2-статус (внутреннее состояние исполнителя) для pipeline-статуса.
# None — допустимо несколько значений, см. V2_SET_FOR_PIPELINE.
V2_FOR_PIPELINE: dict[str, str | None] = {
    BACKLOG: "PLANNED",
    READY: "APPROVED",
    IMPLEMENTING: None,           # APPROVED (старт) → TDD_RED → TDD_GREEN → GATES
    REVIEW: "AGENT_REVIEW",
    DONE: "DONE",
    VERIFIED: "DONE",             # v2 не знает VERIFIED; finer-статус только в pipeline
    BLOCKED: None,                # любой активный внутренний
    NEEDS_HUMAN: "ESCALATED_BLOCKED",
    ABORTED: "ABORTED",
}
V2_SET_FOR_PIPELINE: dict[str, set[str]] = {
    BACKLOG: {"PLANNED"},
    READY: {"APPROVED"},
    IMPLEMENTING: {"APPROVED", "TDD_RED", "TDD_GREEN", "GATES"},
    REVIEW: {"AGENT_REVIEW"},
    DONE: {"DONE"},
    VERIFIED: {"DONE"},
    BLOCKED: {"PLANNED", "APPROVED", "TDD_RED", "TDD_GREEN", "GATES", "AGENT_REVIEW"},
    NEEDS_HUMAN: {"ESCALATED_BLOCKED"},
    ABORTED: {"ABORTED"},
}


def consistent_v2(pipeline: str, v2_status: str) -> bool:
    """Согласованы ли pipeline-статус и v2-статус задачи (для валидатора)."""
    allowed = V2_SET_FOR_PIPELINE.get(pipeline)
    if allowed is None:
        return pipeline in PIPELINE_STATUSES  # неизвестный pipeline — не здесь проверяем
    return v2_status in allowed
