"""Инфраструктура прогона: worktree, провайдер, прерывания, ретеншн.

Вынесено из scheduler.py (рефакторинг 04.11.2026 — лимит 800 строк);
поведение не менялось. Миксин SupportMixin подключается в Daemon (core).
"""

from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from domain.model.enums import GIT_TASK_TYPES
from repository.models import TaskRun


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

        return await ensure_task_worktree(
            project.path, task.code, project.base_branch, repo_path=task.repo_path
        )

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
