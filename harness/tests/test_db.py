"""Тесты слоя доступа БД (порция R1): схема, владение, команды, события, карточка."""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import db as dbmod  # noqa: E402
import cards  # noqa: E402
import state_machine as sm  # noqa: E402
import orchestrator as orch  # noqa: E402


class DbFixture(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.conn = dbmod.connect(os.path.join(self._td.name, "t.db"))
        self.pid = dbmod.upsert_project(self.conn, "test", "/tmp/ws_test")
        self.sid = dbmod.create_story(self.conn, self.pid, None, "Тестовая", "# СТ")

    def tearDown(self):
        self.conn.close()
        self._td.cleanup()

    def mk_task(self, tid="T1", title="Задача", origin="plan"):
        return dbmod.task_create(self.conn, self.sid,
                                 {"id": tid, "title": title}, origin=origin)


class TestProjectsStories(DbFixture):
    def test_story_create_auto_fnr(self):
        sid2 = dbmod.create_story(self.conn, self.pid, None, "Вторая", "")
        self.assertEqual(
            self.conn.execute("SELECT fnr FROM stories WHERE id=?", (sid2,)).fetchone()[0],
            "FNR_2")

    def test_story_pause_and_status_guards(self):
        self.assertFalse(dbmod.story_set_status(self.conn, self.sid,
                                                "AWAITING_APPROVAL", by="session"))
        self.assertTrue(dbmod.story_set_status(self.conn, self.sid,
                                               "PLANNED", by="daemon"))
        self.assertTrue(dbmod.story_set_status(self.conn, self.sid,
                                               "AWAITING_APPROVAL", by="session"))
        self.assertFalse(dbmod.story_set_status(self.conn, self.sid,
                                                "AWAITING_APPROVAL", by="session"))
        dbmod.story_pause(self.conn, self.sid, True)
        self.assertIn("PAUSE", dbmod.pending_flags_view(self.conn, self.sid))


class TestTaskOwnership(DbFixture):
    def test_v2_domain_session_only(self):
        self.mk_task()
        self.assertTrue(dbmod.task_set_v2(self.conn, self.sid, "T1",
                                          {"status": "TDD_RED", "iteration_count": 2}))
        row = self.conn.execute("SELECT v2_status, iteration_count FROM tasks"
                                " WHERE tid='T1'").fetchone()
        self.assertEqual((row["v2_status"], row["iteration_count"]), ("TDD_RED", 2))

    def test_v2_cannot_touch_v3(self):
        self.mk_task()
        self.assertFalse(dbmod.task_set_v2(self.conn, self.sid, "T1",
                                           {"pipeline": "REVIEW"}))

    def test_v3_set_by_daemon(self):
        self.mk_task()
        dbmod.task_set_v3(self.conn, self.sid, "T1",
                          {"pipeline": "REVIEW", "review_iterations": 2})
        row = self.conn.execute("SELECT pipeline, review_iterations FROM tasks"
                                " WHERE tid='T1'").fetchone()
        self.assertEqual(row["pipeline"], "REVIEW")

    def test_card_version_conflict(self):
        self.mk_task()
        ok, v = dbmod.task_set_card(self.conn, self.sid, "T1", "первая")
        self.assertTrue(ok)
        ok, cur = dbmod.task_set_card(self.conn, self.sid, "T1", "вторая",
                                      expect_version=v - 1)
        self.assertFalse(ok)
        ok, _ = dbmod.task_set_card(self.conn, self.sid, "T1", "третья",
                                    expect_version=cur)
        self.assertTrue(ok)

    def test_task_create_validates_dup_and_origin(self):
        self.mk_task("T1")
        with self.assertRaises(ValueError):
            dbmod.task_create(self.conn, self.sid, {"id": "T1", "title": "дубль"})
        tid = dbmod.task_create(self.conn, self.sid,
                                {"title": "агентская"}, origin="agent")
        row = self.conn.execute("SELECT pipeline FROM tasks WHERE tid=?",
                                (tid,)).fetchone()
        self.assertEqual(row["pipeline"], "PROPOSED")

    def test_read_task_aggregates(self):
        self.mk_task("T2")
        dbmod.task_set_v2(self.conn, self.sid, "T2", {"status": "DONE"})
        t = dbmod.read_task(self.conn, self.sid, "T2")
        self.assertEqual(t["v2_status"], "DONE")
        self.assertEqual(t["gates"], {"build": "pending", "test": "pending",
                                      "lint": "pending", "coverage": "pending",
                                      "review": "pending"})
        self.assertEqual(t["depends_on"], [])


class TestCommandsEvents(DbFixture):
    def test_commands_consumed_once(self):
        self.mk_task()
        dbmod.insert_command(self.conn, self.sid, "TASK_T1_RETRY")
        dbmod.insert_command(self.conn, self.sid, "APPROVE_PLAN")
        names = [c["name"] for c in dbmod.consume_commands(self.conn, self.sid)]
        self.assertEqual(sorted(names), ["APPROVE_PLAN", "TASK_T1_RETRY"])
        self.assertEqual(dbmod.consume_commands(self.conn, self.sid), [])

    def test_delete_pending_command(self):
        self.mk_task()
        dbmod.insert_command(self.conn, self.sid, "PAUSE")
        dbmod.delete_pending_command(self.conn, self.sid, "PAUSE")
        self.assertEqual(dbmod.pending_flags_view(self.conn, self.sid), set())

    def test_events_cursor(self):
        self.mk_task()
        a = dbmod.append_event(self.conn, self.sid, "T1", "раз")
        dbmod.append_event(self.conn, self.sid, "T1", "два")
        fresh = dbmod.events_after(self.conn, self.sid, a)
        self.assertEqual([e["text"] for e in fresh], ["два"])

    def test_usage_increment_on_session_finish(self):
        self.mk_task()
        s = dbmod.session_start(self.conn, self.sid, "T1", "implementing",
                                pid=999999, host="h", log_path="/tmp/x.log")
        dbmod.session_finish(self.conn, s, 0, usage={
            "tokens_in": 10, "tokens_out": 5, "tokens_total": 15, "cost_usd": 0.5})
        row = self.conn.execute("SELECT usage_tokens_total, usage_cost_usd,"
                                " usage_sessions FROM tasks WHERE tid='T1'").fetchone()
        self.assertEqual((row["usage_tokens_total"], row["usage_cost_usd"],
                          row["usage_sessions"]), (15, 0.5, 1))

    def test_dangling_dep_blocked_by_fk(self):
        # несуществующая зависимость отсекается самой схемой (FK)
        self.mk_task("T1")
        with self.assertRaises(sqlite3.IntegrityError):
            with dbmod.tx(self.conn):
                self.conn.execute("INSERT INTO task_deps(story_id, tid, dep_tid)"
                                  " VALUES (?,?,?)", (self.sid, "T1", "T9"))

    def test_cycle_detected_by_validate(self):
        self.mk_task("T1")
        self.mk_task("T2")
        with dbmod.tx(self.conn):
            self.conn.execute("INSERT INTO task_deps VALUES (?,?,?)",
                              (self.sid, "T1", "T2"))
            self.conn.execute("INSERT INTO task_deps VALUES (?,?,?)",
                              (self.sid, "T2", "T1"))
        out = dbmod.validate_story(self.conn, self.sid)
        self.assertFalse(out["valid"])
        self.assertTrue(any("цикл" in e for e in out["errors"]))


class TestCardsCommon(DbFixture):
    def test_cards_canon_shared(self):
        self.assertEqual(
            cards.parse_checklist_sections("## План работ (чек-лист)\n\n- [x] a\n")[0]["done"], 1)
        self.assertEqual(cards.card_preview("## Что сделать\n\nТекст", "fb"), "Текст")


if __name__ == "__main__":
    unittest.main()


class TestChecklistGate(unittest.TestCase):
    """Гейт чек-листа: открытые mandatory в plan-секции блокируют approve."""

    def setUp(self):
        import tempfile
        self._td = tempfile.TemporaryDirectory()
        self.conn = dbmod.connect(os.path.join(self._td.name, "g.db"))
        self.pid = dbmod.upsert_project(self.conn, "t", "/tmp/g")
        self.sid = dbmod.create_story(self.conn, self.pid, "FNR_1", "Т", "")
        tid = dbmod.task_create(self.conn, self.sid,
                                {"id": "T1", "title": "A"}, origin="plan")
        dbmod.task_set_v3(self.conn, self.sid, tid, {"pipeline": "REVIEW"})
        dbmod.task_set_v2(self.conn, self.sid, tid, {"status": "AGENT_REVIEW"})
        sec = dbmod.section_add(self.conn, self.conn.execute(
            "SELECT id FROM tasks WHERE tid=?", (tid,)).fetchone()["id"],
            "План работ (чек-лист)", kind="plan")
        self.item_id = dbmod.item_add(self.conn, sec, "финальный прогон",
                                      state="inprog", mandatory=True)
        self.tid = tid

    def tearDown(self):
        self.conn.close()
        self._td.cleanup()

    def test_gate_blocks_approve_while_mandatory_open(self):
        ok = orch.apply_transition(self.conn, self.sid, self.tid,
                                   sm.EV_REVIEW_APPROVED, "вердикт APPROVED")
        self.assertFalse(ok)
        row = self.conn.execute("SELECT pipeline FROM tasks WHERE tid=?",
                                (self.tid,)).fetchone()
        self.assertEqual(row["pipeline"], "REVIEW")
        # закрыли mandatory — approve проходит
        dbmod.item_update(self.conn, self.item_id, state="done")
        ok = orch.apply_transition(self.conn, self.sid, self.tid,
                                   sm.EV_REVIEW_APPROVED, "вердикт APPROVED")
        self.assertTrue(ok)
        row = self.conn.execute("SELECT pipeline FROM tasks WHERE tid=?",
                                (self.tid,)).fetchone()
        self.assertEqual(row["pipeline"], "DONE")

    def test_gate_blocks_on_review_mandatory(self):
        # С4: незакрытый mandatory чек-листа ревьюера тоже блокирует approve
        dbmod.item_update(self.conn, self.item_id, state="done")  # план закрыт
        sec = dbmod.section_add(self.conn, self.conn.execute(
            "SELECT id FROM tasks WHERE tid=?", (self.tid,)).fetchone()["id"],
            "Ревью (чек-лист)", kind="review")
        rv = dbmod.item_add(self.conn, sec, "проверена обработка 409", state="todo",
                            mandatory=True)
        ok = orch.apply_transition(self.conn, self.sid, self.tid,
                                   sm.EV_REVIEW_APPROVED, "вердикт APPROVED")
        self.assertFalse(ok)
        row = self.conn.execute("SELECT pipeline FROM tasks WHERE tid=?",
                                (self.tid,)).fetchone()
        self.assertEqual(row["pipeline"], "REVIEW")
        # ревьюер закрыл свой пункт — approve проходит
        dbmod.item_update(self.conn, rv, state="done")
        ok = orch.apply_transition(self.conn, self.sid, self.tid,
                                   sm.EV_REVIEW_APPROVED, "вердикт APPROVED")
        self.assertTrue(ok)
