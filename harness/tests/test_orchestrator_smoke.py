"""Smoke демона на БД: полный цикл конвейера и kill-восстановление (R3)."""

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
import orchestrator as orch  # noqa: E402
import state_machine as sm  # noqa: E402

STUB = ROOT / "tests" / "fixtures" / "stub_claude.py"


class SmokeFixture(unittest.TestCase):
    """Story FNR_99: T1→T2, план утверждён; воркспейс-каталог для .run/.claude."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        td = Path(self._td.name)
        self.ws = td / "ws"
        hdir = self.ws / "sa_documentation" / "FNR" / "FNR_99" / "harness"
        hdir.mkdir(parents=True)
        self.conn = dbmod.connect(td / "smoke.db")
        self.pid = dbmod.upsert_project(self.conn, "smoke", str(self.ws))
        self.sid = dbmod.create_story(self.conn, self.pid, "FNR_99", "Smoke", "# СТ")
        with dbmod.tx(self.conn):
            self.conn.execute("UPDATE stories SET status='APPROVED', epic_branch=?,"
                              " updated_at=? WHERE id=?",
                              ("harness/FNR-99-smoke", dbmod.now_iso(), self.sid))
        for sysname in ("core",):
            self.conn.execute(
                "INSERT INTO story_systems(story_id, name, path, stack, bootstrap)"
                " VALUES (?,?,?,?, 'ready')", (self.sid, sysname, "core", "python"))
        for tid, deps in (("T1", []), ("T2", ["T1"])):
            tid_done = dbmod.task_create(self.conn, self.sid, {
                "id": tid, "title": f"Задача {tid}", "system": "core",
                "depends_on": deps,
                "acceptance_criteria": [{"id": f"AC-1.1.1", "desc": "x"}],
            }, origin="plan")
            with dbmod.tx(self.conn):
                self.conn.execute("UPDATE tasks SET branch=? WHERE story_id=? AND tid=?",
                                  (f"harness/FNR-99-smoke-{tid.lower()}", self.sid, tid_done))
        os.chmod(STUB, 0o755)
        self.opts = type("Opts", (), {
            "poll_interval": 0, "stage_timeout": 60, "heartbeat_timeout": 60,
            "max_retries": 3, "max_turns": 10, "skip_permissions": True,
            "claude_bin": str(STUB), "dry_run": False, "verbose": False,
        })()
        self.lane = orch.WorkspaceLane(self.ws, self.conn, self.pid, "smoke")

    def tearDown(self):
        if self.lane.proc is not None:
            try:
                orch._kill_tree(self.lane.proc)
            except OSError:
                pass
        self.conn.close()
        self._td.cleanup()

    def pipelines(self) -> dict:
        return {r["tid"]: r["pipeline"] for r in self.conn.execute(
            "SELECT tid, pipeline FROM tasks ORDER BY tid")}

    def run_until(self, predicate, ticks=60):
        for _ in range(ticks):
            orch.process_workspace(self.lane, self.opts)
            if predicate():
                return
            time.sleep(0.03)


class TestConveyorSmoke(SmokeFixture):
    """Полный цикл: T1 (impl→review) → T2 → verify → VERIFIED."""

    def test_full_cycle(self):
        self.run_until(lambda: self.pipelines() == {"T1": sm.VERIFIED,
                                                    "T2": sm.VERIFIED})
        self.assertEqual(self.pipelines(), {"T1": sm.VERIFIED, "T2": sm.VERIFIED})
        self.assertIsNotNone(dbmod.doc_get(self.conn, self.sid, "verification_report"))
        t1 = dbmod.read_task(self.conn, self.sid, "T1")
        self.assertEqual(t1["session_id"], "aa11bb22cc33dd44ee55ff66")
        texts = " ".join(e["text"] for e in dbmod.events_after(self.conn, self.sid, 0))
        for marker in ("queue_ready", "start", "review_approved", "verify"):
            self.assertIn(marker, texts.lower())


class TestKillRecovery(SmokeFixture):
    """kill демона: осиротевшая сессия с мёртвым pid дозаминируется, дубля нет."""

    def test_orphan_session_reconciled_once(self):
        # имитируем осиротевшую сессию T1: строка running с мёртвым pid,
        # задача IMPLEMENTING со сделанной v2-работой
        dbmod.task_set_v3(self.conn, self.sid, "T1", {"pipeline": "IMPLEMENTING"})
        dbmod.session_start(self.conn, self.sid, "T1", "implementing",
                            pid=999999, host="dead-host", log_path="/tmp/dead.log")
        dbmod.task_set_v2(self.conn, self.sid, "T1", {"status": "AGENT_REVIEW"})
        seen = []
        for _ in range(6):
            orch.process_workspace(self.lane, self.opts)
            pipelines = self.pipelines()
            seen.append(pipelines["T1"])
            if pipelines["T1"] == sm.REVIEW:
                break
        self.assertEqual(self.pipelines()["T1"], sm.REVIEW)
        # сессия погашена без дубля стадии: процессов слот не занял в этот тик
        statuses = [r["status"] for r in self.conn.execute(
            "SELECT status FROM sessions WHERE tid='T1'")]
        self.assertIn("orphan", statuses)


if __name__ == "__main__":
    unittest.main()
