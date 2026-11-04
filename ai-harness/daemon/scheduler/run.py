"""Прогон задачи агентом: контекст, сессии SDK, таймауты, resume.

Вынесено из scheduler.py (рефакторинг 04.11.2026 — лимит 800 строк);
поведение не менялось. Миксин RunMixin подключается в Daemon (core).
"""

from __future__ import annotations

import sqlalchemy as sa
from repository.models import Task, User

from daemon.runner.agent_runner import is_provider_unreachable
from daemon.runner.reservation import release_reservation
from daemon.scheduler.helpers import (
    HANDOFF_OUTCOMES,
    active_run_id,
    log,
    targeted_retry_block,
    task_id_by_code,
)


class RunMixin:
    async def _run_task(
        self,
        task_code: str,
        agent_id,
        status_key: str,
        cfg: dict[str, str],
        run_id: str | None = None,
    ) -> None:
        """Резерв получен: собрать контекст, запустить агента, применить результат.

        Подготовка — в короткоживущей сессии; пока агент работает, открытых
        транзакций не держим: долгая idle-in-transaction вставала в очередь
        перед UPDATE пульса/резерва и замораживала тики демона (инцидент
        29.10.2026: демон молчал 15 минут, пульс и свип встали за её блокировкой)."""

        try:
            async with self._maker() as session:
                task = (
                    await session.execute(sa.select(Task).where(Task.code == task_code))
                ).scalar_one()
                agent = await session.get(User, agent_id)
                profile = (
                    (
                        await session.execute(
                            sa.text(
                                "SELECT role, model, allowed_tools, mcp_servers, agent_dir, skills "
                                "FROM agent_profile WHERE user_id = :u"
                            ),
                            {"u": str(agent_id)},
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                # персона агента — одна строка; методологии живут в назначенных скиллах
                role = (profile or {}).get("role") or "исполнитель этапа конвейера"
                persona = f"{agent.name} — {role}"[:300]

                worktree = await self._ensure_worktree(session, task)

                from daemon.runner.agent_runner import RunRequest

                run_id = run_id or await active_run_id(session, task.id)
                seq = [0]

                async def on_event(
                    kind: str, text: str | None = None, data: dict | None = None
                ) -> None:
                    from repository.models import TaskRunLog

                    if kind == "system" and data and data.get("session_id"):
                        # SDK-сессия прогона — для resume после «лимит ходов/таймаут»
                        async with self._maker() as ss:
                            await ss.execute(
                                sa.text("UPDATE task_run SET session_id = :s WHERE id = :r"),
                                {"s": str(data["session_id"])[:64], "r": str(run_id)},
                            )
                            await ss.commit()
                    if kind == "usage" and data:
                        # накопительные значения за прогон — пишем как есть (идемпотентно),
                        # интерфейс читает их живьём (решение владельца 27.10.2026)
                        async with self._maker() as su:
                            await su.execute(
                                sa.text(
                                    "UPDATE task_run SET input_tokens = :i, output_tokens = :o, "
                                    "cache_tokens = :c WHERE id = :r"
                                ),
                                {
                                    "i": int(data.get("input", 0)),
                                    "o": int(data.get("output", 0)),
                                    "c": int(data.get("cache", 0)),
                                    "r": str(run_id),
                                },
                            )
                            await su.commit()
                        return
                    seq[0] += 1
                    async with self._maker() as s:
                        s.add(
                            TaskRunLog(run_id=run_id, seq=seq[0], kind=kind, text=text, data=data)
                        )
                        await s.commit()

                from infrastructure.paths import host_to_container, task_repo_root

                # приоритет: свой путь агента → глобальная папка инструментов (одна на все проекты)
                agent_dir = (
                    (profile or {}).get("agent_dir")
                    or (cfg.get("agents.tools_dir") or "").strip()
                    or None
                )
                # cwd прогона: worktree этапа разработки, иначе целевой репозиторий
                # (мультирепозиторий: task.repo_path, как в merge_task_branch) —
                # агент не должен блуждать по /app контейнера в поисках кода
                project_path = (
                    await session.execute(
                        sa.text("SELECT path FROM project WHERE id = :i"),
                        {"i": str(task.project_id)},
                    )
                ).scalar_one_or_none()
                root = task_repo_root(project_path, task.repo_path)
                # resume: прошлый прогон той же задачи оборвался лимитом ходов
                # или таймаутом — продолжаем его SDK-сессию (наработка в разговоре
                # сохраняется; бюджет ходов у запроса свой, лестница ретраев
                # ограничивает цепочку). Инфра-сбои и обычные failed — свежий лист.
                # прицельный перепрогон: прошлый failed — отказ чеклист-гейта?
                # (по коду отказа, не подстроками в тексте — анализ 03.11.2026)
                last_denied = (
                    await session.execute(
                        sa.text(
                            "SELECT detail FROM task_run "
                            "WHERE task_id = :t AND outcome = 'failed' AND reason_code IN "
                            "('checklist_not_closed', 'checklist_failed', 'checklist_not_created') "
                            "ORDER BY started_at DESC LIMIT 1"
                        ),
                        {"t": str(task.id)},
                    )
                ).scalar_one_or_none()
                base_ctx = await self._context_md(session, task)
                if last_denied:
                    open_items = (
                        (
                            await session.execute(
                                sa.text(
                                    "SELECT ci.kind AS kind, ci.position AS position, "
                                    "ci.text AS text, ci.status AS status "
                                    "FROM checklist_item ci "
                                    "JOIN checklist c ON c.id = ci.checklist_id "
                                    "WHERE c.task_id = :t AND ci.status NOT IN ('done', 'closed') "
                                    "ORDER BY c.kind, ci.position"
                                ),
                                {"t": str(task.id)},
                            )
                        )
                        .mappings()
                        .all()
                    )
                    block = targeted_retry_block(last_denied.strip(), [dict(r) for r in open_items])
                    if block:
                        base_ctx = base_ctx + "\n\n" + block

                # handoff: микро-состояние последнего обрыва — последние действия
                # предыдущего агента (разговор умер вместе с сессией, а чеклист
                # про это не знает); ~12 записей лога прогона
                last_run_id = (
                    await session.execute(
                        sa.text(
                            "SELECT id FROM task_run WHERE task_id = :t "
                            "AND outcome IN ('failed', 'interrupted') "
                            "ORDER BY started_at DESC LIMIT 1"
                        ),
                        {"t": str(task.id)},
                    )
                ).scalar_one_or_none()
                if last_run_id:
                    handoff_rows = (
                        (
                            await session.execute(
                                sa.text(
                                    "SELECT kind, left(coalesce(text,''),150) AS txt "
                                    "FROM task_run_log "
                                    "WHERE run_id = :r AND kind IN ('tool', 'thinking') "
                                    "AND coalesce(text, '') <> '' "
                                    "ORDER BY seq DESC LIMIT 12"
                                ),
                                {"r": str(last_run_id)},
                            )
                        )
                        .mappings()
                        .all()
                    )
                    if handoff_rows:
                        base_ctx += (
                            "\n\n## Handoff — последние действия предыдущего агента "
                            "(сессия оборвана; продолжай с этого места)\n"
                            + "\n".join(
                                f"- [{r['kind']}] {r['txt']}" for r in reversed(handoff_rows)
                            )
                        )
                # resume — только при РАННЕМ обрыве (< 15 мин работы): короткую
                # сессию продолжить дешевле, чем начинать заново; длинная уже
                # деградировала (ход дорожал с ростом префикса) — вместо неё
                # свежая сессия + handoff из лога (решение владельца 31.10.2026)
                resume_sid = (
                    await session.execute(
                        sa.text(
                            "SELECT session_id FROM task_run "
                            "WHERE task_id = :t AND outcome = 'failed' AND session_id IS NOT NULL "
                            "AND reason_code IN ('turns_limit', 'timeout_work') "
                            "AND finished_at - started_at < interval '15 minutes' "
                            "ORDER BY started_at DESC LIMIT 1"
                        ),
                        {"t": str(task.id)},
                    )
                ).scalar_one_or_none()
                req_kwargs: dict = dict(
                    task_code=task_code,
                    persona=persona,
                    context_md=base_ctx,
                    worktree_path=worktree,
                    cwd_path=None if worktree else (host_to_container(root) if root else None),
                    provider=await self._provider_for(session, agent_id),
                    timeouts={
                        "start": int(cfg["daemon.timeout_start_seconds"]),
                        "work": int(cfg["daemon.timeout_work_seconds"]),
                    },
                    model=(profile or {}).get("model"),
                    mcp_servers=(profile or {}).get("mcp_servers"),
                    max_turns=int(cfg.get("daemon.max_turns") or 200),
                    resume_session_id=resume_sid,
                    soft_turns=int(cfg.get("daemon.soft_turns") or 0) or None,
                    on_event=on_event,
                )
                if profile and profile.get("allowed_tools"):
                    req_kwargs["allowed_tools"] = tuple(profile["allowed_tools"])
                if agent_dir:  # в БД путь как на компьютере; раннеру нужен контейнерный
                    req_kwargs["agent_dir"] = host_to_container(agent_dir)
                skill_names = [s for s in ((profile or {}).get("skills") or []) if s]
                if skill_names:  # явно назначенные скиллы — в промт прогона (вариант 4)
                    req_kwargs["skills_md"] = tuple(
                        await self._registry_skills_md(session, skill_names)
                    )
                req = RunRequest(**req_kwargs)
        except Exception as err:  # noqa: BLE001 — демон не должен падать
            log.exception("run failed: %s", task_code)
            from domain.model.validators import DomainError
            from infrastructure.git.worktree import GitError
            from usecase.task.transition import apply_blocked

            # Детерминированный сбой окружения (git/шифрование/дефект кода):
            # ретрай бессмыслен — агенты даже не начинали, а каждый повтор
            # читает кэш-префикс и жжёт токены (шторм 29.10: 306 прогонов на
            # один git-сбой, 87% всех прогонов эры — failed). Инфра-сбой →
            # сразу blocked «требуется участие человека» с причиной-stderr;
            # попытки не сжигаются. Агентские сбои (таймауты, отчёты failed)
            # остаются на ретрай-лестнице.
            infra = isinstance(
                err, (GitError, DomainError, NameError, ImportError, FileNotFoundError)
            )
            async with self._maker() as s2:
                task_id = await task_id_by_code(s2, task_code)
                if infra:
                    try:
                        task_row = await s2.get(Task, task_id)
                        await apply_blocked(
                            s2,
                            task_row,
                            None,
                            str(err)[:500],
                            subject_kind="auto",
                            rule_code="INFRA",
                        )
                    except Exception:  # noqa: BLE001 — blocked любой ценой
                        log.warning("apply_blocked failed for %s", task_code, exc_info=True)
                        await s2.rollback()
                        await s2.execute(
                            sa.text(
                                "UPDATE task SET status_key = 'blocked', blocked_reason = :r "
                                "WHERE id = :i"
                            ),
                            {"r": str(err)[:500], "i": str(task_id)},
                        )
                else:
                    await s2.execute(
                        sa.text("UPDATE task SET retry_count = retry_count + 1 WHERE code = :c"),
                        {"c": task_code},
                    )
                await s2.commit()
                await release_reservation(
                    s2,
                    task_id,
                    run_id,
                    "failed",
                    str(err)[:500],
                    reason_code="runner_error" if not infra else "infra",
                )
            self._active.pop(run_id, None)
            self._runs.pop(run_id, None)
            return

        # Прогон агента и применение отчёта — БЕЗ открытых транзакций, пока
        # агент работает: долгая idle-in-transaction замораживала тики демона
        try:
            report = await self.runner.run(req)
            from daemon.runner.circuit import record_failure, record_success

            if run_id:
                from repository.models import TaskRunLog

                async with self._maker() as sf:
                    sf.add(
                        TaskRunLog(
                            run_id=run_id,
                            seq=10**6,
                            kind="system",
                            text=f"прогон завершён: {report.status}",
                        )
                    )
                    await sf.commit()
            # комментарии агента к задаче (решение владельца 26.10.2026)
            if report.comments:
                from repository.models import TaskComment

                async with self._maker() as sc:
                    for body in report.comments[:5]:
                        sc.add(
                            TaskComment(
                                task_id=task.id, author_id=agent.id, body=body.strip()[:4000]
                            )
                        )
                    await sc.commit()
            elif report.outcome_code in HANDOFF_OUTCOMES:
                # агент не отписался (обрыв/таймаут/битый отчёт) — след сессии
                # пишет демон от имени агента (решение владельца 04.11.2026)
                from daemon.scheduler.helpers import (
                    _HANDOFF_HEADLINES,
                    write_handoff_comment,
                )

                await write_handoff_comment(
                    self._maker,
                    task.id,
                    agent.id,
                    run_id,
                    _HANDOFF_HEADLINES.get(report.outcome_code, "Сессия завершилась без отчёта"),
                )
            async with self._maker() as session:
                conn_id = (
                    await session.execute(
                        sa.text("SELECT connection_id FROM agent_profile WHERE user_id = :u"),
                        {"u": str(agent_id)},
                    )
                ).scalar_one_or_none()
                if report.status == "success":
                    await record_success(session, conn_id)
                elif report.status == "failed":
                    await record_failure(session, conn_id)
                    from daemon.runner.circuit import maybe_trip

                    await maybe_trip(session, conn_id)
                await self._apply_report(session, task, agent, report, cfg, run_id)
        except Exception as err:  # noqa: BLE001 — демон не должен падать
            log.exception("run failed: %s", task_code)
            from daemon.scheduler.helpers import write_handoff_comment

            async with self._maker() as s2:
                # провайдер недоступен (DNS/сеть/API) — вина среды, не агента:
                # попытку не сжигаем (ФТ-ah-35 «задачи ждут, не блокируются»),
                # отказ пишем в предохранитель — пауза защитит весь конвейер
                provider_down = is_provider_unreachable(str(err))
                if not provider_down:
                    # обычные инфра-сбои считаются попыткой: иначе задача
                    # ретраится вечно (VITRINA-32…35: git-ошибка, ретрай каждый тик)
                    await s2.execute(
                        sa.text("UPDATE task SET retry_count = retry_count + 1 WHERE code = :c"),
                        {"c": task_code},
                    )
                    await s2.commit()
                # сбой среди сессии: лог непуст — след сессии пишет демон
                await write_handoff_comment(
                    s2,
                    await task_id_by_code(s2, task_code),
                    agent_id,
                    run_id,
                    f"Сбой раннера: {str(err)[:120]}",
                )
                await release_reservation(
                    s2,
                    await task_id_by_code(s2, task_code),
                    run_id,
                    "failed",
                    str(err)[:500],
                    reason_code="provider_unreachable" if provider_down else "runner_error",
                )
                if provider_down:
                    from daemon.runner.circuit import maybe_trip, record_failure

                    await record_failure(s2, None)
                    await maybe_trip(s2, None)
        finally:
            self._active.pop(run_id, None)
            self._runs.pop(run_id, None)
