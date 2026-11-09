"""ФНР-15: карта покрытия, carry-forward, ревизия «ПСИ-редактора», слияние без репо."""

from __future__ import annotations

import sqlalchemy as sa

SECTIONS_V1 = [
    {
        "heading": "Г1. Импорт",
        "items": [
            {"action": "Импорт пакета", "expected": "Черновики созданы", "taskCode": None},
        ],
    }
]


async def _mk_story_with_child(client) -> tuple[str, str]:
    r = await client.post(
        "/api/v1/tasks",
        json={
            "projectId": "AH",
            "type": "story",
            "title": "ФНР-15",
            "priority": "medium",
            "authorTag": "by_human",
        },
    )
    assert r.status_code == 200, r.text
    story = r.json()["code"]
    r = await client.post(
        "/api/v1/tasks",
        json={
            "projectId": "AH",
            "type": "common_task",
            "title": "Ребёнок",
            "priority": "medium",
            "authorTag": "by_human",
            "storyCode": story,
        },
    )
    assert r.status_code == 200, r.text
    return story, r.json()["code"]


async def test_taskcode_and_carry_forward(client, _test_db):
    """ФТ-01/03: taskCode даёт linked_task_id; дельта-регистрация переносит
    нетронутые пункты (carried_from_version) и сбрасывает вердикты."""
    story, child = await _mk_story_with_child(client)

    async with __import__("database").get_sessionmaker()() as s:
        child_id = (
            await s.execute(sa.text("SELECT id FROM task WHERE code=:c"), {"c": child})
        ).scalar_one()

    # v1: полный документ со связями
    sections_v1 = [
        {
            "heading": "Г1",
            "items": [
                {"action": "Пункт про ребёнка", "expected": "Ок", "taskCode": child},
                {"action": "Общий пункт", "expected": "Ок"},
            ],
        },
    ]
    r = await client.post(f"/api/v1/stories/{story}/psi", json={"sections": sections_v1})
    assert r.status_code == 200, r.text

    async with __import__("database").get_sessionmaker()() as s:
        rows = (
            await s.execute(
                sa.text(
                    "SELECT position, text, linked_task_id FROM checklist_item ci "
                    "JOIN checklist c ON c.id=ci.checklist_id JOIN task t ON t.id=c.task_id "
                    "WHERE t.code=:s AND c.kind='psi' AND ci.kind='item' ORDER BY position"
                ),
                {"s": story},
            )
        ).all()
    linked = [r for r in rows if r[2] is not None]
    assert linked and str(linked[0][2]) == str(child_id), "taskCode → linked_task_id"

    # v2: ДЕЛЬТА — только пункт про ребёнка (тот же taskCode)
    sections_v2 = [
        {
            "heading": "Г1 (переработка)",
            "items": [
                {"action": "Пункт про ребёнка v2", "expected": "Ок v2", "taskCode": child},
            ],
        },
    ]
    r = await client.post(f"/api/v1/stories/{story}/psi", json={"sections": sections_v2})
    assert r.status_code == 200, r.text

    async with __import__("database").get_sessionmaker()() as s:
        rows = (
            await s.execute(
                sa.text(
                    "SELECT text, carried_from_version FROM checklist_item ci "
                    "JOIN checklist c ON c.id=ci.checklist_id JOIN task t ON t.id=c.task_id "
                    "WHERE t.code=:s AND c.kind='psi' AND ci.kind='item' ORDER BY position"
                ),
                {"s": story},
            )
        ).all()
    texts = [r[0] for r in rows]
    assert "Пункт про ребёнка v2" in texts, "дельта-пункт заменён"
    assert "Общий пункт" in texts, "нетронутый пункт перенесён (carry-forward)"
    carried = [r for r in rows if r[0] == "Общий пункт"]
    assert carried[0][1] == 1, f"carried_from_version=1, стал {carried[0][1]}"

    # taskCode вне истории → 400
    r = await client.post(
        "/api/v1/tasks",
        json={
            "projectId": "AH",
            "type": "common_task",
            "title": "Чужой",
            "priority": "medium",
            "authorTag": "by_human",
        },
    )
    outsider = r.json()["code"]
    r = await client.post(
        f"/api/v1/stories/{story}/psi",
        json={
            "sections": [
                {"heading": "Г", "items": [{"action": "x", "expected": "y", "taskCode": outsider}]}
            ]
        },
    )
    assert r.status_code == 400, r.text
    assert "не является задачей/багом истории" in r.json().get("message", "")


async def test_link_task_endpoint(client, _test_db):
    """ФТ-FNR15-01.3: POST /psi/link-task идемпотентен, 400 на чужой задаче."""
    story, child = await _mk_story_with_child(client)
    r = await client.post(
        f"/api/v1/stories/{story}/psi",
        json={"sections": [{"heading": "Г", "items": [{"action": "Шаг", "expected": "Ок"}]}]},
    )
    assert r.status_code == 200
    r = await client.post(
        f"/api/v1/stories/{story}/psi/link-task", json={"position": 1, "taskCode": child}
    )
    assert r.status_code == 200, r.text
    assert r.json()["linkedTaskCode"] == child
    r = await client.post(
        f"/api/v1/stories/{story}/psi/link-task", json={"position": 1, "taskCode": child}
    )
    assert r.status_code == 200, "идемпотентность"
    r = await client.post(
        f"/api/v1/stories/{story}/psi/link-task", json={"position": 99, "taskCode": child}
    )
    assert r.status_code == 400, r.text


async def test_manager_review_verdict(client, _test_db):
    """ФТ-FNR15-08: вердикт редактора — approved/rejected в чеклисте, хроника."""
    story, _child = await _mk_story_with_child(client)
    r = await client.post(
        f"/api/v1/stories/{story}/psi",
        json={"sections": [{"heading": "Г", "items": [{"action": "Шаг", "expected": "Ок"}]}]},
    )
    assert r.status_code == 200
    r = await client.post(
        f"/api/v1/stories/{story}/psi/review",
        json={"verdict": False, "note": "П.1: не сказано, где выполнять"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"version": 1, "state": "rejected"}

    async with __import__("database").get_sessionmaker()() as s:
        state, ver = (
            await s.execute(
                sa.text(
                    "SELECT c.manager_review_state, c.manager_review_version "
                    "FROM checklist c JOIN task t ON t.id=c.task_id "
                    "WHERE t.code=:s AND c.kind='psi'"
                ),
                {"s": story},
            )
        ).one()
    assert state == "rejected" and ver == 1

    r = await client.post(f"/api/v1/stories/{story}/psi/review", json={"verdict": True, "note": ""})
    assert r.json()["state"] == "approved"


async def test_merge_skip_non_repo_root(_test_db, tmp_path):
    """ФТ-FNR15-09 сценарий А: не-git корень — слияние пропускается без отказа."""
    import os
    from types import SimpleNamespace

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from daemon.scheduler.scheduler import Daemon

    eng = create_async_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with async_sessionmaker(eng)() as s:
            await s.execute(
                sa.text("UPDATE project SET path = :p WHERE mnemonic='AH'"), {"p": str(tmp_path)}
            )
            await s.execute(
                sa.text(
                    "INSERT INTO task (id, project_id, code, task_type_id, title, "
                    "description_md, status_key, flow_version_id, priority, author_id) "
                    "SELECT gen_random_uuid(), p.id, 'AH-1', tt.id, 'Merge-skip', '', "
                    "'done', fv.id, 'medium', u.id "
                    'FROM project p, task_type tt, flow_version fv, "user" u '
                    "WHERE p.mnemonic='AH' AND tt.key='common_task' "
                    "AND fv.task_type_id = tt.id AND fv.is_current AND fv.is_published "
                    "AND u.name='Алексей'"
                )
            )
            await s.commit()
            row = (
                await s.execute(sa.text("SELECT id, project_id FROM task WHERE code='AH-1'"))
            ).first()
            task_stub = SimpleNamespace(
                id=row.id, project_id=row.project_id, repo_path=None, code="AH-1", psi_path=None
            )
            from daemon.runner.agent_runner import FakeRunner

            daemon = Daemon(async_sessionmaker(eng, expire_on_commit=False), FakeRunner())
            await daemon._merge_before_done(s, task_stub)
            chron = (
                await s.execute(
                    sa.text(
                        "SELECT count(*) FROM chronicle WHERE task_id=:i "
                        "AND message LIKE '%не git-репозиторий%'"
                    ),
                    {"i": str(row.id)},
                )
            ).scalar_one()
            assert chron == 1, "хроника «слияние не требуется» записана"
    finally:
        await eng.dispose()


async def test_doc_numbering_consistent_across_surfaces(client, _test_db):
    """Анализ 09.11.2026: номер П.N един на всех поверхностях ПСИ — psi.md,
    /psi/items, /psi/runs, /psi/link-task, get_document (docNumber) — и в
    многосекционном документе, где чеклист-позиция расходится с номером."""
    story, child = await _mk_story_with_child(client)
    r = await client.post(
        "/api/v1/tasks",
        json={
            "projectId": "AH",
            "type": "common_task",
            "title": "Второй ребёнок",
            "priority": "medium",
            "authorTag": "by_human",
            "storyCode": story,
        },
    )
    assert r.status_code == 200
    child2 = r.json()["code"]

    sections = [
        {
            "heading": "Г1",
            "items": [
                {"action": "Пункт один", "expected": "Ок", "taskCode": child},
                {"action": "Пункт два", "expected": "Ок"},
            ],
        },
        {"heading": "Г2", "items": [{"action": "Пункт три", "expected": "Ок"}]},
    ]
    r = await client.post(f"/api/v1/stories/{story}/psi", json={"sections": sections})
    assert r.status_code == 200, r.text

    r = await client.get(f"/api/v1/stories/{story}/psi")
    numbered = [i for i in r.json()["items"] if i["kind"] == "item"]
    assert [i["docNumber"] for i in numbered] == [1, 2, 3]
    assert [i["position"] for i in numbered] == [1, 2, 4]  # позиция 3 — заголовок Г2

    # карта покрытия по П.N: П.3 → второй ребёнок; в БД связь ляжет на позицию 4
    r = await client.post(
        f"/api/v1/stories/{story}/psi/link-task", json={"position": 3, "taskCode": child2}
    )
    assert r.status_code == 200, r.text
    async with __import__("database").get_sessionmaker()() as s:
        rows = (
            await s.execute(
                sa.text(
                    "SELECT ci.position, lt.code FROM checklist_item ci "
                    "JOIN checklist c ON c.id=ci.checklist_id "
                    "JOIN task t ON t.id=c.task_id "
                    "JOIN task lt ON lt.id=ci.linked_task_id "
                    "WHERE t.code=:s AND c.kind='psi' AND ci.kind='item' "
                    "AND ci.linked_task_id IS NOT NULL"
                ),
                {"s": story},
            )
        ).all()
    assert (4, child2) in [(x[0], x[1]) for x in rows], "П.3 → чеклист-позиция 4"

    # прогон по П.N: П.3 → failed на чеклист-позиции 4
    r = await client.post(
        f"/api/v1/stories/{story}/psi/runs",
        json={"results": [{"position": 3, "passed": False, "actual": "упало"}]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["failed"] == 1
    r = await client.get(f"/api/v1/stories/{story}/psi")
    items = {i["position"]: i for i in r.json()["items"]}
    assert items[4]["status"] == "failed" and items[4]["actual"] == "упало"

    # неизвестный номер — честный 400 вместо молчаливого пропуска
    r = await client.post(
        f"/api/v1/stories/{story}/psi/runs",
        json={"results": [{"position": 9, "passed": True, "actual": ""}]},
    )
    assert r.status_code == 400, r.text
    assert "П.9" in r.json()["message"]
