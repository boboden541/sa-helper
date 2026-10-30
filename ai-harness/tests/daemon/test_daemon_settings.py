"""Регрессии конфигурации демона: тик из app_setting и глобальная папка инструментов.

Фон: daemon/main.py спал по захардкоженным 30 с (DAEMON_TICK_SECONDS не читался),
а фолбэк scheduler'а на agents.tools_dir был мёртв — load_daemon_settings грузил
только daemon.* ключи.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from daemon.config import load_daemon_settings
from daemon.scheduler.scheduler import Daemon


def _maker(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


async def _set_setting(_test_db, key: str, value: str) -> None:
    async with _maker(_test_db)() as s:
        await s.execute(sa.text(
            "INSERT INTO app_setting (key, value) VALUES (:k, :v) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"),
            {"k": key, "v": value})
        await s.commit()


async def _del_setting(_test_db, key: str) -> None:
    async with _maker(_test_db)() as s:
        await s.execute(sa.text("DELETE FROM app_setting WHERE key = :k"), {"k": key})
        await s.commit()


async def test_tools_dir_always_in_cfg(_test_db):
    """Фолбэк scheduler'а на глобальную папку инструментов больше не мёртв:
    ключ agents.tools_dir есть в конфиге даже без строки в БД."""
    async with _maker(_test_db)() as s:
        cfg = await load_daemon_settings(s)
    assert cfg.get("agents.tools_dir") == ""


async def test_tools_dir_read_from_db(_test_db):
    """Значение из app_setting доходит до конфига демона."""
    await _set_setting(_test_db, "agents.tools_dir", "/home/me/sa-helper/.claude")
    try:
        async with _maker(_test_db)() as s:
            cfg = await load_daemon_settings(s)
    finally:
        await _del_setting(_test_db, "agents.tools_dir")
    assert cfg["agents.tools_dir"] == "/home/me/sa-helper/.claude"


async def test_tick_seconds_from_setting(_test_db):
    """Интервал цикла читается из app_setting, а не захардкожен."""
    daemon = Daemon(_maker(_test_db), runner=None)
    await _set_setting(_test_db, "daemon.tick_seconds", "5")
    try:
        assert await daemon.tick_seconds(30) == 5
    finally:
        await _del_setting(_test_db, "daemon.tick_seconds")


async def test_tick_seconds_garbage_falls_back(_test_db):
    """Нечисловое значение не роняет цикл — возвращается прошлый интервал."""
    daemon = Daemon(_maker(_test_db), runner=None)
    await _set_setting(_test_db, "daemon.tick_seconds", "abc")
    try:
        assert await daemon.tick_seconds(30) == 30
    finally:
        await _del_setting(_test_db, "daemon.tick_seconds")


async def test_tick_seconds_floor_is_one(_test_db):
    """Нулевой/отрицательный интервал зажимается до 1 с."""
    daemon = Daemon(_maker(_test_db), runner=None)
    await _set_setting(_test_db, "daemon.tick_seconds", "0")
    try:
        assert await daemon.tick_seconds(30) == 1
    finally:
        await _del_setting(_test_db, "daemon.tick_seconds")


async def test_max_turns_default_and_from_db(_test_db):
    """daemon.max_turns — настраиваемый лимит ходов заработал (замысел 5867e2a;
    до 30.10.2026 ключ существовал только в комментарии — настройка молча
    не работала, реальный дефолт был 100)."""
    async with _maker(_test_db)() as s:
        cfg = await load_daemon_settings(s)
    assert cfg["daemon.max_turns"] == "200"

    await _set_setting(_test_db, "daemon.max_turns", "350")
    try:
        async with _maker(_test_db)() as s:
            cfg = await load_daemon_settings(s)
    finally:
        await _del_setting(_test_db, "daemon.max_turns")
    assert cfg["daemon.max_turns"] == "350"
