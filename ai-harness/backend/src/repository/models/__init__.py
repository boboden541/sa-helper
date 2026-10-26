"""Все ORM-модели: импорт регистрирует метаданные для Alembic autogenerate."""

from repository.models.base import Base
from repository.models.core import AppSetting, DeadMnemonic, Project, Session, TaskType, User
from repository.models.flow import AliasColumn, FlowPreset, FlowStatus, FlowTransition, FlowVersion
from repository.models.journal import (
    ChatMessage,
    Chronicle,
    ChroniclePayload,
    Notification,
    PsiDocument,
    PsiRun,
    PsiRunItem,
    SettingsJournal,
)
from repository.models.settings_entities import AgentProfile, Assignment, Connection, ProviderPreset
from repository.models.task import (
    Checklist,
    ChecklistItem,
    Task,
    TaskArtifact,
    TaskAssignee,
    TaskBranch,
    TaskComment,
    TaskRelation,
    TaskRun,
    TaskRunLog,
    Tag,
    TaskTag,
)

__all__ = [
    "Base",
    "AppSetting", "DeadMnemonic", "Project", "Session", "TaskType", "User",
    "AliasColumn", "FlowPreset", "FlowStatus", "FlowTransition", "FlowVersion",
    "ChatMessage", "Chronicle", "ChroniclePayload", "Notification",
    "PsiDocument", "PsiRun", "PsiRunItem", "SettingsJournal",
    "AgentProfile", "Assignment", "Connection", "ProviderPreset",
    "Checklist", "ChecklistItem", "Task", "TaskArtifact", "TaskAssignee",
    "TaskBranch", "TaskComment", "TaskRelation", "TaskRun", "TaskRunLog", "Tag", "TaskTag",
]
