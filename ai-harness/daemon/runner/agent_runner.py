"""Контракт раннера агента (риск R7, СТ §4.3.1 + решение владельца: Claude Agent SDK).

Вход: скилл + контекст задачи + worktree. Выход: RunReport (статус, summary,
обновления чеклистов, артефакт, предложенный переход). Heartbeat и прерывание —
зона ответственности daemon/runner/heartbeat.py.

Живой лог (решение владельца 26.10.2026): раннер отдаёт каждое событие SDK
через req.on_event(kind, text=None, data=None) — промт, размышления,
вызовы инструментов, результаты, отчёт. Панель «вкладка Агент» стримит их
в реальном времени; демон пишет строки в task_run_log.
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
    skill_md: str
    context_md: str
    worktree_path: Path | None = None
    provider: dict | None = None   # {protocol,url,model,token} расшифрован только здесь
    timeouts: dict = field(default_factory=lambda: {"start": 300, "work": 1800})
    allowed_tools: tuple[str, ...] = ("Read", "Grep", "Glob", "Edit", "Write", "Bash")
    model: str | None = None         # модель прогона (иначе модель подключения)
    mcp_servers: dict | None = None  # {имя: {url|command, …}} — MCP-серверы
    agent_dir: str | None = None     # папка агентов (.claude); путь уже в координатах контейнера
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
    """Достаёт последний JSON-объект отчёта из текста агента; при неудаче — failed."""
    import contextlib

    for candidate in reversed(re.findall(r"\{.*\}", text, re.DOTALL)):
        with contextlib.suppress(json.JSONDecodeError):
            raw = json.loads(candidate)
            return RunReport(
                status=raw.get("status", "failed"),
                summary_md=raw.get("summary_md", ""),
                checklist_updates=raw.get("checklist_updates", []),
                artifact_md=raw.get("artifact_md"),
                artifact_kind=raw.get("artifact_kind"),
                proposed_transition=raw.get("proposed_transition"),
                questions=raw.get("questions", []),
                comments=[c for c in raw.get("comments", []) if isinstance(c, str) and c.strip()],
                raw=text[-4000:],
            )
    return RunReport(status="failed", summary_md="агент не вернул отчёт по контракту",
                     raw=text[-4000:])


def _tail(s: str, n: int = 600) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else f"…{s[-n:]}"


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


class ClaudeCodeRunner:
    """Реальный раннер: headless Claude Agent SDK в worktree задачи.

    Каждое сообщение SDK превращается в событие req.on_event:
    system (старт сессии) → thinking (текст/размышления ассистента, целиком)
    → tool (вызов) → tool_result (хвост результата) → report (итог).
    """

    def __init__(self, sdk_module=None) -> None:
        try:
            import claude_agent_sdk as sdk  # noqa: F401

            self._sdk = sdk
        except ImportError as err:  # pragma: no cover
            raise RuntimeError(
                "claude-agent-sdk не установлен: pip install 'ai-harness[daemon]'"
            " (и CLI Claude Code: npm i -g @anthropic-ai/claude-code)") from err

    async def run(self, req: RunRequest) -> RunReport:
        prompt = (f"# Скилл\n{req.skill_md}\n\n# Контекст задачи\n{req.context_md}\n"
                  f"{REPORT_CONTRACT}")
        await req.emit("prompt", text=prompt)
        opts_cls = _options_cls(self._sdk)
        fields = {f.name for f in dataclasses.fields(opts_cls)}
        if req.agent_dir and req.worktree_path:
            mode = _link_agent_dir(req.agent_dir, req.worktree_path)
            await req.emit("system", text=f"папка инструментов подключена ({mode}): "
                                         f"{req.agent_dir} → .claude")
        options = opts_cls(**_options_kwargs(req, fields))
        env = _sdk_env(req.provider)
        if env:
            try:
                options.env = env
            except Exception:  # noqa: BLE001 — старые версии SDK без поля env
                import os

                os.environ.update(env)

        collected: list[str] = []
        async for message in self._sdk.query(prompt=prompt, options=options):
            await self._emit_message(req, message, collected)
        report = parse_report("\n".join(collected))
        await req.emit("report", text=report.summary_md,
                       data={"status": report.status,
                             "proposed_transition": report.proposed_transition})
        return report

    async def _emit_message(self, req: RunRequest, message, collected: list[str]) -> None:
        sdk = self._sdk
        subtype = getattr(message, "subtype", None)
        if subtype == "init":
            await req.emit("system", text="сессия агента запущена",
                           data={"model": getattr(message, "model", None),
                                 "cwd": getattr(message, "cwd", None),
                                 "tools": getattr(message, "tools", None)})
            return
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

        await req.emit("prompt", text=f"# Скилл\n{req.skill_md}\n\n# Контекст\n{req.context_md}")
        await req.emit("system", text="сессия агента запущена (демо-режим без SDK)",
                       data={"model": "fake", "cwd": str(req.worktree_path or ".")})
        await beat()
        await req.emit("thinking", text="Читаю постановку задачи и чек-лист: "
                       "нужно понять, какой файл править и какие тесты затронуты.")
        await beat()
        await req.emit("tool", text="Read", data={"input": {"file_path": "src/board.tsx"}})
        await beat()
        await req.emit("tool_result", text="export function Board() {\n  … 120 строк …}")
        await beat()
        await req.emit("thinking", text="Вижу причину: фильтр колонок учитывает только "
                       "дефолтные статусы. Правлю маппинг и добавляю тест.")
        await beat()
        await req.emit("tool", text="Edit", data={"input": {"file_path": "src/board.tsx",
                                                            "new_string": "colIdOfStatus(t.type, …)"}})
        await beat()
        await req.emit("tool", text="Bash", data={"input": {"command": "npm test -- board"}})
        await beat()
        await req.emit("tool_result", text="Tests: 8 passed")
        await beat()
        await req.emit("tool", text="Bash", data={"input": {"command": "git add -A && git commit -m fix"}})
        await beat()
        await req.emit("tool_result", text="[task/AH-59] 1 file changed")
        await beat()
        await req.emit("report", text="Демо-прогон завершён")
        return RunReport(status="success",
                         summary_md="Демо-прогон: правка применена, тесты зелёные.",
                         comments=["Добавил тест на сохранение темы — он поймал баг, "
                                   "который чинил вторым коммитом."],
                         proposed_transition=None, raw="demo")
