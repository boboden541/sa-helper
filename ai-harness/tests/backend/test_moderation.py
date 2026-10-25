"""ФТ-ah-19 модерация pending: три исключения минуют статус предложения."""

from __future__ import annotations

import sqlalchemy as sa

from usecase.task.create_task import CreateTaskInput, create_task


def _inp(**kw):
    base = dict(project_mnemonic="AH", type_key="common_task", title="Модерация",
                priority="medium", author_tag="by_human")
    base.update(kw)
    return CreateTaskInput(**base)


async def _status_of(session, code):
    from repository.models import Task

    return (await session.execute(sa.select(Task.status_key).where(Task.code == code))).scalar_one()


async def test_human_creates_pending_with_notification(session, actor_id):
    """Задача из интерфейса — pending + уведомление о модерации."""
    from repository.models import Notification, User

    actor = await session.get(User, actor_id)
    created = await create_task(session, actor, _inp())
    assert created.status == "pending"
    notif = (await session.execute(
        sa.select(Notification).where(Notification.code == created.code,
                                      Notification.event_key == "pending_moderation")
    )).scalar_one()
    assert notif.resolved_at is None


async def test_agent_subtask_of_story_skips_pending(session, actor_id):
    """Подзадачи декомпозиции (агент + история) — сразу to do."""
    from repository.models import Task, User

    human = await session.get(User, actor_id)
    story = await create_task(session, human, _inp(type_key="story", title="История про оплаты"))
    # апрув истории → backlog → to do (упрощённо ставим to do напрямую)
    await session.execute(sa.update(Task).where(Task.code == story.code)
                          .values(status_key="todo"))
    await session.commit()

    agent = (await session.execute(
        sa.select(User).where(User.user_type == "agent", User.is_service.is_(False))
    )).scalar_one()
    sub = await create_task(session, agent, _inp(title="Подзадача", story_code=story.code))
    assert await _status_of(session, sub.code) == "todo"


async def test_bug_with_parent_in_testing_skips_pending(session, actor_id):
    """Баг при родителе in testing — сразу to do."""
    from repository.models import Task, User

    human = await session.get(User, actor_id)
    story = await create_task(session, human, _inp(type_key="story", title="История на тесте"))
    await session.execute(sa.update(Task).where(Task.code == story.code)
                          .values(status_key="in_testing"))
    await session.commit()
    bug = await create_task(session, human, _inp(type_key="bug", title="Баг из теста",
                                                 story_code=story.code))
    assert await _status_of(session, bug.code) == "todo"


async def test_eve_confirmed_skips_pending(session, actor_id):
    from repository.models import User

    actor = await session.get(User, actor_id)
    t = await create_task(session, actor, _inp(title="Подтверждено в Eve", eve_confirmed=True))
    assert t.status == "todo"


async def test_bug_without_testing_parent_goes_pending(session, actor_id):
    """Баг вне тестирования (заметил человек) — полноценный триаж в pending."""
    from repository.models import User

    actor = await session.get(User, actor_id)
    bug = await create_task(session, actor, _inp(type_key="bug", title="Баг мимо теста"))
    assert bug.status == "pending"
