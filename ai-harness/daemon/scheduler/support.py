"""Инфраструктура прогона: worktree, провайдер, прерывания, ретеншн.

Вынесено из scheduler.py (рефакторинг 04.11.2026 — лимит 800 строк);
поведение не менялось. Миксин SupportMixin подключается в Daemon (core).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
from pathlib import Path

import sqlalchemy as sa
from domain.model.enums import GIT_TASK_TYPES
from repository.models import TaskBranch, TaskRun


class SupportMixin:
    async def _ensure_worktree(self, session, task):
        from repository.models import Project

        if task.status_key != "in_progress":
            return None
        type_key = (
            await session.execute(
                sa.text("SELECT key FROM task_type WHERE id = :i"), {"i": str(task.task_type_id)}
            )
        ).scalar_one()
        if type_key not in GIT_TASK_TYPES:
            return None
        project = await session.get(Project, task.project_id)

        from infrastructure.git.worktree import ensure_task_worktree

        wt = await ensure_task_worktree(
            project.path, task.code, project.base_branch, repo_path=task.repo_path
        )
        await self._upsert_task_branch(session, project, task, wt_path=str(wt))
        return wt

    async def _upsert_task_branch(self, session, project, task, wt_path: str | None = None) -> None:
        """Writer строки task_branch (ФТ-FNR14-03): в живом потоке строку не
        писал никто — только legacy-миграция, поэтому «story git delta» всю
        дорогу был мёртв (анализ 06.11.2026). Пишем при создании worktree и
        добиваем при слиянии; idempotent по uq task_branch.task_id."""
        from infrastructure.git.worktree import worktree_path_for
        from infrastructure.paths import host_to_container

        if task.repo_path:
            root = host_to_container(str(Path(project.path) / task.repo_path))
        else:
            root = host_to_container(project.path)
        path = wt_path or str(worktree_path_for(root, task.code))
        tb = (
            await session.execute(sa.select(TaskBranch).where(TaskBranch.task_id == task.id))
        ).scalar_one_or_none()
        if tb is None:
            session.add(
                TaskBranch(
                    task_id=task.id,
                    branch_name=f"task/{task.code}",
                    worktree_path=path[:500],
                )
            )
        elif tb.worktree_path != path[:500]:
            tb.worktree_path = path[:500]
        # коммит делает вызывающий (тиковая транзакция/merge-блок уже с ним)

    async def _verify_stand(self, run_session, task) -> None:
        """Телеметрия стенда (ФТ-FNR14-05): перед стартом прогона демон опрашивает
        сервисы манифеста .harness/stand.json → task.stand_verified_at /
        stand_health_status. Раньше колонки были мёртвыми (анализ 06.11.2026).
        НЕ гейтит запуск — решение о блокировке задач при лежащем стенде остаётся
        за владельцем; факт доступен агентам и карточке."""
        from urllib.parse import urlparse

        from infrastructure.paths import host_to_container, task_repo_root
        from repository.models import Project

        project = await run_session.get(Project, task.project_id)
        if not project or not project.path:
            return
        stand_path = (
            Path(host_to_container(task_repo_root(project.path, task.repo_path)))
            / ".harness"
            / "stand.json"
        )
        if not stand_path.exists():
            return
        status = "unknown"
        try:
            stand = json.loads(stand_path.read_text(encoding="utf-8"))
            services = stand.get("services", {})
            status = "up"
            for _name, info in services.items():
                url = info.get("base_url") or info.get("dsn") or ""
                parsed = urlparse(url)
                if not (parsed.hostname and parsed.port):
                    continue  # dsn без порта и прочие неразборчивые — пропустить
                try:
                    _reader, writer = await asyncio.wait_for(
                        asyncio.open_connection(parsed.hostname, parsed.port), timeout=3.0
                    )
                    writer.close()
                except Exception:  # noqa: BLE001 — любой сетевой отказ = «down»
                    status = "down"
                    break
        except Exception:  # noqa: BLE001 — нечитаемый манифест = «unknown»
            status = "unknown"
        await run_session.execute(
            sa.text(
                "UPDATE task SET stand_verified_at = now(), stand_health_status = :s WHERE id = :i"
            ),
            {"s": status, "i": str(task.id)},
        )
        await run_session.commit()

    async def _stand_down(self, session, task) -> bool:
        """ФТ-FNR14-09: жёсткий гейт запуска — при лежащем стенде прогон
        in_testing не стартует вовсе: попытки не горят, в хронику эпизод
        пишется один раз (не спамим каждый тик). Nondeterministic-сеть не
        блокирует: «unknown» (нечитаемый манифест) пропускается."""
        from urllib.parse import urlparse

        from infrastructure.paths import host_to_container, task_repo_root
        from repository.models import Project

        from daemon.scheduler.helpers import _chronicle

        project = await session.get(Project, task.project_id)
        if not project or not project.path:
            return False
        stand_path = (
            Path(host_to_container(task_repo_root(project.path, task.repo_path)))
            / ".harness"
            / "stand.json"
        )
        if not stand_path.exists():
            return False
        status = "unknown"
        try:
            stand = json.loads(stand_path.read_text(encoding="utf-8"))
            services = stand.get("services", {})
            status = "up"
            for _name, info in services.items():
                url = info.get("base_url") or info.get("dsn") or ""
                parsed = urlparse(url)
                if not (parsed.hostname and parsed.port):
                    continue
                try:
                    _reader, writer = await asyncio.wait_for(
                        asyncio.open_connection(parsed.hostname, parsed.port), timeout=3.0
                    )
                    writer.close()
                except Exception:  # noqa: BLE001
                    status = "down"
                    break
        except Exception:  # noqa: BLE001
            status = "unknown"
        if status != "down":
            notified = getattr(self, "_stand_notified", None)
            if notified:
                notified.discard(str(task.id))
            return False
        notified = getattr(self, "_stand_notified", None)
        if notified is None:
            notified = set()
            self._stand_notified = notified
        if str(task.id) in notified:
            return True
        notified.add(str(task.id))
        session.add(
            _chronicle(
                task.id,
                "agent",
                "Стенд недоступен (stand_unavailable): сервис манифеста .harness/"
                "stand.json не отвечает — прогон отложен, попытка не сгорает",
            )
        )
        await session.commit()
        return True

    async def _provider_for(self, session, agent_id) -> dict | None:
        """Расшифрованное подключение агента (ANTHROPIC_* для раннера).
        Расшифровка только здесь и только на момент запуска (СТ §4.4.2)."""
        from repository.models import Connection
        from usecase.settings.connections import get_decrypted_token

        conn_id = (
            await session.execute(
                sa.text("SELECT connection_id FROM agent_profile WHERE user_id = :u"),
                {"u": str(agent_id)},
            )
        ).scalar_one_or_none()
        conn = await session.get(Connection, conn_id) if conn_id else None
        if conn is None:  # своё подключение не задано — активное глобальное
            conn = (
                await session.execute(
                    sa.select(Connection).where(Connection.is_active.is_(True)).limit(1)
                )
            ).scalar_one_or_none()
        if conn is None:
            return None
        if conn.protocol == "openai":
            # фаст-фейл вместо молчаливого ухода на дефолтного провайдера
            # (анализ 03.11.2026: _sdk_env возвращал пустой env, прогон уходил
            # на дефолт; DomainError → INFRA-blocked, попытки не сжигаются)
            from domain.model.validators import DomainError

            raise DomainError(
                "Подключение с протоколом openai не поддерживается прогонами "
                "агентов: SDK работает только с Anthropic-совместимыми "
                "эндпоинтами. Назначьте агенту anthropic-совместимое "
                "подключение (или активное глобальное)."
            )
        return {
            "protocol": conn.protocol,
            "url": conn.url,
            "model": conn.model,
            "token": await get_decrypted_token(session, conn),
        }

    async def _check_interrupts(self, session) -> int:
        """Перехват человеком: прогон помечен outcome='interrupted' -> убить процесс (ФТ-ah-32).
        Матч по run_id текущего прогона, а не по окну времени: свежезапущенный прогон
        не гасится эхом чужого перехвата. Незавершённый отчёт не применяется."""
        if not self._active:
            return 0
        now = dt.datetime.now(dt.timezone.utc)
        rows = (
            await session.execute(
                sa.select(TaskRun.id).where(
                    TaskRun.finished_at.isnot(None),
                    TaskRun.outcome == "interrupted",
                    TaskRun.finished_at >= now - dt.timedelta(minutes=10),
                    TaskRun.id.in_(list(self._active.keys())),
                )
            )
        ).all()
        killed = 0
        for (rid,) in rows:
            t = self._active.get(str(rid))
            if t is not None and not t.done():
                t.cancel()
                killed += 1
            # run-строка уже помечена в БД перехватом; чистим учёт демона
            self._active.pop(str(rid), None)
            self._runs.pop(str(rid), None)
        return killed

    async def _retention_tick(self, session) -> None:
        """Сырые строки живого лога старше 7 дней удаляются; раз в сутки (решение владельца)."""
        from repository.models import AppSetting

        key = "runlog.retention_last"
        today = dt.datetime.now(dt.timezone.utc).date().isoformat()
        last = (
            await session.execute(sa.select(AppSetting.value).where(AppSetting.key == key))
        ).scalar_one_or_none()
        if last == today:
            return
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)
        from repository.models import TaskRunLog

        await session.execute(sa.delete(TaskRunLog).where(TaskRunLog.created_at < cutoff))
        row = (
            await session.execute(sa.select(AppSetting).where(AppSetting.key == key))
        ).scalar_one_or_none()
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
        rows = (
            (
                await session.execute(
                    sa.select(ToolArtifact).where(
                        ToolArtifact.kind == "skill", ToolArtifact.name.in_(names)
                    )
                )
            )
            .scalars()
            .all()
        )
        by_name = {r.name: r for r in rows}
        out: list[str] = []
        for n in names:
            r = by_name.get(n)
            path = root / r.rel_path if r else None
            if path and path.is_file():
                out.append(
                    f"## Скилл: {n}\n\n" + path.read_text(encoding="utf-8", errors="replace")
                )
            else:
                out.append(
                    f"## Скилл: {n}\n\n(файл не найден в папке инструментов — скилл пропущен)"
                )
        return out
