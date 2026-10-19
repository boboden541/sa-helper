"""Story/бэклог на БД: ручные задачи, предложения, правка описания, usage (R3)."""

from __future__ import annotations

import json
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


class StoriesFixture(unittest.TestCase):
    """Story FNR_1 (T1 DONE; план утверждён, конвейер ждёт работу)."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        td = Path(self._td.name)
        self.ws = td / "ws"
        hdir = self.ws / "sa_documentation" / "FNR" / "FNR_1" / "harness"
        hdir.mkdir(parents=True)
        self.conn = dbmod.connect(td / "s.db")
        self.pid = dbmod.upsert_project(self.conn, "test", str(self.ws))
        self.sid = dbmod.create_story(self.conn, self.pid, "FNR_1", "Демо", "# СТ")
        with dbmod.tx(self.conn):
            self.conn.execute("UPDATE stories SET status='APPROVED', epic_branch=?,"
                              " updated_at=? WHERE id=?",
                              ("harness/FNR-1-demo", dbmod.now_iso(), self.sid))
        self.conn.execute("INSERT INTO story_systems(story_id, name, path, stack,"
                          " bootstrap) VALUES (?,?,?,?, 'ready')",
                          (self.sid, "core", "core", "python"))
        t1 = dbmod.task_create(self.conn, self.sid, {
            "id": "T1", "title": "A", "system": "core",
            "acceptance_criteria": [{"id": "AC-1.1.1", "desc": "x"}]}, origin="plan")
        dbmod.task_set_v3(self.conn, self.sid, t1, {"pipeline": "DONE"})
        dbmod.task_set_v2(self.conn, self.sid, t1, {"status": "DONE"})
        self.opts = type("Opts", (), {
            "poll_interval": 0, "stage_timeout": 60, "heartbeat_timeout": 60,
            "max_retries": 3, "max_turns": 10, "skip_permissions": True,
            "claude_bin": str(ROOT / "tests" / "fixtures" / "stub_claude.py"), "dry_run": False, "verbose": False,
        })()
        self.lane = orch.WorkspaceLane(self.ws, self.conn, self.pid, "test")

    def tearDown(self):
        if self.lane.proc is not None:
            try:
                orch._kill_tree(self.lane.proc)
            except OSError:
                pass
        self.conn.close()
        self._td.cleanup()

    def tick(self):
        orch.process_workspace(self.lane, self.opts)


class TestManualTask(StoriesFixture):
    def test_task_new_command_creates_task_and_card(self):
        dbmod.insert_command(self.conn, self.sid, "task.new", {
            "title": "Ручная", "description": "делать хорошо",
            "system": "core", "acceptance": ["работает"]}, by="human")
        self.tick()
        row = self.conn.execute("SELECT pipeline, card_md FROM tasks WHERE tid='T2'").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["pipeline"], "PROPOSED")
        self.assertIn("| Система | core |", row["card_md"])
        self.assertIn("## Что сделать", row["card_md"])
        self.assertIn("делать хорошо", row["card_md"])

    def test_task_new_rejected_on_unknown_dep(self):
        before = self.conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        dbmod.insert_command(self.conn, self.sid, "task.new", {
            "title": "X", "depends_on": ["T99"]}, by="human")
        self.tick()
        after = self.conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        self.assertEqual(before, after)


class TestProposedFlags(StoriesFixture):
    def test_accept_and_reject_flags(self):
        tid = dbmod.task_create(self.conn, self.sid,
                                {"title": "Предложение агента"}, origin="agent")
        row = self.conn.execute("SELECT pipeline FROM tasks WHERE tid=?",
                                (tid,)).fetchone()
        self.assertEqual(row["pipeline"], "PROPOSED")
        dbmod.insert_command(self.conn, self.sid, f"TASK_{tid}_REJECT", by="human")
        self.tick()
        row = self.conn.execute("SELECT pipeline FROM tasks WHERE tid=?",
                                (tid,)).fetchone()
        self.assertEqual(row["pipeline"], "ABORTED")


class TestTaskEdit(StoriesFixture):
    def test_edit_desc_updates_description_and_card_section(self):
        dbmod.task_set_card(self.conn, self.sid, "T1",
                            "# T1\n\n## Что сделать\n\nСтарое описание.\n")
        dbmod.insert_command(self.conn, self.sid, "task.edit_desc", {
            "task_id": "T1", "description": "Новое описание задачи"}, by="human")
        self.tick()
        row = self.conn.execute("SELECT description, card_md FROM tasks WHERE tid='T1'").fetchone()
        self.assertIn("Новое описание задачи", row["description"])
        self.assertIn("Новое описание задачи", row["card_md"])
        self.assertNotIn("Старое описание.", row["card_md"])
        comment = self.conn.execute(
            "SELECT body FROM comments WHERE tid='T1' AND author='daemon'").fetchone()
        self.assertIsNotNone(comment)


class TestUsage(unittest.TestCase):
    """Расход сессии из result-события stream-лога (канон G2)."""

    def test_pick_usage_parses_result(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "T1_implementing_77.log"
            stream = "".join([
                json.dumps({"type": "assistant", "message": {"content": []}}) + "\n",
                json.dumps({"type": "result", "duration_ms": 60000,
                            "total_cost_usd": 0.42,
                            "usage": {"input_tokens": 1000,
                                      "cache_read_input_tokens": 5000,
                                      "cache_creation_input_tokens": 200,
                                      "output_tokens": 300}}) + "\n",
            ])
            log.write_text(stream, encoding="utf-8")
            u = orch._pick_usage(log)
            self.assertEqual(u["tokens_in"], 6200)
            self.assertEqual(u["tokens_out"], 300)
            self.assertEqual(u["tokens_total"], 6500)
            self.assertAlmostEqual(u["cost_usd"], 0.42, places=3)


class TestAttachmentsRegex(unittest.TestCase):
    def test_safe_name(self):
        sys.path.insert(0, str(ROOT / "web"))
        import server as ui
        self.assertEqual(ui.ATTACHMENT_NAME_RE.sub("_", "../etc/passwd"), ".._etc_passwd")
        self.assertEqual(ui.ATTACHMENT_NAME_RE.sub("_", "отчёт май.csv"), "отчёт_май.csv")


if __name__ == "__main__":
    unittest.main()
