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
            self.assertEqual(t2[0]["pipeline"], sm.PROPOSED)
  # порция K: Предложена → декомпозиция → Бэклог\n            self.assertEqual(t2[0]["origin"], "manual")
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


class TestUsage(unittest.TestCase):
    """Порция G2: сбор токенов/$ из result-событий stream-лога."""

    def _harness_with_log(self, tmp: Path) -> Path:
        harness = tmp / "harness"
        (harness / ".run").mkdir(parents=True)
        (harness / "manifest.json").write_text(json.dumps({
            "fnr_id": "FNR_1", "status": "IN_PROGRESS", "tasks": []}), encoding="utf-8")
        stream = "".join([
            json.dumps({"type": "assistant", "message": {"content": []}}) + "\n",
            json.dumps({"type": "result", "duration_ms": 60000,
                        "total_cost_usd": 0.4200,
                        "usage": {"input_tokens": 1000,
                                  "cache_read_input_tokens": 5000,
                                  "cache_creation_input_tokens": 200,
                                  "output_tokens": 300}}) + "\n",
        ])
        (harness / ".run" / "T1_implementing_77.log").write_text(stream, encoding="utf-8")
        return harness

    def test_pick_usage_parses_result(self):
        with tempfile.TemporaryDirectory() as td:
            h = self._harness_with_log(Path(td))
            u = orch._pick_usage(h, "T1", "implementing")
            self.assertEqual(u["tokens_in"], 6200)
            self.assertEqual(u["tokens_out"], 300)
            self.assertEqual(u["tokens_total"], 6500)
            self.assertAlmostEqual(u["cost_usd"], 0.42, places=3)

    def test_merge_usage_accumulates_sessions(self):
        task = {"usage": {"tokens_in": 100, "tokens_out": 10, "tokens_total": 110,
                          "cost_usd": 0.1, "sessions": 1}}
        orch._merge_usage(task, {"tokens_in": 50, "tokens_out": 5,
                                 "tokens_total": 55, "cost_usd": 0.05})
        u = task["usage"]
        self.assertEqual((u["tokens_in"], u["tokens_total"], u["sessions"]),
                         (150, 165, 2))
        self.assertAlmostEqual(u["cost_usd"], 0.15, places=3)


class TestTaskEdit(unittest.TestCase):
    """Порция G3: правка описания человеком через payload-флаг."""

    def test_task_edit_updates_manifest_and_card(self):
        with tempfile.TemporaryDirectory() as td:
            ws, harness = sandbox(Path(td), approved=True)
            (harness / "tasks").mkdir()
            (harness / "tasks" / "T1.md").write_text(
                "# T1: A\n\n## Что сделать\n\nСтарое описание\n\n## Критерии приёмки\n",
                encoding="utf-8")
            (harness / ".flags" / "TASK_EDIT_T1.json").write_text(json.dumps({
                "description": "Новое описание от человека"}), encoding="utf-8")

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
            self.assertEqual(doc["tasks"][0]["description"], "Новое описание от человека")
            card = (harness / "tasks" / "T1.md").read_text(encoding="utf-8")
            self.assertIn("Новое описание от человека", card)
            self.assertNotIn("Старое описание", card)
            journal = (harness / "comments" / "T1.md").read_text(encoding="utf-8")
            self.assertIn("Описание обновлено человеком", journal)


class TestTimelineAndAttachments(unittest.TestCase):
    """Вложения задачи (таймлайн переехал в таблицу events — R2)."""

    def test_attachments_safe_name(self):
        sys.path.insert(0, str(ROOT / "web"))
        import server as ui
        self.assertEqual(ui.ATTACHMENT_NAME_RE.sub("_", "../etc/passwd"), ".._etc_passwd")
        self.assertEqual(ui.ATTACHMENT_NAME_RE.sub("_", "отчёт май.csv"), "отчёт_май.csv")


class TestShadowAuthority(unittest.TestCase):
    """Чужой писатель перезаписал pipeline — демон восстанавливает из тени."""

    def test_foreign_pipeline_write_reverted(self):
        with tempfile.TemporaryDirectory() as td:
            ws, harness = sandbox(Path(td), approved=False)
            doc = json.loads((harness / "manifest.json").read_text(encoding="utf-8"))
            doc["tasks"][0]["pipeline"] = "BACKLOG"   # у задачи есть v3-поля
            (harness / "manifest.json").write_text(json.dumps(doc), encoding="utf-8")
            # тень отражает текущее состояние манифеста
            orch.shadow_save(harness, doc)
            # сессия-«самоделкин» перезаписала pipeline готовой задачи
            doc["tasks"][0]["pipeline"] = "DONE"
            doc["tasks"][0]["status"] = "DONE"
            (harness / "manifest.json").write_text(json.dumps(doc), encoding="utf-8")

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
            orch.process_workspace(lane, Opts)  # план не утверждён — но authority сработает

            doc = json.loads((harness / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(doc["tasks"][0]["pipeline"], "BACKLOG")  # истина из тени
            log = (harness / "logs" / "events.log").read_text(encoding="utf-8")
            self.assertIn("восстановлен из тени", log)


class TestDecomposeFlow(unittest.TestCase):
    """Ручная задача → Предложена → декомпозиция → Бэклог."""

    def test_manual_task_lands_in_proposed_and_decomposes(self):
        import os
        with tempfile.TemporaryDirectory() as td:
            ws, harness = sandbox(Path(td), approved=True)
            (harness / ".flags" / "TASK_NEW_1.json").write_text(json.dumps({
                "title": "Реестр отчётов", "system": "core",
                "description": "Добавить таблицу отчётов",
                "depends_on": ["T1"]}), encoding="utf-8")

            stub_dec = ROOT / "tests" / "fixtures" / "stub_decompose.py"
            os.chmod(stub_dec, 0o755)

            class Opts:
                poll_interval = 0
                stage_timeout = 60
                heartbeat_timeout = 60
                max_retries = 3
                max_turns = 10
                skip_permissions = True
                claude_bin = str(stub_dec)
                dry_run = False
                verbose = False

            lane = orch.WorkspaceLane(ws)
            for _ in range(60):
                orch.process_workspace(lane, Opts)
                time.sleep(0.02)
                doc = json.loads((harness / "manifest.json").read_text(encoding="utf-8"))
                t2 = [t for t in doc["tasks"] if t["id"] == "T2"]
                if t2 and t2[0].get("pipeline") == "BACKLOG" and t2[0].get("decomposed"):
                    break

            doc = json.loads((harness / "manifest.json").read_text(encoding="utf-8"))
            t2 = [t for t in doc["tasks"] if t["id"] == "T2"][0]
            self.assertEqual(t2["pipeline"], "BACKLOG")
            self.assertEqual(t2["origin"], "manual")
            self.assertTrue(t2["decomposed"])
            card = (harness / "tasks" / "T2.md").read_text(encoding="utf-8")
            journal = (harness / "comments" / "T2.md").read_text(encoding="utf-8")
            self.assertIn("Декомпозиция выполнена", journal)
