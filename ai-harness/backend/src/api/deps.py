"""Зависимости FastAPI: сессия БД и актор запроса."""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_sessionmaker


async def get_session() -> AsyncSession:
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        await session.close()


async def get_actor(session: AsyncSession = Depends(get_session)) -> "User":
    """Актор этапа 1: первый человек (вход — этап 4, ФТ-ah-73)."""
    import sqlalchemy as sa
    from repository.models import User

    user = (await session.execute(
        sa.select(User).where(User.user_type == "human").order_by(User.created_at).limit(1)
    )).scalar_one_or_none()
    return user
