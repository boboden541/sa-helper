"""Тесты FNR-11: проекты (CRUD/каскад/инициализация), шлюз состава плана
(черновики, удаление, номера без переиспользования, DAG-валидация),
многослотовый decide, попытки и долг повторов."""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "web"))

import db as dbmod  # noqa: E402
import server as web  # noqa: E402
import orchestrator as orch  # noqa: E402
import state_machine as sm  # noqa: E402
import transition as tr  # noqa: E402


class ApiFixture(unittest.TestCase):
    """Витрина на эфемерном порту + временная БД + временный каталог."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.conn = dbmod.connect(Path(self._td.name) / "t.db")
        web.STATE["conn"] = self.conn
        web.STATE["default_project"] = None
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self._pcount = 0

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        web.STATE["conn"] = None
        self.conn.close()
        self._td.cleanup()

    def req(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(self.base + path, method=method, data=data,
                                   headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(r, timeout=10) as res:
                return res.status, json.loads(res.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def mk_project(self, name: str | None = None) -> tuple[int, str]:
        self._pcount += 1
        name = name or f"prj{self._pcount}"
        pdir = Path(self._td.name) / name
        pdir.mkdir(exist_ok=True)
        code, _ = self.req("POST", "/api/projects", {"name": name, "path": str(pdir)})
        assert code == 200, code
        return int(dbmod.get_project(self.conn, name)["id"]), name


class TestProjects(ApiFixture):
    def test_create_empty_dir_initializes_structure(self):
        pdir = Path(self._td.name) / "fresh"
        pdir.mkdir()
        code, doc = self.req("POST", "/api/projects",
                             {"name": "fresh", "path": str(pdir)})
        self.assertEqual(code, 200)
        self.assertTrue(doc["initialized"])
        self.assertTrue((pdir / "README.md").is_file())
        self.assertTrue((pdir / ".gitignore").is_file())
        self.assertTrue((pdir / ".git").is_dir())

    def test_create_nonempty_dir_no_init(self):
        pdir = Path(self._td.name) / "full"
        pdir.mkdir()
        (pdir / "app.py").write_text("x", encoding="utf-8")
        code, doc = self.req("POST", "/api/projects",
                             {"name": "full", "path": str(pdir)})
        self.assertEqual(code, 200)
        self.assertFalse(doc["initialized"])
        self.assertFalse((pdir / "README.md").exists())

    def test_create_nonexistent_path_rejected(self):
        code, _ = self.req("POST", "/api/projects",
                           {"name": "ghost", "path": str(Path(self._td.name) / "nope")})
        self.assertEqual(code, 400)

    def test_get_projects_includes_new_fields(self):
        pid, _ = self.mk_project("p1")
        code, doc = self.req("GET", "/api/projects")
        prj = next(p for p in doc["projects"] if p["name"] == "p1")
        self.assertIn("alias", prj)
        self.assertIn("auto_registered", prj)
        self.assertIn("deleted", prj)
        self.assertFalse(prj["auto_registered"])

    def test_patch_alias_and_description(self):
        pid, _ = self.mk_project("p2")
        code, _ = self.req("PATCH", "/api/projects/p2",
                           {"alias": "Коротко", "description": "описание"})
        self.assertEqual(code, 200)
        row = dbmod.get_project(self.conn, "p2")
        self.assertEqual(row["alias"], "Коротко")
        self.assertEqual(row["description"], "описание")
        code, _ = self.req("PATCH", "/api/projects/p2", {})
        self.assertEqual(code, 400)
        code, _ = self.req("PATCH", "/api/projects/nope", {"alias": "x"})
        self.assertEqual(code, 404)

    def test_delete_guards_and_cascade(self):
        pid, name = self.mk_project("p3")
        sid = dbmod.create_story(self.conn, pid, None, "S", "x", "task.md")
        dbmod.task_create(self.conn, sid, {"id": "T1", "title": "x"})
        # без подтверждения — 400 и масштаб каскада
        code, doc = self.req("DELETE", "/api/projects/p3", {"confirm": False})
        self.assertEqual(code, 400)
        self.assertEqual(doc["cascade"]["stories"], 1)
        self.assertEqual(doc["cascade"]["tasks"], 1)
        # с подтверждением — полный каскад
        code, doc = self.req("DELETE", "/api/projects/p3", {"confirm": True})
        self.assertEqual(code, 200)
        self.assertFalse(doc["deferred"])
        self.assertIsNone(dbmod.get_project(self.conn, "p3"))
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) c FROM stories").fetchone()["c"], 0)

    def test_delete_auto_project_requires_include_auto(self):
        a1 = Path(self._td.name) / "a1"
        a1.mkdir()
        dbmod.upsert_project(self.conn, "auto1", str(a1), auto_registered=True)
        code, _ = self.req("DELETE", "/api/projects/auto1", {"confirm": True})
        self.assertEqual(code, 409)
        code, doc = self.req("DELETE", "/api/projects/auto1",
                             {"confirm": True, "include_auto": True})
        self.assertEqual(code, 200)

    def test_delete_busy_project_deferred(self):
        pid, name = self.mk_project("busy")
        sid = dbmod.create_story(self.conn, pid, None, "S", "x", "t.md")
        dbmod.session_start(self.conn, sid, "T1", "implementing",
                            999999, "h", "x.log", attempt_uid=uuid.uuid4().hex[:8])
        code, doc = self.req("DELETE", f"/api/projects/{name}", {"confirm": True})
        self.assertEqual(code, 200)
        self.assertTrue(doc["deferred"])
        self.assertEqual(dbmod.get_project(self.conn, name)["deleted"], 1)
        # отложенный каскад: после завершения сессии проект стирается
        dbmod.session_finish(self.conn, self.conn.execute(
            "SELECT id FROM sessions").fetchone()["id"], 0, status="finished")
        dbmod.project_delete_now(self.conn, name)
        self.assertIsNone(dbmod.get_project(self.conn, name))


class TestPlanGateway(ApiFixture):
    def _story(self, status: str) -> int:
        pid, _ = self.mk_project()
        sid = dbmod.create_story(self.conn, pid, None, "S", "x", "t.md")
        with dbmod.tx(self.conn):
            self.conn.execute("UPDATE stories SET status=? WHERE id=?", (status, sid))
        return sid

    def test_derived_draft_while_awaiting_approval(self):
        sid = self._story("AWAITING_APPROVAL")
        tid = dbmod.task_create(self.conn, sid, {"title": "плановая"})
        self.assertEqual(tid, "T1")
        row = dbmod.read_task(self.conn, sid, "T1", with_card=False)
        self.assertEqual(row["pipeline"], "PROPOSED")   # черновик, не бэклог
        tid2 = dbmod.task_create(self.conn, sid, {"title": "из очереди"},
                                 origin="manual")
        row2 = dbmod.read_task(self.conn, sid, tid2, with_card=False)
        self.assertEqual(row2["pipeline"], "PROPOSED")  # и из очереди — черновик

    def test_normal_story_backlog_unchanged(self):
        sid = self._story("PLANNED")
        tid = dbmod.task_create(self.conn, sid, {"title": "плановая"})
        row = dbmod.read_task(self.conn, sid, tid, with_card=False)
        self.assertEqual(row["pipeline"], "BACKLOG")
        tid2 = dbmod.task_create(self.conn, sid, {"title": "агентская"},
                                 origin="agent")
        row2 = dbmod.read_task(self.conn, sid, tid2, with_card=False)
        self.assertEqual(row2["pipeline"], "PROPOSED")

    def test_delete_draft_archives_and_frees_deps(self):
        sid = self._story("AWAITING_APPROVAL")
        dbmod.task_create(self.conn, sid, {"id": "T1", "title": "удаляемая"})
        dbmod.task_create(self.conn, sid, {"id": "T2", "title": "зависимая",
                                           "depends_on": ["T1"]})
        dbmod.append_comment(self.conn, sid, "T1", "agent", "диалог задачи")
        ok, freed, archived = dbmod.task_delete_draft(self.conn, sid, "T1")
        self.assertTrue(ok)
        self.assertEqual(freed, ["T2"])
        self.assertGreaterEqual(archived, 1)
        self.assertIsNone(dbmod.read_task(self.conn, sid, "T1", with_card=False))
        # зависимая задача жива и свободна от предка
        self.assertIsNotNone(dbmod.read_task(self.conn, sid, "T2", with_card=False))

    def test_task_seq_no_reuse(self):
        sid = self._story("AWAITING_APPROVAL")
        t1 = dbmod.task_create(self.conn, sid, {"title": "a"})
        ok, _, _ = dbmod.task_delete_draft(self.conn, sid, t1)
        self.assertTrue(ok)
        t2 = dbmod.task_create(self.conn, sid, {"title": "b"})
        self.assertNotEqual(t1, t2)          # номер не переиспользуется
        self.assertEqual(t2, "T2")

    def test_dep_validation(self):
        sid = self._story("PLANNED")
        with self.assertRaises(ValueError):  # предок не существует (назад)
            dbmod.task_create(self.conn, sid,
                              {"id": "T5", "title": "x", "depends_on": ["T2"]})
        # ссылка вперёд внутри одного плана — допустима
        dbmod.task_create(self.conn, sid,
                          {"id": "T1", "title": "ранняя", "depends_on": ["T2"]})
        dbmod.task_create(self.conn, sid, {"id": "T2", "title": "поздняя"})
        dbmod.task_create(self.conn, sid,
                          {"id": "T3", "title": "c", "depends_on": ["T4"]})
        with self.assertRaises(ValueError):  # цикл T4→T3 (цепочка замыкается)
            dbmod.task_create(self.conn, sid,
                              {"id": "T4", "title": "d", "depends_on": ["T3"]})


class TestMultiSlotDecide(unittest.TestCase):
    """Снимки решений: K=1 ≡ однослотовое поведение, K=2 — два старта."""

    @staticmethod
    def _manifest(pipelines: dict[str, str]) -> dict:
        return {"fnr_id": "FNR_X", "status": "APPROVED",
                "auto_review_strategy": "closure_first",
                "circuit_breaker": {"max_iterations_per_task": 4},
                "tasks": [{"id": tid, "pipeline": p, "status": "APPROVED",
                           "depends_on": [], "paused": False,
                           "skip_review": False, "origin": "plan",
                           "decomposed": False, "retries": 0, "retry_debt": 0,
                           "review_iterations": 0, "retry_after_ts": 0,
                           "review_verdict": None}
                          for tid, p in pipelines.items()]}

    @staticmethod
    def _state(k: int) -> dict:
        return {"lane_free": True, "running_task_id": None, "running_ids": [],
                "max_parallel": k, "now": time.time(),
                "verification_report": False, "verify_attempted": False,
                "max_retries": 3, "orphan_running": False}

    def test_k1_single_start(self):
        d = orch.decide(self._manifest({"T1": "READY", "T2": "READY"}), set(),
                        self._state(1))
        starts = [x for x in d if x[0] == "stage"]
        self.assertEqual(len(starts), 1)

    def test_k2_parallel_starts(self):
        d = orch.decide(self._manifest({"T1": "READY", "T2": "READY"}), set(),
                        self._state(2))
        starts = [x for x in d if x[0] == "stage"]
        self.assertEqual(len(starts), 2)

    def test_verify_waits_for_slots(self):
        m = self._manifest({"T1": "DONE", "T2": "DONE"})
        state = self._state(2)
        state["verification_report"] = True
        state["running_ids"] = ["T9"]
        d = orch.decide(m, set(), state)
        self.assertNotIn("stage", [x[0] for x in d])

    def test_retry_debt_in_escalation(self):
        m = self._manifest({"T1": "BLOCKED"})
        m["tasks"][0]["retries"] = 2
        m["tasks"][0]["retry_debt"] = 1
        state = self._state(1)
        d = orch.decide(m, set(), state)
        escalations = [x for x in d
                       if x[0] == "event" and x[2] == sm.EV_BLOCKED_ESCALATED]
        self.assertEqual(len(escalations), 1)  # 2 + 1 >= 3 → карантин-эскалация


class TestRecoveryPolicies(ApiFixture):
    def test_attempt_uid_persisted(self):
        pid, _ = self.mk_project()
        sid = dbmod.create_story(self.conn, pid, None, "S", "x", "t.md")
        row = dbmod.session_start(self.conn, sid, "T1", "implementing",
                                  1, "h", "x.log", attempt_uid=uuid.uuid4().hex[:12])
        got = self.conn.execute("SELECT attempt_uid FROM sessions WHERE id=?",
                                (row,)).fetchone()["attempt_uid"]
        self.assertTrue(got)

    def test_retry_debt_accumulates_and_resets(self):
        pid, _ = self.mk_project()
        sid = dbmod.create_story(self.conn, pid, None, "S", "x", "t.md")
        dbmod.task_create(self.conn, sid, {"id": "T1", "title": "x"})
        task = dbmod.read_task(self.conn, sid, "T1", with_card=False)
        task["id"] = "T1"
        tr.pre_event_effects(self.conn, sid, "T1", sm.EV_IMPL_BLOCKED, task)
        task = dbmod.read_task(self.conn, sid, "T1", with_card=False)  # тик: перечитано
        task["id"] = "T1"
        tr.pre_event_effects(self.conn, sid, "T1", sm.EV_IMPL_BLOCKED, task)
        row = self.conn.execute("SELECT retry_debt FROM tasks WHERE story_id=? AND tid=?",
                                (sid, "T1")).fetchone()
        self.assertEqual(row["retry_debt"], 2)   # копится между эпизодами
        tr.pre_event_effects(self.conn, sid, "T1", sm.EV_VERIFY_PASSED, task)
        row = self.conn.execute("SELECT retry_debt FROM tasks WHERE story_id=? AND tid=?",
                                (sid, "T1")).fetchone()
        self.assertEqual(row["retry_debt"], 0)   # обнуляется полным завершением


if __name__ == "__main__":
    unittest.main()


class TestReadableTail(unittest.TestCase):
    """Хроника сессии: мышление (🧠) и промпт (📋) видны человеку (СТ 5.1.2/прозрачность)."""

    def test_thinking_prompt_and_tools_visible(self):
        import server as web2
        log = Path(tempfile.mkdtemp()) / "s.log"
        recs = [
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "text", "text": "/impl-review sa_documentation/FNR T12"}]}},
            {"type": "assistant", "message": {"content": [
                {"type": "thinking", "thinking": "Начну с предусловий ревью."},
                {"type": "tool_use", "name": "Bash", "input": {"command": "ls", "description": "список"}},
                {"type": "text", "text": "Проверяю дельту."}]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "c1", "content": "файлы"}]}},
        ]
        log.write_text("\n".join(json.dumps(r) for r in recs), encoding="utf-8")
        out = web._readable_tail(log)
        self.assertIn("📋 Промпт:", out)
        self.assertIn("/impl-review", out)
        self.assertIn("🧠 Начну с предусловий", out)
        self.assertIn("🔧 Bash: список", out)
        self.assertIn("🤖 Проверяю дельту.", out)
        # tool_result не должен попасть как промпт
        self.assertNotIn("файлы", out.split("\n")[0])
