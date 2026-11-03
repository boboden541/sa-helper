"""Атомарное резервирование задачи демоном (НФТ-ah-6, AC-4.3.1.1).

Два режима матрицы назначений (AC-4.4.3.1):
- exclusive («замещение»): один исполнитель на пару тип×статус — условный
  UPDATE task SET reserved_by … WHERE reserved_by IS NULL, проигравший гонку
  получает rowcount=0;
- parallel («параллельно»): несколько исполнителей ведут задачу одновременно —
  резервом служит строка task_run (частичный индекс uq_task_run_active
  по паре задача×агент физически ловит двойное взятие того же агента);
  task.reserved_by остаётся пустым.
"""

from __future__ import annotations

import datetime as dt
import uuid

import sqlalchemy as sa
from repository.models import Task, TaskRun
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


async def reserve_task(session: AsyncSession, task_id, agent_id,
                       status_key: str, attempt_no: int = 1,
                       mode: str = "exclusive") -> str | None:
    """Id созданного прогона — резерв получен; None — занято (гонка проиграна)."""
    now = dt.datetime.now(dt.timezone.utc)
    if mode == "parallel":
        # свой прогон на агента; двойное взятие того же агента ловит
        # частичный индекс uq_task_run_active (task_id, agent_id)
        try:
            run = TaskRun(task_id=task_id, agent_id=agent_id, status_key=status_key,
                          attempt_no=attempt_no)
            session.add(run)
            await session.execute(
                sa.update(Task).where(Task.id == task_id,
                                      Task.status_key == status_key)
                .values(heartbeat_at=now))
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return None
        return str(run.id)

    # exclusive: условный UPDATE — физически исключает двойное взятие двумя
    # копиями демона; проигравший получает rowcount=0
    result = await session.execute(
        sa.update(Task)
        .where(Task.id == task_id, Task.reserved_by.is_(None),
               Task.status_key == status_key)
        .values(reserved_by=agent_id, reserved_at=now,
                heartbeat_at=now)
    )
    if result.rowcount != 1:
        await session.rollback()
        return None
    run = TaskRun(task_id=task_id, agent_id=agent_id, status_key=status_key,
                  attempt_no=attempt_no)
    session.add(run)
    await session.commit()
    return str(run.id)


async def release_reservation(session: AsyncSession, task_id,
                              run_id: str | None = None, outcome: str = "success",
                              detail: str | None = None,
                              reason_code: str | None = None) -> None:
    """Завершает КОНКРЕТНЫЙ прогон; резерв задачи снимается, только когда
    активных прогонов у задачи не осталось (parallel: соседний прогон
    продолжает жить).

    Совместимость: старые вызовы передавали outcome третьим аргументом
    (release_reservation(s, task_id, "failed", "причина")) — не-UUID в run_id
    трактуем как легаси-вызов и сдвигаем на место outcome/detail."""
    if run_id is not None:
        try:
            uuid.UUID(str(run_id))
        except (ValueError, AttributeError, TypeError):
            if detail is None:
                detail = outcome
            outcome = str(run_id)
            run_id = None
    now = dt.datetime.now(dt.timezone.utc)
    if run_id is None:
        await session.execute(
            sa.update(TaskRun)
            .where(TaskRun.task_id == task_id, TaskRun.finished_at.is_(None))
            .values(finished_at=now, outcome=outcome, detail=detail,
                    reason_code=reason_code))
        await session.execute(
            sa.update(Task)
            .where(Task.id == task_id)
            .values(reserved_by=None, reserved_at=None, heartbeat_at=None))
        await session.commit()
        return
    await session.execute(
        sa.update(TaskRun)
        # run_id бывает и str, и asyncpg-UUID (тесты/вызовы демона) — приводим
        .where(TaskRun.id == (run_id if isinstance(run_id, uuid.UUID)
                              else uuid.UUID(str(run_id))))
        .values(finished_at=now, outcome=outcome, detail=detail,
                reason_code=reason_code))
    # резерв задачи снимаем только когда активных прогонов не осталось
    left = (await session.execute(
        sa.select(sa.func.count()).select_from(TaskRun)
        .where(TaskRun.task_id == task_id, TaskRun.finished_at.is_(None))
    )).scalar_one()
    if left == 0:
        await session.execute(
            sa.update(Task)
            .where(Task.id == task_id)
            .values(reserved_by=None, reserved_at=None, heartbeat_at=None))
    await session.commit()
