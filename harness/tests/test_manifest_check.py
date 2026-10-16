"""Тесты валидатора манифеста: обратная совместимость v2 + поля конвейера v3."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import manifest_check  # noqa: E402


def v2_manifest() -> dict:
    """Минимальный валидный документ в формате v2 (как после /impl-plan)."""
    return {
        "fnr_id": "FNR_8",
        "epic_branch": "harness/FNR-8-draft-import",
        "status": "AWAITING_APPROVAL",
        "systems": [{"name": "core", "path": "core", "stack": "python", "bootstrap": "ready"}],
        "tasks": [{
            "id": "T1",
            "title": "Контракт",
            "system": "core",
            "phase": "contract",
            "branch": "harness/FNR-8-draft-import-t1",
            "status": "PLANNED",
            "depends_on": [],
            "fr_ids": ["FR-1.1"],
            "acceptance_criteria": [{"id": "AC-1.1.1", "desc": "условие", "status": "PENDING"}],
        }],
    }


class TestV2Compatibility(unittest.TestCase):
    def test_plain_v2_is_valid(self):
        errors, warnings = manifest_check.validate(v2_manifest())
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_v2_without_pipeline_has_no_pipeline_errors(self):
        doc = v2_manifest()
        doc["tasks"][0].pop("status")  # отсутствие v2-статуса — ошибка и в v2
        errors, _ = manifest_check.validate(doc)
        self.assertTrue(any("status" in e for e in errors))


class TestV3PipelineFields(unittest.TestCase):
    def test_pipeline_backlog_consistent(self):
        doc = v2_manifest()
        doc["auto_mode"] = True
        doc["created_by"] = "impl-handoff"
        doc["tasks"][0].update({"pipeline": "BACKLOG", "skip_review": False})
        errors, _ = manifest_check.validate(doc)
        self.assertEqual(errors, [])

    def test_pipeline_review_with_status_done_is_inconsistent(self):
        doc = v2_manifest()
        doc["tasks"][0].update({"pipeline": "REVIEW", "status": "DONE"})
        errors, _ = manifest_check.validate(doc)
        self.assertTrue(any("pipeline" in e for e in errors))

    def test_pipeline_unknown_value(self):
        doc = v2_manifest()
        doc["tasks"][0]["pipeline"] = "WAT"
        errors, _ = manifest_check.validate(doc)
        self.assertTrue(any("pipeline" in e.lower() for e in errors))

    def test_blocked_fields(self):
        doc = v2_manifest()
        doc["tasks"][0].update({"pipeline": "BLOCKED", "status": "TDD_GREEN",
                                "blocked_from": "IMPLEMENTING", "retries": 2})
        errors, _ = manifest_check.validate(doc)
        self.assertEqual(errors, [])

    def test_blocked_from_unknown(self):
        doc = v2_manifest()
        doc["tasks"][0].update({"pipeline": "BLOCKED", "status": "TDD_GREEN",
                                "blocked_from": "MARS"})
        errors, _ = manifest_check.validate(doc)
        self.assertTrue(any("blocked_from" in e for e in errors))

    def test_retry_and_iterations_must_be_non_negative_ints(self):
        doc = v2_manifest()
        doc["tasks"][0].update({"pipeline": "READY", "status": "APPROVED",
                                "retries": -1, "review_iterations": "many"})
        errors, _ = manifest_check.validate(doc)
        self.assertEqual(len([e for e in errors if "retries" in e or "review_iterations" in e]), 2)

    def test_flags_must_be_bool(self):
        doc = v2_manifest()
        doc["tasks"][0].update({"pipeline": "READY", "status": "APPROVED",
                                "skip_review": "yes", "paused": 1})
        errors, _ = manifest_check.validate(doc)
        self.assertEqual(len([e for e in errors if "skip_review" in e or "paused" in e]), 2)

    def test_findings_shape(self):
        doc = v2_manifest()
        doc["tasks"][0].update({
            "pipeline": "REVIEW", "status": "AGENT_REVIEW",
            "findings": [{"id": "b1", "text": "DROP без guard", "file": "a.java:42",
                          "resolution": "open"},
                         {"id": "", "text": ""}],  # битая находка
        })
        errors, _ = manifest_check.validate(doc)
        self.assertEqual(len([e for e in errors if "findings" in e]), 1)

    def test_session_id_and_owner(self):
        doc = v2_manifest()
        doc["tasks"][0].update({"pipeline": "IMPLEMENTING", "status": "TDD_RED",
                                "session_id": "abc-123", "owner": "ai"})
        errors, _ = manifest_check.validate(doc)
        self.assertEqual(errors, [])

    def test_owner_unknown(self):
        doc = v2_manifest()
        doc["tasks"][0].update({"pipeline": "BACKLOG", "owner": "robot"})
        errors, _ = manifest_check.validate(doc)
        self.assertTrue(any("owner" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
