#!/usr/bin/env python3
"""Заглушка декомпозиции: /task-decompose — помечает decomposed=true."""
from __future__ import annotations
import json, sys, time
from pathlib import Path

PROMPT = sys.argv[sys.argv.index("-p") + 1] if "-p" in sys.argv else ""
parts = PROMPT.split()
CWD = Path.cwd()
if len(parts) >= 3 and parts[0] == "/task-decompose":
    harness = CWD / parts[1]
    mp = harness / "manifest.json"
    doc = json.loads(mp.read_text(encoding="utf-8"))
    for t in doc["tasks"]:
        if t["id"] == parts[2]:
            t["decomposed"] = True
            t["description"] = "Полная постановка (после декомпозиции)"
    cdir = harness / "comments"
    cdir.mkdir(exist_ok=True)
    ts = time.strftime("%Y-%m-%d %H:%M")
    with (cdir / (parts[2] + ".md")).open("a", encoding="utf-8") as fh:
        fh.write(f"- [{ts} | agent] Декомпозиция выполнена: чек-лист и постановка готовы\n")
    doc["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    mp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("decomposed", parts[2])
