"""Демон-координатор конвейера v3 (handoff_pipeline_design.md §3.3).

Ведёт задачи FNR по машине состояний (state_machine.py) автономно: сам
запускает стадии реализации/ревью/верификации как headless-сессии claude CLI
(те же команды v2: /impl-run, /impl-review, /impl-verify), следит за
живостью (heartbeat + watchdog), перезапускает упавшие стадии с backoff и
ведёт журнал событий. Человек управляет флагами `.flags/` (сегодня —
APPROVE_PLAN и PAUSE; адресные кнопки задач — порция C) и витриной.

Ключевые решения:
  - Состояние целиком в файлах: manifest.json + .flags/ + .run/ (pid, heartbeat,
    stream-логи). Демон можно убить -9 — при старте он дозаминирует состояния
    (осиротевшая IMPLEMENTING/REVIEW без живого процесса → retry или эскалация).
  - Один писатель за раз: пока стадия задачи исполняется, демон НЕ пишет её
    манифест (только читает) — сессия-исполнитель владеет v2-полями; демон
    применяет переходы между стадиями. Это снимает гонку двух писателей.
  - Решения — чистая функция decide(): тестируется без спавна claude.
  - Реестр воркспейсов: `~/.sa-helper/workspaces.json` (общий с витриной,
    порция D) или явный `--workspace <путь>`.

Пример:
    python3 harness/orchestrator.py --workspace /path/to/workspace --once --dry-run

Только stdlib; кроссплатформенно (macOS/Linux и Windows Git Bash: `python`).
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
from runner import _kill_tree  # noqa: E402  (кроссплатформенный kill дерева)

IS_WINDOWS = os.name == "nt"
REGISTRY_PATH = Path.home() / ".sa-helper" / "workspaces.json"

# Стадии → команды v2 (промпты в .claude/commands воркспейса; cwd = корень воркспейса)
STAGE_COMMANDS = {
    "implementing": "/impl-run {harness} {task}",
    "review": "/impl-review {harness} {task}",
    "verify": "/impl-verify {harness}",
}
# Флаги задач витрины (порция C): TASK_<ID>_<ДЕЙСТВИЕ> в .flags/
TASK_FLAG_RE = re.compile(
    r"^TASK_(T\d+)_(REQUEST_CHANGES|FORCE_APPROVE|RETRY|RESUME_WORK|PAUSE|ABORT|SKIP_REVIEW)$")

# v2-статус → pipeline при миграции документа без поля pipeline
_V2_TO_PIPELINE = {
    "PLANNED": sm.BACKLOG, "APPROVED": sm.BACKLOG,
    "TDD_RED": sm.IMPLEMENTING, "TDD_GREEN": sm.IMPLEMENTING, "GATES": sm.IMPLEMENTING,
    "AGENT_REVIEW": sm.REVIEW, "DONE": sm.DONE,
    "ESCALATED_BLOCKED": sm.NEEDS_HUMAN, "ABORTED": sm.ABORTED,
}


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"


def log_event(harness: Path, message: str) -> None:
    """Append-only журнал событий: <harness>/logs/events.log."""
    logs = harness / "logs"
    logs.mkdir(exist_ok=True)
    line = f"- [{time.strftime('%Y-%m-%d %H:%M:%S')} | daemon] {message}\n"
    with (logs / "events.log").open("a", encoding="utf-8") as fh:
        fh.write(line)


def load_manifest(harness: Path) -> dict | None:
    """Читает манифест; None при отсутствии/битом JSON (атомарная запись даёт
    либо старый, либо новый документ — битый возможен только при чужой записи)."""
    try:
        return json.loads((harness / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save_manifest(harness: Path, doc: dict) -> None:
    """Атомарная запись (tmp + os.replace) — тот же протокол, что у агента."""
    target = harness / "manifest.json"
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, target)


def apply_transition(harness: Path, doc: dict, task: dict, event: str,
                     reason: str) -> bool:
    """Применить событие машины состояний и записать манифест. False при отказе."""
    result = sm.transition(task, event)
    if not result["ok"]:
        log_event(harness, f"{task.get('id')}: ОТКАЗ {event}: {result['error']}")
        return False
    task.update(result["patch"])
    task["pipeline_since"] = now_iso()
    doc["updated_at"] = now_iso()
    save_manifest(harness, doc)
    log_event(harness, f"{task.get('id')}: {event} → {task['pipeline']} ({reason})")
    return True


def migrate_task_pipeline(task: dict) -> bool:
    """v2-документ → v3: вывести pipeline из status (идемпотентно)."""
    if task.get("pipeline") in sm.PIPELINE_STATUSES:
        return False
    task["pipeline"] = _V2_TO_PIPELINE.get(task.get("status"), sm.BACKLOG)
    task.setdefault("retries", 0)
    task.setdefault("review_iterations", 0)
    task.setdefault("skip_review", False)
    task.setdefault("paused", False)
    return True


def deps_done(task: dict, tasks_by_id: dict) -> bool:
    return all(
        (tasks_by_id.get(d) or {}).get("pipeline") in (sm.DONE, sm.VERIFIED)
        for d in (task.get("depends_on") or [])
    )


def completion_events(task: dict, review_iterations_max: int = 3) -> list[tuple[str, str]]:
    """События завершения стадии по факту в манифесте.

    Вызывается, когда процесса стадии нет (осиротевшая задача после падения
    демона или завершившаяся сессия): манифест говорит, чем всё кончилось.
    Пустой список — стадия не завершена (тогда смотрим orphan/relaunch).
    """
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


def reconcile_review(harness: Path, doc: dict, task: dict,
                     review_iterations_max: int = 3) -> str | None:
    """Ревью-петля: приоритет — машиночитаемый вердикт (review_gate), затем
    v2-поля манифеста. None — вердикта ещё нет (сессия не добралась)."""
    tid = task["id"]
    verdict_md = None
    for candidate in sorted((harness / "reviews").glob(f"{tid}_*.md")):
        verdict_md = candidate.read_text(encoding="utf-8", errors="replace")
    parsed = rg.parse_review_verdict(verdict_md)
    if parsed is not None:
        strategy = doc.get("auto_review_strategy", "closure_first")
        gate = rg.review_gate(task, parsed, strategy=strategy,
                              review_iterations_max=review_iterations_max)
        task["review_verdict"] = parsed["status"]
        task["findings"] = gate["findings"]
        apply_transition(harness, doc, task, gate["event"], gate["reason"])
        return gate["reason"]
    # фолбэк: старый формат (только v2-поля) — без findings
    events = completion_events(task, review_iterations_max)
    if events:
        event, reason = events[0]
        apply_transition(harness, doc, task, event, reason)
        return reason
    return None


def task_flags_decisions(manifest: dict, flags: set[str]) -> list[tuple]:
    """Адресные события задач из .flags/TASK_<ID>_<ДЕЙСТВИЕ>.

    Возвращает решения (флаг съедается всегда; нелегальный переход откажет
    машина состояний с журналированием). PAUSE/RESUME_WORK/SKIP_REVIEW —
    setters полей задачи, не переходы.
    """
    decisions: list[tuple] = []
    by_id = {t.get("id"): t for t in manifest.get("tasks", [])}
    for name in sorted(flags):
        match = TASK_FLAG_RE.match(name)
        if not match:
            continue
        tid, action = match.groups()
        task = by_id.get(tid)
        if task is None:
            continue  # флаг на несуществующую задачу — игнорируем содержимое
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
        else:
            event = {"REQUEST_CHANGES": sm.EV_REQUEST_CHANGES,
                     "FORCE_APPROVE": sm.EV_FORCE_APPROVE,
                     "ABORT": sm.EV_ABORT}[action]
            decisions.append(("event", tid, event, f"флаг {name}"))
    return decisions


# --- чистое ядро решений (тестируется без спавна claude) ----------------

def decide(manifest: dict, flags: set[str], state: dict) -> list[tuple]:
    """Решения одного тика по одному FNR.

    state: {"lane_free": bool, "running_task_id": str|None, "now": float,
            "verification_report": bool, "verify_attempted": bool,
            "orphan_running": bool, "max_retries": int}
    Возвращает список решений:
      ("event", task_id, event, reason)   — переход машины состояний;
      ("stage", task_id, stage)           — запустить стадию;
      ("flag", name)                      — потребить флаг (манифест уже учтён);
      ("approve_plan",)                   — статус манифеста → APPROVED;
      ("wait", reason)                    — ничего не делать (для журнала/сухого прогона).
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

    # адресные события задач (порция C): отдельный тик — решения по свежему манифесту
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
        lane_free = bool(state.get("lane_free")) and not running  # слот мог занять сосед
        if task.get("paused"):
            continue

        if pipeline == sm.BACKLOG and deps_done(task, by_id):
            decisions.append(("event", tid, sm.EV_QUEUE_READY, "зависимости закрыты"))
            pipeline = sm.READY  # локально: без мутации задачи (валидация — в transition)

        if pipeline == sm.BLOCKED:
            if state["now"] < float(task.get("retry_after_ts") or 0):
                continue
            if (task.get("retries") or 0) >= state.get("max_retries", 3):
                decisions.append(("event", tid, sm.EV_BLOCKED_ESCALATED,
                                  f"retries={task.get('retries')} — исчерпаны"))
            else:
                decisions.append(("event", tid, sm.EV_RETRY,
                                  f"backoff истёк (retries={task.get('retries')})"))
                pipeline = task.get("blocked_from") or sm.IMPLEMENTING  # локально
            # падаем ниже: RETRY вернул задачу в IMPLEMENTING — слот перезапустит стадию

        if pipeline in (sm.IMPLEMENTING, sm.REVIEW):
            done_events = completion_events(task)
            if done_events:
                decisions.append(("event", tid, *done_events[0]))
                continue
            if state.get("orphan_running"):
                continue  # чужая сессия ещё жива — не влезаем (fencing)
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


def reconcile_after_stage(harness: Path, doc: dict, task: dict,
                          exit_code: int, max_retries: int = 3,
                          review_iterations_max: int = 3) -> str:
    """Перевод задачи после завершения стадии по факту в манифесте.

    Возвращает человекочитаемое резюме. Вызывается, когда процесса стадии
    уже нет — манифест принадлежит демону, гонки нет.
    """
    tid = task["id"]
    if task.get("pipeline") == sm.REVIEW:
        reason = reconcile_review(harness, doc, task,
                                  review_iterations_max=review_iterations_max)
        if reason:
            return f"{tid}: {reason} → {task['pipeline']}"
        # вердикта ещё нет — сессия прервана до вердикта
        apply_transition(harness, doc, task, sm.EV_IMPL_BLOCKED,
                         f"сессия ревью прервана без вердикта (exit={exit_code})")
        task["retry_after_ts"] = time.time() + min(300 * (2 ** (task.get("retries") or 0)), 3600)
        save_manifest(harness, doc)
        return f"{tid}: сессия ревью прервана → BLOCKED"

    events = completion_events(task, review_iterations_max)
    if events:
        event, reason = events[0]
        apply_transition(harness, doc, task, event, reason)
        label = {
            sm.EV_IMPL_PASSED: "реализация завершена",
            sm.EV_IMPL_ESCALATED: "эскалация circuit breaker",
        }.get(event, event)
        return f"{tid}: {label} → {task['pipeline']}"

    # стадия не доведена до конца (сессия прервана) — retry с backoff
    apply_transition(harness, doc, task, sm.EV_IMPL_BLOCKED,
                     f"сессия прервана (exit={exit_code}, status={task.get('status')})")
    task["retry_after_ts"] = time.time() + min(300 * (2 ** (task.get("retries") or 0)), 3600)
    save_manifest(harness, doc)
    if (task.get("retries") or 0) > max_retries:
        apply_transition(harness, doc, task, sm.EV_BLOCKED_ESCALATED,
                         f"retries={task['retries']} — исчерпаны")
        return f"{tid}: сессия прервана, retries исчерпаны → NEEDS_HUMAN"
    return f"{tid}: сессия прервана → BLOCKED (retry #{task['retries']} по backoff)"


# --- исполнение стадий ---------------------------------------------------

def claude_command(args: list[str], skip_permissions: bool,
                   claude_bin: str = "claude") -> list[str]:
    base = [claude_bin, *args, "--output-format", "stream-json", "--verbose"]
    base += ["--dangerously-skip-permissions"] if skip_permissions \
        else ["--permission-mode", "acceptEdits"]
    return base


def spawn_stage(workspace: Path, harness: Path, task_id: str | None, stage: str,
                opts: argparse.Namespace) -> subprocess.Popen:
    """Запуск headless-сессии стадии; стрим → .run/, heartbeat → .run/*.hb."""
    rel = Path(os.path.relpath(harness, workspace)).as_posix()
    template = STAGE_COMMANDS[stage]
    prompt = template.format(harness=rel, task=task_id) if task_id \
        else template.format(harness=rel)
    run_dir = harness / ".run"
    run_dir.mkdir(exist_ok=True)
    suffix = task_id or "fnr"
    log_path = run_dir / f"{suffix}_{stage}_{int(time.time())}.log"
    hb_path = run_dir / f"{suffix}_{stage}.hb"

    args = claude_command(["-p", prompt, "--max-turns", str(opts.max_turns)],
                          opts.skip_permissions, getattr(opts, "claude_bin", "claude"))
    if opts.dry_run:
        print(f"  [dry-run] cwd={workspace} лог={log_path.name}\n  [dry-run] {' '.join(args)}")
        return None

    kwargs: dict = {"cwd": str(workspace), "stdin": subprocess.DEVNULL}
    if IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    stdout_fh = open(log_path, "wb")  # ребёнок пишет напрямую в лог стадии
    try:
        proc = subprocess.Popen(args, stdout=stdout_fh, stderr=subprocess.STDOUT, **kwargs)
    finally:
        stdout_fh.close()  # fd dup'нут в ребёнка; родительская копия не нужна
    hb_path.write_text(str(int(time.time())), encoding="utf-8")
    (run_dir / f"{suffix}_{stage}.pid").write_text(str(proc.pid), encoding="utf-8")
    threading.Thread(target=_stream_watch, args=(log_path, hb_path, proc),
                     daemon=True).start()
    return proc


def _stream_watch(log_path: Path, hb_path: Path, proc: subprocess.Popen) -> None:
    """Живость стадии: stream-лог растёт → обновить heartbeat-файл.

    Отдельная нать вместо чтения stdout: дескриптор открыт на запись (ребёнок
    пишет в него напрямую), читать его нельзя. По завершении процесса закрывает
    дескриптор stdout, который держит Popen.
    """
    size = -1
    while proc.poll() is None:
        try:
            current = log_path.stat().st_size
        except OSError:
            current = -1
        if current != size:
            size = current
            try:
                hb_path.write_text(str(int(time.time())), encoding="utf-8")
            except OSError:
                return
        time.sleep(1.0)
    try:
        if proc.stdout:
            proc.stdout.close()
    except OSError:
        pass


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


def claim_lock(harness: Path) -> bool:
    """Пер-воркспейсный лок демона: .run/daemon.lock (pid). Мёртвый лок — берём."""
    lock = harness / ".run" / "daemon.lock"
    lock.parent.mkdir(exist_ok=True)
    if lock.exists():
        try:
            old = int(lock.read_text(encoding="utf-8").strip() or 0)
            if old != os.getpid() and pid_alive(old):
                return False
        except (OSError, ValueError):
            pass
    lock.write_text(str(os.getpid()), encoding="utf-8")
    return True


# --- цикл по воркспейсу --------------------------------------------------

class WorkspaceLane:
    """Состояние исполнения одного воркспейса: текущая стадия и её процесс."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.proc: subprocess.Popen | None = None
        self.harness: Path | None = None
        self.task_id: str | None = None
        self.stage: str | None = None
        self.started_at = 0.0


def find_harnesses(workspace: Path) -> list[Path]:
    return sorted(p for p in workspace.glob("sa_documentation/FNR/FNR_*/harness")
                  if (p / "manifest.json").is_file())


def process_workspace(lane: WorkspaceLane, opts: argparse.Namespace) -> None:
    """Один тик по воркспейсу: reconcile → решения → стадии."""
    ws = lane.root

    # 1. текущая стадия: живость, watchdog, завершение
    if lane.proc is not None:
        code = lane.proc.poll()
        hb = lane.harness / ".run" / f"{lane.task_id or 'fnr'}_{lane.stage}.hb"
        quiet_for = time.time() - (hb.stat().st_mtime if hb.exists() else lane.started_at)
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
                return  # стадия ещё работает, манифест не трогаем (один писатель)
        # стадия завершилась — reconcile и освободить слот
        harness, task_id, stage = lane.harness, lane.task_id, lane.stage
        if stage == "verify":
            report = harness / "verification_report.md"
            if report.exists():
                doc = load_manifest(harness)
                for t in doc.get("tasks", []):
                    if t.get("pipeline") == sm.DONE:
                        apply_transition(harness, doc, t, sm.EV_VERIFY_PASSED,
                                         "verification_report готов")
                print(f"  [verify] {harness.parent.name}: задачи → VERIFIED")
            else:
                (harness / ".run" / "verify_attempted").write_text(now_iso(), encoding="utf-8")
                log_event(harness, "verify завершился без verification_report.md")
        else:
            doc = load_manifest(harness)
            task = next((t for t in doc.get("tasks", []) if t.get("id") == task_id), None)
            if task:
                summary = reconcile_after_stage(harness, doc, task, code,
                                                max_retries=opts.max_retries)
                print(f"  [stage] {summary}")
        try:
            if lane.proc and lane.proc.stdout:
                lane.proc.stdout.close()
        except OSError:
            pass
        lane.proc = lane.harness = lane.task_id = lane.stage = None
        return

    # 2. перебор FNR: свободный слот — ищем работу
    for harness in find_harnesses(ws):
        if not claim_lock(harness):
            continue
        doc = load_manifest(harness)
        if doc is None:
            continue
        flags_dir = harness / ".flags"
        flags = {p.name for p in flags_dir.glob("*")} if flags_dir.is_dir() else set()
        run_dir = harness / ".run"

        # fencing: живые pid-файлы осиротевших сессий (после kill -9 демона) —
        # чужая сессия ещё пишет манифест, демону входить нельзя
        orphan_running = False
        if run_dir.is_dir():
            for pid_file in run_dir.glob("*.pid"):
                try:
                    if pid_alive(int(pid_file.read_text(encoding="utf-8").strip())):
                        orphan_running = True
                        break
                except (OSError, ValueError):
                    continue

        state = {
            "lane_free": True,
            "running_task_id": None,
            "now": time.time(),
            "verification_report": (harness / "verification_report.md").exists(),
            "verify_attempted": (run_dir / "verify_attempted").exists(),
            "max_retries": opts.max_retries,
            "orphan_running": orphan_running,
        }
        decisions = decide(doc, flags, state)

        if opts.dry_run:
            # сухой прогон полностью read-only: только показать решения
            fnr = harness.parent.name
            print(f"  [dry-run] {fnr}: flags={sorted(flags) or '—'} "
                  f"orphan={orphan_running}")
            for d in decisions:
                print(f"  [dry-run] {fnr}: {d}")
            continue

        for d in decisions:
            kind = d[0]
            if kind == "flag":
                try:
                    (flags_dir / d[1]).unlink()
                except OSError:
                    pass
            elif kind == "set":
                _, tid, field, value = d
                task = next(t for t in doc["tasks"] if t["id"] == tid)
                task[field] = value
                doc["updated_at"] = now_iso()
                save_manifest(harness, doc)
                log_event(harness, f"{tid}: {field}={value} (флаг задачи)")
                print(f"  [{harness.parent.name}] {tid}: {field}={value}")
            elif kind == "approve_plan":
                if doc.get("status") == "AWAITING_APPROVAL":
                    doc["status"] = "APPROVED"
                    save_manifest(harness, doc)
                    log_event(harness, "план утверждён (APPROVE_PLAN) — конвейер запущен")
                    print(f"  [{harness.parent.name}] план утверждён — конвейер запущен")
            elif kind == "event":
                _, tid, event, reason = d
                task = next(t for t in doc["tasks"] if t["id"] == tid)
                if event == sm.EV_RETRY:
                    task["retry_after_ts"] = 0
                if event == sm.EV_IMPL_BLOCKED:
                    backoff = min(300 * (2 ** (task.get("retries") or 0)), 3600)
                    task["retry_after_ts"] = time.time() + backoff
                if event in (sm.EV_REVIEW_CHANGES, sm.EV_REQUEST_CHANGES):
                    # доработка начинается с чистым v2-статусом — иначе completion
                    # по DONE/AGENT_REVIEW ложно закроет задачу до старта сессии
                    task["status"] = "APPROVED"
                    task["review_verdict"] = None
                apply_transition(harness, doc, task, event, reason)
            elif kind == "stage":
                _, tid, stage = d
                fnr = harness.parent.name
                if opts.dry_run:
                    print(f"  [dry-run] {fnr}: стадия {stage} для {tid or 'FNR'}")
                    spawn_stage(ws, harness, tid, stage, opts)
                    continue
                print(f"  [{fnr}] стадия {stage}: {tid or 'вся FNR'}")
                log_event(harness, f"запуск стадии {stage}: {tid or 'FNR целиком'}")
                if doc.get("status") in ("APPROVED",):
                    doc["status"] = "IN_PROGRESS"
                    save_manifest(harness, doc)
                proc = spawn_stage(ws, harness, tid, stage, opts)
                if proc is not None:
                    lane.proc, lane.harness = proc, harness
                    lane.task_id, lane.stage = tid, stage
                    lane.started_at = time.time()
                    return  # слот занят до конца стадии
            elif kind == "wait":
                if opts.dry_run or opts.verbose:
                    print(f"  [{harness.parent.name}] ожидание: {d[1]}")


# --- точка входа ---------------------------------------------------------

def load_workspaces(arg: str | None) -> list[Path]:
    if arg:
        return [Path(arg).resolve()]
    if REGISTRY_PATH.is_file():
        try:
            data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
            items = data.get("workspaces", data) if isinstance(data, dict) else data
            return [Path(i["path"]).resolve() for i in items if isinstance(i, dict)]
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            pass
    print(f"Реестр воркспейсов не найден: {REGISTRY_PATH}\n"
          f"Укажите --workspace <путь> или создайте реестр "
          f'{{"workspaces": [{{"name": "...", "path": "..."}}]}}')
    sys.exit(2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Демон-координатор AI Harness v3")
    parser.add_argument("--workspace", help="корень воркспейса (иначе — реестр)")
    parser.add_argument("--poll-interval", type=int, default=5)
    parser.add_argument("--stage-timeout", type=int, default=7200,
                        help="максимальная длительность стадии, с")
    parser.add_argument("--heartbeat-timeout", type=int, default=1200,
                        help="максимальная тишина stream-лога, с")
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--max-turns", type=int, default=400)
    parser.add_argument("--skip-permissions", action="store_true",
                        help="--dangerously-skip-permissions (иначе acceptEdits+allowlist)")
    parser.add_argument("--claude-bin", default="claude",
                        help="путь к бинарю claude (по умолчанию — из PATH; для smoke-тестов)")
    parser.add_argument("--dry-run", action="store_true",
                        help="показывать решения, не спавнить claude и не писать манифесты")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--once", action="store_true", help="один цикл и выход")
    opts = parser.parse_args()

    workspaces = load_workspaces(opts.workspace)
    lanes = [WorkspaceLane(w) for w in workspaces]
    print(f"Демон конвейера: {len(lanes)} воркспейс(ов), "
          f"poll={opts.poll_interval}с, dry-run={opts.dry_run}")
    try:
        while True:
            for lane in lanes:
                if lane.root.is_dir():
                    process_workspace(lane, opts)
                else:
                    print(f"  [warn] воркспейс недоступен: {lane.root}")
            if opts.once:
                break
            time.sleep(opts.poll_interval)
    except KeyboardInterrupt:
        print("\nОстановка демона (текущая стадия НЕ прервана — она доработает сама; "
              "перезапуск подхватит её по манифесту).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
