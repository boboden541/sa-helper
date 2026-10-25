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
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class TaskPatchIn(BaseModel):
    title: str | None = None
    description_md: str | None = Field(default=None, alias="descriptionMd")
    priority: str | None = None
    tags: list[str] | None = None
    if_updated_at: datetime | None = Field(default=None, alias="ifUpdatedAt")
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class GateOut(BaseModel):
    allowed: list[str] = []
    denied: list[dict] = []


class TaskCardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    title: str
    priority: str
    type: str
    status_key: str = Field(alias="statusKey")
    story_code: str | None = Field(default=None, alias="storyCode")
    tags: list[str] = []
    agent: dict | None = None
    gate: GateOut = GateOut()
    changed_by_other: bool | None = Field(default=None, alias="changedByOther", exclude=True)


class TaskListOut(BaseModel):
    total: int
    items: list[TaskCardOut]
