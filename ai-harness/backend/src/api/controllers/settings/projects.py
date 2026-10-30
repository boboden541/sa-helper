"""Проекты: CRUD, архив, репозитории, пользователи (расщепление settings.py, B1)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_actor, get_session
from api.middleware.errors import ApiError
from domain.model.validators import DomainError
from repository.models import Project, User
from usecase.settings import projects as projects_uc

router = APIRouter()


# ---------- проекты ----------

class ProjectIn(BaseModel):
    name: str | None = None
    mnemonic: str | None = None
    path: str | None = None
    baseBranch: str | None = None
    description: str | None = None
    model_config = ConfigDict(extra="forbid")


@router.get("/projects")
async def projects_list(session: AsyncSession = Depends(get_session),
                        actor: User = Depends(get_actor)):
    import sqlalchemy as sa

    from repository.models import Task

    rows = (await session.execute(sa.select(Project).order_by(Project.mnemonic))).scalars().all()
    # открытые задачи: все типы, статусы не терминальные по flow-версии самой
    # задачи (решение владельца 28.10.2026 — жёсткий список done/canceled
    # ломал счётчик при кастомных статусных моделях)
    from repository.models import FlowStatus, FlowVersion

    fs = FlowStatus.__table__
    fvw = FlowVersion.__table__
    counts = dict((await session.execute(
        sa.select(Project.mnemonic, sa.func.count(Task.id))
        .join(Task, Task.project_id == Project.id)
        .outerjoin(fvw, sa.and_(fvw.c.task_type_id == Task.task_type_id,
                                fvw.c.is_current.is_(True),
                                fvw.c.is_published.is_(True)))
        .outerjoin(fs, sa.and_(fs.c.flow_version_id == fvw.c.id,
                               fs.c.status_key == Task.status_key))
        .where(sa.or_(fs.c.is_terminal.is_(None), fs.c.is_terminal.is_(False)))
        .group_by(Project.mnemonic))).all())
    return [{"id": str(p.id), "name": p.name, "mnemonic": p.mnemonic, "path": p.path,
             "baseBranch": p.base_branch, "isArchived": p.is_archived,
             "description": p.description,
             "openCount": counts.get(p.mnemonic, 0)} for p in rows]


@router.post("/projects")
async def projects_create(payload: ProjectIn,
                          session: AsyncSession = Depends(get_session),
                          actor: User = Depends(get_actor)):
    try:
        p = await projects_uc.create_project(session, projects_uc.ProjectInput(
            name=payload.name or "", mnemonic=payload.mnemonic or "",
            path=payload.path or "", base_branch=payload.baseBranch or "main",
            description=payload.description))
    except DomainError as err:
        raise ApiError(400, err.message, tech=err.tech)
    return {"id": str(p.id), "mnemonic": p.mnemonic}


@router.patch("/projects/{project_id}")
async def projects_update(project_id: str, payload: ProjectIn,
                          session: AsyncSession = Depends(get_session),
                          actor: User = Depends(get_actor)):
    import uuid as uuid_mod

    try:
        await projects_uc.update_project(session, uuid_mod.UUID(project_id),
                                         payload.model_dump(exclude_none=True))
    except DomainError as err:
        raise ApiError(400, err.message)
    return {"ok": True}


@router.post("/projects/{project_id}/archive")
async def projects_archive(project_id: str, archived: bool = True,
                           session: AsyncSession = Depends(get_session),
                           actor: User = Depends(get_actor)):
    import uuid as uuid_mod

    try:
        await projects_uc.set_archived(session, uuid_mod.UUID(project_id), archived)
    except DomainError as err:
        raise ApiError(400, err.message)
    return {"ok": True}


@router.delete("/projects/{project_id}")
async def projects_delete(project_id: str, session: AsyncSession = Depends(get_session),
                          actor: User = Depends(get_actor)):
    import uuid as uuid_mod

    try:
        await projects_uc.delete_project(session, uuid_mod.UUID(project_id))
    except DomainError as err:
        raise ApiError(400, err.message)
    return {"ok": True}


@router.get("/projects/{key}/repos")
async def project_repos(key: str, session: AsyncSession = Depends(get_session),
                        actor: User = Depends(get_actor)):
    """Git-репозитории внутри папки проекта (мультирепозиторий, решение
    владельца 29.10.2026). Корень-репозиторий (если проект — одиночный репо)
    возвращается первым с repoPath=null."""
    import os
    import uuid as uuid_mod
    from pathlib import Path

    import sqlalchemy as sa

    proj = None
    if key.upper() == key and len(key) <= 10:  # мнемоника
        proj = (await session.execute(
            sa.select(Project).where(Project.mnemonic == key.upper()))).scalar_one_or_none()
    if proj is None:
        try:
            proj = await session.get(Project, uuid_mod.UUID(key))
        except ValueError:
            proj = None
    if proj is None:
        raise ApiError(404, f"Проект {key!r} не найден")

    from infrastructure.paths import host_to_container

    root = Path(host_to_container(proj.path))
    repos: list[dict] = []
    if (root / ".git").exists():
        repos.append({"label": f"{proj.name} (корень)", "repoPath": None})
    try:
        for child in sorted(root.iterdir()):
            if child.is_dir() and (child / ".git").exists():
                repos.append({"label": child.name, "repoPath": child.name})
    except OSError:
        pass
    return {"repos": repos}


@router.get("/users")
async def users_list(session: AsyncSession = Depends(get_session),
                     actor: User = Depends(get_actor)):
    """Единый список людей и агентов (ФТ-ah-72) — матрица назначений и адресаты."""
    import sqlalchemy as sa

    rows = (await session.execute(
        sa.select(User).where(User.is_service.is_(False))
        .order_by(User.user_type, User.name))).scalars().all()
    return [{"id": str(u.id), "name": u.name, "userType": u.user_type,
             "isChatBot": u.is_chat_bot} for u in rows]
