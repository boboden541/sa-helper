"""ФНР-16 golden: старые литеральные правила M1–M6 vs универсальный движок `when`.

Эталон старой семантики встроен в тест (rules.py удалён). Корпус прогоняется через
обе реализации: движок обязан дать идентичные решения на графе сида story flow.
Расхождение по «рёбра нет» трактуется честно: старое правило с отсутствующим
авто-ребром не применялось и наблюдаемо давало None (TransitionDenied гасился)."""

from __future__ import annotations

import pytest
from domain.mirroring.ctx import MirrorCtx

CHILD_ACTIVE = frozenset({"in_progress", "in_review", "in_testing"})
CHILD_CLOSED = frozenset({"done", "canceled"})
CHILD_BLOCKED = frozenset({"blocked"})


def old_evaluate(
    story_status: str,
    children_statuses: list[str],
    blocked_rule: str | None = None,
    psi_ready: bool = False,
    manager_approved: bool = False,
    manager_rejected: bool = False,
) -> tuple[str, str] | None:
    """Точная копия семантики бывшего rules.py.evaluate (после ФНР-15)."""
    has_children = len(children_statuses) > 0
    any_active = any(s in CHILD_ACTIVE for s in children_statuses)
    all_closed = has_children and all(s in CHILD_CLOSED for s in children_statuses)
    all_blocked = has_children and all(s in CHILD_BLOCKED for s in children_statuses)

    if any_active and story_status in ("todo", "blocked", "in_testing", "psi_review"):
        return ("M1", "in_progress")
    if all_closed and (
        story_status == "in_progress" or (story_status == "blocked" and blocked_rule == "M5")
    ):
        return ("M2", "qa_ready")
    if story_status == "qa_ready" and psi_ready:
        return ("M3a", "psi_review")
    if story_status == "psi_review" and manager_approved:
        return ("M3b", "in_testing")
    if story_status == "psi_review" and manager_rejected:
        return ("M3c", "qa_ready")
    if all_blocked and story_status == "in_progress":
        return ("M5", "blocked")
    return None


CHILD_SETS = {
    "mixed": ["done", "in_progress"],
    "all_closed": ["done", "done", "canceled"],
    "all_blocked": ["blocked", "blocked"],
    "empty": [],
    "one_active": ["in_testing"],
}
SOURCES = [
    "pending",
    "todo",
    "in_progress",
    "qa_ready",
    "psi_review",
    "in_testing",
    "done",
    "blocked",
]
RULE_FLAGS = [(False, False, False), (True, False, False), (True, True, False), (True, False, True)]


@pytest.mark.parametrize("story_status", SOURCES)
@pytest.mark.parametrize("children_key", list(CHILD_SETS))
@pytest.mark.parametrize("psi_ready,approved,rejected", RULE_FLAGS)
async def test_golden_equivalence(
    _test_db, story_status, children_key, psi_ready, approved, rejected
):
    from domain.mirroring.engine import find_mirror_transition
    from sqlalchemy import text as sa_text

    blocked_rule = "M5" if children_key == "all_blocked" else None
    children = CHILD_SETS[children_key]

    async with __import__("database").get_sessionmaker()() as s:
        fv = (
            await s.execute(
                sa_text(
                    "SELECT fv.id FROM flow_version fv JOIN task_type tt ON tt.id=fv.task_type_id "
                    "WHERE tt.key='story' AND fv.is_current"
                )
            )
        ).scalar_one()
        task_stub = type("T", (), {"status_key": story_status, "flow_version_id": fv})
        ctx = MirrorCtx(
            story_status=story_status,
            children=children,
            blocked_rule=blocked_rule,
            ref_version=1,
            psi_plan_ref=1 if psi_ready else None,
            manager_state="approved" if approved else ("rejected" if rejected else None),
            manager_review_version=1 if (approved or rejected) else None,
            manager_latest=1,
            story_kind="story",
        )
        engine_result = await find_mirror_transition(s, task_stub, fv, ctx)

    old_result = old_evaluate(
        story_status,
        children,
        blocked_rule,
        psi_ready=psi_ready,
        manager_approved=approved,
        manager_rejected=rejected,
    )
    # «рёбра нет» = наблюдаемый None: старое правило без авто-ребра гасилось
    # TransitionDenied'ом (например M1-с-psi_review — ребра в flow не было)
    from domain.transition.graph import load_graph

    graph = await load_graph(s, fv)
    if old_result is not None:
        edge = next(
            (
                e
                for e in graph.edges_from(story_status)
                if e.to_status == old_result[1] and e.runner == "auto"
            ),
            None,
        )
        if edge is None or not edge.when:
            old_result = None
    assert engine_result == old_result, (
        f"расхождение на {story_status}/{children_key}/psi={psi_ready}/"
        f"ok={approved}/rej={rejected}: движок={engine_result}, эталон={old_result}"
    )
