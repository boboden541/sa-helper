"""Тень v3-полей (переживает перезапись манифеста v2-сессиями) и отчёты демона."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import orchestrator as orch  # noqa: E402
import state_machine as sm  # noqa: E402


def harness(tmp: Path) -> Path:
    h = tmp / "harness"
    h.mkdir(parents=True)
    doc = {"fnr_id": "FNR_1", "status": "IN_PROGRESS", "tasks": [
        {"id": "T1", "status": "TDD_GREEN", "pipeline": "IMPLEMENTING",
         "review_iterations": 2, "findings": [{"id": "b1", "text": "x", "resolution": "open"}],
         "session_id": "abc"}]}
    (h / "manifest.json").write_text(json.dumps(doc), encoding="utf-8")
    return h


class TestShadow(unittest.TestCase):
    def test_session_rewrite_restored_from_shadow(self):
        with tempfile.TemporaryDirectory() as td:
            h = harness(Path(td))
            doc = orch.load_manifest(h)
            orch.shadow_save(h, doc)
            # «v2-сессия» переписала манифест без v3-полей
            v2 = {"fnr_id": "FNR_1", "status": "IN_PROGRESS",
                  "tasks": [{"id": "T1", "status": "PLANNED"}]}
            (h / "manifest.json").write_text(json.dumps(v2), encoding="utf-8")
            doc = orch.load_manifest(h)
            self.assertTrue(orch.shadow_restore(h, doc))
            t = doc["tasks"][0]
            self.assertEqual(t["pipeline"], "IMPLEMENTING")
            self.assertEqual(t["review_iterations"], 2)
            self.assertEqual(t["session_id"], "abc")

    def test_no_shadow_touch_when_pipeline_intact(self):
        with tempfile.TemporaryDirectory() as td:
            h = harness(Path(td))
            orch.shadow_save(h, orch.load_manifest(h))
            doc = orch.load_manifest(h)
            doc["tasks"][0]["pipeline"] = "REVIEW"  # живое поле демона главнее тени
            self.assertFalse(orch.shadow_restore(h, doc))


class TestCommentsReports(unittest.TestCase):
    def test_transition_appends_comment_and_escalation_report(self):
        with tempfile.TemporaryDirectory() as td:
            h = harness(Path(td))
            doc = orch.load_manifest(h)
            t = doc["tasks"][0]
            t["status"] = "AGENT_REVIEW"
            self.assertTrue(orch.apply_transition(h, doc, t, sm.EV_IMPL_PASSED, "тест"))
            journal = (h / "comments" / "T1.md").read_text(encoding="utf-8")
            self.assertIn("| daemon] implementation_passed → REVIEW — тест", journal)
            # эскалация — подробный отчёт с действиями
            t2 = dict(t, pipeline=sm.BLOCKED, retries=1, retry_after_ts=0,
                      blocked_from=sm.IMPLEMENTING)
            self.assertTrue(orch.apply_transition(h, doc, t2, sm.EV_BLOCKED_ESCALATED,
                                                  "retries исчерпаны"))
            journal = (h / "comments" / "T1.md").read_text(encoding="utf-8")
            self.assertIn("Требуется вмешательство человека", journal)
            self.assertIn("TASK_T1_RETRY", journal)
            self.assertIn("Открытые замечания", journal)


if __name__ == "__main__":
    unittest.main()
