"""DTO задач: контракты по СТ §4.1.2."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TaskCreateIn(BaseModel):
    project_id: str = Field(alias="projectId")
    type: str
    title: str
    priority: str
    author_tag: str = Field(alias="authorTag")
    tags: list[str] = []
    description_md: str = Field(default="", alias="descriptionMd")
    story_code: str | None = Field(default=None, alias="storyCode")
    psi_path: str | None = Field(default=None, alias="psiPath", max_length=500)
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class TaskPatchIn(BaseModel):
    title: str | None = None
    description_md: str | None = Field(default=None, alias="descriptionMd")
    priority: str | None = None
    psi_path: str | None = Field(default=None, alias="psiPath", max_length=500)
    tags: list[str] | None = None
    if_updated_at: datetime | None = Field(default=None, alias="ifUpdatedAt")
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class GateOut(BaseModel):
    allowed: list[str] = []
    denied: list[dict] = []
    # подписи целей перехода по flow-версии задачи: кастомные статусы
    # («Завершено») показываются на карточке людьми, а не ключами
    labels: dict[str, str] = {}


class TaskCardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    title: str
    priority: str
    type: str
    status_key: str = Field(alias="statusKey")
    project: str = ""
    story_code: str | None = Field(default=None, alias="storyCode")
    psi_path: str | None = Field(default=None, alias="psiPath")
    tags: list[str] = []
    agent: dict | None = None
    tokens_used: int = Field(default=0, alias="tokensUsed")
    gate: GateOut = GateOut()
    changed_by_other: bool | None = Field(default=None, alias="changedByOther", exclude=True)


class TaskListOut(BaseModel):
    total: int
    items: list[TaskCardOut]
