"""Регресс-тесты анализа 11.11.2026 (демон/раннер): env-гонка параллельных
прогонов, лестница ретраев против мусора в app_setting, чистка истёкших
сессий, легаси-шим release_reservation."""

from __future__ import annotations

import dataclasses
import datetime as dt

import sqlalchemy as sa

from daemon.config import retry_pauses_minutes


def test_retry_pauses_default_on_empty():
    """Пустая строка в app_setting больше не роняет тик IndexError'ом (pauses[-1])."""
    assert retry_pauses_minutes({"daemon.retry_pauses_minutes": ""}) == [1, 5, 15]
    assert retry_pauses_minutes({}) == [1, 5, 15]


def test_retry_pauses_garbage_falls_back():
    assert retry_pauses_minutes({"daemon.retry_pauses_minutes": "abc,def"}) == [1, 5, 15]
    assert retry_pauses_minutes({"daemon.retry_pauses_minutes": "0,-3,7"}) == [7]
    assert retry_pauses_minutes({"daemon.retry_pauses_minutes": "2,7"}) == [2, 7]


def test_runner_env_via_options_not_os_environ(monkeypatch):
    """SDK с полем env: окружение провайдера уходит В ОПЦИИ вызова, os.environ
    процесса не трогается — параллельные прогоны с разными подключениями не
    перезаписывают токены друг у друга (анализ 11.11.2026: env всегда шёл в
    os.environ без локи)."""

    @dataclasses.dataclass
    class FakeOptions:
        cwd: str = ""
        allowed_tools: list = dataclasses.field(default_factory=list)
        permission_mode: str = ""
        max_turns: int = 100
        env: dict | None = None

    class FakeSDK:
        ClaudeAgentOptions = FakeOptions

    from daemon.runner.agent_runner import ClaudeCodeRunner

    r = ClaudeCodeRunner(sdk_module=FakeSDK())

    captured = {}

    async def fake_run_env(req, prompt, options, env):
        captured["options"] = options
        captured["env_arg"] = env
        import os

        captured["os_env"] = dict(os.environ)
        return object()  # не RunReport — дальше не идём

    r._run_env = fake_run_env

    from daemon.runner.agent_runner import RunRequest

    req = RunRequest(
        task_code="AH-1",
        context_md="c",
        provider={"protocol": "anthropic", "token": "t", "url": "http://x", "model": "m"},
    )
    import asyncio

    asyncio.run(r.run(req))
    # env попал в опции, а в _run_env пришёл None (os.environ не трогается)
    assert captured["options"].env is not None
    assert "ANTHROPIC_BASE_URL" in captured["options"].env
    assert captured["env_arg"] is None


def test_release_reservation_shim_documented():
    """Шим не-UUID run_id остаётся НАМЕРЕННО (тесты используют как «закрыть все
    прогоны по outcome»); опасный вызыватель (Eve-interrupt) удалён — tripwire
    от возврата легаси-вызова в eve.py (гасил соседа по parallel-матрице)."""
    import ast as ast_mod
    from pathlib import Path

    import usecase.assistant.eve as eve_mod

    tree = ast_mod.parse(Path(eve_mod.__file__).read_text(encoding="utf-8"))
    calls = [
        n
        for n in ast_mod.walk(tree)
        if isinstance(n, ast_mod.Call)
        and (
            (isinstance(n.func, ast_mod.Name) and n.func.id == "release_reservation")
            or (isinstance(n.func, ast_mod.Attribute) and n.func.attr == "release_reservation")
        )
    ]
    assert not calls, (
        "eve.py снова вызывает release_reservation — легаси-вызов с outcome в "
        "run_id гасит ВСЕ прогоны задачи (анализ 11.11.2026)"
    )


async def test_retention_purges_expired_sessions(_test_db):
    """Истёкшие сессии чистятся retention-тиком (раньше таблица session росла
    вечно — чистка была только по logout)."""
    import hashlib
    import secrets

    from repository.models import Session
    from sqlalchemy.ext.asyncio import async_sessionmaker

    eng = _test_db
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        # session вне TRUNCATE-списка conftest — чистим сами от чужих сессий
        await s.execute(sa.text("DELETE FROM session"))
        uid = (await s.execute(sa.text('SELECT id FROM "user" LIMIT 1'))).scalar_one()
        now = dt.datetime.now(dt.timezone.utc)
        s.add(
            Session(
                user_id=uid,
                token_hash=hashlib.sha256(secrets.token_urlsafe(8).encode()).hexdigest(),
                expires_at=now - dt.timedelta(hours=1),
            )
        )
        s.add(
            Session(
                user_id=uid,
                token_hash=hashlib.sha256(secrets.token_urlsafe(8).encode()).hexdigest(),
                expires_at=now + dt.timedelta(hours=5),
            )
        )
        # gate «уже запускался сегодня» в тестовой БД не выставлен — тик отработает
        await s.commit()

    from daemon.scheduler.support import SupportMixin

    mixin = SupportMixin()
    async with maker() as s:
        await mixin._retention_tick(s)

    async with maker() as s:
        left = (await s.execute(sa.select(sa.func.count()).select_from(Session))).scalar_one()
    assert left == 1, "истёкшая сессия удалена, живая осталась"
