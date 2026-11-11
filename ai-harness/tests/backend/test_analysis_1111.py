"""Регресс-тесты анализа 11.11.2026 (backend): changedByOther, удаление агента
с историей, клон без скиллов, UUID-мусор в URL, миграции flow, дефолт лимита
цикла доработки, API пользователей и обязательного входа."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from domain.model.validators import DomainError
from repository.models import AgentProfile, Chronicle, Task, User
from sqlalchemy.ext.asyncio import async_sessionmaker
from usecase.settings import flow as flow_uc
from usecase.story.mirror import apply_m4
from usecase.task.create_task import CreateTaskInput, create_task


def _actor_sql():
    return sa.text("SELECT id FROM \"user\" WHERE name = 'Алексей'")


async def _mk_task(session, actor_id, title="Задача для правок"):
    human = await session.get(User, actor_id)
    created = await create_task(
        session,
        human,
        CreateTaskInput(
            project_mnemonic="AH",
            type_key="common_task",
            title=title,
            priority="medium",
            author_tag="by_human",
        ),
    )
    return (await session.execute(sa.select(Task).where(Task.code == created.code))).scalar_one()


async def _mk_agent(session, name):
    user = User(name=name, user_type="agent")
    session.add(user)
    await session.flush()
    session.add(AgentProfile(user_id=user.id, role="тест"))
    await session.commit()
    return user


async def test_patch_returns_changed_by_other(client, _test_db):
    """Конфликтное обновление возвращает changedByOther: раньше флаг терялся
    в _card_out и был exclude=True в DTO — тост фронта не работал никогда."""
    async with async_sessionmaker(_test_db, expire_on_commit=False)() as s:
        task = await _mk_task(s, (await s.execute(_actor_sql())).scalar_one())
        code = task.code
    r = await client.patch(
        f"/api/v1/tasks/{code}",
        json={"title": "Отставшая правка", "ifUpdatedAt": "2000-01-01T00:00:00Z"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["changedByOther"] is True
    fresh = (await client.get(f"/api/v1/tasks/{code}")).json()
    r2 = await client.patch(
        f"/api/v1/tasks/{code}",
        json={"title": "Свежая правка", "ifUpdatedAt": fresh["updatedAt"]},
    )
    assert r2.status_code == 200, r.text
    assert not r2.json()["changedByOther"]


async def test_delete_agent_with_history_400(client, _test_db):
    """Раньше DELETE агента с историей падал IntegrityError → 500 (FK без
    ondelete); теперь честный 400 со списком ссылок. Без истории — 200."""
    async with async_sessionmaker(_test_db, expire_on_commit=False)() as s:
        actor = (await s.execute(_actor_sql())).scalar_one()
        agent = await _mk_agent(s, "Одноразовый агент")
        task = await _mk_task(s, actor, "Носитель хроники")
        s.add(
            Chronicle(
                task_id=task.id,
                author_id=agent.id,
                author_kind="agent",
                event_type="agent",
                message="след",
            )
        )
        await s.commit()
        aid = str(agent.id)
    r = await client.delete(f"/api/v1/agents/{aid}")
    assert r.status_code == 400, r.text
    assert "история" in r.json()["message"]
    async with async_sessionmaker(_test_db, expire_on_commit=False)() as s:
        fresh = await _mk_agent(s, "Чистый агент")
        fid = str(fresh.id)
    r2 = await client.delete(f"/api/v1/agents/{fid}")
    assert r2.status_code == 200, r2.text


async def test_clone_keeps_skills(client):
    """Клон пресет-агента раньше терял назначенные скиллы (поле не копировалось)."""
    agents = (await client.get("/api/v1/agents")).json()
    items = agents["items"] if isinstance(agents, dict) else agents
    src = next(a for a in items if a["name"] == "Тестировщик")
    src_skills = src.get("skills") or []
    assert src_skills, "у пресета Тестировщик должны быть скиллы из сида"
    r = await client.post(f"/api/v1/agents/{src['id']}/clone")
    assert r.status_code == 200, r.text
    agents2 = (await client.get("/api/v1/agents")).json()
    items2 = agents2["items"] if isinstance(agents2, dict) else agents2
    clone = next(a for a in items2 if a["name"] == "Тестировщик (копия)")
    assert (clone.get("skills") or []) == src_skills


async def test_uuid_garbage_is_400_not_500(client):
    """Мусор в путевом UUID — 400 по всему семейству эндпоинтов (раньше 500)."""
    r = await client.get("/api/v1/runs/не-uuid/log")
    assert r.status_code == 400, r.text
    r = await client.delete("/api/v1/projects/не-uuid")
    assert r.status_code == 400, r.text
    r = await client.delete("/api/v1/agents/не-uuid")
    assert r.status_code == 400, r.text


async def _draft_without_qa_ready(session):
    """Определение из текущей опубликованной версии без статуса qa_ready."""
    cur = (
        await session.execute(
            sa.text(
                "SELECT fv.id FROM flow_version fv JOIN task_type tt ON tt.id=fv.task_type_id "
                "WHERE tt.key='common_task' AND fv.is_current AND fv.is_published"
            )
        )
    ).scalar_one()
    statuses = (
        (
            await session.execute(
                sa.text(
                    "SELECT status_key AS key, label, is_entry, is_terminal, is_blocking, "
                    "checklist_gate, alias_column_id FROM flow_status "
                    "WHERE flow_version_id = :fv AND status_key <> 'qa_ready'"
                ),
                {"fv": str(cur)},
            )
        )
        .mappings()
        .all()
    )
    transitions = (
        (
            await session.execute(
                sa.text(
                    "SELECT from_status, to_status, runner, display FROM flow_transition "
                    "WHERE flow_version_id = :fv AND from_status <> 'qa_ready' "
                    "AND to_status <> 'qa_ready'"
                ),
                {"fv": str(cur)},
            )
        )
        .mappings()
        .all()
    )
    sts = [
        {
            "key": s["key"],
            "label": s["label"],
            "stage_desc": "",
            "gate": s["checklist_gate"],
            "entry": bool(s["is_entry"]),
            "terminal": s["is_terminal"],
            "blocking": s["is_blocking"],
            "alias_column_id": s["alias_column_id"],
        }
        for s in statuses
    ]
    trs = [
        {
            "from": t["from_status"],
            "to": t["to_status"],
            "runner": t["runner"],
            "display": t["display"],
        }
        for t in transitions
    ]
    await flow_uc.save_draft(session, "common_task", {"statuses": sts, "transitions": trs})
    return sts


async def test_publish_rejects_bad_migration_target(session, actor_id):
    """Опечатка в статусе-приёмнике миграции — отказ публикации со списком
    (раньше уезжала в task.status_key, задача 500-ила на каждом переводе)."""
    task = await _mk_task(session, actor_id, "Задача в полёте")
    code = task.code
    await session.execute(
        sa.text("UPDATE task SET status_key='qa_ready' WHERE code=:c"), {"c": code}
    )
    await session.commit()
    await _draft_without_qa_ready(session)
    who = await session.get(User, actor_id)
    with pytest.raises(DomainError) as exc:
        await flow_uc.publish(session, "common_task", who, migrations={"qa_ready": "no_such"})
    assert "целевой статус" in exc.value.message


async def _mk_story(session, actor_id, title):
    created = await create_task(
        session,
        await session.get(User, actor_id),
        CreateTaskInput(
            project_mnemonic="AH",
            type_key="story",
            title=title,
            priority="medium",
            author_tag="by_human",
        ),
    )
    return (await session.execute(sa.select(Task).where(Task.code == created.code))).scalar_one()


async def test_m4_cycle_limit_without_seed_setting(session, actor_id):
    """rework.cycle_limit живёт только в сиде: чистая установка без сида не
    должна падать NoResultFound (500) — дефолт 5 из контракта правила."""
    story = await _mk_story(session, actor_id, "История для цикла доработки")
    await session.execute(sa.text("DELETE FROM app_setting WHERE key='rework.cycle_limit'"))
    await session.commit()
    story.m4_count = 4
    await apply_m4(session, story)
    assert story.status_key == "blocked" and story.blocked_rule == "M4"


async def test_m4_cycle_limit_bad_value_defaults(session, actor_id):
    """Мусор в rework.cycle_limit тоже не роняет правило — дефолт 5."""
    story = await _mk_story(session, actor_id, "История для мусорного лимита")
    await session.execute(
        sa.text(
            "INSERT INTO app_setting (key, value) VALUES ('rework.cycle_limit', 'abc') "
            "ON CONFLICT (key) DO UPDATE SET value='abc'"
        )
    )
    await session.commit()
    story.m4_count = 4
    await apply_m4(session, story)
    assert story.status_key == "blocked" and story.blocked_rule == "M4"


async def test_auth_users_and_required_flow(client, _test_db):
    """Анализ 11.11.2026: людей нельзя было завести/сменить пароль/включить
    вход — флаг auth.required был недостижим. Полный цикл API."""
    # включатель
    assert (await client.get("/api/v1/auth/required")).json()["enabled"] is False
    assert (await client.post("/api/v1/auth/required", json={"enabled": True})).status_code == 200
    assert (await client.get("/api/v1/auth/required")).json()["enabled"] is True
    # с включенным входом анонимный доступ к мутациям закрыт (401)...
    r = await client.post("/api/v1/tasks", json={})
    assert r.status_code == 401
    # ...включаем обратно и создаём человека
    assert (await client.post("/api/v1/auth/required", json={"enabled": False})).status_code == 200
    r = await client.post("/api/v1/auth/users", json={"name": "Мария", "password": "секрет123"})
    assert r.status_code == 200, r.text
    r = await client.post("/api/v1/auth/users", json={"name": "Мария", "password": "другой1"})
    assert r.status_code == 400
    # вход под новой учёткой
    r = await client.post("/api/v1/auth/login", json={"name": "Мария", "password": "секрет123"})
    assert r.status_code == 200, r.text
    # смена пароля: неверный старый → 400; верный → вход под новым
    r = await client.post(
        "/api/v1/auth/change-password",
        json={"oldPassword": "неверный", "newPassword": "новыйпароль1"},
    )
    assert r.status_code == 400
    r = await client.post(
        "/api/v1/auth/change-password",
        json={"oldPassword": "секрет123", "newPassword": "новыйпароль1"},
    )
    assert r.status_code == 200
    r = await client.post("/api/v1/auth/login", json={"name": "Мария", "password": "новыйпароль1"})
    assert r.status_code == 200
    # список людей
    names = [u["name"] for u in (await client.get("/api/v1/auth/users")).json()]
    assert "Мария" in names and "Алексей" in names
    # уборка: таблица "user" вне TRUNCATE-списка conftest — иначе последующие
    # тесты, ждущие ровно одного человека, падают MultipleResultsFound
    async with async_sessionmaker(_test_db, expire_on_commit=False)() as s:
        await s.execute(
            sa.text(
                "DELETE FROM session WHERE user_id IN (SELECT id FROM \"user\" WHERE name='Мария')"
            )
        )
        await s.execute(sa.text("DELETE FROM \"user\" WHERE name='Мария'"))
        await s.commit()


async def test_change_password_requires_current(client, _test_db):
    """Смена пароля без активной сессии-куки при включенном входе — 401."""
    await client.post("/api/v1/auth/required", json={"enabled": True})
    try:
        r = await client.post(
            "/api/v1/auth/change-password", json={"oldPassword": "a", "newPassword": "b"}
        )
        assert r.status_code == 401
    finally:
        await client.post("/api/v1/auth/required", json={"enabled": False})
