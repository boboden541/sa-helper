"""Smoke-тест демона: полный цикл конвейера на песочнице со stub-сессиями.

Доказывает ворота B: после approve конвейер сам ведёт DAG без ручных команд.
Состояния целиком в файлах — демон можно убить, следующий тик дозаминирует.
"""

from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import orchestrator as orch  # noqa: E402
import state_machine as sm  # noqa: E402

STUB = ROOT / "tests" / "fixtures" / "stub_claude.py"


def make_workspace(tmp: Path) -> Path:
    """Воркспейс с FNR_99: T1→T2, план ожидает утверждения."""
    ws = tmp / "ws"
    harness = ws / "sa_documentation" / "FNR" / "FNR_99" / "harness"
    harness.mkdir(parents=True)
    manifest = {
        "fnr_id": "FNR_99", "status": "AWAITING_APPROVAL",
        "epic_branch": "harness/FNR-99-smoke", "workspace": "ws",
        "systems": [{"name": "core", "path": "core", "stack": "python",
                     "bootstrap": "ready"}],
        "tasks": [
            task_card("T1", []),
            task_card("T2", ["T1"]),
        ],
    }
    (harness / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    (harness / ".flags").mkdir()
    (harness / ".flags" / "APPROVE_PLAN").touch()
    return ws


def task_card(tid: str, deps: list[str]) -> dict:
    return {
        "id": tid, "title": f"Задача {tid}", "system": "core", "phase": "regular",
        "branch": f"harness/FNR-99-smoke-{tid.lower()}",
        "status": "PLANNED", "depends_on": deps,
        "fr_ids": ["FR-1.1"],
        "acceptance_criteria": [{"id": "AC-1.1.1", "desc": "x", "status": "PENDING"}],
    }


class TestConveyorSmoke(unittest.TestCase):
    """Полный цикл: approve → T1 (impl→review) → T2 (impl→review) → verify."""

    def test_full_cycle(self):
        import os
        import tempfile
        os.chmod(STUB, 0o755)  # свежий clone может потерять exec-бит
        with tempfile.TemporaryDirectory() as td:
            ws = make_workspace(Path(td))
            harness = ws / "sa_documentation" / "FNR" / "FNR_99" / "harness"

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
            for tick in range(40):
                orch.process_workspace(lane, Opts)
                time.sleep(0.02)

            doc = json.loads((harness / "manifest.json").read_text(encoding="utf-8"))
            pipelines = {t["id"]: t["pipeline"] for t in doc["tasks"]}
            self.assertEqual(pipelines, {"T1": sm.VERIFIED, "T2": sm.VERIFIED})
            self.assertTrue((harness / "verification_report.md").exists())
            events_log = (harness / "logs" / "events.log").read_text(encoding="utf-8")
            for marker in ("queue_ready", "start", "review_approved",
                           "verify_passed", "verify: FNR"):
                self.assertIn(marker, events_log)


class TestKillRecovery(unittest.TestCase):
    """kill -9 демона: осиротевшая сессия не получает дубль, состояние добирается."""

    def test_orphan_fencing_and_completion(self):
        import os
        import tempfile
        slow = ROOT / "tests" / "fixtures" / "stub_slow.py"
        os.chmod(slow, 0o755)
        os.environ["STUB_DELAY"] = "1.5"
        try:
            with tempfile.TemporaryDirectory() as td:
                ws = make_workspace(Path(td))
                harness = ws / "sa_documentation" / "FNR" / "FNR_99" / "harness"
                # план сразу утверждён
                doc = json.loads((harness / "manifest.json").read_text(encoding="utf-8"))
                doc["status"] = "APPROVED"
                (harness / "manifest.json").write_text(json.dumps(doc), encoding="utf-8")

                class Opts:
                    poll_interval = 0
                    stage_timeout = 60
                    heartbeat_timeout = 60
                    max_retries = 3
                    max_turns = 10
                    skip_permissions = True
                    claude_bin = str(slow)
                    dry_run = False
                    verbose = False

                # «демон №1» запускает T1 и «умирает» (lane выброшена, kill -9)
                dead_lane = orch.WorkspaceLane(ws)
                orch.process_workspace(dead_lane, Opts)
                self.assertIsNotNone(dead_lane.proc)

                # «демон №2»: чужая сессия жива — fencing, дубля нет
                new_lane = orch.WorkspaceLane(ws)
                orch.process_workspace(new_lane, Opts)
                self.assertIsNone(new_lane.proc)  # стадию не перезапустили
                pids = list((harness / ".run").glob("T1_implementing*.pid"))
                self.assertEqual(len(pids), 1)  # ровно одна сессия T1

                # сессия-сирота доделала сама и умерла → демон добирает состояние
                time.sleep(1.8)
                orch.process_workspace(new_lane, Opts)  # completion → REVIEW
                doc = json.loads((harness / "manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(doc["tasks"][0]["pipeline"], sm.REVIEW)
        finally:
            os.environ.pop("STUB_DELAY", None)
