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


@dataclasses.dataclass
class _OptsResume:
    cwd: str | None = None
    allowed_tools: list | None = None
    permission_mode: str = "default"
    max_turns: int = 10
    model: str | None = None
    mcp_servers: dict | None = None
    setting_sources: list | None = None
    resume: str | None = None
    session_id: str | None = None


class _ResumeCaptureSDK:
    """Ловит опции запроса и отдаёт session_id в init — раннер должен
    прокинуть resume_session_id в опции и имя сессии наружу."""

    ClaudeAgentOptions = _OptsResume
    last_options: object = None

    @staticmethod
    async def query(*, prompt, options):
        _ResumeCaptureSDK.last_options = options

        class Msg:
            pass

        init = Msg()
        init.subtype = "init"
        init.model = "fake"
        init.cwd = "."
        init.tools = []
        init.session_id = "sess-abc-123"
        yield init
        final = Msg()
        final.subtype = None
        final.usage = None
        final.message = None
        final.content = None
        final.result = '{"status": "success", "summary_md": "готово"}'
        yield final


async def test_resume_passed_and_session_captured():
    """Resume-сессия доходит до опций SDK, session_id из init уходит в on_event
    (демон пишет его в task_run для следующего resume)."""
    events: list = []

    async def on_event(kind, text=None, data=None):
        events.append((kind, data))

    runner = ClaudeCodeRunner(sdk_module=_ResumeCaptureSDK())
    req = RunRequest(task_code="AH-T", context_md="контекст",
                     timeouts={"start": 5, "work": 10},
                     resume_session_id="sess-prev-42", on_event=on_event)
    report = await runner.run(req)
    assert report.status == "success"
    opts = _ResumeCaptureSDK.last_options
    assert opts.resume == "sess-prev-42", "resume_session_id → options.resume"
    kinds = [(k, (d or {}).get("session_id")) for k, d in events]
    assert ("system", "sess-abc-123") in kinds, "session_id из init — в событиях"


async def test_resume_dropped_when_sdk_unsupported():
    """Старый SDK без поля resume: опция тихо отбрасывается, прогон не падает."""

    class _OldSDK(_FakeSDK):
        pass

    runner = ClaudeCodeRunner(sdk_module=_OldSDK())
    req = RunRequest(task_code="AH-T", context_md="к",
                     timeouts={"start": 5, "work": 10},
                     resume_session_id="sess-x")
    report = await runner.run(req)
    assert report.status == "success"
