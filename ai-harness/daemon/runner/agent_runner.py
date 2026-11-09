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

import asyncio
import dataclasses
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

EventFn = Callable[..., Awaitable[None]]

# Старый SDK без поля env у опций: ANTHROPIC_* ставятся в os.environ всего
# процесса — два параллельных прогона с разными подключениями могли уйти
# с чужим токеном/моделью. Такие прогоны сериализуются локом; современный
# путь (options.env) работает без локи — параллелизм сохраняется.
_ENV_LOCK = asyncio.Lock()


@dataclass
class RunRequest:
    task_code: str
    context_md: str
    persona: str | None = None  # «Имя — роль»: единственная персона-строка от агента
    worktree_path: Path | None = None
    # cwd прогона без worktree (папка проекта); при worktree cwd = worktree_path
    cwd_path: str | None = None
    provider: dict | None = None  # {protocol,url,model,token} расшифрован только здесь
    timeouts: dict = field(default_factory=lambda: {"start": 300, "work": 1800})
    allowed_tools: tuple[str, ...] = ("Read", "Grep", "Glob", "Edit", "Write", "Bash")
    model: str | None = None  # модель прогона (иначе модель подключения)
    mcp_servers: dict | None = None  # {имя: {url|command, …}} — MCP-серверы
    agent_dir: str | None = None  # папка агентов (.claude); путь уже в координатах контейнера
    skills_md: tuple[str, ...] = ()  # содержимое явно назначенных скиллов (реестр инструментов)
    skills: tuple[str, ...] = ()  # имена скиллов; первый — вызовом /имя первой строкой промта
    max_turns: int = 100  # ходов SDK; демон всегда передаёт app_setting daemon.max_turns
    resume_session_id: str | None = None  # продолжить прошлую сессию (лимит ходов/таймаут)
    soft_turns: int | None = None  # мягкий лимит ходов: смена сессии до деградации контекста
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
    status: str  # success | failed | blocked
    summary_md: str = ""
    checklist_updates: list[dict] = field(default_factory=list)
    artifact_md: str | None = None
    artifact_kind: str | None = None
    proposed_transition: dict | None = None  # {"to": "...", "reason": "..."}
    relations_updates: list[dict] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    comments: list[str] = field(default_factory=list)  # комментарии агента к задаче
    raw: str = ""
    # машиночитаемый код исхода (миграция 0013): timeout_start/work, turns_limit,
    # soft_turns, no_report — планировщик решает по коду, не подстроками текста
    outcome_code: str | None = None


REPORT_CONTRACT = """
Ты работаешь над задачей трекера AI-Harness. Отчитайся СТРОГО одним JSON-объектом
последней строкой ответа (без markdown-ограждения):
{"status": "success|failed|blocked",
 "summary_md": "что сделано и как проверялось",
 "checklist_updates": [{"checklist_kind": "developer|reviewer|tester|psi",
                        "item_position": 1, "new_status": "todo|in_progress|closed|done|failed",
                        "text": "текст пункта: для нового пункта обязателен, "
                                "для существующего — обнови статус"}],
 "relations_updates": [{"task_code": "MNEMONIC-N", "kind": "do_after|blocked_by",
                        "note": "почему (кратко)"}],
 "artifact_md": "отчёт этапа (если требует скилл)",
 "artifact_kind": "dev_report|review_report|qa_report",
 "proposed_transition": {"to": "ключ статуса", "reason": "почему"},
 "questions": ["вопросы человеку"],
 "comments": ["короткие комментарии к задаче от первого лица (что сделано, что нашёл)"]}
Правила: работай только в текущем каталоге (worktree задачи); коммить осмысленно;
не выполняй merge и не переключай ветки; не выходи в интернет.
ЧЕКЛИСТ — КРИТИЧНО. Это источник истины о прогрессе задачи: прогоны сменяют
друг друга, и открытые пункты в контексте — точка продолжения с того места,
где остановился предыдущий агент. Поэтому: (1) начни прогона со сверки с
открытыми пунктами — продолжай с них, закрытые пункты не переделывай;
(2) выполнил пункт работы — ОБЯЗАТЕЛЬНО включи его в checklist_updates ЭТОГО
ЖЕ отчёта с new_status=closed/done: невключённый выполненный пункт блокирует
гейт перехода и обесценивает весь прогон.
СОХРАНЁННЫЕ ФАЙЛЫ: если работа дала файл (документ, отчёт, выгрузка) —
укажи его путь в summary_md и/или комментарии. Файл, путь которого никому
не сообщён, считается потерянным.
Если status=blocked: ПОСЛЕДНЕЕ предложение summary_md — точная причина блокировки
и что нужно от человека (карточка показывает хвост summary).
Переход: предложи переход только по существующему ребру из твоего текущего статуса
(ключи статусов и рёбра — в контексте задачи). Если твой прошлый переход был
отклонён (причина отказа — в хрониках задачи, они в контексте): устрани причину —
создай или закрой чеклист нужного вида, запиши отчёт этапа, сними блокеры — и
предложи переход снова. Причину, которую ты устранить не можешь, не обходи:
верни {"status": "blocked", ...} с объяснением, решение за человеком.
Комментарии: видны человеку в карточке задачи — пишите по делу, 1–3 предложения.
КОММЕНТАРИИ ОБЯЗАТЕЛЬНЫ при любом исходе (success, failed, blocked): от первого
лица — что сделано, что нашёл, где остановился. Следующая сессия начинает работу
с чтения комментариев — без них точка продолжения теряется.
Связи (relations_updates) — для явных зависимостей между задачами: «blocked_by» —
не брать в работу, пока указанная задача не закрыта; «do_after» — порядок без
жёсткой блокировки. Указывай только реальные зависимости по постановке.
"""


# Признаки «провайдер недоступен» в тексте ошибки SDK/CLI (не вина агента):
# такие сбои не должны сжигать попытки и блокировать задачу (ФТ-ah-35 —
# «массовый отказ провайдера: задачи ждут, не блокируются»; 04.11.2026)
_PROVIDER_DOWN_MARKS = (
    "Can't reach the API server",
    "EAI_AGAIN",
    "ENOTFOUND",
    "ECONNREFUSED",
    "ETIMEDOUT",
    "ECONNRESET",
    "fetch failed",
    "api.anthropic.com",
    "api.z.ai",
)


def is_provider_unreachable(err_text: str) -> bool:
    """True — ошибка среды/сети провайдера, ретрай бессмыслен прямо сейчас."""
    text = err_text or ""
    return any(mark in text for mark in _PROVIDER_DOWN_MARKS)


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
    # Строгий разбор не удался — частая причина у не-Anthropic моделей
    # (GLM и др.): непэкранированная кавычка/сырой перевод строки внутри
    # длинного поля отчёта. Весь труд агента терять нельзя — мягкое
    # извлечение полей регулярками по последнему JSON-фрагменту.
    lenient = _parse_report_lenient(text)
    if lenient is not None:
        return lenient
    return RunReport(
        status="failed",
        summary_md="агент не вернул отчёт по контракту",
        # классификация «провайдер недоступен» — ТОЛЬКО по тексту исключения
        # среды (except-путь run.py), не по текстам агента: сетевые задачи
        # упоминают ECONNREFUSED/таймауты в своём труде — ложная классификация
        # освобождала попытку и крутила задачу по кругу (анализ 06.11.2026)
        outcome_code="no_report",
        raw=text[-4000:],
    )


_LENIENT_STATUS = re.compile(r'"status"\s*:\s*"(success|failed|blocked)"')
_LENIENT_FIELD_T = r'"{}"\s*:\s*"((?:[^"\\]|\\.)*)"'


def _unjson(s: str) -> str:
    """Разворачивает базовые \\n/\\t/\" в тексте поля."""
    return s.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"')


def _parse_report_lenient(text: str) -> RunReport | None:
    """Мягкое извлечение отчёта из битого JSON: статус, переход, артефакт,
    чеклист-обновления по регуляркам. Срабатывает только если строгий
    разбор не удался — битые поля лучше потерянного прогона."""
    if '"status"' not in text:
        return None
    m = _LENIENT_STATUS.search(text)
    if not m:
        return None
    status = m.group(1)

    def field(name: str) -> str | None:
        mm = re.compile(_LENIENT_FIELD_T.format(name)).search(text)
        return _unjson(mm.group(1)) if mm else None

    summary = field("summary_md") or ""
    transition = None
    mt = re.search(
        r'"proposed_transition"\s*:\s*\{[^}]*?"to"\s*:\s*"([a-z_0-9]+)"'
        r'[^}]*?"reason"\s*:\s*"((?:[^"\\]|\\.)*)"',
        text,
    )
    if mt:
        transition = {"to": mt.group(1), "reason": _unjson(mt.group(2))}

    updates = []
    for um in re.finditer(
        r'"checklist_kind"\s*:\s*"(developer|reviewer|tester|psi)"'
        r'[^{}]*?"item_position"\s*:\s*(\d+)'
        r'[^{}]*?"new_status"\s*:\s*"(todo|in_progress|closed|done|failed)"'
        r'(?:[^{}]*?"text"\s*:\s*"((?:[^"\\]|\\.)*)")?',
        text,
    ):
        updates.append(
            {
                "checklist_kind": um.group(1),
                "item_position": int(um.group(2)),
                "new_status": um.group(3),
                "text": _unjson(um.group(4)) if um.group(4) else None,
            }
        )

    artifact_md = field("artifact_md")
    artifact_kind = field("artifact_kind")
    if artifact_kind not in ("dev_report", "review_report", "qa_report"):
        artifact_kind = None
        artifact_md = None

    comments = re.findall(r'"comments"\s*:\s*\[(.*?)\]', text, re.S)
    comment_list = []
    if comments:
        for cm in re.finditer(r'"((?:[^"\\]|\\.)*)"', comments[-1]):
            body = _unjson(cm.group(1)).strip()
            if body:
                comment_list.append(body[:4000])

    return RunReport(
        status=status,
        summary_md=summary[:2000] or "(мягкий разбор битого JSON)",
        checklist_updates=updates,
        artifact_md=artifact_md,
        artifact_kind=artifact_kind,
        proposed_transition=transition,
        comments=comment_list[:5],
        raw=text[-4000:],
    )


# тот же allowlist, что в API checklist_put: агент не создаёт чеклисты
# произвольного вида, влияющие на чеклист-гейты (анализ 30.10.2026)
_CHECKLIST_KINDS = ("developer", "reviewer", "tester", "psi")


def _comments_list(raw_comments) -> list:
    """comments из отчёта: массив строк; СТРОКА разворачивается в один элемент —
    иначе итерация строки даёт комментарии по одной букве (дефект 31.10:
    «К», «у», «т»… в карточке задачи)."""
    if isinstance(raw_comments, str):
        return [raw_comments]
    return list(raw_comments or [])


def _report_from(raw: dict, text: str) -> RunReport:
    """Builds RunReport from parsed dict with field type guards."""
    transition = raw.get("proposed_transition")
    if not isinstance(transition, dict) or not isinstance(transition.get("to"), str):
        transition = None
    upd = [
        u
        for u in raw.get("checklist_updates", [])
        if isinstance(u, dict) and u.get("checklist_kind") in _CHECKLIST_KINDS
    ]
    rel = [
        r
        for r in raw.get("relations_updates", [])
        if isinstance(r, dict)
        and isinstance(r.get("task_code"), str)
        and r.get("kind") in ("do_after", "blocked_by")
    ]
    return RunReport(
        status=raw["status"],
        summary_md=str(raw.get("summary_md", "")),
        checklist_updates=upd,
        relations_updates=rel,
        artifact_md=raw.get("artifact_md"),
        artifact_kind=raw.get("artifact_kind"),
        proposed_transition=transition,
        questions=[q for q in raw.get("questions", []) if isinstance(q, str)],
        comments=[
            c for c in _comments_list(raw.get("comments", [])) if isinstance(c, str) and c.strip()
        ],
        raw=text[-4000:],
    )


def _tail(s: str, n: int = 600) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else f"…{s[-n:]}"


def _build_prompt(req: RunRequest) -> str:
    """Промт прогона: персона + вызов скилла + контекст задачи + контракт отчёта.

    Скилл-первый запуск (решение владельца 09.11.2026): сессия начинается
    явным вызовом /имя-скилла — методология активируется командой, а не
    подкладывается пассивным текстом (пассивный текст модель вольна
    недоиспользовать). Первый скилл из списка — вызовом, остальные —
    приложенным текстом. Персона — только имя агента."""
    parts = [f"Ты — {req.persona or 'исполнитель этапа конвейера'}."]
    if req.skills:
        parts.append(f"/{req.skills[0]}")
    parts.append(f"# Контекст задачи\n{req.context_md}")
    if req.skills:
        secondary = req.skills_md[1:]
        if secondary:
            parts.append("# Дополнительные скиллы (справочно)\n" + "\n\n".join(secondary))
    elif req.skills_md:
        parts.append("# Подключённые скиллы (реестр инструментов)\n" + "\n\n".join(req.skills_md))
    parts.append(REPORT_CONTRACT)
    return "\n\n".join(parts)


def _options_cls(sdk) -> type:
    """Класс опций: в SDK 0.2+ это ClaudeAgentOptions, в старых версиях — ClaudeCodeOptions."""
    cls = getattr(sdk, "ClaudeAgentOptions", None) or getattr(sdk, "ClaudeCodeOptions", None)
    if cls is None:
        raise RuntimeError(
            "claude-agent-sdk: не найден класс опций (ClaudeAgentOptions/ClaudeCodeOptions)"
        )
    return cls


def _options_kwargs(req: RunRequest, fields: set[str]) -> dict:
    """Опции вызова SDK — только те, что поддерживаются данной версией пакета.

    Неизвестные данной версии опции тихо отбрасываются: старый SDK не падает
    от новых полей профиля агента."""
    kwargs: dict = {
        "cwd": str(req.cwd_path or req.worktree_path or ""),
        "allowed_tools": list(req.allowed_tools),
        "permission_mode": "acceptEdits",
        "max_turns": int(getattr(req, "max_turns", 100) or 100),
    }
    if req.model:
        kwargs["model"] = req.model
    if req.mcp_servers:
        kwargs["mcp_servers"] = req.mcp_servers
    if req.agent_dir:
        # подхват .claude из worktree: скиллы, команды, субагенты, настройки
        kwargs["setting_sources"] = ["project"]
    if getattr(req, "resume_session_id", None):
        # продолжение оборванной сессии (лимит ходов/таймаут); старый SDK без
        # поля resume тихо отбросит опцию и начнёт свежую сессию
        kwargs["resume"] = req.resume_session_id
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
    """ANTHROPIC_* из расшифрованного подключения.

    anthropic — напрямую (совместимый прокси: Anthropic, z.ai, …).
    openai — через мост LiteLLM (сайдкар переводит /v1/messages в
    chat/completions): адрес моста и мастер-ключ берутся из окружения,
    ключ провайдера внутрь SDK-процесса не попадает."""
    if not provider:
        return {}
    import os

    if provider.get("protocol") == "openai":
        model = provider.get("bridge_model") or provider.get("model") or ""
        return {
            "ANTHROPIC_BASE_URL": os.getenv("LITELLM_URL", "http://litellm:4000"),
            "ANTHROPIC_AUTH_TOKEN": os.getenv("LITELLM_MASTER_KEY", "sk-harness-bridge"),
            "ANTHROPIC_MODEL": model,
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": model,
        }
    if provider.get("protocol") not in (None, "anthropic"):
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


class RunnerSoftLimit(Exception):
    """Сессия достигла мягкого лимита ходов: контекст вырос, продуктивность
    хода падает — завершаем и продолжаем в СВЕЖЕЙ сессии (handoff из лога)."""


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
                " (и CLI Claude Code: npm i -g @anthropic-ai/claude-code)"
            ) from err

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
        turns = 0
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
                # ход = сообщение ассистента с контентом; tool-результаты и
                # служебные сообщения ходами не считаются (иначе лимит втрое
                # агрессивнее задуманного — VITRINA-1, 02.11.2026)
                turns += await self._emit_message(req, message, collected, usage)
                if req.soft_turns and turns >= req.soft_turns:
                    # мягкий лимит: сессия длинная — ход дорожает (кэш = ходы x
                    # префикс), внимание размывается. Завершаем; прогресс — в
                    # чеклисте/коммитах; следующий прогон = свежая сессия + handoff
                    await req.emit(
                        "system", text=f"мягкий лимит ходов ({req.soft_turns}) — смена сессии"
                    )
                    raise RunnerSoftLimit(str(req.soft_turns)) from None
        finally:
            try:
                await gen.aclose()
            except Exception:
                pass
        return turns

    async def run(self, req: RunRequest) -> RunReport:
        prompt = _build_prompt(req)
        await req.emit("prompt", text=prompt)
        opts_cls = _options_cls(self._sdk)
        fields = {f.name for f in dataclasses.fields(opts_cls)}
        if req.agent_dir and req.worktree_path:
            mode = _link_agent_dir(req.agent_dir, req.worktree_path)
            await req.emit(
                "system", text=f"папка инструментов подключена ({mode}): {req.agent_dir} → .claude"
            )
        options = opts_cls(**_options_kwargs(req, fields))
        env = _sdk_env(req.provider)
        if env and "env" not in fields:
            # legacy-SDK без поля env у опций: окружение ставится в os.environ
            # всего процесса — сериализуем такие прогоны, иначе два параллельных
            # прогона с разными подключениями уйдут с чужим токеном (анализ 30.10)
            async with _ENV_LOCK:
                return await self._run_env(req, prompt, options, env)
        return await self._run_env(req, prompt, options, env)

    async def _run_env(self, req: RunRequest, prompt: str, options, env: dict | None) -> RunReport:
        """Сам прогон: окружение провайдера в os.environ только на время
        прогона (legacy-путь — под _ENV_LOCK), таймауты, сбор текста отчёта."""
        import os

        saved_env = None
        if env:
            saved_env = {k: os.environ.get(k) for k in env}
            os.environ.update(env)
        collected: list[str] = []
        usage: dict = {"input": 0, "output": 0, "cache": 0, "total": 0}
        turns = 0
        try:
            turns = await self._iterate_sdk(req, prompt, options, collected, usage)
        except RunnerTimeout as err:
            await req.emit("system", text=f"timeout: {err.args[0]}")
            phase = "старт" if err.args and err.args[0] == "start" else "работа"
            return RunReport(
                status="failed",
                summary_md=f"Таймаут прогона ({phase}) — процесс агента остановлен демоном",
                outcome_code="timeout_start" if phase == "старт" else "timeout_work",
            )
        except RunnerSoftLimit as err:
            # не failed-дефект: плановая смена сессии до деградации длинного
            # контекста; прогресс в чеклисте/коммитах, handoff уйдёт в контекст
            await req.emit("system", text="смена сессии (мягкий лимит ходов)")
            return RunReport(
                status="failed",
                summary_md=f"Мягкий лимит ходов ({err}) — плановая смена сессии: "
                f"прогресс в чеклисте и коммитах, следующий прогон "
                f"продолжит с открытых пунктов",
                outcome_code="soft_turns",
            )
        finally:
            if saved_env is not None:
                import os

                for k, v in saved_env.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
        report = parse_report("\n".join(collected))
        if report.status == "failed" and turns >= req.max_turns:
            # исчерпание жёсткого лимита ходов: код для resume-логики демона
            # (раньше распознавалось подстрокой "Reached maximum number of turns")
            report.outcome_code = "turns_limit"
        await req.emit(
            "report",
            text=report.summary_md,
            data={"status": report.status, "proposed_transition": report.proposed_transition},
        )
        return report

    async def _emit_message(
        self, req: RunRequest, message, collected: list[str], usage: dict
    ) -> bool:
        """Обработка сообщения SDK; True = это был ХОД ассистента (для мягкого
        лимита — tool-результаты и служебные сообщения ходами не считаются:
        раньше лимит втрое агрессивнее задуманного — VITRINA-1, 02.11)."""
        subtype = getattr(message, "subtype", None)
        if subtype == "init":
            # SDK >= 0.2.x: данные init лежат в message.data (словарь), а не в
            # атрибутах — раньше session_id всегда читался как None, resume
            # молча не включался, и каждый ретрай стартовал с чистого листа
            init = getattr(message, "data", None) or {}
            await req.emit(
                "system",
                text="сессия агента запущена",
                data={
                    "model": init.get("model", getattr(message, "model", None)),
                    "cwd": init.get("cwd", getattr(message, "cwd", None)),
                    "tools": init.get("tools", getattr(message, "tools", None)),
                    "session_id": init.get("session_id", getattr(message, "session_id", None)),
                },
            )
            return False
        _accumulate_usage(message, usage)
        if usage.get("total"):
            await req.emit("usage", data=dict(usage))
        content = getattr(message, "content", None)
        if content is None and getattr(message, "result", None) is not None:
            # ResultMessage: итоговый текст (не ход)
            collected.append(str(message.result))
            return False
        assistant_turn = bool(content)
        for block in content or []:
            btype = type(block).__name__
            text = getattr(block, "text", None)
            thinking = getattr(block, "thinking", None)
            name = getattr(block, "name", None)
            if name and hasattr(block, "input"):  # ToolUseBlock
                await req.emit(
                    "tool", text=name, data={"input": _short_input(getattr(block, "input", None))}
                )
            elif (
                btype == "ToolResultBlock"
                or hasattr(block, "content")
                and text is None
                and name is None
            ):
                await req.emit("tool_result", text=_tail(str(getattr(block, "content", ""))))
            elif thinking:
                await req.emit("thinking", text=thinking)
            elif text:
                collected.append(text)
                await req.emit("thinking", text=text)
        return assistant_turn


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
    raw_cache = _uget(u, "cache_read_input_tokens") + _uget(u, "cache_creation_input_tokens")
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
