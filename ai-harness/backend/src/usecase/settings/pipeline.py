"""Рубильник конвейера и глобальные предупреждения (ФТ-ah-32/35/49/70, B3).

Логика перенесена из контроллера settings (расщепление B1) без изменений
поведения: контроллер только парсит вход и возвращает ответ.
"""

from __future__ import annotations

import sqlalchemy as sa

from sqlalchemy.ext.asyncio import AsyncSession

from repository.models import User


async def status(session: AsyncSession) -> dict:
    """Глобальные предупреждения конвейера (warnbar, ФТ-ah-35/49/70)."""
    import os

    warnings: list[dict] = []
    no_active = (await session.execute(sa.text(
        "SELECT count(*) FROM connection WHERE is_active"))).scalar_one()
    if not no_active:
        warnings.append({"level": "warn",
                         "message": "ИИ-провайдер не подключён: агенты конвейера не запустятся",
                         "goto": "#settings/providers"})
    broken = (await session.execute(sa.text(
        "SELECT mnemonic FROM project WHERE is_archived = false"))).scalars().all()
    from infrastructure.paths import host_to_container

    for mnemonic in broken:
        row = (await session.execute(sa.text(
            "SELECT path FROM project WHERE mnemonic = :m"), {"m": mnemonic})).scalar_one_or_none()
        real = host_to_container(row) if row else None
        if real and not (os.path.isdir(real) and os.access(real, os.W_OK)):
            warnings.append({"level": "danger",
                             "message": f"Путь проекта {mnemonic} недоступен: конвейер приостановлен",
                             "goto": "#settings/projects"})
    paused = (await session.execute(sa.text(
        "SELECT value FROM app_setting WHERE key = 'daemon.paused'"))).scalar_one_or_none()
    return {"warnings": warnings, "paused": paused == "true"}


async def pause(session: AsyncSession, actor: User, *, paused: bool,
                reason: str | None) -> dict:
    """Пауза конвейера: демон не запускает новых агентов; активные прогоны
    прерываются перехватом (ФТ-ah-32). Чат Eve не затрагивается — он идёт
    через API, а не через демон; прогоны чат-ботов исключены из прерывания."""
    import datetime as dt

    from repository.models import AppSetting, Chronicle, Task, TaskRun

    row = (await session.execute(
        sa.select(AppSetting).where(AppSetting.key == "daemon.paused"))).scalar_one_or_none()
    val = "true" if paused else "false"
    if row:
        row.value = val
    else:
        session.add(AppSetting(key="daemon.paused", value=val))
    from usecase.journal.settings_journal import record_and_commit

    interrupted = 0
    if paused:
        now = dt.datetime.now(dt.timezone.utc)
        runs = (await session.execute(
            sa.select(TaskRun, Task)
            .join(Task, Task.id == TaskRun.task_id)
            .join(User, User.id == TaskRun.agent_id)
            .where(TaskRun.finished_at.is_(None), User.is_chat_bot.is_(False)))).all()
        for run, task in runs:
            run.finished_at = now
            run.outcome = "interrupted"
            run.detail = ("конвейер остановлен владельцем: "
                          f"{reason or 'пауза конвейера'}")[:500]
            task.reserved_by = None
            task.reserved_at = None
            task.heartbeat_at = None
            session.add(Chronicle(task_id=task.id, event_type="agent", author_id=actor.id,
                                  author_kind="human",
                                  message="Прогон прерван: конвейер остановлен владельцем"))
            interrupted += 1
    await record_and_commit(
        session, actor.id, "flow",
        f"Конвейер {'приостановлен' if paused else 'возобновлен'}"
        + (f": {reason}" if reason else ""),
        [{"field": "paused", "new": val}])
    return {"ok": True, "paused": paused, "interrupted": interrupted}
