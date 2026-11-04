"""Сборка карточки задачи (TaskCardOut) — вынесена из контроллера
(анализ 03.11.2026: card_view держал 8 запросов инлайн в роутере)."""

from __future__ import annotations

import sqlalchemy as sa
from api.dto.task_dto import GateOut, TaskCardOut
from domain.model.validators import DomainError
from domain.transition.engine import Subject, allowed_targets
from domain.transition.graph import load_graph
from repository.models import Tag, Task, TaskRelation, TaskTag, User
from sqlalchemy.ext.asyncio import AsyncSession

from usecase.task.gates import load_gate_data
from usecase.task.rights import assigned_statuses
from usecase.task.transition import task_flow_version_id


async def build_task_card(session: AsyncSession, code: str, actor: User) -> TaskCardOut:
    task = (
        await session.execute(sa.select(Task).where(Task.code == code.upper()))
    ).scalar_one_or_none()
    if task is None:
        raise DomainError(f"Задача {code} не найдена", tech="task not found")
    type_key = (
        await session.execute(
            sa.text("SELECT key FROM task_type WHERE id = :id"),
            {"id": str(task.task_type_id)},
        )
    ).scalar_one()

    graph = await load_graph(session, await task_flow_version_id(session, task))
    gates = await load_gate_data(session, task)
    if actor.user_type == "agent" and not actor.is_chat_bot:
        subject = Subject(
            kind="agent",
            user_id=str(actor.id),
            assigned_statuses=await assigned_statuses(session, actor.id, task.task_type_id),
        )
    else:
        subject = Subject(kind="human", user_id=str(actor.id))
    decisions = allowed_targets(graph, task.status_key, subject, gates)

    tags = (
        (
            await session.execute(
                sa.select(Tag.label)
                .join(TaskTag, TaskTag.tag_id == Tag.id)
                .where(TaskTag.task_id == task.id)
            )
        )
        .scalars()
        .all()
    )

    relations = (
        await session.execute(
            sa.select(TaskRelation.id, TaskRelation.kind, Task.code, Task.title)
            .join(Task, Task.id == TaskRelation.to_task)
            .where(TaskRelation.from_task == task.id)
        )
    ).all()
    rel_out = [{"id": str(rid), "kind": k, "code": rc, "title": rt} for rid, k, rc, rt in relations]
    story_code = None
    if task.story_id:
        story_code = (
            await session.execute(sa.select(Task.code).where(Task.id == task.story_id))
        ).scalar_one_or_none()

    from repository.models import TaskRun

    # суммы и разбивка расхода токенов по всем прогонам (фича 30.10.2026:
    # клик по цифре раскрывает вход/выход/кэш)
    tokens_in, tokens_out, tokens_cache = (
        await session.execute(
            sa.select(
                sa.func.coalesce(sa.func.sum(TaskRun.input_tokens), 0),
                sa.func.coalesce(sa.func.sum(TaskRun.output_tokens), 0),
                sa.func.coalesce(sa.func.sum(TaskRun.cache_tokens), 0),
            ).where(TaskRun.task_id == task.id)
        )
    ).one()
    tokens_used = tokens_in + tokens_out + tokens_cache

    # подписи всех статусов flow-версии задачи — для кнопок перехода и форса
    from repository.models import FlowStatus

    status_labels = {
        s.status_key: s.label
        for s in (
            await session.execute(
                sa.select(FlowStatus).where(
                    FlowStatus.flow_version_id == await task_flow_version_id(session, task)
                )
            )
        ).scalars()
    }

    return TaskCardOut(
        code=task.code,
        title=task.title,
        priority=task.priority,
        type=type_key,
        statusKey=task.status_key,
        tags=list(tags),
        descriptionMd=task.description_md,
        storyCode=story_code,
        psiPath=task.psi_path,
        repoPath=task.repo_path,
        tokensUsed=tokens_used,
        tokensInput=tokens_in,
        tokensOutput=tokens_out,
        tokensCache=tokens_cache,
        gate=GateOut(
            allowed=[to for to, d in decisions.items() if d.allowed],
            labels=status_labels,
            denied=[
                {"to": to, "reason": d.reason, "code": d.code}
                for to, d in decisions.items()
                if not d.allowed
            ],
        ),
        createdAt=task.created_at.isoformat(),
        updatedAt=task.updated_at.isoformat(),
        blockedReason=task.blocked_reason,
        relations=rel_out,
    )
