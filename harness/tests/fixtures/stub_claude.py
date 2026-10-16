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
    harness = CWD / parts[1]
    task_id = parts[2] if len(parts) > 2 else None
    mp = harness / "manifest.json"
    doc = json.loads(mp.read_text(encoding="utf-8"))
    for t in doc["tasks"]:
        if t["id"] == task_id:
            t["status"] = "DONE"
            t["review_verdict"] = "APPROVED"
    doc["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    mp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

elif len(parts) >= 1 and parts[0] == "/impl-verify":
    harness = CWD / parts[1]
    (harness / "verification_report.md").write_text(
        "# Verification report (stub)\n\nAll gates green.\n", encoding="utf-8")
