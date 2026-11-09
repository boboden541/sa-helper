"""ФНР-16: acceptance_budget — жёсткий бюджет приёмки, потреблённый демоном.

Раньше поведение висело в каталоге и сиде без единого читателя (анализ
09.11.2026): флаг «acceptance_budget» на статусе psi_review ничего не делал,
а общий work-лимит (30 мин) рвал сквозной прогон ПСИ на середине."""

from __future__ import annotations

import os

import sqlalchemy as sa
from repository.models import Task
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from daemon.config import _DEFAULTS
from daemon.scheduler.helpers import acceptance_work_timeout


async def test_acceptance_budget_overrides_work_limit(_test_db):
    """psi_review (behaviors: acceptance_budget) → 60 мин; вне приёмки — общий work-лимит."""
    eng = create_async_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with async_sessionmaker(eng)() as s:
            await s.execute(
                sa.text(
                    "INSERT INTO task (id, project_id, code, task_type_id, title, "
                    "description_md, status_key, flow_version_id, priority, author_id) "
                    "SELECT gen_random_uuid(), p.id, 'AH-BUD-story', tt.id, 'Бюджет', '', "
                    "'psi_review', fv.id, 'medium', u.id "
                    'FROM project p, task_type tt, flow_version fv, "user" u '
                    "WHERE p.mnemonic='AH' AND tt.key='story' "
                    "AND fv.task_type_id = tt.id AND fv.is_current AND fv.is_published "
                    "AND u.name='Алексей'"
                )
            )
            await s.execute(
                sa.text(
                    "INSERT INTO task (id, project_id, code, task_type_id, title, "
                    "description_md, status_key, flow_version_id, priority, author_id) "
                    "SELECT gen_random_uuid(), p.id, 'AH-BUD-common', tt.id, 'Бюджет', '', "
                    "'todo', fv.id, 'medium', u.id "
                    'FROM project p, task_type tt, flow_version fv, "user" u '
                    "WHERE p.mnemonic='AH' AND tt.key='common_task' "
                    "AND fv.task_type_id = tt.id AND fv.is_current AND fv.is_published "
                    "AND u.name='Алексей'"
                )
            )

            await s.commit()
            story = (
                await s.execute(sa.text("SELECT id FROM task WHERE code='AH-BUD-story'"))
            ).scalar_one()
            common = (
                await s.execute(sa.text("SELECT id FROM task WHERE code='AH-BUD-common'"))
            ).scalar_one()
            story_obj = await s.get(Task, story)
            common_obj = await s.get(Task, common)
            cfg = dict(_DEFAULTS)
            assert await acceptance_work_timeout(s, story_obj, cfg) == 60 * 60
            assert await acceptance_work_timeout(s, common_obj, cfg) == 1800
    finally:
        await eng.dispose()
