"""ФНР-16: каталог поведений и классов стадий (данные на статусах вместо литералей).

Поведение — известная демон-эвристика, подключаемая статусу через
`flow_status.behaviors`. Новый вид поведения — код-ПР; подключение — конфигурация.
"""

from __future__ import annotations

# --- каталог поведений -------------------------------------------------------
VERIFY_STAND = "verify_stand"  # гейт стенда перед запуском прогона (ФТ-FNR14-09)
ENSURE_WORKTREE = "ensure_worktree"  # ветка task/<код> при входе в работу (ФТ-ah-37)
NAIVE_REVIEW = "naive_review"  # изолированный контекст ревизии «на дурака» (ФНР-15 4.8)
ACCEPTANCE_BUDGET = "acceptance_budget"  # жёсткий бюджет прогона приёмки (≤60 мин)

BEHAVIORS: dict[str, str] = {
    VERIFY_STAND: "гейт доступности стенда перед запуском прогона",
    ENSURE_WORKTREE: "создание ветки/worktree задачи при входе в работу",
    NAIVE_REVIEW: "изолированный контекст ревизии документа «на дурака»",
    ACCEPTANCE_BUDGET: "жёсткий бюджет прогона приёмки",
}

# --- классы стадий ------------------------------------------------------------
K_DECOMPOSITION = "decomposition"
K_WORK = "work"
K_REVIEW = "review"
K_ACCEPTANCE = "acceptance"
K_CLOSED = "closed"

KINDS: dict[str, str] = {
    K_DECOMPOSITION: "подготовка: декомпозиция/модерация",
    K_WORK: "исполнение",
    K_REVIEW: "подготовка приёмки: план/ревизия документа",
    K_ACCEPTANCE: "сквозная приёмка",
    K_CLOSED: "конечные статусы",
}


async def status_def(session, task):
    """StatusDef статуса задачи из её flow-версии (граф кэшируется процессно)."""
    from usecase.task.transition import task_flow_version_id

    from domain.transition.graph import load_graph

    graph = await load_graph(session, await task_flow_version_id(session, task))
    return graph.status(task.status_key)


async def has_behavior(session, task, behavior: str) -> bool:
    s = await status_def(session, task)
    return bool(s and behavior in s.behaviors)
