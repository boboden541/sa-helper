"""Тесты переходного модуля (С1): синхронный человеческий путь, fencing, гейт."""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import db as dbmod  # noqa: E402
import state_machine as sm  # noqa: E402
import transition as tr  # noqa: E402


class TransitionFixture(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.conn = dbmod.connect(Path(self._td.name) / "t.db")
        self.ws = Path(self._td.name) / "ws"
        (self.ws / "sa_documentation" / "FNR" / "FNR_1" / "harness" / ".run").mkdir(parents=True)
        self.pid_row = dbmod.upsert_project(self.conn, "testws", str(self.ws))
        self.sid = dbmod.create_story(self.conn, self.pid_row, "FNR_1", "Тестовая", "# СТ")

    def tearDown(self):
        self.conn.close()
        self._td.cleanup()


class TestFlagToEvent(TransitionFixture):
    def test_retry_by_pipeline(self):
        task = {"pipeline": sm.BLOCKED}
        kind, event, _ = tr.flag_to_event(task, "RETRY")
        self.assertEqual((kind, event), ("event", sm.EV_RETRY))
        task = {"pipeline": sm.NEEDS_HUMAN}
        kind, event, _ = tr.flag_to_event(task, "RETRY")
        self.assertEqual((kind, event), ("event", sm.EV_RESUME_WORK))

    def test_set_actions(self):
        self.assertEqual(tr.flag_to_event({}, "PAUSE")[0], "set")
        self.assertEqual(tr.flag_to_event({}, "RESUME_WORK")[0], "set")
        self.assertEqual(tr.flag_to_event({}, "SKIP_REVIEW")[0], "set")
        self.assertEqual(tr.flag_to_event({}, "ЧТО-УГОДНО")[0], None)


class TestHumanApply(TransitionFixture):
    def _task(self, tid="T1", **v3):
        dbmod.task_create(self.conn, self.sid, {"id": tid, "title": "T"}, origin="plan")
        if v3:
            dbmod.task_set_v3(self.conn, self.sid, tid, v3)
        return tid

    def test_pause_is_sync_set(self):
        tid = self._task(pipeline="IMPLEMENTING")
        r = tr.human_apply(self.conn, self.sid, tid, "PAUSE")
        self.assertTrue(r["ok"])
        t = dbmod.read_task(self.conn, self.sid, tid, with_card=False)
        self.assertTrue(t["paused"])
        self.assertEqual(r["pipeline"], "IMPLEMENTING")

    def test_abort_from_ready(self):
        tid = self._task(pipeline="READY")
        r = tr.human_apply(self.conn, self.sid, tid, "ABORT")
        self.assertTrue(r["ok"])
        t = dbmod.read_task(self.conn, self.sid, tid, with_card=False)
        self.assertEqual(t["pipeline"], "ABORTED")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM commands").fetchone()[0], 0)
        cmt_row = self.conn.execute(
            "SELECT author FROM comments ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(cmt_row["author"], "human")

    def test_no_task(self):
        r = tr.human_apply(self.conn, self.sid, "T99", "ABORT")
        self.assertEqual(r["code"], "no_task")


class TestFence(TransitionFixture):
    def test_fence_blocks_transition(self):
        dbmod.task_create(self.conn, self.sid, {"id": "T1", "title": "T"}, origin="plan")
        dbmod.task_set_v3(self.conn, self.sid, "T1", {"pipeline": "READY"})
        dbmod.session_start(self.conn, self.sid, "T1", "implementing",
                            os.getpid(), "test", "t.log")
        r = tr.human_apply(self.conn, self.sid, "T1", "ABORT")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "fence")
        self.assertTrue(r["running"])
        self.assertIn("сессия", r["error"])

    def test_fence_not_for_set_actions(self):
        dbmod.task_create(self.conn, self.sid, {"id": "T1", "title": "T"}, origin="plan")
        dbmod.task_set_v3(self.conn, self.sid, "T1", {"pipeline": "IMPLEMENTING"})
        dbmod.session_start(self.conn, self.sid, "T1", "implementing",
                            os.getpid(), "test", "t.log")
        r = tr.human_apply(self.conn, self.sid, "T1", "PAUSE")
        self.assertTrue(r["ok"])  # PAUSE проходит и при живой сессии

    def test_dead_pid_is_not_fence(self):
        dbmod.task_create(self.conn, self.sid, {"id": "T1", "title": "T"}, origin="plan")
        dbmod.task_set_v3(self.conn, self.sid, "T1", {"pipeline": "READY"})
        dbmod.session_start(self.conn, self.sid, "T1", "implementing",
                            999999, "test", "t.log")
        r = tr.human_apply(self.conn, self.sid, "T1", "ABORT")
        self.assertTrue(r["ok"])  # мёртвый pid — сессия не живая


class TestGate(TransitionFixture):
    def test_gate_blocks_force_approve(self):
        tid = dbmod.task_create(self.conn, self.sid, {"id": "T1", "title": "T"}, origin="plan")
        dbmod.task_set_v3(self.conn, self.sid, "T1",
                          {"pipeline": "REVIEW", "review_iterations": 1})
        sec = dbmod.section_add(self.conn, self.conn.execute(
            "SELECT id FROM tasks WHERE tid=?", (tid,)).fetchone()["id"],
            "План работ (чек-лист)", kind="plan")
        dbmod.item_add(self.conn, sec, "Исправить 409", mandatory=1)
        r = tr.human_apply_event(self.conn, self.sid, "T1", sm.EV_FORCE_APPROVE, "тест")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "gate")
        self.assertIn("обязательные пункты", r["error"])

    def test_approve_passes_when_mandatory_closed(self):
        tid = dbmod.task_create(self.conn, self.sid, {"id": "T1", "title": "T"}, origin="plan")
        dbmod.task_set_v3(self.conn, self.sid, "T1", {"pipeline": "REVIEW"})
        sec = dbmod.section_add(self.conn, self.conn.execute(
            "SELECT id FROM tasks WHERE tid=?", (tid,)).fetchone()["id"],
            "План работ (чек-лист)", kind="plan")
        dbmod.item_add(self.conn, sec, "Пункт", mandatory=1)
        it = self.conn.execute(
            "SELECT id FROM checklist_items LIMIT 1").fetchone()
        dbmod.item_update(self.conn, it["id"], state="done")
        r = tr.human_apply_event(self.conn, self.sid, "T1", sm.EV_FORCE_APPROVE, "тест")
        self.assertTrue(r["ok"])
        self.assertEqual(r["pipeline"], "DONE")


class TestPreEventEffects(TransitionFixture):
    def test_retry_clears_backoff_and_escalation(self):
        dbmod.task_create(self.conn, self.sid, {"id": "T1", "title": "T"}, origin="plan")
        dbmod.task_set_v3(self.conn, self.sid, "T1",
                          {"pipeline": "BLOCKED", "retries": 2,
                           "retry_after_ts": time.time() + 999})
        dbmod.task_set_v2(self.conn, self.sid, "T1", {"status": "ESCALATED_BLOCKED"})
        task = dbmod.read_task(self.conn, self.sid, "T1", with_card=False)
        tr.pre_event_effects(self.conn, self.sid, "T1", sm.EV_RETRY, task)
        t = dbmod.read_task(self.conn, self.sid, "T1", with_card=False)
        self.assertEqual(t["retry_after_ts"], 0)
        self.assertEqual(t["v2_status"], "APPROVED")

    def test_request_changes_resets_verdict(self):
        dbmod.task_create(self.conn, self.sid, {"id": "T1", "title": "T"}, origin="plan")
        dbmod.task_set_v3(self.conn, self.sid, "T1",
                          {"pipeline": "DONE", "review_verdict": "APPROVED"})
        task = dbmod.read_task(self.conn, self.sid, "T1", with_card=False)
        tr.pre_event_effects(self.conn, self.sid, "T1", sm.EV_REQUEST_CHANGES, task)
        t = dbmod.read_task(self.conn, self.sid, "T1", with_card=False)
        self.assertIsNone(t["review_verdict"])


class TestStaleGuard(TransitionFixture):
    def test_stale_pipeline_cancels_apply(self):
        tid = dbmod.task_create(self.conn, self.sid, {"id": "T1", "title": "T"}, origin="plan")
        dbmod.task_set_v3(self.conn, self.sid, "T1", {"pipeline": "READY"})
        # двойное применение того же действия: второй вызов — отказ машины
        # состояний → web-код "noop" (идемпотентность двойного клика)
        r1 = tr.human_apply(self.conn, self.sid, "T1", "ABORT")
        self.assertTrue(r1["ok"])
        # вторая попытка того же действия: sm.transition откажет (уже ABORTED)
        r2 = tr.human_apply(self.conn, self.sid, "T1", "ABORT")
        self.assertFalse(r2["ok"])
        self.assertEqual(r2["code"], "noop")
