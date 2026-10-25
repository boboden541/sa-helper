"""AC-4.2.2.1…3 / ФТ-ah-20, ФТ-ah-36: зеркалирование M1–M6 и лимит циклов."""

from __future__ import annotations

import sqlalchemy as sa

from repository.models import Chronicle, Task, User
from usecase.story.mirror import apply_m4, recompute_story_mirroring
from usecase.task.create_task import CreateTaskInput, create_task


def _inp(**kw):
    base = dict(project_mnemonic="AH", type_key="common_task", title="Дочерняя",
                priority="medium", author_tag="by_human")
    base.update(kw)
    return CreateTaskInput(**base)


async def _status(session, code, status):
    await session.execute(sa.update(Task).where(Task.code == code).values(status_key=status))
    await session.commit()


async def _story(session, actor, title="История зеркала") -> Task:
    s = await create_task(session, actor, _inp(type_key="story", title=title))
    story = (await session.execute(
        sa.select(Task).where(Task.code == s.code))).scalar_one()
    await _status(session, s.code, "todo")
    story.status_key = "todo"
    return story


async def _refresh(session, story: Task) -> Task:
    await session.commit()
    return (await session.execute(
        sa.select(Task).where(Task.id == story.id))).scalar_one()


async def test_m2_then_m3_two_chronicle_events(session, actor_id):
    """AC-4.2.2.1: закрытие последней дочерней — qa ready (M2), следующим вызовом —
    in testing (M3); в хрониках два события с номерами правил."""
    actor = await session.get(User, actor_id)
    story = await _story(session, actor)
    child = await create_task(session, actor, _inp(story_code=story.code))

    # ребёнок в pending — история остаётся в todo (нет активных детей)
    assert await recompute_story_mirroring(session, story) is None

    await _status(session, child.code, "in_progress")
    rule = await recompute_story_mirroring(session, story)
    story = await _refresh(session, story)
    assert rule == "M1" and story.status_key == "in_progress"

    await _status(session, child.code, "done")
    rule = await recompute_story_mirroring(session, story)
    story = await _refresh(session, story)
    assert rule == "M2" and story.status_key == "qa_ready"

    rule = await recompute_story_mirroring(session, story)
    story = await _refresh(session, story)
    assert rule == "M3" and story.status_key == "in_testing"

    rules = (await session.execute(
        sa.select(Chronicle.rule_code).where(Chronicle.task_id == story.id,
                                             Chronicle.event_type == "transition",
                                             Chronicle.author_kind == "auto")
        .order_by(Chronicle.created_at))).scalars().all()
    assert rules[-2:] == ["M2", "M3"]


async def test_m1_any_child_in_work(session, actor_id):
    actor = await session.get(User, actor_id)
    story = await _story(session, actor)
    child = await create_task(session, actor, _inp(story_code=story.code))
    await _status(session, child.code, "in_progress")
    rule = await recompute_story_mirroring(session, story)
    story = await _refresh(session, story)
    assert rule == "M1" and story.status_key == "in_progress"


async def test_m1_wins_on_competition(session, actor_id):
    """AC-4.2.2.3: одновременные условия M1 и M2 — побеждает M1."""
    actor = await session.get(User, actor_id)
    story = await _story(session, actor)
    c1 = await create_task(session, actor, _inp(story_code=story.code))
    c2 = await create_task(session, actor, _inp(story_code=story.code))
    await _status(session, c1.code, "done")
    await _status(session, c2.code, "in_progress")  # есть активный → M1, не M2
    rule = await recompute_story_mirroring(session, story)
    story = await _refresh(session, story)
    assert rule == "M1" and story.status_key == "in_progress"


async def test_m5_all_children_blocked(session, actor_id):
    actor = await session.get(User, actor_id)
    story = await _story(session, actor)
    c1 = await create_task(session, actor, _inp(story_code=story.code))
    c2 = await create_task(session, actor, _inp(story_code=story.code))
    await _status(session, c1.code, "in_progress")
    await _status(session, c2.code, "in_progress")
    rule = await recompute_story_mirroring(session, story)
    story = await _refresh(session, story)
    assert rule == "M1"
    await _status(session, c1.code, "blocked")
    await _status(session, c2.code, "blocked")
    rule = await recompute_story_mirroring(session, story)
    story = await _refresh(session, story)
    assert rule == "M5" and story.status_key == "blocked"


async def test_m4_cycle_limit(session, actor_id):
    """AC-4.2.2.2: M4 → blocked; M1 возврат; пятый M4 → blocked «цикл не сходится»."""
    actor = await session.get(User, actor_id)
    story = await _story(session, actor)
    story = await _refresh(session, story)
    await session.execute(sa.update(Task).where(Task.id == story.id)
                          .values(status_key="in_testing"))
    await session.commit()

    for cycle in range(5):
        story = await _refresh(session, story)
        await apply_m4(session, story)
        story = await _refresh(session, story)
        if cycle < 4:
            assert story.status_key == "blocked"
            assert "цикл" not in (story.blocked_reason or "")
            # работа по багу возобновилась → M1 вернёт in progress
            await session.execute(sa.update(Task).where(Task.id == story.id)
                                  .values(status_key="in_progress"))
            await session.commit()

    story = await _refresh(session, story)
    assert story.status_key == "blocked"
    assert "цикл не сходится" in story.blocked_reason.lower()
    assert story.m4_count == 5
