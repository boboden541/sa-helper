"""Контракт уведомлений «система ждёт человека» (ФТ-ah-45): 10 событий.

Создание — событийное (из юзкейсов, порождающих состояние); снятие —
резолвер состояний после перехода и на тике демона. Частичный UNIQUE
(code,event_key) WHERE resolved_at IS NULL делает создание идемпотентным.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from repository.models import Notification, Task

EVENT_KEYS = {
    "pending_moderation": "Задача ждёт модерации",
    "blocked": "Задача заблокирована",
    "cycle_not_converging": "Цикл доработки не сходится",
    "merge_conflict": "Конфликт слияния",
    "provider_or_path_down": "Провайдер или путь проекта недоступны",
    "no_agent_on_status": "На статусе нет назначенного агента",
    "waiting_review": "Задача ждёт ревью",
    "waiting_testing": "Задача ждёт тестирования",
    "story_on_psi": "История на прогоне ПСИ",
    "task_closed": "Задача закрыта",
}


async def raise_event(session: AsyncSession, code: str, event_key: str,
                      message: str, tech_detail: str | None = None) -> None:
    """Идемпотентно поднимает уведомление (повтор — no-op по частичному UNIQUE)."""
    stmt = pg_insert(Notification).values(
        code=code, event_key=event_key, message=message, tech_detail=tech_detail
    ).on_conflict_do_nothing(index_elements=["code", "event_key"],
                             index_where=sa.text("resolved_at IS NULL"))
    await session.execute(stmt)


async def resolve(session: AsyncSession, code: str, event_keys: list[str] | None = None) -> int:
    query = sa.update(Notification).where(
        Notification.code == code, Notification.resolved_at.is_(None))
    if event_keys:
        query = query.where(Notification.event_key.in_(event_keys))
    result = await session.execute(query.values(resolved_at=sa.func.now()))
    return result.rowcount or 0


async def list_open(session: AsyncSession, limit: int = 100) -> list[dict]:
    rows = (await session.execute(
        sa.select(Notification).where(Notification.resolved_at.is_(None))
        .order_by(Notification.created_at.desc()).limit(limit))).scalars().all()
    return [{"id": str(n.id), "code": n.code, "eventKey": n.event_key,
             "message": n.message, "techDetail": n.tech_detail,
             "at": n.created_at.isoformat()} for n in rows]


async def on_transition(session: AsyncSession, task: Task, to: str) -> None:
    """Резолвер состояний при переходе; поднятие «ждёт человека» на рабочих статусах."""
    # состояние ушло — открытые по этой задаче уведомления снимаются
    await resolve(session, task.code)
    if to == "blocked":
        await raise_event(session, task.code, "blocked",
                          f"Задача {task.code} заблокирована: {task.blocked_reason or 'требуется человек'}",
                          tech_detail=task.blocked_reason)
    elif to == "in_review":
        await raise_event(session, task.code, "waiting_review",
                          f"Задача {task.code} ждёт ревью")
    elif to == "in_testing":
        type_key = (await session.execute(
            sa.text("SELECT key FROM task_type WHERE id = :i"),
            {"i": str(task.task_type_id)})).scalar_one()
        if type_key == "story":
            await raise_event(session, task.code, "story_on_psi",
                              f"История {task.code} на сквозном тестировании и прогоне ПСИ")
        else:
            await raise_event(session, task.code, "waiting_testing",
                              f"Задача {task.code} ждёт тестирования")
    elif to in ("done", "canceled"):
        await raise_event(session, task.code, "task_closed",
                          f"Задача {task.code} закрыта ({to})")
