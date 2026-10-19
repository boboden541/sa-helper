"""Тесты мигратора (R1): файлы -> БД -> файлы, структурное сравнение."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import db as dbmod  # noqa: E402
import db_migrate  # noqa: E402


def build_workspace(ws: Path) -> None:
    harness = ws / "sa_documentation" / "FNR" / "FNR_1" / "harness"
    (harness / ".flags").mkdir(parents=True)
    (harness / "tasks").mkdir()
    (harness / "comments").mkdir()
    (harness / "logs").mkdir()
    (harness / "reviews").mkdir()
    (harness / "sa_documentation")  # noqa: прочерк — структура ниже
    man = {
        "fnr_id": "FNR_1", "story_title": "Синтетика",
        "source_document": "system_requirements.md",
        "status": "IN_PROGRESS",
        "epic_branch": "harness/FNR-1-x",
        "workspace": "sa_documentation/FNR/FNR_1",
        "systems": [{"name": "core", "path": "core", "stack": "py",
                     "bootstrap": "ready"}],
        "tasks": [
            {"id": "T1", "title": "Первая", "description": "делать раз",
             "system": "core", "pipeline": "DONE", "status": "DONE",
             "origin": "plan", "decomposed": True,
             "branch": "harness/FNR-1-x-t1",
             "usage": {"tokens_in": 10, "tokens_out": 5, "tokens_total": 15,
                       "cost_usd": 0.25},
             "acceptance_criteria": [
                 {"id": "AC-1.1", "desc": "работает", "status": "PASSED",
                  "test": "test_x"}],
             "gates": {"build": "passed", "test": "passed"},
             "depends_on": ["T2"], "fr_ids": ["FR-1"]},
            {"id": "T2", "title": "Вторая", "pipeline": "BACKLOG",
             "status": "PLANNED", "origin": "plan",
             "blocked_reason": "ждёт T1"},
        ],
    }
    (harness / "manifest.json").write_text(json.dumps(man, ensure_ascii=False),
                                           encoding="utf-8")
    (ws / "sa_documentation" / "FNR" / "FNR_1" / "system_requirements.md").write_text(
        "# СТ\n\nТребования тут\n", encoding="utf-8")
    (harness / "tasks" / "T1_mine.md").write_text(
        "# T1\n\n## Что сделать\n\nСделать раз.\n\n"
        "## План работ (чек-лист)\n\n- [x] шаг 1\n- [~] шаг 2\n", encoding="utf-8")
    (harness / "comments" / "T1.md").write_text(
        "- [2026-10-19 10:00 | daemon] T1: старт\n"
        "- [2026-10-19 10:05 | human] вопрос\n", encoding="utf-8")
    (harness / "logs" / "events.log").write_text(
        "- [2026-10-19 10:00:00 | daemon] T1: переход READY -> IMPLEMENTING\n"
        "- [2026-10-19 10:04:00 | daemon] Story: план построен\n", encoding="utf-8")
    (harness / "reviews" / "T1_review.md").write_text(
        "# Ревью T1\n\n## Verdict (machine-readable)\n\n"
        "status: CHANGES_REQUESTED\n"
        "blocking:\n"
        "  - - | file: a.py | text: сломано\n", encoding="utf-8")
    (harness / "dossier.md").write_text("# Досье\n", encoding="utf-8")


class TestMigrate(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.ws = Path(self._td.name) / "ws"
        build_workspace(self.ws)
        self.dbfile = Path(self._td.name) / "m.db"
        self.conn = dbmod.connect(self.dbfile)

    def tearDown(self):
        self.conn.close()
        self._td.cleanup()

    def test_import_idempotent_and_counts(self):
        rep1 = db_migrate.import_workspace(self.conn, self.ws, "mig")
        self.assertEqual(rep1["stories"], 1)
        self.assertEqual(rep1["tasks"], 2)
        rep2 = db_migrate.import_workspace(self.conn, self.ws, "mig")
        self.assertEqual(rep2["stories"], 1)  # повтор не плодит сущностей
        tasks = self.conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        self.assertEqual(tasks, 2)
        comments = self.conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
        self.assertEqual(comments, 2)
        events = self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        self.assertEqual(events, 2)

    def test_import_maps_fields_and_card(self):
        db_migrate.import_workspace(self.conn, self.ws, "mig")
        proj = dbmod.get_project(self.conn, "mig")
        story = dbmod.get_story(self.conn, int(proj["id"]), "FNR_1")
        sid = int(story["id"])
        self.assertEqual(story["status"], "IN_PROGRESS")
        self.assertIn("# СТ", story["source_md"])
        t1 = dbmod.read_task(self.conn, sid, "T1")
        self.assertEqual(t1["v2_status"], "DONE")
        self.assertEqual(t1["pipeline"], "DONE")
        self.assertEqual(t1["usage_tokens_total"], 15)
        self.assertEqual(t1["depends_on"], ["T2"])
        self.assertEqual(t1["gates"]["build"], "passed")
        self.assertIn("шаг 1", t1["card_md"])
        ac = t1["acceptance_criteria"][0]
        self.assertEqual((ac["ac_id"], ac["status"]), ("AC-1.1", "PASSED"))

    def test_verdict_imported(self):
        db_migrate.import_workspace(self.conn, self.ws, "mig")
        v = self.conn.execute("SELECT status FROM review_verdicts").fetchone()
        self.assertIsNotNone(v)
        item = self.conn.execute("SELECT kind, text FROM verdict_items").fetchone()
        self.assertEqual((item["kind"], item["text"]), ("blocking", "сломано"))

    def test_roundtrip_export(self):
        db_migrate.import_workspace(self.conn, self.ws, "mig")
        out = Path(self._td.name) / "out"
        rep = db_migrate.export_workspace(self.conn, "mig", out)
        self.assertEqual(rep["stories"], 1)
        man = json.loads((out / "FNR_1" / "harness" / "manifest.json")
                         .read_text(encoding="utf-8"))
        self.assertEqual(man["fnr_id"], "FNR_1")
        self.assertEqual(len(man["tasks"]), 2)
        t1 = next(t for t in man["tasks"] if t["id"] == "T1")
        self.assertEqual(t1["pipeline"], "DONE")
        self.assertEqual(t1["usage"]["tokens_total"], 15)
        self.assertEqual(t1["acceptance_criteria"][0]["status"], "PASSED")
        card = (out / "FNR_1" / "harness" / "tasks" / "T1.md").read_text(encoding="utf-8")
        self.assertIn("шаг 1", card)
        comments = (out / "FNR_1" / "harness" / "comments" / "T1.md").read_text("utf-8")
        self.assertIn("| human]", comments)
        events = (out / "FNR_1" / "harness" / "logs" / "events.log").read_text("utf-8")
        self.assertIn("план построен", events)


if __name__ == "__main__":
    unittest.main()
