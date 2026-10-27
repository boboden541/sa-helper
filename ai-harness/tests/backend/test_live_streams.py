"""Живые данные интерфейса (решение владельца 27.10.2026): снапшот активности,
токены в выдаче задач, прирост хроники по watermark."""

from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from repository.models import Task, TaskRun, User
from usecase.journal.live import activity_snapshot, chronicle_after, task_activity


async def _mk_run(_test_db, code: str, tokens: tuple[int, int, int],
                  finished: bool = False) -> None:
    maker = async_sessionmaker(_test_db, expire_on_commit=False)
    async with maker() as s:
        task = (await s.execute(
            sa.select(Task).where(Task.code == code))).scalar_one()
        agent = (await s.execute(
            sa.select(User).where(User.user_type == "agent"))).scalars().first()
        s.add(TaskRun(task_id=task.id, agent_id=agent.id, status_key=task.status_key,
                      input_tokens=tokens[0], output_tokens=tokens[1],
                      cache_tokens=tokens[2],
                      finished_at=dt.datetime.now(dt.timezone.utc) if finished else None))
        await s.commit()


async def _clean(_test_db) -> None:
    async with async_sessionmaker(_test_db, expire_on_commit=False)() as s:
        await s.execute(sa.text(
            "TRUNCATE task, task_run, task_tag, tag, chronicle, notification, "
            "task_relation RESTART IDENTITY CASCADE"))
        await s.execute(sa.text("UPDATE project SET next_number = 1"))
        await s.commit()


async def _mk_task(client, title="Живая задача") -> str:
    r = await client.post("/api/v1/tasks", json={
        "projectId": "AH", "type": "common_task", "title": title,
        "priority": "high", "authorTag": "by_human"})
    assert r.status_code == 200, r.text
    return r.json()["code"]


async def test_activity_snapshot_and_task_activity(client, _test_db):
    await _clean(_test_db)
    code = await _mk_task(client)
    await _mk_run(_test_db, code, (1200000, 80000, 20000))
    maker = async_sessionmaker(_test_db, expire_on_commit=False)
    async with maker() as s:
        task = (await s.execute(sa.select(Task).where(Task.code == code))).scalar_one()
        snap = await activity_snapshot(s)
        assert [x["code"] for x in snap] == [code]
        item = snap[0]
        assert item["total"] == 1300000 and item["minutes"] >= 0
        assert item["stale"] is False and item["agent"]
        act = await task_activity(s, task.id)
        assert act is not None and act["total"] == 1300000 and act["runId"]


async def test_finished_run_not_in_snapshot(client, _test_db):
    await _clean(_test_db)
    code = await _mk_task(client)
    await _mk_run(_test_db, code, (10, 20, 30), finished=True)
    maker = async_sessionmaker(_test_db, expire_on_commit=False)
    async with maker() as s:
        assert await activity_snapshot(s) == []


async def test_chronicle_after_watermark(client, _test_db):
    await _clean(_test_db)
    code = await _mk_task(client)
    maker = async_sessionmaker(_test_db, expire_on_commit=False)
    async with maker() as s:
        task = (await s.execute(sa.select(Task).where(Task.code == code))).scalar_one()
        after = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=5)
        seen: set[str] = set()
        items, after = await chronicle_after(s, task.id, after, seen)
        assert items, "создание задачи пишется в хронику"
        ids = {i["id"] for i in items}
        items2, _ = await chronicle_after(s, task.id, after, seen)
        assert items2 == [], "без новых записей прироста нет (seen отсекает повторы)"
        from repository.models import Chronicle

        s.add(Chronicle(task_id=task.id, event_type="agent", author_kind="agent",
                        message="живая запись"))
        await s.commit()
        items3, _ = await chronicle_after(s, task.id, after, seen)
        assert len(items3) == 1 and items3[0]["message"] == "живая запись"
        assert not (ids & {i["id"] for i in items3})


async def test_tokens_used_in_task_list(client, _test_db):
    await _clean(_test_db)
    code = await _mk_task(client)
    await _mk_run(_test_db, code, (1000, 500, 0), finished=True)
    await _mk_run(_test_db, code, (300, 200, 100))
    r = await client.get("/api/v1/tasks", params={"q": code})
    assert r.status_code == 200, r.text
    card = next(c for c in r.json()["items"] if c["code"] == code)
    assert card["tokensUsed"] == 2100, "сумма токенов всех прогонов задачи"
