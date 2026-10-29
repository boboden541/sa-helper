"""Регрессии исправлений: await чеклиста, изоляция ПСИ, паузы interrupt/success."""

from __future__ import annotations

import datetime as dt

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from daemon.config import load_daemon_settings, retry_pauses_minutes
from daemon.scheduler.scheduler import Daemon, _next_retry_at
from daemon.runner.agent_runner import RunReport
from daemon.runner.reservation import reserve_task
from repository.models import (Checklist, ChecklistItem, PsiDocument, PsiRun,
                               Task, User)

from tests.daemon.test_heartbeat_retry import _maker, _ready_task


async def test_agent_checklist_add_is_applied(_test_db):
    """Агент добавляет пункт чеклиста — пункт появляется (регрессия пропущенного await)."""
    agent_id, code = await _ready_task(_test_db)
    maker = _maker(_test_db)
    daemon = Daemon(maker, runner=None)
    async with maker() as s:
        task = (await s.execute(sa.select(Task).where(Task.code == code))).scalar_one()
        s.add(Checklist(task_id=task.id, kind="developer"))
        await s.commit()
        report = RunReport(status="success", summary_md="ok",
                           checklist_updates=[{"checklist_kind": "developer",
                                               "text": "новый пункт",
                                               "new_status": "todo"}])
        await daemon._apply_checklist_updates(s, task, report)
        items = (await s.execute(
            sa.select(ChecklistItem.text).where(ChecklistItem.kind == "item")
            .order_by(ChecklistItem.position))).scalars().all()
    assert items == ["новый пункт"]


async def test_psi_document_isolated_per_story(_test_db):
    """get_document возвращает только прогоны своей истории (регрессия утечки)."""
    from domain.model.validators import DomainError
    from usecase.story.psi import get_document

    async with _maker(_test_db)() as s:
        await s.execute(sa.text(
            "TRUNCATE task, psi_document, psi_run, psi_run_item RESTART IDENTITY CASCADE"))
        author = (await s.execute(
            sa.select(User).where(User.name == "Алексей"))).scalar_one()
        id_a = (await s.execute(sa.text(
            "INSERT INTO task (id, project_id, code, task_type_id, title, "
            "description_md, status_key, flow_version_id, priority, author_id) "
            "SELECT gen_random_uuid(), p.id, 'AH-STORY-A', t.id, 'S', '', 'qa_ready', fv.id, "
            "'medium', :a FROM project p, task_type t, flow_version fv "
            "WHERE p.mnemonic='AH' AND t.key='story' AND fv.task_type_id = t.id "
            "AND fv.is_current RETURNING id"), {"a": str(author.id)})).scalar_one()
        doc_a = PsiDocument(story_id=id_a, version=1, author_id=author.id)
        s.add(doc_a)
        await s.flush()
        s.add(PsiRun(psi_doc_id=doc_a.id, run_by=author.id, passed=1, failed=0))
        await s.execute(sa.text(
            "INSERT INTO task (id, project_id, code, task_type_id, title, "
            "description_md, status_key, flow_version_id, priority, author_id) "
            "SELECT gen_random_uuid(), p.id, 'AH-STORY-B', t.id, 'S', '', 'qa_ready', fv.id, "
            "'medium', :a FROM project p, task_type t, flow_version fv "
            "WHERE p.mnemonic='AH' AND t.key='story' AND fv.task_type_id = t.id "
            "AND fv.is_current"), {"a": str(author.id)})
        await s.commit()

    async with _maker(_test_db)() as s:
        doc = await get_document(s, "AH-STORY-A")
        assert len(doc["runs"]) == 1  # только свой прогон, не всех историй
        with pytest.raises(DomainError):
            await get_document(s, "AH-STORY-B")  # у B нет ПСИ — раньше отдал бы чужие


async def test_interrupt_and_same_status_success_pause(_test_db):
    """Перехват человеком и успех без перехода → максимальная пауза перед повтором."""
    agent_id, code = await _ready_task(_test_db, status="in_progress")
    cfg = await load_daemon_settings.__wrapped__(_test_db) if hasattr(
        load_daemon_settings, "__wrapped__") else None
    maker = _maker(_test_db)
    async with maker() as s:
        task = (await s.execute(sa.select(Task).where(Task.code == code))).scalar_one()
        cfg = await load_daemon_settings(s)
        pauses = retry_pauses_minutes(cfg)
        now = dt.datetime.now(dt.timezone.utc)

        # успех на том же статусе → максимальная пауза (не вечный цикл)
        await reserve_task(s, task.id, agent_id, "in_progress")
        from daemon.runner.reservation import release_reservation
        await release_reservation(s, task.id, "success")
        nxt = await _next_retry_at(s, task.id, "in_progress", cfg)
        assert nxt is not None and nxt > now + dt.timedelta(minutes=pauses[-1] - 1)

        # перехват человеком → тоже максимальная пауза (тихое окно)
        await reserve_task(s, task.id, agent_id, "in_progress")
        await release_reservation(s, task.id, "interrupted")
        nxt2 = await _next_retry_at(s, task.id, "in_progress", cfg)
        assert nxt2 is not None and nxt2 > now + dt.timedelta(minutes=pauses[-1] - 1)

        # обычный failed → растущая серия от 1 минуты
        await reserve_task(s, task.id, agent_id, "in_progress")
        await release_reservation(s, task.id, "failed")
        nxt3 = await _next_retry_at(s, task.id, "in_progress", cfg)
        assert nxt3 is not None and nxt3 < now + dt.timedelta(minutes=pauses[0] + 1)
