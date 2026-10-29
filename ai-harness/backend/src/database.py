"""Асинхронный движок и фабрика сессий (общие для API и демона)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def init_engine(database_url: str) -> AsyncEngine:
    global _engine, _sessionmaker
    connect_args = {}
    if database_url.startswith("postgresql"):
        # Страховка от утечки транзакций: idle-in-transaction дольше 5 минут
        # рвётся сервером, а не стоит за блокировками и не замораживает тики
        # демона (инцидент 29.10.2026: _run_task держал транзакцию на весь
        # прогон агента — демон замер на 15 минут, пульс и свип встали).
        connect_args["server_settings"] = {"idle_in_transaction_session_timeout": "300000"}
    _engine = create_async_engine(database_url, pool_pre_ping=True,
                                  connect_args=connect_args)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_engine() -> AsyncEngine:
    if _engine is None:
        from config import get_settings

        init_engine(get_settings().database_url)
    return _engine  # type: ignore[return-value]


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        get_engine()
    return _sessionmaker  # type: ignore[return-value]


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
