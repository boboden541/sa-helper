"""Полный API-свип: каждый эндпоинт с реальными данными против :8088.
Печатает PASS/FAIL по каждому пункту; FAIL = любой не-OK ответ вне ожиданий.
Запуск: python scripts/api-sweep.py"""
from __future__ import annotations
import json
import sys
import urllib.request
import urllib.error
import uuid

BASE = "http://localhost:8088"
results: list[tuple[bool, str, str]] = []


def call(method: str, path: str, body=None, expect=200):
    req = urllib.request.Request(BASE + path, method=method,
        headers={"Content-Type": "application/json"},
        data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            try:
                return r.status, json.loads(raw or b"{}")
            except json.JSONDecodeError:
                return r.status, {"_raw": raw.decode(errors="replace")[:200]}
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return e.code, {"_raw": raw.decode(errors="replace")[:200]}


def check(name, got, want):
    ok = got == want
    results.append((ok, name, f"got={got} want={want}"))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{got} ≠ {want}]"))


def main():
    uniq = str(uuid.uuid4())[:6]
    # --- Провайдеры ---
    st, r = call("POST", "/api/v1/connections", {"name": f"swp-{uniq}", "protocol": "anthropic",
        "url": "https://api.anthropic.com", "model": "claude-sonnet-5", "token": "sk-swp-" + uniq})
    check("connections create", st, 200)
    cid = r.get("id")
    st, r = call("POST", "/api/v1/connections", {"name": f"swp-{uniq}", "protocol": "openai",
        "url": "https://x", "model": "m", "token": "t"})
    check("connections duplicate name → 400", st, 400)
    st, _ = call("GET", "/api/v1/provider-presets")
    check("provider-presets list", st, 200)
    st, _ = call("GET", "/api/v1/connections")
    check("connections list", st, 200)
    # --- Проекты ---
    st, r = call("POST", "/api/v1/projects", {"name": "Sweep", "mnemonic": f"SW{uniq[:2].upper()}",
        "path": "/tmp"})
    check("projects create", st, 200)
    pid = r.get("id")
    st, r = call("POST", "/api/v1/projects", {"name": "Дубль", "mnemonic": f"SW{uniq[:2].upper()}", "path": "/tmp"})
    check("projects duplicate mnemonic → 400", st, 400)
    # --- Задачи ---
    st, r = call("POST", "/api/v1/tasks", {"projectId": "AH", "type": "common_task",
        "title": "Sweep задача " + uniq, "priority": "high", "authorTag": "by_human",
        "tags": ["sweep"], "descriptionMd": "## Sweep\nпроверка"})
    check("task create → pending", (st, r.get("statusKey")), (200, "pending"))
    code = r.get("code")
    st, r = call("GET", f"/api/v1/tasks/{code}")
    check("task card GET", st, 200)
    check("task card gate present", "allowed" in (r.get("gate") or {}), True)
    st, r = call("PATCH", f"/api/v1/tasks/{code}", {"title": "Sweep переименована", "priority": "critical",
        "tags": ["sweep", "e2e"]})
    check("task PATCH (title/prio/tags)", st, 200)
    # --- Переходы/форс ---
    st, r = call("POST", f"/api/v1/tasks/{code}/transitions", {"to": "done"})
    check("invalid edge → 400", st, 400)
    call("POST", f"/api/v1/tasks/{code}/force", {"to": "todo", "reason": "sweep"})
    st, r = call("POST", f"/api/v1/tasks/{code}/transitions", {"to": "in_progress"})
    check("gate denial applied=false", (st, r.get("applied")), (200, False))
    st, r = call("POST", f"/api/v1/tasks/{code}/force", {"to": "in_progress", "reason": "sweep"})
    check("force with reason", (st, r.get("applied")), (200, True))
    st, _ = call("POST", f"/api/v1/tasks/{code}/force", {"to": "todo"})
    check("force empty reason → 400", st, 400)
    # --- Чеклисты/комментарии/артефакты/связи ---
    st, _ = call("PUT", f"/api/v1/tasks/{code}/checklists/developer",
                 {"lines": "# Этап\n- сделать\n+ сделано"})
    check("checklist PUT", st, 200)
    st, r = call("GET", f"/api/v1/tasks/{code}/checklists/developer")
    check("checklist GET ≥2 items", (st, len(r.get("items", [])) >= 2), (200, True))
    st, _ = call("POST", f"/api/v1/tasks/{code}/comments", {"body": "комментарий sweep"})
    check("comment add", st, 200)
    st, _ = call("GET", f"/api/v1/tasks/{code}/comments")
    check("comments list", st, 200)
    st, _ = call("POST", f"/api/v1/tasks/{code}/artifacts/dev_report", {"bodyMd": "отчёт sweep"})
    check("artifact add v1", st, 200)
    st, _ = call("POST", f"/api/v1/tasks/{code}/artifacts/dev_report", {"bodyMd": "отчёт sweep v2"})
    check("artifact add v2", st, 200)
    st, r = call("GET", f"/api/v1/tasks/{code}/artifacts/dev_report")
    check("artifact versions kept", (st, len(r.get("versions", [])) >= 2), (200, True))
    st, _ = call("GET", f"/api/v1/tasks/{code}/chronicle")
    check("chronicle", st, 200)
    # --- Eve ---
    st, r = call("POST", "/api/v1/assistant/messages", {"text": f"что с {code}?"})
    check("eve report phrase", st, 200)
    # --- Поток статусов ---
    st, r = call("GET", "/api/v1/flows/common_task/validate")
    check("flow validate", (st, r.get("ok")), (200, True))
    st, _ = call("GET", "/api/v1/queue")
    check("queue snapshot", st, 200)
    st, _ = call("GET", "/api/v1/pipeline-status")
    check("pipeline-status", st, 200)
    st, _ = call("GET", "/api/v1/settings-journal")
    check("settings journal", st, 200)
    st, _ = call("GET", "/api/v1/users")
    check("users list", st, 200)
    st, r = call("GET", "/api/v1/agents")
    check("agents list ≥7", (st, len(r) >= 7), (200, True))
    # --- Итог ---
    fails = [x for x in results if not x[0]]
    print(f"\nИТОГ: {len(results) - len(fails)}/{len(results)} PASS")
    for ok, name, detail in fails:
        print("FAIL:", name, "—", detail)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
