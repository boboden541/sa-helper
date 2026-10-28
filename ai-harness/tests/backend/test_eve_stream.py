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
