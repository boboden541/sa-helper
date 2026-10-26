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


async def test_project_path_created_and_inited(session, actor_id, tmp_path):
    """Решение владельца 26.10.2026: несуществующая директория создаётся,
    новой директории даётся git-репозиторий с начальным коммитом."""
    import subprocess

    from usecase.settings.projects import ProjectInput, create_project

    target = tmp_path / "deep" / "nested" / "workspace"
    proj = await create_project(session, ProjectInput(
        name="Созданный путь", mnemonic="QQ", path=str(target)))
    assert target.is_dir()
    assert proj.path == str(target.resolve())
    assert subprocess.run(["git", "rev-parse", "--verify", "HEAD"],
                          cwd=target, capture_output=True).returncode == 0

    # существующая директория-репозиторий не трогается
    marker = target / "file.txt"
    marker.write_text("x", encoding="utf-8")
    proj2 = await create_project(session, ProjectInput(
        name="Существующая", mnemonic="QW", path=str(target)))
    assert proj2.path == str(target.resolve())
    assert marker.read_text(encoding="utf-8") == "x"

    # некреабельный путь — честная ошибка создания
    with pytest.raises(Exception, match="Не удалось создать"):
        await create_project(session, ProjectInput(
            name="Плохой путь", mnemonic="QE", path="/nonexistent/path/xyz"))


# ---------- alias-колонки (ФТ-ah-66, режим правки доски) ----------

async def test_alias_column_crud_and_delete_guard(client):
    r = await client.post("/api/v1/alias-columns",
                          json={"label": "Новая колонка", "color": "#123456"})
    assert r.status_code == 200
    col_id = r.json()["id"]

    r = await client.patch(f"/api/v1/alias-columns/{col_id}", json={"label": "Переименована"})
    assert r.json()["label"] == "Переименована"

    journal = (await client.get("/api/v1/settings-journal")).json()
    assert any("колонк" in row["summary"].lower() for row in journal)

    r = await client.delete(f"/api/v1/alias-columns/{col_id}")
    assert r.status_code == 200

    # защищённая колонка: «К работе» привязана к статусам встроенных flow
    cols = (await client.get("/api/v1/alias-columns")).json()
    todo = next(c for c in cols if c["label"] == "К работе")
    r = await client.delete(f"/api/v1/alias-columns/{todo['id']}")
    assert r.status_code == 400 and "привязано" in r.json()["message"]


async def test_matrix_get_roundtrip(client, session):
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from repository.models import Assignment, TaskType, User

    agent = (await session.execute(
        sa.select(User).where(User.name == "Ревьюер-1"))).scalar_one_or_none()
    if agent is None:
        agent = (await session.execute(pg_insert(User).values(
            name="Ревьюер-1", user_type="agent").returning(User))).scalar_one()
        await session.commit()
    type_id = (await session.execute(
        sa.select(TaskType.id).where(TaskType.key == "common_task"))).scalar_one()
    await session.execute(pg_insert(Assignment).values(
        task_type_id=type_id, status_key="in_review", user_id=agent.id,
        mode="parallel").on_conflict_do_nothing())
    await session.commit()

    r = await client.get("/api/v1/matrix/common_task")
    assert r.status_code == 200
    entries = r.json()["matrix"].get("in_review", [])
    assert any(e["name"] == "Ревьюер-1" and e["mode"] == "parallel" for e in entries)


async def test_task_type_wizard_creates_type_and_flow(client, session):
    """Мастер «+ тип задачи»: тип + опубликованный flow из пресета (ФТ-ah-57)."""
    r = await client.post("/api/v1/task-types", json={
        "key": "wizard_test", "label": "Визард-тип", "cloneFrom": "qa_task"})
    assert r.status_code == 200, r.text
    flow = (await client.get("/api/v1/flows/wizard_test")).json()
    assert flow["version"] >= 1 and len(flow["statuses"]) >= 5
    r2 = await client.post("/api/v1/task-types", json={
        "key": "wizard_test", "label": "Дубль", "cloneFrom": "qa_task"})
    assert r2.status_code == 400
