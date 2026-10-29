"""Движок переходов — единственная точка правил flow (СТ §4.2.1).

Чистые функции без IO: юзкейсы загружают граф и данные гейтов, движок решает.
Правила едины для человека через API, агента из демона и правил автомата (ФТ-ah-26…29).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from domain.transition.graph import ACTIVE_STATUSES, GATE_LABELS, FlowGraph


@dataclass(frozen=True)
class Subject:
    kind: str  # human | agent | eve | auto
    user_id: str | None = None
    # статусы, на которых агент назначен в матрице (для kind='agent')
    assigned_statuses: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ChecklistState:
    exists: bool = False
    total: int = 0
    open: int = 0
    failed: int = 0


@dataclass(frozen=True)
class GateData:
    """Данные гейтов задачи на момент решения."""

    checklists: dict[str, ChecklistState] = field(default_factory=dict)
    open_blockers: tuple[tuple[str, str], ...] = ()  # (code, title)
    artifacts: dict[str, bool] = field(default_factory=dict)  # kind -> present
    psi_failed: int = 0  # непройденные пункты ПСИ истории


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str = ""


def _reason_checklist_not_created(gate: str) -> str:
    return f"{GATE_LABELS[gate]} не создан — этап не начат"


def _reason_checklist_closed(state: ChecklistState, gate: str) -> str:
    if state.open:
        plural = "пункт" if state.open % 10 == 1 and state.open % 100 != 11 else "пунктов"
        return f"{GATE_LABELS[gate]}: не закрыто {state.open} {plural}"
    return f"{GATE_LABELS[gate]}: есть неуспешные пункты ({state.failed})"


def _checklist_state_is_closed(state: ChecklistState) -> bool:
    return state.exists and state.total > 0 and state.open == 0 and state.failed == 0


def check_edge(graph: FlowGraph, current: str, target: str, subject: Subject,
               gates: GateData) -> Decision:
    """Решение по конкретному ребру: права субъекта, затем гейты (порядок СТ §4.2.1)."""
    edge = graph.edge(current, target)
    if edge is None:
        from_status = graph.status(current)
        to_status = graph.status(target)
        if to_status is None:
            return Decision(False, f"Статус «{target}» не существует в flow задачи")
        return Decision(
            False,
            "Переход не предусмотрен flow: "
            f"«{from_status.label if from_status else current}» → «{to_status.label}»",
        )

    # --- права субъекта (матрица прав, постановка «Права субъектов») ---
    if subject.kind == "auto":
        if edge.runner != "auto":
            return Decision(False, f"Ребро не помечено как автоматическое ({edge.runner})")
    elif subject.kind == "agent":
        if current not in subject.assigned_statuses:
            return Decision(False, f"Агент не назначен на статус «{current}» — переход отклонён")
        if edge.runner not in ("agent", "auto_or_agent"):
            return Decision(False, "Переход недоступен агенту: "
                                   f"исполнитель ребра — {edge.runner}")
        if target == "canceled":
            return Decision(False, "Агент не может отменять задачи")
        if graph.status(current).is_terminal:
            return Decision(False, "Агент не может переводить из терминального статуса")
    # human / eve: любые валидные рёбра (Eve приравнена к человеку)

    # --- гейты (ФТ-ah-9): жёсткие связи, ПСИ, чеклисты, артефакты ---
    if edge.cond_links and target in ACTIVE_STATUSES and gates.open_blockers:
        code, title = gates.open_blockers[0]
        return Decision(False, f"жёсткая связь blocked by {code} — «{title}» не закрыта")

    if target == "done" and gates.psi_failed:
        return Decision(False, f"прогон ПСИ не пройден полностью: {gates.psi_failed} "
                               "пунктов «не пройден»")

    if edge.cond_checklist:
        decision = _check_gates(graph, edge, current, target, gates)
        if decision is not None:
            return decision

    if edge.cond_artifact:
        from domain.transition.graph import ARTIFACT_KINDS

        kind = ARTIFACT_KINDS.get(current)
        if kind and not gates.artifacts.get(kind, False):
            return Decision(False, "не заполнен артефакт этапа")

    return Decision(True)


# Порядок стадий для определения направления перехода (вперёд/назад)
STAGE_ORDER = {
    "pending": 0, "backlog": 1, "todo": 2, "in_progress": 3,
    "review_ready": 4, "in_review": 4, "qa_ready": 5, "in_testing": 5, "done": 6,
}
ESCAPE_STATUSES = frozenset({"blocked", "canceled"})


def _check_gates(graph: FlowGraph, edge, current: str, target: str,
                 gates: GateData) -> Decision | None:
    """Чеклист-гейты (ФТ-ah-9). Семантика:
    - уход в blocked/canceled — без проверок (единственный выход с незакрытым чеклистом);
    - выход из статуса с гейтом вперёд: чеклист создан и закрыт без failed
      (для todo — только создан: декомпозиция завершена, работа впереди);
    - вход в работу (in progress) — чеклист этапа создан («взять в работу нельзя», AC-4.2.1.1);
    - автоматические рёбра не проверяют «создан» (автомат не составляет чеклисты,
      иначе зеркалирование M3 блокировалось бы пустым чеклистом тестировщика).
    """
    src = graph.status(current)
    dst = graph.status(target)
    # canceled/blocked — всегда разрешены как вход (escape-статусы), условия
    # «canceled как терминальный» были дублем этого правила
    if dst.key in ESCAPE_STATUSES:
        return None

    stage_from = STAGE_ORDER.get(src.key, 0)
    stage_to = STAGE_ORDER.get(dst.key, 0)
    forward = stage_to > stage_from

    def state_of(gate: str) -> ChecklistState:
        return gates.checklists.get(gate, ChecklistState())

    if forward and src.checklist_gate:
        state = state_of(src.checklist_gate)
        if not state.exists or state.total == 0:
            # absent/empty checklist — honest "not created" instead of "0 items not closed" (bug from the owner)
            reason = _reason_checklist_not_created(src.checklist_gate)
            if src.key == "todo":
                reason += " — decomposition not done"
            return Decision(False, reason)
        if not _checklist_state_is_closed(state):
            return Decision(False, _reason_checklist_closed(state, src.checklist_gate))

    if edge.runner != "auto" and dst.key == "in_progress" and dst.checklist_gate:
        state = state_of(dst.checklist_gate)
        if not state.exists or state.total == 0:
            return Decision(False, _reason_checklist_not_created(dst.checklist_gate))

    if forward and edge.runner != "auto" and dst.key == "in_review" and dst.checklist_gate:
        state = state_of(dst.checklist_gate)
        if not state.exists or state.total == 0:
            return Decision(False, _reason_checklist_not_created(dst.checklist_gate))

    return None


def allowed_targets(graph: FlowGraph, current: str, subject: Subject, gates: GateData) -> dict[str, Decision]:
    """Все рёбра из текущего статуса с решениями — для карточки и DnD-подсветки."""
    return {
        e.to_status: check_edge(graph, current, e.to_status, subject, gates)
        for e in graph.edges_from(current)
    }


def check_force(graph: FlowGraph, current: str, target: str, subject: Subject,
                reason: str | None) -> Decision:
    """Форс: только человек (Eve приравнена), причина обязательна (ФТ-ah-28)."""
    if subject.kind not in ("human", "eve"):
        return Decision(False, "Форс-переход доступен только человеку")
    if not (reason or "").strip():
        return Decision(False, "Причина форс-перехода обязательна")
    if graph.status(target) is None:
        return Decision(False, f"Статус «{target}» не существует в flow задачи")
    return Decision(True)
