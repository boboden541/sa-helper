"""Тесты адаптера агентов sahelper.py (R4): подкоманды, владение, exit-коды."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import db as dbmod  # noqa: E402

SAHELPER = ROOT / "sahelper.py"


class SahelperFixture(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        td = Path(self._td.name)
        self.ws = td / "ws"
        self.ws.mkdir()
        self.dbfile = td / "a.db"
        conn = dbmod.connect(self.dbfile)
        self.pid = dbmod.upsert_project(conn, "ws", str(self.ws))
        self.sid = dbmod.create_story(conn, self.pid, "FNR_1", "Демо", "# СТ")
        with dbmod.tx(conn):
            conn.execute("UPDATE stories SET status='PLANNED' WHERE id=?", (self.sid,))
        self.env = dict(os.environ, HARNESS_DB=str(self.dbfile))
        conn.close()

    def tearDown(self):
        self._td.cleanup()

    def _run(self, *args, stdin=None):
        r = subprocess.run([sys.executable, str(SAHELPER), *args],
                           capture_output=True, text=True, env=self.env,
                           cwd=self.ws, input=stdin)
        return r.returncode, r.stdout

    def set_planned(self):
        conn = dbmod.connect(self.dbfile)
        with dbmod.tx(conn):
            conn.execute("UPDATE stories SET status='PLANNED' WHERE id=?", (self.sid,))
        conn.close()


class TestReadCommands(SahelperFixture):
    def test_state_shows_story(self):
        code, out = self._run("state", "FNR_1")
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertEqual(d["fnr"], "FNR_1")
        self.assertEqual(d["status"], "PLANNED")

    def test_validate_ok(self):
        code, out = self._run("validate", "FNR_1")
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["valid"])

    def test_unknown_story_errors(self):
        code, _ = self._run("state", "FNR_99")
        self.assertEqual(code, 1)


class TestWriteOwnership(SahelperFixture):
    def test_story_status_session_gate(self):
        self.set_planned()
        code, out = self._run("story-status", "FNR_1", "AWAITING_APPROVAL")
        self.assertEqual(code, 0)
        # повторно — отказ (переход однократный)
        code, _ = self._run("story-status", "FNR_1", "AWAITING_APPROVAL")
        self.assertEqual(code, 1)

    def test_task_create_and_validate_dag(self):
        self._run("task-create", "FNR_1", '{"title": "Первая"}')
        code, out = self._run("task-create", "FNR_1",
                             '{"title": "Вторая", "depends_on": ["T1"]}')
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["id"], "T2")
        code, out = self._run("validate", "FNR_1")
        self.assertTrue(json.loads(out)["valid"])

    def test_card_set_version_conflict_exit3(self):
        self._run("task-create", "FNR_1", '{"title": "Первая"}')
        code, out = self._run("card-set", "FNR_1", "T1", "--file", "-",
                             "--expect-version", "1", stdin="# T1\n\nтекст\n")
        self.assertEqual(code, 0)
        code, out = self._run("card-set", "FNR_1", "T1", "--file", "-",
                             "--expect-version", "1", stdin="x\n")
        self.assertEqual(code, 3)
        self.assertIn("card_version", json.loads(out))

    def test_checklist_set_appends_section(self):
        self._run("task-create", "FNR_1", '{"title": "Первая"}')
        code, out = self._run("checklist-set", "FNR_1", "T1",
                             "--section", "План работ (чек-лист)",
                             "--file", "-", stdin="- [ ] шаг 1\n- [~] шаг 2\n")
        self.assertEqual(code, 0)
        # чек-лист — отдельная модель: пункты в таблицах, card_md без секций
        conn = dbmod.connect(self.dbfile)
        items = [(r["text_md"], r["state"]) for r in conn.execute(
            "SELECT text_md, state FROM checklist_items ORDER BY seq")]
        card = conn.execute("SELECT card_md FROM tasks WHERE tid='T1'").fetchone()["card_md"] or ""
        conn.close()
        self.assertIn(("шаг 1", "todo"), items)
        self.assertIn(("шаг 2", "inprog"), items)
        self.assertNotIn("## План работ", card)

    def test_verdict_set_writes_items_and_comment(self):
        self._run("task-create", "FNR_1", '{"title": "Первая"}')
        code, out = self._run("verdict-set", "FNR_1", "T1",
                             "--status", "CHANGES_REQUESTED", "--iteration", "1",
                             "--blocking",
                             '[{"file": "a.py", "text": "сломано"}]')
        self.assertEqual(code, 0)
        conn = dbmod.connect(self.dbfile)
        item = conn.execute("SELECT kind, text FROM verdict_items").fetchone()
        self.assertEqual((item["kind"], item["text"]), ("blocking", "сломано"))
        comment = conn.execute("SELECT body FROM comments WHERE author='reviewer'").fetchone()
        self.assertIn("CHANGES_REQUESTED", comment["body"])
        conn.close()

    def test_flag_whitelist(self):
        code, _ = self._run("flag", "FNR_1", "BANANA")
        self.assertEqual(code, 1)
        code, out = self._run("flag", "FNR_1", "TASK_T1_ABORT")
        self.assertEqual(code, 0)
        conn = dbmod.connect(self.dbfile)
        row = conn.execute("SELECT name FROM commands WHERE consumed_at IS NULL").fetchone()
        self.assertEqual(row["name"], "TASK_T1_ABORT")
        conn.close()

    def test_comment_add_author_gate(self):
        code, _ = self._run("comment-add", "FNR_1", "T1", "--author", "human",
                           "--text", "нельзя")
        self.assertEqual(code, 1)
        code, out = self._run("comment-add", "FNR_1", "T1", "--author", "agent",
                             "--text", "взято в работу")
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()


class TestReviewCommand(SahelperFixture):
    """С4: режим доработки — единое чтение «что чинить» + новые флаги чек-листа."""

    def _setup_task(self):
        code, out = self._run("task-create", "FNR_1",
                              '{"id": "T1", "title": "А"}')
        self.assertEqual(code, 0)
        self._run("checklist-section-add", "FNR_1", "T1",
                  "--title", "Ревью (чек-лист)", "--kind", "review")
        code, out = self._run(
            "checklist-add", "FNR_1", "T1", "--section", "Ревью (чек-лист)",
            "--text", "Проверена обработка 409", "--kind", "review",
            "--depth", "1", "--mandatory")
        self.assertEqual(code, 0)
        self._run("verdict-set", "FNR_1", "T1", "--status", "CHANGES_REQUESTED",
                  "--iteration", "1",
                  "--blocking", '[{"file": "app/api.py:120", "text": "нет гейта версии"}]')
        self._run("comment-add", "FNR_1", "T1", "--author", "reviewer",
                  "--text", "Есть замечания — см. отчёт и чек-лист ревью")
        report = Path(self._td.name) / "review.md"
        report.write_text("## Замечания\n\n- app/api.py:120 — нет гейта версии\n",
                          encoding="utf-8")
        self._run("doc-set", "FNR_1", "--kind", "review", "--tid", "T1",
                  "--file", str(report))

    def test_review_returns_full_context(self):
        self._setup_task()
        code, out = self._run("review", "FNR_1", "T1")
        self.assertEqual(code, 0)
        d = json.loads(out)
        # счётчик итераций растит демон на EV_REVIEW_CHANGES (после вердикта — 0)
        self.assertEqual(d["task"]["review_iterations"], 0)
        self.assertEqual(d["verdict"]["status"], "CHANGES_REQUESTED")
        self.assertEqual(d["verdict_items"][0]["file"], "app/api.py:120")
        self.assertEqual(len(d["review_checklist"]), 1)
        self.assertEqual(d["review_checklist"][0]["items"][0]["mandatory"], 1)
        self.assertEqual(d["review_checklist"][0]["items"][0]["depth"], 1)
        # авто-комментарий вердикта + явный комментарий ревьюера
        self.assertEqual(len(d["reviewer_comments"]), 2)
        self.assertTrue(any("Вердикт" in c["body"] for c in d["reviewer_comments"]))
        self.assertIn("Замечания", d["review_md"])
        # findings-таблицу пишет reconcile_review демона; после verdict-set — пуста
        self.assertEqual(d["findings"], [])

    def test_state_shows_review_fields(self):
        self._setup_task()
        code, out = self._run("state", "FNR_1")
        d = json.loads(out)
        t1 = next(x for x in d["tasks"] if x["id"] == "T1")
        # verdict-set не пишет v3-поля (владение демона) — только таблицу вердиктов
        self.assertEqual(t1["review_iterations"], 0)
        self.assertIsNone(t1["review_verdict"])
        self.assertIn("retries", t1)
        self.assertIn("blocked_from", t1)

    def test_checklist_add_depth_plan(self):
        self._run("task-create", "FNR_1", '{"id": "T2", "title": "B"}')
        self._run("checklist-add", "FNR_1", "T2", "--section", "План работ (чек-лист)",
                  "--text", "Доработки по итогам ревью (iter 1)", "--depth", "1",
                  "--kind", "plan")
        code, out = self._run("checklist-add", "FNR_1", "T2",
                              "--section", "План работ (чек-лист)",
                              "--text", "Исправить 409-гейт", "--depth", "2")
        self.assertEqual(code, 0)
        conn = dbmod.connect(self.dbfile)
        rows = conn.execute(
            "SELECT ci.depth, cs.kind FROM checklist_items ci"
            " JOIN checklist_sections cs ON cs.id=ci.section_id"
            " WHERE ci.text_md LIKE '%Доработки%'").fetchone()
        self.assertEqual(rows["depth"], 1)
        self.assertEqual(rows["kind"], "plan")  # --kind прокинут в _ensure_section
        rows2 = conn.execute(
            "SELECT depth FROM checklist_items WHERE text_md LIKE '%409-гейт%'"
        ).fetchone()
        self.assertEqual(rows2["depth"], 2)
        conn.close()
