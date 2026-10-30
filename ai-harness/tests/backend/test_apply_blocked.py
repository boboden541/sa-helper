"""apply_blocked: автоблокировка через движок с rule_code в хронике (анализ
30.10.2026 — раньше _block_unassigned и отчёт агента писали blocked напрямую,
мимо рёбер flow и без rule_code — второй параллельный контур смены статуса)."""

from __future__ import annotations

import sqlalchemy as sa

from repository.models import Chronicle, Task
from usecase.task.transition import apply_blocked


async def _mk_task(client) -> str:
    r = await client.post("/api/v1/tasks", json={
        "projectId": "AH", "type": "common_task", "title": "Блок-тест",
        "priority": "high", "authorTag": "by_human"})
    assert r.status_code == 200, r.text
    return r.json()["code"]


async def test_apply_blocked_writes_rule_code(client, session):
    code = await _mk_task(client)
    task = (await session.execute(
        sa.select(Task).where(Task.code == code))).scalar_one()
    result = await apply_blocked(session, task, None,
                                 "тест: нет назначенного агента",
                                 subject_kind="auto", rule_code="AUTO_BLOCK")
    await session.commit()
    assert result.status_key == "blocked"
    assert result.blocked_reason.startswith("тест")
    rows = (await session.execute(
        sa.select(Chronicle).where(Chronicle.task_id == task.id,
                                   Chronicle.rule_code == "AUTO_BLOCK")
    )).scalars().all()
    assert rows, "rule_code не попал в хронику"
    assert any("Автоблокировка" in r.message for r in rows)
    await session.rollback()  # закрываем автобегин-транзакцию ассертов: открытый SELECT блокирует TRUNCATE teardown


async def test_apply_blocked_from_status_without_edge(session, client):
    """Нет легального ребра → прямой write-фолбэк с rule_code (escape-семантика,
    прежнее поведение сохранено)."""
    code = await _mk_task(client)
    task = (await session.execute(
        sa.select(Task).where(Task.code == code))).scalar_one()
    task.status_key = "done"  # ребра done→blocked в сиде нет — уход в фолбэк
    await session.flush()
    result = await apply_blocked(session, task, None, "тест 2",
                                 subject_kind="auto", rule_code="AUTO_BLOCK")
    await session.commit()
    assert result.status_key == "blocked"
    rows = (await session.execute(
        sa.select(Chronicle).where(Chronicle.task_id == task.id,
                                   Chronicle.rule_code == "AUTO_BLOCK"))).scalars().all()
    assert rows
    await session.rollback()
