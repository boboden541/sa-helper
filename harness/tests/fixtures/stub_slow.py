#!/usr/bin/env python3
"""Заглушка медленной сессии: спит STUB_DELAY секунд, затем завершает задачу
как stub_claude (AGENT_REVIEW). Для теста восстановления после kill -9."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

time.sleep(float(os.environ.get("STUB_DELAY", "0")))

PROMPT = sys.argv[sys.argv.index("-p") + 1] if "-p" in sys.argv else ""
parts = PROMPT.split()
CWD = Path.cwd()
if len(parts) >= 3 and parts[0] == "/impl-run":
    mp = CWD / parts[1] / "manifest.json"
    import json
    doc = json.loads(mp.read_text(encoding="utf-8"))
    for t in doc["tasks"]:
        if t["id"] == parts[2]:
            t["status"] = "AGENT_REVIEW"
    mp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
