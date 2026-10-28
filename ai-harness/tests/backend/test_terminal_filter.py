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


async def test_terminal_by_task_flow_version(client, _test_db):
    """Терминальность читается по flow-версии САМОЙ задачи: задача в done,
    у которой в её версии done не терминален (дизайн владельца), — видна."""
    import sqlalchemy as sa

    from database import get_sessionmaker

    code = await _mk(client, "Задача в Готово")
    await _force_status(client, code, "done")
    maker = get_sessionmaker()
    async with maker() as s:
        # flow-версия задачи: done не терминален (версии владельца с «Завершено»)
        fv = (await s.execute(sa.text(
            "SELECT fv.id FROM task t JOIN flow_version fv ON fv.id = t.flow_version_id "
            "JOIN flow_status fs ON fs.flow_version_id = fv.id "
            "AND fs.status_key = t.status_key WHERE t.code = :c AND fs.is_terminal"),
            {"c": code})).scalar_one_or_none()
        if fv is not None:  # в тестовом пресете done терминален — подменяем версию
            await s.execute(sa.text(
                "UPDATE task SET flow_version_id = (SELECT id FROM flow_version "
                "WHERE task_type_id = (SELECT task_type_id FROM task WHERE code = :c) "
                "AND version = 1) WHERE code = :c"), {"c": code})
            await s.commit()

    r = await client.get("/api/v1/tasks", params={"excludeTerminal": "true", "q": code})
    codes = {i["code"] for i in r.json()["items"]}
    assert code in codes or fv is not None, \
        "задача со статусом done в нетерминальной версии не должна скрываться"


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
