"""Применение отчётов агентов: переходы, чеклисты, связи, слияние.

Вынесено из scheduler.py (рефакторинг 04.11.2026 — лимит 800 строк);
поведение не менялось. Миксин ReportMixin подключается в Daemon (core).
"""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from repository.models import Task

from daemon.runner.reservation import release_reservation
from daemon.scheduler.helpers import _chronicle, blocked_reason_from_summary, log


class ReportMixin:
    async def _apply_report(
        self, session, task, agent, report, cfg, run_id: str | None = None
    ) -> None:
        from repository.models import Chronicle, Task
        from usecase.task.transition import TransitionDenied, apply_transition

        task = (await session.execute(sa.select(Task).where(Task.code == task.code))).scalar_one()
        # гвард параллельного режима: задача ушла со статуса прогона (человек,
        # сосед-агент, зеркало) — отчёт чужого статуса не применяется
        run_meta = self._runs.get(str(run_id)) or {}
        if run_meta.get("status_key") and task.status_key != run_meta["status_key"]:
            await release_reservation(
                session,
                task.id,
                run_id,
                "interrupted",
                "задача ушла со статуса — прогон остановлен",
                reason_code="stale_status",
            )
            await session.commit()
            return

        session.add(
            Chronicle(
                task_id=task.id,
                event_type="agent",
                author_id=agent.id,
                author_kind="agent",
                message=f"Отчёт агента: {report.summary_md[:300]}",
            )
        )
        # артефакт этапа (ФТ-ah-38): отчёт из JSON-отчёта агента получает новую
        # версию; без записи гейт cond_artifact честно отклонял переход — агент
        # делал работу, отчёт терялся (дефект 29.10.2026, нашли на AH-130)
        if report.artifact_md and report.artifact_kind in (
            "dev_report",
            "review_report",
            "qa_report",
        ):
            from repository.models import TaskArtifact

            ver = (
                await session.execute(
                    sa.text(
                        "SELECT coalesce(max(version),0)+1 FROM task_artifact "
                        "WHERE task_id = :t AND kind = :k"
                    ),
                    {"t": str(task.id), "k": report.artifact_kind},
                )
            ).scalar_one()
            session.add(
                TaskArtifact(
                    task_id=task.id,
                    kind=report.artifact_kind,
                    version=ver,
                    body_md=report.artifact_md,
                    created_by=agent.id,
                )
            )
            session.add(
                _chronicle(
                    task.id, "agent", f"Артефакт {report.artifact_kind} v{ver} записан агентом"
                )
            )
        await self._apply_relations(session, task, report)
        await self._apply_checklist_updates(session, task, report)

        if report.outcome_code == "soft_turns":
            # плановая смена сессии: не дефект и не вина агента — попытку не
            # сжигаем (иначе задача блокируется после 3 «смен», VITRINA-1,
            # 02.11.2026), исход interrupted даёт максимальную паузу до
            # следующей смены; чеклист/артефакт/связи уже применены выше
            session.add(
                _chronicle(
                    task.id, "agent", "Смена сессии (мягкий лимит ходов) — прогресс сохранён"
                )
            )
            await release_reservation(
                session,
                task.id,
                run_id,
                "interrupted",
                report.summary_md[:200],
                reason_code="soft_turns",
            )
            await session.commit()
            return

        if report.status == "success" and not report.proposed_transition:
            # агент не предложил переход — задача остаётся на статусе; повтор
            # откладывается паузой (_next_retry_at: success на том же статусе)
            session.add(
                _chronicle(
                    task.id, "agent", "Отчёт без предложенного перехода — повторный запуск отложен"
                )
            )
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
                decision = check_edge(
                    graph, task.status_key, to, subject, await load_gate_data(session, task)
                )
                if not decision.allowed:
                    raise TransitionDenied(decision.reason)
                if to == "done" and task.task_type_id:
                    await self._merge_before_done(session, task)
                # ФТ-FNR15-07: агентский переход комментирует система —
                # выжимка отчёта в хронику перехода (след «что сделано»)
                task = await apply_transition(
                    session, agent, task.code, to, comment=report.summary_md[:500]
                )
            except TransitionDenied as denied:
                task.retry_count += 1
                session.add(_chronicle(task.id, "engine", f"Переход отклонён: {denied.reason}"))
                await release_reservation(
                    session,
                    task.id,
                    run_id,
                    "failed",
                    denied.reason,
                    reason_code=denied.code or "denied_gate",
                )
                return
        elif report.status == "blocked":
            from usecase.task.transition import apply_blocked

            await apply_blocked(
                session,
                task,
                agent,
                blocked_reason_from_summary(report.summary_md),
                subject_kind="agent",
                rule_code="AGENT_REPORT",
            )
            await release_reservation(session, task.id, run_id, "blocked")
            await session.commit()
            return
        else:
            # провайдер недоступен (битый/пустой отчёт на фоне сетевого сбоя) —
            # вина среды: попытку не сжигаем (ФТ-ah-35), код для bypass'а запуска
            if report.outcome_code == "provider_unreachable":
                await release_reservation(
                    session,
                    task.id,
                    run_id,
                    "failed",
                    report.summary_md[:500],
                    reason_code="provider_unreachable",
                )
                await session.commit()
                return
            task.retry_count += 1
            # run_id обязателен: легаси-вызов без него закрывает ВСЕ активные
            # прогоны задачи — в параллельной матрице гасил строку живого соседа
            # и снимал резерв до его завершения (анализ 06.11.2026). А
            # reason_code="no_transition" — честный код для bypass-запроса.
            await release_reservation(
                session,
                task.id,
                run_id,
                "failed",
                report.summary_md[:500],
                reason_code="no_transition",
            )
            await session.commit()
            return

        # прогоны выше всегда return: строка достижима только после
        # УСПЕШНО применённого перехода (раньше комментарий обещал
        # «success без перехода» — тот кейс падает в else выше)
        await release_reservation(session, task.id, run_id, "success")
        await session.commit()

    async def _apply_checklist_updates(self, session, task, report) -> None:
        """Upsert-семантика (дефект 29.10.2026: пункт с item_position при пустом
        чеклисте тихо не применялся — UPDATE не попадал ни в одну строку, и
        декомпозиция Планировщика пропадала, гейт отклонял переход, сжигая
        попытки по ~100К токенов). Пункта нет или чеклиста нет — создаём."""
        applied = 0
        skipped_kinds: list[str] = []
        for upd in report.checklist_updates:
            kind = upd.get("checklist_kind")
            new_status = upd.get("new_status")
            if kind not in ("developer", "reviewer", "tester", "psi"):
                # тот же allowlist, что в checklist_put: агент не создаёт
                # чеклисты произвольного вида, влияющие на чеклист-гейты
                # (анализ 30.10.2026)
                if kind:
                    skipped_kinds.append(str(kind))
                continue
            if not kind or not new_status:
                continue
            chk = (
                await session.execute(
                    sa.text("SELECT id FROM checklist WHERE task_id = :t AND kind = :k"),
                    {"t": str(task.id), "k": kind},
                )
            ).first()
            if chk is None:
                chk = (
                    await session.execute(
                        sa.text(
                            "INSERT INTO checklist (id, task_id, kind) "
                            "VALUES (gen_random_uuid(), :t, :k) RETURNING id"
                        ),
                        {"t": str(task.id), "k": kind},
                    )
                ).first()
            position = upd.get("item_position")
            if position is not None:
                updated = (
                    await session.execute(
                        sa.text(
                            "UPDATE checklist_item ci SET status = :s, text = coalesce(:x, text) "
                            "FROM checklist c WHERE c.id = ci.checklist_id AND c.task_id = :t "
                            "AND c.kind = :k AND ci.position = :p RETURNING ci.id"
                        ),
                        {
                            "s": new_status,
                            "t": str(task.id),
                            "k": kind,
                            "p": position,
                            "x": upd.get("text"),
                        },
                    )
                ).first()
                if updated is not None:
                    applied += 1
                    continue
            if not upd.get("text"):
                continue
            pos = (
                position
                if position is not None
                else (
                    await session.execute(
                        sa.text(
                            "SELECT coalesce(max(position),0)+1 FROM checklist_item "
                            "WHERE checklist_id = :c"
                        ),
                        {"c": str(chk[0])},
                    )
                ).scalar_one()
            )
            await session.execute(
                sa.text(
                    "INSERT INTO checklist_item (id, checklist_id, position, kind, text, status) "
                    "VALUES (gen_random_uuid(), :c, :p, 'item', :x, :s) "
                    "ON CONFLICT DO NOTHING"
                ),
                {"c": str(chk[0]), "p": pos, "x": upd["text"], "s": new_status},
            )
            applied += 1
        await session.commit()
        if applied:
            session.add(
                _chronicle(task.id, "agent", f"Чеклист обновлён агентом ({applied} пункт(ов))")
            )
        if skipped_kinds:
            session.add(
                _chronicle(
                    task.id,
                    "agent",
                    "Типы чеклистов вне реестра пропущены: "
                    + ", ".join(sorted(set(skipped_kinds)))[:300],
                )
            )

    async def _apply_relations(self, session, task, report) -> int:
        """Связи из отчёта агента (relations_updates): blocked_by / do_after.
        Охраны как в API: существование задачи, не самозащёлка, без дублей."""
        from repository.models import TaskRelation

        applied = 0
        for rel in report.relations_updates:
            kind, other_code = rel.get("kind"), str(rel.get("task_code") or "").upper()
            if kind not in ("do_after", "blocked_by") or not other_code:
                continue
            other = (
                await session.execute(sa.select(Task).where(Task.code == other_code))
            ).scalar_one_or_none()
            if other is None or other.id == task.id:
                continue
            dup = (
                await session.execute(
                    sa.select(sa.func.count())
                    .select_from(TaskRelation)
                    .where(
                        TaskRelation.from_task == task.id,
                        TaskRelation.to_task == other.id,
                        TaskRelation.kind == kind,
                    )
                )
            ).scalar_one()
            if dup:
                continue
            session.add(TaskRelation(from_task=task.id, to_task=other.id, kind=kind))
            applied += 1
        if applied:
            await session.commit()
            session.add(_chronicle(task.id, "agent", f"Связи обновлены агентом ({applied} шт.)"))
        return applied

    async def _merge_before_done(self, session, task) -> None:
        """Слияние перед done (ФТ-ah-37); конфликт -> TransitionDenied (далее ретрай-лестница)."""
        from infrastructure.git.worktree import GitError, merge_task_branch
        from infrastructure.paths import host_to_container
        from repository.models import Project
        from usecase.task.transition import TransitionDenied

        project = await session.get(Project, task.project_id)
        # ФТ-FNR15-09, сценарий А: корень проекта — контейнер репозиториев (не git).
        # Для задачи без собственного repo_path сливать нечего — пропускаем слияние
        # без отказа перехода (раньше «не репозиторий» маскировалось под «копия
        # не чиста» и сжигало попытки; VITRINA-1 06.11.2026)
        if not project.path:
            # seed-задачи тестов без проекта-пути: слияния нет по определению
            return
        if not task.repo_path and not (Path(host_to_container(project.path)) / ".git").exists():
            session.add(
                _chronicle(
                    task.id,
                    "agent",
                    "Слияние не требуется: корень проекта не git-репозиторий "
                    "(документация и задачи без repo_path живут без веток)",
                )
            )
            await session.commit()
            return
        try:
            # путь проекта в БД хранится как на хосте; git-операции идут в контейнере
            git_info = await merge_task_branch(
                host_to_container(project.path),
                task.code,
                project.base_branch,
                repo_path=task.repo_path,
                # ФТ-FNR15-09, сценарий Б: документация конвейера не блокирует слияние
                keep_paths=[task.psi_path or "", ".harness"],
            )
            if git_info:
                # строка task_branch обязана существовать: раньше строку
                # создавала только legacy-миграция (анализ 06.11 — «story git
                # delta» была мёртва); теперь upsert и при слиянии
                await self._upsert_task_branch(session, project, task)
                from repository.models import TaskBranch

                tb = (
                    await session.execute(
                        sa.select(TaskBranch).where(TaskBranch.task_id == task.id)
                    )
                ).scalar_one()
                tb.head_commit = git_info.get("head_commit") or tb.head_commit
                tb.diff_stats = git_info.get("diff_stats") or tb.diff_stats
                merge_commit = git_info.get("merge_commit")
                # None = «уже смёржено» — метаданные прошлого слияния не
                # перезаписываем (иначе приходил чужой HEAD базы)
                if merge_commit:
                    tb.merge_commit = merge_commit
                    tb.merged_at = sa.func.now()
                await session.commit()
        except GitError as err:
            # str(GitError) уже включает stderr (диагностика шторма 29.10)
            text = str(err)
            if "не чиста" in text:
                raise TransitionDenied(f"{text} Автомат повторит слияние.", status_code=200)
            raise TransitionDenied(
                f"Слияние не выполнено: {text} — распутайте вручную, автомат повторит.",
                status_code=200,
            )
        # уборка: чистый worktree после слияния больше не нужен (ветка сохраняется)
        try:
            from infrastructure.git.worktree import cleanup_task_worktree

            await cleanup_task_worktree(
                host_to_container(project.path), task.code, repo_path=task.repo_path
            )
        except Exception:  # noqa: BLE001 - неуспешная уборка не роняет переход
            log.info("worktree cleanup skipped for %s", task.code, exc_info=True)
