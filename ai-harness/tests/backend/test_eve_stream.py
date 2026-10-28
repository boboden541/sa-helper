"""SSE-стриминг ответа Eve (решение владельца 28.10.2026): детерминированные
ветки отвечают событием done; формат — data: {json}."""


async def test_stream_done_event(client, _test_db):
    r = await client.post("/api/v1/tasks", json={
        "projectId": "AH", "type": "common_task", "title": "Стрим-задача",
        "priority": "medium", "authorTag": "by_human"})
    code = r.json()["code"]
    r = await client.post("/api/v1/assistant/messages/stream",
                          json={"text": f"что с задачей {code}?"})
    assert r.status_code == 200, r.text
    assert "text/event-stream" in r.headers.get("content-type", "")
    assert "data:" in r.text, "ответ должен быть SSE-потоком"
    assert '"type": "done"' in r.text.replace("done", "done") or '"type":"done"' in r.text
    assert code in r.text, "дайджест задачи должен попасть в итоговое событие"


async def test_stream_intent_confirm(client, _test_db):
    r = await client.post("/api/v1/tasks", json={
        "projectId": "AH", "type": "common_task", "title": "Задача на перевод",
        "priority": "medium", "authorTag": "by_human"})
    code = r.json()["code"]
    r = await client.post("/api/v1/assistant/messages/stream",
                          json={"text": f"переведи {code} на ревью"})
    assert r.status_code == 200
    assert "confirm" in r.text, "изменяющее действие требует подтверждения"
    r2 = await client.post("/api/v1/assistant/messages/stream", json={"text": "да"})
    assert '"reply"' in r2.text


async def test_agent_session_and_abort_registry(client, _test_db):
    """Реестр стоп-кнопки: register/request; сессионный ключ — на пользователя."""
    from usecase.assistant import eve_agent

    eve_agent.register_turn('turn-1')
    assert eve_agent.request_abort('turn-1') is True
    assert eve_agent.request_abort('turn-1') is True  # повторный — не падает
    assert eve_agent.request_abort('нет такого') is False

    import sqlalchemy as sa
    from database import get_sessionmaker
    from repository.models import User

    maker = get_sessionmaker()
    async with maker() as s:
        uid = (await s.execute(sa.select(User.id).where(User.name == "Алексей"))).scalar_one()
        await eve_agent._save_session_id(s, type('U', (), {'id': uid})(), 'sess-abc')
        await s.commit()
    async with maker() as s:
        uid = (await s.execute(sa.select(User.id).where(User.name == "Алексей"))).scalar_one()
        assert await eve_agent._load_session_id(s, type('U', (), {'id': uid})()) == 'sess-abc'
