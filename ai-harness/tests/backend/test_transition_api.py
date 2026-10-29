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
