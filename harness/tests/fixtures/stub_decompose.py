#!/usr/bin/env python3
"""Заглушка декомпозиции (БД): decomposed=true + описание + комментарий."""
from __future__ import annotations
import json, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import db as dbmod  # noqa: E402

PROMPT = sys.argv[sys.argv.index("-p") + 1] if "-p" in sys.argv else ""
parts = PROMPT.split()
if len(parts) >= 3 and parts[0] == "/task-decompose":
    conn = dbmod.connect(os.environ.get("HARNESS_DB"))
    row = conn.execute("SELECT id FROM stories ORDER BY id LIMIT 1").fetchone()
    sid = int(row["id"])
    tid = parts[2]
    dbmod.task_set_v2(conn, sid, tid, {"status": "PLANNED"})
    with dbmod.tx(conn):
        conn.execute("UPDATE tasks SET decomposed=1, description=? WHERE story_id=? AND tid=?",
                     ("Полная постановка (после декомпозиции)", sid, tid))
    dbmod.append_comment(conn, sid, tid, "agent",
                         "Декомпозиция выполнена: чек-лист и постановка готовы")
    print("decomposed", tid)
