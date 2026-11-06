"""Поэтапная отметка пунктов ПСИ (решение владельца 04.11.2026): вердикт сразу
в БД — переживает обрыв сессии, гейт M6 и карточка видят живую картину."""

from __future__ import annotations

import sqlalchemy as sa

SECTIONS = [
    {
        "heading": "Г1. Проверки входа",
        "items": [
            {"action": "Открыть список", "expected": "Список открывается"},
            {"action": "Создать запись", "expected": "Запись создана"},
        ],
    },
    {
        "heading": "Г2. Проверки выхода",
        "items": [{"action": "Удалить запись", "expected": "Запись удалена"}],
    },
]


async def _mk(client) -> str:
    r = await client.post(
        "/api/v1/tasks",
        json={
            "projectId": "AH",
            "type": "story",
            "title": "Поэтапный ПСИ",
            "priority": "medium",
            "authorTag": "by_human",
        },
    )
    assert r.status_code == 200, r.text
    code = r.json()["code"]
    r = await client.post(f"/api/v1/stories/{code}/psi", json={"sections": SECTIONS})
    assert r.status_code == 200, r.text
    return code


async def test_mark_item(client, _test_db):
    code = await _mk(client)
    r = await client.post(
        f"/api/v1/stories/{code}/psi/items",
        json={"position": 1, "passed": True, "actual": "список открылся"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"position": 1, "status": "done", "passed": True}

    r = await client.post(
        f"/api/v1/stories/{code}/psi/items",
        json={"position": 2, "passed": False, "actual": "запись не создалась"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"position": 2, "status": "failed", "passed": False}

    # документная нумерация П.N: счёт ТОЛЬКО по пунктам — П.3 («Удалить запись»)
    # живёт на чеклист-position 4 (заголовок Г2 занимает позицию 3) и раньше
    # был недостижим по номеру документа (анализ 06.11: молча чужой пункт)
    r = await client.post(
        f"/api/v1/stories/{code}/psi/items",
        json={"position": 3, "passed": False, "actual": "запись не удалилась"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"position": 3, "status": "failed", "passed": False}

    # пунктов всего 3 → П.4 не существует
    r = await client.post(
        f"/api/v1/stories/{code}/psi/items",
        json={"position": 4, "passed": True, "actual": ""},
    )
    assert r.status_code == 400, r.text
    assert "П.4" in r.json().get("message", "")

    r = await client.get(f"/api/v1/stories/{code}/psi")
    items = {i["position"]: i for i in r.json()["items"] if i["kind"] == "item"}
    assert items[1]["status"] == "done" and items[1]["actual"] == "список открылся"
    assert items[2]["status"] == "failed" and "не создалась" in items[2]["actual"]
    assert items[4]["status"] == "failed" and "не удалилась" in items[4]["actual"]

    async with __import__("database").get_sessionmaker()() as s:
        rows = (
            (await s.execute(sa.text("SELECT message FROM chronicle WHERE event_type='psi'")))
            .scalars()
            .all()
        )
    fails = [m for m in rows if "НЕ ПРОЙДЕН" in m]
    assert fails == [
        "Пункт П.2 ПСИ НЕ ПРОЙДЕН: запись не создалась",
        "Пункт П.3 ПСИ НЕ ПРОЙДЕН: запись не удалилась",
    ], fails


async def test_mark_item_unknown_position(client):
    code = await _mk(client)
    r = await client.post(
        f"/api/v1/stories/{code}/psi/items",
        json={"position": 99, "passed": True, "actual": ""},
    )
    assert r.status_code == 400, r.text
    assert "П.99" in r.json().get("message", "")
