"""Фильтр exclude_terminal (решение владельца 28.10.2026): доска без
терминальных статусов, список — целиком; терминальность по flow-версии задачи."""


async def _mk(client, title: str, type_: str = "common_task") -> str:
    r = await client.post("/api/v1/tasks", json={
        "projectId": "AH", "type": type_, "title": title,
        "priority": "medium", "authorTag": "by_human"})
    assert r.status_code == 200, r.text
    return r.json()["code"]


async def _force_status(client, code: str, status: str) -> None:
    import sqlalchemy as sa

    from database import get_sessionmaker

    # прямой UPDATE: терминальные статусы недостижимы движком без гейтов
    maker = get_sessionmaker()
    async with maker() as s:
        await s.execute(sa.text(
            "UPDATE task SET status_key = :st WHERE code = :c"),
            {"st": status, "c": code})
        await s.commit()


async def test_exclude_terminal_split(client, _test_db):
    code_open = await _mk(client, "Открытая задача")
    code_done = await _mk(client, "Завершённая задача")
    code_canceled = await _mk(client, "Отменённая задача")
    await _force_status(client, code_done, "done")
    await _force_status(client, code_canceled, "canceled")

    r = await client.get("/api/v1/tasks", params={"excludeTerminal": "true", "q": "задача"})
    assert r.status_code == 200, r.text
    codes = {i["code"] for i in r.json()["items"]}
    assert code_open in codes, "открытая задача видна"
    assert code_done not in codes and code_canceled not in codes, \
        "терминальные (done/canceled) скрыты"

    r = await client.get("/api/v1/tasks", params={"q": "задача"})
    codes = {i["code"] for i in r.json()["items"]}
    assert {code_open, code_done, code_canceled} <= codes, "без параметра видны все"


async def test_terminal_always_by_current_version(client, _test_db):
    """Решение владельца 28.10.2026: терминальность — всегда по АКТУАЛЬНОЙ
    версии flow типа задачи, даже если задача приколота к старой версии,
    где её статус был нетерминальным."""
    import sqlalchemy as sa

    from database import get_sessionmaker

    code = await _mk(client, "Задача в Готово")
    await _force_status(client, code, "done")
    maker = get_sessionmaker()
    async with maker() as s:
        # прикалываем задачу к самой первой версии типа (done там мог быть
        # нетерминальным) — фильтр всё равно читает АКТУАЛЬНУЮ версию
        await s.execute(sa.text(
            "UPDATE task SET flow_version_id = (SELECT fv.id FROM flow_version fv "
            "JOIN task_type tt ON tt.id = fv.task_type_id "
            "WHERE tt.key = 'common_task' ORDER BY fv.version LIMIT 1) "
            "WHERE code = :c"), {"c": code})
        await s.commit()

    r = await client.get("/api/v1/tasks", params={"excludeTerminal": "true", "q": code})
    codes = {i["code"] for i in r.json()["items"]}
    assert code not in codes, \
        "done скрыт по актуальной версии flow независимо от версии задачи"


async def test_list_returns_story_code(client, _test_db):
    """Доска группирует задачи в полосы по storyCode из выдачи списка (ФТ-ah-16) —
    поле должно заполняться всегда, иначе задачи «теряют» историю (баг 28.10.2026)."""
    story = await _mk(client, "История для группировки", type_="story")
    task = await _mk(client, "Задача в истории")
    r = await client.post(f"/api/v1/tasks/{task}/story-link",
                          json={"storyCode": story})
    assert r.status_code == 200, r.text
    r = await client.get("/api/v1/tasks", params={"q": task})
    items = r.json()["items"]
    assert items and items[0]["storyCode"] == story, \
        "storyCode в выдаче списка обязателен для группировки на доске"
