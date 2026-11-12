"""Ядро планировщика: цикл тика и автоматика статусов (СТ §4.3.1).

Человек работает параллельно, не ожидая демона: ручные операции идут через API,
демон только запускает агентов и ведёт автоматику.
"""

from __future__ import annotations

import asyncio
import logging

import sqlalchemy as sa
from repository.models import Assignment, Task, TaskType, User
from sqlalchemy.ext.asyncio import AsyncSession

from daemon.bridge import sync_bridge
from daemon.config import load_daemon_settings
from daemon.scheduler.helpers import (
    _chronicle,
    _next_retry_at,
    active_run_id,
    blocked_reason_from_summary,
    targeted_retry_block,
    task_id_by_code,
)
from daemon.scheduler.launch import LaunchMixin
from daemon.scheduler.reports import ReportMixin
from daemon.scheduler.run import RunMixin
from daemon.scheduler.support import SupportMixin
from daemon.scheduler.ticks import TicksMixin

__all__ = [
    "Daemon",
    "_chronicle",
    "_next_retry_at",
    "active_run_id",
    "blocked_reason_from_summary",
    "targeted_retry_block",
    "task_id_by_code",
]


class Daemon(TicksMixin, LaunchMixin, RunMixin, SupportMixin, ReportMixin):
    def __init__(self, sessionmaker, runner) -> None:
        self._maker = sessionmaker
        self.runner = runner
        # ключ всего — run_id (режим parallel: у задачи несколько одновременных
        # прогонов разных агентов; AC-4.4.3.1, анализ 03.11.2026)
        self._active: dict[str, asyncio.Task] = {}  # run_id -> asyncio.Task
        self._runs: dict[str, dict] = {}  # run_id -> {task_code, status_key, agent_id, task_id}

    async def tick(self) -> dict:
        async with self._maker() as session:
            cfg = await load_daemon_settings(session)
            summary: dict[str, object] = {
                "launched": 0,
                "blocked_no_agent": 0,
                "mirrored": 0,
                "heartbeat_lost": 0,
                "paused": False,
                "bridge": None,
            }
            await self._touch_active(session)
            summary["heartbeat_lost"] = await self._sweep_dead_runs(session, cfg)
            # глобальный пульс демона для compose-healthcheck (анализ 06.11:
            # у daemon-контейнера healthcheck не было вовсе)
            await session.execute(
                sa.text(
                    "INSERT INTO app_setting (key, value) VALUES ('daemon:heartbeat', "
                    "to_char(now() at time zone 'utc', 'YYYY-MM-DD\"T\"HH24:MI:SS.US')) "
                    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
                )
            )
            await session.commit()
            # пауза конвейера (решение владельца 28.10.2026 «подержать задачу
            # в конкретном статусе»): замораживается ВСЯ автоматика статусов —
            # зеркала историй и автоблокировка не исполняются, статусы
            # фиксируются до возобновления. Heartbeat/очистка живут.
            paused = (
                await session.execute(
                    sa.text("SELECT value FROM app_setting WHERE key = 'daemon.paused'")
                )
            ).scalar_one_or_none() == "true"
            summary["paused"] = paused
            if paused:
                summary["launched"] = 0  # рубильник: новых агентов не запускаем
                summary["interrupted"] = await self._check_interrupts(session)
                await self._retention_tick(session)
                return summary
            summary["blocked_no_agent"] = await self._block_unassigned(session)
            summary["mirrored"] = await self._tick_mirroring(session)
            summary["unblocked"] = await self._tick_unblock(session)
            # мост LiteLLM: конфиг маршрутов по openai-подключениям (Шаг 1
            # мультипротокола) — при изменении подключений перезаписывается
            # до запуска новых агентов. Сбой моста не роняет тик (лог + ретрай
            # следующим тиком: хэш обновляется только после успешного рестарта)
            try:
                summary["bridge"] = await sync_bridge(session)
            except Exception as err:  # noqa: BLE001 — мост не должен ронять тик
                logging.getLogger("daemon").warning(
                    "мост LiteLLM: sync не удался (%s) — повтор следующим тиком", err
                )
                summary["bridge"] = "error"
            summary["launched"] = await self._launch_ready(session, cfg)
            summary["interrupted"] = await self._check_interrupts(session)
            await self._retention_tick(session)
            return summary

    async def tick_seconds(self, fallback: int) -> int:
        """Интервал сна цикла из app_setting daemon.tick_seconds (перечитывается
        каждый цикл — правка настройки применяется без перезапуска демона).
        При сбое чтения/нечисловом значении — прошлый интервал."""
        try:
            async with self._maker() as session:
                cfg = await load_daemon_settings(session)
            return max(1, int(cfg["daemon.tick_seconds"]))
        except Exception:  # noqa: BLE001 — конфиг не должен ронять цикл демона
            return fallback

    # --- блокировки и автоматика -------------------------------------------

    async def _block_unassigned(self, session: AsyncSession) -> int:
        """Задача на «рабочем» статусе без назначенного агента → blocked (ФТ-ah-63)."""
        # истории не автоблокируются: их статус выводится зеркалом M1–M6
        # (решение владельца 28.10.2026 — правило только для задач-исполнителей)
        rows = (
            await session.execute(
                sa.select(Task, TaskType.key.label("type_key"))
                .join(TaskType, TaskType.id == Task.task_type_id)
                .where(
                    Task.status_key.notin_(
                        ("pending", "backlog", "todo", "blocked", "done", "canceled")
                    ),
                    TaskType.key != "story",
                )
            )
        ).all()
        blocked = 0
        for task, _type_key in rows:
            has_agent = (
                await session.execute(
                    sa.select(sa.func.count())
                    .select_from(Assignment)
                    .join(User, User.id == Assignment.user_id)
                    .where(
                        Assignment.task_type_id == task.task_type_id,
                        Assignment.status_key == task.status_key,
                        User.user_type == "agent",
                        User.is_service.is_(False),
                    )
                )
            ).scalar_one()
            if has_agent:
                continue
            former = task.status_key  # статус до блокировки — попадёт в сообщение
            from usecase.task.transition import apply_blocked

            await apply_blocked(
                session,
                task,
                None,
                f"Нет назначенного агента на статус «{former}»",
                subject_kind="auto",
                rule_code="AUTO_BLOCK",
            )
            blocked += 1
        await session.commit()
        return blocked
