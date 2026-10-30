"""Общие фикстуры: тестовая БД (миграции + seed), клиент API, очистка между тестами."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT))

TEST_DB = "ai_harness_test"
# Креды переопределяются окружением (TEST_DATABASE_URL); дефолт — локальный
# docker compose (постгрес на 5433, юзер/пароль из переменных compose)
TEST_URL = os.environ.get(
    "TEST_DATABASE_URL",
    f"postgresql+asyncpg://harness:harness@localhost:5433/{TEST_DB}")
os.environ["DATABASE_URL"] = TEST_URL
os.environ.setdefault("AI_HARNESS_TOKEN_KEY", "")

import sqlalchemy as sa  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402


@pytest.fixture(scope="session")
async def _test_db():
    """Создаёт тестовую БД, накатывает миграции, наполняет seed'ом."""
    import asyncpg

    admin = await asyncpg.connect("postgresql://harness:harness@localhost:5433/ai_harness")
    await admin.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}"')
    await admin.execute(f'CREATE DATABASE "{TEST_DB}"')
    await admin.close()

    from alembic import command
    from alembic.config import Config

    alembic_cfg = Config(str(ROOT / "alembic.ini"))
    os.environ["TEST_DATABASE_URL"] = TEST_URL
    # alembic запускает собственный event loop — выполняем в отдельном потоке
    await asyncio.to_thread(command.upgrade, alembic_cfg, "head")

    from database import dispose_engine
    from db.seeds.seed_dev import seed

    await seed()  # DATABASE_URL указывает на тестовую БД

    engine = create_async_engine(TEST_URL)
    yield engine
    await dispose_engine()
    await engine.dispose()

    admin = await asyncpg.connect("postgresql://harness:harness@localhost:5433/ai_harness")
    await admin.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}"')
    await admin.close()


@pytest.fixture
async def engine(_test_db):
    return _test_db


@pytest.fixture
async def session(_test_db):
    """Сессия на тест; между тестами — TRUNCATE операционных таблиц (справочники живут)."""
    maker = async_sessionmaker(_test_db, expire_on_commit=False)
    async with maker() as s:
        yield s
    await s.execute(sa.text(
        "TRUNCATE task, task_tag, tag, chronicle, chronicle_payload, notification, "
        "task_run, task_relation, checklist, checklist_item, task_comment, "
        "task_assignee, task_artifact, task_branch, psi_document, psi_run, psi_run_item, "
        "assignment, dead_mnemonic RESTART IDENTITY CASCADE"
    ))
    await s.execute(sa.text("UPDATE project SET next_number = 1"))
    await s.commit()


@pytest.fixture
async def client(_test_db):
    """HTTP-клиент поверх приложения на тестовой БД.
    После теста чистим операционные таблицы — как session-фикстура, иначе
    остатки client-тестов ломают тесты порядка очереди ниже по алфавиту."""
    from httpx import ASGITransport, AsyncClient

    from main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    async with async_sessionmaker(_test_db, expire_on_commit=False)() as s:
        await s.execute(sa.text(
            "TRUNCATE task, task_tag, tag, chronicle, chronicle_payload, notification, "
            "task_run, task_run_log, task_relation, checklist, checklist_item, task_comment, "
            "task_assignee, task_artifact, task_branch, psi_document, psi_run, psi_run_item, "
            "assignment, dead_mnemonic RESTART IDENTITY CASCADE"
        ))
        await s.execute(sa.text("UPDATE project SET next_number = 1"))
        await s.commit()


@pytest.fixture
async def actor_id(_test_db):
    """id первого человека (Алексей) — актор по умолчанию этапа 1."""
    maker = async_sessionmaker(_test_db, expire_on_commit=False)
    async with maker() as s:
        from repository.models import User

        return (await s.execute(
            sa.select(User.id).where(User.name == "Алексей")
        )).scalar_one()
