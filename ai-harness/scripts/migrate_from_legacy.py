"""Миграция старого harness (SQLite ~/.sa-helper/harness.db) → новый ai-harness (PostgreSQL).

Решение владельца 27.10.2026: выгрузить истории, задачи, контекст по каждой
задаче и сессии агентов из пилота FNR_8 и загрузить в текущую базу.

Перенос: story → story-задача; tasks → common_task/bug/qa_task; card_md →
descriptionMd; чек-листы plan/review → чек-листы этапов; comments → комментарии;
events → хроники; sessions → task_run; documents → артефакты; task_deps →
связи do_after; AC/гейты/находки/вердикты — сводными записями хроники.
Не переносится: steward_messages (заменён Eve), commands (операционная
очередь), task_frs/story_systems (ссылки уже в card_md), ai_settings/meta.

Запуск: DATABASE_URL=... .venv/bin/python scripts/migrate_from_legacy.py <snapshot.db> [--dry-run]
Идемпотентность: при существующем проекте VITRINA выполнение прерывается.
"""

from __future__ import annotations

import datetime as dt
import os
import sys
import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

MAX_DESC = 20000
STAGE_AGENT = {"implementing": "Разработчик", "review": "Ревьюер",
               "verify": "Тестировщик", "decompose": "Планировщик",
               "handoff": "Планировщик"}
COMMENT_AUTHOR = {"human": "Алексей", "reviewer": "Ревьюер",
                  "agent": "Разработчик", "daemon": "system", "steward": "Eve"}
ITEM_STATE = {"todo": "todo", "inprog": "in_progress", "done": "done",
              "review": "in_progress", "failed": "failed", "blocked": "failed",
              "skipped": "closed"}
DOC_KIND = {"review": "review_report", "verification_report": "qa_report",
            "failure_report": "dev_report", "runbook": "dev_report"}
# документы вне трёх видов артефактов (dossier/execution_plan/pr_draft, полный СТ)
# уходят в хронику истории целыми текстами (chronicle.message — Text без лимита)
VITRINA_PATH = "/Users/raaliev/Desktop/mts_projects/vitrina"


def ts(raw: str | None) -> dt.datetime | None:
    if not raw:
        return None
    try:
        return dt.datetime.fromisoformat(raw)
    except ValueError:
        return None


def utc(d: dt.datetime | None) -> dt.datetime:
    if d is None:
        return dt.datetime.now(dt.timezone.utc)
    if d.tzinfo is None:
        return d.replace(tzinfo=dt.timezone.utc)
    return d


class Migrator:
    def __init__(self, old, s, uid):
        self.old = old
        self.s = s
        self.uid = uid
        self.counter = 0
        self.tid_map: dict[str, str] = {}   # T1 → VITRINA-N
        self.task_pk: dict[str, str] = {}   # T1 → uuid

    async def next_code(self, project_id) -> str:
        self.counter += 1
        code = f"VITRINA-{self.counter}"
        await self.s.execute(sa.text(
            "UPDATE project SET next_number = :n + 1 WHERE id = :p AND next_number <= :n"),
            {"n": self.counter, "p": str(project_id)})
        return code

    async def insert_task(self, project_id, tid_key: str, type_pk, flow_pk,
                          title: str, desc_md: str, status_key: str,
                          created, updated, story_fk: str | None) -> str:
        code = await self.next_code(project_id)
        pk = str(uuid.uuid4())
        await self.s.execute(sa.text(
            "INSERT INTO task (id, project_id, code, task_type_id, title, "
            "description_md, status_key, flow_version_id, priority, story_id, "
            "author_id, created_at, updated_at) "
            "VALUES (:i, :p, :c, :t, :ti, :d, :st, :fv, 'medium', :sy, :a, :cr, :up)"),
            {"i": pk, "p": str(project_id), "c": code, "t": str(type_pk),
             "ti": title[:64], "d": desc_md, "st": status_key, "fv": str(flow_pk),
             "sy": story_fk, "a": str(self.uid["Алексей"]),
             "cr": utc(created), "up": utc(updated)})
        if tid_key:
            self.tid_map[tid_key] = code
            self.task_pk[tid_key] = pk
        return pk

    async def chronicle(self, task_pk: str, event_type: str, author_kind: str,
                        message: str, *, author_id=None, rule_code=None,
                        at: dt.datetime | None = None, limit: int | None = 20000):
        text = (message or "").strip()
        if limit is not None:
            text = text[:limit] or "(пусто)"
        await self.s.execute(sa.text(
            "INSERT INTO chronicle (id, task_id, event_type, author_id, author_kind, "
            "rule_code, message, created_at) "
            "VALUES (:i, :t, :et, :a, :ak, :rc, :m, :at)"),
            {"i": str(uuid.uuid4()), "t": task_pk, "et": event_type,
             "a": str(author_id) if author_id else None, "ak": author_kind,
             "rc": rule_code, "m": text or "(пусто)", "at": utc(at)})

    async def run(self, project_id, story_old, tasks_old):
        story_pk = await self.insert_story(project_id, story_old)
        for row in tasks_old:
            await self.insert_legacy_task(project_id, story_old, story_pk, row)
        await self.import_context(story_old, tasks_old)
        await self.import_sessions(story_old, tasks_old)
        await self.import_deps(story_old)

    # --- история ------------------------------------------------------------
    async def insert_story(self, project_id, story_old) -> str:
        type_pk, flow_pk = (await self.s.execute(sa.text(
            "SELECT t.id, fv.id FROM task_type t "
            "JOIN flow_version fv ON fv.task_type_id = t.id AND fv.is_current "
            "WHERE t.key = 'story'"))).one()
        source = story_old["source_md"] or ""
        note = (f"\n\n---\n\n> Текст СТ обрезан при миграции "
                f"({len(source)} символов); полная версия — в хронике истории, "
                f"запись «[doc] СТ (полный текст)».")
        cut = MAX_DESC - len(note) - 10
        desc = source[:cut] + note if len(source) > cut else source
        story_pk = await self.insert_task(
            project_id, "", type_pk, flow_pk,
            f"FNR_8: {story_old['story_title'] or 'пилот миграции'}",
            desc, "done", ts(story_old["created_at"]), ts(story_old["updated_at"]), None)
        self.task_pk[""] = story_pk
        # полный СТ — целым текстом в хронику истории (Text без лимита)
        if source:
            await self.chronicle(story_pk, "field", "auto",
                                 "[doc] СТ (полный текст):\n\n" + source,
                                 rule_code="LEGACY", limit=None,
                                 at=utc(ts(story_old["created_at"])))
        await self.chronicle(story_pk, "field", "human",
                             "История перенесена из старого harness (пилот FNR_8, "
                             "витрина) — решение владельца 27.10.2026. Все 29 задач "
                             "выполнены в старом конвейере; документ ПСИ в формате "
                             "нового трекера не составлялся, поэтому история закрыта "
                             "как архивная.",
                             author_id=self.uid["Алексей"])
        await self.chronicle(story_pk, "agent", "auto",
                             "Статус в старом harness: IN_PROGRESS; tasks T1–T29: DONE. "
                             "Артефакты: dossier (досье СТ), execution_plan, "
                             "verification_report, pr_draft — в документах истории.",
                             rule_code="LEGACY", at=utc(ts(story_old["updated_at"])))
        return story_pk

    async def artifact(self, task_pk: str, tid: str, kind: str, body: str) -> None:
        if not body or not kind:
            return
        version = 1 + (await self.s.execute(sa.text(
            "SELECT count(*) FROM task_artifact WHERE task_id = :t AND kind = :k"),
            {"t": task_pk, "k": kind})).scalar_one()
        await self.s.execute(sa.text(
            "INSERT INTO task_artifact (id, task_id, kind, version, body_md, created_by) "
            "VALUES (:i, :t, :k, :v, :b, :by)"),
            {"i": str(uuid.uuid4()), "t": task_pk, "k": kind[:16], "v": version,
             "b": body, "by": str(self.uid["Алексей"])})

    # --- задачи -------------------------------------------------------------
    async def insert_legacy_task(self, project_id, story_old, story_pk, row) -> None:
        tid = row["tid"]
        title = row["title"] or tid
        type_key = ("bug" if "дефект" in title.lower()
                    else "qa_task" if tid == "T17" else "common_task")
        type_pk, flow_pk = (await self.s.execute(sa.text(
            "SELECT t.id, fv.id FROM task_type t "
            "JOIN flow_version fv ON fv.task_type_id = t.id AND fv.is_current "
            "WHERE t.key = :k"), {"k": type_key})).one()
        desc = row["card_md"] or row["description"] or ""
        prefix = f"> Перенесено из старого harness: T-код **{tid}**, "
        prefix += f"конвейер «{row['pipeline']}», фаза {row['phase']}, происхождение {row['origin']}.\n\n"
        task_pk = await self.insert_task(
            project_id, tid, type_pk, flow_pk, title, prefix + desc, "done",
            ts(row["created_at"]), ts(row["updated_at"]), story_pk)
        if row["branch"]:
            await self.s.execute(sa.text(
                "INSERT INTO task_branch (id, task_id, branch_name, worktree_path, "
                "created_at, merged_at) VALUES (:i, :t, :b, :w, :c, :m)"),
                {"i": str(uuid.uuid4()), "t": task_pk, "b": row["branch"][:64],
                 "w": (row["worktree"] or "")[:500], "c": utc(ts(row["created_at"])),
                 "m": utc(ts(row["updated_at"]))})
        await self.chronicle(task_pk, "agent", "auto",
                             f"Задача перенесена из старого harness: {tid} "
                             f"(была «{row['pipeline']}», расход "
                             f"{row['usage_tokens_total']} токенов за "
                             f"{row['usage_sessions']} сессий).",
                             rule_code="LEGACY", at=utc(ts(row["updated_at"])))

    # --- контекст задач: чек-листы, комментарии, события, документы, гейты ---
    async def import_context(self, story_old, tasks_old) -> None:
        s, old = self.s, self.old
        # чек-листы: секций одного вида может быть несколько, а в новой модели
        # чек-лист один на (задача, вид) — сливаю секции заголовками в один
        plan_kind = {"plan": "developer", "review": "reviewer", "custom": "developer"}
        checklists: dict[tuple, str] = {}
        for sec in old.execute(
                "SELECT cs.*, t.tid FROM checklist_sections cs "
                "JOIN tasks t ON t.id = cs.task_id ORDER BY t.tid, cs.seq"):
            task_pk = self.task_pk.get(sec["tid"])
            if not task_pk:
                continue
            kind = plan_kind[sec["kind"]]
            key = (sec["tid"], kind)
            if key not in checklists:
                chk = str(uuid.uuid4())
                await s.execute(sa.text(
                    "INSERT INTO checklist (id, task_id, kind) VALUES (:i, :t, :k)"),
                    {"i": chk, "t": task_pk, "k": kind})
                checklists[key] = chk
            chk = checklists[key]
            pos = 1 + (await s.execute(sa.text(
                "SELECT count(*) FROM checklist_item WHERE checklist_id = :c"),
                {"c": chk})).scalar_one()
            await s.execute(sa.text(
                "INSERT INTO checklist_item (id, checklist_id, position, kind, level, "
                "text, status) VALUES (:i, :c, :p, 'heading', 1, :x, 'todo')"),
                {"i": str(uuid.uuid4()), "c": chk, "p": pos, "x": sec["title"]})
            for item in old.execute(
                    "SELECT * FROM checklist_items WHERE section_id=? ORDER BY seq",
                    (sec["id"],)):
                pos += 1
                await s.execute(sa.text(
                    "INSERT INTO checklist_item (id, checklist_id, position, kind, "
                    "level, text, status) VALUES (:i, :c, :p, 'item', :l, :x, :st)"),
                    {"i": str(uuid.uuid4()), "c": chk, "p": pos,
                     "l": min(5, 1 + (item["depth"] or 0)),
                     "x": item["text_md"], "st": ITEM_STATE.get(item["state"], "todo")})
        # комментарии
        for c in old.execute("SELECT * FROM comments ORDER BY ts"):
            task_pk = self.task_pk.get(c["tid"] or "")
            if not task_pk:
                continue
            await s.execute(sa.text(
                "INSERT INTO task_comment (id, task_id, author_id, body, created_at) "
                "VALUES (:i, :t, :a, :b, :at)"),
                {"i": str(uuid.uuid4()), "t": task_pk,
                 "a": str(self.uid[COMMENT_AUTHOR.get(c["author"], "system")]),
                 "b": c["body"], "at": utc(ts(c["ts"]))})
        # события → хроники (старый kind сохраняется префиксом)
        for e in old.execute("SELECT * FROM events ORDER BY id"):
            task_pk = self.task_pk.get(e["tid"] or "")
            if not task_pk:
                continue
            actor = e["actor"]
            if actor == "session":
                et, ak, aid, rc = "agent", "agent", self.uid["Разработчик"], None
            elif actor == "human":
                et, ak, aid, rc = "field", "human", self.uid["Алексей"], None
            elif actor == "steward":
                et, ak, aid, rc = "field", "eve", self.uid["Eve"], None
            else:  # daemon / server
                et, ak, aid, rc = "agent", "auto", None, "LEGACY"
            prefix = f"[{e['kind']}] " if e["kind"] else ""
            await self.chronicle(task_pk, et, ak, prefix + (e["text"] or ""),
                                 author_id=aid, rule_code=rc, at=utc(ts(e["ts"])))
        # документы → артефакты
        for d in old.execute("SELECT * FROM documents"):
            task_pk = self.task_pk.get(d["tid"] or "")
            if not task_pk:
                continue
            kind = DOC_KIND.get(d["kind"])
            if kind:
                await self.artifact(task_pk, d["tid"] or "", kind, d["body_md"])
            else:  # dossier / execution_plan / pr_draft — целым текстом в хронику
                await self.chronicle(task_pk, "field", "auto",
                                     f"[doc] {d['kind']}:\n\n{d['body_md']}",
                                     rule_code="LEGACY", limit=None,
                                     at=utc(ts(d["updated_at"])))
        # гейты, находки, вердикты, AC — сводными записями хроники
        for t in tasks_old:
            task_pk = self.task_pk.get(t["tid"])
            if not task_pk:
                continue
            gates = old.execute(
                "SELECT gate, state FROM gates WHERE tid=? ORDER BY gate", (t["tid"],)).fetchall()
            if gates:
                await self.chronicle(task_pk, "agent", "auto", "Гейты этапа: "
                                     + " · ".join(f"{g['gate']}={g['state']}" for g in gates),
                                     rule_code="LEGACY")
            findings = old.execute(
                "SELECT fid, text, resolution FROM findings WHERE tid=? ORDER BY fid",
                (t["tid"],)).fetchall()
            if findings:
                lines = "\n".join(f"- {f['text']} — {f['resolution']}" for f in findings)
                await self.chronicle(task_pk, "agent", "auto",
                                     f"Находки ревью ({len(findings)}):\n{lines}",
                                     rule_code="LEGACY")
            for v in old.execute(
                    "SELECT iteration, status, created_at FROM review_verdicts "
                    "WHERE tid=? ORDER BY iteration", (t["tid"],)):
                await self.chronicle(task_pk, "agent", "agent",
                                     f"Вердикт ревью (итерация {v['iteration']}): "
                                     f"{v['status']}",
                                     author_id=self.uid["Ревьюер"],
                                     at=utc(ts(v["created_at"])))
            acs = old.execute(
                "SELECT ac_id, status FROM acceptance_criteria WHERE tid=? ORDER BY seq",
                (t["tid"],)).fetchall()
            if acs:
                await self.chronicle(task_pk, "field", "auto", "Критерии приёмки: "
                                     + " · ".join(f"{a['ac_id']}={a['status']}" for a in acs),
                                     rule_code="LEGACY")

    # --- сессии агентов → прогоны -------------------------------------------
    async def import_sessions(self, story_old, tasks_old) -> None:
        per_task: dict[str, int] = {}
        for r in self.old.execute(
                "SELECT * FROM sessions ORDER BY COALESCE(started_at, last_beat_at), id"):
            task_pk = self.task_pk.get(r["tid"] or "")
            if not task_pk:
                continue  # сессии без задачи (handoff истории) учтены в хронике
            per_task[r["tid"]] = per_task.get(r["tid"], 0) + 1
            started = utc(ts(r["started_at"]))
            finished = utc(ts(r["finished_at"]) or ts(r["last_beat_at"]) or ts(r["started_at"]))
            outcome = {"finished": "success" if (r["exit_code"] in (0, None)) else "failed",
                       "killed": "interrupted", "orphan": "failed",
                       "running": "interrupted"}[r["status"]]
            agent = self.uid[STAGE_AGENT.get(r["stage"], "Разработчик")]
            detail = (f"[{r['stage']}] старая сессия #{r['id']}: "
                      f"claude_session={r['claude_session_id'] or '—'}, "
                      f"exit={r['exit_code']}, cost=${r['cost_usd'] or 0:.2f}, "
                      f"лог: {r['log_path']}")
            await self.s.execute(sa.text(
                "INSERT INTO task_run (id, task_id, agent_id, status_key, attempt_no, "
                "started_at, heartbeat_at, finished_at, outcome, detail, "
                "input_tokens, output_tokens, cache_tokens) "
                "VALUES (:i, :t, :a, 'done', :n, :st, :hb, :fi, :o, :d, :ti, :to, 0)"),
                {"i": str(uuid.uuid4()), "t": task_pk, "a": str(agent),
                 "n": per_task[r["tid"]], "st": started, "hb": finished, "fi": finished,
                 "o": outcome, "d": detail, "ti": r["tokens_in"] or 0,
                 "to": r["tokens_out"] or 0})

    # --- зависимости → связи -------------------------------------------------
    async def import_deps(self, story_old) -> None:
        for d in self.old.execute("SELECT tid, dep_tid FROM task_deps"):
            a, b = self.task_pk.get(d["tid"]), self.task_pk.get(d["dep_tid"])
            if not a or not b or a == b:
                continue
            await self.s.execute(sa.text(
                "INSERT INTO task_relation (id, from_task, to_task, kind) "
                "VALUES (:i, :f, :t, 'do_after')"),
                {"i": str(uuid.uuid4()), "f": a, "t": b})


async def main(snapshot_path: str, dry_run: bool) -> None:
    import sqlite3

    old = sqlite3.connect(snapshot_path)
    old.row_factory = sqlite3.Row

    engine = create_async_engine(os.environ["DATABASE_URL"])
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        users = dict((await s.execute(sa.text(
            'SELECT name, id FROM "user"'))).all())
        need = {"Алексей", "Разработчик", "Ревьюер", "Тестировщик",
                "Планировщик", "Eve", "system"}
        missing = need - set(users)
        if missing:
            raise SystemExit(f"Нет пользователей-целей: {missing} — выполните seed")
        uid = {k: users[k] if isinstance(users[k], uuid.UUID) else uuid.UUID(str(users[k])) for k in need}

        if (await s.execute(sa.text(
                "SELECT 1 FROM project WHERE mnemonic = 'VITRINA'"))).scalar():
            raise SystemExit("Проект VITRINA уже существует — миграция уже выполнялась")

        story_old = old.execute("SELECT * FROM stories").fetchone()
        project_old = old.execute("SELECT * FROM projects WHERE id=?",
                                  (story_old["project_id"],)).fetchone()
        tasks_old = old.execute(
            "SELECT * FROM tasks ORDER BY CAST(substr(tid, 2) AS INTEGER)").fetchall()
        n_sessions = old.execute("SELECT count(*) FROM sessions").fetchone()[0]
        n_events = old.execute("SELECT count(*) FROM events").fetchone()[0]
        n_comments = old.execute("SELECT count(*) FROM comments").fetchone()[0]
        print(f"Источник: {project_old['name']} · история {story_old['fnr']} "
              f"({story_old['status']}), задач {len(tasks_old)}, сессий {n_sessions}, "
              f"событий {n_events}, комментариев {n_comments}")

        if dry_run:
            print("DRY-RUN: изменений не будет. Уберите флаг для переноса.")
            await engine.dispose()
            return

        project_id = uuid.uuid4()
        await s.execute(sa.text(
            "INSERT INTO project (id, name, mnemonic, path, base_branch, next_number) "
            "VALUES (:i, :n, 'VITRINA', :p, 'main', 1)"),
            {"i": str(project_id), "n": "Vitrina (legacy FNR_8)", "p": VITRINA_PATH})

        m = Migrator(old, s, uid)
        await m.run(project_id, story_old, tasks_old)
        await s.commit()
        print(f"Готово: проект VITRINA, история VITRINA-1, задач {m.counter - 1}. "
              f"Коды: {m.tid_map.get('T1')}…{m.tid_map.get('T29')}")
    await engine.dispose()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    import asyncio

    asyncio.run(main(sys.argv[1], "--dry-run" in sys.argv))
