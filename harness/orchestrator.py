"""Демон-координатор конвейера v3 на БД (порция R3 миграции на SQLite).

Ведёт задачи Story по машине состояний (state_machine.py) автономно: сам
запускает стадии headless-сессиями claude CLI (те же команды v2), следит за
живостью (sessions.last_beat_at + watchdog), перезапускает упавшие стадии
с backoff и пишет события в БД (SSE-фид + таймлайн). Человек управляет
командами (очередь commands — бывшие .flags) и витриной.

Ключевые решения:
  - Состояние целиком в БД (~/.sa-helper/harness.db, WAL): kill -9 демона
    не теряет состояние; осиротевшие сессии распознаются по таблице sessions
    (status='running' + живой pid → fencing; мёртвый pid → reconcile).
  - Один писатель домена: pipeline и v3-поля пишет только демон; сессии —
    только v2-домен (через адаптер, R4). Тень не нужна: UPDATE колоночный.
  - Решения — чистая функция decide(): не изменилась с файловой версии.
  - Stream-логи стадий остаются файлами (.run/*.log), путь — в sessions.

Только stdlib; кроссплатформенно (macOS/Linux, Windows Git Bash).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import state_machine as sm  # noqa: E402
import review_gate as rg  # noqa: E402
import db as dbmod  # noqa: E402
import cards  # noqa: E402
from runner import _kill_tree  # noqa: E402

IS_WINDOWS = os.name == "nt"

STAGE_COMMANDS = {
    "implementing": "/impl-run {harness} {task}",
    "review": "/impl-review {harness} {task}",
    "verify": "/impl-verify {harness}",
    "handoff": "/impl-handoff {source}",
    "decompose": "/task-decompose {harness} {task}",
}
TASK_FLAG_RE = re.compile(
    r"^TASK_(T\d+)_(REQUEST_CHANGES|FORCE_APPROVE|RETRY|RESUME_WORK|PAUSE|ABORT|SKIP_REVIEW|ACCEPT|REJECT|DEFER)$")
SESSION_ID_RE = re.compile('"session_id":\\s*"([a-f0-9-]+)"')


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"


def claude_command(args: list[str], skip_permissions: bool,
                   claude_bin: str = "claude") -> list[str]:
    base = [claude_bin, *args, "--output-format", "stream-json", "--verbose"]
    base += ["--dangerously-skip-permissions"] if skip_permissions \
        else ["--permission-mode", "acceptEdits"]
    return base


def pid_alive(pid: int) -> bool:
    try:
        if IS_WINDOWS:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                                 capture_output=True, text=True, check=False)
            return str(pid) in out.stdout
        os.kill(pid, 0)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def deps_done(task: dict, tasks_by_id: dict) -> bool:
    return all(
        (tasks_by_id.get(d) or {}).get("pipeline") in (sm.DONE, sm.VERIFIED)
        for d in (task.get("depends_on") or [])
    )


def completion_events(task: dict, review_iterations_max: int = 3) -> list[tuple[str, str]]:
    """События завершения стадии по факту состояния задачи (канон v3)."""
    pipeline = task.get("pipeline")
    status = task.get("status")
    verdict = task.get("review_verdict")
    if pipeline == sm.IMPLEMENTING:
        if status in ("AGENT_REVIEW", "DONE"):
            return [(sm.EV_IMPL_PASSED, f"сессия завершила реализацию (status={status})")]
        if status == "ESCALATED_BLOCKED":
            return [(sm.EV_IMPL_ESCALATED, "circuit breaker (status=ESCALATED_BLOCKED)")]
        return []
    if pipeline == sm.REVIEW:
        if verdict == "APPROVED" and status == "DONE":
            return [(sm.EV_REVIEW_APPROVED, "вердикт APPROVED")]
        if verdict == "CHANGES_REQUESTED":
            if (task.get("review_iterations") or 0) >= review_iterations_max:
                return [(sm.EV_REVIEW_STALLED, "лимит итераций ревью исчерпан")]
            return [(sm.EV_REVIEW_CHANGES, "вердикт CHANGES_REQUESTED → доработка")]
        return []
    return []


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


# --- чистое ядро решений (не изменилось с файловой версии) ----------------

def decide(manifest: dict, flags: set[str], state: dict) -> list[tuple]:
    """Решения одного тика по одной Story.

    state: {"lane_free": bool, "running_task_id": str|None, "now": float,
            "verification_report": bool, "verify_attempted": bool,
            "orphan_running": bool, "max_retries": int}
    """
    decisions: list[tuple] = []
    status = manifest.get("status")
    tasks = manifest.get("tasks", [])
    by_id = {t.get("id"): t for t in tasks}
    running = state.get("running_task_id")
    paused = "PAUSE" in flags

    if status == "AWAITING_APPROVAL" and "APPROVE_PLAN" in flags:
        decisions.append(("flag", "APPROVE_PLAN"))
        decisions.append(("approve_plan",))
        decisions.append(("wait", "план утверждён — конвейер стартует со следующего тика"))
        return decisions

    task_flag_decisions = task_flags_decisions(manifest, flags)
    if task_flag_decisions:
        return task_flag_decisions + [("wait", "флаги задач применены")]

    for task in tasks:
        migrate_task_pipeline(task)

    if status == "AWAITING_APPROVAL":
        decisions.append(("wait", "план не утверждён (нет .flags/APPROVE_PLAN)"))
        return decisions

    for task in tasks:
        tid = task["id"]
        pipeline = task["pipeline"]
        lane_free = bool(state.get("lane_free")) and not running
        if task.get("paused"):
            continue

        if pipeline == sm.BACKLOG and deps_done(task, by_id):
            decisions.append(("event", tid, sm.EV_QUEUE_READY, "зависимости закрыты"))
            pipeline = sm.READY

        if pipeline == sm.BLOCKED:
            if state["now"] < float(task.get("retry_after_ts") or 0):
                continue
            if (task.get("retries") or 0) >= state.get("max_retries", 3):
                decisions.append(("event", tid, sm.EV_BLOCKED_ESCALATED,
                                  f"retries={task.get('retries')} — исчерпаны"))
            else:
                decisions.append(("event", tid, sm.EV_RETRY,
                                  f"backoff истёк (retries={task.get('retries')})"))
                pipeline = task.get("blocked_from") or sm.IMPLEMENTING

        if pipeline == sm.PROPOSED:
            if task.get("origin") == "manual" and not task.get("decomposed"):
                if state.get("orphan_running"):
                    continue
                if lane_free and not paused:
                    decisions.append(("stage", tid, "decompose"))
                    running = tid
                continue
            if task.get("origin") == "manual" and task.get("decomposed"):
                decisions.append(("event", tid, sm.EV_DECOMPOSE_DONE,
                                  "декомпозиция завершена → в бэклог"))
                continue

        if pipeline in (sm.IMPLEMENTING, sm.REVIEW):
            done_events = completion_events(task)
            if done_events:
                decisions.append(("event", tid, *done_events[0]))
                continue
            if state.get("orphan_running"):
                continue
            if lane_free and not paused:
                decisions.append(("stage", tid,
                                  "implementing" if pipeline == sm.IMPLEMENTING else "review"))
                running = tid
            continue

        if pipeline == sm.READY and lane_free and not paused:
            decisions.append(("event", tid, sm.EV_START, "слот свободен"))
            decisions.append(("stage", tid, "implementing"))
            running = tid

    if (tasks and all(t["pipeline"] in (sm.DONE, sm.VERIFIED, sm.ABORTED) for t in tasks)
            and any(t["pipeline"] == sm.DONE for t in tasks)
            and not state.get("verification_report") and not state.get("verify_attempted")
            and not running and lane_free and not paused):
        decisions.append(("stage", None, "verify"))

    return decisions


def migrate_task_pipeline(task: dict) -> bool:
    """v2-задача без pipeline → вывод pipeline (идемпотентно; в БД — no-op)."""
    if task.get("pipeline") in sm.PIPELINE_STATUSES:
        return False
    if task.get("origin") == "agent":
        task["pipeline"] = sm.PROPOSED
    else:
        task["pipeline"] = _V2_TO_PIPELINE.get(task.get("status"), sm.BACKLOG)
    task.setdefault("retries", 0)
    task.setdefault("review_iterations", 0)
    task.setdefault("skip_review", False)
    task.setdefault("paused", False)
    return True


_V2_TO_PIPELINE = {
    "PLANNED": sm.BACKLOG, "APPROVED": sm.BACKLOG,
    "TDD_RED": sm.IMPLEMENTING, "TDD_GREEN": sm.IMPLEMENTING, "GATES": sm.IMPLEMENTING,
    "AGENT_REVIEW": sm.REVIEW, "DONE": sm.DONE,
    "ESCALATED_BLOCKED": sm.NEEDS_HUMAN, "ABORTED": sm.ABORTED,
}


# --- вид манифеста из БД (для decide/флагов) ------------------------------

def manifest_view(conn, story_id: int) -> dict:
    """Story в форме старого manifest.json — ровно то, что читает decide()."""
    story = conn.execute("SELECT * FROM stories WHERE id=?", (story_id,)).fetchone()
    tasks = []
    for row in conn.execute("SELECT tid FROM tasks WHERE story_id=? ORDER BY"
                            " CAST(SUBSTR(tid,2) AS INTEGER)", (story_id,)):
        t = dbmod.read_task(conn, story_id, row["tid"], with_card=False)
        tasks.append({
            "id": t["tid"], "pipeline": t["pipeline"], "status": t["v2_status"],
            "depends_on": t["depends_on"], "paused": bool(t["paused"]),
            "skip_review": bool(t["skip_review"]), "origin": t["origin"],
            "decomposed": bool(t["decomposed"]), "retries": t["retries"],
            "review_iterations": t["review_iterations"],
            "retry_after_ts": t["retry_after_ts"],
            "review_verdict": t["review_verdict"],
        })
    return {
        "fnr_id": story["fnr"], "status": story["status"],
        "auto_review_strategy": story["auto_review_strategy"],
        "circuit_breaker": {"max_iterations_per_task": story["circuit_breaker_max"]},
        "tasks": tasks,
    }


def _verify_flags(conn, story_id: int, ws: Path, fnr: str) -> tuple[bool, bool]:
    """verification_report существует / verify уже пробовали (маркер в meta)."""
    has_report = dbmod.doc_get(conn, story_id, "verification_report") is not None
    attempted = conn.execute("SELECT value FROM meta WHERE key=?",
                             (f"verify_attempted:{story_id}",)).fetchone()
    return bool(has_report), bool(attempted)


# --- применение переходов и журналы (БД) ---------------------------------

def ev(conn, story_id: int, tid: str | None, text: str) -> None:
    dbmod.append_event(conn, story_id, tid, text, actor="daemon")


def cmt(conn, story_id: int, tid: str, text: str) -> None:
    dbmod.append_comment(conn, story_id, tid, "daemon", text)


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


def apply_transition(conn, story_id: int, tid: str, event: str, reason: str) -> bool:
    """Применить событие машины состояний в БД. False при отказе."""
    task = dbmod.read_task(conn, story_id, tid, with_card=False)
    if not task:
        return False
    task["id"] = task["tid"]
    result = sm.transition(task, event)
    if not result["ok"]:
        ev(conn, story_id, tid, f"{tid}: ОТКАЗ {event}: {result['error']}")
        return False
    patch = dict(result["patch"])
    new_pipeline = patch.get("pipeline")
    with dbmod.tx(conn):
        sets = ", ".join(f"{k}=?" for k in patch)
        conn.execute(f"UPDATE tasks SET {sets}, pipeline_since=?, blocked_reason=?,"
                     " updated_at=? WHERE story_id=? AND tid=?",
                     (*patch.values(), now_iso(), reason, now_iso(), story_id, tid))
    if new_pipeline and new_pipeline != sm.NEEDS_HUMAN:
        dbmod.steward_options_clear(conn, story_id, tid)
    label = f"{tid}: {event} → {new_pipeline} ({reason})"
    ev(conn, story_id, tid, label)
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
        cmt(conn, story_id, tid, f"{event} → {new_pipeline} — {reason}")
    return True


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
                                stdin=subprocess.DEVNULL)
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


# --- reconcile ревью-петли и завершения стадий (БД) ----------------------

def _latest_verdict(conn, story_id: int, tid: str) -> dict | None:
    """Последний вердикт задачи в форме parse_review_verdict (для rg.review_gate)."""
    row = conn.execute(
        "SELECT id, status FROM review_verdicts WHERE story_id=? AND tid=?"
        " ORDER BY iteration DESC, id DESC LIMIT 1", (story_id, tid)).fetchone()
    if not row:
        return None
    blocking, advisory = [], []
    for it in conn.execute("SELECT kind, fid, file, text FROM verdict_items"
                           " WHERE verdict_id=?", (row["id"],)):
        item = {"id": it["fid"], "file": it["file"] or "", "text": it["text"]}
        (blocking if it["kind"] == "blocking" else advisory).append(item)
    return {"status": row["status"], "blocking": blocking,
            "advisory": advisory, "previous": {}}


def reconcile_review(conn, story_id: int, tid: str,
                     review_iterations_max: int = 3) -> str | None:
    """Ревью-петля: вердикт из БД → review_gate → findings + переход."""
    task = dbmod.read_task(conn, story_id, tid, with_card=False)
    task["id"] = tid
    parsed = _latest_verdict(conn, story_id, tid)
    if parsed is not None:
        story = conn.execute("SELECT auto_review_strategy FROM stories WHERE id=?",
                             (story_id,)).fetchone()
        gate = rg.review_gate(task, parsed,
                              strategy=story["auto_review_strategy"] or "closure_first",
                              review_iterations_max=review_iterations_max)
        with dbmod.tx(conn):
            conn.execute("DELETE FROM findings WHERE story_id=? AND tid=?",
                         (story_id, tid))
            for f in gate["findings"]:
                conn.execute(
                    "INSERT OR REPLACE INTO findings(story_id, tid, fid, text, file,"
                    " resolution, updated_at) VALUES (?,?,?,?,?,?,?)",
                    (story_id, tid, f["id"], f["text"], f.get("file"),
                     f.get("resolution", "open"), now_iso()))
        v3 = {"review_verdict": parsed["status"]}
        if gate["event"] == sm.EV_REVIEW_CHANGES:
            task["status"] = "APPROVED"
            task["review_verdict"] = None
            dbmod.task_set_v2(conn, story_id, tid, {"status": "APPROVED"})
            v3["review_verdict"] = None
        dbmod.task_set_v3(conn, story_id, tid, v3)
        task["review_verdict"] = v3["review_verdict"] if v3["review_verdict"] else parsed["status"]
        apply_transition(conn, story_id, tid, gate["event"], gate["reason"])
        return gate["reason"]
    events = completion_events(task, review_iterations_max)
    if events:
        event, reason = events[0]
        apply_transition(conn, story_id, tid, event, reason)
        return reason
    return None


def reconcile_after_stage(conn, story_id: int, tid: str, exit_code: int,
                          max_retries: int = 3,
                          review_iterations_max: int = 3) -> str:
    """Перевод задачи после завершения стадии (канон файловой версии)."""
    task = dbmod.read_task(conn, story_id, tid, with_card=False)
    task["id"] = tid
    if task.get("pipeline") not in (sm.IMPLEMENTING, sm.REVIEW):
        return f"{tid}: стадия уже учтена (pipeline={task.get('pipeline')})"
    if task.get("pipeline") == sm.REVIEW:
        reason = reconcile_review(conn, story_id, tid,
                                  review_iterations_max=review_iterations_max)
        if reason:
            task = dbmod.read_task(conn, story_id, tid, with_card=False)
            return f"{tid}: {reason} → {task['pipeline']}"
        apply_transition(conn, story_id, tid, sm.EV_IMPL_BLOCKED,
                         f"сессия ревью прервана без вердикта (exit={exit_code})")
        dbmod.task_set_v3(conn, story_id, tid, {
            "retry_after_ts": time.time()
            + min(300 * (2 ** (task.get("retries") or 0)), 3600)})
        return f"{tid}: сессия ревью прервана → BLOCKED"

    events = completion_events(task, review_iterations_max)
    if events:
        event, reason = events[0]
        apply_transition(conn, story_id, tid, event, reason)
        label = {sm.EV_IMPL_PASSED: "реализация завершена",
                 sm.EV_IMPL_ESCALATED: "эскалация circuit breaker"}.get(event, event)
        return f"{tid}: {label} → {dbmod.read_task(conn, story_id, tid, with_card=False)['pipeline']}"

    apply_transition(conn, story_id, tid, sm.EV_IMPL_BLOCKED,
                     f"сессия прервана (exit={exit_code}, status={task.get('status')})")
    dbmod.task_set_v3(conn, story_id, tid, {
        "retry_after_ts": time.time() + min(300 * (2 ** (task.get("retries") or 0)), 3600)})
    retries = dbmod.read_task(conn, story_id, tid, with_card=False)["retries"]
    if retries > max_retries:
        apply_transition(conn, story_id, tid, sm.EV_BLOCKED_ESCALATED,
                         f"retries={retries} — исчерпаны")
        return f"{tid}: сессия прервана, retries исчерпаны → NEEDS_HUMAN"
    return f"{tid}: сессия прервана → BLOCKED (retry #{retries} по backoff)"


# --- исполнение стадий ----------------------------------------------------

def spawn_stage(workspace: Path, hdir: Path, task_id: str | None, stage: str,
                opts: argparse.Namespace, story_id: int, conn) -> tuple | None:
    """Запуск headless-сессии; стрим → .run/*.log (файл), живость/сессия → БД."""
    rel = Path(os.path.relpath(hdir, workspace)).as_posix()
    template = STAGE_COMMANDS[stage]
    if stage == "handoff":
        source = rel.rsplit("/harness", 1)[0] + "/system_requirements.md"
        prompt = template.format(source=source)
    elif task_id:
        prompt = template.format(harness=rel, task=task_id)
    else:
        prompt = template.format(harness=rel)
    run_dir = hdir / ".run"
    run_dir.mkdir(parents=True, exist_ok=True)
    suffix = task_id or "fnr"
    log_path = run_dir / f"{suffix}_{stage}_{int(time.time())}.log"

    args = claude_command(["-p", prompt, "--max-turns", str(opts.max_turns)],
                          opts.skip_permissions, getattr(opts, "claude_bin", "claude"))
    if opts.dry_run:
        print(f"  [dry-run] cwd={workspace} лог={log_path.name}\n  [dry-run] {' '.join(args)}")
        return None

    env = dict(os.environ)
    # путь БД — из самого соединения (PRAGMA database_list): тестовый контур
    # передаёт свой файл, прод — ~/.sa-helper/harness.db
    dbfile = [r[2] for r in conn.execute("PRAGMA database_list") if r[1] == "main"]
    env["HARNESS_DB"] = os.environ.get("HARNESS_DB") or (dbfile[0] if dbfile
                                                         else str(dbmod.db_path()))
    kwargs: dict = {"cwd": str(workspace), "stdin": subprocess.DEVNULL, "env": env}
    if IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    stdout_fh = open(log_path, "wb")
    try:
        try:
            proc = subprocess.Popen(args, stdout=stdout_fh,
                                    stderr=subprocess.STDOUT, **kwargs)
        except OSError as exc:
            print(f"  [warn] стадия {stage} не запущена ({exc})")
            return None
    finally:
        stdout_fh.close()
    session_row = dbmod.session_start(conn, story_id, task_id, stage, proc.pid,
                                      os.uname().nodename if not IS_WINDOWS else "win",
                                      str(log_path))
    threading.Thread(target=_stream_watch, args=(log_path, proc, conn, session_row),
                     daemon=True).start()
    return proc, session_row, log_path


def _stream_watch(log_path: Path, proc: subprocess.Popen,
                  conn, session_row: int) -> None:
    """Живость стадии: лог растёт → last_beat_at в БД; session_id → БД."""
    size = pos = 0
    claude_sid = None
    while proc.poll() is None:
        try:
            current = log_path.stat().st_size
            if current != size:
                size = current
                try:
                    dbmod.session_beat(conn, session_row)
                except Exception:
                    pass
                if claude_sid is None:
                    with log_path.open("rb") as fh:
                        fh.seek(pos)
                        chunk = fh.read().decode("utf-8", errors="replace")
                    pos = size
                    found = SESSION_ID_RE.search(chunk)
                    if found:
                        claude_sid = found.group(1)
                        try:
                            with dbmod.tx(conn):
                                conn.execute("UPDATE sessions SET claude_session_id=?"
                                             " WHERE id=?", (claude_sid, session_row))
                        except Exception:
                            pass
        except OSError:
            return
        time.sleep(1.0)
    try:
        if proc.stdout:
            proc.stdout.close()
    except OSError:
        pass


def _pick_usage(log_path: Path | None) -> dict | None:
    """Расход сессии из result-события stream-лога (канон v3)."""
    if not log_path or not Path(log_path).is_file():
        return None
    try:
        content = Path(log_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in reversed(content.splitlines()):
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if d.get("type") != "result":
            continue
        u = d.get("usage") or {}
        tokens_in = int(u.get("input_tokens") or 0) \
            + int(u.get("cache_read_input_tokens") or 0) \
            + int(u.get("cache_creation_input_tokens") or 0)
        tokens_out = int(u.get("output_tokens") or 0)
        return {"tokens_in": tokens_in, "tokens_out": tokens_out,
                "tokens_total": tokens_in + tokens_out,
                "cost_usd": round(float(d.get("total_cost_usd") or 0), 4)}
    return None


def _pick_session_id(log_path: Path | None) -> str | None:
    if not log_path or not Path(log_path).is_file():
        return None
    try:
        content = Path(log_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    found = SESSION_ID_RE.search(content)
    return found.group(1) if found else None


def claim_lock(hdir: Path) -> bool:
    """Пер-воркспейсный лок демона: .run/daemon.lock (pid). Мёртвый лок — берём."""
    lock = hdir / ".run" / "daemon.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    if lock.exists():
        try:
            old = int(lock.read_text(encoding="utf-8").strip() or 0)
            if old != os.getpid() and pid_alive(old):
                return False
        except (OSError, ValueError):
            pass
    lock.write_text(str(os.getpid()), encoding="utf-8")
    return True


# --- payload-команды: правка описания и ручные задачи --------------------

def _update_card_description(card_md: str, description: str) -> str:
    """Секция «Что сделать» в карточке (канон TASK_EDIT)."""
    section = re.search(r"(## Что сделать\n\n)(.*?)(\n## |\Z)", card_md, re.S)
    if section:
        return card_md[:section.start(2)] + description + card_md[section.end(2):]
    return card_md + f"\n## Что сделать\n\n{description}\n"


def apply_task_edit_desc(conn, story_id: int, tid: str, payload: dict) -> None:
    description = str((payload or {}).get("description") or "").strip()
    task = dbmod.read_task(conn, story_id, tid, with_card=True)
    if not description or task is None:
        ev(conn, story_id, tid, f"task.edit_desc {tid} отклонён: нет задачи или текста")
        return
    dbmod.task_set_v3(conn, story_id, tid, {})
    with dbmod.tx(conn):
        conn.execute("UPDATE tasks SET description=?, updated_at=? WHERE story_id=? AND tid=?",
                     (description[:600], now_iso(), story_id, tid))
    if task.get("card_md"):
        dbmod.task_set_card(conn, story_id, tid,
                            _update_card_description(task["card_md"], description))
    cmt(conn, story_id, tid, "**Описание обновлено человеком** через витрину — "
                             "карточка и постановка синхронизированы.")
    ev(conn, story_id, tid, f"{tid}: описание обновлено человеком (task.edit_desc)")


def create_manual_task(conn, story_id: int, payload: dict) -> tuple[bool, str]:
    """Ручная задача Story (канон порции F): карточка + запись в БД. Пишет демон."""
    title = str(payload.get("title") or "").strip()
    if not title:
        return False, "нужен title"
    systems = [r["name"] for r in conn.execute(
        "SELECT name FROM story_systems WHERE story_id=?", (story_id,))]
    system = payload.get("system") or (systems[0] if systems else None)
    if systems and system not in systems:
        return False, f"система '{system}' не объявлена"
    deps = [str(d) for d in (payload.get("depends_on") or [])]
    known = {r["tid"] for r in conn.execute("SELECT tid FROM tasks WHERE story_id=?",
                                            (story_id,))}
    unknown = [d for d in deps if d not in known]
    if unknown:
        return False, f"неизвестные зависимости: {unknown}"
    story = conn.execute("SELECT epic_branch FROM stories WHERE id=?", (story_id,)).fetchone()
    spec = {
        "title": title,
        "description": str(payload.get("description") or "").strip()[:300],
        "system": system,
        "depends_on": deps,
        "fr_ids": payload.get("fr_ids") or [],
        "acceptance_criteria": [
            {"id": None, "desc": str(a).strip()[:200]}
            for a in (payload.get("acceptance") or [title])
        ],
    }
    tid = dbmod.task_create(conn, story_id, spec, origin="manual")
    with dbmod.tx(conn):
        conn.execute("UPDATE tasks SET pipeline='PROPOSED' WHERE story_id=? AND tid=?",
                     (story_id, tid))
        slug = (story["epic_branch"] or "task").rsplit("-", 1)[0]
        conn.execute("UPDATE tasks SET branch=? WHERE story_id=? AND tid=?",
                     (f"{slug}-{tid.lower()}", story_id, tid))
        if not (payload.get("acceptance") or []):
            pass
        else:
            conn.execute("DELETE FROM acceptance_criteria WHERE story_id=? AND tid=?",
                         (story_id, tid))
            for i, a in enumerate(payload.get("acceptance") or [], 1):
                conn.execute(
                    "INSERT INTO acceptance_criteria(story_id, tid, ac_id, seq, desc_md,"
                    " status) VALUES (?,?,?,?,?,'PENDING')",
                    (story_id, tid, f"AC-{tid[1:]}.{i}", i, str(a).strip()[:200]))
    ac_rows = "\n".join(f"| AC-{tid[1:]}.{i} | {a} | — |"
                        for i, a in enumerate(payload.get("acceptance") or [title], 1))
    card = (f"# {tid}: {title}\n\n| Поле | Значение |\n|------|----------|\n"
            f"| Система | {system} |\n| Фаза | regular |\n| Происхождение | вручную (Story UI) |\n"
            f"| Зависимости | {', '.join(deps) or '—'} |\n\n## Что сделать\n\n"
            f"{payload.get('description') or title}\n\n## Критерии приёмки\n\n"
            f"| AC | Условие | Тест |\n|----|---------|------|\n{ac_rows}\n")
    dbmod.task_set_card(conn, story_id, tid, card)
    cmt(conn, story_id, tid,
        "**Задача добавлена вручную** через витрину Story — статус «Предложена»: "
        "Steward проведёт декомпозицию (полная постановка + чек-лист), "
        "затем задача попадёт в бэклог.")
    ev(conn, story_id, tid, f"{tid}: создана вручную человеком: {title}")
    return True, tid


# --- цикл по воркспейсу ----------------------------------------------------

class WorkspaceLane:
    """Слот исполнения: одна живая стадия на проект (канон v3)."""

    def __init__(self, root: Path, conn, project_id: int, name: str) -> None:
        self.root = root
        self.conn = conn
        self.project_id = project_id
        self.name = name
        self.proc = None
        self.session_row: int | None = None
        self.log_path: Path | None = None
        self.story_id: int | None = None
        self.fnr: str | None = None
        self.hdir: Path | None = None
        self.task_id: str | None = None
        self.stage: str | None = None
        self.started_at = 0.0


def _beat_age(conn, session_row: int | None, started_at: float) -> float:
    if session_row is not None:
        row = conn.execute("SELECT last_beat_at FROM sessions WHERE id=?",
                           (session_row,)).fetchone()
        if row and row["last_beat_at"]:
            try:
                from datetime import datetime
                return time.time() - datetime.fromisoformat(
                    row["last_beat_at"]).timestamp()
            except ValueError:
                pass
    return time.time() - started_at


def process_workspace(lane: WorkspaceLane, opts: argparse.Namespace) -> None:
    """Один тик по проекту: reconcile осиротевших → стадия → решения."""
    conn = lane.conn
    ws = lane.root

    # 0. осиротевшие сессии прошлых запусков демона: pid мёртв → reconcile
    for s in conn.execute("SELECT id, story_id, tid, stage, pid, log_path FROM sessions"
                          " WHERE status='running'").fetchall():
        if lane.session_row is not None and s["id"] == lane.session_row:
            continue
        try:
            alive = pid_alive(int(s["pid"] or 0))
        except (TypeError, ValueError):
            alive = False
        if alive:
            continue  # чужая живая сессия — fencing (decide получит orphan_running)
        usage = _pick_usage(Path(s["log_path"]))
        dbmod.session_finish(conn, s["id"], -1, status="orphan", usage=usage,
                             claude_session_id=_pick_session_id(Path(s["log_path"])))
        if s["tid"] and s["stage"] in ("implementing", "review"):
            summary = reconcile_after_stage(conn, s["story_id"], s["tid"], -1,
                                            max_retries=opts.max_retries)
            print(f"  [orphan] {summary}")

    # 1. текущая стадия слота: живость, watchdog, завершение
    if lane.proc is not None:
        code = lane.proc.poll()
        quiet_for = _beat_age(conn, lane.session_row, lane.started_at)
        if code is None and quiet_for > opts.heartbeat_timeout:
            print(f"  [watchdog] тишина {int(quiet_for)}с > {opts.heartbeat_timeout}с — "
                  f"убиваю стадию {lane.stage} {lane.task_id}")
            _kill_tree(lane.proc)
            code = lane.proc.wait(timeout=30)
        if code is None:
            if time.time() - lane.started_at > opts.stage_timeout:
                print(f"  [watchdog] stage_timeout — убиваю {lane.stage} {lane.task_id}")
                _kill_tree(lane.proc)
                code = lane.proc.wait(timeout=30)
            else:
                return  # стадия работает (один писатель домена сессии)
        # стадия завершилась
        usage = _pick_usage(lane.log_path)
        csid = _pick_session_id(lane.log_path)
        dbmod.session_finish(conn, lane.session_row, code,
                             status="finished" if code == 0 else "killed",
                             usage=usage, claude_session_id=csid)
        sid = lane.story_id
        if lane.task_id and csid:
            # session_id последней сессии задачи — чат через claude --resume
            dbmod.task_set_v3(conn, sid, lane.task_id, {"session_id": csid})
        fnr = lane.fnr
        if lane.stage == "handoff":
            n_tasks = conn.execute("SELECT COUNT(*) c FROM tasks WHERE story_id=?",
                                   (sid,)).fetchone()["c"]
            story = conn.execute("SELECT status FROM stories WHERE id=?", (sid,)).fetchone()
            if n_tasks:
                if story["status"] in ("PENDING_HANDOFF", "PLANNED"):
                    dbmod.story_set_status(conn, sid, "AWAITING_APPROVAL", by="daemon") \
                        if story["status"] == "PLANNED" else None
                    with dbmod.tx(conn):
                        conn.execute("UPDATE stories SET status='AWAITING_APPROVAL',"
                                     " updated_at=? WHERE id=? AND status='PLANNED'",
                                     (now_iso(), sid))
                ev(conn, sid, None, "Story готова: план построен, ждёт утверждения "
                                    "(команда APPROVE_PLAN)")
                print(f"  [handoff] {fnr}: план готов — ждёт утверждения")
            else:
                with dbmod.tx(conn):
                    conn.execute(
                        "INSERT INTO meta(key, value) VALUES (?,?)"
                        " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (f"handoff_failed:{sid}", now_iso()))
                ev(conn, sid, None, "handoff завершился без плана — gap-report в "
                                    "handoff_report.md, требуется доработка СТ")
                print(f"  [handoff] {fnr}: STOP — см. handoff_report")
        elif lane.stage == "verify":
            if dbmod.doc_get(conn, sid, "verification_report") is not None:
                for t in conn.execute("SELECT tid FROM tasks WHERE story_id=?"
                                      " AND pipeline='DONE'", (sid,)).fetchall():
                    apply_transition(conn, sid, t["tid"], sm.EV_VERIFY_PASSED,
                                     "verification_report готов")
                print(f"  [verify] {fnr}: задачи → VERIFIED")
            else:
                with dbmod.tx(conn):
                    conn.execute(
                        "INSERT INTO meta(key, value) VALUES (?,?)"
                        " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (f"verify_attempted:{sid}", now_iso()))
                ev(conn, sid, None, "verify завершился без verification_report")
        elif lane.task_id:
            summary = reconcile_after_stage(conn, sid, lane.task_id, code,
                                            max_retries=opts.max_retries)
            print(f"  [stage] {summary}")
        try:
            if lane.proc and lane.proc.stdout:
                lane.proc.stdout.close()
        except OSError:
            pass
        lane.proc = lane.session_row = lane.log_path = None
        lane.story_id = lane.fnr = lane.hdir = lane.task_id = lane.stage = None
        return

    # 2. Story в ожидании handoff (созданы из витрины)
    for s in conn.execute("SELECT id, fnr FROM stories WHERE project_id=? AND"
                          " status='PENDING_HANDOFF' ORDER BY id",
                          (lane.project_id,)).fetchall():
        sid, fnr = int(s["id"]), s["fnr"]
        hdir = ws / "sa_documentation" / "FNR" / fnr / "harness"
        if not claim_lock(hdir):
            continue
        print(f"  [{fnr}] стадия handoff: построение плана из СТ")
        ev(conn, sid, None, "запуск стадии handoff: /impl-handoff")
        spawned = spawn_stage(ws, hdir, None, "handoff", opts, sid, conn)
        if spawned is not None:
            lane.proc, lane.session_row, lane.log_path = spawned
            lane.story_id, lane.fnr, lane.hdir = sid, fnr, hdir
            lane.task_id, lane.stage = None, "handoff"
            lane.started_at = time.time()
            return
        break  # dry-run

    # 3. перебор Story: свободный слот — ищем работу
    for s in conn.execute("SELECT id, fnr, status FROM stories WHERE project_id=?"
                          " AND status != 'PENDING_HANDOFF' ORDER BY id",
                          (lane.project_id,)).fetchall():
        sid, fnr = int(s["id"]), s["fnr"]
        hdir = ws / "sa_documentation" / "FNR" / fnr / "harness"
        if not claim_lock(hdir):
            continue

        # команды тика: атомарное потребление (dry-run — только взгляд)
        if opts.dry_run:
            flags = set(dbmod.pending_flags_view(conn, sid))
        else:
            consumed = dbmod.consume_commands(conn, sid)
            flags = set()
            for cmd in consumed:
                if cmd["name"] == "task.edit_desc":
                    payload = cmd["payload"] or {}
                    apply_task_edit_desc(conn, sid, str(payload.get("task_id") or ""),
                                         payload)
                    continue
                if cmd["name"] == "task.new":
                    ok, info = create_manual_task(conn, sid, cmd["payload"] or {})
                    print(f"  [{fnr}] TASK_NEW: {'создана ' + info if ok else 'ОТКАЗ — ' + info}")
                    if not ok:
                        ev(conn, sid, None, f"TASK_NEW отклонён: {info}")
                    continue
                flags.add(cmd["name"])

        orphan_running = any(r["alive"] for r in dbmod.live_sessions(conn, sid))

        # self-heal: задача стоит в NEEDS_HUMAN, а вариантов Steward нет
        # (потеряны при миграции/сбое) — готовим заново
        if not opts.dry_run:
            for r in conn.execute("SELECT tid FROM tasks WHERE story_id=? AND"
                                  " pipeline='NEEDS_HUMAN'", (sid,)).fetchall():
                if dbmod.steward_options_get(conn, sid, r["tid"]) is None:
                    task = dbmod.read_task(conn, sid, r["tid"], with_card=False)
                    task["id"] = r["tid"]
                    threading.Thread(target=_steward_options, daemon=True,
                                     args=(conn, sid, r["tid"],
                                           task.get("blocked_reason") or "требуется решение")).start()
        has_report, verify_attempted = _verify_flags(conn, sid, ws, fnr)
        state = {
            "lane_free": True,
            "running_task_id": None,
            "now": time.time(),
            "verification_report": has_report,
            "verify_attempted": verify_attempted,
            "max_retries": opts.max_retries,
            "orphan_running": orphan_running,
        }
        decisions = decide(manifest_view(conn, sid), flags, state)

        if opts.dry_run:
            print(f"  [dry-run] {fnr}: flags={sorted(flags) or '—'} orphan={orphan_running}")
            for d in decisions:
                print(f"  [dry-run] {fnr}: {d}")
            continue

        for d in decisions:
            kind = d[0]
            if kind == "flag":
                pass  # команда уже погашена consume_commands
            elif kind == "set":
                _, tid, field, value = d
                dbmod.task_set_v3(conn, sid, tid, {field: value})
                ev(conn, sid, tid, f"{tid}: {field}={value} (команда задачи)")
                print(f"  [{fnr}] {tid}: {field}={value}")
            elif kind == "approve_plan":
                story = conn.execute("SELECT status FROM stories WHERE id=?",
                                     (sid,)).fetchone()
                if story["status"] == "AWAITING_APPROVAL":
                    with dbmod.tx(conn):
                        conn.execute("UPDATE stories SET status='APPROVED', updated_at=?"
                                     " WHERE id=?", (now_iso(), sid))
                    ev(conn, sid, None, "план утверждён (APPROVE_PLAN) — конвейер запущен")
                    print(f"  [{fnr}] план утверждён — конвейер запущен")
            elif kind == "event":
                _, tid, event, reason = d
                task = dbmod.read_task(conn, sid, tid, with_card=False)
                if event in (sm.EV_RETRY, sm.EV_RESUME_WORK) \
                        and task.get("v2_status") == "ESCALATED_BLOCKED":
                    # человек явно попросил повторить после circuit breaker:
                    # снимаем v2-эскалацию, иначе completion ре-эскалирует
                    # до старта новой сессии (кейс T7)
                    target = task.get("blocked_from") or "IMPLEMENTING"
                    v2 = "AGENT_REVIEW" if target == "REVIEW" else "APPROVED"
                    dbmod.task_set_v2(conn, sid, tid, {"status": v2})
                if event == sm.EV_RETRY:
                    dbmod.task_set_v3(conn, sid, tid, {"retry_after_ts": 0})
                if event in (sm.EV_REVIEW_CHANGES, sm.EV_REQUEST_CHANGES):
                    # доработка с чистым v2-статусом (канон v3)
                    dbmod.task_set_v2(conn, sid, tid, {"status": "APPROVED"})
                    dbmod.task_set_v3(conn, sid, tid, {"review_verdict": None})
                if event == sm.EV_IMPL_BLOCKED:
                    backoff = min(300 * (2 ** (task.get("retries") or 0)), 3600)
                    dbmod.task_set_v3(conn, sid, tid,
                                      {"retry_after_ts": time.time() + backoff})
                apply_transition(conn, sid, tid, event, reason)
            elif kind == "stage":
                _, tid, stage = d
                if opts.dry_run:
                    print(f"  [dry-run] {fnr}: стадия {stage} для {tid or 'FNR'}")
                    continue
                print(f"  [{fnr}] стадия {stage}: {tid or 'вся FNR'}")
                ev(conn, sid, tid, f"запуск стадии {stage}: {tid or 'FNR целиком'}")
                story = conn.execute("SELECT status FROM stories WHERE id=?",
                                     (sid,)).fetchone()
                if story["status"] == "APPROVED":
                    with dbmod.tx(conn):
                        conn.execute("UPDATE stories SET status='IN_PROGRESS',"
                                     " updated_at=? WHERE id=?", (now_iso(), sid))
                spawned = spawn_stage(ws, hdir, tid, stage, opts, sid, conn)
                if spawned is not None:
                    lane.proc, lane.session_row, lane.log_path = spawned
                    lane.story_id, lane.fnr, lane.hdir = sid, fnr, hdir
                    lane.task_id, lane.stage = tid, stage
                    lane.started_at = time.time()
                    return  # слот занят до конца стадии
            elif kind == "wait":
                if opts.dry_run or opts.verbose:
                    print(f"  [{fnr}] ожидание: {d[1]}")


# --- точка входа -----------------------------------------------------------

def load_lanes(conn, workspace: str | None, project_name: str | None = None,
               update_path: bool = True) -> list[WorkspaceLane]:
    if workspace:
        wsp = Path(workspace).resolve()
        name = project_name or wsp.name
        pid_row = dbmod.upsert_project(conn, name, str(wsp), update_path=update_path)
        row = dbmod.get_project(conn, name)
        # корень монтирования — то, что передано; канонический путь в БД не трогаем
        return [WorkspaceLane(wsp, conn, int(row["id"]), name)]
    lanes = []
    for p in dbmod.list_projects(conn):
        lanes.append(WorkspaceLane(Path(p["path"]), conn, int(p["id"]), p["name"]))
    if not lanes:
        print("Реестр проектов пуст: добавьте проект в витрине или укажите --workspace")
        sys.exit(2)
    return lanes


def main() -> int:
    parser = argparse.ArgumentParser(description="Демон-координатор AI Harness v3 (SQLite)")
    parser.add_argument("--workspace", help="корень воркспейса (иначе — проекты из БД)")
    parser.add_argument("--project-name", default=None,
                        help="имя проекта (контейнер: канонический путь в БД не меняется)")
    parser.add_argument("--poll-interval", type=int, default=5)
    parser.add_argument("--stage-timeout", type=int, default=7200)
    parser.add_argument("--heartbeat-timeout", type=int, default=1200)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--max-turns", type=int, default=400)
    parser.add_argument("--skip-permissions", action="store_true")
    parser.add_argument("--claude-bin", default="claude")
    parser.add_argument("--dry-run", action="store_true",
                        help="показывать решения, не спавнить claude и не писать в БД")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--once", action="store_true", help="один цикл и выход")
    parser.add_argument("--db", default=None, help="путь к БД (HARNESS_DB)")
    opts = parser.parse_args()
    conn = dbmod.connect(opts.db) if opts.db else dbmod.connect()
    lanes = load_lanes(conn, opts.workspace, (opts.project_name or None) or None,
                       update_path=not opts.workspace)
    print(f"Демон конвейера (SQLite): {len(lanes)} проект(ов), "
          f"poll={opts.poll_interval}с, dry-run={opts.dry_run}")
    try:
        while True:
            for lane in lanes:
                if lane.root.is_dir():
                    process_workspace(lane, opts)
                else:
                    print(f"  [warn] проект недоступен: {lane.root}")
            if opts.once:
                break
            time.sleep(opts.poll_interval)
    except KeyboardInterrupt:
        print("\nОстановка демона (текущая стадия НЕ прервана — она доработает сама; "
              "перезапуск подхватит её по sessions).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
