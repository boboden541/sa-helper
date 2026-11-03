"""Версионирование эталона постановки (решение владельца 03.11.2026).

Эталон = описание из БД harness: ref_version/ref_hash на задаче, заверка плана
source_ref_version на чеклисте. План устарел ⟺ stamp < ref_version.
Булев psi_stale полностью заменён.
"""

from __future__ import annotations

import sqlalchemy as sa
from repository.models import Checklist, Chronicle, Task


async def _mk_story(client, **kw) -> str:
    payload = {"projectId": "AH", "type": "story", "title": "История эталона",
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


async def _doc(client, code: str) -> dict:
    r = await client.get(f"/api/v1/stories/{code}/psi")
    return r.json()


async def _task(session, code: str) -> Task:
    session.expire_all()  # PATCH шёл через другое соединение — сбросить identity-map
    return (await session.execute(sa.select(Task).where(Task.code == code))).scalar_one()


async def test_description_change_bumps_version_and_hash(client, session):
    code = await _mk_story(client)
    before = await _task(session, code)
    v0 = before.ref_version
    r = await client.patch(f"/api/v1/tasks/{code}", json={"descriptionMd": "Новая постановка"})
    assert r.status_code == 200, r.text
    after = await _task(session, code)
    assert after.ref_version == v0 + 1
    assert after.ref_hash is not None and len(after.ref_hash) == 64
    events = (await session.execute(sa.select(Chronicle.message).where(
        Chronicle.task_id == after.id, Chronicle.rule_code == "REF"))).scalars().all()
    assert any(f"v{v0 + 1}" in m for m in events), "событие эталона в хронике"


async def test_child_addition_and_edit_bump_story_version(client, session):
    code = await _mk_story(client)
    v0 = (await _task(session, code)).ref_version
    r = await client.post("/api/v1/tasks", json={
        "projectId": "AH", "type": "common_task", "title": "Ребёнок",
        "priority": "medium", "authorTag": "by_human", "storyCode": code})
    child_code = r.json()["code"]
    v1 = (await _task(session, code)).ref_version
    assert v1 == v0 + 1, "добавление ребёнка поднимает эталон истории"
    r2 = await client.patch(f"/api/v1/tasks/{child_code}", json={"descriptionMd": "Правка ребёнка"})
    assert r2.status_code == 200
    v2 = (await _task(session, code)).ref_version
    assert v2 == v1 + 1, "правка постановки ребёнка поднимает эталон истории"


async def test_plan_stale_computed_from_versions(client, session):
    code = await _mk_story(client)
    await _mk_psi(client, code)  # регистрация заверяет план текущей версией эталона
    d = await _doc(client, code)
    assert d["stale"] is False
    assert d["refVersion"] == d["planRefVersion"], "план заверен текущей версией"
    # эталон изменился → план устарел (без булевых флагов)
    await client.patch(f"/api/v1/tasks/{code}", json={"descriptionMd": "Расширенная постановка"})
    d2 = await _doc(client, code)
    assert d2["stale"] is True
    assert d2["planRefVersion"] < d2["refVersion"]
    # новая версия документа заверяет план заново
    await _mk_psi(client, code)
    d3 = await _doc(client, code)
    assert d3["stale"] is False


async def test_checklist_put_stamps_non_psi_only(client, session):
    code = await _mk_story(client)
    await client.patch(f"/api/v1/tasks/{code}", json={"descriptionMd": "Постановка v2"})
    ref = (await _task(session, code)).ref_version
    # developer-чеклист: пересмотр заверяет план текущей версией
    r = await client.put(f"/api/v1/tasks/{code}/checklists/developer",
                         json={"lines": "- пункт плана"})
    assert r.status_code == 200, r.text
    stamp = (await session.execute(sa.select(Checklist.source_ref_version).where(
        Checklist.task_id == (await _task(session, code)).id,
        Checklist.kind == "developer"))).scalar_one()
    assert stamp == ref, "PUT developer-чеклиста заверяет план"
    # psi-чеклист: PUT НЕ заверяет (только регистрация версии документа)
    r2 = await client.put(f"/api/v1/tasks/{code}/checklists/psi",
                          json={"lines": "# Г1\n- старый пункт"})
    assert r2.status_code == 200, r2.text
    psi_stamp = (await session.execute(sa.select(Checklist.source_ref_version).where(
        Checklist.task_id == (await _task(session, code)).id,
        Checklist.kind == "psi"))).scalar_one()
    assert psi_stamp is None, "PUT psi-чеклиста не заверяет план"
