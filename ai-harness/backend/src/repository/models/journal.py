"""Хроники, ПСИ, уведомления, журнал настроек, чат Eve."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, SmallInteger, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from repository.models.base import Base


class ChroniclePayload(Base):
    """Тяжёлое содержимое (промты, мысли агента); ретеншн 90 дней (ФТ-ah-44)."""

    __tablename__ = "chronicle_payload"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    body: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Chronicle(Base):
    """Единый журнал задачи: одно событие — одна запись (ФТ-ah-43)."""

    __tablename__ = "chronicle"
    __table_args__ = (Index("idx_chronicle_task", "task_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("task.id", ondelete="CASCADE"))
    event_type: Mapped[str] = mapped_column(String(16))  # field|transition|force|agent|denied|psi|bug
    author_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id"))
    author_kind: Mapped[str] = mapped_column(String(8))  # human|agent|eve|auto
    rule_code: Mapped[str | None] = mapped_column(String(16))  # обязателен для author_kind=auto
    message: Mapped[str] = mapped_column(Text)
    payload_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chronicle_payload.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PsiDocument(Base):
    """Документ ПСИ истории с версиями (ФТ-ah-39)."""

    __tablename__ = "psi_document"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    story_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("task.id"))
    version: Mapped[int] = mapped_column(Integer)
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PsiRun(Base):
    """Прогон ПСИ: счётчики протокола (ФТ-ah-41); пункты — в psi_run_item."""

    __tablename__ = "psi_run"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    psi_doc_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("psi_document.id"))
    run_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id"))
    passed: Mapped[int] = mapped_column(SmallInteger)
    failed: Mapped[int] = mapped_column(SmallInteger)
    ran_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PsiRunItem(Base):
    """Снапшот пунктов прогона: протокол самодостаточен и не зависит
    от сброса чеклиста новым циклом (ФТ-ah-41, решение 25.10.2026)."""

    __tablename__ = "psi_run_item"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    psi_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("psi_run.id", ondelete="CASCADE"))
    item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("checklist_item.id"))
    position: Mapped[int] = mapped_column(Integer)
    item_text: Mapped[str] = mapped_column(Text)
    expected: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12))  # todo|done|failed
    actual: Mapped[str | None] = mapped_column(Text)


class Notification(Base):
    """Уведомление «система ждёт человека»; снимается при разрешении состояния (ФТ-ah-45)."""

    __tablename__ = "notification"
    __table_args__ = (
        Index(
            "uq_notification_open", "code", "event_key",
            unique=True, postgresql_where=text("resolved_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(16))  # task-code источника состояния
    recipient_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id"))  # NULL = всем людям проекта
    event_key: Mapped[str] = mapped_column(String(32))  # ключ одного из 9 событий контракта
    message: Mapped[str] = mapped_column(Text)
    tech_detail: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SettingsJournal(Base):
    """Журнал настроек: полный диф старое/новое (ФТ-ah-64); секреты — только маски."""

    __tablename__ = "settings_journal"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    who_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id"))
    entity: Mapped[str] = mapped_column(String(32))  # flow|connection|agent|matrix|project|board
    summary: Mapped[str] = mapped_column(Text)
    diff: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChatMessage(Base):
    """История диалогов Eve (ФТ-ah-50); task_code — контекст экрана, если распознан."""

    __tablename__ = "chat_message"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id"))
    role: Mapped[str] = mapped_column(String(12))  # user|assistant
    body: Mapped[str] = mapped_column(Text)
    task_code: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
