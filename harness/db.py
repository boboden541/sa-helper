"""Слой доступа к БД витрины AI-harness (SQLite, stdlib; порция R1).

Единственное место, где живёт схема и SQL. Демон и сервер ходят напрямую;
адаптер агентов (sahelper.py, R4) использует те же функции с ролью «session» —
владение доменами обеспечивается гранулярностью функций:
  task_set_v2 — только колонки сессии; task_set_v3 — только демона.
"""

from __future__ import annotations

import os
import json
import re
import sqlite3
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

sys_path = str(Path(__file__).resolve().parent)
if sys_path not in __import__("sys").path:
    __import__("sys").path.insert(0, sys_path)
import state_machine as sm  # noqa: E402
import cards  # noqa: E402

DB_PATH_DEFAULT = Path.home() / ".sa-helper" / "harness.db"

SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta(
  key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS projects(
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  path TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stories(
  id INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  fnr TEXT NOT NULL,
  story_title TEXT,
  source_md TEXT,                        -- СТ: markdown-контент [H]
  source_name TEXT,
  status TEXT NOT NULL DEFAULT 'PENDING_HANDOFF' CHECK(status IN
    ('PENDING_HANDOFF','PLANNED','AWAITING_APPROVAL','APPROVED','IN_PROGRESS','COMPLETED','ABORTED')),
  epic_branch TEXT,                      -- [S]
  workspace TEXT,                        -- [S]
  active_task_id TEXT,                   -- [D]
  circuit_breaker_max INTEGER NOT NULL DEFAULT 4,
  auto_mode INTEGER NOT NULL DEFAULT 0,  -- [S]
  auto_review_strategy TEXT NOT NULL DEFAULT 'closure_first'
    CHECK(auto_review_strategy IN ('closure_first','full_re_review')),  -- [S]
  paused INTEGER NOT NULL DEFAULT 0,     -- [H] глобальный PAUSE — состояние Story
  created_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(project_id, fnr)
);

CREATE TABLE IF NOT EXISTS story_systems(
  story_id INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  path TEXT,
  stack TEXT,
  preset TEXT,
  data_only INTEGER NOT NULL DEFAULT 0,
  bootstrap TEXT CHECK(bootstrap IS NULL OR bootstrap IN
    ('ready','ready_with_notes','stop','ready_data_only')),
  build_cmd TEXT, test_cmd TEXT, lint_cmd TEXT, tests TEXT, guidelines TEXT,
  PRIMARY KEY(story_id, name)
);

CREATE TABLE IF NOT EXISTS tasks(
  id INTEGER PRIMARY KEY,
  story_id INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
  tid TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT,                      -- проза-постановка [S-create/D-edit]
  system TEXT,
  phase TEXT NOT NULL DEFAULT 'regular' CHECK(phase IN
    ('regular','contract','producer','consumer','characterization')),
  branch TEXT, worktree TEXT,
  v2_status TEXT NOT NULL DEFAULT 'PLANNED' CHECK(v2_status IN
    ('PLANNED','APPROVED','TDD_RED','TDD_GREEN','GATES','AGENT_REVIEW','DONE','ESCALATED_BLOCKED','ABORTED')),
  pipeline TEXT NOT NULL DEFAULT 'BACKLOG' CHECK(pipeline IN
    ('PROPOSED','BACKLOG','READY','IMPLEMENTING','REVIEW','DONE','VERIFIED','BLOCKED','NEEDS_HUMAN','ABORTED')),
  origin TEXT NOT NULL DEFAULT 'plan' CHECK(origin IN ('plan','manual','agent')),
  decomposed INTEGER NOT NULL DEFAULT 0,          -- [S-decompose]
  iteration_count INTEGER NOT NULL DEFAULT 0,     -- [S] circuit-breaker счётчик
  blocked_from TEXT, retries INTEGER NOT NULL DEFAULT 0, review_iterations INTEGER NOT NULL DEFAULT 0,
  retry_after_ts REAL, pipeline_since TEXT,
  paused INTEGER NOT NULL DEFAULT 0, skip_review INTEGER NOT NULL DEFAULT 0,
  owner TEXT CHECK(owner IS NULL OR owner IN ('ai','human')),
  session_id TEXT,                       -- [D]
  review_verdict TEXT,                   -- [D]
  blocked_reason TEXT,                   -- [D]
  card_md TEXT,
  card_version INTEGER NOT NULL DEFAULT 1,
  card_updated_at TEXT,
  usage_tokens_in INTEGER NOT NULL DEFAULT 0, usage_tokens_out INTEGER NOT NULL DEFAULT 0,
  usage_tokens_total INTEGER NOT NULL DEFAULT 0, usage_cost_usd REAL NOT NULL DEFAULT 0,
  usage_sessions INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(story_id, tid)
);
CREATE INDEX IF NOT EXISTS idx_tasks_story_pipeline ON tasks(story_id, pipeline);

CREATE TABLE IF NOT EXISTS acceptance_criteria(
  story_id INTEGER NOT NULL, tid TEXT NOT NULL,
  ac_id TEXT NOT NULL, seq INTEGER NOT NULL DEFAULT 0,
  desc_md TEXT NOT NULL, test TEXT,
  status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','PASSED','FAILED')),  -- [S]
  PRIMARY KEY(story_id, tid, ac_id),
  FOREIGN KEY(story_id, tid) REFERENCES tasks(story_id, tid) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS task_deps(                                  -- DAG
  story_id INTEGER NOT NULL, tid TEXT NOT NULL, dep_tid TEXT NOT NULL,
  PRIMARY KEY(story_id, tid, dep_tid),
  FOREIGN KEY(story_id, tid) REFERENCES tasks(story_id, tid) ON DELETE CASCADE,
  FOREIGN KEY(story_id, dep_tid) REFERENCES tasks(story_id, tid) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS task_frs(                                   -- fr_ids
  story_id INTEGER NOT NULL, tid TEXT NOT NULL, fr_id TEXT NOT NULL,
  PRIMARY KEY(story_id, tid, fr_id),
  FOREIGN KEY(story_id, tid) REFERENCES tasks(story_id, tid) ON delete CASCADE
);

CREATE TABLE IF NOT EXISTS gates(
  story_id INTEGER NOT NULL, tid TEXT NOT NULL,
  gate TEXT NOT NULL CHECK(gate IN ('build','test','lint','coverage','review')),
  state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN
    ('pending','running','passed','failed','skipped','changes_requested','partial')),   -- [S]
  detail TEXT, updated_at TEXT,
  PRIMARY KEY(story_id, tid, gate),
  FOREIGN KEY(story_id, tid) REFERENCES tasks(story_id, tid) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS findings(
  story_id INTEGER NOT NULL, tid TEXT NOT NULL, fid TEXT NOT NULL,   -- sha1_12 [D]
  text TEXT NOT NULL, file TEXT,
  resolution TEXT NOT NULL DEFAULT 'open' CHECK(resolution IN ('open','resolved','still_blocking')),
  updated_at TEXT,
  PRIMARY KEY(story_id, tid, fid),
  FOREIGN KEY(story_id, tid) REFERENCES tasks(story_id, tid) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS review_verdicts(
  id INTEGER PRIMARY KEY,
  story_id INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
  tid TEXT NOT NULL,
  iteration INTEGER NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('APPROVED','CHANGES_REQUESTED')),
  created_at TEXT NOT NULL,
  UNIQUE(story_id, tid, iteration)
);

CREATE TABLE IF NOT EXISTS verdict_items(
  verdict_id INTEGER NOT NULL REFERENCES review_verdicts(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK(kind IN ('blocking','advisory')),
  fid TEXT NOT NULL,
  file TEXT, text TEXT NOT NULL,
  PRIMARY KEY(verdict_id, kind, fid)
);

CREATE TABLE IF NOT EXISTS commands(
  id INTEGER PRIMARY KEY,
  story_id INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
  name TEXT NOT NULL,                    -- 'APPROVE_PLAN' | 'TASK_T3_RETRY' | 'task.new' | 'task.edit_desc'
  payload TEXT,                          -- JSON для payload-команд
  created_by TEXT NOT NULL DEFAULT 'human' CHECK(created_by IN ('human','agent','steward')),
  created_at TEXT NOT NULL,
  consumed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_commands_pending ON commands(story_id) WHERE consumed_at IS NULL;

CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,  -- глобальный курсор SSE
  story_id INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
  tid TEXT,
  ts TEXT NOT NULL,
  actor TEXT NOT NULL DEFAULT 'daemon' CHECK(actor IN
    ('daemon','session','human','server','steward')),
  kind TEXT,
  text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_story_id ON events(story_id, id);
CREATE INDEX IF NOT EXISTS idx_events_story_task ON events(story_id, tid, id);

CREATE TABLE IF NOT EXISTS comments(
  id INTEGER PRIMARY KEY,
  story_id INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
  tid TEXT,
  ts TEXT NOT NULL,
  author TEXT NOT NULL CHECK(author IN ('human','agent','daemon','reviewer','steward')),
  body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_comments_story_task ON comments(story_id, tid, id);

CREATE TABLE IF NOT EXISTS documents(
  id INTEGER PRIMARY KEY,
  story_id INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
  tid TEXT,
  kind TEXT NOT NULL,
  body_md TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(story_id, tid, kind)
);

CREATE TABLE IF NOT EXISTS sessions(
  id INTEGER PRIMARY KEY,
  story_id INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
  tid TEXT,
  stage TEXT NOT NULL CHECK(stage IN ('implementing','review','verify','handoff','decompose')),
  pid INTEGER, host TEXT,
  log_path TEXT NOT NULL,
  claude_session_id TEXT,
  status TEXT NOT NULL DEFAULT 'running' CHECK(status IN ('running','finished','killed','orphan')),
  started_at TEXT, last_beat_at TEXT, finished_at TEXT, exit_code INTEGER,
  tokens_in INTEGER, tokens_out INTEGER, tokens_total INTEGER, cost_usd REAL
);
CREATE INDEX IF NOT EXISTS idx_sessions_story_live ON sessions(story_id, status);

CREATE TABLE IF NOT EXISTS attachments(
  id INTEGER PRIMARY KEY,
  story_id INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
  tid TEXT NOT NULL,
  name TEXT NOT NULL,
  path TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(story_id, tid, name)
);

CREATE TABLE IF NOT EXISTS checklist_sections(
  id INTEGER PRIMARY KEY,
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'custom' CHECK(kind IN ('plan','review','custom')),
  seq INTEGER NOT NULL DEFAULT 0,
  note TEXT,
  updated_at TEXT NOT NULL,
  UNIQUE(task_id, title)
);
CREATE INDEX IF NOT EXISTS idx_chsec_task ON checklist_sections(task_id, seq);

CREATE TABLE IF NOT EXISTS checklist_items(
  id INTEGER PRIMARY KEY,
  section_id INTEGER NOT NULL REFERENCES checklist_sections(id) ON DELETE CASCADE,
  seq INTEGER NOT NULL DEFAULT 0,
  depth INTEGER NOT NULL DEFAULT 0,
  text_md TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'todo' CHECK(state IN
    ('todo','inprog','done','review','blocked','failed','skipped')),
  mandatory INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chitems_section ON checklist_items(section_id, seq);

CREATE TABLE IF NOT EXISTS steward_messages(
  id INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  ts TEXT NOT NULL,
  author TEXT NOT NULL CHECK(author IN ('human','steward')),
  body TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS steward_state(
  project_id INTEGER PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
  pending INTEGER NOT NULL DEFAULT 0, pending_text TEXT, session_id TEXT
);

CREATE TABLE IF NOT EXISTS steward_options(
  story_id INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
  tid TEXT NOT NULL, options_json TEXT NOT NULL, updated_at TEXT,
  PRIMARY KEY(story_id, tid)
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def db_path() -> Path:
    env = os.environ.get("HARNESS_DB")
    if env:
        return Path(env)
    env = os.environ.get("SAHELPER_HOME")
    base = Path(env) if env else Path.home() / ".sa-helper"
    return base / "harness.db"


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    """Соединение с прагмами и схемой. Один на поток (thread-local у клиента)."""
    p = Path(path) if path else db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=5.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None   # autocommit; транзакциями управляет только tx()
    # WAL — на локальной ФС хоста; в контейнерах поверх bind-mount WAL даёт
    # disk I/O error (общая -shm) — там журнальник DELETE (нагрузка мала)
    conn.execute(f"PRAGMA journal_mode={os.environ.get('HARNESS_JOURNAL', 'wal')}")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA_SQL)
    conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
                 (str(SCHEMA_VERSION),))
    ver = int(conn.execute(
        "SELECT value FROM meta WHERE key='schema_version'").fetchone()[0])
    if ver < 2:
        _migrate_checklists_v2(conn)
        conn.execute("UPDATE meta SET value='2' WHERE key='schema_version'")
    if ver < 3:
        try:
            conn.execute("ALTER TABLE checklist_items ADD COLUMN depth INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # колонка уже есть (свежая БД из SCHEMA_SQL)
        conn.execute("UPDATE meta SET value='3' WHERE key='schema_version'")
    conn.commit()
    return conn


def _migrate_checklists_v2(conn: sqlite3.Connection) -> None:
    """v1→v2: чек-лист-секции из card_md всех задач → таблицы checklist_*.

    Идемпотентно: card_md, в котором секций нет, не трогается. Заголовки
    сравниваются по префиксу контрактов («План работ (чек-лист)…» → plan,
    «Доработка по ревью (чек-лист)…» → review, суффикс — в note); пустые
    заголовки-двойники пропускаются.
    """
    import cards as _cards
    with tx(conn):
        for row in conn.execute("SELECT id, card_md FROM tasks"
                                " WHERE card_md LIKE '%чек-лист%'").fetchall():
            task_id, card_md = int(row["id"]), row["card_md"] or ""
            sections = _cards.parse_checklist_sections(card_md)
            if not sections:
                continue
            for sec in sections:
                title = sec["title"].strip()
                kind = "custom"
                canon = title
                if title.startswith("План работ (чек-лист)"):
                    kind, canon = "plan", "План работ (чек-лист)"
                elif title.startswith("Доработка по ревью (чек-лист)"):
                    kind, canon = "review", "Доработка по ревью (чек-лист)"
                note = title[len(canon):].strip(" —") or None
                if not sec["items"]:
                    continue  # пустой заголовок-двойник
                existing = conn.execute(
                    "SELECT id FROM checklist_sections WHERE task_id=? AND title=?",
                    (task_id, canon)).fetchone()
                if existing:
                    # дубликат заголовка (повторные декомпозиции) — дописываем
                    # пункты в существующую секцию
                    sec_id = int(existing["id"])
                    base = conn.execute("SELECT COALESCE(MAX(seq),0) FROM checklist_items"
                                        " WHERE section_id=?", (sec_id,)).fetchone()[0]
                    for i, it in enumerate(sec["items"], base + 1):
                        conn.execute(
                            "INSERT INTO checklist_items(section_id, seq, text_md, state,"
                            " mandatory, created_at, updated_at) VALUES (?,?,?,?,0,?,?)",
                            (sec_id, i, it["text"], it["state"], now_iso(), now_iso()))
                else:
                    n_sec = conn.execute("SELECT COUNT(*) c FROM checklist_sections"
                                         " WHERE task_id=?", (task_id,)).fetchone()["c"]
                    cur = conn.execute(
                        "INSERT INTO checklist_sections(task_id, title, kind, seq, note,"
                        " updated_at) VALUES (?,?,?,?,?,?)",
                        (task_id, canon, kind, n_sec, note, now_iso()))
                    sec_id = int(cur.lastrowid)
                    for i, it in enumerate(sec["items"], 1):
                        conn.execute(
                            "INSERT INTO checklist_items(section_id, seq, text_md, state,"
                            " mandatory, created_at, updated_at) VALUES (?,?,?,?,0,?,?)",
                            (sec_id, i, it["text"], it["state"], now_iso(), now_iso()))
            # вырезать чек-лист-секции из карточки
            new_md = _cut_checklist_sections(card_md)
            if new_md != card_md:
                conn.execute(
                    "UPDATE tasks SET card_md=?, card_version=card_version+1,"
                    " card_updated_at=? WHERE id=?",
                    (new_md, now_iso(), task_id))


def _cut_checklist_sections(card_md: str) -> str:
    """Удалить из card_md секции «## …чек-лист…» (с телом до следующего ##)."""
    lines = (card_md or "").splitlines()
    out: list[str] = []
    skipping = False
    for line in lines:
        if line.startswith("## "):
            skipping = "чек-лист" in line.lower()
            if skipping:
                continue
        if not skipping:
            out.append(line)
    text = "\n".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text).strip() + ("\n" if text.strip() else "")
    return text


@contextmanager
def tx(conn: sqlite3.Connection, immediate: bool = True):
    """Транзакция с retry на SQLITE_BUSY (короткие записи, конкурентные писатели)."""
    for attempt in range(3):
        try:
            conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
            return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc) and "busy" not in str(exc).lower():
                raise
            if attempt == 2:
                raise
            time.sleep(0.3 * (attempt + 1))


# ─── проекты ────────────────────────────────────────────────────────────────

def upsert_project(conn: sqlite3.Connection, name: str, path: str,
                   update_path: bool = True) -> int:
    """[H/M] Реестр проектов (поглощает workspaces.json). Ключи — и имя, и путь.

    update_path=False — контейнерный контур: канонический путь в БД остаётся
    хостовым, монтирование (/work) не затирает его."""
    path = str(Path(path).resolve())
    name = (name or "").strip() or Path(path).name   # пустое имя — имя каталога
    with tx(conn):
        row = conn.execute("SELECT id FROM projects WHERE name=?", (name,)).fetchone()
        if row:
            if update_path:
                conn.execute("UPDATE projects SET path=? WHERE id=?", (path, row["id"]))
            return int(row["id"])
        row = conn.execute("SELECT id, name FROM projects WHERE path=?", (path,)).fetchone()
        if row:
            conn.execute("UPDATE projects SET name=? WHERE id=?", (name, row["id"]))
            return int(row["id"])
        cur = conn.execute(
            "INSERT INTO projects(name, path, created_at) VALUES (?,?,?)",
            (name, path, now_iso()))
        return int(cur.lastrowid)


def list_projects(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM projects ORDER BY name").fetchall()


def get_project(conn: sqlite3.Connection, name: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM projects WHERE name=?", (name,)).fetchone()


def get_project_by_path(conn: sqlite3.Connection, path: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM projects WHERE path=?",
                        (str(Path(path).resolve()),)).fetchone()


# ─── stories ────────────────────────────────────────────────────────────────

def create_story(conn: sqlite3.Connection, project_id: int, fnr: str | None,
                 title: str, source_md: str, source_name: str = "") -> int:
    """[H] Новая Story: row PENDING_HANDOFF (демон построит план)."""
    fnr = fnr or _next_fnr(conn, project_id)
    with tx(conn):
        cur = conn.execute(
            "INSERT INTO stories(project_id, fnr, story_title, source_md, source_name,"
            " status, created_by, created_at, updated_at)"
            " VALUES (?,?,?,?,?,'PENDING_HANDOFF','ui',?,?)",
            (project_id, fnr, title, source_md, source_name, now_iso(), now_iso()))
        return int(cur.lastrowid)


def _next_fnr(conn: sqlite3.Connection, project_id: int) -> str:
    row = conn.execute(
        "SELECT fnr FROM stories WHERE project_id=? ORDER BY"
        " CAST(SUBSTR(fnr, 5) AS INTEGER) DESC LIMIT 1",
        (project_id,)).fetchone()
    n = int(row["fnr"].split("_", 1)[1]) if row else 0
    return f"FNR_{n + 1}"


def get_story(conn: sqlite3.Connection, project_id: int, fnr: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM stories WHERE project_id=? AND fnr=?",
        (project_id, fnr)).fetchone()


def story_init(conn: sqlite3.Connection, story_id: int, fields: dict) -> None:
    """[S] Заполнение полей Story сессией (impl-plan/handoff) — только пока
    статус PENDING_HANDOFF/PLANNED (до утверждения плана человеком)."""
    allowed = ("story_title", "epic_branch", "workspace", "circuit_breaker_max",
               "auto_mode", "auto_review_strategy", "created_by")
    sets, vals = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            vals.append(v)
    if not sets:
        return
    sets.append("updated_at=?")
    vals.append(now_iso())
    vals.append(story_id)
    with tx(conn):
        conn.execute(
            f"UPDATE stories SET {', '.join(sets)} WHERE id=?"
            " AND status IN ('PENDING_HANDOFF','PLANNED')",
            vals)


def story_set_status(conn: sqlite3.Connection, story_id: int, new: str, by: str) -> bool:
    """Легальный переход статуса Story. Сессия — только PLANNED→AWAITING_APPROVAL
    однократно; остальное — демон."""
    with tx(conn):
        row = conn.execute("SELECT status FROM stories WHERE id=?", (story_id,)).fetchone()
        if not row:
            return False
        cur_status = row["status"]
        if by == "session":
            if not (cur_status == "PLANNED" and new == "AWAITING_APPROVAL"):
                return False
        else:
            ok_pairs = {
                ("PENDING_HANDOFF", "PLANNED"), ("AWAITING_APPROVAL", "APPROVED"),
                ("APPROVED", "IN_PROGRESS"), ("IN_PROGRESS", "COMPLETED"),
                ("AWAITING_APPROVAL", "PLANNED"),
            }
            if (cur_status, new) not in ok_pairs and cur_status != "ABORTED":
                return False
        conn.execute("UPDATE stories SET status=?, updated_at=? WHERE id=?",
                     (new, now_iso(), story_id))
        return True


def story_pause(conn: sqlite3.Connection, story_id: int, paused: bool) -> None:
    """[H] Глобальный PAUSE — состояние Story (бывший флаг)."""
    with tx(conn):
        conn.execute("UPDATE stories SET paused=?, updated_at=? WHERE id=?",
                     (1 if paused else 0, now_iso(), story_id))


def list_story_ids(conn: sqlite3.Connection, project_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, fnr, status FROM stories WHERE project_id=? ORDER BY id",
        (project_id,)).fetchall()


# ─── tasks ──────────────────────────────────────────────────────────────────

V2_ALLOWED_SET = {"status": "v2_status", "iteration_count": "iteration_count"}
V3_SET_COLS = ("pipeline", "blocked_from", "retries", "review_iterations",
               "retry_after_ts", "pipeline_since", "paused", "skip_review",
               "session_id", "review_verdict", "blocked_reason")


def _bump(conn: sqlite3.Connection, story_id: int, tid: str) -> None:
    conn.execute("UPDATE tasks SET updated_at=? WHERE story_id=? AND tid=?",
                 (now_iso(), story_id, tid))


def read_task(conn: sqlite3.Connection, story_id: int, tid: str,
              with_card: bool = True) -> dict | None:
    """Задача целиком: поля + AC + gates + deps + frs + findings (+ карточка)."""
    row = conn.execute("SELECT * FROM tasks WHERE story_id=? AND tid=?",
                       (story_id, tid)).fetchone()
    if not row:
        return None
    t = dict(row)
    t["status"] = t["v2_status"]   # канон манифеста: v2-статус под именем status
    t["acceptance_criteria"] = [
        dict(r) for r in conn.execute(
            "SELECT ac_id, seq, desc_md AS desc, test, status FROM acceptance_criteria"
            " WHERE story_id=? AND tid=? ORDER BY seq", (story_id, tid))]
    t["gates"] = {r["gate"]: r["state"] for r in conn.execute(
        "SELECT gate, state FROM gates WHERE story_id=? AND tid=?", (story_id, tid))}
    t["depends_on"] = [r["dep_tid"] for r in conn.execute(
        "SELECT dep_tid FROM task_deps WHERE story_id=? AND tid=?", (story_id, tid))]
    t["fr_ids"] = [r["fr_id"] for r in conn.execute(
        "SELECT fr_id FROM task_frs WHERE story_id=? AND tid=?", (story_id, tid))]
    t["findings"] = [dict(r) for r in conn.execute(
        "SELECT fid, text, file, resolution, updated_at FROM findings"
        " WHERE story_id=? AND tid=?", (story_id, tid))]
    if with_card:
        t["card_md"] = t.get("card_md") or ""
    return t


def task_create(conn: sqlite3.Connection, story_id: int, spec: dict,
                origin: str = "plan") -> str:
    """[S] Новая задача с валидацией (regex/DAG/system) — атомарный tid."""
    tid = str(spec.get("id") or "").strip()
    title = str(spec.get("title") or "").strip()
    if not title:
        raise ValueError("нужен title")
    with tx(conn):
        if not tid:
            row = conn.execute(
                "SELECT tid FROM tasks WHERE story_id=? ORDER BY"
                " CAST(SUBSTR(tid, 2) AS INTEGER) DESC LIMIT 1", (story_id,)).fetchone()
            n = int(row["tid"][1:]) if row else 0
            tid = f"T{n + 1}"
        dup = conn.execute("SELECT id FROM tasks WHERE story_id=? AND tid=?",
                           (story_id, tid)).fetchone()
        if dup:
            raise ValueError(f"задача {tid} уже существует")
        now = now_iso()
        conn.execute(
            "INSERT INTO tasks(story_id, tid, title, description, system, phase,"
            " branch, origin, decomposed, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (story_id, tid, title, str(spec.get("description") or ""),
             spec.get("system"), str(spec.get("phase") or "regular"),
             str(spec.get("branch") or ""), origin,
             0, now, now))  # decomposed=False — декомпозирует стадия/сессия
        pipeline = "PROPOSED" if origin == "agent" else "BACKLOG"
        conn.execute("UPDATE tasks SET pipeline=? WHERE story_id=? AND tid=?",
                     (pipeline, story_id, tid))
        for ac in spec.get("acceptance_criteria") or []:
            conn.execute(
                "INSERT OR IGNORE INTO acceptance_criteria(story_id, tid, ac_id, seq,"
                " desc_md, test, status) VALUES (?,?,?,?,?,?, 'PENDING')",
                (story_id, tid, ac.get("id"), int(ac.get("seq") or 0),
                 ac.get("desc") or "", ac.get("test")))
        for d in spec.get("depends_on") or []:
            conn.execute("INSERT OR IGNORE INTO task_deps(story_id, tid, dep_tid)"
                         " VALUES (?,?,?)", (story_id, tid, str(d)))
        for fr in spec.get("fr_ids") or []:
            conn.execute("INSERT OR IGNORE INTO task_frs(story_id, tid, fr_id)"
                         " VALUES (?,?,?)", (story_id, tid, str(fr)))
        for g in ("build", "test", "lint", "coverage", "review"):
            conn.execute("INSERT OR IGNORE INTO gates(story_id, tid, gate)"
                         " VALUES (?,?,?)", (story_id, tid, g))
    return tid


def task_set_v2(conn: sqlite3.Connection, story_id: int, tid: str, patch: dict) -> bool:
    """[S] Колонки v2-домена сессии (владение). Возвращает False, если задача
    не найдена; чужие колонки отвергаются молча — адаптер строит патч сам."""
    cols = {V2_ALLOWED_SET[k]: v for k, v in patch.items() if k in V2_ALLOWED_SET}
    if not cols:
        return False
    sets = ", ".join(f"{k}=?" for k in cols)
    vals = list(cols.values())
    with tx(conn):
        exists = conn.execute("SELECT id FROM tasks WHERE story_id=? AND tid=?",
                              (story_id, tid)).fetchone()
        if not exists:
            return False
        conn.execute(f"UPDATE tasks SET {sets}, updated_at=? WHERE story_id=? AND tid=?",
                     (*vals, now_iso(), story_id, tid))
    return True


def task_set_v3(conn: sqlite3.Connection, story_id: int, tid: str, patch: dict) -> None:
    """[D] Колонки v3-домена демона."""
    cols = {k: v for k, v in patch.items() if k in V3_SET_COLS}
    if not cols:
        return
    sets = ", ".join(f"{k}=?" for k in cols)
    vals = list(cols.values())
    with tx(conn):
        conn.execute(f"UPDATE tasks SET {sets}, updated_at=? WHERE story_id=? AND tid=?",
                     (*vals, now_iso(), story_id, tid))


def task_set_card(conn: sqlite3.Connection, story_id: int, tid: str, card_md: str,
                  expect_version: int | None = None) -> tuple[bool, int]:
    """[S/H] Сохранение карточки с оптимистичной блокировкой.
    Возвращает (ok, текущая_version); конфликт версии → (False, версия)."""
    with tx(conn):
        row = conn.execute(
            "SELECT card_version FROM tasks WHERE story_id=? AND tid=?",
            (story_id, tid)).fetchone()
        if not row:
            return False, 0
        cur_ver = int(row["card_version"])
        if expect_version is not None and int(expect_version) != cur_ver:
            return False, cur_ver
        conn.execute(
            "UPDATE tasks SET card_md=?, card_version=card_version+1,"
            " card_updated_at=?, updated_at=? WHERE story_id=? AND tid=?",
            (card_md, now_iso(), now_iso(), story_id, tid))
        return True, cur_ver + 1


def task_transition(conn: sqlite3.Connection, story_id: int, tid: str, event: str,
                    reason: str = "") -> dict | None:
    """[D] Переход машины состояний (канон apply_transition демона)."""
    task = read_task(conn, story_id, tid, with_card=False)
    if not task:
        return None
    patch = sm.transition(task, event)   # нелегальный переход → исключение/None по канону
    if patch is None:
        return None
    with tx(conn):
        sets = ", ".join(f"{k}=?" for k in patch)
        vals = list(patch.values())
        conn.execute(
            f"UPDATE tasks SET {sets}, pipeline_since=?, blocked_reason=?, updated_at=?"
            " WHERE story_id=? AND tid=?",
            (*vals, now_iso(), reason or task.get("blocked_reason") or "", now_iso(),
             story_id, tid))
    append_event(conn, story_id, tid, f"{tid}: переход {event}"
                 + (f" ({reason}) {tid}→" if reason else ""), actor="daemon", kind="transition")
    return patch


# ─── команды (поглощают .flags/) ────────────────────────────────────────────

def insert_command(conn: sqlite3.Connection, story_id: int, name: str,
                   payload: dict | None = None, by: str = "human") -> int:
    """[H/S] UI/агент/стюард создают команду; демон потребляет в транзакции тика."""
    with tx(conn):
        cur = conn.execute(
            "INSERT INTO commands(story_id, name, payload, created_by, created_at)"
            " VALUES (?,?,?,?,?)",
            (story_id, name, json.dumps(payload, ensure_ascii=False) if payload else None,
             by, now_iso()))
        return int(cur.lastrowid)


def consume_commands(conn: sqlite3.Connection, story_id: int,
                     exclude_tid: str | None = None) -> list[dict]:
    """[D] Атомарно забрать отложенные команды Story.

    exclude_tid — команды этой задачи остаются в очереди (живая сессия
    сама увидит их через flags и остановится; один писатель её домена).
    """
    out: list[dict] = []
    seen: set[str] = set()
    with tx(conn):
        rows = conn.execute(
            "SELECT id, name, payload FROM commands WHERE story_id=:sid AND consumed_at IS NULL"
            " AND (:tid IS NULL OR name NOT GLOB 'TASK_' || :tid || '_*')"
            " ORDER BY id", {"sid": story_id, "tid": exclude_tid}).fetchall()
        for r in rows:
            if r["name"] in seen:   # дубликаты кликов гасим без исполнения
                conn.execute("UPDATE commands SET consumed_at=? WHERE id=?",
                             (now_iso(), r["id"]))
                continue
            seen.add(r["name"])
            conn.execute("UPDATE commands SET consumed_at=? WHERE id=?",
                         (now_iso(), r["id"]))
            out.append({"id": r["id"], "name": r["name"],
                        "payload": json.loads(r["payload"]) if r["payload"] else None})
    return out


def pending_commands(conn: sqlite3.Connection, story_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT id, name, payload FROM commands WHERE story_id=? AND consumed_at IS NULL"
        " ORDER BY id", (story_id,)).fetchall()]


def pending_flags_view(conn: sqlite3.Connection, story_id: int) -> set[str]:
    """Вид флагов для decide(): имена отложенных команд + PAUSE из состояния."""
    names = {r["name"] for r in conn.execute(
        "SELECT name FROM commands WHERE story_id=? AND consumed_at IS NULL",
        (story_id,)).fetchall()}
    s = conn.execute("SELECT paused FROM stories WHERE id=?", (story_id,)).fetchone()
    if s and s["paused"]:
        names.add("PAUSE")
    return names


def delete_pending_command(conn: sqlite3.Connection, story_id: int, name: str) -> None:
    """[H] Снять отложенную команду (бывший DELETE /api/flag/<name>)."""
    with tx(conn):
        conn.execute("DELETE FROM commands WHERE story_id=? AND consumed_at IS NULL"
                     " AND name=?", (story_id, name))


# ─── комментарии и события ──────────────────────────────────────────────────

def append_comment(conn: sqlite3.Connection, story_id: int, tid: str | None,
                   author: str, body: str) -> None:
    """[все роли] Журнал задачи (бывший comments/<id>.md, append-only)."""
    with tx(conn):
        conn.execute("INSERT INTO comments(story_id, tid, ts, author, body)"
                     " VALUES (?,?,?,?,?)",
                     (story_id, tid, time.strftime("%Y-%m-%d %H:%M"), author, body))


def list_comments(conn: sqlite3.Connection, story_id: int,
                  tid: str | None = None) -> list[dict]:
    if tid is None:
        rows = conn.execute("SELECT tid, ts, author, body FROM comments"
                            " WHERE story_id=? ORDER BY id", (story_id,)).fetchall()
    else:
        rows = conn.execute("SELECT tid, ts, author, body FROM comments"
                            " WHERE story_id=? AND tid=? ORDER BY id",
                            (story_id, tid)).fetchall()
    return [dict(r) for r in rows]


def append_event(conn: sqlite3.Connection, story_id: int, tid: str | None, text: str,
                 actor: str = "daemon", kind: str | None = None) -> int:
    """[все роли] Событие: SSE-фид + таймлайн + аудит (бывший events.log)."""
    with tx(conn):
        cur = conn.execute(
            "INSERT INTO events(story_id, tid, ts, actor, kind, text)"
            " VALUES (?,?,?,?,?,?)",
            (story_id, tid, time.strftime("%Y-%m-%d %H:%M:%S"), actor, kind, text))
        return int(cur.lastrowid)


def events_after(conn: sqlite3.Connection, story_id: int | None, last_id: int) -> list[dict]:
    """Инкремент для SSE (по PK-курсору)."""
    if story_id is None:
        rows = conn.execute("SELECT id, story_id, tid, ts, actor, kind, text FROM events"
                            " WHERE id>? ORDER BY id", (last_id,)).fetchall()
    else:
        rows = conn.execute("SELECT id, story_id, tid, ts, actor, kind, text FROM events"
                            " WHERE story_id=? AND id>? ORDER BY id",
                            (story_id, last_id)).fetchall()
    return [dict(r) for r in rows]


def timeline(conn: sqlite3.Connection, story_id: int, tid: str) -> list[dict]:
    """Таймлайн задачи из событий (бывший /api/timeline)."""
    rows = conn.execute(
        "SELECT ts, text FROM events WHERE story_id=? AND tid=? ORDER BY id",
        (story_id, tid)).fetchall()
    return [{"ts": r["ts"], "text": r["text"]} for r in rows]


# ─── документы стадий ───────────────────────────────────────────────────────

def doc_set(conn: sqlite3.Connection, story_id: int, kind: str, body_md: str,
            tid: str | None = None) -> None:
    """[S] Документ стадии (dossier/execution_plan/verification_report/…)."""
    with tx(conn):
        conn.execute(
            "INSERT INTO documents(story_id, tid, kind, body_md, updated_at)"
            " VALUES (?,?,?,?,?)"
            " ON CONFLICT(story_id, tid, kind) DO UPDATE SET"
            " body_md=excluded.body_md, updated_at=excluded.updated_at",
            (story_id, tid, kind, body_md, now_iso()))


def doc_get(conn: sqlite3.Connection, story_id: int, kind: str,
            tid: str | None = None) -> str | None:
    if tid is None:
        row = conn.execute(
            "SELECT body_md FROM documents WHERE story_id=? AND kind=? AND tid IS NULL",
            (story_id, kind)).fetchone()
    else:
        row = conn.execute(
            "SELECT body_md FROM documents WHERE story_id=? AND kind=? AND tid=?",
            (story_id, kind, tid)).fetchone()
    return row["body_md"] if row else None


# ─── сессии стадий (вместо .pid/.hb/.session) ───────────────────────────────

def session_start(conn: sqlite3.Connection, story_id: int, tid: str | None,
                  stage: str, pid: int, host: str, log_path: str) -> int:
    """[D] Стадия запущена (log_path — файл .run/*.log остаётся)."""
    with tx(conn):
        cur = conn.execute(
            "INSERT INTO sessions(story_id, tid, stage, pid, host, log_path,"
            " status, started_at, last_beat_at) VALUES (?,?,?,?,?,?,'running',?,?)",
            (story_id, tid, stage, pid, host, log_path, now_iso(), now_iso()))
        return int(cur.lastrowid)


def session_beat(conn: sqlite3.Connection, session_row_id: int) -> None:
    """[D] Heartbeat нити _stream_watch (throttle на вызывающей стороне)."""
    with tx(conn):
        conn.execute("UPDATE sessions SET last_beat_at=? WHERE id=?",
                     (now_iso(), session_row_id))


def session_finish(conn: sqlite3.Connection, session_row_id: int, exit_code: int,
                   status: str = "finished", usage: dict | None = None,
                   claude_session_id: str | None = None) -> None:
    """[D] Стадия завершена (+usage из result-события)."""
    u = usage or {}
    with tx(conn):
        conn.execute(
            "UPDATE sessions SET status=?, exit_code=?, finished_at=?,"
            " tokens_in=?, tokens_out=?, tokens_total=?, cost_usd=?, claude_session_id=?"
            " WHERE id=?",
            (status, exit_code, now_iso(), u.get("tokens_in"),
             u.get("tokens_out"), u.get("tokens_total"), u.get("cost_usd"),
             claude_session_id, session_row_id))
        if u.get("tokens_total"):
            sid = conn.execute("SELECT story_id, tid FROM sessions WHERE id=?",
                               (session_row_id,)).fetchone()
            if sid:
                conn.execute(
                    "UPDATE tasks SET"
                    " usage_tokens_in = usage_tokens_in + ?,"
                    " usage_tokens_out = usage_tokens_out + ?,"
                    " usage_tokens_total = usage_tokens_total + ?,"
                    " usage_cost_usd = usage_cost_usd + ?,"
                    " usage_sessions = usage_sessions + 1"
                    " WHERE story_id=? AND tid=?",
                    (u.get("tokens_in") or 0, u.get("tokens_out") or 0,
                     u.get("tokens_total") or 0, u.get("cost_usd") or 0,
                     sid["story_id"], sid["tid"]))


def live_sessions(conn: sqlite3.Connection, story_id: int) -> list[dict]:
    """Живые стадии Story (для 409-гейта карточки и лив-индикаторов)."""
    rows = conn.execute(
        "SELECT id, tid, stage, pid, host, last_beat_at FROM sessions"
        " WHERE story_id=? AND status='running'", (story_id,)).fetchall()
    out = []
    for r in rows:
        alive = False
        try:
            alive = pid_alive(int(r["pid"]))
        except (TypeError, ValueError):
            alive = False
        out.append({**dict(r), "alive": alive})
    return out


def pid_alive(pid: int) -> bool:
    try:
        if os.name == "nt":
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                                 capture_output=True, text=True, check=False)
            return str(pid) in out.stdout
        os.kill(pid, 0)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


# ─── steward ────────────────────────────────────────────────────────────────

def steward_append(conn: sqlite3.Connection, project_id: int, author: str,
                   body: str) -> None:
    with tx(conn):
        conn.execute("INSERT INTO steward_messages(project_id, ts, author, body)"
                     " VALUES (?,?,?,?)",
                     (project_id, time.strftime("%Y-%m-%d %H:%M"), author, body))


def steward_get_state(conn: sqlite3.Connection, project_id: int) -> dict:
    row = conn.execute("SELECT pending, pending_text, session_id FROM steward_state"
                       " WHERE project_id=?", (project_id,)).fetchone()
    if not row:
        with tx(conn):
            conn.execute("INSERT OR IGNORE INTO steward_state(project_id) VALUES (?)",
                         (project_id,))
        return {"pending": 0, "pending_text": None, "session_id": None}
    return {"pending": row["pending"], "pending_text": row["pending_text"],
            "session_id": row["session_id"]}


def steward_set_pending(conn: sqlite3.Connection, project_id: int,
                        pending: bool, text: str | None = None) -> None:
    with tx(conn):
        conn.execute(
            "INSERT INTO steward_state(project_id, pending, pending_text) VALUES (?,?,?)"
            " ON CONFLICT(project_id) DO UPDATE SET pending=excluded.pending,"
            " pending_text=excluded.pending_text",
            (project_id, 1 if pending else 0, text))


def steward_set_session(conn: sqlite3.Connection, project_id: int,
                        session_id: str) -> None:
    with tx(conn):
        conn.execute("UPDATE steward_state SET session_id=? WHERE project_id=?",
                     (session_id, project_id))


def steward_options_set(conn: sqlite3.Connection, story_id: int, tid: str,
                        options_json: str) -> None:
    """[D] Варианты Steward при эскалации (бывший options/T<k>.json)."""
    with tx(conn):
        conn.execute(
            "INSERT INTO steward_options(story_id, tid, options_json, updated_at)"
            " VALUES (?,?,?,?)"
            " ON CONFLICT(story_id, tid) DO UPDATE SET"
            " options_json=excluded.options_json, updated_at=excluded.updated_at",
            (story_id, tid, options_json, now_iso()))


def steward_options_clear(conn: sqlite3.Connection, story_id: int, tid: str) -> None:
    with tx(conn):
        conn.execute("DELETE FROM steward_options WHERE story_id=? AND tid=?",
                     (story_id, tid))


def steward_options_get(conn: sqlite3.Connection, story_id: int, tid: str) -> dict | None:
    row = conn.execute("SELECT options_json FROM steward_options WHERE story_id=? AND tid=?",
                       (story_id, tid)).fetchone()
    return json.loads(row["options_json"]) if row else None


# ─── вердикты ревью (from review_gate) ──────────────────────────────────────

def verdict_add(conn: sqlite3.Connection, story_id: int, tid: str, iteration: int,
                status: str, blocking: list[dict], advisory: list[dict]) -> int:
    """[S-ревьюер] Вердикт: review_verdicts + verdict_items (fid = sha1_12)."""
    import hashlib
    with tx(conn):
        cur = conn.execute(
            "INSERT INTO review_verdicts(story_id, tid, iteration, status, created_at)"
            " VALUES (?,?,?,?,?)",
            (story_id, tid, iteration, status, now_iso()))
        vid = int(cur.lastrowid)
        for item in blocking + advisory:
            kind = "blocking" if item in blocking else "advisory"
            raw = f"{item.get('file') or ''}|{item.get('text') or ''}"
            fid = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
            conn.execute(
                "INSERT INTO verdict_items(verdict_id, kind, fid, file, text)"
                " VALUES (?,?,?,?,?)",
                (vid, kind, fid, item.get("file"), item.get("text")))
    return vid


# ─── валидация канона (бывший manifest_check) ───────────────────────────────

def validate_story(conn: sqlite3.Connection, story_id: int) -> dict:
    """Канон Story по данным БД: DAG без циклов, зависимости существуют, системы объявлены.
    Возвращает {valid, errors[]} — заменяет manifest_check на данных БД."""
    errors: list[str] = []
    story = conn.execute("SELECT * FROM stories WHERE id=?", (story_id,)).fetchone()
    if not story:
        return {"valid": False, "errors": ["story not found"]}
    tasks = [dict(r) for r in conn.execute(
        "SELECT tid, v2_status, pipeline, system, decomposed FROM tasks"
        " WHERE story_id=? ORDER BY tid", (story_id,))]
    tids = {t["tid"] for t in tasks}
    deps_map: dict[str, list[str]] = {}
    for t in tasks:
        deps_map[t["tid"]] = [r["dep_tid"] for r in conn.execute(
            "SELECT dep_tid FROM task_deps WHERE story_id=? AND tid=?",
            (story_id, t["tid"])).fetchall()]
    for t in tasks:
        for d in deps_map[t["tid"]]:
            if d not in tids:
                errors.append(f"{t['tid']}: зависимость {d} не существует")
    # итеративный DFS с раскраской: GRAY (в пути) -> цикл
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {tid: WHITE for tid in deps_map}
    for start in deps_map:
        if color[start] != WHITE:
            continue
        color[start] = GRAY
        stack = [(start, iter(deps_map[start]))]
        while stack:
            node, it = stack[-1]
            advanced = False
            for nxt in it:
                st = color.get(nxt, BLACK)
                if st == GRAY:
                    errors.append(f"{start}: цикл зависимостей через {nxt}")
                    continue
                if st == WHITE:
                    color[nxt] = GRAY
                    stack.append((nxt, iter(deps_map.get(nxt, []))))
                    advanced = True
                    break
            if not advanced:
                color[node] = BLACK
                stack.pop()
    for t in tasks:
        if t["system"]:
            hit = conn.execute(
                "SELECT 1 FROM story_systems WHERE story_id=? AND name=?",
                (story_id, t["system"])).fetchone()
            if not hit:
                errors.append(f"{t['tid']}: система {t['system']} не объявлена")
    return {"valid": not errors, "errors": errors}


# ─── чек-лист задачи (модель v2) ────────────────────────────────────────────

CHECKLIST_STATES = ("todo", "inprog", "done", "review", "blocked", "failed", "skipped")


def task_row_id(conn: sqlite3.Connection, story_id: int, tid: str) -> int | None:
    row = conn.execute("SELECT id FROM tasks WHERE story_id=? AND tid=?",
                       (story_id, tid)).fetchone()
    return int(row["id"]) if row else None


def checklist_get(conn: sqlite3.Connection, task_id: int) -> list[dict]:
    """Секции с пунктами (упорядоченно)."""
    sections = []
    for srow in conn.execute(
            "SELECT id, title, kind, seq, note FROM checklist_sections"
            " WHERE task_id=? ORDER BY seq, id", (task_id,)):
        items = [dict(r) for r in conn.execute(
            "SELECT id, seq, depth, text_md AS text, state, mandatory, updated_at"
            " FROM checklist_items WHERE section_id=? ORDER BY seq, id",
            (srow["id"],))]
        sections.append({"id": srow["id"], "title": srow["title"], "kind": srow["kind"],
                         "seq": srow["seq"], "note": srow["note"], "items": items})
    return sections


def checklist_progress_db(conn: sqlite3.Connection, task_id: int) -> dict:
    row = conn.execute(
        "SELECT COUNT(*) total,"
        " SUM(state='done') done,"
        " SUM(state IN ('inprog','review','blocked','failed')) wip,"
        " SUM(mandatory=1 AND state NOT IN ('done','skipped')) open_mandatory"
        " FROM checklist_items ci JOIN checklist_sections cs ON cs.id=ci.section_id"
        " WHERE cs.task_id=?", (task_id,)).fetchone()
    return {"total": row["total"] or 0, "done": row["done"] or 0,
            "in_progress": row["wip"] or 0,
            "open_mandatory": row["open_mandatory"] or 0}


def checklist_open_mandatory(conn: sqlite3.Connection, task_id: int) -> list[dict]:
    """Незакрытые обязательные пункты plan-секций (гейт approve ревью)."""
    return [dict(r) for r in conn.execute(
        "SELECT ci.id, cs.title, ci.text_md AS text FROM checklist_items ci"
        " JOIN checklist_sections cs ON cs.id=ci.section_id"
        " WHERE cs.task_id=? AND cs.kind='plan' AND ci.mandatory=1"
        " AND ci.state NOT IN ('done','skipped')", (task_id,))]


def section_add(conn: sqlite3.Connection, task_id: int, title: str,
                kind: str = "custom") -> int:
    if kind not in ("plan", "review", "custom"):
        raise ValueError(f"неизвестный kind: {kind}")
    title = (title or "").strip()
    if not title:
        raise ValueError("нужен заголовок секции")
    with tx(conn):
        n = conn.execute("SELECT COALESCE(MAX(seq),-1)+1 FROM checklist_sections"
                         " WHERE task_id=?", (task_id,)).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO checklist_sections(task_id, title, kind, seq, updated_at)"
            " VALUES (?,?,?,?,?)"
            " ON CONFLICT(task_id, title) DO UPDATE SET kind=excluded.kind,"
            " updated_at=excluded.updated_at",
            (task_id, title, kind, n, now_iso()))
        return int(cur.lastrowid)


def section_delete(conn: sqlite3.Connection, section_id: int) -> None:
    with tx(conn):
        conn.execute("DELETE FROM checklist_sections WHERE id=?", (section_id,))


def item_add(conn: sqlite3.Connection, section_id: int, text: str,
             state: str = "todo", mandatory: bool = False,
             depth: int = 0) -> int:
    if state not in CHECKLIST_STATES:
        raise ValueError(f"неизвестное состояние: {state}")
    text = (text or "").strip()
    if not text:
        raise ValueError("нужен текст пункта")
    with tx(conn):
        n = conn.execute("SELECT COALESCE(MAX(seq),-1)+1 FROM checklist_items"
                         " WHERE section_id=?", (section_id,)).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO checklist_items(section_id, seq, depth, text_md, state,"
            " mandatory, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (section_id, n, depth, text.strip(), state, 1 if mandatory else 0,
             now_iso(), now_iso()))
        return int(cur.lastrowid)


def item_update(conn: sqlite3.Connection, item_id: int, text: str | None = None,
                state: str | None = None, mandatory: bool | None = None) -> bool:
    sets, vals = [], []
    if text is not None:
        if not text.strip():
            raise ValueError("пустой текст пункта")
        sets.append("text_md=?"); vals.append(text.strip())
    if state is not None:
        if state not in CHECKLIST_STATES:
            raise ValueError(f"неизвестное состояние: {state}")
        sets.append("state=?"); vals.append(state)
    if mandatory is not None:
        sets.append("mandatory=?"); vals.append(1 if mandatory else 0)
    if not sets:
        return False
    with tx(conn):
        cur = conn.execute("SELECT id FROM checklist_items WHERE id=?", (item_id,)).fetchone()
        if not cur:
            return False
        conn.execute(f"UPDATE checklist_items SET {', '.join(sets)}, updated_at=? WHERE id=?",
                     (*vals, now_iso(), item_id))
    return True


def item_delete(conn: sqlite3.Connection, item_id: int) -> None:
    with tx(conn):
        conn.execute("DELETE FROM checklist_items WHERE id=?", (item_id,))


# ─── Checkvist-синтаксис (текстовый режим) ─────────────────────────────────

_CV_SECTION = re.compile(r"^#{1,5}\s+(.+?)\s*$")
_CV_HEADER = re.compile(r"^(#{2,6})\s+(.+?)\s*$")
_CV_ITEM = re.compile(
    r"^(\+|~|-|\[ \]|\[~\]|\[r\]|\[b\]|\[f\]|\[x\]|\[s\])\s*(.*)$")
_CV_STATE = {"+": "done", "~": "inprog", "-": "todo", "[ ]": "todo", "[~]": "inprog",
             "[r]": "review", "[b]": "blocked", "[f]": "failed",
             "[x]": "done",   # канон чек-листов: [x] = done
             "[s]": "skipped"}  # skipped — [s] (наше расширение)
_STATE_TO_CV = {"done": "+", "inprog": "~", "todo": "-", "review": "[r]",
                "blocked": "[b]", "failed": "[f]", "skipped": "[s]"}


def parse_checkvist(text: str) -> list[dict]:
    """Checkvist-синтаксис → секции/пункты (см. гайд Checkvist): `# заголовок`
    открывает секцию; `+`/`~`/`-`/`[r]`/`[b]`/`[f]`/`[x]` — состояния;
    `!` после маркера или в конце строки — обязательный пункт."""
    sections: list[dict] = []
    cur: dict | None = None
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        h = _CV_SECTION.match(line.strip())
        if h:
            cur = {"title": h.group(1).strip(), "items": []}
            sections.append(cur)
            continue
        sub = _CV_HEADER.match(line.strip())
        if sub:
            depth = len(sub.group(1)) - 1
            if cur is None:
                cur = {"title": "Чек-лист", "items": []}
                sections.append(cur)
            cur["items"].append({"state": "todo", "text": sub.group(2).strip(),
                                 "mandatory": False, "depth": depth})
            continue
        m = _CV_ITEM.match(line.strip())
        if not m:
            continue  # посторонние строки пропускаем (не падаем)
        marker, rest = m.group(1), m.group(2).strip()
        # вложенный канонический маркер: "- [ ] …" = то же, что "- …"
        nest = re.match(r"^(\[ \]|\[~\]|\[r\]|\[b\]|\[f\]|\[x\]|\[s\])\s*(.*)$", rest)
        if nest:
            marker = nest.group(1)   # вложенный маркер уточняет состояние
            rest = nest.group(2).strip()
        mandatory = False
        if rest.startswith("!"):
            mandatory = True
            rest = rest[1:].strip()
        elif rest.endswith("!"):
            mandatory = True
            rest = rest[:-1].strip()
        if cur is None:
            cur = {"title": "Чек-лист", "items": []}
            sections.append(cur)
        cur["items"].append({"state": _CV_STATE[marker], "text": rest,
                             "mandatory": mandatory, "depth": 0})
    return [s for s in sections if s["items"]]


def serialize_checklist(sections: list[dict]) -> str:
    """Модель → Checkvist-текст (для редактора и export-снапшота)."""
    out: list[str] = []
    for sec in sections:
        out.append(f"# {sec['title']}")
        for it in sec["items"]:
            mark = _STATE_TO_CV.get(it["state"], "-")
            bang = " !" if it.get("mandatory") else ""
            out.append(f"{mark} {it['text']}{bang}")
        out.append("")
    return "\n".join(out).strip() + "\n"


def checklist_replace(conn: sqlite3.Connection, task_id: int,
                      sections: list[dict]) -> None:
    """Полная замена чек-листа задачи секциями из parse_checkvist."""
    with tx(conn):
        conn.execute("DELETE FROM checklist_sections WHERE task_id=?", (task_id,))
        for i, sec in enumerate(sections):
            title = sec["title"].strip()
            kind = "plan" if title.startswith("План работ (чек-лист)") else \
                   "review" if title.startswith("Доработка по ревью (чек-лист)") else "custom"
            cur = conn.execute(
                "INSERT INTO checklist_sections(task_id, title, kind, seq, updated_at)"
                " VALUES (?,?,?,?,?)",
                (task_id, title, kind, i, now_iso()))
            sec_id = int(cur.lastrowid)
            for j, it in enumerate(sec["items"], 1):
                conn.execute(
                    "INSERT INTO checklist_items(section_id, seq, text_md, state,"
                    " mandatory, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                    (sec_id, j, it["text"], it["state"],
                     1 if it.get("mandatory") else 0, now_iso(), now_iso()))
        conn.execute("UPDATE tasks SET updated_at=? WHERE id=?", (now_iso(), task_id))


def checklist_replace_section(conn: sqlite3.Connection, task_id: int, title: str,
                              items: list[dict]) -> None:
    """Замена/создание ОДНОЙ секции по заголовку (checklist-set агента/человека)."""
    kind = "plan" if title.startswith("План работ (чек-лист)") else \
           "review" if title.startswith("Доработка по ревью (чек-лист)") else "custom"
    with tx(conn):
        conn.execute("DELETE FROM checklist_sections WHERE task_id=? AND title=?",
                     (task_id, title))
        n = conn.execute("SELECT COALESCE(MAX(seq),-1)+1 FROM checklist_sections"
                         " WHERE task_id=?", (task_id,)).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO checklist_sections(task_id, title, kind, seq, updated_at)"
            " VALUES (?,?,?,?,?)", (task_id, title, kind, n, now_iso()))
        sec_id = int(cur.lastrowid)
        for j, it in enumerate(items, 1):
            conn.execute(
                "INSERT INTO checklist_items(section_id, seq, text_md, state, mandatory,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                (sec_id, j, it["text"], it["state"],
                 1 if it.get("mandatory") else 0, now_iso(), now_iso()))
