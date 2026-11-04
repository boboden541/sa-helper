"""Контекст агента видит прогресс: чеклист-источник-истины, отчёты этапов,
комментарии (02.11.2026 — агенты повторяли работу, не видя итоги прошлых
прогонов: артефакты и комментарии в контекст не попадали вовсе).
Без client-фикстуры: одна сессия — нет кросс-сессионных TRUNCATE-дедлоков."""

from __future__ import annotations

import sqlalchemy as sa
from repository.models import Task, TaskArtifact, TaskComment
from sqlalchemy.ext.asyncio import async_sessionmaker
from usecase.task.context_bundle import build_context_md
from usecase.task.create_task import CreateTaskInput, create_task


async def _mk_progress(session, actor_id):
    human = await session.get(__import__("repository.models", fromlist=["User"]).User, actor_id)
    created = await create_task(
        session,
        human,
        CreateTaskInput(
            project_mnemonic="AH",
            type_key="common_task",
            title="Контекст-тест",
            priority="medium",
            author_tag="by_human",
        ),
    )
    # create_task отдаёт CreatedTask-датакласс; для контекста нужен ORM-объект
    task = (await session.execute(sa.select(Task).where(Task.code == created.code))).scalar_one()
    from usecase.journal.checklists import put_checklist

    await put_checklist(
        session,
        human,
        task,
        "developer",
        "# План\n- подготовить окружение\nx закрытый пункт\n~ веду тесты",
    )
    _agent = (
        await session.execute(sa.text("SELECT id FROM \"user\" WHERE name = 'Тестировщик'"))
    ).scalar_one()
    session.add(
        TaskArtifact(
            task_id=task.id,
            kind="dev_report",
            version=1,
            created_by=human.id,
            body_md="## Вердикт\nGREEN — тесты прошли, всё подтверждено.",
        )
    )
    session.add(
        TaskComment(
            task_id=task.id, author_id=human.id, body="Продолжай с тестов, сборку я уже сделал"
        )
    )
    await session.commit()
    return task


async def test_context_shows_progress_sources(_test_db, actor_id):
    maker = async_sessionmaker(_test_db, expire_on_commit=False)
    async with maker() as session:
        task = await _mk_progress(session, actor_id)
        ctx = await build_context_md(session, task)

        assert "источник истины" in ctx and "с чего продолжить" in ctx
        # позиции считаются по всем строкам чеклиста (заголовок = №0)
        assert "☐ №1 подготовить окружение [todo]" in ctx
        assert "☐ №3 веду тесты [in_progress]" in ctx
        assert "закрыты: №2" in ctx
        assert "### Чеклист developer" in ctx
        assert "Отчёт dev_report" in ctx and "GREEN" in ctx
        assert "Продолжай с тестов" in ctx and "человек" in ctx
        await session.rollback()


async def test_context_artifact_squeezed(_test_db, actor_id):
    """Длинный артефакт не раздувает контекст: начало + конец (вердикт в конце)."""
    maker = async_sessionmaker(_test_db, expire_on_commit=False)
    async with maker() as session:
        task = await _mk_progress(session, actor_id)
        task.body_md = None
        human = await session.get(__import__("repository.models", fromlist=["User"]).User, actor_id)
        session.add(
            TaskArtifact(
                task_id=task.id,
                kind="qa_report",
                version=1,
                created_by=human.id,
                body_md="строка падений\n" * 3000,
            )
        )
        await session.commit()
        ctx = await build_context_md(session, task)

        assert len(ctx) < 12000, "контекст не должен раздуваться от длинного артефакта"
        assert "сокращено" in ctx and "строка падений" in ctx
        await session.rollback()
