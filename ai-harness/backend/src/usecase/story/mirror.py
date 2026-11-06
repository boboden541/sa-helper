"""Пересчёт статуса истории по дочерним задачам/багам (вызывается демоном на тике
и юзкейсами, меняющими статусы детей)."""

from __future__ import annotations

import sqlalchemy as sa
from domain.mirroring.rules import evaluate
from repository.models import AppSetting, Task, TaskType
from sqlalchemy.ext.asyncio import AsyncSession

from usecase.task.transition import TransitionDenied, apply_transition


async def recompute_story_mirroring(session: AsyncSession, story: Task) -> str | None:
    """Возвращает правило сработавшего перехода ('M1'…) или None; один переход за вызов."""
    type_key = (
        await session.execute(sa.select(TaskType.key).where(TaskType.id == story.task_type_id))
    ).scalar_one_or_none()
    if type_key != "story":
        return None
    children = (
        (await session.execute(sa.select(Task.status_key).where(Task.story_id == story.id)))
        .scalars()
        .all()
    )
    # проверка актуальности ПСИ-плана для правила M3 (ФТ-FNR14-04)
    from usecase.story.reference import psi_plan_ref_version

    plan_ref = await psi_plan_ref_version(session, story.id)
    psi_ready = plan_ref is not None and plan_ref >= (story.ref_version or 1)

    # вердикт «ПСИ-редактора» (ФНР-15 4.8): рёбра M3b/M3c
    from repository.models import Checklist, PsiDocument

    approved = rejected = False
    if story.status_key == "psi_review":
        chk = (
            await session.execute(
                sa.select(Checklist).where(Checklist.task_id == story.id, Checklist.kind == "psi")
            )
        ).scalar_one_or_none()
        latest = (
            await session.execute(
                sa.select(sa.func.max(PsiDocument.version)).where(PsiDocument.story_id == story.id)
            )
        ).scalar_one()
        if chk and latest:
            approved = (
                chk.manager_review_state == "approved" and chk.manager_review_version == latest
            )
            rejected = chk.manager_review_state == "rejected"

    rule = evaluate(
        story.status_key,
        list(children),
        story.blocked_rule,
        psi_ready=psi_ready,
        manager_approved=approved,
        manager_rejected=rejected,
    )
    if rule is None:
        return None
    rule_code, to_status = rule
    try:
        await apply_transition(
            session, None, story.code, to_status, subject_kind="auto", rule_code=rule_code
        )
    except TransitionDenied:
        return None  # ребро отсутствует в версии задачи — пересчёт ничего не меняет
    return rule_code


async def apply_m4(session: AsyncSession, story: Task) -> None:
    """Событийное правило M4: тестирование/ПСИ завершились замечаниями, баги заведены.

    Счётчик циклов по M4; лимит (по умолчанию 5) → blocked «цикл не сходится» (ФТ-ah-36).
    """
    limit = int(
        (
            await session.execute(
                sa.select(AppSetting.value).where(AppSetting.key == "rework.cycle_limit")
            )
        ).scalar_one()
    )
    story.m4_count += 1
    if story.m4_count >= limit:
        story.status_key = "blocked"
        story.blocked_rule = "M4"
        story.blocked_reason = (
            f"Цикл не сходится: {story.m4_count} циклов доработки (лимит {limit}) — "
            "нужно участие человека"
        )
        session.add(_chronicle(story.id, "M4", f"Автоблокировка: {story.blocked_reason}"))
    else:
        if story.status_key != "blocked":
            await apply_transition(
                session, None, story.code, "blocked", subject_kind="auto", rule_code="M4"
            )
        else:
            session.add(
                _chronicle(story.id, "M4", f"Цикл доработки {story.m4_count} (лимит {limit})")
            )
    await session.commit()


def _chronicle(task_id, rule: str, message: str):
    from repository.models import Chronicle

    return Chronicle(
        task_id=task_id,
        event_type="transition",
        author_kind="auto",
        rule_code=rule,
        message=message,
    )
