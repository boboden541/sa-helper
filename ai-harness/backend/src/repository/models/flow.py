"""Версии flow, статусы, переходы, alias-колонки, пресеты flow."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from repository.models.base import Base


class AliasColumn(Base):
    __tablename__ = "alias_column"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    label: Mapped[str] = mapped_column(String(32))
    color: Mapped[str] = mapped_column(String(7), default="#888888")
    position: Mapped[int] = mapped_column(Integer)


class FlowVersion(Base):
    """Публикация создаёт новую строку (ФТ-ah-56).
    is_published=false — единственная рабочая копия типа (решение 25.10.2026)."""

    __tablename__ = "flow_version"
    __table_args__ = (UniqueConstraint("task_type_id", "version", name="uq_flow_version"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    task_type_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("task_type.id"))
    version: Mapped[int] = mapped_column(Integer)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FlowStatus(Base):
    __tablename__ = "flow_status"
    __table_args__ = (UniqueConstraint("flow_version_id", "status_key", name="uq_flow_status_key"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    flow_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("flow_version.id", ondelete="CASCADE"))
    status_key: Mapped[str] = mapped_column(String(32))
    label: Mapped[str] = mapped_column(String(64))
    stage_desc: Mapped[str | None] = mapped_column(String(2000))
    checklist_gate: Mapped[str | None] = mapped_column(String(16))  # developer|reviewer|tester
    is_entry: Mapped[bool] = mapped_column(Boolean, default=False)
    is_terminal: Mapped[bool] = mapped_column(Boolean, default=False)
    is_blocking: Mapped[bool] = mapped_column(Boolean, default=False)
    alias_column_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("alias_column.id"))


class FlowTransition(Base):
    __tablename__ = "flow_transition"
    __table_args__ = (UniqueConstraint("flow_version_id", "from_status", "to_status", name="uq_flow_transition"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    flow_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("flow_version.id", ondelete="CASCADE"))
    from_status: Mapped[str] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32))
    runner: Mapped[str] = mapped_column(String(16))  # human|agent|auto|auto_or_agent
    display: Mapped[str] = mapped_column(String(64))
    cond_checklist: Mapped[bool] = mapped_column(Boolean, default=True)
    cond_links: Mapped[bool] = mapped_column(Boolean, default=True)
    cond_artifact: Mapped[bool] = mapped_column(Boolean, default=False)
    rule_code: Mapped[str | None] = mapped_column(String(16))  # M1…M6, MIG, DENY — для автомата


class FlowPreset(Base):
    __tablename__ = "flow_preset"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    definition: Mapped[str] = mapped_column(Text)  # YAML
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
