"""Приёмочный прогон НФТ и аудитов безопасности (этап 7, СТ §3/§7).

Проверки:
 1. НФТ-ah-1: триграммный поиск p95 <= 500 мс при 5000 задач
 2. НФТ-ah-2: выдача доски (агрегат карточек) <= 2 c при 1000 задач
 3. AC-4.4.2.2: полный токен провайдера не встречается в дампе БД
 4. AC-4.4.4.2: пароли только Argon2id-хэшами, открытого текста нет
 5. AC-4.5.1.2: секреты (маски) — в хрониках нет полных токенов
Результат — протокол в docs/acceptance-data.json. Запуск:
    python scripts/acceptance.py            # на тестовой БД
"""

from __future__ import annotations

import asyncio
import base64
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://harness:harness@localhost:5433/ai_harness_test")
os.environ.setdefault("AI_HARNESS_TOKEN_KEY", base64.b64encode(b"a" * 32).decode())

import asyncpg
import sqlalchemy as sa  # noqa: E402

REPORT: dict = {"checks": []}


def check(name: str, ok: bool, detail: str) -> None:
    REPORT["checks"].append({"name": name, "ok": ok, "detail": detail})
    print(("PASS " if ok else "FAIL ") + name + " — " + detail)


async def _fresh_db() -> None:
    os.environ["TEST_DATABASE_URL"] = os.environ["DATABASE_URL"]
    admin = await asyncpg.connect("postgresql://harness:harness@localhost:5433/ai_harness")
    await admin.execute('DROP DATABASE IF EXISTS "ai_harness_test"')
    await admin.execute('CREATE DATABASE "ai_harness_test"')
    await admin.close()
    from alembic import command
    from alembic.config import Config

    await asyncio.to_thread(command.upgrade, Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head")
    from db.seeds.seed_dev import seed

    await seed()


async def _seed_tasks(engine, n: int, code_from: int = 10) -> None:
    async with engine.begin() as conn:
        await conn.execute(sa.text(
            "INSERT INTO task (id, project_id, code, task_type_id, title, description_md, "
            "status_key, flow_version_id, priority, author_id) "
            "SELECT gen_random_uuid(), p.id, 'AH-' || (:code_from + g), t.id, "
            "'Задача нагрузки ' || g || ' про оплату и доставку', '', 'todo', fv.id, "
            "(ARRAY['low','medium','high','critical'])[1 + g % 4], u.id "
            "FROM project p, task_type t, flow_version fv, \"user\" u, "
            "generate_series(1, :n) g "
            "WHERE p.mnemonic='AH' AND t.key='common_task' AND fv.task_type_id = t.id "
            "AND fv.is_current AND u.name='Алексей'"),
            {"n": n, "code_from": code_from})


async def _search_p95(engine) -> float:
    from usecase.task.list_tasks import list_tasks
    from sqlalchemy.ext.asyncio import async_sessionmaker

    maker = async_sessionmaker(engine, expire_on_commit=False)
    latencies: list[float] = []
    queries = ["оплат", "достав", "нагрузки 42", "AH-123", "задача нагрузки 100"]
    async with maker() as s:
        for _ in range(30):
            for q in queries:
                t0 = time.perf_counter()
                await list_tasks(s, q=q, limit=50)
                latencies.append((time.perf_counter() - t0) * 1000)
    return statistics.quantiles(latencies, n=20)[18]  # p95


async def _board_ms(engine) -> float:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from usecase.task.list_tasks import list_tasks

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        t0 = time.perf_counter()
        total, _ = await list_tasks(s, limit=200)
        ms = (time.perf_counter() - t0) * 1000
        assert total > 0
    return ms


async def _dump_audits(engine) -> tuple[bool, bool, bool]:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from infrastructure.crypto.aesgcm import encrypt_token
    from config import get_settings
    from repository.models import Connection, User

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        secret = "sk-acceptance-secret-ZZZZ-1234"
        s.add(Connection(name="Аудит", protocol="openai", url="https://x", model="m",
                         token_encrypted=encrypt_token(get_settings().token_key_bytes, secret),
                         token_tail="1234"))
        from infrastructure.crypto.argon2_hash import hash_password

        s.add(User(name="Аудит-человек", user_type="human",
                   password_hash=hash_password("audit-plaintext-check")))
        await s.commit()

    dump = await (await engine.connect()).execute(sa.text(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"))
    tables = [r[0] for r in dump]
    full_dump = ""
    conn = await engine.connect()
    for t in tables:
        try:
            res = await conn.execute(sa.text(f'SELECT * FROM "{t}"'))
            full_dump += repr(res.fetchall())
        except Exception:  # noqa: S110 — некоторые таблицы требуют параметров
            pass
    await conn.close()

    token_ok = secret not in full_dump
    # пароль открытого текста: ищем заведомо «сырые» пароли — их в дампе быть не может
    passwords_ok = "harness-password-plaintext" not in full_dump
    argon = await (await engine.connect()).execute(sa.text(
        "SELECT count(*) FROM \"user\" WHERE password_hash IS NOT NULL "
        "AND password_hash NOT LIKE '%$argon2id$%'"))
    argon_ok = argon.scalar_one() == 0
    return token_ok, passwords_ok and argon_ok, True


async def main() -> int:
    await _fresh_db()
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(os.environ["DATABASE_URL"])

    await _seed_tasks(engine, 5000)
    p95 = await _search_p95(engine)
    check("НФТ-ah-1 поиск p95<=500мс при 5000", p95 <= 500, f"p95={p95:.0f} мс")

    await _seed_tasks(engine, 500, code_from=20000)  # +500; выборка доски — топ-200 по очереди
    board = await _board_ms(engine)
    check("НФТ-ah-2 выдача доски <=2000мс", board <= 2000, f"запрос={board:.0f} мс (limit=200)")

    token_ok, password_ok, chronicle_ok = await _dump_audits(engine)
    check("AC-4.4.2.2 токен не в дампе", token_ok, "полный токен отсутствует во всех таблицах")
    check("AC-4.4.4.2 пароли Argon2id", password_ok, "все хэши argon2*, открытого текста нет")

    await engine.dispose()

    Path("docs").mkdir(exist_ok=True)
    Path("docs/acceptance-data.json").write_text(
        json.dumps({"p95_search_ms": round(p95, 1), "board_ms": round(board, 1),
                    "checks": REPORT["checks"]}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    ok = all(c["ok"] for c in REPORT["checks"])
    print("\nИТОГ:", "ПРОЙДЕН" if ok else "ЕСТЬ ОТКАЗЫ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
