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
        target = _guess_target(text)
        if target is None:
            reply = {"reply": "Куда перевести? Назовите статус: например, «на ревью».",
                     "task": task.code}
        else:
            reply = await _plan_transition(session, user, task, target)
    elif WHY_VERBS.search(text) and task is not None:
        reply = await _explain_blocked(session, task)
    elif REPORT_VERBS.search(text) and task is not None:
        reply = {"reply": f"{task.code} «{task.title}»: статус «{task.status_key}», "
                          f"приоритет {task.priority}.", "task": task.code}
    elif re.search(r"создай задачу", text, re.IGNORECASE):
        title = re.search(r"«(.+?)»|\"(.+?)\"", text)
        reply = {"action": "open_create_dialog",
                 "prefillTitle": (title.group(1) or title.group(2)) if title else ""}
    else:
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
        f"Текущее состояние системы:\n{context}\n\n{screen}\n\n"
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


def _guess_target(text: str) -> str | None:
    mapping = {"ревью": "in_review", "тест": "in_testing", "работ": "in_progress",
               "бэклог": "backlog", "готов": "done", "отмен": "canceled",
               "блок": "blocked", "декомпозиц": "todo", "к работе": "todo"}
    for needle, status in mapping.items():
        if needle in text.lower():
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
        except DomainError as d:
            reply = {"reply": f"Не получилось: {d.message}", "task": intent["task"]}
            session.add(ChatMessage(user_id=user.id, role="assistant",
                                    body=reply["reply"], task_code=intent["task"]))
            await session.commit()
            return reply
        reply = {"reply": f"Сделано: {intent['task']} → «{intent['to']}».",
                 "task": intent["task"]}
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
