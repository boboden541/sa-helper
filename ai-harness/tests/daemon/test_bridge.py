"""Мост LiteLLM: рендер конфига, env SDK, синхронизация по тику.

Шаг 1 мультипротокола: openai-подключения ведут прогоны через сайдкар —
раньше были заблокированы fast-fail'ом (годны только для чата Eve)."""

from __future__ import annotations

import json

from daemon.bridge import render_config
from daemon.runner.agent_runner import _sdk_env


def test_render_config_lists_openai_routes():
    rows = [
        ("11111111-1111-1111-1111-111111111111", "https://a/v1", "model-a", "tok-a"),
        ("22222222-2222-2222-2222-222222222222", "https://b/v1", "model-b", "tok-b"),
    ]
    cfg = json.loads(render_config(rows))
    routes = {m["model_name"]: m["litellm_params"] for m in cfg["model_list"]}
    assert set(routes) == {"har-11111111", "har-22222222"}
    assert routes["har-11111111"]["model"] == "openai/model-a"
    assert routes["har-11111111"]["api_base"] == "https://a/v1"
    assert routes["har-11111111"]["api_key"] == "tok-a"
    assert cfg["litellm_settings"] == {"drop_params": True}


def test_sdk_env_openai_routes_via_bridge(monkeypatch):
    monkeypatch.setenv("LITELLM_URL", "http://bridge:4000")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-test")
    env = _sdk_env({"protocol": "openai", "bridge_model": "har-abc12345"})
    assert env["ANTHROPIC_BASE_URL"] == "http://bridge:4000"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "sk-test"
    assert env["ANTHROPIC_MODEL"] == "har-abc12345"
    assert "ANTHROPIC_DEFAULT_HAIKU_MODEL" in env


async def test_sync_bridge_renders_and_restarts_on_change(_test_db, tmp_path, monkeypatch):
    import os

    import sqlalchemy as sa
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from daemon.bridge import sync_bridge

    eng = create_async_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with async_sessionmaker(eng)() as s:
            await s.execute(
                sa.text(
                    "INSERT INTO connection (id, name, protocol, url, model, "
                    "token_encrypted, token_tail, check_status, is_active) "
                    "VALUES (gen_random_uuid(), 'X', 'openai', 'https://prov/v1', "
                    "'m-1', 'enc', 'xx', 'unchecked', false)"
                )
            )
            await s.commit()
            monkeypatch.setattr(
                "daemon.bridge.CONFIG_PATH", str(tmp_path / "config.yaml")
            )

            async def fake_decrypt(session, conn):
                return "tok-xyz"

            monkeypatch.setattr("usecase.settings.connections.get_decrypted_token", fake_decrypt)

            def fake_run(*a, **kw):
                return None

            monkeypatch.setattr("daemon.bridge.subprocess.run", fake_run)
            r1 = await sync_bridge(s)
            assert r1 == "rendered"
            assert "har-" in (tmp_path / "config.yaml").read_text()
            r2 = await sync_bridge(s)
            assert r2 is None
            await s.execute(sa.text("UPDATE connection SET model='m-2' WHERE name='X'"))
            await s.commit()
            r3 = await sync_bridge(s)
            assert r3 == "rendered"
    finally:
        await eng.dispose()
