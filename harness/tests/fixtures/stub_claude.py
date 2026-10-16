#!/usr/bin/env python3
"""Заглушка headless-сессии claude для smoke-теста демона (orchestrator.py).

Имитирует контракт сессии-исполнителя: обновляет v2-поля манифеста (status,
review_verdict) по команде стадии, пишет stream-json-подобный вывод в stdout
(для heartbeat-нити демона). Запуск — только из тестов, на PATH не ставить.

Контракт стадий (как у реальных команд v2):
  /impl-run   → status: AGENT_REVIEW (задача готова к ревью)
  /impl-review→ status: DONE + review_verdict: APPROVED
  /impl-verify→ пишет verification_report.md
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

PROMPT = sys.argv[sys.argv.index("-p") + 1] if "-p" in sys.argv else ""
CWD = Path.cwd()

# stream-json-подобные строки — живость для heartbeat-нити демона
print(json.dumps({"type": "system", "subtype": "init",
                  "session_id": "aa11bb22cc33dd44ee55ff66"}), flush=True)
print(json.dumps({"type": "system", "subtype": "stub_start", "prompt": PROMPT[:60]}), flush=True)
print(json.dumps({"type": "result", "subtype": "stub_done"}), flush=True)

parts = PROMPT.split()
if len(parts) >= 2 and parts[0] == "/impl-run":
    harness = CWD / parts[1]
    task_id = parts[2] if len(parts) > 2 else None
    mp = harness / "manifest.json"
    doc = json.loads(mp.read_text(encoding="utf-8"))
    for t in doc["tasks"]:
        if t["id"] == task_id:
            t["status"] = "AGENT_REVIEW"
    doc["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    mp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

elif len(parts) >= 2 and parts[0] == "/impl-review":
    import os
    harness = CWD / parts[1]
    task_id = parts[2] if len(parts) > 2 else None
    mp = harness / "manifest.json"
    doc = json.loads(mp.read_text(encoding="utf-8"))
    mode = os.environ.get("STUB_REVIEW", "approve")
    for t in doc["tasks"]:
        if t["id"] != task_id:
            continue
        if mode == "approve":
            t["status"] = "DONE"
            t["review_verdict"] = "APPROVED"
        else:
            # CHANGES_REQUESTED: structured verdict, каждый раунд — НОВЫЙ текст
            # (loop: один и тот же) — id различаются, closure_first видит новые
            it = int(t.get("review_iterations") or 0)
            name = f"same" if mode == "loop" else f"iter{it}"
            t["review_verdict"] = "CHANGES_REQUESTED"
            reviews = harness / "reviews"
            reviews.mkdir(exist_ok=True)
            (reviews / f"{task_id}_review.md").write_text(
                "# Ревью " + str(task_id) + "\n\n"
                "## Verdict (machine-readable)\n"
                "status: CHANGES_REQUESTED\n"
                "blocking:\n"
                f"- | file: src/X.java:1 | text: замечание {name}\n",
                encoding="utf-8")
    doc["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    mp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

elif len(parts) >= 1 and parts[0] == "/impl-verify":
    harness = CWD / parts[1]
    (harness / "verification_report.md").write_text(
        "# Verification report (stub)\n\nAll gates green.\n", encoding="utf-8")
