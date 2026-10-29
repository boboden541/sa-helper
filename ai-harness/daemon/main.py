"""Точка входа демона: python -m daemon.main (переиспользует домен backend'а)."""

from __future__ import annotations

import asyncio
import logging

from database import get_sessionmaker
from daemon.scheduler.scheduler import Daemon

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")


async def main() -> None:
    import os

    from daemon.runner.agent_runner import ClaudeCodeRunner

    if os.getenv("DAEMON_DEMO") == "1":
        # Демо-режим: показательная лента событий для панели «Прогоны» без SDK
        from daemon.runner.agent_runner import FakeRunner

        logging.warning("DAEMON_DEMO=1 — агент работает в демонстрационном режиме")
        runner = FakeRunner()
    else:
        try:
            runner = ClaudeCodeRunner()
        except RuntimeError:
            logging.warning("claude-agent-sdk не установлен — демон работает в режиме без запуска агентов")
            from daemon.runner.agent_runner import FakeRunner

            runner = FakeRunner(script=lambda req: __import__(
                "daemon.runner.agent_runner", fromlist=["RunReport"]).RunReport(
                status="blocked",
                summary_md="раннер агентов не настроен (claude-agent-sdk не установлен) — "
                           "требуется участие человека"))

    daemon = Daemon(get_sessionmaker(), runner)
    # стартовый интервал — из окружения; дальше источник истины —
    # app_setting daemon.tick_seconds, перечитывается перед каждым сном
    tick_seconds = max(1, int(os.getenv("DAEMON_TICK_SECONDS", "30")))
    logging.info("демон запущен (тик %s с)", tick_seconds)
    while True:
        import time as _time

        started = _time.monotonic()
        try:
            summary = await daemon.tick()
            duration = _time.monotonic() - started
            if duration > 10:
                logging.warning("медленный тик: %.1f с — %s", duration, summary)
            elif any(v for k, v in summary.items() if k != "launched") or summary["launched"]:
                logging.info("тик: %s", summary)
        except Exception:  # noqa: BLE001
            logging.exception("ошибка тика")
        tick_seconds = await daemon.tick_seconds(tick_seconds)
        await asyncio.sleep(tick_seconds)


if __name__ == "__main__":
    asyncio.run(main())
