"""«ПСИ устарел» — контур управления изменениями требований (УИТ, 03.11.2026).

Ставка: смена постановки (описание истории, добавление дочерней задачи) при
составленном документе. Снятие: новая версия документа / ручная актуализация.
"""

from __future__ import annotations

import sqlalchemy as sa
from repository.models import Chronicle, PsiDocument, Task


async def _mk_story(client, **kw) -> str:
    payload = {"projectId": "AH", "type": "story", "title": "История УИТ",
               "priority": "high", "authorTag": "by_human"}
    payload.update(kw)
    r = await client.post("/api/v1/tasks", json=payload)
    assert r.status_code == 200, r.text
    return r.json()["code"]


async def _mk_psi(client, code: str) -> int:
    r = await client.post(f"/api/v1/stories/{code}/psi", json={
        "sections": [{"heading": "Г1. Проверки",
                      "items": [{"action": "Открыть доску",
                                 "expected": "Доска открылась"}]}]})
    assert r.status_code == 200, r.text
    return r.json()["version"]


async def _stale(client, code: str) -> bool:
    r = await client.get(f"/api/v1/stories/{code}/psi")
    return bool(r.json().get("stale"))


async def test_child_addition_makes_psi_stale(client):
    code = await _mk_story(client)
    await _mk_psi(client, code)
    assert not await _stale(client, code)
    r = await client.post("/api/v1/tasks", json={
        "projectId": "AH", "type": "common_task", "title": "Новый ребёнок",
        "priority": "medium", "authorTag": "by_human", "storyCode": code})
    assert r.status_code == 200, r.text
    assert await _stale(client, code), "добавление ребёнка делает ПСИ устаревшим"


async def test_description_change_makes_psi_stale(client):
    code = await _mk_story(client)
    await _mk_psi(client, code)
    r = await client.patch(f"/api/v1/tasks/{code}", json={
        "descriptionMd": "Расширенная постановка: новый функционал"})
    assert r.status_code == 200, r.text
    assert await _stale(client, code), "правка описания делает ПСИ устаревшим"


async def test_new_version_clears_stale(client):
    code = await _mk_story(client)
    await _mk_psi(client, code)
    r = await client.post("/api/v1/tasks", json={
        "projectId": "AH", "type": "common_task", "title": "Ещё ребёнок",
        "priority": "medium", "authorTag": "by_human", "storyCode": code})
    assert r.status_code == 200, r.text
    assert await _stale(client, code)
    await _mk_psi(client, code)  # v2 — актуализация
    assert not await _stale(client, code), "новая версия снимает отметку"


async def test_no_doc_no_stale(client):
    code = await _mk_story(client)
    r = await client.post("/api/v1/tasks", json={
        "projectId": "AH", "type": "common_task", "title": "Ребёнок без ПСИ",
        "priority": "medium", "authorTag": "by_human", "storyCode": code})
    assert r.status_code == 200, r.text
    assert not await _stale(client, code), "без документа отметки нет"


async def test_actualize_endpoint_and_non_story(client):
    code = await _mk_story(client)
    await _mk_psi(client, code)
    r = await client.post(f"/api/v1/stories/{code}/psi/actualize", json={})
    assert r.status_code == 200 and r.json()["stale"] is True, r.text
    # не-история → 400
    r2 = await client.post("/api/v1/tasks", json={
        "projectId": "AH", "type": "common_task", "title": "Не история",
        "priority": "medium", "authorTag": "by_human"})
    code2 = r2.json()["code"]
    r3 = await client.post(f"/api/v1/stories/{code2}/psi/actualize", json={})
    assert r3.status_code == 400, r3.text
