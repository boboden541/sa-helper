"""Тесты витрины v3 на web/server.py: move/pipeline_of, DELETE флагов,
ручная Task (?project=), task_rows (branch/sessions), PATCH-зона П2.

Ранее web/server.py тестами не покрывался (test_ui_server гоняет legacy
ui/ui_server.py) — порция П6 закрыла пробел на починенных эндпоинтах.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "web"))

import server as web  # noqa: E402


def build_workspace(tmp: Path) -> Path:
    ws = tmp / "ws"
    harness = ws / "sa_documentation" / "FNR" / "FNR_1" / "harness"
    (harness / ".flags").mkdir(parents=True)
    (harness / ".run").mkdir()
    (harness / "tasks").mkdir()
    manifest = {"story_title": "Тестовая", "tasks": [
        {"id": "T1", "title": "A", "pipeline": "DONE", "status": "DONE",
         "branch": "harness/fnr-1-a-t1"},
        {"id": "T2", "title": "B", "pipeline": "READY", "status": "APPROVED",
         "description": "старое краткое из манифеста",
         "usage": {"tokens_in": 10, "tokens_out": 5, "tokens_total": 15,
                   "cost_usd": 0.01}},
    ]}
    (harness / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (harness / "tasks" / "T2_b.md").write_text(
        "# T2: задача B\n\n## Что сделать\n\nСобрать каталог и опубликовать.\n\n"
        "## Чек-лист\n\n- [x] раз\n- [b] два\n", encoding="utf-8")
    return ws


class WebServerFixture(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._td = tempfile.TemporaryDirectory()
        self.ws = build_workspace(Path(self._td.name))
        web.STATE["workspace"] = self.ws
        web.STATE["projects"] = {"testws": str(self.ws)}
        web.STATE["harness"] = None
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        web.STATE["workspace"] = None
        web.STATE["projects"] = {}
        web.STATE["harness"] = None
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

    def flags(self) -> list[str]:
        return sorted(p.name for p in
                      (self.ws / "sa_documentation/FNR/FNR_1/harness/.flags").iterdir())


class TestMove(WebServerFixture):
    def test_abort_from_ready(self):
        # П2: pipeline_of + MOVE_MAP += ABORTED (ранее — NameError на любой move)
        out = self.post(self.q("/api/task/T2/move"), {"to": "ABORTED"})
        self.assertTrue(out["ok"])
        self.assertIn("TASK_T2_ABORT", self.flags())

    def test_invalid_transition_is_400_not_500(self):
        code, body = self.post_expect_error(self.q("/api/task/T2/move"),
                                            {"to": "BACKLOG"})
        self.assertEqual(code, 400)
        self.assertIn("недопустим", body["error"])

    def test_pipeline_of_maps_v2_status(self):
        # задача без pipeline, но с внутренним v2-статусом
        self.assertEqual(web.pipeline_of({"status": "AGENT_REVIEW"}), "REVIEW")
        self.assertEqual(web.pipeline_of({"pipeline": "REVIEW"}), "REVIEW")
        self.assertEqual(web.pipeline_of({}), "BACKLOG")

    def test_move_targets_in_endpoint(self):
        state = self.get(self.q("/api/state"))
        tasks = {t["id"]: t for t in state["manifest"]["tasks"]}
        self.assertEqual(tasks["T2"]["move_targets"], ["ABORTED"])
        self.assertEqual(tasks["T1"]["move_targets"], ["IMPLEMENTING"])


class TestFlags(WebServerFixture):
    def test_delete_flag_removes_file(self):
        # П2: do_DELETE был мёртв (NameError) и не понимал ?project=
        self.post(self.q("/api/flag/TEST_FLAG_X"))
        self.assertIn("TEST_FLAG_X", self.flags())
        self.delete(self.q("/api/flag/TEST_FLAG_X"))
        self.assertNotIn("TEST_FLAG_X", self.flags())

    def test_delete_missing_flag_is_ok(self):
        self.delete(self.q("/api/flag/NOPE"))  # missing_ok → 200

    def test_delete_bad_name_is_400(self):
        req = urllib.request.Request(
            self.base + self.q("/api/flag/..%2Fx"), method="DELETE")
        try:
            urllib.request.urlopen(req, timeout=5)
            raise AssertionError("ожидали 400")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)


class TestManualTask(WebServerFixture):
    def test_create_task_via_project_query(self):
        # П2: fnr уходил в позицию project → всегда 404
        out = self.post(f"/api/story/FNR_1/task?project=testws",
                        {"title": "Ручная", "description": "из теста"})
        self.assertTrue(out["queued"])
        new = [f for f in self.flags() if f.startswith("TASK_NEW_")]
        self.assertEqual(len(new), 1)
        payload = json.loads(
            (self.ws / "sa_documentation/FNR/FNR_1/harness/.flags" / new[0])
            .read_text(encoding="utf-8"))
        self.assertEqual(payload["title"], "Ручная")

    def test_create_task_unknown_story_is_404(self):
        code, _ = self.post_expect_error(f"/api/story/FNR_99/task?project=testws",
                                         {"title": "X"})
        self.assertEqual(code, 404)


class TestStewardGuard(WebServerFixture):
    """/api/steward/* без ?project= (или с неизвестным) — 400, не TypeError
    (живой инцидент: _steward_dir(None) ронял запрос с трейсбеком)."""

    def test_chat_without_project_is_400(self):
        try:
            urllib.request.urlopen(f"{self.base}/api/steward/chat", timeout=5)
            raise AssertionError("ожидали 400")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)

    def test_chat_unknown_project_is_400(self):
        try:
            urllib.request.urlopen(f"{self.base}/api/steward/chat?project=nope",
                                   timeout=5)
            raise AssertionError("ожидали 400")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)

    def test_message_without_project_is_400(self):
        code, _ = self.post_expect_error("/api/steward/message", {"text": "привет"})
        self.assertEqual(code, 400)


class TestCardEdit(WebServerFixture):
    """Д1: единое описание — карточка первична. POST /api/task/<id>/card пишет
    только карточку (+журнал/комментарий), манифест не трогает; live-гейт 409/force;
    превью description деривируется из карточки."""

    NEW_CARD = ("# T2: задача B\n\n## Что сделать\n\nСделать правильно и с покрытием.\n\n"
                "## Чек-лист\n\n- [ ] раз\n")

    def _card_path(self) -> Path:
        return self.ws / "sa_documentation/FNR/FNR_1/harness/tasks/T2_b.md"

    def _harness(self) -> Path:
        return self.ws / "sa_documentation/FNR/FNR_1/harness"

    def test_card_save_overwrites_existing_file(self):
        out = self.post(self.q("/api/task/T2/card"), {"card_md": self.NEW_CARD})
        self.assertTrue(out["ok"])
        self.assertEqual(out["card"], "T2_b.md")
        self.assertEqual(self._card_path().read_text(encoding="utf-8"), self.NEW_CARD)

    def test_card_save_appends_comment_and_event(self):
        self.post(self.q("/api/task/T2/card"), {"card_md": self.NEW_CARD})
        comments = (self._harness() / "comments" / "T2.md").read_text(encoding="utf-8")
        self.assertIn("| human", comments)
        self.assertIn("Карточка обновлена", comments)
        events = (self._harness() / "logs" / "events.log").read_text(encoding="utf-8")
        self.assertIn("T2: карточка обновлена человеком", events)

    def test_card_save_conflict_when_live_then_force(self):
        run = self._harness() / ".run"
        (run / "T2_impl.hb").write_text("", encoding="utf-8")
        (run / "T2_impl.pid").write_text(str(os.getpid()), encoding="utf-8")
        code, body = self.post_expect_error(self.q("/api/task/T2/card"),
                                            {"card_md": self.NEW_CARD})
        self.assertEqual(code, 409)
        self.assertTrue(body.get("running"))
        self.assertEqual(
            self._card_path().read_text(encoding="utf-8"),
            "# T2: задача B\n\n## Что сделать\n\nСобрать каталог и опубликовать.\n\n"
            "## Чек-лист\n\n- [x] раз\n- [b] два\n")  # файл не тронут без force
        out = self.post(self.q("/api/task/T2/card"),
                        {"card_md": self.NEW_CARD, "force": True})
        self.assertTrue(out["ok"])

    def test_card_save_creates_missing_card(self):
        out = self.post(self.q("/api/task/T1/card"), {"card_md": "# T1\n\nтекст\n"})
        self.assertTrue(out["ok"])
        self.assertEqual(out["card"], "T1.md")
        self.assertTrue((self._harness() / "tasks" / "T1.md").is_file())

    def test_card_save_does_not_touch_manifest(self):
        manifest = self._harness() / "manifest.json"
        before = manifest.read_bytes()
        self.post(self.q("/api/task/T2/card"), {"card_md": self.NEW_CARD})
        self.assertEqual(manifest.read_bytes(), before)

    def test_card_save_validation(self):
        code, _ = self.post_expect_error(self.q("/api/task/TX/card"),
                                         {"card_md": "# x\n"})
        self.assertEqual(code, 400)
        code, _ = self.post_expect_error(self.q("/api/task/T2/card"),
                                         {"card_md": "   \n  "})
        self.assertEqual(code, 400)

    def test_state_description_derived_from_card(self):
        state = self.get(self.q("/api/state"))
        desc = {t["id"]: t["description"] for t in state["manifest"]["tasks"]}
        self.assertTrue(desc["T2"].startswith("Собрать каталог и опубликовать"))
        self.assertLessEqual(len(desc["T2"]), 281)
        self.assertEqual(desc["T1"], "")  # карточки нет — fallback пуст

    def test_stories_rows_have_preview(self):
        data = self.get("/api/stories?project=testws")
        story = next(s for s in data["stories"] if s["fnr"] == "FNR_1")
        rows = {t["id"]: t for t in story["task_list"]}
        self.assertTrue(rows["T2"]["description"].startswith("Собрать каталог"))

    def test_preview_fallbacks(self):
        self.assertEqual(web.card_preview(
            "## Что сделать\n\nТекст here\n\n## Критерии\n\nx"), "Текст here")
        self.assertEqual(web.card_preview("просто абзац"), "просто абзац")
        self.assertEqual(web.card_preview("", "fb"), "fb")
        long = "слово " * 100
        out = web.card_preview(long)
        self.assertEqual(len(out), 280)
        self.assertTrue(out.endswith("…"))


class TestTaskRows(WebServerFixture):
    def test_rows_have_branch_paused_sessions(self):
        # П2: branch/paused/phase + usage.sessions в task_rows
        data = self.get("/api/stories?project=testws")
        story = next(s for s in data["stories"] if s["fnr"] == "FNR_1")
        rows = {t["id"]: t for t in story["task_list"]}
        self.assertEqual(rows["T1"]["branch"], "harness/fnr-1-a-t1")
        self.assertFalse(rows["T1"]["paused"])
        self.assertIn("sessions", rows["T2"]["usage"])
        self.assertEqual(rows["T2"]["usage"]["sessions"], 0)

    def test_state_usage_sessions(self):
        state = self.get(self.q("/api/state"))
        tasks = {t["id"]: t for t in state["manifest"]["tasks"]}
        self.assertIn("sessions", tasks["T2"]["usage"])


if __name__ == "__main__":
    unittest.main()
