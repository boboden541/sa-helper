"""Eve: чат-помощник с правами человека (СТ §4.5.3, ФТ-ah-50…53).

Изменяющие действия — намерение → «да»; аудит каждого действия в хроники
неотключаем; свободный режим — настройка eve.free_mode.
"""

from __future__ import annotations

import datetime as dt
import re

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from domain.model.validators import DomainError
from repository.models import AppSetting, ChatMessage, Task, User
from usecase.task.transition import TransitionDenied, apply_force, apply_transition

from usecase.assistant import eve_agent  # noqa: F401 — фолбэк-проверки внизу

_CODE_RE = re.compile(r"\b[A-Za-zА-Яа-я]{2,10}-\d+\b")
_INTENT_TTL = dt.timedelta(minutes=10)
# процессы без общего состояния — намерения живут в памяти backend (TTL 10 мин);
# оба сообщения (намерение и «да») пишутся в chat_message для аудита
_INTENTS: dict[str, tuple[dict, dt.datetime]] = {}

MOVE_VERBS = re.compile(r"переведи|перевести|верни|возьми", re.IGNORECASE)
WHY_VERBS = re.compile(r"почему|не двигается|встала|застряла", re.IGNORECASE)
REPORT_VERBS = re.compile(r"что с |расскажи о задаче|статус задачи", re.IGNORECASE)


async def free_mode(session: AsyncSession) -> bool:
    value = (await session.execute(
        sa.select(AppSetting.value).where(AppSetting.key == "eve.free_mode")
    )).scalar_one_or_none()
    return (value or "false").lower() == "true"


async def _find_task(session: AsyncSession, text: str) -> Task | None:
    match = _CODE_RE.search(text or "")
    if not match:
        return None
    return (await session.execute(
        sa.select(Task).where(Task.code == match.group(0).upper()))).scalar_one_or_none()


async def handle_message(session: AsyncSession, user: User, text: str,
                         screen_task_code: str | None = None) -> dict:
    """Обрабатывает фразу; возвращает ответ Eve. Аудит — chat_message всегда."""
    session.add(ChatMessage(user_id=user.id, role="user", body=text,
                            task_code=screen_task_code))

    task = await _find_task(session, text) or (
        await _find_task(session, screen_task_code) if screen_task_code else None)

    # намерение на подтверждении?
    intent = _pop_intent(user.id, text)
    if intent is not None:
        return await _confirm_intent(session, user, intent)

    if MOVE_VERBS.search(text) and task is not None:
        target = _guess_target(text, await _flow_statuses(session, task))
        if target is None:
            reply = {"reply": "Куда перевести? Назовите статус: например, «на ревью».",
                     "task": task.code}
        else:
            reply = await _plan_transition(session, user, task, target)
    elif WHY_VERBS.search(text) and task is not None:
        reply = await _explain_blocked(session, task)
    elif REPORT_VERBS.search(text) and task is not None:
        reply = await _task_digest(session, task)
    else:
        # свободный вопрос — Eve-агенту (SDK: трекер+репо+docker+интернет);
        # недоступен — прежний режим (контекст-инъекция) (решение 28.10.2026)
        edits_confirmed = bool(re.search(eve_agent.EDIT_CONFIRM_RE, text, re.IGNORECASE)) \
            if hasattr(eve_agent, "EDIT_CONFIRM_RE") else False

        def _register(intent: dict) -> None:
            _INTENTS[str(user.id)] = (
                intent, dt.datetime.now(dt.timezone.utc) + _INTENT_TTL)

        try:
            result = await eve_agent.agent_reply(
                session, user, text, _register,
                screen_task_code=task.code if task else None,
                edits_confirmed=edits_confirmed)
        except Exception:  # noqa: BLE001 — агент не поднялся, отвечает прежний режим
            from usecase.assistant.eve_agent import sdk_available

            result = None
        if result is not None:
            session.add(ChatMessage(user_id=user.id, role="assistant",
                                    body=str(result.get("reply") or ""),
                                    task_code=task.code if task else None))
            await session.commit()
            return result
        # свободный вопрос — в LLM активного провайдера (Eve — «Джарвис» владельца)
        return await free_chat_reply(session, user, text, task)
    session.add(ChatMessage(user_id=user.id, role="assistant",
                            body=str(reply.get("reply") or reply.get("action", "")),
                            task_code=task.code if task else None))
    await session.commit()
    return reply


async def free_chat_reply(session: AsyncSession, user: User, text: str,
                          task: Task | None = None) -> dict:
    """Свободное общение: вопрос уходит в LLM активного провайдера с контекстом
    системы (проекты, задачи, очередь, предупреждения конвейера, экран)."""
    from infrastructure.ai.chat import chat_call
    from repository.models import Connection
    from usecase.settings.connections import get_decrypted_token

    conn = (await session.execute(
        sa.select(Connection).where(Connection.is_active.is_(True))
    )).scalar_one_or_none()
    if conn is None:
        return {"reply": "ИИ-провайдер не подключён: настройте и проверьте "
                         "подключение в Настройках → ИИ-провайдеры, после этого я смогу "
                         "отвечать на любые вопросы."}

    context = await _system_context(session)
    deep = await _deep_details(session, text, task)
    screen = f"Открыт экран задачи {task.code} «{task.title}» (статус {task.status_key})." if task \
        else "Открыт канбан-доска или общий экран."
    system = (
        "Ты — Eve, встроенный ИИ-ассистент сервиса AI-Harness: task-tracker с конвейером "
        "автономной реализации фичей силами ИИ-агентов. Ты — личный помощник владельца "
        "(его «Джарвис»). Отвечай по-русски, кратко и по делу.\n\n"
        "Как работает сервис: задачи 5 типов (story/common_task/qa_task/bug/analyse_task) "
        "движутся по статусным моделям (flow); демон на каждом тике запускает ИИ-агентов на "
        "статусах с назначениями из матрицы; агенты работают в git-worktree; проверки качества — "
        "чеклисты-гейты, ревью, тестирование, ПСИ; компоненты: backend (FastAPI), frontend (React), "
        "PostgreSQL, демон; всё поднято в docker compose.\n\n"
        "У тебя ПОЛНЫЙ доступ на чтение к трекеру: ниже — индекс всех задач с названиями, "
        "статусами и расходом токенов; по упомянутым в вопросе кодам — полное содержимое "
        "карточек, хроники, чек-листы, прогоны и комментарии; по названному проекту — дайджест "
        "всех его задач. Опирайся на эти данные и отвечай конкретно: коды, статусы, цифры. "
        "Если данных нет в контексте — так и скажи, не выдумывай.\n\n"
        f"Текущее состояние системы:\n{context}\n\n{screen}\n\n{deep}\n\n"
        "Важно: изменяющие действия (переводы статусов, создание) выполняются только через "
        "специальные команды — если тебя просят действие, скажи точную фразу-команду, например "
        "«переведи <код> на ревью». На вопросы о контейнерах docker отвечай по описанию стека "
        "и состоянию конвейера — прямого доступа к docker у тебя нет.")
    history = (await session.execute(
        sa.select(ChatMessage).where(ChatMessage.user_id == user.id)
        .order_by(ChatMessage.created_at.desc()).limit(10))).scalars().all()
    messages = [{"role": "assistant" if m.role == "assistant" else "user", "content": m.body}
                for m in reversed(history)]
    messages.append({"role": "user", "content": text})
    try:
        answer = await chat_call(
            conn.protocol, conn.url, conn.model,
            await get_decrypted_token(session, conn), system, messages)
    except Exception as err:  # noqa: BLE001 — двухслойный ответ
        return {"reply": f"Провайдер недоступен или отклонил запрос. Проверьте подключение "
                         f"«{conn.name}» в настройках. Технически: {err}"}
    return {"reply": answer or "Провайдер вернул пустой ответ."}


async def _system_context(session: AsyncSession) -> str:
    from repository.models import Project

    lines: list[str] = []
    warnings = (await session.execute(sa.text(
        "SELECT count(*) FROM connection WHERE is_active"))).scalar_one()
    lines.append(f"Активных ИИ-подключений: {warnings}.")
    for mnemonic, name, arch in (await session.execute(
            sa.select(Project.mnemonic, Project.name, Project.is_archived))).all():
        lines.append(f"Проект {mnemonic} «{name}»{' (архив)' if arch else ''}")
    counts = (await session.execute(sa.text(
        "SELECT tt.key, t.status_key, count(*) FROM task t "
        "JOIN task_type tt ON tt.id = t.task_type_id GROUP BY 1,2 ORDER BY 1,2"))).all()
    lines.append("Задачи: " + ("; ".join(f"{k}/{s}: {n}" for k, s, n in counts) or "нет задач"))
    blocked = (await session.execute(sa.text(
        "SELECT code, coalesce(blocked_reason,'') FROM task WHERE status_key='blocked' "
        "LIMIT 5"))).all()
    if blocked:
        lines.append("Заблокированы: " + "; ".join(f"{c} ({r})" for c, r in blocked))
    return "\n".join(lines)


_CTX_BUDGET = 70000  # символов на весь добор контекста


async def _deep_details(session: AsyncSession, text: str,
                        screen_task: Task | None) -> str:
    """Добор контекста для свободного вопроса: индекс всех задач, полная
    раскопка упомянутых кодов (карточка, хроники, чек-листы, прогоны,
    комментарии) и дайджест названного проекта. Решение владельца 27.10.2026:
    Eve — полноценно читающий ассистент, а не голая статистика."""
    codes: list[str] = []
    for m in _CODE_RE.findall(text or ""):
        c = m.upper()
        if c not in codes:
            codes.append(c)
    if screen_task is not None and screen_task.code not in codes:
        codes.insert(0, screen_task.code)

    projects = (await session.execute(sa.text(
        "SELECT mnemonic FROM project ORDER BY mnemonic"))).scalars().all()
    text_wo_codes = _CODE_RE.sub(" ", text or "")
    mentioned_projects = [m for m in projects
                          if len(m) >= 3 and re.search(rf"\b{m}\b(?!-)", text_wo_codes.upper())]

    parts: list[str] = []
    budget = _CTX_BUDGET

    # индекс всех задач по проектам
    index_lines: list[str] = []
    rows = (await session.execute(sa.text(
        "SELECT p.mnemonic AS pr, tt.key AS tp, t.code, t.status_key AS st, "
        "t.priority AS pr2, t.title, coalesce(t.blocked_reason,'') AS br, "
        "(SELECT coalesce(sum(r.input_tokens + r.output_tokens + r.cache_tokens),0) "
        " FROM task_run r WHERE r.task_id = t.id) AS tok "
        "FROM task t JOIN project p ON p.id = t.project_id "
        "JOIN task_type tt ON tt.id = t.task_type_id "
        "ORDER BY p.mnemonic, t.status_key, t.code"))).all()
    cur = None
    for pr, tp, code, st, prio, title, br, tok in rows:
        if pr != cur:
            cur = pr
            index_lines.append(f"Проект {pr}:")
        line = (f"  {code} [{tp}/{st}] {title[:70]}"
                + (f" · {tok} токенов" if tok else "")
                + (f" · ЗАБЛОКИРОВАНА: {br[:80]}" if br else ""))
        index_lines.append(line)
    parts.append("ИНДЕКС ЗАДАЧ:\n" + "\n".join(index_lines))
    budget -= sum(len(x) for x in index_lines)

    # дайджест названного проекта: по каждой задаче с кусочком описания
    for mn in mentioned_projects[:2]:
        digest: list[str] = [f"ПРОЕКТ {mn} — все задачи с описаниями:"]
        for t in (await session.execute(sa.text(
                "SELECT t.code, tt.key AS tp, t.status_key AS st, t.title, "
                "t.description_md FROM task t "
                "JOIN task_type tt ON tt.id = t.task_type_id "
                "JOIN project p ON p.id = t.project_id "
                "WHERE p.mnemonic = :m ORDER BY t.code"), {"m": mn})).all():
            desc = (t.description_md or "").strip()
            head = desc[:600] + ("…" if len(desc) > 600 else "")
            digest.append(f"\n{t.code} [{t.tp}/{t.st}] {t.title}\n{head}")
        chunk = "\n".join(digest)
        if len(chunk) > budget:
            chunk = chunk[:budget] + "\n…(дайджест обрезан по лимиту контекста)"
        parts.append(chunk)
        budget -= len(chunk)
        if budget <= 0:
            break

    # полная раскопка упомянутых кодов
    for code in codes[:6]:
        t = (await session.execute(
            sa.select(Task).where(Task.code == code))).scalar_one_or_none()
        if t is None:
            continue
        block: list[str] = [f"ЗАДАЧА {t.code} [{t.status_key}] «{t.title}» "
                            f"(приоритет {t.priority})"]
        desc = (t.description_md or "").strip()
        block.append("Карточка:\n" + desc[:4000] + ("…" if len(desc) > 4000 else ""))
        chron = (await session.execute(sa.text(
            "SELECT event_type, author_kind, message FROM chronicle "
            "WHERE task_id = :i ORDER BY created_at DESC LIMIT 12"),
            {"i": str(t.id)})).all()
        if chron:
            block.append("Хроника (свежие сверху):\n" + "\n".join(
                f"- [{c[0]}/{c[1]}] {c[2][:200]}" for c in chron))
        cl = (await session.execute(sa.text(
            "SELECT c.kind, count(*) FILTER (WHERE i.status IN ('done','closed')) AS done_n, "
            "count(*) FILTER (WHERE i.kind='item') AS total FROM checklist c "
            "LEFT JOIN checklist_item i ON i.checklist_id = c.id "
            "WHERE c.task_id = :i GROUP BY c.kind"), {"i": str(t.id)})).all()
        if cl:
            block.append("Чек-листы: " + "; ".join(
                f"{c[0]} {c[1]}/{c[2]}" for c in cl))
        runs = (await session.execute(sa.text(
            "SELECT u.name, r.outcome, r.input_tokens + r.output_tokens + r.cache_tokens "
            "FROM task_run r JOIN \"user\" u ON u.id = r.agent_id "
            "WHERE r.task_id = :i ORDER BY r.started_at DESC LIMIT 5"),
            {"i": str(t.id)})).all()
        if runs:
            block.append("Прогоны: " + "; ".join(
                f"{a} ({o}, {tok or 0} ток.)" for a, o, tok in runs))
        com = (await session.execute(sa.text(
            "SELECT u.name, c.body FROM task_comment c JOIN \"user\" u ON u.id = c.author_id "
            "WHERE c.task_id = :i ORDER BY c.created_at DESC LIMIT 3"),
            {"i": str(t.id)})).all()
        if com:
            block.append("Комментарии (свежие):\n" + "\n".join(
                f"- {a}: {b[:200]}" for a, b in com))
        chunk = "\n".join(block)
        if len(chunk) > budget:
            chunk = chunk[:max(budget, 2000)] + "\n…(обрезано по лимиту контекста)"
        parts.append(chunk)
        budget -= len(chunk)
        if budget <= 0:
            break

    return "\n\n".join(parts)


async def _flow_statuses(session, task) -> list[tuple[str, str]]:
    """[(ключ, метка)] статусов flow-версии задачи — для резолвинга цели по метке."""
    import sqlalchemy as sa

    from repository.models import FlowStatus, FlowVersion

    return [(k, l) for k, l in (await session.execute(
        sa.select(FlowStatus.status_key, FlowStatus.label)
        .join(FlowVersion, FlowVersion.id == FlowStatus.flow_version_id)
        .where(FlowVersion.task_type_id == task.task_type_id,
               FlowVersion.is_current.is_(True), FlowVersion.is_published.is_(True))
    )).all()]


def _guess_target(text: str, statuses: list[tuple[str, str]] | None = None) -> str | None:
    """Цель перехода: сначала самое длинное совпадение по МЕТКЕ статуса
    («готово к ревью» → review_ready, а не in_review), затем словник,
    но только среди статусов, существующих в flow задачи."""
    t = text.lower()
    best: tuple[str, str] | None = None
    for key, label in (statuses or []):
        lbl = (label or "").lower().strip()
        if lbl and lbl in t and (best is None or len(lbl) > len(best[1])):
            best = (key, lbl)
    if best is not None:
        return best[0]
    mapping = {"ревью": "in_review", "тест": "in_testing", "работ": "in_progress",
               "бэклог": "backlog", "готов": "done", "отмен": "canceled",
               "блок": "blocked", "декомпозиц": "todo", "к работе": "todo"}
    for needle, status in mapping.items():
        if needle in t and (statuses is None or any(k == status for k, _ in statuses)):
            return status
    return None


async def _plan_transition(session: AsyncSession, user: User, task: Task,
                           target: str) -> dict:
    if await free_mode(session):
        try:
            await apply_transition(session, user, task.code, target)
            return {"reply": f"Готово: {task.code} → «{target}» (свободный режим).",
                    "task": task.code}
        except TransitionDenied as d:
            return {"reply": f"Не вышло: {d.reason}", "task": task.code}
    _INTENTS[str(user.id)] = (
        {"kind": "transition", "task": task.code, "to": target,
         "expires": (dt.datetime.now(dt.timezone.utc) + _INTENT_TTL).isoformat()},
        dt.datetime.now(dt.timezone.utc) + _INTENT_TTL)
    return {"action": "confirm", "intent": {"kind": "transition", "task": task.code,
                                            "to": target},
            "reply": f"Переведу {task.code} в «{target}». Подтвердите: «да»."}


def _pop_intent(user_id, text: str) -> dict | None:
    if not re.fullmatch(r"\s*(да|подтверждаю|yes)\s*", text, re.IGNORECASE):
        return None
    item = _INTENTS.get(str(user_id))
    if not item:
        return None
    intent, expires = item
    if expires < dt.datetime.now(dt.timezone.utc):
        _INTENTS.pop(str(user_id), None)
        return None
    _INTENTS.pop(str(user_id), None)
    return intent


async def _confirm_intent(session: AsyncSession, user: User, intent: dict) -> dict:
    if intent["kind"] == "transition":
        try:
            await apply_transition(session, user, intent["task"], intent["to"])
        except TransitionDenied as d:
            reply = {"reply": f"Не получилось: {d.reason}", "task": intent["task"]}
            session.add(ChatMessage(user_id=user.id, role="assistant",
                                    body=reply["reply"], task_code=intent["task"]))
            await session.commit()
            return reply
        except DomainError as d:
            reply = {"reply": f"Не получилось: {d.message}", "task": intent["task"]}
            session.add(ChatMessage(user_id=user.id, role="assistant",
                                    body=reply["reply"], task_code=intent["task"]))
            await session.commit()
            return reply
        reply = {"reply": f"Сделано: {intent['task']} → «{intent['to']}».",
                 "task": intent["task"]}
    elif intent["kind"] == "create_task":
        from usecase.task.create_task import CreateTaskInput, create_task

        try:
            created = await create_task(session, user, CreateTaskInput(
                project_mnemonic=intent["project"], type_key=intent.get("type") or "common_task",
                title=intent["title"], priority="medium", author_tag="by_human",
                description_md=intent.get("description") or ""))
            fresh = await session.execute(sa.text(
                "SELECT title FROM task WHERE code = :c"), {"c": created.code})
            reply = {"reply": f"Задача создана: {created.code} "
                              f"«{(fresh.scalar_one_or_none() or '')[:80]}».",
                     "task": created.code}
        except DomainError as d:
            reply = {"reply": f"Не получилось: {d.message}"}
    elif intent["kind"] == "interrupt":
        import datetime as _dt

        from daemon.runner.reservation import release_reservation
        from repository.models import Chronicle, TaskRun

        t = (await session.execute(
            sa.select(Task).where(Task.code == intent["task"].upper()))).scalar_one_or_none()
        run = (await session.execute(
            sa.select(TaskRun).where(TaskRun.task_id == t.id, TaskRun.finished_at.is_(None))
            .order_by(TaskRun.started_at.desc()).limit(1))).scalar_one_or_none() if t else None
        if run is None:
            reply = {"reply": f"У {intent['task']} нет активного прогона — прерывать нечего.",
                     "task": intent.get("task")}
        else:
            now = _dt.datetime.now(_dt.timezone.utc)
            run.finished_at = now
            run.outcome = "interrupted"
            run.detail = "прервано через Eve"
            t.reserved_by = None
            t.reserved_at = None
            t.heartbeat_at = None
            session.add(Chronicle(task_id=t.id, event_type="agent", author_id=user.id,
                                  author_kind="human",
                                  message="Прогон прерван владельцем через Eve"))
            await release_reservation(session, t.id, "interrupted", "прервано через Eve")
            reply = {"reply": f"Агент над {t.code} прерван, задача освобождена.",
                     "task": t.code}
    elif intent["kind"] == "pipeline_pause":
        from repository.models import AppSetting

        row = (await session.execute(
            sa.select(AppSetting).where(AppSetting.key == "daemon.paused"))).scalar_one_or_none()
        val = "true" if intent.get("paused", True) else "false"
        if row:
            row.value = val
        else:
            session.add(AppSetting(key="daemon.paused", value=val))
        state = "остановлен (новые агенты не запускаются)" if val == "true" else "возобновлён"
        reply = {"reply": f"Конвейер {state}."}
    else:  # force
        try:
            await apply_force(session, user, intent["task"], intent["to"],
                              intent["reason"])
        except TransitionDenied as d:
            reply = {"reply": f"Не получилось: {d.reason}"}
        else:
            reply = {"reply": f"Форс-переход {intent['task']} → «{intent['to']}» выполнен."}
    session.add(ChatMessage(user_id=user.id, role="assistant", body=reply["reply"],
                            task_code=intent.get("task")))
    await session.commit()
    return reply


async def plan_force(session: AsyncSession, user: User, task_code: str, to: str,
                     reason: str) -> dict:
    """Форс с само-сформулированной причиной — тоже через намерение (ФТ-ah-52)."""
    _INTENTS[str(user.id)] = (
        {"kind": "force", "task": task_code, "to": to, "reason": reason},
        dt.datetime.now(dt.timezone.utc) + _INTENT_TTL)
    return {"action": "confirm", "intent": {"kind": "force", "task": task_code, "to": to},
            "reply": f"Форс-переход {task_code} в «{to}» с причиной: {reason}. «да»?"}


async def _task_digest(session: AsyncSession, task: Task) -> dict:
    """Досье задачи без LLM: статус, карточка-выжимка, чек-листы, прогоны, хроника."""
    lines = [f"{task.code} «{task.title}» — статус «{task.status_key}», "
             f"приоритет {task.priority}."]
    desc = (task.description_md or "").strip()
    if desc:
        lines.append("Карточка (выжимка): " + desc[:800] + ("…" if len(desc) > 800 else ""))
    cl = (await session.execute(sa.text(
        "SELECT c.kind, count(*) FILTER (WHERE i.status IN ('done','closed')) AS done_n, "
        "count(*) FILTER (WHERE i.kind='item') AS total FROM checklist c "
        "LEFT JOIN checklist_item i ON i.checklist_id = c.id "
        "WHERE c.task_id = :i GROUP BY c.kind"), {"i": str(task.id)})).all()
    if cl:
        lines.append("Чек-листы: " + "; ".join(f"{c[0]} {c[1]}/{c[2]}" for c in cl))
    runs = (await session.execute(sa.text(
        "SELECT u.name, r.outcome, r.input_tokens + r.output_tokens + r.cache_tokens "
        "FROM task_run r JOIN \"user\" u ON u.id = r.agent_id "
        "WHERE r.task_id = :i ORDER BY r.started_at DESC LIMIT 5"),
        {"i": str(task.id)})).all()
    if runs:
        lines.append("Прогоны: " + "; ".join(
            f"{a} ({o}, {tok or 0} ток.)" for a, o, tok in runs))
    chron = (await session.execute(sa.text(
        "SELECT event_type, message FROM chronicle WHERE task_id = :i "
        "ORDER BY created_at DESC LIMIT 7"), {"i": str(task.id)})).all()
    if chron:
        lines.append("Хроника (свежие сверху):\n" + "\n".join(
            f"- [{c[0]}] {c[1][:160]}" for c in chron))
    return {"reply": "\n\n".join(lines), "task": task.code}


async def _explain_blocked(session: AsyncSession, task: Task) -> dict:
    reasons = []
    if task.status_key == "blocked":
        reasons.append(f"статус blocked: {task.blocked_reason or 'причина не указана'}")
    if task.reserved_by:
        reasons.append("задача в работе у агента")
    blockers = (await session.execute(sa.text(
        "SELECT t.code FROM task_relation r JOIN task t ON t.id = r.to_task "
        "WHERE r.from_task = :i AND r.kind = 'blocked_by' "
        "AND t.status_key NOT IN ('done','canceled')"), {"i": str(task.id)})).scalars().all()
    if blockers:
        reasons.append("жёсткие связи: " + ", ".join(blockers))
    if not reasons:
        reasons.append("явных блокеров не вижу; смотрите хроники задачи")
    return {"reply": f"{task.code}: " + "; ".join(reasons), "task": task.code}


async def history(session: AsyncSession, user: User, limit: int = 50) -> list[dict]:
    rows = (await session.execute(
        sa.select(ChatMessage).where(ChatMessage.user_id == user.id)
        .order_by(ChatMessage.created_at.desc()).limit(limit))).scalars().all()
    return [{"role": m.role, "body": m.body, "taskCode": m.task_code,
             "at": m.created_at.isoformat()} for m in reversed(rows)]
