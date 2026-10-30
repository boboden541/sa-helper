"""Зависимости FastAPI: сессия БД и актор запроса."""

from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_sessionmaker


async def get_session() -> AsyncSession:
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        await session.close()


async def _resolve_actor(request: Request, session: AsyncSession) -> "User | None":
    """Актор по куке; без входа и при auth.required=false — первый человек
    (dev-режим этапов 1–3); при auth.required и отсутствии сессии — 401."""
    import sqlalchemy as sa

    from repository.models import User
    from usecase.auth.login import COOKIE_NAME, auth_required, user_for_token

    token = request.cookies.get(COOKIE_NAME, "")
    if token:
        user = await user_for_token(session, token)
        if user is not None:
            return user
    if await auth_required(session):
        from api.middleware.errors import ApiError

        raise ApiError(401, "Требуется вход в систему", tech="no valid session cookie")
    return (await session.execute(
        sa.select(User).where(User.user_type == "human").order_by(User.created_at).limit(1)
    )).scalar_one_or_none()


async def get_actor(request: Request, session: AsyncSession = Depends(get_session)) -> "User":
    """Актор запроса: сессия по httpOnly-cookie (ФТ-ah-73)."""
    return await _resolve_actor(request, session)


async def actor_snapshot(request: Request) -> "User":
    """Актор для долгоживущих ответов (SSE): короткая сессия закрывается сразу
    после разрешения пользователя — dependency-сессия не живёт весь стрим
    (анализ 30.10.2026: idle-in-transaction на 15–30 минут выкупала пул)."""
    from database import get_sessionmaker

    async with get_sessionmaker()() as session:
        return await _resolve_actor(request, session)
