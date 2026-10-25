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


async def get_actor(request: Request, session: AsyncSession = Depends(get_session)) -> "User":
    """Актор запроса: сессия по httpOnly-cookie (ФТ-ah-73); без входа и при
    auth.required=false — первый человек (dev-режим этапа 1–3); иначе 401."""
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
