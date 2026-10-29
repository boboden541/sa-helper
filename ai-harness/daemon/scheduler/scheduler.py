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


async def active_run_id(session, task_id) -> str | None:
    """Id активного прогона задачи (для лога прогона); None — активного нет."""
    return (await session.execute(
        sa.select(TaskRun.id)
        .where(TaskRun.task_id == task_id, TaskRun.finished_at.is_(None))
        .order_by(TaskRun.started_at.desc()).limit(1))).scalar_one_or_none()

from domain.model.enums import GIT_TASK_TYPES
from repository.models import Assignment, Project, Task, TaskRelation, TaskType, User

log = logging.getLogger("daemon")


PRIORITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _queue_sort(rows: list) -> list:
    """Правила очереди: приоритет → баги выше → старые выше (ФТ-ah-4).
    rows — кортежи (Task, type_key, user_id, mode, position).
    Для зависимости-осознанного порядка _launch_ready сортирует сам (см. _dep_key)."""
    rank = PRIORITY_RANK

    def key(item):
        task, type_key = item[0], item[1]
        return (rank.get(task.priority, 9),
                0 if type_key == "bug" else 1,
                task.created_at, task.code)

    return sorted(rows, key=key)


async def _next_retry_at(session: AsyncSession, task_id, status_key: str,
                         cfg: dict[str, str]) -> dt.datetime | None:
    """Пауза перед повторным запуском (ФТ-ah-33): растущая серия 1 → 5 → 15 мин.

    Особые исходы (без выжигания попыток):
    - перехват человеком (interrupted) — максимальная пауза: у человека тихое окно,
      чтобы забрать задачу себе, а демон не перезапускал агента у него из рук;
    - успех без перехода (тот же статус) — максимальная пауза: агент отчитался,
      но ничего не изменил; повтор сразу же означал бы вечный цикл."""
    from repository.models import TaskRun

    row = (await session.execute(
        sa.select(TaskRun.finished_at, TaskRun.attempt_no,
                  TaskRun.outcome, TaskRun.status_key)
        .where(TaskRun.task_id == task_id,
               TaskRun.outcome.in_(("failed", "interrupted", "success")))
        .order_by(TaskRun.finished_at.desc()).limit(1)
    )).first()
    if row is None:
        return None
    pauses = retry_pauses_minutes(cfg)
    if row.outcome in ("interrupted", "success") and (
            row.outcome == "interrupted" or row.status_key == status_key):
        return row.finished_at + dt.timedelta(minutes=pauses[-1])
    attempt = min(row.attempt_no, len(pauses)) - 1
    return row.finished_at + dt.timedelta(minutes=pauses[max(attempt, 0)])


class Daemon:
    def __init__(self, sessionmaker, runner) -> None:
        self._maker = sessionmaker
        self.runner = runner
        self._active: dict[str, asyncio.Task] = {}  # task_code -> asyncio.Task
        self._active_runs: dict[str, str] = {}  # task_code -> run_id текущего прогона
        self._paused_until: dict[str, dt.datetime] = {}  # connection_id -> until

    async def tick(self) -> dict:
        async with self._maker() as session:
            cfg = await load_daemon_settings(session)
            summary = {"launched": 0, "blocked_no_agent": 0, "mirrored": 0,
                       "heartbeat_lost": 0, "paused": False}
            await self._touch_active(session)
            summary["heartbeat_lost"] = await self._sweep_dead_runs(session, cfg)
            # пауза конвейера (решение владельца 28.10.2026 «подержать задачу
            # в конкретном статусе»): замораживается ВСЯ автоматика статусов —
            # зеркала историй и автоблокировка не исполняются, статусы
            # фиксируются до возобновления. Heartbeat/очистка живут.
            paused = (await session.execute(sa.text(
                "SELECT value FROM app_setting WHERE key = 'daemon.paused'"
            ))).scalar_one_or_none() == "true"
            summary["paused"] = paused
            if paused:
                summary["launched"] = 0  # рубильник: новых агентов не запускаем
                summary["interrupted"] = await self._check_interrupts(session)
                await self._retention_tick(session)
                return summary
            summary["blocked_no_agent"] = await self._block_unassigned(session)
            summary["mirrored"] = await self._tick_mirroring(session)
            summary["unblocked"] = await self._tick_unblock(session)
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
        rows = (await session.execute(
            sa.select(Task, TaskType.key.label("type_key"))
            .join(TaskType, TaskType.id == Task.task_type_id)
            .where(Task.status_key.notin_(("pending", "backlog", "todo", "blocked",
                                           "done", "canceled")),
                   TaskType.key != "story")
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
            former = task.status_key  # статус до блокировки — попадёт в сообщение
            task.status_key = "blocked"
            task.blocked_reason = f"Нет назначенного агента на статус «{former}»"
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
        from usecase.task.transition import TransitionDenied, apply_transition, \
            task_flow_version_id

        rows = (await session.execute(
            sa.select(Task, TaskType.key.label("type_key"))
            .join(TaskType, TaskType.id == Task.task_type_id)
            .where(Task.status_key == "blocked", TaskType.key != "story",
                   Task.reserved_by.is_(None)))).all()
        returned = 0
        for task, type_key in rows:
            blockers = (await session.execute(
                sa.select(Task.code)
                .join(TaskRelation, TaskRelation.to_task == Task.id)
                .where(TaskRelation.from_task == task.id,
                       TaskRelation.kind == "blocked_by",
                       Task.status_key.notin_(("done", "canceled"))))).scalars().all()
            if not blockers:
                continue  # природа блокера не зависимости — человеку (СТ)
            still_open = (await session.execute(
                sa.select(sa.func.count()).select_from(TaskRelation)
                .join(Task, Task.id == TaskRelation.to_task)
                .where(TaskRelation.from_task == task.id,
                       TaskRelation.kind == "blocked_by",
                       Task.status_key.notin_(("done", "canceled")))).scalar_one())
            if still_open:
                continue
            graph = await load_graph(session, await task_flow_version_id(session, task))
            subject = Subject(kind="auto")
            gates = await load_gate_data(session, task)
            edges = (await session.execute(
                sa.select(FlowTransition.to_status)
                .join(FlowVersion, FlowVersion.id == FlowTransition.flow_version_id)
                .where(FlowVersion.task_type_id == task.task_type_id,
                       FlowVersion.is_current.is_(True),
                       FlowVersion.is_published.is_(True),
                       FlowTransition.from_status == "blocked"))).scalars().all()
            # детерминированный выбор: ближайший рабочий статус по порядку стадий
            for target in sorted(set(edges), key=lambda s: STAGE_ORDER.get(s, 99)):
                decision = check_edge(graph, "blocked", target, subject, gates)
                if decision.allowed:
                    try:
                        await apply_transition(session, None, task.code, target,
                                               subject_kind="auto",
                                               rule_code="AUTO_UNBLOCK",
                                               _allow_cascade=False)
                        session.add(_chronicle(
                            task.id, "auto",
                            f"Блокеры сняты ({', '.join(sorted(set(blockers)))}) — "
                            f"автовозврат из «Заблокировано» в «{target}»"))
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
        """Потеря heartbeat ≥ 3 тиков → резерв снят, попытка неудачна (AC-4.3.1.2)."""
        from repository.models import TaskRun

        # порог = таймауту старта прогона: пульс — детектор смерти ДЕМОНА,
        # а не отзывчивости SDK (медленный тик под нагрузкой node/стриминга
        # не должен убивать живой прогон; отзывчивость агента ловят таймауты
        # старта/работы). 90 с на практике убивали живые прогоны (VITRINA).
        threshold = dt.timedelta(seconds=max(300, int(cfg.get("daemon.tick_seconds", "30")) * 3))
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
        # рубильник конвейера (решение владельца 26.10.2026): на паузе новых агентов не запускаем
        paused = (await session.execute(
            sa.text("SELECT value FROM app_setting WHERE key = 'daemon.paused'"))).scalar_one_or_none()
        if paused == "true":
            return 0
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
        from daemon.runner.circuit import paused_connections

        paused_conns = await paused_connections(session)
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
            retry_at = await _next_retry_at(session, task.id, task.status_key, cfg)
            if retry_at and retry_at > now:
                continue  # ждёт растущей паузы ретрая
            # массовый отказ провайдера: задачи ждут, не блокируются (ФТ-ah-35)
            agent_conn = (await session.execute(
                sa.text("SELECT connection_id FROM agent_profile WHERE user_id = :u"),
                {"u": str(agent_row[0])})).scalar_one_or_none()
            conn_key = str(agent_conn) if agent_conn else "default"
            if agent_conn is not None and conn_key in paused_conns:
                continue
            ready.append((*row, *agent_row))

        # правило очереди по зависимостям (решение владельца 29.10.2026):
        # приоритет → сперва задачи, которые сами разблокируют других
        # (blocked_by на них от незакрытых задач) → баги → задачи с открытым
        # do_after опускаются (СТ «Влияние связей») → старые выше
        cand_ids = [t.id for t, _, _, _, _ in ready]
        blocks_count: dict = {}
        do_after_open: set = set()
        if cand_ids:
            blocks_rows = await session.execute(
                sa.select(TaskRelation.to_task, sa.func.count()).select_from(TaskRelation)
                .join(Task, Task.id == TaskRelation.from_task)
                .where(TaskRelation.to_task.in_(cand_ids),
                       TaskRelation.kind == "blocked_by",
                       Task.status_key.notin_(("done", "canceled")))
                .group_by(TaskRelation.to_task))
            for to_task, cnt in blocks_rows.all():
                blocks_count[to_task] = cnt
            do_after_res = await session.execute(
                sa.select(TaskRelation.from_task).select_from(TaskRelation)
                .join(Task, Task.id == TaskRelation.to_task)
                .where(TaskRelation.from_task.in_(cand_ids),
                       TaskRelation.kind == "do_after",
                       Task.status_key.notin_(("done", "canceled"))))
            do_after_open = {r[0] for r in do_after_res.all()}

        def _dep_key(item):
            task, type_key = item[0], item[1]
            return (PRIORITY_RANK.get(task.priority, 9),
                    -blocks_count.get(task.id, 0),
                    0 if type_key == "bug" else 1,
                    1 if task.id in do_after_open else 0,
                    task.created_at, task.code)

        max_attempts = int(cfg["daemon.max_attempts"])
        launched = 0
        for task, type_key, agent_id, mode, position in sorted(ready, key=_dep_key):
            if task.code in self._active:
                continue
            if task.retry_count >= max_attempts:
                # исчерпание попыток → blocked «требуется участие человека» (ФТ-ah-34)
                former = task.status_key
                task.status_key = "blocked"
                task.blocked_reason = (
                    "Требуется участие человека: исчерпаны попытки "
                    f"({task.retry_count} из {max_attempts}) на статусе «{former}»")
                session.add(_chronicle(task.id, "exhausted",
                                       f"Автоблокировка: {task.blocked_reason}"))
                await session.commit()
                continue
            if len(self._active) >= int(cfg.get("daemon.max_parallel", "4")):
                break  # лимит параллелизма: не плодим сотни одновременных SDK-процессов
            # жёсткая связь blocked_by: задачу не берём в работу, пока блокер не
            # закрыт (СТ «Влияние связей»). Проверка ДО резерва: агент не
            # сжигает попытки и токены на отказ гейта (VITRINA-36, 29.10.2026)
            hard_blocked_res = await session.execute(
                sa.select(sa.func.count()).select_from(TaskRelation)
                .join(Task, Task.id == TaskRelation.to_task)
                .where(TaskRelation.from_task == task.id,
                       TaskRelation.kind == "blocked_by",
                       Task.status_key.notin_(("done", "canceled"))))
            hard_blocked = hard_blocked_res.scalar_one()
            if hard_blocked:
                continue
            run_id = await reserve_task(session, task.id, agent_id, task.status_key,
                                        attempt_no=task.retry_count + 1)
            if not run_id:
                continue  # занято другой копией демона
            self._active_runs[task.code] = run_id
            async def _go(task=task, agent_id=agent_id, status_key=task.status_key,
                          run_id=run_id):
                await self._run_task(task.code, agent_id, status_key, cfg, run_id)
            self._active[task.code] = asyncio.create_task(_go())
            launched += 1
        return launched

    async def _run_task(self, task_code: str, agent_id, status_key: str,
                        cfg: dict[str, str], run_id: str | None = None) -> None:
        """Резерв получен: собрать контекст, запустить агента, применить результат.

        Подготовка — в короткоживущей сессии; пока агент работает, открытых
        транзакций не держим: долгая idle-in-transaction вставала в очередь
        перед UPDATE пульса/резерва и замораживала тики демона (инцидент
        29.10.2026: демон молчал 15 минут, пульс и свип встали за её блокировкой)."""
        from usecase.task.transition import TransitionDenied, apply_transition

        try:
            async with self._maker() as session:
                task = (await session.execute(
                    sa.select(Task).where(Task.code == task_code))).scalar_one()
                agent = await session.get(User, agent_id)
                profile = (await session.execute(
                    sa.text("SELECT role, model, allowed_tools, mcp_servers, agent_dir, skills "
                            "FROM agent_profile WHERE user_id = :u"),
                    {"u": str(agent_id)},
                )).mappings().one_or_none()
                # персона агента — одна строка; методологии живут в назначенных скиллах
                persona = (f"{agent.name} — {(profile or {}).get('role') or 'исполнитель этапа конвейера'}"[:300])

                worktree = await self._ensure_worktree(session, task)

                from daemon.runner.agent_runner import RunRequest

                run_id = run_id or await active_run_id(session, task.id)
                seq = [0]

                async def on_event(kind: str, text: str | None = None,
                                   data: dict | None = None) -> None:
                    from repository.models import TaskRunLog

                    if kind == "usage" and data:
                        # накопительные значения за прогон — пишем как есть (идемпотентно),
                        # интерфейс читает их живьём (решение владельца 27.10.2026)
                        async with self._maker() as su:
                            await su.execute(sa.text(
                                "UPDATE task_run SET input_tokens = :i, output_tokens = :o, "
                                "cache_tokens = :c WHERE id = :r"),
                                {"i": int(data.get("input", 0)),
                                 "o": int(data.get("output", 0)),
                                 "c": int(data.get("cache", 0)), "r": str(run_id)})
                            await su.commit()
                        return
                    seq[0] += 1
                    async with self._maker() as s:
                        s.add(TaskRunLog(run_id=run_id, seq=seq[0], kind=kind,
                                         text=text, data=data))
                        await s.commit()

                from infrastructure.paths import host_to_container

                # приоритет: свой путь агента → глобальная папка инструментов (одна на все проекты)
                agent_dir = ((profile or {}).get("agent_dir")
                             or (cfg.get("agents.tools_dir") or "").strip() or None)
                # cwd прогона: worktree этапа разработки, иначе папка проекта —
                # агент не должен блуждать по /app контейнера в поисках кода
                project_path = (await session.execute(
                    sa.text("SELECT path FROM project WHERE id = :i"),
                    {"i": str(task.project_id)})).scalar_one_or_none()
                req_kwargs: dict = dict(
                    task_code=task_code, persona=persona,
                    context_md=await self._context_md(session, task),
                    worktree_path=worktree,
                    cwd_path=None if worktree else (
                        host_to_container(project_path) if project_path else None),
                    provider=await self._provider_for(session, agent_id),
                    timeouts={"start": int(cfg["daemon.timeout_start_seconds"]),
                              "work": int(cfg["daemon.timeout_work_seconds"])},
                    model=(profile or {}).get("model"),
                    mcp_servers=(profile or {}).get("mcp_servers"),
                    on_event=on_event,
                )
                if profile and profile.get("allowed_tools"):
                    req_kwargs["allowed_tools"] = tuple(profile["allowed_tools"])
                if agent_dir:  # в БД путь как на компьютере; раннеру нужен контейнерный
                    req_kwargs["agent_dir"] = host_to_container(agent_dir)
                skill_names = [s for s in ((profile or {}).get("skills") or []) if s]
                if skill_names:  # явно назначенные скиллы — в промт прогона (вариант 4)
                    req_kwargs["skills_md"] = tuple(
                        await self._registry_skills_md(session, skill_names))
                req = RunRequest(**req_kwargs)
        except Exception as err:  # noqa: BLE001 — демон не должен падать
            log.exception("run failed: %s", task_code)
            async with self._maker() as s2:
                # сбой инфраструктуры (worktree/git/провайдер) тоже считается
                # попыткой: иначе задача ретраится вечно, сжигая токены
                # (VITRINA-32…35: git-ошибка worktree, ретрай каждый тик)
                await s2.execute(sa.text(
                    "UPDATE task SET retry_count = retry_count + 1 WHERE code = :c"),
                    {"c": task_code})
                await s2.commit()
                await release_reservation(s2, await task_id_by_code(s2, task_code),
                                          "failed", str(err)[:500])
            self._active.pop(task_code, None)
            self._active_runs.pop(task_code, None)
            return

        # Прогон агента и применение отчёта — БЕЗ открытых транзакций, пока
        # агент работает: долгая idle-in-transaction замораживала тики демона
        try:
            report = await self.runner.run(req)
            from daemon.runner.circuit import record_failure, record_success

            if run_id:
                from repository.models import TaskRunLog

                async with self._maker() as sf:
                    sf.add(TaskRunLog(run_id=run_id, seq=10**6, kind="system",
                                      text=f"прогон завершён: {report.status}"))
                    await sf.commit()
            # комментарии агента к задаче (решение владельца 26.10.2026)
            if report.comments:
                from repository.models import TaskComment

                async with self._maker() as sc:
                    for body in report.comments[:5]:
                        sc.add(TaskComment(task_id=task.id, author_id=agent.id,
                                           body=body.strip()[:4000]))
                    await sc.commit()
            async with self._maker() as session:
                conn_id = (await session.execute(
                    sa.text("SELECT connection_id FROM agent_profile WHERE user_id = :u"),
                    {"u": str(agent_id)})).scalar_one_or_none()
                if report.status == "success":
                    record_success(str(conn_id) if conn_id else None)
                elif report.status == "failed":
                    record_failure(str(conn_id) if conn_id else None)
                    from daemon.runner.circuit import maybe_trip

                    await maybe_trip(session, str(conn_id) if conn_id else None)
                await self._apply_report(session, task, agent, report, cfg)
        except Exception as err:  # noqa: BLE001 — демон не должен падать
            log.exception("run failed: %s", task_code)
            async with self._maker() as s2:
                # сбой инфраструктуры (worktree/git/провайдер) тоже считается
                # попыткой: иначе задача ретраится вечно, сжигая токены
                # (VITRINA-32…35: git-ошибка worktree, ретрай каждый тик)
                await s2.execute(sa.text(
                    "UPDATE task SET retry_count = retry_count + 1 WHERE code = :c"),
                    {"c": task_code})
                await s2.commit()
                await release_reservation(s2, await task_id_by_code(s2, task_code),
                                          "failed", str(err)[:500])
        finally:
            self._active.pop(task_code, None)
            self._active_runs.pop(task_code, None)

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

        return await ensure_task_worktree(project.path, task.code, project.base_branch,
                                          repo_path=task.repo_path)

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
        """Перехват человеком: прогон помечен outcome='interrupted' -> убить процесс (ФТ-ah-32).
        Матч по run_id текущего прогона, а не по окну времени: свежезапущенный прогон
        не гасится эхом чужого перехвата. Незавершённый отчёт не применяется."""
        if not self._active:
            return 0
        now = dt.datetime.now(dt.timezone.utc)
        rows = (await session.execute(
            sa.select(Task.code, TaskRun.id)
            .join(Task, Task.id == TaskRun.task_id)
            .where(TaskRun.finished_at.isnot(None),
                   TaskRun.outcome == "interrupted",
                   TaskRun.finished_at >= now - dt.timedelta(minutes=10),
                   Task.code.in_(list(self._active_runs.keys()))))).all()
        killed = 0
        for code, rid in rows:
            if self._active_runs.get(code) != str(rid):
                continue  # гасим только тот прогон, который сами запустили
            t = self._active.pop(code, None)
            self._active_runs.pop(code, None)
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

    async def _registry_skills_md(self, session, names: list[str]) -> list[str]:
        """Содержимое явно назначенных агенту скиллов из реестра инструментов.

        Пропавший файл не роняет прогон — в промт уходит честная пометка."""
        from domain.model.validators import DomainError
        from repository.models import ToolArtifact

        from usecase.settings import tools as tools_uc

        try:
            _user, root = await tools_uc._global_dir(session)
        except DomainError:
            return []
        rows = (await session.execute(sa.select(ToolArtifact).where(
            ToolArtifact.kind == "skill", ToolArtifact.name.in_(names)))).scalars().all()
        by_name = {r.name: r for r in rows}
        out: list[str] = []
        for n in names:
            r = by_name.get(n)
            path = root / r.rel_path if r else None
            if path and path.is_file():
                out.append(f"## Скилл: {n}\n\n"
                           + path.read_text(encoding="utf-8", errors="replace"))
            else:
                out.append(f"## Скилл: {n}\n\n"
                           "(файл не найден в папке инструментов — скилл пропущен)")
        return out

    async def _apply_report(self, session, task, agent, report, cfg) -> None:
        from repository.models import Chronicle, Task
        from usecase.task.transition import TransitionDenied, apply_transition

        task = (await session.execute(
            sa.select(Task).where(Task.code == task.code))).scalar_one()

        session.add(Chronicle(
            task_id=task.id, event_type="agent", author_id=agent.id, author_kind="agent",
            message=f"Отчёт агента: {report.summary_md[:300]}",
        ))
        # артефакт этапа (ФТ-ah-38): отчёт из JSON-отчёта агента получает новую
        # версию; без записи гейт cond_artifact честно отклонял переход — агент
        # делал работу, отчёт терялся (дефект 29.10.2026, нашли на AH-130)
        if report.artifact_md and report.artifact_kind in ("dev_report", "review_report", "qa_report"):
            from repository.models import TaskArtifact

            ver = (await session.execute(sa.text(
                "SELECT coalesce(max(version),0)+1 FROM task_artifact "
                "WHERE task_id = :t AND kind = :k"),
                {"t": str(task.id), "k": report.artifact_kind})).scalar_one()
            session.add(TaskArtifact(task_id=task.id, kind=report.artifact_kind,
                                     version=ver, body_md=report.artifact_md,
                                     created_by=agent.id))
            session.add(_chronicle(task.id, "agent",
                                   f"Артефакт {report.artifact_kind} v{ver} записан агентом"))
        await self._apply_relations(session, task, report)
        await self._apply_checklist_updates(session, task, report)

        if report.status == "success" and not report.proposed_transition:
            # агент не предложил переход — задача остаётся на статусе; повтор
            # откладывается паузой (_next_retry_at: success на том же статусе)
            session.add(_chronicle(task.id, "agent",
                                   "Отчёт без предложенного перехода — повторный запуск отложен"))
        if report.status == "success" and report.proposed_transition:
            to = report.proposed_transition.get("to")
            try:
                # Слияние перед done — ТОЛЬКО по легальному ребру: раньше merge
                # запускался до проверки перехода, и «done» из статуса без ребра
                # (например todo→done) давал ложный «Конфликт слияния» вместо
                # честного «переход отклонён» и сжигал попытки прогона.
                from domain.transition.engine import check_edge
                from domain.transition.graph import load_graph

                from usecase.task.gates import load_gate_data
                from usecase.task.transition import _subject_for, task_flow_version_id

                subject = await _subject_for(session, agent, task)
                graph = await load_graph(session, await task_flow_version_id(session, task))
                decision = check_edge(graph, task.status_key, to, subject,
                                      await load_gate_data(session, task))
                if not decision.allowed:
                    raise TransitionDenied(decision.reason)
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
        """Upsert-семантика (дефект 29.10.2026: пункт с item_position при пустом
        чеклисте тихо не применялся — UPDATE не попадал ни в одну строку, и
        декомпозиция Планировщика пропадала, гейт отклонял переход, сжигая
        попытки по ~100К токенов). Пункта нет или чеклиста нет — создаём."""
        applied = 0
        for upd in report.checklist_updates:
            kind = upd.get("checklist_kind")
            new_status = upd.get("new_status")
            if not kind or not new_status:
                continue
            chk = (await session.execute(sa.text(
                "SELECT id FROM checklist WHERE task_id = :t AND kind = :k"),
                {"t": str(task.id), "k": kind})).first()
            if chk is None:
                chk = (await session.execute(sa.text(
                    "INSERT INTO checklist (id, task_id, kind) "
                    "VALUES (gen_random_uuid(), :t, :k) RETURNING id"),
                    {"t": str(task.id), "k": kind})).first()
            position = upd.get("item_position")
            if position is not None:
                updated = (await session.execute(sa.text(
                    "UPDATE checklist_item ci SET status = :s, text = coalesce(:x, text) "
                    "FROM checklist c WHERE c.id = ci.checklist_id AND c.task_id = :t "
                    "AND c.kind = :k AND ci.position = :p RETURNING ci.id"), {
                        "s": new_status, "t": str(task.id), "k": kind,
                        "p": position, "x": upd.get("text")})).first()
                if updated is not None:
                    applied += 1
                    continue
            if not upd.get("text"):
                continue
            pos = position if position is not None else (await session.execute(
                sa.text("SELECT coalesce(max(position),0)+1 FROM checklist_item "
                        "WHERE checklist_id = :c"), {"c": str(chk[0])})).scalar_one()
            await session.execute(sa.text(
                "INSERT INTO checklist_item (id, checklist_id, position, kind, text, status) "
                "VALUES (gen_random_uuid(), :c, :p, 'item', :x, :s) "
                "ON CONFLICT DO NOTHING"), {
                    "c": str(chk[0]), "p": pos, "x": upd["text"], "s": new_status})
            applied += 1
        await session.commit()
        if applied:
            session.add(_chronicle(task.id, "agent",
                                   f"Чеклист обновлён агентом ({applied} пункт(ов))"))

    async def _apply_relations(self, session, task, report) -> int:
        """Связи из отчёта агента (relations_updates): blocked_by / do_after.
        Охраны как в API: существование задачи, не самозащёлка, без дублей."""
        from repository.models import TaskRelation

        applied = 0
        for rel in report.relations_updates:
            kind, other_code = rel.get("kind"), str(rel.get("task_code") or "").upper()
            if kind not in ("do_after", "blocked_by") or not other_code:
                continue
            other = (await session.execute(
                sa.select(Task).where(Task.code == other_code))).scalar_one_or_none()
            if other is None or other.id == task.id:
                continue
            dup = (await session.execute(
                sa.select(sa.func.count()).select_from(TaskRelation)
                .where(TaskRelation.from_task == task.id, TaskRelation.to_task == other.id,
                       TaskRelation.kind == kind))).scalar_one()
            if dup:
                continue
            session.add(TaskRelation(from_task=task.id, to_task=other.id, kind=kind))
            applied += 1
        if applied:
            await session.commit()
            session.add(_chronicle(task.id, "agent",
                                   f"Связи обновлены агентом ({applied} шт.)"))
        return applied

    async def _merge_before_done(self, session, task) -> None:
        """Слияние перед done (ФТ-ah-37); конфликт -> TransitionDenied (далее ретрай-лестница)."""
        from repository.models import Project

        from infrastructure.git.worktree import GitError, merge_task_branch
        from infrastructure.paths import host_to_container
        from usecase.task.transition import TransitionDenied

        project = await session.get(Project, task.project_id)
        try:
            # путь проекта в БД хранится как на хосте; git-операции идут в контейнере
            await merge_task_branch(host_to_container(project.path), task.code,
                                    project.base_branch, repo_path=task.repo_path)
        except GitError as err:
            raise TransitionDenied(
                f"Конфликт слияния: распутайте вручную, автомат повторит ({err.stderr[:200]})",
                status_code=200)
        # уборка: чистый worktree после слияния больше не нужен (ветка сохраняется)
        try:
            from infrastructure.git.worktree import cleanup_task_worktree

            await cleanup_task_worktree(host_to_container(project.path), task.code,
                                        repo_path=task.repo_path)
        except Exception:  # noqa: BLE001 - неуспешная уборка не роняет переход
            log.info("worktree cleanup skipped for %s", task.code, exc_info=True)

async def task_id_by_code(session, code):
    from repository.models import Task

    return (await session.execute(
        sa.select(Task.id).where(Task.code == code))).scalar_one()


def _chronicle(task_id, rule: str, message: str):
    from repository.models import Chronicle

    return Chronicle(task_id=task_id, event_type="agent", author_kind="auto",
                     rule_code=rule, message=message)
