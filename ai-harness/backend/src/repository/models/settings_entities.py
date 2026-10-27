"""Профили агентов, матрица назначений, подключения провайдеров, пресеты провайдеров, реестр инструментов."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from repository.models.base import Base


class ToolArtifact(Base):
    """Карточка инструментария из глобальной папки (вариант 4, решение владельца 27.10.2026):
    команды и скиллы SA-Helper, отслеживаются по sha256 содержимого.
    Файлы только читаются — импорт ничего не перемещает и не изменяет."""

    __tablename__ = "tool_artifact"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(16))  # command | skill
    name: Mapped[str] = mapped_column(String(128))
    rel_path: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("kind", "name", name="uq_tool_artifact_kind_name"),)


class AgentProfile(Base):
    """Карточка агента (ФТ-ah-62): скилл, роль, своё или активное подключение.

    Опции раннера («мост», решение владельца 27.10.2026): модель, инструменты,
    MCP-серверы, папка агентов на компьютере пользователя (копируется в worktree
    как .claude и подхватывается SDK). NULL = стандартное поведение раннера."""

    __tablename__ = "agent_profile"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(200))
    skill_md: Mapped[str] = mapped_column(Text)
    connection_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("connection.id"))  # NULL = активное
    is_preset: Mapped[bool] = mapped_column(Boolean, default=False)
    preset_source: Mapped[dict | None] = mapped_column(JSONB)  # исходный скилл для сброса
    model: Mapped[str | None] = mapped_column(String(128))  # переопределение модели прогона
    allowed_tools: Mapped[list | None] = mapped_column(JSONB)  # None = стандартный набор раннера
    mcp_servers: Mapped[dict | None] = mapped_column(JSONB)  # {имя: {url|command, …}}
    agent_dir: Mapped[str | None] = mapped_column(String(500))  # путь на компьютере пользователя


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
