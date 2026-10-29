"""Контракт раннера агента (риск R7, СТ §4.3.1 + решение владельца: Claude Agent SDK).

Вход: скилл + контекст задачи + worktree. Выход: RunReport (статус, summary,
обновления чеклистов, артефакт, предложенный переход). Heartbeat и прерывание —
зона ответственности scheduler (_touch_active/_sweep_dead_runs) и
reservation.release_reservation.

Живой лог (решение владельца 26.10.2026): раннер отдаёт каждое событие SDK
через req.on_event(kind, text=None, data=None) — промт, размышления,
вызовы инструментов, результаты, отчёт. Панель «вкладка Агент» стримит их
в реальном времени; демон пишет строки в task_run_log.

Токены (решение владельца 27.10.2026): usage каждого хода SDK накапливается
и отдаётся событием req.emit("usage", data={input, output, cache}) —
накопительные абсолютные значения за прогон; демон пишет их в task_run,
а интерфейс показывает живой счётчик (например «1300К»).
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

EventFn = Callable[..., Awaitable[None]]


@dataclass
class RunRequest:
    task_code: str
    context_md: str
    persona: str | None = None   # «Имя — роль»: единственная персона-строка от агента
    worktree_path: Path | None = None
    provider: dict | None = None   # {protocol,url,model,token} расшифрован только здесь
    timeouts: dict = field(default_factory=lambda: {"start": 300, "work": 1800})
    allowed_tools: tuple[str, ...] = ("Read", "Grep", "Glob", "Edit", "Write", "Bash")
    model: str | None = None         # модель прогона (иначе модель подключения)
    mcp_servers: dict | None = None  # {имя: {url|command, …}} — MCP-серверы
    agent_dir: str | None = None     # папка агентов (.claude); путь уже в координатах контейнера
    skills_md: tuple[str, ...] = ()  # содержимое явно назначенных скиллов (реестр инструментов)
    on_event: EventFn | None = None  # async (kind, text=None, data=None)

    async def emit(self, kind: str, text: str | None = None, data: dict | None = None) -> None:
        if self.on_event is None:
            return
        try:
            await self.on_event(kind, text=text, data=data)
        except Exception:  # noqa: BLE001 — лог не должен ронять прогон
            pass


@dataclass
class RunReport:
    status: str                     # success | failed | blocked
    summary_md: str = ""
    checklist_updates: list[dict] = field(default_factory=list)
    artifact_md: str | None = None
    artifact_kind: str | None = None
    proposed_transition: dict | None = None  # {"to": "...", "reason": "..."}
    questions: list[str] = field(default_factory=list)
    comments: list[str] = field(default_factory=list)  # комментарии агента к задаче
    raw: str = ""


REPORT_CONTRACT = """
Ты работаешь над задачей трекера AI-Harness. Отчитайся СТРОГО одним JSON-объектом
последней строкой ответа (без markdown-ограждения):
{"status": "success|failed|blocked",
 "summary_md": "что сделано и как проверялось",
 "checklist_updates": [{"checklist_kind": "developer|reviewer|tester",
                        "item_position": 1, "new_status": "todo|in_progress|closed|done|failed",
                        "text": "новый пункт (если добавляешь)"}],
 "artifact_md": "отчёт этапа (если требует скилл)",
 "artifact_kind": "dev_report|review_report|qa_report",
 "proposed_transition": {"to": "ключ статуса", "reason": "почему"},
 "questions": ["вопросы человеку"],
 "comments": ["короткие комментарии к задаче от первого лица (что сделано, что нашёл)"]}
Правила: работай только в текущем каталоге (worktree задачи); коммить осмысленно;
не выполняй merge и не переключай ветки; не выходи в интернет.
Комментарии видны человеку в карточке задачи — пишите по делу, 1–3 предложения.
"""


def parse_report(text: str) -> RunReport:
    """JSON report extraction; fallback = failed report.

    Scan candidates last-to-first via json.JSONDecoder.raw_decode from each
    '{' position: the old greedy regex broke on any stray braces in agent text.
    Status is validated against the contract.
    """
    dec = json.JSONDecoder()
    for m in reversed(list(re.finditer(r"\{", text))):
        try:
            raw, _end = dec.raw_decode(text, m.start())
        except ValueError:
            continue
        if not isinstance(raw, dict):
            continue
        if raw.get("status") not in ("success", "failed", "blocked"):
            continue
        return _report_from(raw, text)
    return RunReport(status="failed", summary_md="агент не вернул отчёт по контракту",
                     raw=text[-4000:])


def _report_from(raw: dict, text: str) -> RunReport:
    """Builds RunReport from parsed dict with field type guards."""
    transition = raw.get("proposed_transition")
    if not isinstance(transition, dict) or not isinstance(transition.get("to"), str):
        transition = None
    upd = [u for u in raw.get("checklist_updates", []) if isinstance(u, dict)]
    return RunReport(
        status=raw["status"],
        summary_md=str(raw.get("summary_md", "")),
        checklist_updates=upd,
        artifact_md=raw.get("artifact_md"),
        artifact_kind=raw.get("artifact_kind"),
        proposed_transition=transition,
        questions=[q for q in raw.get("questions", []) if isinstance(q, str)],
        comments=[c for c in raw.get("comments", []) if isinstance(c, str) and c.strip()],
        raw=text[-4000:],
    )


def _tail(s: str, n: int = 600) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else f"…{s[-n:]}"


def _build_prompt(req: RunRequest) -> str:
    """Промт прогона: персона + контекст задачи + назначенные скиллы + контракт отчёта.

    Свободного текста у агента больше нет (решение владельца 27.10.2026):
    методологии — в скиллах реестра, персона — одна строка «Имя — роль»."""
    parts = [f"Ты — {req.persona or 'исполнитель этапа конвейера'}.",
             f"# Контекст задачи\n{req.context_md}"]
    if req.skills_md:
        parts.append("# Подключённые скиллы (реестр инструментов)\n" + "\n\n".join(req.skills_md))
    parts.append(REPORT_CONTRACT)
    return "\n\n".join(parts)


def _options_cls(sdk) -> type:
    """Класс опций: в SDK 0.2+ это ClaudeAgentOptions, в старых версиях — ClaudeCodeOptions."""
    cls = getattr(sdk, "ClaudeAgentOptions", None) or getattr(sdk, "ClaudeCodeOptions", None)
    if cls is None:
        raise RuntimeError("claude-agent-sdk: не найден класс опций "
                           "(ClaudeAgentOptions/ClaudeCodeOptions)")
    return cls


def _options_kwargs(req: RunRequest, fields: set[str]) -> dict:
    """Опции вызова SDK — только те, что поддерживаются данной версией пакета.

    Неизвестные данной версии опции тихо отбрасываются: старый SDK не падает
    от новых полей профиля агента."""
    kwargs: dict = {"cwd": str(req.worktree_path) if req.worktree_path else None,
              "allowed_tools": list(req.allowed_tools),
              "permission_mode": "acceptEdits",
              "max_turns": 100}
    if req.model:
        kwargs["model"] = req.model
    if req.mcp_servers:
        kwargs["mcp_servers"] = req.mcp_servers
    if req.agent_dir:
        # подхват .claude из worktree: скиллы, команды, субагенты, настройки
        kwargs["setting_sources"] = ["project"]
    return {k: v for k, v in kwargs.items() if k in fields}


def _link_agent_dir(agent_dir: str, worktree) -> str:
    """Подключает папку инструментов к worktree БЕЗ копии (решение владельца 27.10.2026:
    SA-Helper уже установлен в папке — плодить копии по каждой задаче нельзя).

    Симлинк (Windows — junction, совсем без прав — копия). Ссылка живая: правки
    пользователя в папке сразу видны агенту. Возвращает способ подключения."""
    import shutil
    import sys

    src = Path(agent_dir).expanduser().resolve()
    dst = Path(worktree) / ".claude"
    if dst.is_symlink():
        dst.unlink()
    elif dst.exists():  # копия от прежней версии механики
        shutil.rmtree(dst)
    mode = "симлинк"
    try:
        dst.symlink_to(src, target_is_directory=True)
    except (OSError, NotImplementedError):
        linked = False
        if sys.platform == "win32":
            try:
                import _winapi

                _winapi.CreateJunction(str(src), str(dst))
                mode, linked = "junction", True
            except OSError:
                pass
        if not linked:
            shutil.copytree(src, dst, dirs_exist_ok=True)
            mode = "копия"
    _exclude_from_git(worktree, ".claude/")
    return mode


def _exclude_from_git(worktree, pattern: str) -> None:
    """Прячет служебную папку из git-статуса агента (только внутри worktree)."""
    dot_git = Path(worktree) / ".git"
    try:
        if dot_git.is_file():  # linked worktree: файл «gitdir: …»
            target = dot_git.read_text(encoding="utf-8").strip()
            gitdir = Path(target.removeprefix("gitdir:").strip())
            if not gitdir.is_absolute():
                gitdir = (Path(worktree) / gitdir).resolve()
        elif dot_git.is_dir():
            gitdir = dot_git
        else:
            return
        info = gitdir / "info"
        info.mkdir(parents=True, exist_ok=True)
        exclude = info / "exclude"
        lines = exclude.read_text(encoding="utf-8").splitlines() if exclude.exists() else []
        if pattern not in lines:
            lines.append(pattern)
            exclude.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass  # не критично: worst case — .claude видна в git status


def _sdk_env(provider: dict | None) -> dict[str, str]:
    """ANTHROPIC_* из расшифрованного подключения (Anthropic-совместимый прокси)."""
    if not provider or provider.get("protocol") not in (None, "anthropic"):
        return {}
    env: dict[str, str] = {}
    if provider.get("token"):
        env["ANTHROPIC_AUTH_TOKEN"] = provider["token"]
    if provider.get("url"):
        env["ANTHROPIC_BASE_URL"] = provider["url"]
    if provider.get("model"):
        env["ANTHROPIC_MODEL"] = provider["model"]
        env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = provider["model"]
    return env


class RunnerTimeout(Exception):
    """SDK/process did not produce messages within configured timeouts."""


class ClaudeCodeRunner:
    """Реальный раннер: headless Claude Agent SDK в worktree задачи.

    Каждое сообщение SDK превращается в событие req.on_event:
    system (старт сессии) → thinking (текст/размышления ассистента, целиком)
    → tool (вызов) → tool_result (хвост результата) → report (итог).
    """

    def __init__(self, sdk_module=None) -> None:
        if sdk_module is not None:
            self._sdk = sdk_module  # подменный SDK для тестов
            return
        try:
            import claude_agent_sdk as sdk  # noqa: F401

            self._sdk = sdk
        except ImportError as err:  # pragma: no cover
            raise RuntimeError(
                "claude-agent-sdk не установлен: pip install 'ai-harness[daemon]'"
            " (и CLI Claude Code: npm i -g @anthropic-ai/claude-code)") from err

    async def _iterate_sdk(self, req, prompt, options, collected, usage):
        """Iterates SDK messages with per-message timeout and process cleanup.

        The old code iterated without timeouts: a hung SDK = an eternal asyncio
        task, an unkilled process, and a task stuck forever in _active.
        """
        import asyncio
        loop = asyncio.get_running_loop()
        t = req.timeouts or {}
        start_to = float(t.get("start", 300))
        work_to = float(t.get("work", 1800))
        deadline = loop.time() + work_to
        gen = self._sdk.query(prompt=prompt, options=options)
        started = False
        try:
            while True:
                remaining = start_to if not started else max(0.0, deadline - loop.time())
                try:
                    message = await asyncio.wait_for(gen.__anext__(), timeout=remaining)
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    raise RunnerTimeout("start" if not started else "work") from None
                started = True
                await self._emit_message(req, message, collected, usage)
        finally:
            try:
                await gen.aclose()
            except Exception:
                pass


    async def run(self, req: RunRequest) -> RunReport:
        prompt = _build_prompt(req)
        await req.emit("prompt", text=prompt)
        opts_cls = _options_cls(self._sdk)
        fields = {f.name for f in dataclasses.fields(opts_cls)}
        if req.agent_dir and req.worktree_path:
            mode = _link_agent_dir(req.agent_dir, req.worktree_path)
            await req.emit("system", text=f"папка инструментов подключена ({mode}): "
                                         f"{req.agent_dir} → .claude")
        options = opts_cls(**_options_kwargs(req, fields))
        env = _sdk_env(req.provider)
        saved_env = None
        if env:
            if "env" in fields:
                options.env = env
            else:
                import os
                saved_env = {k: os.environ.get(k) for k in env}
                os.environ.update(env)
        collected: list[str] = []
        usage: dict = {"input": 0, "output": 0, "cache": 0, "total": 0}
        try:
            await self._iterate_sdk(req, prompt, options, collected, usage)
        except RunnerTimeout as err:
            await req.emit("system", text=f"timeout: {err.args[0]}")
            phase = "старт" if err.args and err.args[0] == "start" else "работа"
            return RunReport(status="failed",
                             summary_md=f"Таймаут прогона ({phase}) — процесс агента остановлен демоном")
        finally:
            if saved_env is not None:
                import os
                for k, v in saved_env.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
        report = parse_report("\n".join(collected))
        await req.emit("report", text=report.summary_md,
                       data={"status": report.status,
                             "proposed_transition": report.proposed_transition})
        return report


    async def _emit_message(self, req: RunRequest, message,
                            collected: list[str], usage: dict) -> None:
        sdk = self._sdk
        subtype = getattr(message, "subtype", None)
        if subtype == "init":
            await req.emit("system", text="сессия агента запущена",
                           data={"model": getattr(message, "model", None),
                                 "cwd": getattr(message, "cwd", None),
                                 "tools": getattr(message, "tools", None)})
            return
        _accumulate_usage(message, usage)
        if usage.get("total"):
            await req.emit("usage", data=dict(usage))
        content = getattr(message, "content", None)
        if content is None and getattr(message, "result", None) is not None:
            # ResultMessage: итоговый текст
            collected.append(str(getattr(message, "result")))
            return
        for block in (content or []):
            btype = type(block).__name__
            text = getattr(block, "text", None)
            thinking = getattr(block, "thinking", None)
            name = getattr(block, "name", None)
            if name and hasattr(block, "input"):  # ToolUseBlock
                await req.emit("tool", text=name,
                               data={"input": _short_input(getattr(block, "input", None))})
            elif btype == "ToolResultBlock" or hasattr(block, "content") and text is None and name is None:
                await req.emit("tool_result", text=_tail(str(getattr(block, "content", ""))))
            elif thinking:
                await req.emit("thinking", text=thinking)
            elif text:
                collected.append(text)
                await req.emit("thinking", text=text)


def _uget(usage, key: str) -> int:
    """usage бывает dict (ResultMessage) и объектом anthropic (AssistantMessage.message)."""
    if usage is None:
        return 0
    val = usage.get(key, 0) if isinstance(usage, dict) else getattr(usage, key, 0)
    return int(val or 0)


def _accumulate_usage(message, acc: dict) -> None:
    """Прибавляет usage хода к накопителю; сумма — input+output+cache («потрачено токенов»)."""
    u = getattr(message, "usage", None)
    if u is None:  # у AssistantMessage usage внутри исходного Message (message.message)
        u = getattr(getattr(message, "message", None), "usage", None)
    raw_in = _uget(u, "input_tokens")
    raw_out = _uget(u, "output_tokens")
    raw_cache = (_uget(u, "cache_read_input_tokens")
                 + _uget(u, "cache_creation_input_tokens"))
    if not (raw_in or raw_out or raw_cache):
        return
    acc["input"] += raw_in
    acc["output"] += raw_out
    acc["cache"] += raw_cache
    acc["total"] = acc["input"] + acc["output"] + acc["cache"]


def _short_input(inp, n: int = 400) -> dict | None:
    """Краткая форма аргументов инструмента для лога (без сырья целиком)."""
    if isinstance(inp, dict):
        return {k: _tail(str(v), 200) for k, v in list(inp.items())[:6]}
    if inp is None:
        return None
    return {"raw": _tail(str(inp), n)}


class FakeRunner:
    """Тестовый раннер: без вызова провайдера; сценарий задаётся функцией.
    Если сценарий не задан — проигрывает показательную ленту событий для панели."""

    def __init__(self, script=None) -> None:
        self.script = script
        self.requests: list[RunRequest] = []

    async def run(self, req: RunRequest) -> RunReport:
        import asyncio

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
        await req.emit("system", text="сессия агента запущена (демо-режим без SDK)",
                       data={"model": "fake", "cwd": str(req.worktree_path or ".")})
        await beat()
        spend(); await req.emit("usage", data=dict(usage))
        await req.emit("thinking", text="Читаю постановку задачи и чек-лист: "
                       "нужно понять, какой файл править и какие тесты затронуты.")
        await beat()
        await req.emit("tool", text="Read", data={"input": {"file_path": "src/board.tsx"}})
        await beat()
        spend(); await req.emit("usage", data=dict(usage))
        await beat()
        await req.emit("tool_result", text="export function Board() {\n  … 120 строк …}")
        await beat()
        await req.emit("thinking", text="Вижу причину: фильтр колонок учитывает только "
                       "дефолтные статусы. Правлю маппинг и добавляю тест.")
        await beat()
        await req.emit("tool", text="Edit", data={"input": {"file_path": "src/board.tsx",
                                                            "new_string": "colIdOfStatus(t.type, …)"}})
        await beat()
        spend(); await req.emit("usage", data=dict(usage))
        await beat()
        await req.emit("tool", text="Bash", data={"input": {"command": "npm test -- board"}})
        await beat()
        spend(); await req.emit("usage", data=dict(usage))
        await beat()
        await req.emit("tool_result", text="Tests: 8 passed")
        await beat()
        await req.emit("tool", text="Bash", data={"input": {"command": "git add -A && git commit -m fix"}})
        await beat()
        spend(); await req.emit("usage", data=dict(usage))
        await beat()
        await req.emit("tool_result", text="[task/AH-59] 1 file changed")
        await beat()
        await beat()
        spend(inp=31000, out=1400, cache=22000); await req.emit("usage", data=dict(usage))
        await req.emit("report", text="Демо-прогон завершён")
        return RunReport(status="success",
                         summary_md="Демо-прогон: правка применена, тесты зелёные.",
                         comments=["Добавил тест на сохранение темы — он поймал баг, "
                                   "который чинил вторым коммитом."],
                         proposed_transition=None, raw="demo")
