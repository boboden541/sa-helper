"""Тесты review-gate: разбор вердикта и решение петли доработки."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import review_gate as rg  # noqa: E402
import state_machine as sm  # noqa: E402


def verdict(status="CHANGES_REQUESTED", blocking=None, previous=None):
    lines = [VERDICT := "## Verdict (machine-readable)", f"status: {status}"]
    if blocking is not None:
        lines.append("blocking:")
        for b in blocking:
            lines.append(b if isinstance(b, str) else f"- {b}")  # строка уже готовый пункт
    if previous:
        lines.append("previous:")
        for pid, st in previous.items():
            lines.append(f"- {pid}: {st}")
    return "\n".join(lines)


class TestParse(unittest.TestCase):
    def test_full_block(self):
        md = """# Ревью T3

Находки с файл:строка, рубрика v2 §11.

## Verdict (machine-readable)
status: CHANGES_REQUESTED
blocking:
- b1 | file: src/A.java:42 | text: DROP без guard URL
- b2 | file: src/B.java:7 | text: unused import
advisory:
- a1 | file: src/C.java:1 | text: стиль
previous:
- b1: resolved
"""
        v = rg.parse_review_verdict(md)
        self.assertEqual(v["status"], "CHANGES_REQUESTED")
        self.assertEqual([f["id"] for f in v["blocking"]], ["b1", "b2"])
        self.assertEqual(v["blocking"][0]["file"], "src/A.java:42")
        self.assertEqual(v["blocking"][1]["text"], "unused import")
        self.assertEqual(v["previous"], {"b1": "resolved"})

    def test_no_block_returns_None(self):
        self.assertIsNone(rg.parse_review_verdict("# Ревью без блока\n"))

    bad = [
        "## Verdict (machine-readable)\nstatus: MAYBE\nblocking:\n- x | text: y\n",
        "## Verdict enum-break status: APPROVED\nblocking:\n- x | text: y\n",
        "## Verdict (machine-readable)\nstatus: APPROVED\nblocking:\n- x | text: y",
    ]

    def test_edge_cases(self):
        v = rg.parse_review_verdict(self.bad[2])
        self.assertEqual(v["status"], "APPROVED")
        self.assertEqual(v["blocking"][0]["text"], "y")

    def test_auto_id_and_malformed_previous_ignored(self):
        v = rg.parse_review_verdict(
            "## Verdict (machine-readable)\nstatus: CHANGES_REQUESTED\n"
            "blocking:\n- | file: a.java:1 | text: дубль\n"
            "previous:\n- no-colon-line\n- b9: nonsense\n")
        self.assertEqual(len(v["blocking"]), 1)
        self.assertEqual(len(v["blocking"][0]["id"]), 12)  # хеш вместо явного id
        self.assertEqual(v["previous"], {})  # мусор в previous игнорируется


class TestGate(unittest.TestCase):
    """Чистое решение петли: approve / доработка / честная остановка."""

    def task(self, **extra):
        return {"id": "T1", "review_iterations": 0, "findings": [], **extra}

    def test_approved_clears_findings(self):
        task = self.task(findings=[{"id": "b1", "text": "x", "resolution": "open"}])
        v = rg.parse_review_verdict(verdict("APPROVED"))
        res = rg.review_gate(task, v)
        self.assertEqual(res["event"], sm.EV_REVIEW_APPROVED)
        self.assertTrue(all(f["resolution"] == "resolved" for f in res["findings"]))

    def test_rework_on_first_blocking(self):
        v = rg.parse_review_verdict(verdict(blocking=["- | file: a.java:1 | text: дубль DDL"]))
        res = rg.review_gate(self.task(), v)
        self.assertEqual(res["event"], sm.EV_REVIEW_CHANGES)
        self.assertEqual(res["findings"][0]["resolution"], "open")

    def test_old_findings_with_fid_key_get_id(self):
        # хотфикс crash-loop 2026-10-21: находки из БД имеют fid, из вердикта id;
        # все выходные находки обязаны иметь id (INSERT f["id"] в reconcile_review)
        task = self.task(findings=[{"fid": "old1", "text": "старая",
                                    "resolution": "open"}])
        v = rg.parse_review_verdict(verdict(
            blocking=["- new1 | file: a.java:1 | text: новая находка"]))
        res = rg.review_gate(task, v)
        self.assertTrue(all(f.get("id") for f in res["findings"]),
                        f"находка без id: {res['findings']}")
        self.assertIn("new1", {f["id"] for f in res["findings"]})
        self.assertIn("old1", {f["id"] for f in res["findings"]})

    def test_approved_resolves_fid_findings_with_id(self):
        task = self.task(findings=[{"fid": "old1", "text": "старая",
                                    "resolution": "open"}])
        v = rg.parse_review_verdict(verdict(blocking=[]))
        res = rg.review_gate(task, v)
        self.assertEqual(res["event"], sm.EV_REVIEW_APPROVED)
        self.assertEqual(res["findings"][0]["id"], "old1")

    def test_closure_first_stalls_on_new_blockers_after_fix(self):
        # прошлые находки закрыты (ревьюер подтвердил), но найдены новые
        task = self.task(findings=[{"id": "b1", "text": "x", "resolution": "open"}])
        v = rg.parse_review_verdict(verdict(
            blocking=["- b1-still | file: a.java:1 | text: НОВОЕ замечание"],
            previous={"b1": "resolved"}))
        res = rg.review_gate(task, v, strategy="closure_first")
        self.assertEqual(res["event"], sm.EV_REVIEW_STALLED)

    def test_closure_first_continues_while_still_blocking(self):
        # b1 ещё не закрыт — петля продолжается (closure_first не мешает штатной доработке)
        task = self.task(findings=[{"id": "b1", "text": "x", "resolution": "open"}])
        v = rg.parse_review_verdict(verdict(
            blocking=["- b1 | file: a.java:1 | text: x"],
            previous={"b1": "still_blocking"}))
        res = rg.review_gate(self.task(), v, strategy="closure_first")
        self.assertEqual(res["event"], sm.EV_REVIEW_CHANGES)
        self.assertEqual(res["findings"][0]["resolution"], "still_blocking")

    def test_auto_previous_by_findings_ids(self):
        # ревьюер не заполнил previous: b1 закрыл, нашёл b2 — closure_first должен остановить
        task = self.task(findings=[{"id": "b1", "text": "x", "resolution": "open"}])
        v = rg.parse_review_verdict(verdict(
            blocking=["- b2 | file: b.java:2 | text: новое"]))
        res = rg.review_gate(task, v, strategy="closure_first")
        self.assertEqual(res["event"], sm.EV_REVIEW_STALLED)

    def test_auto_previous_still_blocking_continues(self):
        task = self.task(findings=[{"id": "b1", "text": "x", "resolution": "open"}])
        v = rg.parse_review_verdict(verdict(
            blocking=["- b1 | file: a.java:1 | text: x"]))
        res = rg.review_gate(task, v, strategy="closure_first")
        self.assertEqual(res["event"], sm.EV_REVIEW_CHANGES)

    def test_iteration_limit_stalls(self):
        v = rg.parse_review_verdict(verdict(blocking=["- | file: a.java:1 | text: x"]))
        res = rg.review_gate(self.task(review_iterations=3), v, strategy="full_re_review")
        self.assertEqual(res["event"], sm.EV_REVIEW_STALLED)

    def test_full_re_review_keeps_looping_below_limit(self):
        v = rg.parse_review_verdict(verdict(blocking=["- | file: a.java:1 | text: x"]))
        res = rg.review_gate(self.task(review_iterations=2), v, strategy="full_re_review")
        self.assertEqual(res["event"], sm.EV_REVIEW_CHANGES)


if __name__ == "__main__":
    unittest.main()
