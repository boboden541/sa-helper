"""Конфигурация демона из app_setting (перечитывается на каждом тике)."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from repository.models import AppSetting

_DEFAULTS = {
    "daemon.tick_seconds": "30",
    "daemon.timeout_start_seconds": "300",
    "daemon.timeout_work_seconds": "1800",
    "daemon.max_attempts": "3",
    "daemon.retry_pauses_minutes": "1,5,15",
    "daemon.max_parallel": "4",
}


async def load_daemon_settings(session: AsyncSession) -> dict[str, str]:
    rows = (await session.execute(
        sa.select(AppSetting.key, AppSetting.value).where(
            AppSetting.key.in_(_DEFAULTS.keys()))
    )).all()
    cfg = dict(_DEFAULTS)
    cfg.update(dict(rows))
    return cfg


def retry_pauses_minutes(cfg: dict[str, str]) -> list[int]:
    return [int(x) for x in cfg["daemon.retry_pauses_minutes"].split(",") if x.strip()]
