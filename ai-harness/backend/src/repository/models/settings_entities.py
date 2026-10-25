"""Профили агентов, матрица назначений, подключения провайдеров, пресеты провайдеров."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from repository.models.base import Base


class AgentProfile(Base):
    """Карточка агента (ФТ-ah-62): скилл, роль, своё или активное подключение."""

    __tablename__ = "agent_profile"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(200))
    skill_md: Mapped[str] = mapped_column(Text)
    connection_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("connection.id"))  # NULL = активное
    is_preset: Mapped[bool] = mapped_column(Boolean, default=False)
    preset_source: Mapped[dict | None] = mapped_column(JSONB)  # исходный скилл для сброса


class Assignment(Base):
    """Матрица назначений (ФТ-ah-63): тип → статус → исполнители + режим совместной работы."""

    __tablename__ = "assignment"
    __table_args__ = (UniqueConstraint("task_type_id", "status_key", "user_id", name="uq_assignment"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    task_type_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("task_type.id"))
    status_key: Mapped[str] = mapped_column(String(32))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id"))
    mode: Mapped[str] = mapped_column(String(12), default="replacement")  # parallel|replacement
    position: Mapped[int] = mapped_column(Integer, default=1)  # порядок замещения


class Connection(Base):
    """Подключение провайдера (ФТ-ah-59…61); токен — AES-256-GCM, ровно одно активное.
    Частичный уникальный индекс uq_connection_active создаётся миграцией 0001."""

    __tablename__ = "connection"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    protocol: Mapped[str] = mapped_column(String(16))  # openai|anthropic
    url: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(128))
    token_encrypted: Mapped[bytes] = mapped_column(LargeBinary)  # BYTEA
    token_tail: Mapped[str] = mapped_column(String(8))  # последние 4 символа (НФТ-ah-8)
    check_status: Mapped[str] = mapped_column(String(12), default="unchecked")
    check_error: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProviderPreset(Base):
    """Пресет провайдера: автозаполняет URL (ФТ-ah-59); не путать с пресетом flow."""

    __tablename__ = "provider_preset"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    protocol: Mapped[str] = mapped_column(String(16))
    base_url: Mapped[str] = mapped_column(Text)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=True)
