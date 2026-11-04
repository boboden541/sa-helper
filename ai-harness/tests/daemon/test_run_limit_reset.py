"""Сброс счётчика прогонов при выходе из blocked + семантика бюджета
(инцидент VITRINA-1, ночь 02→03.11.2026).

До фикса: 40 прогонов ПСИ-составителя (17 — плановые смены сессии) упирались
в daemon.max_runs_per_task, задача блокировалась, а ручной выход из blocked
не сбрасывал счётчик — вернуть задачу в работу было невозможно.
"""

import sqlalchemy as sa
from repository.models import Task, User
from usecase.task.create_task import CreateTaskInput, create_task

from tests.daemon.test_heartbeat_retry import _ready_task


def _inp(**kw):
    base = dict(
        project_mnemonic="AH",
        type_key="story",
        title="Лимит прогонов",
        priority="high",
        author_tag="by_human",
    )
    base.update(kw)
    return CreateTaskInput(**base)


async def _blocked_story(session, actor, holder: dict):
    s = await create_task(session, actor, _inp())
    holder["code"] = s.code
    await session.execute(
        sa.update(Task)
        .where(Task.code == s.code)
        .values(
            status_key="blocked",
            blocked_rule="RUN_LIMIT",
            blocked_reason="исчерпан лимит прогонов",
            runs_reset_at=None,
        )
    )
    await session.commit()


async def test_human_leave_blocked_resets_budget(session, actor_id):
    """Выход из blocked (человек) чистит blocked_reason/rule и ставит
    runs_reset_at — бюджет daemon.max_runs_per_task начинается с нуля."""
    actor = await session.get(User, actor_id)
    holder: dict = {}
    await _blocked_story(session, actor, holder)
    from usecase.task.transition import apply_transition

    await apply_transition(session, actor, holder["code"], "qa_ready")
    task = (await session.execute(sa.select(Task).where(Task.code == holder["code"]))).scalar_one()
    assert task.status_key == "qa_ready"
    assert task.blocked_reason is None and task.blocked_rule is None
    assert task.runs_reset_at is not None, "бюджет прогонов сброшен"


async def test_force_leave_blocked_resets_budget(session, actor_id):
    actor = await session.get(User, actor_id)
    holder: dict = {}
    await _blocked_story(session, actor, holder)
    from usecase.task.transition import apply_force

    await apply_force(
        session, actor, holder["code"], "in_progress", "разобрался, возвращаю в работу"
    )
    task = (await session.execute(sa.select(Task).where(Task.code == holder["code"]))).scalar_one()
    assert task.status_key == "in_progress"
    assert task.runs_reset_at is not None, "форс тоже сбрасывает бюджет"


async def test_budget_counts_real_runs_only(_test_db):
    """daemon.max_runs_per_task: плановые смены сессии (soft_turns) и обрывы
    «задача ушла со статуса» (stale_status) бюджет не тратят; прогоны до
    последнего выхода из blocked (runs_reset_at) не считаются."""
    from tests.daemon.test_heartbeat_retry import _maker

    agent_id, code = await _ready_task(_test_db)
    maker = _maker(_test_db)
    async with maker() as s:
        task_id = (
            await s.execute(sa.text("SELECT id FROM task WHERE code = :c"), {"c": code})
        ).scalar_one()
        await s.execute(
            sa.text(
                "INSERT INTO task_run (id, task_id, agent_id, status_key, attempt_no, "
                "finished_at, outcome, reason_code, started_at) "
                "SELECT gen_random_uuid(), :t, :a, 'in_progress', 1, "
                "now() - interval '2 hours', 'failed', 'soft_turns', now() - interval '2 hours'"
            ),
            {"t": str(task_id), "a": str(agent_id)},
        )
        await s.execute(
            sa.text(
                "INSERT INTO task_run (id, task_id, agent_id, status_key, attempt_no, "
                "finished_at, outcome, reason_code, started_at) "
                "SELECT gen_random_uuid(), :t, :a, 'in_progress', 2, "
                "now() - interval '2 hours', 'failed', 'denied_gate', now() - interval '2 hours'"
            ),
            {"t": str(task_id), "a": str(agent_id)},
        )
        await s.commit()
        total = (
            await s.execute(
                sa.text("SELECT count(*) FROM task_run WHERE task_id = :t"), {"t": str(task_id)}
            )
        ).scalar_one()
        assert total == 2, "самопроверка сидов"
    from daemon.scheduler.scheduler import Daemon

    daemon = Daemon(maker, runner=None)
    cfg = {
        "daemon.max_runs_per_task": "2",
        "daemon.max_attempts": "3",
        "daemon.max_parallel": "4",
        "daemon.timeout_start_seconds": "300",
        "daemon.timeout_work_seconds": "1800",
        "daemon.retry_pauses_minutes": "1,5,15",
    }
    async with maker() as s:
        launched = await daemon._launch_ready(s, cfg)
    assert launched == 1, (
        "счётчик учитывает только denied_gate (1 из 2): запуск есть; "
        "без фильтра soft_turns счёт был бы 2 из 2 — blocked"
    )


async def test_budget_respects_runs_reset_at(_test_db):
    """Прогоны до runs_reset_at (выход из blocked) в бюджет не входят."""
    from daemon.scheduler.scheduler import Daemon
    from tests.daemon.test_heartbeat_retry import _maker

    agent_id, code = await _ready_task(_test_db)
    maker = _maker(_test_db)
    async with maker() as s:
        await s.execute(
            sa.text("UPDATE task SET runs_reset_at = now() - interval '1 hour' WHERE code = :c"),
            {"c": code},
        )
        await s.execute(
            sa.text(
                "INSERT INTO task_run (id, task_id, agent_id, status_key, attempt_no, "
                "finished_at, outcome, reason_code, started_at) "
                "SELECT gen_random_uuid(), id, :a, 'in_progress', 1, "
                "now() - interval '2 hours', 'failed', 'denied_gate', "
                "now() - interval '2 hours' FROM task WHERE code = :c"
            ),
            {"a": str(agent_id), "c": code},
        )
        await s.commit()
    daemon = Daemon(maker, runner=None)
    cfg = {
        "daemon.max_runs_per_task": "1",
        "daemon.max_attempts": "3",
        "daemon.max_parallel": "4",
        "daemon.timeout_start_seconds": "300",
        "daemon.timeout_work_seconds": "1800",
        "daemon.retry_pauses_minutes": "1,5,15",
    }
    async with maker() as s:
        launched = await daemon._launch_ready(s, cfg)
    assert launched == 1, "прогон до runs_reset_at не входит в бюджет — запуск есть"
    import asyncio

    for t in daemon._active.values():
        t.cancel()
    await asyncio.gather(*daemon._active.values(), return_exceptions=True)


async def test_stale_psi_plan_skips_retry_pause(_test_db):
    """План ПСИ устарел (эталон v2 > заверка v1) на истории в in_testing
    снимает паузу прогонов: составитель запускается на следующем тике,
    а не через 15 минут (версионирование эталона, 03.11.2026)."""
    from daemon.scheduler.scheduler import Daemon
    from tests.daemon.test_heartbeat_retry import _maker

    async with _maker(_test_db)() as s:
        await s.execute(
            sa.text(
                "TRUNCATE task, task_run, task_tag, tag, chronicle, notification, "
                "task_relation, checklist, checklist_item, task_assignee RESTART IDENTITY CASCADE"
            )
        )
        await s.execute(sa.text("UPDATE project SET next_number = 1"))
        await s.commit()
        story_id = (
            await s.execute(
                sa.text(
                    "INSERT INTO task (id, project_id, code, task_type_id, title, description_md, "
                    "status_key, flow_version_id, priority, author_id, ref_version) "
                    "SELECT gen_random_uuid(), p.id, 'AH-' || next_number, t.id, 'История', '', "
                    "'in_testing', fv.id, 'high', u.id, 2 FROM project p, task_type t, "
                    "flow_version fv, \"user\" u WHERE p.mnemonic='AH' AND t.key='story' "
                    "AND fv.task_type_id=t.id AND fv.is_current AND u.name='Алексей' "
                    "RETURNING id"
                )
            )
        ).scalar_one()
        await s.execute(
            sa.text("UPDATE project SET next_number = next_number + 1 WHERE mnemonic='AH'")
        )
        agent = (
            await s.execute(sa.text("SELECT id FROM \"user\" WHERE name='ПСИ-составитель'"))
        ).scalar_one_or_none()
        if agent is None:
            agent = (
                await s.execute(
                    sa.text(
                        'INSERT INTO "user" (id, name, user_type) VALUES (gen_random_uuid(), '
                        "'ПСИ-составитель', 'agent') RETURNING id"
                    )
                )
            ).scalar_one()
        await s.execute(
            sa.text(
                "INSERT INTO assignment (id, task_type_id, status_key, user_id) "
                "SELECT gen_random_uuid(), task_type_id, 'in_testing', :a FROM task "
                "WHERE id = :t ON CONFLICT DO NOTHING"
            ),
            {"a": str(agent), "t": str(story_id)},
        )
        await s.execute(
            sa.text(
                "INSERT INTO checklist (id, task_id, kind, source_ref_version) "
                "SELECT gen_random_uuid(), id, 'psi', 1 FROM task WHERE id = :t"
            ),
            {"t": str(story_id)},
        )
        # свежий успешный прогон на том же статусе — обычная пауза 15 минут
        await s.execute(
            sa.text(
                "INSERT INTO task_run (id, task_id, agent_id, status_key, attempt_no, "
                "finished_at, outcome, started_at) SELECT gen_random_uuid(), id, :a, "
                "'in_testing', 1, now() - interval '1 minute', 'success', "
                "now() - interval '31 minutes' FROM task WHERE id = :t"
            ),
            {"a": str(agent), "t": str(story_id)},
        )
        await s.commit()

    maker = _maker(_test_db)
    daemon = Daemon(maker, runner=None)
    cfg = {
        "daemon.max_attempts": "3",
        "daemon.max_parallel": "4",
        "daemon.timeout_start_seconds": "300",
        "daemon.timeout_work_seconds": "1800",
        "daemon.retry_pauses_minutes": "1,5,15",
    }
    async with maker() as s:
        launched = await daemon._launch_ready(s, cfg)
    assert launched == 1, "устаревший план psi снимает паузу — запуск на этом же тике"
    import asyncio

    for t in daemon._active.values():
        t.cancel()
    await asyncio.gather(*daemon._active.values(), return_exceptions=True)
