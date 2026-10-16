"""Тесты витрины v3: действия задач, живой лог, чат задачи (ui_server.py)."""

from __future__ import annotations

import json
import sys
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ui"))

import ui_server  # noqa: E402


def build_harness(tmp: Path) -> Path:
    harness = tmp / "ws" / "sa_documentation" / "FNR" / "FNR_1" / "harness"
    (harness / ".flags").mkdir(parents=True)
    (harness / ".run").mkdir()
    manifest = {"fnr_id": "FNR_1", "status": "IN_PROGRESS", "tasks": [
        {"id": "T1", "title": "A", "pipeline": "DONE", "status": "DONE",
         "session_id": "sess-123"},
        {"id": "T2", "title": "B", "pipeline": "READY", "status": "APPROVED"},
    ]}
    (harness / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (harness / ".run" / "T1_implementing_42.log").write_text(
        '{"session_id":"sess-123"}\nline2\n' * 400, encoding="utf-8")
    return harness


class ServerFixture(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._td = tempfile.TemporaryDirectory()
        harness = build_harness(Path(self._td.name))
        ui_server.STATE["harness"] = harness
        ui_server.STATE["claude_bin"] = str(ROOT / "tests" / "fixtures" / "stub_chat.py")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ui_server.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self._td.cleanup()

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=5) as r:
            return json.loads(r.read())

    def post(self, path, body=None):
        req = urllib.request.Request(
            self.base + path, method="POST",
            data=json.dumps(body or {}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())

    def test_state_has_actions(self):
        state = self.get("/api/state")
        tasks = {t["id"]: t for t in state["manifest"]["tasks"]}
        self.assertIn("TASK_T1_REQUEST_CHANGES", tasks["T1"]["actions"])
        self.assertIn("TASK_T1_PAUSE", tasks["T1"]["actions"])
        self.assertIn("TASK_T2_PAUSE", tasks["T2"]["actions"])
        self.assertTrue(tasks["T1"]["can_ask"])
        self.assertFalse(tasks["T2"]["can_ask"])

    def test_log_tail(self):
        doc = self.get("/api/log/T1")
        self.assertEqual(doc["file"], "T1_implementing_42.log")
        self.assertIn("line2", doc["log"])
        self.assertLessEqual(len(doc["log"]), 8192 + 8)
        self.assertEqual(self.get("/api/log/T9")["file"], None)

    def test_ask_requires_session(self):
        with urllib.request.urlopen(self.base + "/api/state", timeout=5) as r:
            pass  # sanity
        try:
            self.post("/api/ask/T2", {"text": "вопрос без сессии"})
            self.fail("ожидали 409")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 409)

    def test_ask_appends_question_and_answer(self):
        res = self.post("/api/ask/T1", {"text": "почему trust-auth?"})
        self.assertTrue(res["pending"])
        harness = ui_server.STATE["harness"]
        pending = harness / ".run" / "T1_ask.pending"
        deadline = time.time() + 10
        while pending.exists() and time.time() < deadline:
            time.sleep(0.05)
        self.assertFalse(pending.exists(), "чат не завершился")
        comments = (harness / "comments" / "T1.md").read_text(encoding="utf-8")
        self.assertIn("| human] почему trust-auth?", comments)
        self.assertIn("| agent] Ответ агента на вопрос: почему trust-auth?", comments)


if __name__ == "__main__":
    unittest.main()


class TestChecklistProgress(unittest.TestCase):
    def test_counts_jira_style_checkboxes(self):
        card = """## План работ (чек-лист)
- [x]RED-тесты
- [~]Миграция V2
- [ ]Репозиторий
- обычный пункт списка — не чекбокс
"""
        self.assertEqual(ui_server.checklist_progress(card),
                         {"total": 3, "done": 1, "in_progress": 1})

    def test_empty_card(self):
        self.assertEqual(ui_server.checklist_progress(""),
                         {"total": 0, "done": 0, "in_progress": 0})


class TestChecklistSections(unittest.TestCase):
    def test_sections_items_and_continuations(self):
        card = ("## План работ (чек-лист)\n"
                "- [x]RED-тесты: test_ac_4_1_2_1_*\n"
                "- [~]Миграция V2__create_id_mapping.sql\n"
                "  (DDL из СТ 4.1.2, дословно)\n"
                "- [ ]Репозиторий\n"
                "\n"
                "nit: unused import.\n"
                "\n"
                "## Доработка по ревью (чек-лист)\n"
                "- [ ]src/A.java:42 — тело 403\n"
                "  глобальный обработчик → вернуть payload\n")
        secs = ui_server.parse_checklist_sections(card)
        self.assertEqual([s["title"] for s in secs],
                         ["План работ (чек-лист)", "Доработка по ревью (чек-лист)"])
        plan = secs[0]
        self.assertEqual(plan["total"], 3)
        self.assertEqual([i["state"] for i in plan["items"]], ["done", "wip", "todo"])
        self.assertIn("(DDL из СТ 4.1.2, дословно)", plan["items"][1]["text"])
        review = secs[1]
        self.assertIn("глобальный обработчик", review["items"][0]["text"])

    def test_no_checkboxes_no_sections(self):
        self.assertEqual(ui_server.parse_checklist_sections("# Задача\n- простой пункт\n"), [])
