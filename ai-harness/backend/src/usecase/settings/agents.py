"""Пользователи-агенты и матрица назначений (СТ §4.4.3, ФТ-ah-62/63)."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from domain.model.validators import DomainError
from repository.models import AgentProfile, Assignment, TaskType, User


async def _ensure_agent_user(session: AsyncSession, name: str) -> User:
    user = (await session.execute(sa.select(User).where(User.name == name))).scalar_one_or_none()
    if user is None:
        user = User(name=name, user_type="agent")
        session.add(user)
        await session.flush()
    return user


async def create_agent(session: AsyncSession, data: dict) -> User:
    name = (data.get("name") or "").strip()
    if not (1 <= len(name) <= 64):
        raise DomainError("Имя агента: 1–64 символа", field="name")
    if (await session.execute(sa.select(sa.func.count()).select_from(User)
                              .where(User.name == name))).scalar_one():
        raise DomainError(f"Имя {name!r} занято", field="name")
    user = await _ensure_agent_user(session, name)
    profile = AgentProfile(
        user_id=user.id,
        role=data.get("role") or "исполнитель этапа конвейера",
        skill_md=data.get("skill_md") or "",
        connection_id=data.get("connection_id"),
        is_preset=bool(data.get("is_preset")),
        preset_source=data.get("preset_source"),
    )
    session.add(profile)
    await session.commit()
    return user


async def update_agent(session: AsyncSession, user_id: uuid.UUID, fields: dict) -> None:
    profile = (await session.execute(
        sa.select(AgentProfile).where(AgentProfile.user_id == user_id))).scalar_one_or_none()
    if profile is None:
        raise DomainError("Агент не найден")
    for field in ("role", "skill_md", "connection_id"):
        if field in fields:
            setattr(profile, field, fields[field])
    await session.commit()


async def delete_agent(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Удаление запрещено при назначениях — со списком статусов (ФТ-ah-62)."""
    assignments = (await session.execute(
        sa.select(Assignment.task_type_id, Assignment.status_key)
        .where(Assignment.user_id == user_id))).all()
    if assignments:
        usage = ", ".join(f"{type_id}:{status}" for type_id, status in assignments[:10])
        raise DomainError(f"Агент назначен на статусы: {usage} — сначала снимите назначения")
    user = await session.get(User, user_id)
    if user is None:
        raise DomainError("Агент не найден")
    if user.is_service or user.is_chat_bot:
        raise DomainError("Служебные пользователи не удаляются")
    await session.delete(user)
    await session.commit()


async def reset_preset_agent(session: AsyncSession, user_id: uuid.UUID) -> None:
    profile = (await session.execute(
        sa.select(AgentProfile).where(AgentProfile.user_id == user_id))).scalar_one_or_none()
    if profile is None or not profile.is_preset or not profile.preset_source:
        raise DomainError("Сброс доступен только предустановленным агентам")
    profile.role = profile.preset_source.get("role", profile.role)
    profile.skill_md = profile.preset_source.get("skill_md", profile.skill_md)
    await session.commit()


async def set_assignments(session: AsyncSession, task_type_id: uuid.UUID,
                          status_key: str, entries: list[dict]) -> None:
    """entries: [{user_id, mode, position}].

    Семантика постановки: люди назначаются на любой статус; ИИ-агент — только
    на статус, где у него есть работа (исходящее ребро runner
    agent/auto_or_agent). На чисто человеческие статусы (pending → backlog)
    агенты не назначаются — людям там работать можно (ФТ-ah-63)."""
    for e in entries:
        user_id = e.get("user_id") or e.get("userId")
        ut = await session.execute(sa.text(
            'SELECT user_type FROM "user" WHERE id = :i'), {"i": str(user_id)})
        if (ut.scalar_one_or_none() or "human") == "agent":
            await _reject_no_agent_work(session, task_type_id, status_key)
            break
    await session.execute(sa.delete(Assignment).where(
        Assignment.task_type_id == task_type_id, Assignment.status_key == status_key))
    for i, e in enumerate(entries):
        user_id = e.get("user_id") or e.get("userId")
        session.add(Assignment(task_type_id=task_type_id, status_key=status_key,
                               user_id=user_id,
                               mode=e.get("mode", "replacement"),
                               position=e.get("position", i + 1)))
    await session.commit()


async def _reject_no_agent_work(session: AsyncSession, task_type_id: uuid.UUID,
                                status_key: str) -> None:
    """Агенту нечего делать на статусе без агентных рёбер (например, pending)."""
    rows = (await session.execute(sa.text(
        "SELECT ft.runner FROM flow_transition ft "
        "JOIN flow_version fv ON fv.id = ft.flow_version_id "
        "WHERE fv.task_type_id = :t AND fv.is_current AND fv.is_published "
        "AND ft.from_status = :s"), {"t": str(task_type_id), "s": status_key})).all()
    if rows and not any(r[0] in ("agent", "auto_or_agent") for r in rows):
        raise DomainError(
            f"Статус «{status_key}» без агентной работы (только ручные переходы): "
            "назначение агентов отклонено — назначьте здесь человека")


async def reset_preset_agent(session: AsyncSession, user_id: uuid.UUID) -> None:
    profile = (await session.execute(
        sa.select(AgentProfile).where(AgentProfile.user_id == user_id))).scalar_one_or_none()
    if profile is None or not profile.is_preset or not profile.preset_source:
        raise DomainError("Сброс доступен только предустановленным агентам")
    profile.role = profile.preset_source.get("role", profile.role)
    profile.skill_md = profile.preset_source.get("skill_md", profile.skill_md)
    await session.commit()



async def agent_usages(session: AsyncSession, user_id: uuid.UUID) -> list[str]:
    rows = (await session.execute(
        sa.select(TaskType.key, Assignment.status_key)
        .join(TaskType, TaskType.id == Assignment.task_type_id)
        .where(Assignment.user_id == user_id))).all()
    return [f"{key}:{status}" for key, status in rows]
