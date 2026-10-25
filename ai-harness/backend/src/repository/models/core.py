"""Проекты, пользователи, типы задач, настройки, сессии."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from repository.models.base import Base


class Project(Base):
    __tablename__ = "project"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64))
    mnemonic: Mapped[str] = mapped_column(String(10), unique=True)
    path: Mapped[str] = mapped_column(Text)
    base_branch: Mapped[str] = mapped_column(String(128), default="main")
    description: Mapped[str | None] = mapped_column(Text)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    next_number: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DeadMnemonic(Base):
    """Мнемоники удалённых проектов не переиспользуются (ФТ-ah-47)."""

    __tablename__ = "dead_mnemonic"

    mnemonic: Mapped[str] = mapped_column(String(10), primary_key=True)


class User(Base):
    __tablename__ = "user"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    user_type: Mapped[str] = mapped_column(String(8))  # human | agent
    is_chat_bot: Mapped[bool] = mapped_column(Boolean, default=False)  # true только у Eve
    is_service: Mapped[bool] = mapped_column(Boolean, default=False)  # служебный system
    password_hash: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TaskType(Base):
    __tablename__ = "task_type"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(24), unique=True)
    label: Mapped[str] = mapped_column(String(64))
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)


class AppSetting(Base):
    __tablename__ = "app_setting"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Session(Base):
    """Сессии входа (ФТ-ah-73): хранится только хэш токена."""

    __tablename__ = "session"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
