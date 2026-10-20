"""Тесты витрины на БД (порция R2): API работает через слой db.py."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "web"))

import db as dbmod  # noqa: E402
import server as web  # noqa: E402


class WebServerFixture(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.dbfile = Path(self._td.name) / "t.db"
        self.conn = dbmod.connect(self.dbfile)
        self.ws = Path(self._td.name) / "ws"
        (self.ws / "sa_documentation" / "FNR" / "FNR_1" / "harness" / ".run").mkdir(parents=True)
        self.pid_row = dbmod.upsert_project(self.conn, "testws", str(self.ws))
        self.sid = dbmod.create_story(self.conn, self.pid_row, "FNR_1", "Тестовая", "# СТ")
        self.t1 = dbmod.task_create(self.conn, self.sid,
                                    {"id": "T1", "title": "A",
                                     "branch": "harness/fnr-1-a-t1"}, origin="plan")
        dbmod.task_set_v3(self.conn, self.sid, "T1", {"pipeline": "DONE"})
        dbmod.task_set_v2(self.conn, self.sid, "T1", {"status": "DONE"})
        self.t2 = dbmod.task_create(self.conn, self.sid,
                                    {"id": "T2", "title": "B",
                                     "description": "старое краткое",
                                     "branch": "harness/fnr-1-b-t2"}, origin="plan")
        dbmod.task_set_v3(self.conn, self.sid, "T2", {"pipeline": "READY"})
        dbmod.task_set_v2(self.conn, self.sid, "T2", {"status": "APPROVED"})
        dbmod.task_set_card(self.conn, self.sid, "T2",
                            "# T2: задача B\n\n## Что сделать\n\nСобрать каталог.\n")
        web.STATE["conn"] = self.conn
        web.STATE["default_project"] = "testws"
        web.STATE["claude_bin"] = str(ROOT / "tests" / "fixtures" / "stub_chat.py")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        web.STATE["conn"] = None
        self.conn.close()
        self._td.cleanup()

    def q(self, path: str) -> str:
        return f"{path}?project=testws&fnr=FNR_1"

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

    def delete(self, path):
        req = urllib.request.Request(self.base + path, method="DELETE")
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())

    def post_expect_error(self, path, body=None) -> tuple[int, dict]:
        try:
            self.post(path, body)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
        raise AssertionError(f"ожидали ошибку на {path}")

    def commands(self) -> list[str]:
        return [r["name"] for r in self.conn.execute(
            "SELECT name FROM commands WHERE consumed_at IS NULL").fetchall()]


class TestStateAndStories(WebServerFixture):
    def test_state_manifest_view(self):
        state = self.get(self.q("/api/state"))
        self.assertEqual(state["manifest"]["fnr_id"], "FNR_1")
        tasks = {t["id"]: t for t in state["manifest"]["tasks"]}
        self.assertEqual(tasks["T1"]["pipeline"], "DONE")
        self.assertIn("TASK_T1_REQUEST_CHANGES", tasks["T1"]["actions"])
        self.assertIn("TASK_T2_PAUSE", tasks["T2"]["actions"])
        self.assertEqual(tasks["T2"]["move_targets"], ["ABORTED"])
        self.assertEqual(tasks["T2"]["checklist"]["total"], 0)

    def test_card_preview_on_board(self):
        data = self.get("/api/stories?project=testws")
        story = data["stories"][0]
        rows = {t["id"]: t for t in story["task_list"]}
        self.assertTrue(rows["T2"]["description"].startswith("Собрать каталог"))
        self.assertEqual(story["counts"].get("READY"), 1)


class TestMove(WebServerFixture):
    def test_move_applies_sync(self):
        out = self.post(self.q("/api/task/T2/move"), {"to": "ABORTED"})
        self.assertTrue(out["ok"])
        self.assertEqual(out.get("pipeline"), "ABORTED")  # применён сразу
        self.assertEqual(self.commands(), [])  # не через очередь
        task = dbmod.read_task(self.conn, self.sid, "T2", with_card=False)
        self.assertEqual(task["pipeline"], "ABORTED")
        ev = self.conn.execute(
            "SELECT actor FROM events WHERE tid='T2' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        self.assertEqual(ev["actor"], "human")

    def test_move_fence_409(self):
        dbmod.session_start(self.conn, self.sid, "T2", "implementing",
                            os.getpid(), "test", "t.log")
        code, body = self.post_expect_error(self.q("/api/task/T2/move"),
                                            {"to": "ABORTED"})
        self.assertEqual(code, 409)
        self.assertIn("сессия", body["error"])
        self.assertTrue(body["running"])

    def test_invalid_transition_is_400(self):
        code, body = self.post_expect_error(self.q("/api/task/T2/move"),
                                            {"to": "BACKLOG"})
        self.assertEqual(code, 400)
        self.assertIn("недопустим", body["error"])


class TestCard(WebServerFixture):
    NEW_CARD = "# T2\n\n## Что сделать\n\nНовая постановка.\n"

    def test_card_save_roundtrip(self):
        out = self.post(self.q("/api/task/T2/card"), {"card_md": self.NEW_CARD})
        self.assertTrue(out["ok"])
        self.assertGreaterEqual(out["card_version"], 2)
        doc = self.get(self.q("/api/task/T2"))
        self.assertIn("Новая постановка", doc["card_md"])
        self.assertIn("| human]", doc["comments_md"])
        comments = self.conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
        self.assertGreaterEqual(comments, 1)

    def test_card_version_conflict(self):
        self.post(self.q("/api/task/T2/card"), {"card_md": self.NEW_CARD})
        code, body = self.post_expect_error(self.q("/api/task/T2/card"),
                                            {"card_md": "x", "expect_version": 1})
        self.assertEqual(code, 409)
        self.assertIn("card_version", body)

    def test_card_conflict_when_live_then_force(self):
        s = dbmod.session_start(self.conn, self.sid, "T2", "implementing",
                                pid=os.getpid(), host="h", log_path="/tmp/x.log")
        code, body = self.post_expect_error(self.q("/api/task/T2/card"),
                                            {"card_md": self.NEW_CARD})
        self.assertEqual(code, 409)
        self.assertTrue(body.get("running"))
        out = self.post(self.q("/api/task/T2/card"),
                        {"card_md": self.NEW_CARD, "force": True})
        self.assertTrue(out["ok"])
        dbmod.session_finish(self.conn, s, 0)

    def test_card_validation(self):
        code, _ = self.post_expect_error(self.q("/api/task/TX/card"), {"card_md": "# x"})
        self.assertEqual(code, 404)
        code, _ = self.post_expect_error(self.q("/api/task/T2/card"), {"card_md": "  "})
        self.assertEqual(code, 400)


class TestFlags(WebServerFixture):
    def test_pause_is_story_state(self):
        self.post(self.q("/api/flag/PAUSE"))
        state = self.get(self.q("/api/state"))
        self.assertIn("PAUSE", state["flags"])
        self.assertEqual(self.commands(), [])
        self.delete(self.q("/api/flag/PAUSE"))
        state = self.get(self.q("/api/state"))
        self.assertNotIn("PAUSE", state["flags"])

    def test_flag_creates_command_and_delete_removes(self):
        self.post(self.q("/api/flag/APPROVE_PLAN"))
        self.assertEqual(self.commands(), ["APPROVE_PLAN"])
        self.delete(self.q("/api/flag/APPROVE_PLAN"))
        self.assertEqual(self.commands(), [])

    def test_delete_bad_name_is_400(self):
        req = urllib.request.Request(
            self.base + self.q("/api/flag/..%2Fx"), method="DELETE")
        try:
            urllib.request.urlopen(req, timeout=5)
            raise AssertionError("ожидали 400")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)


class TestManualTask(WebServerFixture):
    def test_create_task_queues_command(self):
        out = self.post("/api/story/FNR_1/task?project=testws",
                        {"title": "Ручная", "description": "из теста"})
        self.assertTrue(out["queued"])
        self.assertEqual(self.commands(), ["task.new"])
        row = self.conn.execute("SELECT payload FROM commands").fetchone()
        self.assertEqual(json.loads(row["payload"])["title"], "Ручная")

    def test_create_task_unknown_story_is_404(self):
        code, _ = self.post_expect_error("/api/story/FNR_99/task?project=testws",
                                         {"title": "X"})
        self.assertEqual(code, 404)


class TestStewardGuard(WebServerFixture):
    def test_chat_without_project_is_400(self):
        try:
            urllib.request.urlopen(f"{self.base}/api/steward/chat", timeout=5)
            raise AssertionError("ожидали 400")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)

    def test_message_without_project_is_400(self):
        code, _ = self.post_expect_error("/api/steward/message", {"text": "привет"})
        self.assertEqual(code, 400)

    def test_task_doc_has_findings_and_review_md(self):
        # С4: блок «Ревью» панели всегда видит находки и markdown-отчёт
        tid_row = self.conn.execute("SELECT id FROM tasks WHERE tid='T2'").fetchone()
        dbmod.verdict_add(self.conn, self.sid, "T2", 1, "CHANGES_REQUESTED",
                          blocking=[{"file": "a.py:1", "text": "нет гейта"}],
                          advisory=[])
        # findings-таблицу пишет reconcile_review демона — сеем напрямую
        with dbmod.tx(self.conn):
            self.conn.execute(
                "INSERT INTO findings(story_id, tid, fid, text, file, resolution,"
                " updated_at) VALUES (?,?,?,?,?, 'open', ?)",
                (self.sid, "T2", "abc123", "нет гейта", "a.py:1", dbmod.now_iso()))
        dbmod.doc_set(self.conn, self.sid, "review", "## Отчёт\n", tid="T2")
        doc = self.get(self.q("/api/task/T2"))
        self.assertEqual(doc["review_md"], "## Отчёт\n")
        state = self.get(self.q("/api/state"))
        t2 = next(x for x in state["manifest"]["tasks"] if x["id"] == "T2")
        self.assertEqual(t2["findings"][0]["file"], "a.py:1")

    def test_chat_messages_have_ids(self):
        # С3: id сообщения — ключ merge-полла чата (история/эхо)
        dbmod.steward_append(self.conn, self.pid_row, "human", "привет")
        dbmod.steward_append(self.conn, self.pid_row, "steward", "ответ")
        data = self.get(self.q("/api/steward/chat"))
        msgs = data["messages"]
        self.assertEqual([m["text"] for m in msgs], ["привет", "ответ"])
        self.assertTrue(all(isinstance(m.get("id"), int) for m in msgs))
        self.assertFalse(data["pending"])


class TestComments(WebServerFixture):
    def test_comment_and_attention_retry(self):
        dbmod.task_set_v3(self.conn, self.sid, "T2", {"pipeline": "NEEDS_HUMAN"})
        self.post(self.q("/api/comment/T2"), {"text": "починить 403"})
        doc = self.get(self.q("/api/task/T2"))
        self.assertIn("починить 403", doc["comments_md"])
        # С1: retry применён синхронно, без демона — задача вернулась в работу
        task = dbmod.read_task(self.conn, self.sid, "T2", with_card=False)
        self.assertEqual(task["pipeline"], "IMPLEMENTING")
        self.assertEqual(self.commands(), [])


if __name__ == "__main__":
    unittest.main()


class TestSessionDiagnosis(unittest.TestCase):
    """Диагноз последней сессии: пермиссии/API-ошибка видны в problem-блоке."""

    def test_permission_denied_detected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            hdir = Path(td)
            run = hdir / ".run"
            run.mkdir()
            lines = [
                json.dumps({"type": "system", "subtype": "init", "session_id": "x"}),
                json.dumps({"type": "system", "subtype": "permission_denied",
                            "tool_name": "Bash",
                            "message": "The following part requires approval: python3 -V"}),
            ]
            (run / "T5_implementing_1.log").write_text("\n".join(lines), encoding="utf-8")
            d = web._session_diagnosis(hdir, "T5")
            self.assertIn("отказ пермиссий", d)
            self.assertIn("python3 -V", d)

    def test_no_diagnosis_for_healthy_log(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            hdir = Path(td)
            run = hdir / ".run"
            run.mkdir()
            (run / "T1_implementing_1.log").write_text(
                json.dumps({"type": "result", "result": "готово"}), encoding="utf-8")
            self.assertIsNone(web._session_diagnosis(hdir, "T1"))


if __name__ == "__main__":
    unittest.main()
