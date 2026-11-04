"""Тики автоматики: зеркала историй, автовозврат из blocked, свипы.

Вынесено из scheduler.py (рефакторинг 04.11.2026 — лимит 800 строк);
поведение не менялось. Миксин TicksMixin подключается в Daemon (core).
"""

from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from repository.models import Task, TaskRelation, TaskType
from sqlalchemy.ext.asyncio import AsyncSession

from daemon.runner.reservation import release_reservation
from daemon.scheduler.helpers import _chronicle


class TicksMixin:
    async def _tick_mirroring(self, session: AsyncSession) -> int:
        """Пересчёт зеркалирования всех живых историй (постановка: каждый тик)."""
        from usecase.story.mirror import recompute_story_mirroring

        stories = (
            (
                await session.execute(
                    sa.select(Task)
                    .join(TaskType, TaskType.id == Task.task_type_id)
                    .where(TaskType.key == "story", Task.status_key.notin_(("done", "canceled")))
                )
            )
            .scalars()
            .all()
        )
        changed = 0
        for story in stories:
            if await recompute_story_mirroring(session, story):
                changed += 1
        return changed

    async def _tick_unblock(self, session: AsyncSession) -> int:
        """Правило AUTO_UNBLOCK: задача в blocked из-за жёстких связей возвращается
        в работу автоматически, когда последний блокер закрыт (решение владельца
        29.10.2026 — «перевод должен работать по правилам flow», подпись ребра
        «Автоматом или ручное вмешательство»). Природа блокера определяется
        наличием связей blocked_by; задачи без связей (провалы агентов, конфликт
        слияния) остаются человеку — по СТ. Истории не трогаем: их ведут зеркала
        M1/M5. Один переход за вызов, событие с rule_code в хронику."""
        from domain.transition.engine import STAGE_ORDER, Subject, check_edge
        from domain.transition.graph import load_graph
        from repository.models import FlowTransition, FlowVersion
        from usecase.task.gates import load_gate_data
        from usecase.task.transition import TransitionDenied, apply_transition, task_flow_version_id

        rows = (
            await session.execute(
                sa.select(Task, TaskType.key.label("type_key"))
                .join(TaskType, TaskType.id == Task.task_type_id)
                .where(
                    Task.status_key == "blocked",
                    TaskType.key != "story",
                    Task.reserved_by.is_(None),
                )
            )
        ).all()
        returned = 0
        for task, _type_key in rows:
            blockers = (
                (
                    await session.execute(
                        sa.select(Task.code)
                        .join(TaskRelation, TaskRelation.to_task == Task.id)
                        .where(
                            TaskRelation.from_task == task.id,
                            TaskRelation.kind == "blocked_by",
                            Task.status_key.notin_(("done", "canceled")),
                        )
                    )
                )
                .scalars()
                .all()
            )
            if not blockers:
                continue  # природа блокера не зависимости — человеку (СТ)
            still_open = await session.execute(
                sa.select(sa.func.count())
                .select_from(TaskRelation)
                .join(Task, Task.id == TaskRelation.to_task)
                .where(
                    TaskRelation.from_task == task.id,
                    TaskRelation.kind == "blocked_by",
                    Task.status_key.notin_(("done", "canceled")),
                )
            ).scalar_one()
            if still_open:
                continue
            graph = await load_graph(session, await task_flow_version_id(session, task))
            subject = Subject(kind="auto")
            gates = await load_gate_data(session, task)
            edges = (
                (
                    await session.execute(
                        sa.select(FlowTransition.to_status)
                        .join(FlowVersion, FlowVersion.id == FlowTransition.flow_version_id)
                        .where(
                            FlowVersion.task_type_id == task.task_type_id,
                            FlowVersion.is_current.is_(True),
                            FlowVersion.is_published.is_(True),
                            FlowTransition.from_status == "blocked",
                        )
                    )
                )
                .scalars()
                .all()
            )
            # детерминированный выбор: ближайший рабочий статус по порядку стадий
            for target in sorted(set(edges), key=lambda s: STAGE_ORDER.get(s, 99)):
                decision = check_edge(graph, "blocked", target, subject, gates)
                if decision.allowed:
                    try:
                        await apply_transition(
                            session,
                            None,
                            task.code,
                            target,
                            subject_kind="auto",
                            rule_code="AUTO_UNBLOCK",
                            _allow_cascade=False,
                        )
                        session.add(
                            _chronicle(
                                task.id,
                                "auto",
                                f"Блокеры сняты ({', '.join(sorted(set(blockers)))}) — "
                                f"автовозврат из «Заблокировано» в «{target}»",
                            )
                        )
                        await session.commit()
                        returned += 1
                    except TransitionDenied:
                        continue
                    break
        return returned

    async def _touch_active(self, session: AsyncSession) -> None:
        """Прогоны этого демона живы: обновляем heartbeat (смерть процесса ловит sweep)."""
        if not self._active:
            return
        now = dt.datetime.now(dt.timezone.utc)
        run_ids = list(self._active.keys())
        await session.execute(
            sa.text(
                "UPDATE task_run SET heartbeat_at = :n WHERE finished_at IS NULL "
                "AND id = ANY(:rids)"
            ),
            {"n": now, "rids": run_ids},
        )
        codes = sorted({m["task_code"] for m in self._runs.values()})
        await session.execute(
            sa.text(
                "UPDATE task SET heartbeat_at = :n WHERE reserved_by IS NOT NULL "
                "AND code = ANY(:codes)"
            ),
            {"n": now, "codes": codes},
        )
        await session.commit()

    async def _sweep_dead_runs(self, session: AsyncSession, cfg: dict[str, str]) -> int:
        """Потеря heartbeat ≥ 3 тиков → резерв снят, попытка неудачна (AC-4.3.1.2)."""
        from repository.models import TaskRun

        # порог = таймауту старта прогона: пульс — детектор смерти ДЕМОНА,
        # а не отзывчивости SDK (медленный тик под нагрузкой node/стриминга
        # не должен убивать живой прогон; отзывчивость агента ловят таймауты
        # старта/работы). 90 с на практике убивали живые прогоны (VITRINA).
        threshold = dt.timedelta(seconds=max(300, int(cfg.get("daemon.tick_seconds", "30")) * 3))
        now = dt.datetime.now(dt.timezone.utc)
        dead = (
            await session.execute(
                sa.select(TaskRun, Task)
                .join(Task, Task.id == TaskRun.task_id)
                .where(TaskRun.finished_at.is_(None), TaskRun.heartbeat_at < now - threshold)
            )
        ).all()
        lost = 0
        for run, task in dead:
            # по прогону (parallel: у задачи живёт соседний прогон — не трогаем)
            await release_reservation(
                session, task.id, str(run.id), "failed", "heartbeat пропал — возврат в очередь"
            )
            task.retry_count += 1
            session.add(
                _chronicle(
                    task.id,
                    "heartbeat",
                    f"Heartbeat пропал — резерв снят (попытка {run.attempt_no})",
                )
            )
            lost += 1
        if lost:
            await session.commit()
        return lost

    # --- запуск готовых задач ----------------------------------------------
