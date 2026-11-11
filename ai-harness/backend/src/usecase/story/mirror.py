"""Пересчёт статуса истории по дочерним задачам/багам (вызывается демоном на тике
и юзкейсами, меняющими статусы детей)."""

from __future__ import annotations

import sqlalchemy as sa
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
    # ФНР-16: семантика автопереходов — данные на рёбрах (when), движок универсальный.
    # Факты для предикатов собираются в MirrorCtx пачкой (без N+1).
    from domain.mirroring.ctx import MirrorCtx
    from domain.mirroring.engine import find_mirror_transition
    from repository.models import Checklist, PsiDocument

    from usecase.story.reference import psi_plan_ref_version
    from usecase.task.transition import task_flow_version_id

    plan_ref = await psi_plan_ref_version(session, story.id)
    manager_state = manager_review_version = manager_latest = None
    if story.status_key == "psi_review":
        chk = (
            await session.execute(
                sa.select(Checklist).where(Checklist.task_id == story.id, Checklist.kind == "psi")
            )
        ).scalar_one_or_none()
        manager_latest = (
            await session.execute(
                sa.select(sa.func.max(PsiDocument.version)).where(PsiDocument.story_id == story.id)
            )
        ).scalar_one()
        if chk:
            manager_state = chk.manager_review_state
            manager_review_version = chk.manager_review_version

    ctx = MirrorCtx(
        story_status=story.status_key,
        children=list(children),
        blocked_rule=story.blocked_rule,
        ref_version=story.ref_version or 1,
        psi_plan_ref=plan_ref,
        manager_state=manager_state,
        manager_review_version=manager_review_version,
        manager_latest=manager_latest,
        story_kind=type_key,
    )
    rule = await find_mirror_transition(
        session, story, await task_flow_version_id(session, story), ctx
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
    raw = (
        await session.execute(
            sa.select(AppSetting.value).where(AppSetting.key == "rework.cycle_limit")
        )
    ).scalar_one_or_none()
    # настройка живёт только в сиде: чистая установка без сидов → NoResultFound 500
    # — дефолт 5 из сигнатуры правила (ФТ-ah-36) вместо падения (анализ 11.11.2026)
    try:
        limit = int(str(raw).strip()) if raw not in (None, "") else 5
    except ValueError:
        limit = 5
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
