"""Eve-агент: настоящий агент на Claude Agent SDK (решение владельца 28.10.2026).

Вместо прекомпьют-контекста — модель с инструментами в цикле:
  чтение: трекер (in-process tools), репозитории компьютера (cwd на host-home),
          docker (полный доступ, сокет смонтирован), интернет (WebFetch/curl);
  запись: изменяющие действия трекера — только propose_action → намерение →
          «да» пользователя (аудит в chat_message неотключаем); правки файлов —
          только после явного подтверждения в чате (permission_mode).

Фолбэк: SDK/CLI/провайдер недоступны → agent_reply вернёт None, вызывающий
код отвечает прежним режимом (контекст-инъекция из eve.free_chat_reply).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import shlex
import shutil
import subprocess

import sqlalchemy as sa

log = logging.getLogger("eve_agent")

_CODE_RE = r"\b[A-Za-zА-Яа-я]{2,10}-\d+\b"
_TOOL_OUTPUT_CAP = 6000
_DOCKER_TIMEOUT = 30
AGENT_TURNS = 40

EDIT_CONFIRM_RE = r"примени\b|применить правки|подтверждаю правки|да, примени"


def sdk_available() -> bool:
    """SDK + Claude Code CLI на месте?"""
    try:
        import claude_agent_sdk  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return shutil.which("node") is not None or shutil.which("claude") is not None


def _cap(text: str, n: int = _TOOL_OUTPUT_CAP) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[:n] + f"\n…(обрезано, всего {len(text)} симв.)"


async def _one(sql: str, params: dict | None = None):
    from database import get_sessionmaker

    async with get_sessionmaker()() as s:
        return (await s.execute(sa.text(sql), params or {})).mappings().first()


async def _all(sql: str, params: dict | None = None):
    from database import get_sessionmaker

    async with get_sessionmaker()() as s:
        return (await s.execute(sa.text(sql), params or {})).mappings().all()


def _build_tools(register_intent):
    """In-process MCP-инструменты «harness»: чтение трекера и управление."""
    from claude_agent_sdk import tool

    @tool("task_card", "Полная карточка задачи по коду (описание, хроника, чек-листы, прогоны)",
          {"code": str})
    async def task_card(args, ctx=None):
        code = str(args.get("code", "")).upper()
        row = await _one(
            "SELECT t.id, t.code, t.title, t.status_key AS st, t.priority, t.description_md AS d "
            "FROM task t WHERE t.code = :c", {"c": code})
        if not row:
            return {"content": [{"type": "text", "text": f"Задача {code} не найдена"}]}
        chron = await _all(
            "SELECT event_type, author_kind, message FROM chronicle WHERE task_id = :i "
            "ORDER BY created_at DESC LIMIT 15", {"i": str(row["id"])})
        runs = await _all(
            "SELECT u.name AS agent, r.outcome, r.input_tokens + r.output_tokens + r.cache_tokens AS tok "
            "FROM task_run r JOIN \"user\" u ON u.id = r.agent_id "
            "WHERE r.task_id = :i ORDER BY r.started_at DESC LIMIT 5", {"i": str(row["id"])})
        cl = await _all(
            "SELECT c.kind, count(*) FILTER (WHERE i.status IN ('done','closed')) AS done_n, "
            "count(*) FILTER (WHERE i.kind = 'item') AS total FROM checklist c "
            "LEFT JOIN checklist_item i ON i.checklist_id = c.id "
            "WHERE c.task_id = :i GROUP BY c.kind", {"i": str(row["id"])})
        out = {
            "code": row["code"], "status": row["st"], "title": row["title"],
            "priority": row["priority"],
            "card_md": (row["d"] or "")[:8000],
            "chronicle": [f"[{c['event_type']}/{c['author_kind']}] {c['message'][:250]}" for c in chron],
            "checklists": {c["kind"]: f"{c['done_n']}/{c['total']}" for c in cl},
            "runs": [f"{r['agent']} ({r['outcome']}, {r['tok'] or 0} ток.)" for r in runs],
        }
        return {"content": [{"type": "text", "text": _cap(json.dumps(out, ensure_ascii=False, indent=1))}]}

    @tool("tasks_search", "Поиск задач: проект, статус, подстрока в названии/коде",
          {"project": str, "status": str, "q": str, "limit": int})
    async def tasks_search(args, ctx=None):
        cond, par = [], {"lim": int(args.get("limit") or 25)}
        if args.get("project"):
            cond.append("p.mnemonic = :pr")
            par["pr"] = str(args["project"]).upper()
        if args.get("status"):
            cond.append("t.status_key = :st")
            par["st"] = str(args["status"])
        if args.get("q"):
            cond.append("(t.title ILIKE :qq OR t.code ILIKE :qc)")
            par["qq"] = f"%{args['q']}%"
            par["qc"] = f"%{args['q']}%"
        where = ("WHERE " + " AND ".join(cond)) if cond else ""
        rows = await _all(
            f"SELECT t.code, tt.key AS tp, t.status_key AS st, t.title "
            f"FROM task t JOIN project p ON p.id = t.project_id "
            f"JOIN task_type tt ON tt.id = t.task_type_id {where} "
            f"ORDER BY t.updated_at DESC LIMIT :lim", par)
        return {"content": [{"type": "text", "text": _cap("\n".join(
            f"{r['code']} [{r['tp']}/{r['st']}] {r['title']}" for r in rows) or "ничего не найдено")}]}

    @tool("story_tree", "История и её задачи: статусы, токены, итог",
          {"code": str})
    async def story_tree(args, ctx=None):
        code = str(args.get("code", "")).upper()
        story = await _one(
            "SELECT t.id, t.code, t.title, t.status_key AS st FROM task t WHERE t.code = :c",
            {"c": code})
        if not story:
            return {"content": [{"type": "text", "text": f"Задача {code} не найдена"}]}
        kids = await _all(
            "SELECT t.code, tt.key AS tp, t.status_key AS st, t.title, "
            "(SELECT coalesce(sum(r.input_tokens + r.output_tokens + r.cache_tokens),0) "
            " FROM task_run r WHERE r.task_id = t.id) AS tok "
            "FROM task t JOIN task_type tt ON tt.id = t.task_type_id "
            "WHERE t.story_id = :i ORDER BY t.code", {"i": str(story["id"])})
        # tok — NUMERIC из sum() → Decimal, json.dumps его не переваривает
        tasks = [{"code": k["code"], "type": k["tp"], "status": k["st"],
                  "title": k["title"], "tokens": int(k["tok"] or 0)} for k in kids]
        out = {"story": f"{story['code']} [{story['st']}] {story['title']}",
               "tasks": tasks,
               "total_tokens": sum(t["tokens"] for t in tasks)}
        return {"content": [{"type": "text", "text": _cap(json.dumps(out, ensure_ascii=False, indent=1))}]}

    @tool("projects_status", "Проекты: открытые задачи, пауза конвейера, активные прогоны", {})
    async def projects_status(args, ctx=None):
        paused = await _one("SELECT value FROM app_setting WHERE key = 'daemon.paused'")
        runs = await _all(
            "SELECT t.code, u.name AS agent FROM task_run r "
            "JOIN task t ON t.id = r.task_id JOIN \"user\" u ON u.id = r.agent_id "
            "WHERE r.finished_at IS NULL")
        projs = await _all(
            "SELECT p.mnemonic, count(t.id) FILTER (WHERE fs.is_terminal IS NOT TRUE) AS open_n "
            "FROM project p LEFT JOIN task t ON t.project_id = p.id "
            "LEFT JOIN flow_status fs ON fs.flow_version_id = t.flow_version_id "
            "AND fs.status_key = t.status_key GROUP BY p.mnemonic ORDER BY p.mnemonic")
        return {"content": [{"type": "text", "text": _cap(json.dumps({
            "pipeline_paused": (paused or {}).get("value") == "true",
            "active_runs": [f"{r['code']} ({r['agent']})" for r in runs],
            "projects": {r["mnemonic"]: r["open_n"] for r in projs},
        }, ensure_ascii=False, indent=1))}]}

    @tool("propose_action", "Изменяющее действие над трекером: записать намерение. "
          "Пользователь подтвердит словом «да» — сообщите ему об этом. "
          "kind: transition|force|create_task|interrupt|pipeline_pause. "
          "Для create_task: type — один из story/common_task/qa_task/bug/analyse_task "
          "(«задача» = common_task), project — мнемоника проекта (VITRINA, AH…). "
          "Для transition/force: to — ключ статуса из status-flow типа задачи "
          "(например new_status_9 = «Завершено», done = «Готово»).",
          {"kind": str, "task": str, "to": str, "reason": str,
           "title": str, "project": str, "type": str, "paused": bool})
    async def propose_action(args, ctx=None):
        kind = str(args.get("kind", ""))
        supported = {"transition", "force", "create_task", "interrupt", "pipeline_pause"}
        if kind not in supported:
            return {"content": [{"type": "text", "text": f"Неизвестный вид действия: {kind}"}]}
        intent: dict = {"kind": kind}
        for key in ("task", "to", "reason", "title", "project", "type"):
            if args.get(key):
                intent[key] = str(args[key])
        if kind == "create_task":
            # нормализация типов: «задача»/task → common_task; неизвестное — тоже
            alias = {"task": "common_task", "задача": "common_task",
                     "story": "story", "common_task": "common_task",
                     "qa_task": "qa_task", "bug": "bug", "analyse_task": "analyse_task"}
            t = (intent.get("type") or "common_task").lower()
            intent["type"] = alias.get(t, "common_task")
        if kind == "pipeline_pause":
            intent["paused"] = bool(args.get("paused", True))
        if kind in ("transition", "force") and (not intent.get("task") or not intent.get("to")):
            return {"content": [{"type": "text", "text": "Нужны task и to (код задачи и статус)"}]}
        if kind == "interrupt" and not intent.get("task"):
            return {"content": [{"type": "text", "text": "Нужен task (код задачи)"}]}
        if kind == "create_task" and (not intent.get("title") or not intent.get("project")):
            return {"content": [{"type": "text",
                    "text": "Нужны title и project (мнемоника проекта)"}]}
        register_intent(intent)
        return {"content": [{"type": "text", "text":
                "Намерение записано. Скажите пользователю, что подтвердить нужно словом «да»: "
                + json.dumps(intent, ensure_ascii=False)}]}

    @tool("docker", "Полный доступ к docker CLI (ps, logs, inspect, exec …). args — аргументы команды",
          {"args": str})
    async def docker_tool(args, ctx=None):
        cmd = ["docker"] + shlex.split(str(args.get("args", "")))
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=_DOCKER_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            return {"content": [{"type": "text", "text": "docker: таймаут 30 с"}]}
        return {"content": [{"type": "text", "text": _cap(out.decode("utf-8", "replace"))}]}

    from claude_agent_sdk import create_sdk_mcp_server

    server = create_sdk_mcp_server("harness", tools=[
        task_card, tasks_search, story_tree, projects_status, propose_action, docker_tool])
    names = ["task_card", "tasks_search", "story_tree", "projects_status",
             "propose_action", "docker"]
    return server, [f"mcp__harness__{n}" for n in names]


async def _env_and_model(session, conn_row) -> tuple[dict, str] | None:
    """ANTHROPIC_* env для SDK; None — провайдер не anthropic-протокола."""
    from repository.models import Connection
    from usecase.settings.connections import get_decrypted_token

    if conn_row["protocol"] != "anthropic":
        return None
    conn = await session.get(Connection, conn_row["id"])
    if conn is None:
        return None
    token = await get_decrypted_token(session, conn)
    url = (conn.url or "").rstrip("/")
    if url.endswith("/v1/messages"):
        url = url[: -len("/v1/messages")]
    return ({"ANTHROPIC_BASE_URL": url, "ANTHROPIC_AUTH_TOKEN": token},
            conn.model or "")


SYSTEM_PROMPT = """Ты — Eve, встроенный ИИ-агент AI-Harness: task-tracker с конвейером
автономных агентов. Ты — личный помощник владельца (его «Джарвис»). Отвечай по-русски,
кратко и по делу, с конкретикой: коды задач, пути файлов, числа.

У тебя полный доступ:
- инструменты mcp__harness__* — трекер (карточки, поиск, истории, статусы проектов,
  изменяющие действия через propose_action);
- файловая система и репозитории компьютера — cwd это домашняя папка пользователя;
  ищи код через Grep/Glob/Read, историю изменений через Bash (git log/git diff);
- docker — полный доступ инструментом mcp__harness__docker (ps/logs/inspect/exec …);
- интернет — WebFetch/Bash curl.

Правила:
1. Изменяющие действия над трекером (перевод статуса, создание задачи, прерывание
   агента, пауза конвейера, форс) — ТОЛЬКО инструментом mcp__harness__propose_action;
   оно записывает намерение, пользователь подтвердит словом «да». Не пытайся менять
   статусы напрямую в базе.
2. Правки файлов (Edit/Write) — только если пользователь явно подтвердил применение
   в последнем сообщении. Иначе опиши предлагаемое изменение (файл, старое → новое)
   и попроси подтверждения фразой «примени правки».
3. Не выдумывай: чего нет в инструментах или выводе команд — так и скажи.
4. Работаешь в docker-контейнере: домашняя папка пользователя смонтирована в
   /app/host-home; сам трекер поднят рядом (контейнеры ai-harness-*).
"""


async def agent_reply(session, user, text: str, register_intent,
                      screen_task_code: str | None = None,
                      edits_confirmed: bool = False) -> dict | None:
    """Запускает Eve-агента. None → вызывающий код отвечает прежним режимом."""
    if not sdk_available():
        log.warning('eve_agent откат: %s', 'sdk_available=False')
        return None
    try:
        from claude_agent_sdk import ClaudeAgentOptions, query
    except Exception:  # noqa: BLE001
        return None

    conn = (await session.execute(sa.text(
        "SELECT id, protocol, url, model, name FROM connection "
        "WHERE is_active LIMIT 1"))).mappings().first()
    if conn is None:
        log.warning('eve_agent откат: %s', 'нет активного провайдера')
        return None
    env_model = await _env_and_model(session, conn)
    if env_model is None:
        log.warning('eve_agent откат: %s', 'протокол не anthropic')
        return None  # не anthropic-протокол — SDK не примет; отвечает прежний режим
    env, model = env_model

    server, harness_tools = _build_tools(register_intent)
    home = os.environ.get("HARNESS_CONTAINER_HOME") or os.path.expanduser("~")
    allowed = ["Read", "Grep", "Glob", "Bash", "WebFetch"] + harness_tools
    if edits_confirmed:
        allowed += ["Edit", "Write"]
    note = ("\n\nПользователь подтвердил применение правок из предыдущего ответа — "
            "примени их точно, только обозначенные изменения." if edits_confirmed else "")

    options = ClaudeAgentOptions(
        cwd=home,
        allowed_tools=allowed,
        disallowed_tools=[] if edits_confirmed else ["Edit", "Write", "NotebookEdit"],
        permission_mode="acceptEdits" if edits_confirmed else "default",
        max_turns=AGENT_TURNS,
        mcp_servers={"harness": server},
        setting_sources=[],
        system_prompt=SYSTEM_PROMPT + note,
        model=model or None,
        env=env,
    )

    answer_parts: list[str] = []
    result_text: str | None = None
    tools_used = 0
    stderr_lines: list[str] = []
    options.stderr = lambda line: (stderr_lines.append(line), None)[1] if len(stderr_lines) < 200 else None
    try:
        async for message in query(prompt=text, options=options):
            kind = type(message).__name__
            if kind == "AssistantMessage":
                for block in getattr(message, "content", []) or []:
                    if getattr(block, "type", "") == "text":
                        answer_parts.append(block.text)
                    elif getattr(block, "type", "") == "tool_use":
                        tools_used += 1
            elif kind == "ResultMessage":
                # GLM через z.ai может отдавать AssistantMessage с пустым
                # контентом — итоговый текст живёт в ResultMessage.result
                result_text = (getattr(message, "result", None) or "").strip() or result_text
                if getattr(message, "is_error", False) and not answer_parts and not result_text:
                    return {"reply": f"Агент завершился с ошибкой: "
                                     f"{getattr(message, 'result', '') or 'без деталей'}"}
    except Exception as err:  # noqa: BLE001 — двухслойный ответ наружу
        log.warning("eve_agent упал: %s", err, exc_info=True)
        if not answer_parts and not result_text:
            return None  # тихий откат в прежний режим
        answer_parts.append(f"\n\n(обрыв агента: {err})")

    answer = ("".join(answer_parts).strip() or (result_text or "").strip())
    if not answer:
        log.warning("eve_agent откат: пустой ответ (tools_used=%s, stderr=%s)",
                    tools_used, stderr_lines[-3:])
        return None
    return {"reply": answer, "agent": True}
