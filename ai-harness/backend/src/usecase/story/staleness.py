"""«ПСИ устарел» — события изменения требований истории (контур УИТ, 03.11.2026).

Единственная точка постановки и снятия отметки: ставится фактом изменения
постановки (описание истории, состав дочерних задач) при уже составленном
документе ПСИ; снимается выпуском новой версии документа. Это заметка
человеку и сигнал агенту-составителю, не блокер: конвейер не останавливается.
"""

from __future__ import annotations

import sqlalchemy as sa
from repository.models import Chronicle, PsiDocument, Task
from sqlalchemy.ext.asyncio import AsyncSession


async def mark_psi_stale(session: AsyncSession, story: Task, cause: str) -> bool:
    """Поставить «ПСИ устарел», если документ уже составлен и отметки ещё нет.
    Возвращает True — отметка поставлена этим вызовом."""
    if not story.psi_stale:
        has_doc = (await session.execute(
            sa.select(sa.func.count()).select_from(PsiDocument)
            .where(PsiDocument.story_id == story.id))).scalar_one()
        if not has_doc:
            return False  # ПСИ ещё не было: актуализировать нечего
        story.psi_stale = True
        session.add(Chronicle(
            task_id=story.id, event_type="psi",
            author_kind="auto",
            rule_code="PSI_STALE",
            message=f"Требования изменились ({cause}) — ПСИ устарел, нужна новая версия"))
    return True


async def clear_psi_stale(session: AsyncSession, story: Task, version: int) -> None:
    """Новая версия документа выпущена — требования отражены, отметка снята."""
    if story.psi_stale:
        story.psi_stale = False
        session.add(Chronicle(
            task_id=story.id, event_type="psi", author_kind="auto",
            rule_code="PSI_STALE",
            message=f"ПСИ v{version} отражает актуальные требования — отметка снята"))


async def request_actualize(session: AsyncSession, story: Task) -> bool:
    """Кнопка «Актуализировать ПСИ» (человек/Eve): ставит отметку принудительно —
    документ есть всегда (иначе ПСИ просто ещё не составлен)."""
    story.psi_stale = True
    session.add(Chronicle(
        task_id=story.id, event_type="psi", author_kind="human",
        rule_code="PSI_STALE",
        message="Актуализация ПСИ запрошена вручную — составителю нужна новая версия"))
    return True


async def is_story(session: AsyncSession, task: Task) -> bool:
    from repository.models import TaskType

    return (await session.execute(
        sa.select(TaskType.key).where(TaskType.id == task.task_type_id)
    )).scalar_one_or_none() == "story"
