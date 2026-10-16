"""Порция F: Story и бэклог — ручные задачи, предложения, handoff-очередь."""

from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import orchestrator as orch  # noqa: E402
import state_machine as sm  # noqa: E402

STUB = ROOT / "tests" / "fixtures" / "stub_claude.py"


def sandbox(tmp: Path, approved: bool = False) -> tuple[Path, Path]:
    """Воркспейс с одной Story FNR_1 (T1; план утверждён опционально)."""
    ws = tmp / "ws"
    harness = ws / "sa_documentation" / "FNR" / "FNR_1" / "harness"
    (harness / ".flags").mkdir(parents=True)
    manifest = {"fnr_id": "FNR_1", "status": "APPROVED" if approved else "AWAITING_APPROVAL",
                "epic_branch": "harness/FNR-1-demo",
                "systems": [{"name": "core", "path": "core", "stack": "python",
                             "bootstrap": "ready"}],
                "tasks": [{"id": "T1", "title": "A", "system": "core", "phase": "regular",
                           "branch": "harness/FNR-1-demo-t1", "status": "PLANNED",
                           "depends_on": [], "fr_ids": ["FR-1.1"],
                           "acceptance_criteria": [
                               {"id": "AC-1.1.1", "desc": "x", "status": "PENDING"}]}]}
    (harness / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return ws, harness


class TestManualTask(unittest.TestCase):
    def test_task_new_flag_creates_task_and_card(self):
        with tempfile.TemporaryDirectory() as td:
            ws, harness = sandbox(Path(td))
            (harness / ".flags" / "TASK_NEW_1.json").write_text(json.dumps({
                "title": "Реестр отчётов", "system": "core",
                "description": "Добавить таблицу отчётов",
                "depends_on": ["T1"], "acceptance": ["Таблица создана"],
            }), encoding="utf-8")

            class Opts:
                poll_interval = 0
                stage_timeout = 60
                heartbeat_timeout = 60
                max_retries = 3
                max_turns = 10
                skip_permissions = True
                claude_bin = str(STUB)
                dry_run = False
                verbose = False

            lane = orch.WorkspaceLane(ws)
            for _ in range(6):
                orch.process_workspace(lane, Opts)
                time.sleep(0.02)

            doc = json.loads((harness / "manifest.json").read_text(encoding="utf-8"))
            t2 = [t for t in doc["tasks"] if t["id"] == "T2"]
            self.assertEqual(len(t2), 1)
            self.assertEqual(t2[0]["pipeline"], sm.BACKLOG)
            self.assertEqual(t2[0]["origin"], "manual")
            self.assertEqual(t2[0]["depends_on"], ["T1"])
            self.assertTrue((harness / "tasks" / "T2.md").exists())
            self.assertFalse((harness / ".flags" / "TASK_NEW_1.json").exists())
            journal = (harness / "comments" / "T2.md").read_text(encoding="utf-8")
            self.assertIn("добавлена вручную", journal)

    def test_task_new_rejected_on_unknown_dep(self):
        with tempfile.TemporaryDirectory() as td:
            ws, harness = sandbox(Path(td))
            (harness / ".flags" / "TASK_NEW_1.json").write_text(json.dumps({
                "title": "X", "system": "core", "depends_on": ["T99"],
            }), encoding="utf-8")

            class Opts:
                poll_interval = 0
                stage_timeout = 60
                heartbeat_timeout = 60
                max_retries = 3
                max_turns = 10
                skip_permissions = True
                claude_bin = str(STUB)
                dry_run = False
                verbose = False

            orch.process_workspace(orch.WorkspaceLane(ws), Opts)
            doc = json.loads((harness / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(len(doc["tasks"]), 1)  # T99 не существует — задача не создана
            self.assertFalse((harness / ".flags" / "TASK_NEW_1.json").exists())


class TestProposedFlags(unittest.TestCase):
    def test_accept_and_reject_flags(self):
        with tempfile.TemporaryDirectory() as td:
            ws, harness = sandbox(Path(td))
            doc = json.loads((harness / "manifest.json").read_text(encoding="utf-8"))
            doc["tasks"].append({"id": "T2", "title": "Предложение агента", "system": "core",
                                 "phase": "regular", "branch": "harness/FNR-1-demo-t2",
                                 "status": "PLANNED", "pipeline": "PROPOSED",
                                 "depends_on": [], "fr_ids": [], "origin": "agent",
                                 "acceptance_criteria": [
                                     {"id": "AC-2.1", "desc": "x", "status": "PENDING"}]})
            (harness / "manifest.json").write_text(json.dumps(doc), encoding="utf-8")
            (harness / ".flags" / "TASK_T2_ACCEPT").touch()

            class Opts:
                poll_interval = 0
                stage_timeout = 60
                heartbeat_timeout = 60
                max_retries = 3
                max_turns = 10
                skip_permissions = True
                claude_bin = str(STUB)
                dry_run = False
                verbose = False

            lane = orch.WorkspaceLane(ws)
            for _ in range(4):
                orch.process_workspace(lane, Opts)
                time.sleep(0.02)
            doc = json.loads((harness / "manifest.json").read_text(encoding="utf-8"))
            t2 = [t for t in doc["tasks"] if t["id"] == "T2"][0]
            self.assertEqual(t2["pipeline"], sm.BACKLOG)

    def test_agent_task_without_pipeline_migrates_to_proposed(self):
        with tempfile.TemporaryDirectory() as td:
            ws, harness = sandbox(Path(td))
            doc = json.loads((harness / "manifest.json").read_text(encoding="utf-8"))
            doc["tasks"].append({"id": "T2", "title": "От агента", "system": "core",
                                 "status": "PLANNED", "origin": "agent", "depends_on": [],
                                 "fr_ids": [], "acceptance_criteria": []})
            self.assertTrue(orch.migrate_task_pipeline(doc["tasks"][1]))
            self.assertEqual(doc["tasks"][1]["pipeline"], sm.PROPOSED)


class TestHandoffQueue(unittest.TestCase):
    def test_pending_handoff_discovered_and_spawned(self):
        import os
        with tempfile.TemporaryDirectory() as td:
            ws, harness = sandbox(Path(td))
            # вторая Story без манифеста, с handoff-флагом и СТ
            h2 = ws / "sa_documentation" / "FNR" / "FNR_2" / "harness"
            (h2 / ".flags").mkdir(parents=True)
            (h2 / ".flags" / "HANDOFF").write_text("{}", encoding="utf-8")
            (ws / "sa_documentation" / "FNR" / "FNR_2" / "system_requirements.md").write_text(
                "# СТ\n", encoding="utf-8")
            self.assertEqual([p.parent.name for p in orch.find_pending_handoffs(ws)], ["FNR_2"])

            os.chmod(STUB, 0o755)

            class Opts:
                poll_interval = 0
                stage_timeout = 60
                heartbeat_timeout = 60
                max_retries = 3
                max_turns = 10
                skip_permissions = True
                claude_bin = str(STUB)
                dry_run = False
                verbose = False

            lane = orch.WorkspaceLane(ws)
            orch.process_workspace(lane, Opts)
            self.assertIsNotNone(lane.proc)
            self.assertEqual(lane.stage, "handoff")


if __name__ == "__main__":
    unittest.main()
