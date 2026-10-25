"""Контракт раннера агента (риск R7, СТ §4.3.1 + решение владельца: Claude Agent SDK).

Вход: скилл + контекст задачи + worktree. Выход: RunReport (статус, summary,
обновления чеклистов, артефакт, предложенный переход). Heartbeat и прерывание —
зона ответственности daemon/runner/heartbeat.py.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RunRequest:
    task_code: str
    skill_md: str
    context_md: str
    worktree_path: Path | None = None
    provider: dict | None = None   # {protocol,url,model,token} расшифрован только здесь
    timeouts: dict = field(default_factory=lambda: {"start": 300, "work": 1800})
    allowed_tools: tuple[str, ...] = ("Read", "Grep", "Glob", "Edit", "Write", "Bash")


@dataclass
class RunReport:
    status: str                     # success | failed | blocked
    summary_md: str = ""
    checklist_updates: list[dict] = field(default_factory=list)
    artifact_md: str | None = None
    artifact_kind: str | None = None
    proposed_transition: dict | None = None  # {"to": "...", "reason": "..."}
    questions: list[str] = field(default_factory=list)
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
 "questions": ["вопросы человеку"]}
Правила: работай только в текущем каталоге (worktree задачи); коммить осмысленно;
не выполняй merge и не переключай ветки; не выходи в интернет.
"""


def parse_report(text: str) -> RunReport:
    """Извлекает последний JSON-объект отчёта из ответа агента; иначе failed."""
    matches = re.findall(r"\{.*\}", text, re.DOTALL)
    for candidate in reversed(matches):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("status") in ("success", "failed", "blocked"):
            return RunReport(
                status=data["status"],
                summary_md=data.get("summary_md", ""),
                checklist_updates=data.get("checklist_updates") or [],
                artifact_md=data.get("artifact_md"),
                artifact_kind=data.get("artifact_kind"),
                proposed_transition=data.get("proposed_transition"),
                questions=data.get("questions") or [],
                raw=text,
            )
    return RunReport(status="failed", summary_md="агент не вернул отчёт по контракту", raw=text)


class ClaudeCodeRunner:
    """Реальный раннер: headless Claude Agent SDK в worktree задачи."""

    def __init__(self, sdk_module=None) -> None:
        try:
            import claude_agent_sdk as sdk  # noqa: F401

            self._sdk = sdk
        except ImportError as err:  # pragma: no cover
            raise RuntimeError(
                "claude-agent-sdk не установлен: pip install 'ai-harness[daemon]'"
            ) from err

    async def run(self, req: RunRequest) -> RunReport:
        options = self._sdk.ClaudeCodeOptions(
            cwd=str(req.worktree_path) if req.worktree_path else None,
            allowed_tools=list(req.allowed_tools),
            permission_mode="acceptEdits",
            max_turns=100,
        )
        prompt = (f"# Скилл\n{req.skill_md}\n\n# Контекст задачи\n{req.context_md}\n"
                  f"{REPORT_CONTRACT}")
        collected: list[str] = []
        async for message in self._sdk.query(prompt=prompt, options=options):
            text = getattr(message, "text", None) or getattr(message, "result", None)
            if text:
                collected.append(text)
        return parse_report("\n".join(collected))


class FakeRunner:
    """Тестовый раннер: без вызова провайдера; сценарий задаётся функцией."""

    def __init__(self, script=None) -> None:
        self.script = script or (lambda req: RunReport(status="success", summary_md="ok"))
        self.requests: list[RunRequest] = []

    async def run(self, req: RunRequest) -> RunReport:
        self.requests.append(req)
        return self.script(req)
