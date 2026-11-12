"""Демо-раннер: без SDK — показательная лента событий для панели «Прогоны».

Используется: DAEMON_DEMO=1 (демо-режим владельца) и fallback демона при
отсутствии claude-agent-sdk (демон жив, задачи получают честный blocked).
Реэкспортируется из agent_runner — исторические импорты трогать не стали.
"""

from __future__ import annotations

import asyncio

from daemon.runner.agent_runner import RunReport, RunRequest, _build_prompt


class FakeRunner:
    """Тестовый раннер: без вызова провайдера; сценарий задаётся функцией.
    Если сценарий не задан — проигрывает показательную ленту событий для панели."""

    def __init__(self, script=None) -> None:
        self.script = script
        self.requests: list[RunRequest] = []

    async def run(self, req: RunRequest) -> RunReport:

        self.requests.append(req)
        if self.script is not None:
            return self.script(req)

        async def beat() -> None:
            await asyncio.sleep(1.2)  # темп, похожий на реального агента

        usage = {"input": 0, "output": 0, "cache": 0, "total": 0}

        def spend(inp: int = 24000, out: int = 900, cache: int = 18000) -> None:
            usage["input"] += inp
            usage["output"] += out
            usage["cache"] += cache
            usage["total"] = usage["input"] + usage["output"] + usage["cache"]

        await req.emit("prompt", text=_build_prompt(req))
        await req.emit(
            "system",
            text="сессия агента запущена (демо-режим без SDK)",
            data={"model": "fake", "cwd": str(req.worktree_path or ".")},
        )
        await beat()
        spend()
        await req.emit("usage", data=dict(usage))
        await req.emit(
            "thinking",
            text="Читаю постановку задачи и чек-лист: "
            "нужно понять, какой файл править и какие тесты затронуты.",
        )
        await beat()
        await req.emit("tool", text="Read", data={"input": {"file_path": "src/board.tsx"}})
        await beat()
        spend()
        await req.emit("usage", data=dict(usage))
        await beat()
        await req.emit("tool_result", text="export function Board() {\n  … 120 строк …}")
        await beat()
        await req.emit(
            "thinking",
            text="Вижу причину: фильтр колонок учитывает только "
            "дефолтные статусы. Правлю маппинг и добавляю тест.",
        )
        await beat()
        await req.emit(
            "tool",
            text="Edit",
            data={
                "input": {"file_path": "src/board.tsx", "new_string": "colIdOfStatus(t.type, …)"}
            },
        )
        await beat()
        spend()
        await req.emit("usage", data=dict(usage))
        await beat()
        await req.emit("tool", text="Bash", data={"input": {"command": "npm test -- board"}})
        await beat()
        spend()
        await req.emit("usage", data=dict(usage))
        await beat()
        await req.emit("tool_result", text="Tests: 8 passed")
        await beat()
        await req.emit(
            "tool", text="Bash", data={"input": {"command": "git add -A && git commit -m fix"}}
        )
        await beat()
        spend()
        await req.emit("usage", data=dict(usage))
        await beat()
        await req.emit("tool_result", text="[task/AH-59] 1 file changed")
        await beat()
        await beat()
        spend(inp=31000, out=1400, cache=22000)
        await req.emit("usage", data=dict(usage))
        await req.emit("report", text="Демо-прогон завершён")
        return RunReport(
            status="success",
            summary_md="Демо-прогон: правка применена, тесты зелёные.",
            comments=[
                "Добавил тест на сохранение темы — он поймал баг, который чинил вторым коммитом."
            ],
            proposed_transition=None,
            raw="demo",
        )
