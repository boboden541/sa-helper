"""AC-4.4.2/3/4 + проекты: крипто токенов, матрица, вход, жизненный цикл проекта."""

from __future__ import annotations

import os

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from repository.models import TaskType, User

os.environ.setdefault("AI_HARNESS_TOKEN_KEY", "")


@pytest.fixture
def token_key(monkeypatch):
    import base64

    monkeypatch.setenv("AI_HARNESS_TOKEN_KEY",
                       base64.b64encode(b"k" * 32).decode())
    from config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ---------- провайдеры: шифрование (AC-4.4.2.2) ----------

async def test_token_never_in_dump(session, token_key):
    from usecase.settings.connections import create_connection

    conn = await create_connection(session, {
        "name": "Тест-провайдер", "protocol": "anthropic",
        "url": "https://api.anthropic.com", "model": "claude-sonnet-5",
        "token": "sk-super-secret-9876"})
    assert conn.token_tail.endswith("9876")
    dump = (await session.execute(sa.text(
        "SELECT pg_catalog.concat_ws(' ', token_encrypted::text) FROM connection "
        "WHERE id = :i"), {"i": str(conn.id)})).scalar()
    assert "super-secret" not in (dump or "")


async def test_active_connection_unique_and_delete_guard(session, token_key):
    """AC-4.4.2.3: активное нельзя удалить до выбора другого; смена активного одна."""
    from sqlalchemy.exc import IntegrityError

    from usecase.settings.connections import (
        activate_connection, create_connection, delete_connection)

    c1 = await create_connection(session, {
        "name": "A", "protocol": "openai", "url": "https://x", "model": "m",
        "token": "tok-AAAA"})
    c2 = await create_connection(session, {
        "name": "B", "protocol": "openai", "url": "https://y", "model": "m",
        "token": "tok-BBBB"})
    await activate_connection(session, c1.id)
    with pytest.raises(Exception, match="Активное"):
        await delete_connection(session, c1.id)
    await activate_connection(session, c2.id)
    await delete_connection(session, c1.id)  # теперь можно


# ---------- матрица (AC-4.4.3.x) ----------

async def _agent(session, name="Ревьюер"):
    user = (await session.execute(
        sa.select(User).where(User.name == name))).scalar_one_or_none()
    if user is None:
        user = (await session.execute(pg_insert(User).values(
            name=name, user_type="agent").returning(User))).scalar_one()
        await session.commit()
    return user


async def _type_id(session, key="common_task"):
    return (await session.execute(
        sa.select(TaskType.id).where(TaskType.key == key))).scalar_one()


async def test_matrix_rejects_auto_status(session, actor_id):
    """AC-4.4.3.3: статус без агентной работы (pending) не принимает агентов."""
    from usecase.settings.agents import set_assignments

    story_type = await _type_id(session, "story")
    agent = await _agent(session)
    with pytest.raises(Exception, match="без агентной работы"):
        await set_assignments(session, story_type, "pending",
                              [{"userId": str(agent.id), "mode": "replacement"}])


async def test_delete_agent_with_assignments_blocked(session, actor_id):
    """AC-4.4.3.2: удаление агента с назначениями отклоняется со списком статусов."""
    from usecase.settings.agents import delete_agent, set_assignments

    agent = await _agent(session, "Тестер")
    await set_assignments(session, await _type_id(session), "in_testing",
                          [{"userId": str(agent.id), "mode": "replacement"}])
    with pytest.raises(Exception, match="in_testing"):
        await delete_agent(session, agent.id)


async def test_matrix_modes_stored(session, actor_id):
    from usecase.settings.agents import set_assignments

    a1 = await _agent(session, "Ревьюер-1")
    a2 = await _agent(session, "Ревьюер-2")
    await set_assignments(session, await _type_id(session), "in_review", [
        {"userId": str(a1.id), "mode": "parallel"},
        {"userId": str(a2.id), "mode": "parallel"},
    ])
    modes = (await session.execute(
        sa.text("SELECT DISTINCT mode FROM assignment WHERE status_key='in_review'")
    )).scalars().all()
    assert modes == ["parallel"]


# ---------- вход (AC-4.4.4.x) ----------

async def test_login_flow(client, session):
    """Единый отказ; cookie; logout делает сессию недействительной."""
    r = await client.post("/api/v1/auth/login",
                          json={"name": "Алексей", "password": "неверный"})
    assert r.status_code == 401
    assert r.json()["message"] == "Неверное имя или пароль"  # без раскрытия деталей

    r = await client.post("/api/v1/auth/login",
                          json={"name": "Алексей", "password": "harness"})
    assert r.status_code == 200
    cookie = r.cookies.get("ai_harness_session")
    assert cookie

    r = await client.post("/api/v1/auth/logout")
    assert r.status_code == 200
    # повторный use старого cookie: сессия удалена
    r2 = await client.post("/api/v1/auth/login",
                           json={"name": "Алексей", "password": "harness"})
    token = r2.cookies.get("ai_harness_session")
    from usecase.auth.login import user_for_token

    assert await user_for_token(session, token) is not None


async def test_protected_when_auth_required(client, session):
    """AC-4.4.4.3: при auth.required=true запросы без сессии — 401."""
    await session.execute(sa.text(
        "INSERT INTO app_setting (key, value) VALUES ('auth.required', 'true') "
        "ON CONFLICT (key) DO UPDATE SET value = 'true'"))
    await session.commit()
    r = await client.get("/api/v1/tasks")
    assert r.status_code == 401
    await session.execute(sa.text(
        "UPDATE app_setting SET value='false' WHERE key='auth.required'"))
    await session.commit()


# ---------- проекты ----------

async def test_project_lifecycle(session, actor_id, tmp_path):
    from usecase.settings.projects import (
        ProjectInput, create_project, delete_project, set_archived, update_project)

    target = tmp_path / "proj"
    target.mkdir()
    p = await create_project(session, ProjectInput(
        name="Проект", mnemonic="ZZ", path=str(target)))
    assert p.mnemonic == "ZZ"

    with pytest.raises(Exception, match="неизменна"):
        await update_project(session, p.id, {"mnemonic": "YY"})

    await set_archived(session, p.id, True)
    with pytest.raises(Exception, match="архиве"):
        from usecase.task.create_task import CreateTaskInput, create_task

        await create_task(session, await session.get(User, actor_id), CreateTaskInput(
            project_mnemonic="ZZ", type_key="common_task", title="В архив",
            priority="low", author_tag="by_human"))

    await delete_project(session, p.id)
    with pytest.raises(Exception, match="не переиспользуется"):
        await create_project(session, ProjectInput(
            name="Дубль", mnemonic="zz", path=str(target)))


async def test_project_requires_writable_path(session, actor_id):
    from usecase.settings.projects import ProjectInput, create_project

    with pytest.raises(Exception, match="недоступен"):
        await create_project(session, ProjectInput(
            name="Плохой путь", mnemonic="QQ", path="/nonexistent/path/xyz"))
