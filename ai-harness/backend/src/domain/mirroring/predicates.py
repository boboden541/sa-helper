"""ФНР-16: библиотека предикатов автозеркала.

Предикат — именованное условие `(session, task, ctx) -> bool`; реализуется один раз
в коде (они трогают домен), КОМПОЗИЦИЯ — данные: `flow_transition.when`.
Новый вид условия — небольшой ПР; новые комбинации существующих — конфигурация.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from repository.models import Task
    from sqlalchemy.ext.asyncio import AsyncSession

    from domain.mirroring.ctx import MirrorCtx

# канонические множества статусов детей (перенос из rules.py)
CHILD_ACTIVE = frozenset({"in_progress", "in_review", "in_testing"})
CHILD_CLOSED = frozenset({"done", "canceled"})
CHILD_BLOCKED = frozenset({"blocked"})


@dataclass(frozen=True)
class Predicate:
    name: str
    description: str  # человекочитаемое — для FlowTab (ФТ-FNR16-04)
    fn: "Callable[[AsyncSession, Task, MirrorCtx], Awaitable[bool]]"


REGISTRY: dict[str, Predicate] = {}


def predicate(name: str, description: str):
    def deco(fn):
        REGISTRY[name] = Predicate(name=name, description=description, fn=fn)
        return fn

    return deco


def get(name: str) -> Predicate:
    p = REGISTRY.get(name)
    if p is None:
        raise KeyError(f"Предикат «{name}» не зарегистрирован (библиотека mirroring.predicates)")
    return p


async def satisfied(session: "AsyncSession", task: "Task", ctx, names) -> bool:
    """Конъюнкция предикатов по именам (ребро.when)."""
    for name in names or ():
        if not await get(name).fn(session, task, ctx):
            return False
    return True


# --- условия M1–M5 (перенос литеральных веток rules.py) -----------------------


@predicate("children_any_active", "хотя бы один дочерний элемент в работе")
async def children_any_active(session, task, ctx) -> bool:
    return any(s in CHILD_ACTIVE for s in ctx.children)


@predicate("children_all_closed", "все дочерние задачи и баги в конечном статусе")
async def children_all_closed(session, task, ctx) -> bool:
    return bool(ctx.children) and all(s in CHILD_CLOSED for s in ctx.children)


@predicate("children_all_blocked", "все дочерние задачи заблокированы")
async def children_all_blocked(session, task, ctx) -> bool:
    return bool(ctx.children) and all(s in CHILD_BLOCKED for s in ctx.children)


@predicate("blocked_by_children", "история заблокирована детьми (M5), а не собой")
async def blocked_by_children(session, task, ctx) -> bool:
    # инцидент VITRINA-1: из blocked поднимается только «детский» блокер
    return ctx.blocked_rule == "M5"


@predicate("story_in_progress", "история находится в работе")
async def story_in_progress(session, task, ctx) -> bool:
    return ctx.story_status == "in_progress"


@predicate("psi_plan_registered_current", "план ПСИ зарегистрирован и заверен текущим эталоном")
async def psi_plan_registered_current(session, task, ctx) -> bool:
    return ctx.psi_plan_ref is not None and ctx.psi_plan_ref >= (ctx.ref_version or 1)


@predicate("psi_manager_approved", "«ПСИ-редактор» одобрил последнюю версию документа")
async def psi_manager_approved(session, task, ctx) -> bool:
    return ctx.manager_state == "approved" and ctx.manager_review_version == ctx.manager_latest


@predicate("psi_manager_rejected", "«ПСИ-редактор» отклонил документ (возврат составителю)")
async def psi_manager_rejected(session, task, ctx) -> bool:
    return ctx.manager_state == "rejected"
