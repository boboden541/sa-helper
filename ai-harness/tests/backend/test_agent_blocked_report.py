"""Отчёт агента «заблокировано»: без ложного отказа «Агент не назначен».

apply_blocked для агента строил Subject по kind с ПУСТЫМИ правами — отказ
движка попадал в причину блокировки, агент читал его из хроники и повторял
(самоподдерживающийся мусор VITRINA-1, ночь 02→03.11.2026).
"""

from __future__ import annotations

import sqlalchemy as sa
from repository.models import Chronicle, Task, User
from usecase.task.create_task import CreateTaskInput, create_task
from usecase.task.transition import apply_blocked


async def test_agent_declared_blocked_clean_chronicle(session, actor_id):
    actor = await session.get(User, actor_id)
    s = await create_task(session, actor, CreateTaskInput(
        project_mnemonic="AH", type_key="story", title="Блок от агента",
        priority="high", author_tag="by_human"))
    story = (await session.execute(
        sa.select(Task).where(Task.code == s.code))).scalar_one()
    story.status_key = "in_testing"
    agent = User(name="Тестировщик-регресс", user_type="agent", is_chat_bot=False)
    session.add(agent)
    await session.flush()

    await apply_blocked(session, story, agent,
                        "Прогон ПСИ провален: 2 пункта не пройдены, баги заведены",
                        subject_kind="agent", rule_code="AGENT_REPORT")
    await session.commit()

    assert story.status_key == "blocked"
    assert story.blocked_rule == "AGENT_REPORT"
    assert story.blocked_reason == "Прогон ПСИ провален: 2 пункта не пройдены, баги заведены"
    msgs = (await session.execute(
        sa.select(Chronicle.message).where(Chronicle.task_id == story.id)
        .order_by(Chronicle.created_at))).scalars().all()
    blocked_msgs = [m for m in msgs if m.startswith("Автоблокировка")]
    assert blocked_msgs, "автоблокировка в хронике"
    assert not any("Агент не назначен" in m for m in blocked_msgs), \
        f"ложный отказ в причине блокировки: {blocked_msgs}"
    assert any("Прогон ПСИ провален" in m for m in blocked_msgs), \
        "причина агента в хронике без префикса отказа"
