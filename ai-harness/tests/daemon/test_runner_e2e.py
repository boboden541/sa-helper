"""Прогон ClaudeCodeRunner на фейковом SDK: маршрут run() целиком.

Ловит ошибки сборки класса (метод потерян, вызов модульный и т.п.), которые
не видны на FakeRunner-пути демона."""

from __future__ import annotations

import dataclasses

from daemon.runner.agent_runner import ClaudeCodeRunner, RunRequest


@dataclasses.dataclass
class _Opts:
    cwd: str | None = None
    allowed_tools: list | None = None
    permission_mode: str = "default"
    max_turns: int = 10
    model: str | None = None
    mcp_servers: dict | None = None
    setting_sources: list | None = None


class _FakeSDK:
    ClaudeAgentOptions = _Opts

    @staticmethod
    async def query(*, prompt, options):
        class Msg:
            pass

        init = Msg()
        init.subtype = "init"
        init.model = "fake"
        init.cwd = "."
        init.tools = []
        yield init
        final = Msg()
        final.subtype = None
        final.usage = None
        final.message = None
        final.content = None
        final.result = ('{"status": "success", "summary_md": "готово", '
                        '"proposed_transition": {"to": "review", "reason": "ok"}}')
        yield final


async def test_runner_end_to_end_fake_sdk():
    runner = ClaudeCodeRunner(sdk_module=_FakeSDK())
    req = RunRequest(task_code="AH-T", context_md="контекст",
                     timeouts={"start": 5, "work": 10})
    report = await runner.run(req)
    assert report.status == "success"
    assert report.proposed_transition == {"to": "review", "reason": "ok"}


async def test_runner_timeout_aborts():
    import asyncio

    class SlowSDK:
        ClaudeAgentOptions = _Opts

        @staticmethod
        async def query(*, prompt, options):
            await asyncio.sleep(60)
            yield None  # pragma: no cover

    runner = ClaudeCodeRunner(sdk_module=SlowSDK())
    req = RunRequest(task_code="AH-T", context_md="контекст",
                     timeouts={"start": 1, "work": 2})
    report = await runner.run(req)
    assert report.status == "failed"
    assert "Таймаут" in report.summary_md
