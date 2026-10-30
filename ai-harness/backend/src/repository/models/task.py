"""Задача и её агрегаты: чеклисты, связи, теги, исполнители, артефакты, ветки, прогоны."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, SmallInteger, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from repository.models.base import Base


class Task(Base):
    __tablename__ = "task"
    __table_args__ = (
        Index("idx_task_status", "project_id", "status_key"),
        Index("idx_task_story", "story_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("project.id"))
    code: Mapped[str] = mapped_column(String(16), unique=True)
    task_type_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("task_type.id"))
    title: Mapped[str] = mapped_column(String(64))
    description_md: Mapped[str] = mapped_column(Text)
    status_key: Mapped[str] = mapped_column(String(32))
    flow_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("flow_version.id"))
    priority: Mapped[str] = mapped_column(String(8))
    story_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("task.id"))
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reserved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id"))
    reserved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    psi_path: Mapped[str | None] = mapped_column(String(500))  # путь сохранения psi.md истории (null — дефолт)
    # целевой репозиторий в мультирепозитории проекта (относительный путь)
    repo_path: Mapped[str | None] = mapped_column(String(200))
    retry_count: Mapped[int] = mapped_column(SmallInteger, default=0)
    rework_count: Mapped[int] = mapped_column(SmallInteger, default=0)
    m4_count: Mapped[int] = mapped_column(SmallInteger, default=0)
    blocked_reason: Mapped[str | None] = mapped_column(Text)


class Checklist(Base):
    __tablename__ = "checklist"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("task.id"))
    kind: Mapped[str] = mapped_column(String(16))  # developer|reviewer|tester|psi
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChecklistItem(Base):
    __tablename__ = "checklist_item"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    checklist_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("checklist.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(8), default="item")  # heading|item
    level: Mapped[int | None] = mapped_column(SmallInteger)  # 1..5 для заголовков
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), default="todo")  # todo|in_progress|closed|done|failed
    psi_expected: Mapped[str | None] = mapped_column(Text)
    psi_actual: Mapped[str | None] = mapped_column(Text)
    bug_task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("task.id"))


class TaskRelation(Base):
    """Каноническое направление: do_after | blocked_by; на UI — зеркальный тип."""

    __tablename__ = "task_relation"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    from_task: Mapped[uuid.UUID] = mapped_column(ForeignKey("task.id", ondelete="CASCADE"))
    to_task: Mapped[uuid.UUID] = mapped_column(ForeignKey("task.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(12))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Tag(Base):
    __tablename__ = "tag"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    label: Mapped[str] = mapped_column(String(64), unique=True)
    is_author: Mapped[bool] = mapped_column(Boolean, default=False)  # by_human / by_ai


class TaskTag(Base):
    __tablename__ = "task_tag"

    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("task.id", ondelete="CASCADE"), primary_key=True)
    tag_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tag.id"), primary_key=True)


class TaskAssignee(Base):
    """Единственный источник правды по исполнителям (ФТ-ah-10)."""

    __tablename__ = "task_assignee"

    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("task.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id"), primary_key=True)


class TaskComment(Base):
    __tablename__ = "task_comment"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("task.id", ondelete="CASCADE"))
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TaskArtifact(Base):
    """Артефакт этапа; повторный цикл доработки = новая версия (ФТ-ah-38)."""

    __tablename__ = "task_artifact"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("task.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))  # dev_report|review_report|qa_report
    version: Mapped[int] = mapped_column(Integer, default=1)
    body_md: Mapped[str] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TaskBranch(Base):
    """Ветка задачи task/<task-code> и её worktree (ФТ-ah-37)."""

    __tablename__ = "task_branch"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("task.id"), unique=True)
    branch_name: Mapped[str] = mapped_column(String(64))
    worktree_path: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TaskRun(Base):
    """Прогон агента (решение 25.10.2026): heartbeat/исход — у прогона, не у задачи.
    Позволяет режиму «параллельно» вести несколько одновременных исполнений (AC-4.4.3.1)."""

    __tablename__ = "task_run"
    __table_args__ = (
        Index(
            "uq_task_run_active", "task_id", "agent_id",
            unique=True, postgresql_where=text("finished_at IS NULL"),
        ),
        Index("idx_task_run_task", "task_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("task.id", ondelete="CASCADE"))
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id"))
    status_key: Mapped[str] = mapped_column(String(32))
    attempt_no: Mapped[int] = mapped_column(SmallInteger, default=1)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(String(16))  # success|failed|blocked|interrupted
    detail: Mapped[str | None] = mapped_column(Text)
    # расход токенов прогоном, накопительно (решение владельца 27.10.2026):
    # раннер после каждого хода SDK пишет абсолютные значения — идемпотентно
    input_tokens: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    cache_tokens: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    session_id: Mapped[str | None] = mapped_column(String(64))  # SDK-сессия прогона — для resume (30.10.2026)


# Ссылки на UUID-диалект используются миграциями; держим импорт живым для mypy-полноты
_ = UUID


class TaskRunLog(Base):
    """Строка живого лога прогона агента (решение владельца 26.10.2026):
    промт, размышления, вызовы инструментов — для панели «вкладка Агент».
    Сырые строки чистятся через 7 дней; итоги остаются в хронике."""

    __tablename__ = "task_run_log"
    __table_args__ = (Index("idx_task_run_log_run", "run_id", "seq"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("task_run.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)  # порядок внутри прогона, с 1
    kind: Mapped[str] = mapped_column(String(16))  # prompt|system|thinking|tool|tool_result|report
    text: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
