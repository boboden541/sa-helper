"""Правила зеркалирования M1–M6 как чистые функции (СТ §4.2.2, постановка).

Один пересчёт — максимум один переход истории (остальное — следующий тик).
Конкуренция правил: побеждает отражающее более раннюю стадию — M1 (AC-4.2.2.3).
"""

from __future__ import annotations

CHILD_ACTIVE = frozenset({"in_progress", "in_review", "in_testing"})
CHILD_CLOSED = frozenset({"done", "canceled"})
CHILD_BLOCKED = frozenset({"blocked"})


def evaluate(
    story_status: str, children_statuses: list[str], blocked_rule: str | None = None
) -> tuple[str, str] | None:
    """(rule_code, to_status) первого применимого правила или None.

    blocked_rule — правило, которым история вошла в blocked (task.blocked_rule):
    из blocked M2 поднимает историю только когда блокер был «детский» (M5).
    Самоблок (своё тестирование, лимит прогонов, исчерпание попыток) не
    воскресает сам — иначе вечный цикл blocked → qa ready → in testing
    (инцидент VITRINA-1, ночь 02→03.11.2026).
    """
    has_children = len(children_statuses) > 0
    any_active = any(s in CHILD_ACTIVE for s in children_statuses)
    all_closed = has_children and all(s in CHILD_CLOSED for s in children_statuses)
    all_blocked = has_children and all(s in CHILD_BLOCKED for s in children_statuses)

    # M1: хотя бы один ребёнок в работе → in progress (из to do, blocked, in testing — защитный)
    if any_active and story_status in ("todo", "blocked", "in_testing"):
        return ("M1", "in_progress")
    # M2: все дети закрыты → qa ready (из in progress; из blocked — только M5)
    if all_closed and (
        story_status == "in_progress" or (story_status == "blocked" and blocked_rule == "M5")
    ):
        return ("M2", "qa_ready")
    # M3: история в qa ready → in testing
    if story_status == "qa_ready":
        return ("M3", "in_testing")
    # M5: все дети заблокированы → blocked (из in progress)
    if all_blocked and story_status == "in_progress":
        return ("M5", "blocked")
    return None
