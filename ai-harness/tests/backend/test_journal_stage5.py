"""Этап 5: хроники, контракт уведомлений (9 событий), ПСИ, Eve."""

from __future__ import annotations

import sqlalchemy as sa

from repository.models import Notification, PsiRunItem, Task, User
from usecase.journal.chronicle import append, purge_expired_payloads
from usecase.journal.notifications import list_open, on_transition, raise_event, resolve
from usecase.task.create_task import CreateTaskInput, create_task


def _inp(**kw):
    base = dict(project_mnemonic="AH", type_key="common_task", title="Журналы",
                priority="medium", author_tag="by_human")
    base.update(kw)
    return CreateTaskInput(**base)


async def _task(session, actor_id, **kw) -> Task:
    actor = await session.get(User, actor_id)
    created = await create_task(session, actor, _inp(**kw))
    return (await session.execute(
        sa.select(Task).where(Task.code == created.code))).scalar_one()


# ---------- хроники ----------

async def test_auto_event_requires_rule_code(session, actor_id):
    """AC-4.5.1.1: запись автомата без номера правила отклоняется."""
    from domain.model.validators import DomainError

    task = await _task(session, actor_id)
    with pytest.raises(DomainError):
        await append(session, task.id, "transition", "auto", "без правила")


async def test_retention_purges_payload_keeps_record(session, actor_id):
    """AC-4.5.1.2: payload удалён по сроку, лёгкая запись жива."""
    import datetime as dt

    task = await _task(session, actor_id)
    entry = await append(session, task.id, "agent", "agent", "мысли агента",
                         payload="ПРОМПТ: секретный контекст", retention_days=0)
    await session.commit()
    removed = await purge_expired_payloads(session)
    assert removed >= 1
    rows = (await session.execute(sa.text(
        "SELECT count(*) FROM chronicle c LEFT JOIN chronicle_payload p "
        "ON p.id = c.payload_id WHERE c.id = :i AND p.id IS NULL"),
        {"i": str(entry.id)})).scalar_one()
    assert rows == 1  # лёгкая запись жива, payload удалён


# ---------- уведомления: контракт 9 событий (AC-4.5.1.3) ----------

async def test_full_notification_contract(session, actor_id):
    """Каждое событие контракта порождает уведомление; разрешение состояния снимает."""
    from usecase.journal.notifications import EVENT_KEYS

    task = await _task(session, actor_id)
    for key, default_message in EVENT_KEYS.items():
        await raise_event(session, task.code, key, f"{task.code}: {default_message}")
    await session.commit()
    open_keys = {n["eventKey"] for n in await list_open(session)}
    assert set(EVENT_KEYS) <= open_keys

    resolved = await resolve(session, task.code)
    await session.commit()
    assert resolved >= len(EVENT_KEYS)
    remaining = {n["code"] for n in await list_open(session)}
    assert task.code not in remaining


async def test_transition_resolver_raises_and_resolves(session, actor_id):
    """Переход в blocked поднимает уведомление; выход из blocked снимает."""
    from usecase.task.transition import apply_force

    task = await _task(session, actor_id)
    actor = await session.get(User, actor_id)
    await apply_force(session, actor, task.code, "blocked", "проверка уведомлений")
    blocked_notifs = [n for n in await list_open(session)
                      if n["code"] == task.code and n["eventKey"] == "blocked"]
    assert len(blocked_notifs) == 1
    await apply_force(session, actor, task.code, "todo", "разблокировали")
    still = [n for n in await list_open(session)
             if n["code"] == task.code and n["eventKey"] == "blocked"]
    assert not still


# ---------- ПСИ (AC-4.5.2.x) ----------

async def _story_with_psi(session, actor_id):
    actor = await session.get(User, actor_id)
    story = await create_task(session, actor, _inp(type_key="story", title="История ПСИ"))
    version = await _create_psi(session, actor, story.code)
    return actor, story, version


async def _create_psi(session, actor, story_code):
    from usecase.story.psi import create_version

    return await create_version(session, story_code, actor, sections=[
        {"heading": "Авторизация", "items": [
            {"action": "Открыть форму входа", "expected": "Форма открылась"},
            {"action": "Ввести верный пароль", "expected": "Вход выполнен"}]}])


async def test_psi_run_protocol_snapshot_and_bug_prefill(session, actor_id):
    """AC-4.5.2.1: протокол со снапшотом; непройденный — предложение бага."""
    actor, story, version = await _story_with_psi(session, actor_id)
    from usecase.story.psi import get_document, run_psi

    result = await run_psi(session, story.code, actor, results=[
        {"position": 1, "passed": True, "actual": "открылась"},
        {"position": 2, "passed": False, "actual": "ошибка 500"}])
    assert result["passed"] == 1 and result["failed"] == 1
    assert result["bugProposals"][0]["expected"] == "Вход выполнен"

    doc = await get_document(session, story.code)
    assert len(doc["runs"]) == 1
    snapshots = (await session.execute(sa.select(PsiRunItem))).scalars().all()
    assert len(snapshots) == 2  # снапшот обоих пунктов прогона


async def test_psi_new_cycle_keeps_protocols_no_dup_bug(session, actor_id):
    """AC-4.5.2.2: сброс пунктов; протоколы целы; баг по пункту не дублируется."""
    actor, story, _ = await _story_with_psi(session, actor_id)
    from usecase.story.psi import get_document, link_bug, new_cycle, run_psi

    result = await run_psi(session, story.code, actor,
                           results=[{"position": 1, "passed": False, "actual": "упало"}])
    await link_bug(session, story.code, 1, "AH-1")  # заведён баг по пункту

    reset = await new_cycle(session, story.code)
    assert reset == 2

    result2 = await run_psi(session, story.code, actor,
                            results=[{"position": 1, "passed": False, "actual": "снова"}])
    assert result2["bugProposals"] == []  # незакрытый баг пункта уже есть — дубля нет

    doc = await get_document(session, story.code)
    assert len(doc["runs"]) == 2  # оба протокола живы


# ---------- Eve (AC-4.5.3.x) ----------

async def test_eve_intent_then_confirm(session, actor_id):
    """«Переведи X на ревью» → намерение; «да» → переход от Eve с аудитом."""
    actor = await session.get(User, actor_id)
    task = await _task(session, actor_id, type_key="story")
    # история в qa_ready: ребро на in_testing существует (M3), Eve действует как человек
    await session.execute(sa.update(Task).where(Task.code == task.code)
                          .values(status_key="qa_ready"))
    await session.commit()
    from usecase.assistant.eve import handle_message

    reply = await handle_message(session, actor, f"переведи {task.code} на тестирование")
    assert reply["action"] == "confirm"

    confirmed = await handle_message(session, actor, "да")
    assert "Сделано" in confirmed["reply"]
    task_row = (await session.execute(
        sa.select(Task).where(Task.code == task.code))).scalar_one()
    assert task_row.status_key == "in_testing"


async def test_eve_direct_move_when_no_edge(session, actor_id):
    """Ребра нет + подтверждение «да» → прямой перевод (решение владельца
    28.10.2026: произвольные статусы через Eve, как руками через базу)."""
    from usecase.assistant.eve import handle_message

    actor = await session.get(User, actor_id)
    task = await _task(session, actor_id)  # pending: у задачи нет ребра на ревью

    reply = await handle_message(session, actor, f"переведи {task.code} на ревью")
    assert reply["action"] == "confirm"
    confirmed = await handle_message(session, actor, "да")
    assert "прямой перевод" in confirmed["reply"]
    row = (await session.execute(sa.text(
        "SELECT status_key FROM task WHERE code = :c"), {"c": task.code})).scalar_one()
    assert row == "in_review"


async def test_eve_gate_denial_explains(session, actor_id):
    """Настоящий отказ гейта (ребро есть, чеклист не закрыт) — Eve объясняет
    причину и не действует."""
    from usecase.assistant.eve import handle_message

    actor = await session.get(User, actor_id)
    task = await _task(session, actor_id)
    # детерминированность: сброс canonical-пресета (рёбра и гейты известны)
    from usecase.settings.flow import reset_builtin

    await reset_builtin(session, "common_task", actor)
    # настоящий гейт-отказ: ребро in_progress → review_ready есть, но чеклист
    # разработчика не создан; статус ставим напрямую, минуя рёбра
    code = task.code  # до expire_all: доступ к атрибуту ORM после — ленивая загрузка
    await session.execute(sa.text(
        "UPDATE task SET status_key = 'in_progress', flow_version_id = "
        "(SELECT fv.id FROM flow_version fv JOIN task_type tt ON tt.id = fv.task_type_id "
        "WHERE tt.key = 'common_task' AND fv.is_current AND fv.is_published) "
        "WHERE code = :c"), {"c": code})
    await session.commit()
    session.expire(task)  # SQL-обновление мимо ORM — сбросить кеш объекта

    reply = await handle_message(session, actor,
                                 f'переведи {code} в статус "Готово к ревью"')
    assert reply["action"] == "confirm"
    confirmed = await handle_message(session, actor, "да")
    assert "Не получилось" in confirmed["reply"]
    row = (await session.execute(sa.text(
        "SELECT status_key FROM task WHERE code = :c"), {"c": code})).scalar_one()
    assert row == "in_progress"  # Eve не действует сквозь отказ


async def test_eve_free_question_goes_to_llm(session, actor_id):
    """Свободный вопрос уходит в LLM активного провайдера; без провайдера —
    честный ответ «подключите», а не выдуманные действия (ФТ-ah-52)."""
    actor = await session.get(User, actor_id)
    from usecase.assistant.eve import handle_message

    reply = await handle_message(session, actor, "свари кофе")
    assert ("reply" in reply) and reply["reply"]


import pytest  # noqa: E402
