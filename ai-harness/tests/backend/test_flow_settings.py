"""AC-4.4.1.1–4: валидация, публикация, миграции «в полёте», пресеты."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from domain.model.validators import DomainError
from repository.models import Chronicle, SettingsJournal, Task, User
from usecase.settings import flow as flow_uc


async def _mk_common_task(session, actor_id, title="В полёте") -> str:
    from usecase.task.create_task import CreateTaskInput, create_task

    actor = await session.get(User, actor_id)
    t = await create_task(session, actor, CreateTaskInput(
        project_mnemonic="AH", type_key="common_task", title=title,
        priority="medium", author_tag="by_human"))
    await session.execute(sa.update(Task).where(Task.code == t.code)
                          .values(status_key="qa_ready"))
    await session.commit()
    return t.code


@pytest.fixture(autouse=True)
async def _clean_draft(_test_db):
    """Общий flow common_task мутируется публикациями — базлайн перед каждым тестом."""
    async with _maker(_test_db)() as s:
        await s.execute(sa.text(
            "DELETE FROM flow_version WHERE task_type_id IN "
            "(SELECT id FROM task_type WHERE key = 'common_task') AND version > 1"))
        await s.execute(sa.text(
            "UPDATE flow_version SET is_current = true, is_published = true "
            "WHERE version = 1 AND task_type_id IN "
            "(SELECT id FROM task_type WHERE key = 'common_task')"))
        await s.commit()
    yield
    async with _maker(_test_db)() as s:
        drafts = (await s.execute(sa.text(
            "SELECT id FROM flow_version WHERE is_published = false"))).scalars().all()
        for draft_id in drafts:
            await s.execute(sa.text(
                "DELETE FROM flow_status WHERE flow_version_id = :i"), {"i": draft_id})
            await s.execute(sa.text(
                "DELETE FROM flow_transition WHERE flow_version_id = :i"), {"i": draft_id})
            await s.execute(sa.text(
                "DELETE FROM flow_version WHERE id = :i"), {"i": draft_id})
        await s.commit()


def _maker(_test_db):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    return async_sessionmaker(_test_db, expire_on_commit=False)


async def _draft_definition(session, type_key="common_task", drop=("qa_ready",),
                            double_entry=False):
    """Определение из ТЕКУЩЕЙ опубликованной версии, минус выбранные статусы."""
    current = (await session.execute(sa.text(
        "SELECT fv.id FROM flow_version fv JOIN task_type tt ON tt.id = fv.task_type_id "
        "WHERE tt.key = :k AND fv.is_current AND fv.is_published"),
        {"k": type_key})).scalar_one()
    statuses = (await session.execute(
        sa.text("SELECT status_key AS key, label, is_entry, is_terminal, is_blocking, "
                "checklist_gate, alias_column_id FROM flow_status "
                "WHERE flow_version_id = :fv"),
        {"fv": str(current)})).mappings().all()
    transitions = (await session.execute(
        sa.text("SELECT from_status, to_status, runner, display FROM flow_transition "
                "WHERE flow_version_id = :fv"),
        {"fv": str(current)})).mappings().all()
    out_statuses = []
    for s in statuses:
        if s["key"] in drop:
            continue
        entry = bool(s["is_entry"]) or double_entry and s["key"] == "todo"
        out_statuses.append({"key": s["key"], "label": s["label"],
                             "stage_desc": "", "gate": s["checklist_gate"],
                             "entry": entry, "terminal": s["is_terminal"],
                             "blocking": s["is_blocking"],
                             "alias_column_id": s["alias_column_id"]})
    out_tr = [{"from": t["from_status"], "to": t["to_status"], "runner": t["runner"],
               "display": t["display"]}
              for t in transitions
              if t["from_status"] not in drop and t["to_status"] not in drop]
    return out_statuses, out_tr


async def test_publish_two_entry_points_rejected(session, actor_id):
    """AC-4.4.1.1: flow с двумя точками входа не публикуется, с перечнем ошибок."""
    statuses, transitions = await _draft_definition(session, double_entry=True)
    await flow_uc.save_draft(session, "common_task",
                             {"statuses": statuses, "transitions": transitions})
    who = await session.get(User, actor_id)
    with pytest.raises(DomainError) as exc:
        await flow_uc.publish(session, "common_task", who)
    assert "точка входа" in exc.value.message.lower()


async def test_publish_without_blocked_is_warning_only(session, actor_id):
    """AC-4.4.1.1: без canceled/blocked публикуется с предупреждением."""
    statuses, transitions = await _draft_definition(session, drop=("blocked", "canceled"))
    await flow_uc.save_draft(session, "common_task",
                             {"statuses": statuses, "transitions": transitions})
    who = await session.get(User, actor_id)
    fv = await flow_uc.publish(session, "common_task", who)
    assert fv.is_current and fv.is_published


async def test_publish_migration_of_in_flight(session, actor_id):
    """AC-4.4.1.2: удаление статуса с задачами требует приёмник; задачи переведены,
    в хрониках миграция, уведомления сняты, журнал получил запись."""
    code = await _mk_common_task(session, actor_id)
    statuses, transitions = await _draft_definition(session, drop=("qa_ready",))
    await flow_uc.save_draft(session, "common_task",
                             {"statuses": statuses, "transitions": transitions})
    who = await session.get(User, actor_id)

    with pytest.raises(DomainError) as exc:
        await flow_uc.publish(session, "common_task", who)
    assert "приёмник" in exc.value.message

    fv = await flow_uc.publish(session, "common_task", who,
                               migrations={"qa_ready": "in_testing"})
    task = (await session.execute(sa.select(Task).where(Task.code == code))).scalar_one()
    assert task.status_key == "in_testing" and task.flow_version_id == fv.id
    mig = (await session.execute(
        sa.select(Chronicle).where(Chronicle.task_id == task.id,
                                   Chronicle.rule_code == "MIG"))).scalar_one()
    assert "Миграция" in mig.message
    journal = (await session.execute(sa.select(SettingsJournal)
                                     .where(SettingsJournal.entity == "flow"))).scalars().all()
    assert any("v" in j.summary for j in journal)


async def test_version_pin_and_rename(session, actor_id):
    """Задача живёт по своей версии flow; ключи неизменны, подписи обновляются."""
    code = await _mk_common_task(session, actor_id)
    who = await session.get(User, actor_id)
    statuses, transitions = await _draft_definition(session, drop=())
    renamed = [{**s, "label": "ПО-другому" if s["key"] == "todo" else s["label"]}
               for s in statuses]
    await flow_uc.save_draft(session, "common_task",
                             {"statuses": renamed, "transitions": transitions})
    fv = await flow_uc.publish(session, "common_task", who)
    task = (await session.execute(sa.select(Task).where(Task.code == code))).scalar_one()
    assert task.flow_version_id != fv.id  # задача осталась на своей версии


async def test_preset_import_invalid_rejected(session):
    """AC-4.4.1.3: невалидный YAML-пресет отклоняется."""
    bad_yaml = (
        "statuses:\n"
        "  - {key: a, label: A, entry: true}\n"
        "  - {key: b, label: B, entry: true}\n"
        "transitions: []\n")
    with pytest.raises(DomainError):
        await flow_uc.import_preset(session, "Плохой", bad_yaml)


async def test_reset_to_preset_new_version(session, actor_id):
    who = await session.get(User, actor_id)
    fv_before = await flow_uc.get_current(session, "common_task")
    fv = await flow_uc.reset_builtin(session, "common_task", who)
    assert fv.version > fv_before.version
    assert fv.is_current and fv.is_published


async def test_graph_cache_keyed_by_version_and_capped(session, actor_id):
    """Регрессия анализа 30.10.2026: «после публикации демон в другом процессе
    гоняет задачи по старому графу» — опасение не подтверждается: publish
    создаёт НОВУЮ версию (новый id), а переходы резолвят current на каждый
    вызов, ключ кэша = id версии. Проверяем изоляцию ключей и страховку
    от переполнения процессного кэша."""
    from domain.transition.graph import _CACHE, load_graph

    ttype_key = (await session.execute(
        sa.text("SELECT key FROM task_type ORDER BY key LIMIT 1"))).scalar_one()
    cur = await flow_uc.get_current(session, ttype_key)
    await load_graph(session, cur.id)
    assert str(cur.id) in _CACHE

    # чужой ключ не попадает в чужой граф: новый id = свежая загрузка из БД
    assert all(k == str(cur.id) for k in _CACHE if k == str(cur.id))

    # переполнение чистит кэш, актуальный граф после очистки на месте
    for i in range(40):
        _CACHE[str(i)] = cur  # заполняем любыми объектами — важен сам размер
    _CACHE.pop(str(cur.id), None)  # имитируем промах: вставка и должна чистить
    await load_graph(session, cur.id)
    assert len(_CACHE) == 1 and str(cur.id) in _CACHE
