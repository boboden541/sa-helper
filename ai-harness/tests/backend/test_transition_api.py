"""Контракт API переходов (СТ §4.2.1): коды 200/400/404, applied/reason, карточка с gate."""

from __future__ import annotations

import sqlalchemy as sa

from repository.models import Task


async def _mk_task(client, **kw):
    payload = {"projectId": "AH", "type": "common_task", "title": "API переход",
               "priority": "high", "authorTag": "by_human"}
    payload.update(kw)
    r = await client.post("/api/v1/tasks", json=payload)
    assert r.status_code == 200, r.text
    return r.json()["code"]


async def _status(session, code, status):
    await session.execute(sa.update(Task).where(Task.code == code).values(status_key=status))
    await session.commit()


async def test_transition_unknown_task_404(client):
    r = await client.post("/api/v1/tasks/NOPE-9/transitions", json={"to": "todo"})
    assert r.status_code == 404


async def test_transition_unknown_edge_400(client):
    code = await _mk_task(client)  # pending
    r = await client.post(f"/api/v1/tasks/{code}/transitions", json={"to": "done"})
    assert r.status_code == 400


async def test_transition_gate_denial_200_applied_false(client, session):
    """Гейт не пускает: HTTP 200, applied=false, человекочитаемая причина."""
    code = await _mk_task(client)
    await _status(session, code, "todo")
    r = await client.post(f"/api/v1/tasks/{code}/transitions", json={"to": "in_progress"})
    assert r.status_code == 200
    body = r.json()
    assert body["applied"] is False and "не создан" in body["reason"]


async def test_force_empty_reason_400(client, session):
    code = await _mk_task(client)
    await _status(session, code, "done")
    r = await client.post(f"/api/v1/tasks/{code}/force", json={"to": "todo", "reason": ""})
    assert r.status_code == 400
    r = await client.post(f"/api/v1/tasks/{code}/force",
                          json={"to": "todo", "reason": "разблокируем по решению владельца"})
    assert r.status_code == 200 and r.json()["applied"] is True


async def test_card_contains_gate_decisions(client, session):
    code = await _mk_task(client)  # pending
    r = await client.get(f"/api/v1/tasks/{code}")
    assert r.status_code == 200
    gate = r.json()["gate"]
    assert "todo" in gate["allowed"]  # пресет без бэклога: pending → todo (решение владельца 29.10.2026)
    assert any(d["to"] == "canceled" for d in gate["denied"]) is False
    # pending → canceled разрешён человеку
    assert any("canceled" in a for a in gate["allowed"])


async def test_card_tokens_breakdown(client, session):
    """Разбивка токенов в карточке: вход/выход/кэш суммируются по прогонам
    (фича 30.10.2026 — клик по цифре раскрывает составляющие)."""
    import sqlalchemy as sa

    code = await _mk_task(client)
    task_id = (await session.execute(
        sa.text("SELECT id FROM task WHERE code = :c"), {"c": code})).scalar_one()
    for i, (tin, tout, tcache) in enumerate([(100, 20, 50), (30, 10, 5)]):
        await session.execute(sa.text(
            "INSERT INTO task_run (id, task_id, agent_id, status_key, attempt_no, "
            "input_tokens, output_tokens, cache_tokens) "
            "SELECT gen_random_uuid(), :t, u.id, 'in_progress', :n, :i, :o, :c "
            "FROM \"user\" u WHERE u.user_type = 'agent' LIMIT 1"),
            {"t": str(task_id), "n": i + 1, "i": tin, "o": tout, "c": tcache})
        # частичный UNIQUE «один активный прогон на задачу+агента»: закрываем
        # предыдущий, чтобы вставить следующий
        if i == 0:
            await session.execute(sa.text(
                "UPDATE task_run SET finished_at = now(), outcome = 'failed' "
                "WHERE task_id = :t"), {"t": str(task_id)})
    await session.commit()

    card = (await client.get(f"/api/v1/tasks/{code}")).json()
    assert card["tokensUsed"] == 100 + 20 + 50 + 30 + 10 + 5
    assert card["tokensInput"] == 130
    assert card["tokensOutput"] == 30
    assert card["tokensCache"] == 55


async def test_list_tokens_breakdown(client, session):
    """Разбивка доходит и через список задач (доска/список показывают её по клику)."""
    import sqlalchemy as sa

    code = await _mk_task(client)
    task_id = (await session.execute(
        sa.text("SELECT id FROM task WHERE code = :c"), {"c": code})).scalar_one()
    await session.execute(sa.text(
        "INSERT INTO task_run (id, task_id, agent_id, status_key, attempt_no, "
        "input_tokens, output_tokens, cache_tokens, finished_at, outcome) "
        "SELECT gen_random_uuid(), :t, u.id, 'in_progress', 1, 10, 2, 3, now(), 'failed' "
        "FROM \"user\" u WHERE u.user_type = 'agent' LIMIT 1"), {"t": str(task_id)})
    await session.commit()

    items = (await client.get("/api/v1/tasks?limit=50")).json()["items"]
    row = next(i for i in items if i["code"] == code)
    assert row["tokensUsed"] == 15
    assert (row["tokensInput"], row["tokensOutput"], row["tokensCache"]) == (10, 2, 3)
