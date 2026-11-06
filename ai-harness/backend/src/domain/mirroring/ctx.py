"""ФНР-16: контекст вычисления зеркал — пакетная загрузка фактов одним запросом
на тик (N+1 запрещён: все истории тика читаются пачкой, как в mirror.py)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MirrorCtx:
    story_status: str
    children: list[str] = field(default_factory=list)
    blocked_rule: str | None = None
    ref_version: int = 1
    psi_plan_ref: int | None = None
    manager_state: str | None = None
    manager_review_version: int | None = None
    manager_latest: int | None = None
    story_kind: str | None = None  # ключ типа задачи (story | common_task | …)
