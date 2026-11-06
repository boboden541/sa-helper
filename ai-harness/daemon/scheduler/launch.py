"""Запуск готовых задач: выбор, приоритеты, резерв, лимиты.

Вынесено из scheduler.py (рефакторинг 04.11.2026 — лимит 800 строк);
поведение не менялось. Миксин LaunchMixin подключается в Daemon (core).
"""

from __future__ import annotations

import asyncio
import datetime as dt

import sqlalchemy as sa
from domain.model.enums import PRIORITY_RANK
from repository.models import Assignment, Project, Task, TaskRelation, TaskType, User
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from daemon.runner.reservation import reserve_task
from daemon.scheduler.helpers import _chronicle, _retry_at_from_run


class LaunchMixin:
    async def _launch_ready(self, session: AsyncSession, cfg: dict[str, str]) -> int:
        # рубильник конвейера (решение владельца 26.10.2026): на паузе новых агентов не запускаем
        paused = (
            await session.execute(
                sa.text("SELECT value FROM app_setting WHERE key = 'daemon.paused'")
            )
        ).scalar_one_or_none()
        if paused == "true":
            return 0
        now = dt.datetime.now(dt.timezone.utc)
        # reserved_by НЕ фильтруем в SQL: параллельные задачи живут с пустым
        # reserved_by при активных прогонах; эксклюзивный резерв отсеивается
        # в python-цикле ниже (анализ 03.11.2026)
        rows = (
            await session.execute(
                sa.select(Task, TaskType.key.label("type_key"))
                .join(TaskType, TaskType.id == Task.task_type_id)
                .outerjoin(Project, Project.id == Task.project_id)
                .where(
                    Task.status_key.notin_(("pending", "blocked", "done", "canceled")),
                    Project.is_archived.is_(False),
                )
            )
        ).all()

        # только статусы с назначенным живым агентом (матрица).
        # Предвыборка пачками (анализ 30.10.2026: на задачу приходилось 3-4
        # отдельных запроса — сотни задач на тике умножали тики на сотни Query)
        from daemon.runner.circuit import paused_connections

        paused_conns = await paused_connections(session)

        assign_rows = (
            await session.execute(
                sa.select(
                    Assignment.task_type_id,
                    Assignment.status_key,
                    Assignment.user_id,
                    Assignment.mode,
                    Assignment.position,
                )
                .join(User, User.id == Assignment.user_id)
                .where(User.user_type == "agent", User.is_service.is_(False))
                .order_by(Assignment.position)
            )
        ).all()
        assignments: dict[tuple, list] = {}
        for at, sk, uid, mode, pos in assign_rows:
            assignments.setdefault((str(at), sk), []).append((uid, mode, pos))

        conn_rows = (
            await session.execute(sa.text("SELECT user_id, connection_id FROM agent_profile"))
        ).all()
        conn_by_agent = {str(uid): cid for uid, cid in conn_rows}

        from repository.models import TaskRun

        # последний прогон — по паре (задача, агент): в parallel пауза ретрая
        # одного агента не должна задерживать первого запуска соседа
        last_runs: dict[tuple, tuple] = {}
        if rows:
            lr = (
                await session.execute(
                    sa.select(
                        TaskRun.task_id,
                        TaskRun.agent_id,
                        TaskRun.finished_at,
                        TaskRun.attempt_no,
                        TaskRun.outcome,
                        TaskRun.status_key,
                    )
                    .where(
                        TaskRun.task_id.in_([row.Task.id for row in rows]),
                        TaskRun.outcome.in_(("failed", "interrupted", "success")),
                    )
                    .ext(
                        distinct_on(TaskRun.task_id, TaskRun.agent_id)
                    )  # DISTINCT ON: современная форма SA 2.1 (distinct(args) deprecated)
                    .order_by(TaskRun.task_id, TaskRun.agent_id, TaskRun.finished_at.desc())
                )
            ).all()
            last_runs = {(str(r[0]), str(r[1])): tuple(r)[2:] for r in lr}

        # счётчик прогонов задачи в целом: retry_count сбрасывается переходами,
        # поэтому цикл «разработка↔ревью» легально сжигал сотни прогонов
        # (VITRINA-35: 130). Пакетно, одним group-by.
        # Инцидент VITRINA-1 (03.11.2026): считаем только «настоящие» прогоны —
        # плановые смены сессии (soft_turns) и обрывы «задача ушла со статуса»
        # (stale_status) не тратят бюджет; прогоны до последнего выхода из
        # blocked (runs_reset_at — «человек разобрался») не считаются.
        # штампы psi-планов историй-кандидатов: устаревший план снимает паузу
        # прогонов (пересмотр плана — первоочередная работа составителя)
        from repository.models import Checklist as _CK
        from repository.models import Task as _T
        from repository.models import TaskRun as _TR

        psi_stamps: dict = {}
        story_ids = [row.Task.id for row in rows if row.type_key == "story"]
        if story_ids:
            stamps = (
                await session.execute(
                    sa.select(_CK.task_id, _CK.source_ref_version).where(
                        _CK.kind == "psi", _CK.task_id.in_(story_ids)
                    )
                )
            ).all()
            psi_stamps = {str(tid): (v or 0) for tid, v in stamps}

        run_counts: dict = {}
        if rows:
            rc = (
                await session.execute(
                    sa.select(_TR.task_id, sa.func.count())
                    .join(_T, _T.id == _TR.task_id)
                    .where(
                        _TR.task_id.in_([row.Task.id for row in rows]),
                        sa.or_(
                            _TR.reason_code.is_(None),
                            _TR.reason_code.notin_(("soft_turns", "stale_status")),
                        ),
                        sa.or_(_T.runs_reset_at.is_(None), _TR.started_at > _T.runs_reset_at),
                    )
                    .group_by(_TR.task_id)
                )
            ).all()
            run_counts = {str(tid): n for tid, n in rc}

        # активные прогоны кандидатов — один пакетный запрос (parallel: пара
        # «задача×агент» с живым прогоном не перезапускается)
        active_pairs: set[tuple] = set()
        if rows:
            act = (
                await session.execute(
                    sa.select(TaskRun.task_id, TaskRun.agent_id).where(
                        TaskRun.task_id.in_([row.Task.id for row in rows]),
                        TaskRun.finished_at.is_(None),
                    )
                )
            ).all()
            active_pairs = {(str(tid), str(aid)) for tid, aid in act}

        ready = []
        for row in rows:
            task = row.Task
            type_key = row.type_key
            if task.reserved_by is not None:
                continue  # эксклюзивный резерв держит другая копия демона — не трогаем
            agent_rows = assignments.get((str(task.task_type_id), task.status_key))
            if not agent_rows:
                continue
            # режим ведущей записи (первой по position): parallel — работают все
            # назначенные агенты одновременно; exclusive — только первый
            parallel = agent_rows[0][1] == "parallel"
            agents = agent_rows if parallel else agent_rows[:1]
            for uid, _m, _p in agents:
                if (str(task.id), str(uid)) in active_pairs:
                    continue  # у агента уже есть живой прогон по этой задаче
                last = last_runs.get((str(task.id), str(uid)))
                retry_at = _retry_at_from_run(last, task.status_key, cfg) if last else None
                # план psi устарел (эталон v{ref} > план v{stamp}) на истории
                # в in_testing: пауза снята — пересмотр плана без простоев
                if (
                    retry_at
                    and retry_at > now
                    and not (
                        type_key == "story" and task.ref_version > psi_stamps.get(str(task.id), 0)
                    )
                ):
                    continue  # ждёт растущую паузу ретрая
                # массовый отказ провайдера: задачи ждут, не блокируются (ФТ-ah-35)
                agent_conn = conn_by_agent.get(str(uid))
                conn_key = str(agent_conn) if agent_conn else "default"
                if conn_key in paused_conns:  # «default»-агенты тоже паузятся
                    continue
                # ФТ-FNR14-09: лежащий стенд не отпускает in_testing на прогон —
                # попытка не сгорает, эпизод в хронике пишется один раз
                if task.status_key == "in_testing" and await self._stand_down(session, task):
                    continue
                ready.append((task, type_key, uid, "parallel" if parallel else "replacement", _p))

        # правило очереди по зависимостям (решение владельца 29.10.2026):
        # приоритет → сперва задачи, которые сами разблокируют других
        # (blocked_by на них от незакрытых задач) → баги → задачи с открытым
        # do_after опускаются (СТ «Влияние связей») → старые выше
        cand_ids = [t.id for t, _, _, _, _ in ready]
        blocks_count: dict = {}
        do_after_open: set = set()
        if cand_ids:
            blocks_rows = await session.execute(
                sa.select(TaskRelation.to_task, sa.func.count())
                .select_from(TaskRelation)
                .join(Task, Task.id == TaskRelation.from_task)
                .where(
                    TaskRelation.to_task.in_(cand_ids),
                    TaskRelation.kind == "blocked_by",
                    Task.status_key.notin_(("done", "canceled")),
                )
                .group_by(TaskRelation.to_task)
            )
            for to_task, cnt in blocks_rows.all():
                blocks_count[to_task] = cnt
            do_after_res = await session.execute(
                sa.select(TaskRelation.from_task)
                .select_from(TaskRelation)
                .join(Task, Task.id == TaskRelation.to_task)
                .where(
                    TaskRelation.from_task.in_(cand_ids),
                    TaskRelation.kind == "do_after",
                    Task.status_key.notin_(("done", "canceled")),
                )
            )
            do_after_open = {r[0] for r in do_after_res.all()}

        def _dep_key(item):
            task, type_key = item[0], item[1]
            return (
                PRIORITY_RANK.get(task.priority, 9),
                -blocks_count.get(task.id, 0),
                0 if type_key == "bug" else 1,
                1 if task.id in do_after_open else 0,
                task.created_at,
                task.code,
            )

        max_attempts = int(cfg["daemon.max_attempts"])
        launched = 0
        for task, _type_key, agent_id, mode, _position in sorted(ready, key=_dep_key):
            # replacement: один активный прогон на задачу; parallel: соседи живут одновременно
            if mode == "replacement" and any(
                m["task_code"] == task.code for m in self._runs.values()
            ):
                continue
            total_runs = run_counts.get(str(task.id), 0)
            warn_n = int(cfg.get("daemon.warn_runs_per_task") or 0)
            max_n = int(cfg.get("daemon.max_runs_per_task") or 0)
            if max_n and total_runs >= max_n:
                # лимит прогонов задачи: цикл не сходится — стоп, разбирает человек
                from usecase.journal.notifications import raise_event
                from usecase.task.transition import apply_blocked

                await apply_blocked(
                    session,
                    task,
                    None,
                    f"Требуется участие человека: исчерпан лимит прогонов задачи "
                    f"({total_runs} из daemon.max_runs_per_task={max_n}) — цикл "
                    f"разработки не сходится; проверьте ревью/тесты или поднимите лимит. "
                    f"Верните задачу в нужный статус вручную — счётчик прогонов "
                    f"сбросится автоматически",
                    subject_kind="auto",
                    rule_code="RUN_LIMIT",
                )
                await raise_event(
                    session,
                    task.code,
                    "cycle_not_converging",
                    f"Задача {task.code}: {total_runs} прогонов — цикл не сходится",
                )
                await session.commit()
                continue
            if warn_n and total_runs >= warn_n and total_runs < max_n:
                from usecase.journal.notifications import raise_event

                # идемпотентно (частичный UNIQUE): одно открытое уведомление
                await raise_event(
                    session,
                    task.code,
                    "cycle_not_converging",
                    f"Задача {task.code}: {total_runs}-й прогон — цикл может не сходиться",
                )
            if task.retry_count >= max_attempts:
                # провайдер мигает — задача НЕ блокируется (ФТ-ah-35 «задачи
                # ждут»): последний отказ был сетью/API, не работой агента
                last_reason = (
                    await session.execute(
                        sa.text(
                            "SELECT reason_code FROM task_run WHERE task_id = :t "
                            "AND outcome = 'failed' "
                            "ORDER BY started_at DESC LIMIT 1"
                        ),
                        # bypass-запрос: последний failed решает; NULL-причины
                        # (честные сбои) перекрывают старую провайдерную запись
                        # — иначе одна прошлая флапа навсегда «отравляла» bypass
                        {"t": str(task.id)},
                    )
                ).scalar_one_or_none()
                if last_reason == "provider_unreachable":
                    continue
                # исчерпание попыток → blocked «требуется участие человека» (ФТ-ah-34).
                # Прозрачность (решение владельца 30.10.2026): в причину входят
                # последние сбои прогонов — «что случилось» видно сразу, без
                # раскопок хроник и лент прогонов.
                former = task.status_key
                causes = (
                    (
                        await session.execute(
                            sa.select(sa.text("DISTINCT ON (detail) left(detail, 120) AS d"))
                            .select_from(sa.text("task_run"))
                            .where(
                                sa.text(
                                    "task_id = :tid AND outcome = 'failed' "
                                    "AND coalesce(detail,'') <> ''"
                                )
                            )
                            .order_by(sa.text("detail, started_at DESC"))
                            .limit(3)
                            .params(tid=str(task.id))
                        )
                    )
                    .scalars()
                    .all()
                )
                cause_txt = ("; последние сбои: " + " | ".join(causes)) if causes else ""
                task.status_key = "blocked"
                task.blocked_rule = "AUTO_BLOCK"
                task.blocked_reason = (
                    "Требуется участие человека: исчерпаны попытки "
                    f"({task.retry_count} из {max_attempts}) на статусе «{former}»." + cause_txt
                )[:500]
                session.add(
                    _chronicle(task.id, "exhausted", f"Автоблокировка: {task.blocked_reason}")
                )
                await session.commit()
                continue
            if len(self._active) >= int(cfg.get("daemon.max_parallel", "4")):
                break  # лимит параллелизма: не плодим сотни одновременных SDK-процессов
            # жёсткая связь blocked_by: задачу не берём в работу, пока блокер не
            # закрыт (СТ «Влияние связей»). Проверка ДО резерва: агент не
            # сжигает попытки и токены на отказ гейта (VITRINA-36, 29.10.2026)
            hard_blocked_res = await session.execute(
                sa.select(sa.func.count())
                .select_from(TaskRelation)
                .join(Task, Task.id == TaskRelation.to_task)
                .where(
                    TaskRelation.from_task == task.id,
                    TaskRelation.kind == "blocked_by",
                    Task.status_key.notin_(("done", "canceled")),
                )
            )
            hard_blocked = hard_blocked_res.scalar_one()
            if hard_blocked:
                continue
            run_id = await reserve_task(
                session,
                task.id,
                agent_id,
                task.status_key,
                attempt_no=task.retry_count + 1,
                mode=mode,
            )
            if not run_id:
                continue  # занято: гонка проиграна (эксклюзив) или агент уже живёт (parallel)
            self._runs[run_id] = {
                "task_code": task.code,
                "task_id": str(task.id),
                "status_key": task.status_key,
                "agent_id": str(agent_id),
            }

            async def _go(task=task, agent_id=agent_id, status_key=task.status_key, run_id=run_id):
                await self._run_task(task.code, agent_id, status_key, cfg, run_id)

            self._active[run_id] = asyncio.create_task(_go())
            launched += 1
        return launched
