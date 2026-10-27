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


def _clean_runner_fields(data: dict) -> dict:
    """Нормализует и проверяет опции раннера («мост»): модель, инструменты, MCP, папка агентов.

    Пустые/отсутствующие значения → None (стандартное поведение раннера).
    Папка агентов — путь как на компьютере пользователя; должна существовать."""

    out: dict = {"model": None, "allowed_tools": None, "mcp_servers": None, "agent_dir": None,
                 "skills": None}

    model = (data.get("model") or "").strip()
    if len(model) > 128:
        raise DomainError("Модель: до 128 символов", field="model")
    out["model"] = model or None

    tools = data.get("allowed_tools")
    if tools is not None:
        cleaned = [t.strip() for t in tools if isinstance(t, str) and t.strip()]
        if len(cleaned) > 32 or any(len(t) > 96 or any(ch.isspace() for ch in t) for t in cleaned):
            raise DomainError("Инструменты: до 32 имён без пробелов (Read, Bash, mcp__сервер__инструмент…)",
                              field="allowedTools")
        out["allowed_tools"] = cleaned or None

    servers = data.get("mcp_servers")
    if servers is not None:
        if not isinstance(servers, dict) or len(servers) > 16 or not servers:
            raise DomainError("MCP-серверы: JSON-объект {имя: {url|command…}}, до 16 серверов",
                              field="mcpServers")
        for name, cfg in servers.items():
            if not isinstance(cfg, dict) or not (cfg.get("url") or cfg.get("command")):
                raise DomainError(f"MCP-сервер {name!r}: нужен url (http) или command (stdio)",
                                  field="mcpServers")
        out["mcp_servers"] = servers

    agent_dir = (data.get("agent_dir") or "").strip() or None
    if agent_dir:
        import os

        from infrastructure.paths import host_to_container

        # проверяем существование в координатах той машины, где реально работает backend
        if not os.path.isdir(host_to_container(agent_dir)):
            raise DomainError(f"Папка агентов не найдена: {agent_dir} — укажите существующую "
                              "(например sa-helper/.claude)", field="agentDir")
    out["agent_dir"] = agent_dir

    skills = data.get("skills")
    if skills is not None:
        cleaned = [s.strip() for s in skills if isinstance(s, str) and s.strip()]
        if len(cleaned) > 8:
            raise DomainError("Скиллов на агенте: до 8", field="skills")
        out["skills"] = cleaned or None
    return out


async def _check_skills_in_registry(session: AsyncSession, skills: list[str] | None) -> None:
    """Назначаемые скиллы должны существовать в реестре инструментов."""
    if not skills:
        return
    from repository.models import ToolArtifact

    names = set((await session.execute(
        sa.select(ToolArtifact.name).where(ToolArtifact.kind == "skill",
                                           ToolArtifact.name.in_(skills)))).scalars())
    missing = [s for s in skills if s not in names]
    if missing:
        raise DomainError(f"Скиллов нет в реестре: {', '.join(missing)} — "
                          "просканируйте папку инструментов", field="skills")


async def create_agent(session: AsyncSession, data: dict) -> User:
    name = (data.get("name") or "").strip()
    if not (1 <= len(name) <= 64):
        raise DomainError("Имя агента: 1–64 символа", field="name")
    if (await session.execute(sa.select(sa.func.count()).select_from(User)
                              .where(User.name == name))).scalar_one():
        raise DomainError(f"Имя {name!r} занято", field="name")
    user = await _ensure_agent_user(session, name)
    runner_fields = _clean_runner_fields(data)
    await _check_skills_in_registry(session, runner_fields["skills"])
    profile = AgentProfile(
        user_id=user.id,
        role=data.get("role") or "исполнитель этапа конвейера",
        skill_md=data.get("skill_md") or "",
        connection_id=data.get("connection_id"),
        is_preset=bool(data.get("is_preset")),
        preset_source=data.get("preset_source"),
        **runner_fields,
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
    # опции раннера меняются только явно переданными ключами (пустая строка/JSON = сброс)
    runner = _clean_runner_fields(fields)
    if "skills" in fields:
        await _check_skills_in_registry(session, runner["skills"])
    for key in ("model", "allowed_tools", "mcp_servers", "agent_dir", "skills"):
        if key in fields:
            setattr(profile, key, runner[key])
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


async def agent_usages(session: AsyncSession, user_id: uuid.UUID) -> list[str]:
    rows = (await session.execute(
        sa.select(TaskType.key, Assignment.status_key)
        .join(TaskType, TaskType.id == Assignment.task_type_id)
        .where(Assignment.user_id == user_id))).all()
    return [f"{key}:{status}" for key, status in rows]
