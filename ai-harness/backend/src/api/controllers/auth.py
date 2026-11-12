"""Контроллер входа/выхода: /api/v1/auth (СТ §4.4.4)."""

from __future__ import annotations

from domain.model.validators import DomainError
from fastapi import APIRouter, Cookie, Depends, Response
from pydantic import BaseModel, ConfigDict
from repository.models import User
from sqlalchemy.ext.asyncio import AsyncSession
from usecase.auth.login import (
    COOKIE_NAME,
    auth_required,
    change_password,
    create_human,
    list_humans,
    login,
    logout,
    set_auth_required,
)

from api.deps import get_actor, get_session
from api.middleware.errors import ApiError

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginIn(BaseModel):
    name: str
    password: str
    model_config = ConfigDict(extra="forbid")


class SessionOut(BaseModel):
    user: str
    user_type: str


@router.post("/login", response_model=SessionOut)
async def login_view(
    payload: LoginIn, response: Response, session: AsyncSession = Depends(get_session)
):
    try:
        user, token = await login(session, payload.name, payload.password)
    except DomainError as err:
        raise ApiError(401, err.message)
    from config import get_settings

    st = get_settings()
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        max_age=st.session_ttl_hours * 3600,
        secure=st.session_cookie_secure,
    )
    return SessionOut(user=user.name, user_type=user.user_type)


@router.post("/logout")
async def logout_view(
    response: Response,
    session: AsyncSession = Depends(get_session),
    ai_harness_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
):
    """Токен сессии читается из httpOnly-куки (раньше — query-параметр:
    серверная сессия не удалялась и жила до конца TTL, анализ 30.10.2026)."""
    if ai_harness_session:
        await logout(session, ai_harness_session)
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


class ChangePasswordIn(BaseModel):
    oldPassword: str
    newPassword: str
    model_config = ConfigDict(extra="forbid")


class UserOut(BaseModel):
    id: str
    name: str
    createdAt: str | None = None


class UserCreateIn(BaseModel):
    name: str
    password: str
    model_config = ConfigDict(extra="forbid")


class AuthRequiredIn(BaseModel):
    enabled: bool
    model_config = ConfigDict(extra="forbid")


@router.post("/change-password")
async def change_password_view(
    payload: ChangePasswordIn,
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(get_actor),
):
    """Смена пароля текущего пользователя (старый пароль обязателен)."""
    try:
        await change_password(session, actor, payload.oldPassword, payload.newPassword)
    except DomainError as err:
        raise ApiError(400, err.message)
    return {"ok": True}


@router.get("/users", response_model=list[UserOut])
async def users_list_view(
    session: AsyncSession = Depends(get_session), actor: User = Depends(get_actor)
):
    """Люди системы — для вкладки «Пользователи»."""
    rows = await list_humans(session)
    return [
        UserOut(
            id=str(u.id),
            name=u.name,
            createdAt=u.created_at.isoformat() if u.created_at else None,
        )
        for u in rows
    ]


@router.post("/users", response_model=UserOut)
async def users_create_view(
    payload: UserCreateIn,
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(get_actor),
):
    """Создание человека с паролем (вход включается «Обязательный вход»)."""
    try:
        u = await create_human(session, payload.name, payload.password)
    except DomainError as err:
        raise ApiError(400, err.message)
    return UserOut(
        id=str(u.id),
        name=u.name,
        createdAt=u.created_at.isoformat() if u.created_at else None,
    )


@router.get("/required")
async def auth_required_view(session: AsyncSession = Depends(get_session)):
    """Состояние обязательного входа (вкладка «Пользователи»)."""
    return {"enabled": await auth_required(session)}


@router.post("/required")
async def auth_required_set_view(
    payload: AuthRequiredIn,
    session: AsyncSession = Depends(get_session),
):
    """Включение/выключение обязательного входа (app_setting auth.required).

    Без get_actor — бутстрап-рубильник: с включенным входом сессия нужна уже
    для ВСЕГО, включая выключение; анонимное включение допустимо, пока вход
    выключен (тот же уровень доверия, что весь dev-режим)."""
    await set_auth_required(session, payload.enabled)
    return {"enabled": payload.enabled}
