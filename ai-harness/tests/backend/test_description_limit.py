"""Лимит описания 150 000 (решение владельца 03.11.2026, было 20 000).

Инцидент VITRINA-1: полная постановка СТ (77 854 симв.) не помещалась в поле
и хранилась обходным путём — запись «[doc] СТ (полный текст)» в хронике.
"""

from __future__ import annotations


async def _mk_task(client) -> str:
    r = await client.post(
        "/api/v1/tasks",
        json={
            "projectId": "AH",
            "type": "common_task",
            "title": "Лимит описания",
            "priority": "medium",
            "authorTag": "by_human",
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["code"]


async def test_full_spec_size_fits(client):
    """Реальный размер постановки VITRINA-1 (77 854) проходит."""
    code = await _mk_task(client)
    body = "# [СТ] Постановка\n\n" + ("| строка таблицы требований с деталями |\n" * 3000)
    assert len(body) > 70000
    r = await client.patch(f"/api/v1/tasks/{code}", json={"descriptionMd": body})
    assert r.status_code == 200, r.text


async def test_over_limit_rejected(client):
    code = await _mk_task(client)
    body = "x" * 150001
    r = await client.patch(f"/api/v1/tasks/{code}", json={"descriptionMd": body})
    assert r.status_code == 400, r.text
    assert "150 000" in r.text
