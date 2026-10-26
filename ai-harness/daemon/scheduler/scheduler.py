"""Планировщик демона: тик, готовые задачи, резерв, запуск агентов (СТ §4.3.1).

Человек работает параллельно, не ожидая демона: ручные операции идут через API,
демон только запускает агентов и ведёт автоматику.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from daemon.config import load_daemon_settings, retry_pauses_minutes
from daemon.runner.reservation import release_reservation, reserve_task
from repository.models import TaskRun


async def active_run_id(session, task_id) -> str:
    """Id активного прогона задачи (для лога прогона)."""
    return (await session.execute(
        sa.select(TaskRun.id)
        .where(TaskRun.task_id == task_id, TaskRun.finished_at.is_(None))
        .order_by(TaskRun.started_at.desc()).limit(1))).scalar_one()

from domain.model.enums import GIT_TASK_TYPES
from repository.models import Assignment, Project, Task, TaskType, User

log = logging.getLogger("daemon")


def _queue_sort(rows: list) -> list:
    """Правила очереди: приоритет → баги выше → старые выше (ФТ-ah-4).
    rows — кортежи (Task, type_key, user_id, mode, position)."""
    rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}

    def key(item):
        task, type_key = item[0], item[1]
        return (rank.get(task.priority, 9),
                0 if type_key == "bug" else 1,
                task.created_at, task.code)

    return sorted(rows, key=key)


async def _next_retry_at(session: AsyncSession, task_id) -> dt.datetime | None:
    """Пауза растущей серии после последней неудачи: 1 → 5 → 15 мин (ФТ-ah-33)."""
    from repository.models import TaskRun

    row = (await session.execute(
        sa.select(TaskRun.finished_at, TaskRun.attempt_no)
        .where(TaskRun.task_id == task_id, TaskRun.outcome == "failed")
        .order_by(TaskRun.finished_at.desc()).limit(1)
    )).first()
    if row is None:
        return None
    cfg = await load_daemon_settings(session)
    pauses = retry_pauses_minutes(cfg)
    attempt = min(row.attempt_no, len(pauses)) - 1
    return row.finished_at + dt.timedelta(minutes=pauses[max(attempt, 0)])


class Daemon:
    def __init__(self, sessionmaker, runner) -> None:
        self._maker = sessionmaker
        self.runner = runner
        self._active: dict[str, asyncio.Task] = {}  # task_code -> asyncio.Task
        self._paused_until: dict[str, dt.datetime] = {}  # connection_id -> until

    async def tick(self) -> dict:
        async with self._maker() as session:
            cfg = await load_daemon_settings(session)
            summary = {"launched": 0, "blocked_no_agent": 0, "mirrored": 0, "heartbeat_lost": 0}
            await self._touch_active(session)
            summary["heartbeat_lost"] = await self._sweep_dead_runs(session, cfg)
            summary["blocked_no_agent"] = await self._block_unassigned(session)
            summary["mirrored"] = await self._tick_mirroring(session)
            summary["launched"] = await self._launch_ready(session, cfg)
            summary["interrupted"] = await self._check_interrupts(session)
            await self._retention_tick(session)
            return summary

    # --- блокировки и автоматика -------------------------------------------

    async def _block_unassigned(self, session: AsyncSession) -> int:
        """Задача на «рабочем» статусе без назначенного агента → blocked (ФТ-ah-63)."""
        rows = (await session.execute(
            sa.select(Task, TaskType.key.label("type_key"))
            .join(TaskType, TaskType.id == Task.task_type_id)
            .where(Task.status_key.notin_(("pending", "backlog", "todo", "blocked",
                                           "done", "canceled")))
        )).all()
        blocked = 0
        for task, type_key in rows:
            has_agent = (await session.execute(
                sa.select(sa.func.count()).select_from(Assignment)
                .join(User, User.id == Assignment.user_id)
                .where(Assignment.task_type_id == task.task_type_id,
                       Assignment.status_key == task.status_key,
                       User.user_type == "agent", User.is_service.is_(False))
            )).scalar_one()
            if has_agent:
                continue
            task.status_key = "blocked"
            task.blocked_reason = f"Нет назначенного агента на статус «{task.status_key}»"
            session.add(_chronicle(task.id, "assignment", "Нет назначенного агента — задача заблокирована"))
            blocked += 1
        await session.commit()
        return blocked

    async def _tick_mirroring(self, session: AsyncSession) -> int:
        """Пересчёт зеркалирования всех живых историй (постановка: каждый тик)."""
        from usecase.story.mirror import recompute_story_mirroring

        stories = (await session.execute(
            sa.select(Task)
            .join(TaskType, TaskType.id == Task.task_type_id)
            .where(TaskType.key == "story",
                   Task.status_key.notin_(("done", "canceled")))
        )).scalars().all()
        changed = 0
        for story in stories:
            if await recompute_story_mirroring(session, story):
                changed += 1
        return changed

    async def _touch_active(self, session: AsyncSession) -> None:
        """Прогоны этого демона живы: обновляем heartbeat (смерть процесса ловит sweep)."""
        if not self._active:
            return
        now = dt.datetime.now(dt.timezone.utc)
        await session.execute(
            sa.text("UPDATE task_run SET heartbeat_at = :n WHERE finished_at IS NULL "
                    "AND task_id IN (SELECT id FROM task WHERE code = ANY(:codes))"),
            {"n": now, "codes": list(self._active.keys())},
        )
        await session.execute(
            sa.text("UPDATE task SET heartbeat_at = :n WHERE reserved_by IS NOT NULL "
                    "AND code = ANY(:codes)"),
            {"n": now, "codes": list(self._active.keys())},
        )
        await session.commit()

    async def _sweep_dead_runs(self, session: AsyncSession, cfg: dict[str, str]) -> int:
        """Потеря heartbeat ≥ 3 интервалов → резерв снят, попытка неудачна (AC-4.3.1.2)."""
        from repository.models import TaskRun

        threshold = dt.timedelta(seconds=30 * 3)
        now = dt.datetime.now(dt.timezone.utc)
        dead = (await session.execute(
            sa.select(TaskRun, Task)
            .join(Task, Task.id == TaskRun.task_id)
            .where(TaskRun.finished_at.is_(None),
                   TaskRun.heartbeat_at < now - threshold)
        )).all()
        lost = 0
        for run, task in dead:
            await release_reservation(session, task.id, "failed",
                                      "heartbeat пропал — возврат в очередь")
            task.retry_count += 1
            session.add(_chronicle(task.id, "heartbeat",
                                   f"Heartbeat пропал — резерв снят (попытка {run.attempt_no})"))
            lost += 1
        if lost:
            await session.commit()
        return lost

    # --- запуск готовых задач ----------------------------------------------

    async def _launch_ready(self, session: AsyncSession, cfg: dict[str, str]) -> int:
        now = dt.datetime.now(dt.timezone.utc)
        rows = (await session.execute(
            sa.select(Task, TaskType.key.label("type_key"))
            .join(TaskType, TaskType.id == Task.task_type_id)
            .outerjoin(Project, Project.id == Task.project_id)
            .where(Task.reserved_by.is_(None),
                   Task.status_key.notin_(("pending", "blocked", "done", "canceled")),
                   Project.is_archived.is_(False))
        )).all()

        # только статусы с назначенным живым агентом (матрица)
        ready = []
        for row in rows:
            task = row.Task
            agent_row = (await session.execute(
                sa.select(Assignment.user_id, Assignment.mode, Assignment.position)
                .join(User, User.id == Assignment.user_id)
                .where(Assignment.task_type_id == task.task_type_id,
                       Assignment.status_key == task.status_key,
                       User.user_type == "agent", User.is_service.is_(False))
                .order_by(Assignment.position)
            )).first()
            if agent_row is None:
                continue
            retry_at = await _next_retry_at(session, task.id)
            if retry_at and retry_at > now:
                continue  # ждёт растущей паузы ретрая
            # массовый отказ провайдера: задачи ждут, не блокируются (ФТ-ah-35)
            from daemon.runner.circuit import paused_connections

            agent_conn = (await session.execute(
                sa.text("SELECT connection_id FROM agent_profile WHERE user_id = :u"),
                {"u": str(agent_row[0])})).scalar_one_or_none()
            paused = await paused_connections(session)
            conn_key = str(agent_conn) if agent_conn else "default"
            if agent_conn is not None and conn_key in paused:
                continue
            ready.append((*row, *agent_row))

        max_attempts = int(cfg["daemon.max_attempts"])
        launched = 0
        for task, type_key, agent_id, mode, position in _queue_sort(ready):
            if task.code in self._active:
                continue
            if task.retry_count >= max_attempts:
                # исчерпание попыток → blocked «требуется участие человека» (ФТ-ah-34)
                task.status_key = "blocked"
                task.blocked_reason = (
                    "Требуется участие человека: исчерпаны попытки "
                    f"({task.retry_count} из {max_attempts}) на статусе «{task.status_key}»")
                session.add(_chronicle(task.id, "exhausted",
                                       f"Автоблокировка: {task.blocked_reason}"))
                await session.commit()
                continue
            if not await reserve_task(session, task.id, agent_id, task.status_key,
                                      attempt_no=task.retry_count + 1):
                continue  # занято другой копией демона
            async def _go(task=task, agent_id=agent_id, status_key=task.status_key):
                await self._run_task(task.code, agent_id, status_key, cfg)
            self._active[task.code] = asyncio.create_task(_go())
            launched += 1
        return launched

    async def _run_task(self, task_code: str, agent_id, status_key: str,
                        cfg: dict[str, str]) -> None:
        """Резерв получен: собрать контекст, запустить агента, применить результат."""
        from usecase.task.transition import TransitionDenied, apply_transition

        async with self._maker() as session:
            try:
                task = (await session.execute(
                    sa.select(Task).where(Task.code == task_code))).scalar_one()
                agent = await session.get(User, agent_id)
                skill = (await session.execute(
                    sa.text("SELECT skill_md FROM agent_profile WHERE user_id = :u"),
                    {"u": str(agent_id)},
                )).scalar_one_or_none() or "Ты исполнитель этапа конвейера."

                worktree = await self._ensure_worktree(session, task)

                from daemon.runner.agent_runner import RunRequest

                run_id = await active_run_id(session, task.id)
                seq = [0]

                async def on_event(kind: str, text: str | None = None,
                                   data: dict | None = None) -> None:
                    from repository.models import TaskRunLog

                    seq[0] += 1
                    async with self._maker() as s:
                        s.add(TaskRunLog(run_id=run_id, seq=seq[0], kind=kind,
                                         text=text, data=data))
                        await s.commit()

                req = RunRequest(
                    task_code=task_code, skill_md=skill,
                    context_md=await self._context_md(session, task),
                    worktree_path=worktree,
                    provider=await self._provider_for(session, agent_id),
                    timeouts={"start": int(cfg["daemon.timeout_start_seconds"]),
                              "work": int(cfg["daemon.timeout_work_seconds"])},
                    on_event=on_event,
                )
                report = await self.runner.run(req)
                from daemon.runner.circuit import record_failure, record_success

                conn_id = (await session.execute(
                    sa.text("SELECT connection_id FROM agent_profile WHERE user_id = :u"),
                    {"u": str(agent_id)})).scalar_one_or_none()
                if run_id:
                    from repository.models import TaskRunLog

                    async with self._maker() as sf:
                        sf.add(TaskRunLog(run_id=run_id, seq=10**6, kind="system",
                                          text=f"прогон завершён: {report.status}"))
                        await sf.commit()
                if report.status == "success":
                    record_success(str(conn_id) if conn_id else None)
                else:
                    record_failure(str(conn_id) if conn_id else None)
                    from daemon.runner.circuit import maybe_trip

                    await maybe_trip(session, str(conn_id) if conn_id else None)
                await self._apply_report(session, task, agent, report, cfg)
            except Exception as err:  # noqa: BLE001 — демон не должен падать
                log.exception("run failed: %s", task_code)
                async with self._maker() as s2:
                    await release_reservation(s2, await task_id_by_code(s2, task_code),
                                              "failed", str(err)[:500])
            finally:
                self._active.pop(task_code, None)

    async def _ensure_worktree(self, session, task):
        from repository.models import Project

        if task.status_key != "in_progress":
            return None
        type_key = (await session.execute(
            sa.text("SELECT key FROM task_type WHERE id = :i"),
            {"i": str(task.task_type_id)})).scalar_one()
        if type_key not in GIT_TASK_TYPES:
            return None
        project = await session.get(Project, task.project_id)
        from pathlib import Path

        from infrastructure.git.worktree import ensure_task_worktree

        return await ensure_task_worktree(project.path, task.code, project.base_branch)

    async def _provider_for(self, session, agent_id) -> dict | None:
        """Расшифрованное подключение агента (ANTHROPIC_* для раннера).
        Расшифровка только здесь и только на момент запуска (СТ §4.4.2)."""
        from repository.models import Connection
        from usecase.settings.connections import get_decrypted_token

        conn_id = (await session.execute(
            sa.text("SELECT connection_id FROM agent_profile WHERE user_id = :u"),
            {"u": str(agent_id)})).scalar_one_or_none()
        conn = await session.get(Connection, conn_id) if conn_id else None
        if conn is None:  # своё подключение не задано — активное глобальное
            conn = (await session.execute(
                sa.select(Connection).where(Connection.is_active.is_(True))
                .limit(1))).scalar_one_or_none()
        if conn is None:
            return None
        return {"protocol": conn.protocol, "url": conn.url, "model": conn.model,
                "token": await get_decrypted_token(session, conn)}

    async def _check_interrupts(self, session) -> int:
        """Перехват человеком: прогон помечен outcome='interrupted' → убить процесс (ФТ-ah-32).
        asyncio.cancel сворачивает итерацию SDK; незавершённый отчёт не применяется."""
        if not self._active:
            return 0
        now = dt.datetime.now(dt.timezone.utc)
        rows = (await session.execute(
            sa.select(TaskRun.task_id)
            .join(Task, Task.id == TaskRun.task_id)
            .where(TaskRun.finished_at.isnot(None),
                   TaskRun.outcome == "interrupted",
                   TaskRun.finished_at >= now - dt.timedelta(minutes=10),
                   Task.code.in_(list(self._active.keys()))))).scalars().all()
        killed = 0
        for task_id in rows:
            code = (await session.execute(
                sa.select(Task.code).where(Task.id == task_id))).scalar_one_or_none()
            t = self._active.pop(code, None) if code else None
            if t is not None and not t.done():
                t.cancel()
                killed += 1
        return killed

    async def _retention_tick(self, session) -> None:
        """Сырые строки живого лога старше 7 дней удаляются; раз в сутки (решение владельца)."""
        from repository.models import AppSetting

        key = "runlog.retention_last"
        today = dt.datetime.now(dt.timezone.utc).date().isoformat()
        last = (await session.execute(
            sa.select(AppSetting.value).where(AppSetting.key == key))).scalar_one_or_none()
        if last == today:
            return
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)
        from repository.models import TaskRunLog

        await session.execute(sa.delete(TaskRunLog).where(TaskRunLog.created_at < cutoff))
        row = (await session.execute(
            sa.select(AppSetting).where(AppSetting.key == key))).scalar_one_or_none()
        if row:
            row.value = today
        else:
            session.add(AppSetting(key=key, value=today))
        await session.commit()

    async def _context_md(self, session, task) -> str:
        from usecase.task.context_bundle import build_context_md

        return await build_context_md(session, task)

    async def _apply_report(self, session, task, agent, report, cfg) -> None:
        from repository.models import Chronicle, Task
        from usecase.task.transition import apply_transition

        task = (await session.execute(
            sa.select(Task).where(Task.code == task.code))).scalar_one()

        session.add(Chronicle(
            task_id=task.id, event_type="agent", author_id=agent.id, author_kind="agent",
            message=f"Отчёт агента: {report.summary_md[:300]}",
        ))
        await self._apply_checklist_updates(session, task, report)

        if report.status == "success" and report.proposed_transition:
            to = report.proposed_transition.get("to")
            try:
                if to == "done" and task.task_type_id:
                    await self._merge_before_done(session, task)
                task = await apply_transition(session, agent, task.code, to)
            except TransitionDenied as denied:
                task.retry_count += 1
                session.add(_chronicle(task.id, "engine",
                                       f"Переход отклонён: {denied.reason}"))
                await release_reservation(session, task.id, "failed", denied.reason)
                return
        elif report.status == "blocked":
            task.status_key = "blocked"
            task.blocked_reason = report.summary_md[:500]
            await release_reservation(session, task.id, "blocked")
            await session.commit()
            return
        else:
            task.retry_count += 1
            await release_reservation(session, task.id, "failed", report.summary_md[:500])
            await session.commit()
            return

        await release_reservation(session, task.id, "success")
        await session.commit()

    async def _apply_checklist_updates(self, session, task, report) -> None:
        for upd in report.checklist_updates:
            kind = upd.get("checklist_kind")
            new_status = upd.get("new_status")
            if not kind or not new_status:
                continue
            if "item_position" in upd:
                await session.execute(sa.text(
                    "UPDATE checklist_item ci SET status = :s FROM checklist c "
                    "WHERE c.id = ci.checklist_id AND c.task_id = :t "
                    "AND c.kind = :k AND ci.position = :p"), {
                        "s": new_status, "t": str(task.id), "k": kind,
                        "p": upd["item_position"]})
            elif upd.get("text"):
                chk = (await session.execute(sa.text(
                    "SELECT id FROM checklist WHERE task_id = :t AND kind = :k"),
                    {"t": str(task.id), "k": kind})).first()
                if chk:
                    pos = (await session.execute(sa.text(
                        "SELECT coalesce(max(position),0)+1 FROM checklist_item "
                        "WHERE checklist_id = :c"), {"c": str(chk[0])})).scalar_one()
                    session.execute(sa.text(
                        "INSERT INTO checklist_item (id, checklist_id, position, kind, text, status) "
                        "VALUES (gen_random_uuid(), :c, :p, 'item', :x, 'todo')"),
                        {"c": str(chk[0]), "p": pos, "x": upd["text"]})
        await session.commit()

    async def _merge_before_done(self, session, task) -> None:
        """Слияние перед done (ФТ-ah-37); конфликт → blocked, человек распутывает."""
        from repository.models import Project

        from infrastructure.git.worktree import GitError, merge_task_branch

        project = await session.get(Project, task.project_id)
        try:
            await merge_task_branch(project.path, task.code, project.base_branch)
        except GitError as err:
            raise TransitionDenied(
                f"Конфликт слияния: распутайте вручную и автомат повторит ({err.stderr[:200]})",
                status_code=200)


async def task_id_by_code(session, code):
    from repository.models import Task

    return (await session.execute(
        sa.select(Task.id).where(Task.code == code))).scalar_one()


def _chronicle(task_id, rule: str, message: str):
    from repository.models import Chronicle

    return Chronicle(task_id=task_id, event_type="agent", author_kind="auto",
                     rule_code=rule, message=message)
