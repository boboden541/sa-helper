#!/usr/bin/env python3
"""Заглушка headless-сессии claude для smoke-тестов демона на БД (R3).

Контракт сессии-исполнителя (через слой db.py; HARNESS_DB из окружения):
  /impl-run    → v2-статус задачи: AGENT_REVIEW
  /impl-review → v2 DONE + вердикт APPROVED (STUB_REVIEW=changes|loop — иная ветка)
  /impl-verify → документ verification_report
Плюс stream-json-подобный stdout (heartbeat-нить демона).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import db as dbmod  # noqa: E402

PROMPT = sys.argv[sys.argv.index("-p") + 1] if "-p" in sys.argv else ""

print(json.dumps({"type": "system", "subtype": "init",
                  "session_id": "aa11bb22cc33dd44ee55ff66"}), flush=True)
print(json.dumps({"type": "result", "subtype": "stub_done"}), flush=True)

conn = dbmod.connect(os.environ.get("HARNESS_DB"))
row = conn.execute("SELECT id FROM stories ORDER BY id LIMIT 1").fetchone()
if not row:
    sys.exit(0)
story_id = int(row["id"])
parts = PROMPT.split()

if len(parts) >= 2 and parts[0] == "/impl-run":
    tid = parts[2] if len(parts) > 2 else None
    tasks = [r["tid"] for r in conn.execute(
        "SELECT tid FROM tasks WHERE story_id=? ORDER BY tid", (story_id,))]
    for tid in ([tid] if tid else tasks):
        if tid:
            dbmod.task_set_v2(conn, story_id, tid, {"status": "AGENT_REVIEW"})

elif len(parts) >= 2 and parts[0] == "/impl-review":
    tid = parts[2] if len(parts) > 2 else None
    mode = os.environ.get("STUB_REVIEW", "approve")
    if tid:
        if mode == "approve":
            dbmod.task_set_v2(conn, story_id, tid, {"status": "DONE"})
            dbmod.verdict_add(conn, story_id, tid, 1, "APPROVED", [], [])
        else:
            it = conn.execute("SELECT review_iterations FROM tasks WHERE story_id=?"
                              " AND tid=?", (story_id, tid)).fetchone()
            name = "same" if mode == "loop" else f"iter{it['review_iterations']}"
            dbmod.task_set_v2(conn, story_id, tid, {"status": "DONE"})
            dbmod.verdict_add(conn, story_id, tid, max(1, it["review_iterations"]),
                              "CHANGES_REQUESTED",
                              [{"file": "src/X.java:1", "text": f"замечание {name}"}], [])

elif len(parts) >= 1 and parts[0] == "/impl-verify":
    dbmod.doc_set(conn, story_id, "verification_report",
                  "# Verification report (stub)\n\nAll gates green.\n")
