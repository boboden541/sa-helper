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
        reply = {"reply": "Не распознала фразу. Примеры: «переведи SA-12 на ревью», "
                          "«почему SA-14 встала?», «что с SA-7?», «создай задачу «Название»»."}
    session.add(ChatMessage(user_id=user.id, role="assistant",
                            body=str(reply.get("reply") or reply.get("action", "")),
                            task_code=task.code if task else None))
    await session.commit()
    return reply


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
