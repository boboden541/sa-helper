"""Вход/выход: локальные учётные записи, httpOnly-cookie сессии (СТ §4.4.4)."""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from domain.model.validators import DomainError
from infrastructure.crypto.argon2_hash import verify_password
from repository.models import Session, User

COOKIE_NAME = "ai_harness_session"


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def login(session: AsyncSession, name: str, password: str) -> tuple[User, str]:
    """Единый отказ без раскрытия существования пользователя (AC-4.4.4.1)."""
    user = (await session.execute(
        sa.select(User).where(User.name == name, User.user_type == "human")
    )).scalar_one_or_none()
    if user is None or not user.password_hash or not verify_password(user.password_hash, password):
        raise DomainError("Неверное имя или пароль", tech="unified auth failure")
    token = secrets.token_urlsafe(32)
    ttl = dt.timedelta(hours=get_settings().session_ttl_hours)
    session.add(Session(user_id=user.id, token_hash=_token_hash(token),
                        expires_at=dt.datetime.now(dt.timezone.utc) + ttl))
    await session.commit()
    return user, token


async def logout(session: AsyncSession, token: str) -> None:
    await session.execute(sa.delete(Session).where(Session.token_hash == _token_hash(token)))
    await session.commit()


async def user_for_token(session: AsyncSession, token: str) -> User | None:
    if not token:
        return None
    sess = (await session.execute(
        sa.select(Session).where(Session.token_hash == _token_hash(token))
    )).scalar_one_or_none()
    if sess is None or sess.expires_at < dt.datetime.now(dt.timezone.utc):
        return None
    return await session.get(User, sess.user_id)


async def auth_required(session: AsyncSession) -> bool:
    """Включатель обязательного входа (app_setting auth.required; AC-4.4.4.3)."""
    from repository.models import AppSetting

    value = (await session.execute(
        sa.select(AppSetting.value).where(AppSetting.key == "auth.required")
    )).scalar_one_or_none()
    return (value or "false").lower() == "true"
