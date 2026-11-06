"""ФНР-16: универсальный движок автозеркала.

Вместо литеральных правил M1–M6 — рёбра flow с `when` (список имён предикатов).
Порядок применения: «побеждает отражающее более раннюю стадию» — рёбра
упорядочены по позиции статуса-цели (graph.auto_when_edges_from).
Имена правил M1–M6 сохраняются в `rule_code` рёбер: хроники и методологии
не меняются. Escape-рёбра (в blocked/canceled) гейтятся только человеком —
`when` на них не ставится (урок VITRINA-1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from domain.mirroring import predicates
from domain.transition.graph import load_graph

if TYPE_CHECKING:
    from repository.models import Task
    from sqlalchemy.ext.asyncio import AsyncSession

    from domain.mirroring.ctx import MirrorCtx


async def find_mirror_transition(
    session: "AsyncSession", task: "Task", flow_version_id, ctx: "MirrorCtx"
) -> tuple[str, str] | None:
    """(rule_code, to_status) первого допустимого авто-ребра или None.

    Один вызов — максимум один переход (остальное — следующий тик)."""
    graph = await load_graph(session, flow_version_id)
    for edge in graph.auto_when_edges_from(task.status_key):
        if await predicates.satisfied(session, task, ctx, edge.when):
            return (edge.rule_code or "", edge.to_status)
    return None
