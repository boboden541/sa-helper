"""Единая точка применения переходов конвейера (порция С1).

Отделяет «как меняется состояние задачи» от того, КТО его меняет: демон
(actor="daemon", тик) и web-витрина (actor="human", синхронно по клику
человека) идут через один код:

  - apply_transition(): гейт mandatory-чек-листа → sm.transition →
    колоночный UPDATE в одной tx со stale-guard (перечитываем pipeline
    внутри BEGIN IMMEDIATE — чужой ход отменяет применение);
  - pre_event_effects(): сопутствующие правки v2/v3 перед событием
    (деэскалация circuit breaker, сброс backoff, чистый v2 при доработке);
  - human_apply()/human_apply_event(): контракт витрины — fencing по
    живой сессии, коды ok/fence/gate/noop для 200/409-ответов.

Зависимости — только stdlib + db + state_machine: web-процесс не тянет
runner/review_gate демона. Очередь commands остаётся для агентских команд.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import state_machine as sm  # noqa: E402
import ai_provider as aip  # noqa: E402
import db as dbmod  # noqa: E402

TASK_FLAG_RE = re.compile(
    r"^TASK_(T\d+)_(REQUEST_CHANGES|FORCE_APPROVE|RETRY|RESUME_WORK|PAUSE|ABORT|SKIP_REVIEW|ACCEPT|REJECT|DEFER)$")


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"


def ev(conn, story_id: int, tid: str | None, text: str,
       kind: str | None = None, actor: str = "daemon") -> None:
    dbmod.append_event(conn, story_id, tid, text, actor=actor, kind=kind)


def cmt(conn, story_id: int, tid: str, text: str, author: str = "daemon") -> None:
    dbmod.append_comment(conn, story_id, tid, author, text)


def task_flags_decisions(manifest: dict, flags: set[str]) -> list[tuple]:
    """Адресные события задач из очереди команд (канон v3, /.flags)."""
    decisions: list[tuple] = []
    by_id = {t.get("id"): t for t in manifest.get("tasks", [])}
    for name in sorted(flags):
        match = TASK_FLAG_RE.match(name)
        if not match:
            continue
        tid, action = match.groups()
        task = by_id.get(tid)
        if task is None:
            continue
        decisions.append(("flag", name))
        if action == "PAUSE":
            decisions.append(("set", tid, "paused", True))
        elif action == "RESUME_WORK":
            decisions.append(("set", tid, "paused", False))
        elif action == "SKIP_REVIEW":
            decisions.append(("set", tid, "skip_review", True))
        elif action == "RETRY":
            pipeline = task.get("pipeline")
            event = sm.EV_RETRY if pipeline == sm.BLOCKED else sm.EV_RESUME_WORK
            decisions.append(("event", tid, event, f"флаг {name}"))
        elif action == "ACCEPT":
            decisions.append(("event", tid, sm.EV_PROPOSE_ACCEPT, f"флаг {name}"))
        elif action == "DEFER":
            decisions.append(("event", tid, sm.EV_DEFER, f"флаг {name}"))
        elif action == "REJECT":
            decisions.append(("event", tid, sm.EV_PROPOSE_REJECT, f"флаг {name}"))
        else:
            event = {"REQUEST_CHANGES": sm.EV_REQUEST_CHANGES,
                     "FORCE_APPROVE": sm.EV_FORCE_APPROVE,
                     "ABORT": sm.EV_ABORT}[action]
            decisions.append(("event", tid, event, f"флаг {name}"))
    return decisions


def flag_to_event(task: dict, action: str,
                  reason: str | None = None) -> tuple[str | None, str | None, object]:
    """Одна адресная команда задачи → ("set", поле, значение) |
    ("event", EV_*, причина) | (None, None, None) — инверсия
    task_flags_decisions для синхронного пути витрины."""
    reason = reason or f"выбор человека ({action})"
    if action == "PAUSE":
        return ("set", "paused", True)
    if action == "RESUME_WORK":
        return ("set", "paused", False)
    if action == "SKIP_REVIEW":
        return ("set", "skip_review", True)
    events = {"ACCEPT": sm.EV_PROPOSE_ACCEPT, "DEFER": sm.EV_DEFER,
              "REJECT": sm.EV_PROPOSE_REJECT,
              "REQUEST_CHANGES": sm.EV_REQUEST_CHANGES,
              "FORCE_APPROVE": sm.EV_FORCE_APPROVE, "ABORT": sm.EV_ABORT}
    if action == "RETRY":
        pipeline = task.get("pipeline")
        event = sm.EV_RETRY if pipeline == sm.BLOCKED else sm.EV_RESUME_WORK
        return ("event", event, reason)
    if action in events:
        return ("event", events[action], reason)
    return (None, None, None)


def _escalation_report(task: dict, reason: str) -> str:
    tid = task["id"]
    findings = [f for f in (task.get("findings") or [])
                if f.get("resolution") != "resolved"]
    lines = [
        "⏸ **Требуется вмешательство человека** — задача остановлена в статусе NEEDS_HUMAN.",
        f"**Формальная причина:** {reason}",
    ]
    lines.append(
        f"Где остановилась: {task.get('blocked_from') or '—'} · "
        f"итераций ревью: {task.get('review_iterations') or 0}/3 · "
        f"перезапусков: {task.get('retries') or 0}",
    )
    if findings:
        lines.append("Открытые замечания ревью:")
        for f in findings[:10]:
            where = f" ({f['file']})" if f.get("file") else ""
            lines.append(f"· [{f.get('id')}] {f.get('text')}{where} — {f.get('resolution', 'open')}")
    lines += [
        "Что можно сделать (кнопки в карточке):",
        f"· «Повторить» (TASK_{tid}_RETRY) — вернуть задачу в работу с места остановки",
        f"· «Принять (force)» — если считаете задачу готовой (только из Review)",
        f"· «Остановить» (TASK_{tid}_ABORT) — снять задачу с конвейера",
        "Комментарий в этом журнале увидит агент при следующем запуске задачи.",
    ]
    return "\n".join(lines)


def _steward_options(conn, story_id: int, tid: str, reason: str) -> None:
    """Steward предлагает человеку ровно 3 варианта (stdout-JSON → steward_options)."""
    story = conn.execute("SELECT fnr FROM stories WHERE id=?", (story_id,)).fetchone()
    prompt = (
        f"/steward Задача {tid} (Story {story['fnr']}) остановлена в NEEDS_HUMAN. "
        f"Причина: {reason}. Ответь ТОЛЬКО JSON-объектом в stdout, без файлов: "
        'формат {"options": [{"title": "кратко", "explanation": "почему и последствия", '
        '"flag": "TASK_' + tid + '_RETRY|TASK_' + tid + '_FORCE_APPROVE|TASK_' + tid +
        '_ABORT|TASK_' + tid + '_REQUEST_CHANGES|null", "recommended": true|false}]}. '
        "Ровно один recommended=true. Flag=null — только для варианта «разобраться вручную»."
    )
    options_json = None
    try:
        result = subprocess.run(["claude", "--output-format", "json", "-p", prompt],
                                capture_output=True, text=True, timeout=600,
                                stdin=subprocess.DEVNULL,
                                env=aip.apply_env(dict(os.environ), conn))
        try:
            doc = json.loads(result.stdout or "{}")
            answer = str(doc.get("result") or "")
            parsed = json.loads(answer[answer.index("{"):answer.rindex("}") + 1])
            if isinstance(parsed.get("options"), list) and parsed["options"]:
                options_json = json.dumps(parsed, ensure_ascii=False)
        except (json.JSONDecodeError, ValueError, KeyError):
            options_json = None
    except (OSError, subprocess.SubprocessError):
        options_json = None
    if options_json:
        dbmod.steward_options_set(conn, story_id, tid, options_json)
    ev(conn, story_id, tid, f"{tid}: варианты Steward "
                            f"{'записаны' if options_json else 'не подготовлены (offline/лимиты)'}")


def pre_event_effects(conn, story_id: int, tid: str, event: str, task: dict) -> None:
    """Сопутствующие правки v2/v3 перед событием (канон тика демона)."""
    if event in (sm.EV_RETRY, sm.EV_RESUME_WORK) \
            and task.get("v2_status") == "ESCALATED_BLOCKED":
        # человек явно попросил повторить после circuit breaker:
        # снимаем v2-эскалацию, иначе completion ре-эскалирует
        # до старта новой сессии (кейс T7)
        target = task.get("blocked_from") or "IMPLEMENTING"
        v2 = "AGENT_REVIEW" if target == "REVIEW" else "APPROVED"
        dbmod.task_set_v2(conn, story_id, tid, {"status": v2})
    if event == sm.EV_RETRY:
        dbmod.task_set_v3(conn, story_id, tid, {"retry_after_ts": 0})
    if event in (sm.EV_REVIEW_CHANGES, sm.EV_REQUEST_CHANGES):
        # доработка с чистым v2-статусом (канон v3)
        dbmod.task_set_v2(conn, story_id, tid, {"status": "APPROVED"})
        dbmod.task_set_v3(conn, story_id, tid, {"review_verdict": None})
    if event == sm.EV_IMPL_BLOCKED:
        backoff = min(300 * (2 ** (task.get("retries") or 0)), 3600)
        dbmod.task_set_v3(conn, story_id, tid,
                          {"retry_after_ts": time.time() + backoff})
    # СТ FNR-11 4.4.1: долг повторов копится при каждом блоке и не
    # сбрасывается возвратом; обнуляется при полном завершении задачи
    if event == sm.EV_IMPL_BLOCKED:
        dbmod.task_set_v3(conn, story_id, tid,
                          {"retry_debt": (task.get("retry_debt") or 0) + 1})
    if event in (sm.EV_IMPL_PASSED, sm.EV_REVIEW_APPROVED, sm.EV_VERIFY_PASSED):
        dbmod.task_set_v3(conn, story_id, tid, {"retry_debt": 0})


def apply_transition(conn, story_id: int, tid: str, event: str, reason: str,
                     actor: str = "daemon") -> bool:
    """Применить событие машины состояний в БД. False при отказе/гонке.

    actor="daemon" — тик демона (канон); actor="human" — синхронное
    действие человека в витрине: событие и финальный комментарий
    подписаны человеком, служебные тексты (гейт, эскалация) — демоном.
    """
    task = dbmod.read_task(conn, story_id, tid, with_card=False)
    if not task:
        return False
    pipeline_before = task.get("pipeline")
    # гейт чек-листа: незакрытые обязательные пункты блокируют approve
    if event in (sm.EV_REVIEW_APPROVED, sm.EV_FORCE_APPROVE):
        open_m = dbmod.checklist_open_mandatory(conn, task["id"])
        if open_m:
            cmt(conn, story_id, tid,
                f"⛔ Гейт чек-листа: {len(open_m)} обязательных пунктов открыты — "
                "закройте их (или снимите !), затем повторите approve: "
                + "; ".join(f"«{m['text']}»" for m in open_m[:5]))
            ev(conn, story_id, tid,
               f"{tid}: approve отклонён гейтом чек-листа ({len(open_m)} mandatory)",
               kind="gate")
            return False
    task["id"] = task["tid"]
    result = sm.transition(task, event)
    if not result["ok"]:
        ev(conn, story_id, tid, f"{tid}: ОТКАЗ {event}: {result['error']}", actor=actor)
        return False
    patch = dict(result["patch"])
    new_pipeline = patch.get("pipeline")
    # stale-guard: между read и записью задачу мог подвинуть другой писатель
    # (демон/витрина) — BEGIN IMMEDIATE сериализует, перечитываем в tx
    stale = False
    with dbmod.tx(conn):
        cur = conn.execute("SELECT pipeline FROM tasks WHERE story_id=? AND tid=?",
                           (story_id, tid)).fetchone()
        if cur is None or cur["pipeline"] != pipeline_before:
            stale = True
        else:
            sets = ", ".join(f"{k}=?" for k in patch)
            conn.execute(f"UPDATE tasks SET {sets}, pipeline_since=?, blocked_reason=?,"
                         " updated_at=? WHERE story_id=? AND tid=?",
                         (*patch.values(), now_iso(), reason, now_iso(), story_id, tid))
    if stale:
        ev(conn, story_id, tid,
           f"{tid}: {event} отменён — задача параллельно переехала из {pipeline_before}",
           kind="race", actor=actor)
        return False
    if new_pipeline and new_pipeline != sm.NEEDS_HUMAN:
        dbmod.steward_options_clear(conn, story_id, tid)
    label = f"{tid}: {event} → {new_pipeline} ({reason})"
    ev(conn, story_id, tid, label, actor=actor)
    if new_pipeline == sm.NEEDS_HUMAN:
        dbmod.task_set_v3(conn, story_id, tid, {"blocked_reason": reason})
        task["blocked_reason"] = reason
        cmt(conn, story_id, tid, _escalation_report(task, reason))
        threading.Thread(target=_steward_options, daemon=True,
                         args=(conn, story_id, tid, reason)).start()
    elif new_pipeline == sm.BLOCKED:
        wait_min = max(1, round(float(task.get("retry_after_ts") or time.time())
                                - time.time()) // 60)
        cmt(conn, story_id, tid,
            f"⛔ Стадия прервана — задача в BLOCKED, авто-перезапуск ~через {wait_min} мин "
            f"(попытка {task.get('retries') or 0}). Причина: {reason}")
    else:
        cmt(conn, story_id, tid, f"{event} → {new_pipeline} — {reason}",
            author="human" if actor == "human" else "daemon")
    return True


# --- синхронный человеческий путь (витрина) -------------------------------

def _live_task_session(conn, story_id: int, tid: str) -> dict | None:
    """Живая (alive-pid) сессия именно этой задачи — для fencing витрины."""
    for s in dbmod.live_sessions(conn, story_id):
        if s.get("tid") == tid and s.get("alive"):
            return s
    return None


def _human_event(conn, story_id: int, tid: str, event: str, reason: str,
                 fence: bool = True) -> dict:
    """Общее ядро синхронного человеческого события.

    Возвращает web-контракт: {"ok": True, "pipeline": <факт>} либо
    {"ok": False, "code": "no_task"|"fence"|"gate"|"noop", "error": текст}.
    """
    task = dbmod.read_task(conn, story_id, tid, with_card=False)
    if not task:
        return {"ok": False, "code": "no_task", "error": f"задача {tid} не найдена"}
    if fence:
        live = _live_task_session(conn, story_id, tid)
        if live:
            stage = live.get("stage") or "сессия"
            return {"ok": False, "code": "fence", "running": True,
                    "error": f"по {tid} сейчас работает сессия ({stage}) — "
                             "дождитесь завершения стадии или остановите задачу"}
    if event in (sm.EV_REVIEW_APPROVED, sm.EV_FORCE_APPROVE):
        open_m = dbmod.checklist_open_mandatory(conn, task["id"])
        if open_m:
            tail = f" (и ещё {len(open_m) - 5})" if len(open_m) > 5 else ""
            return {"ok": False, "code": "gate",
                    "error": "Гейт чек-листа: открыты обязательные пункты — "
                             + "; ".join(f"«{m['text']}»" for m in open_m[:5]) + tail}
    pre_event_effects(conn, story_id, tid, event, task)
    if not apply_transition(conn, story_id, tid, event, reason, actor="human"):
        # отказ машины состояний = переход уже исполнен/устарел (двойной
        # клик, параллельный ход) — для витрины это не ошибка, а no-op
        return {"ok": False, "code": "noop",
                "error": "переход не применён — вероятно, уже исполнен"}
    fresh = dbmod.read_task(conn, story_id, tid, with_card=False)
    return {"ok": True, "pipeline": (fresh or {}).get("pipeline") or "",
            "noop": False}


def human_apply(conn, story_id: int, tid: str, action: str,
                reason: str | None = None, fence: bool = True) -> dict:
    """Синхронное человеческое действие по имени команды задачи
    (RETRY/RESUME_WORK/PAUSE/ABORT/DEFER/FORCE_APPROVE/...)."""
    task = dbmod.read_task(conn, story_id, tid, with_card=False)
    if not task:
        return {"ok": False, "code": "no_task", "error": f"задача {tid} не найдена"}
    kind, key, value = flag_to_event(task, action, reason)
    if kind is None:
        return {"ok": False, "code": "illegal",
                "error": f"неизвестное действие {action}"}
    if kind == "set":
        # легитимное исключение из «v3 пишет только демон»: paused/skip_review
        # безопасны при живой сессии (сессия читает их через sahelper flags)
        dbmod.task_set_v3(conn, story_id, tid, {key: value})
        ev(conn, story_id, tid, f"{tid}: {key}={value} (человек)",
           kind="flag", actor="human")
        return {"ok": True, "pipeline": task.get("pipeline") or "", "noop": False}
    return _human_event(conn, story_id, tid, key, value, fence=fence)


def human_apply_event(conn, story_id: int, tid: str, event: str, reason: str,
                      fence: bool = True) -> dict:
    """То же, но событие задано напрямую (DnD: пара колонок → EV_*)."""
    return _human_event(conn, story_id, tid, event, reason, fence=fence)
