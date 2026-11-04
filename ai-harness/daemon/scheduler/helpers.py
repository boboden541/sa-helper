"""Хелперы планировщика: паузы ретраев, сортировка очереди, хроники.

Вынесено из scheduler.py (рефакторинг 04.11.2026, решение владельца —
лимит 800 строк на файл); поведение не менялось.
"""

from __future__ import annotations

import datetime as dt
import logging

import sqlalchemy as sa
from repository.models import TaskRun
from sqlalchemy.ext.asyncio import AsyncSession

from daemon.config import retry_pauses_minutes


async def active_run_id(session, task_id) -> str | None:
    """Id активного прогона задачи (для лога прогона); None — активного нет."""
    return (
        await session.execute(
            sa.select(TaskRun.id)
            .where(TaskRun.task_id == task_id, TaskRun.finished_at.is_(None))
            .order_by(TaskRun.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


from repository.models import Task

log = logging.getLogger("daemon")


PRIORITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _queue_sort(rows: list) -> list:
    """Правила очереди: приоритет → баги выше → старые выше (ФТ-ah-4).
    rows — кортежи (Task, type_key, user_id, mode, position).
    Для зависимости-осознанного порядка _launch_ready сортирует сам (см. _dep_key)."""
    rank = PRIORITY_RANK

    def key(item):
        task, type_key = item[0], item[1]
        return (
            rank.get(task.priority, 9),
            0 if type_key == "bug" else 1,
            task.created_at,
            task.code,
        )

    return sorted(rows, key=key)


async def _next_retry_at(
    session: AsyncSession, task_id, status_key: str, cfg: dict[str, str]
) -> dt.datetime | None:
    """Пауза перед повторным запуском (ФТ-ah-33): растущая серия 1 → 5 → 15 мин.

    Особые исходы (без выжигания попыток):
    - перехват человеком (interrupted) — максимальная пауза: у человека тихое окно,
      чтобы забрать задачу себе, а демон не перезапускал агента у него из рук;
    - успех без перехода (тот же статус) — максимальная пауза: агент отчитался,
      но ничего не изменил; повтор сразу же означал бы вечный цикл."""
    from repository.models import TaskRun

    row = (
        await session.execute(
            sa.select(TaskRun.finished_at, TaskRun.attempt_no, TaskRun.outcome, TaskRun.status_key)
            .where(
                TaskRun.task_id == task_id,
                TaskRun.outcome.in_(("failed", "interrupted", "success")),
            )
            .order_by(TaskRun.finished_at.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    return _retry_at_from_run(row, status_key, cfg)


def _retry_at_from_run(run, status_key: str, cfg: dict[str, str]) -> dt.datetime:
    """Чистая часть расчёта паузы: run = (finished_at, attempt_no, outcome,
    status_key) — общий для одиночного и пакетного чтения (анализ 30.10.2026)."""
    pauses = retry_pauses_minutes(cfg)
    finished_at, attempt_no, outcome, run_sk = run[0], run[1], run[2], run[3]
    if outcome in ("interrupted", "success") and (outcome == "interrupted" or run_sk == status_key):
        return finished_at + dt.timedelta(minutes=pauses[-1])
    attempt = min(attempt_no, len(pauses)) - 1
    return finished_at + dt.timedelta(minutes=pauses[max(attempt, 0)])


async def task_id_by_code(session, code):

    return (await session.execute(sa.select(Task.id).where(Task.code == code))).scalar_one()


def blocked_reason_from_summary(summary: str, limit: int = 500) -> str:
    """Причина блокировки для карточки: агент начинает summary с отчёта о работе,
    а причину блокировки пишет в КОНЦЕ (VITRINA-37: «Итог: …» обрезалось ровно
    перед сутью). Берём хвост целиком: обрыв в начале причины информативнее
    её отсутствия."""
    reason = (summary or "").strip()
    if len(reason) <= limit:
        return reason
    return "…" + reason[-(limit - 1) :]


def targeted_retry_block(denied_reason: str | None, open_items: list[dict]) -> str | None:
    """Блок «прицельный перепрогон» для контекста: прошлый прогон упёрся в
    чеклист-гейт — следующий агент верифицирует только открытое, не повторяет
    полный регресс (экономия: 50 мин и ~11М кэша на повтор)."""
    if not (denied_reason and open_items):
        return None
    lines = [f"{it['kind']}#{it['position']}: {it['text']} ({it['status']})" for it in open_items]
    return (
        "## Прицельный перепрогон (важно)\n"
        f"Прошлый прогон выполнил работу, но переход отклонён гейтом: {denied_reason}.\n"
        f"Единственное препятствие — открытые пункты чеклиста:\n"
        + "\n".join(f"- {line}" for line in lines)
        + "\nВерифицируй ТОЛЬКО эти пункты (полный регресс не повторяй — он уже "
        "пройден прошлым прогоном), закрой их в checklist_updates и предложи переход."
    )


def _chronicle(task_id, rule: str, message: str):
    from repository.models import Chronicle

    return Chronicle(
        task_id=task_id, event_type="agent", author_kind="auto", rule_code=rule, message=message
    )


# исходы, при которых агент НЕ успел/не смог отписаться сам — след сессии
# пишет демон (решение владельца 04.11.2026 «комментарий обязателен даже при
# мягком переключении сессии»)
HANDOFF_OUTCOMES = frozenset(
    {"soft_turns", "timeout_start", "timeout_work", "turns_limit", "no_report"}
)

_HANDOFF_HEADLINES = {
    "soft_turns": "Сессия оборвана мягким лимитом ходов — отчёт не был возвращён",
    "timeout_start": "Таймаут старта прогона — процесс остановлен демоном",
    "timeout_work": "Таймаут работы прогона — процесс остановлен демоном",
    "turns_limit": "Исчерпан жёсткий лимит ходов — отчёт не был возвращён",
    "no_report": "Агент не вернул отчёт по контракту",
}


async def write_handoff_comment(maker, task_id, agent_id, run_id, headline: str) -> bool:
    """[handoff]-комментарий в карточку от имени агента: сессия кончилась без
    отчёта — следующий агент и человек видят по карточке, на чём остановились.
    Источник — хвост лога прогона (те же события, что уходят в handoff-блок
    контекста следующей сессии). Пустой лог (агент не начал работать) —
    комментария нет: нечего докладывать. True — комментарий записан."""
    from repository.models import TaskComment

    async with maker() as s:
        rows = (
            (
                await s.execute(
                    sa.text(
                        "SELECT kind, left(coalesce(text,''),160) AS txt FROM task_run_log "
                        "WHERE run_id = :r AND kind IN ('tool', 'thinking') "
                        "AND coalesce(text, '') <> '' ORDER BY seq DESC LIMIT 8"
                    ),
                    {"r": str(run_id)},
                )
            )
            .mappings()
            .all()
        )
        if not rows:
            return False
        lines = [f"[handoff] {headline}. Последние действия сессии:"]
        lines += [f"- [{r['kind']}] {r['txt']}" for r in reversed(rows)]
        lines.append("Следующий прогон продолжит с этого места.")
        s.add(TaskComment(task_id=task_id, author_id=agent_id, body="\n".join(lines)[:4000]))
        await s.commit()
        return True
