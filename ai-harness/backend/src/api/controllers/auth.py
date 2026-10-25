"""Контроллер входа/выхода: /api/v1/auth (СТ §4.4.4)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_session
from api.middleware.errors import ApiError
from domain.model.validators import DomainError
from repository.models import User
from usecase.auth.login import COOKIE_NAME, login, logout

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginIn(BaseModel):
    name: str
    password: str
    model_config = ConfigDict(extra="forbid")


class SessionOut(BaseModel):
    user: str
    user_type: str


@router.post("/login", response_model=SessionOut)
async def login_view(payload: LoginIn, response: Response,
                     session: AsyncSession = Depends(get_session)):
    try:
        user, token = await login(session, payload.name, payload.password)
    except DomainError as err:
        raise ApiError(401, err.message)
    response.set_cookie(COOKIE_NAME, token, httponly=True, samesite="lax")
    return SessionOut(user=user.name, user_type=user.user_type)


@router.post("/logout")
async def logout_view(response: Response,
                      session: AsyncSession = Depends(get_session),
                      ai_harness_session: str = ""):
    if ai_harness_session:
        await logout(session, ai_harness_session)
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}
