"""Иммутабельный граф версии flow + процессный кэш (общий для API и демона)."""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from repository.models import FlowStatus, FlowTransition

# Статусы, вход в которые закрывают жёсткие связи blocked_by (постановка, «Влияние связей»)
ACTIVE_STATUSES = frozenset({"in_progress", "in_review", "in_testing"})

GATE_LABELS = {
    "developer": "чек-лист разработчика",
    "reviewer": "чек-лист ревьюера",
    "tester": "чек-лист тестировщика",
}

ARTIFACT_KINDS = {
    "in_progress": "dev_report",
    "in_review": "review_report",
    "in_testing": "qa_report",
}


@dataclass(frozen=True)
class StatusDef:
    key: str
    label: str
    checklist_gate: str | None
    is_entry: bool
    is_terminal: bool
    is_blocking: bool
    alias: str | None


@dataclass(frozen=True)
class Edge:
    from_status: str
    to_status: str
    runner: str
    display: str
    rule_code: str | None
    cond_checklist: bool
    cond_links: bool
    cond_artifact: bool


@dataclass(frozen=True)
class FlowGraph:
    flow_version_id: str
    statuses: dict[str, StatusDef]
    edges: tuple[Edge, ...]
    _by_from: dict[str, tuple[Edge, ...]] = field(default_factory=dict, repr=False)

    def status(self, key: str) -> StatusDef | None:
        return self.statuses.get(key)

    def edges_from(self, status_key: str) -> tuple[Edge, ...]:
        return self._by_from.get(status_key, ())

    def edge(self, from_status: str, to_status: str) -> Edge | None:
        for e in self.edges_from(from_status):
            if e.to_status == to_status:
                return e
        return None


_CACHE: dict[str, FlowGraph] = {}


def invalidate_cache(flow_version_id: str | None = None) -> None:
    if flow_version_id is None:
        _CACHE.clear()
    else:
        _CACHE.pop(flow_version_id, None)


async def load_graph(session: AsyncSession, flow_version_id) -> FlowGraph:
    key = str(flow_version_id)
    if key in _CACHE:
        return _CACHE[key]

    statuses = {
        s.status_key: StatusDef(
            key=s.status_key, label=s.label, checklist_gate=s.checklist_gate,
            is_entry=s.is_entry, is_terminal=s.is_terminal, is_blocking=s.is_blocking,
            alias=None,
        )
        for s in (await session.execute(
            sa.select(FlowStatus).where(FlowStatus.flow_version_id == flow_version_id)
        )).scalars()
    }
    edges = tuple(
        Edge(
            from_status=t.from_status, to_status=t.to_status, runner=t.runner,
            display=t.display, rule_code=t.rule_code,
            cond_checklist=t.cond_checklist, cond_links=t.cond_links,
            cond_artifact=t.cond_artifact,
        )
        for t in (await session.execute(
            sa.select(FlowTransition).where(FlowTransition.flow_version_id == flow_version_id)
        )).scalars()
    )
    by_from: dict[str, tuple[Edge, ...]] = {}
    for e in edges:
        by_from[e.from_status] = by_from.get(e.from_status, ()) + (e,)
    graph = FlowGraph(flow_version_id=key, statuses=statuses, edges=edges)
    object.__setattr__(graph, "_by_from", by_from)
    _CACHE[key] = graph
    return graph
