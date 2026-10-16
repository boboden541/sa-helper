"""Тесты машины состояний конвейера (state_machine.py)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import state_machine as sm  # noqa: E402


def task(pipeline: str, **extra) -> dict:
    base = {"pipeline": pipeline, "skip_review": False, "blocked_from": None,
            "retries": 0, "review_iterations": 0}
    base.update(extra)
    return base


class TestLegalTransitions(unittest.TestCase):
    def test_backlog_to_ready(self):
        res = sm.transition(task(sm.BACKLOG), sm.EV_QUEUE_READY)
        self.assertTrue(res["ok"])
        self.assertEqual(res["patch"]["pipeline"], sm.READY)

    def test_ready_to_implementing(self):
        res = sm.transition(task(sm.READY), sm.EV_START)
        self.assertTrue(res["ok"])
        self.assertEqual(res["patch"]["pipeline"], sm.IMPLEMENTING)

    def test_impl_passed_goes_to_review(self):
        res = sm.transition(task(sm.IMPLEMENTING), sm.EV_IMPL_PASSED)
        self.assertTrue(res["ok"])
        self.assertEqual(res["patch"]["pipeline"], sm.REVIEW)

    def test_impl_passed_skip_review_goes_to_done(self):
        res = sm.transition(task(sm.IMPLEMENTING, skip_review=True), sm.EV_IMPL_PASSED)
        self.assertTrue(res["ok"])
        self.assertEqual(res["patch"]["pipeline"], sm.DONE)

    def test_impl_escalated_goes_to_needs_human(self):
        res = sm.transition(task(sm.IMPLEMENTING), sm.EV_IMPL_ESCALATED)
        self.assertTrue(res["ok"])
        self.assertEqual(res["patch"]["pipeline"], sm.NEEDS_HUMAN)

    def test_impl_blocked_sets_blocked_from_and_counts_retry(self):
        res = sm.transition(task(sm.IMPLEMENTING, retries=1), sm.EV_IMPL_BLOCKED)
        self.assertTrue(res["ok"])
        self.assertEqual(res["patch"]["pipeline"], sm.BLOCKED)
        self.assertEqual(res["patch"]["blocked_from"], sm.IMPLEMENTING)
        self.assertEqual(res["patch"]["retries"], 2)

    def test_review_approved(self):
        res = sm.transition(task(sm.REVIEW), sm.EV_REVIEW_APPROVED)
        self.assertTrue(res["ok"])
        self.assertEqual(res["patch"]["pipeline"], sm.DONE)

    def test_review_changes_returns_to_implementing_and_counts_iteration(self):
        res = sm.transition(task(sm.REVIEW, review_iterations=1), sm.EV_REVIEW_CHANGES)
        self.assertTrue(res["ok"])
        self.assertEqual(res["patch"]["pipeline"], sm.IMPLEMENTING)
        self.assertEqual(res["patch"]["review_iterations"], 2)

    def test_review_stalled_goes_to_needs_human(self):
        res = sm.transition(task(sm.REVIEW), sm.EV_REVIEW_STALLED)
        self.assertTrue(res["ok"])
        self.assertEqual(res["patch"]["pipeline"], sm.NEEDS_HUMAN)

    def test_force_approve(self):
        res = sm.transition(task(sm.REVIEW), sm.EV_FORCE_APPROVE)
        self.assertTrue(res["ok"])
        self.assertEqual(res["patch"]["pipeline"], sm.DONE)

    def test_request_changes_from_done(self):
        res = sm.transition(task(sm.DONE), sm.EV_REQUEST_CHANGES)
        self.assertTrue(res["ok"])
        self.assertEqual(res["patch"]["pipeline"], sm.IMPLEMENTING)

    def test_verify_passed(self):
        res = sm.transition(task(sm.DONE), sm.EV_VERIFY_PASSED)
        self.assertTrue(res["ok"])
        self.assertEqual(res["patch"]["pipeline"], sm.VERIFIED)

    def test_retry_returns_to_blocked_from(self):
        res = sm.transition(task(sm.BLOCKED, blocked_from=sm.IMPLEMENTING), sm.EV_RETRY)
        self.assertTrue(res["ok"])
        self.assertEqual(res["patch"]["pipeline"], sm.IMPLEMENTING)
        self.assertIsNone(res["patch"]["blocked_from"])

    def test_retry_without_blocked_from_rejected(self):
        res = sm.transition(task(sm.BLOCKED), sm.EV_RETRY)
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "missing_field")

    def test_resume_work_from_needs_human(self):
        res = sm.transition(task(sm.NEEDS_HUMAN, blocked_from=sm.REVIEW), sm.EV_RESUME_WORK)
        self.assertTrue(res["ok"])
        self.assertEqual(res["patch"]["pipeline"], sm.REVIEW)

    def test_abort_from_active(self):
        for status in (sm.BACKLOG, sm.READY, sm.IMPLEMENTING, sm.REVIEW, sm.DONE,
                       sm.BLOCKED, sm.NEEDS_HUMAN):
            with self.subTest(status=status):
                res = sm.transition(task(status), sm.EV_ABORT)
                self.assertTrue(res["ok"])
                self.assertEqual(res["patch"]["pipeline"], sm.ABORTED)


class TestIllegalTransitions(unittest.TestCase):
    def test_terminal_have_no_events(self):
        for status in (sm.VERIFIED, sm.ABORTED):
            with self.subTest(status=status):
                for event in sm._TRANSITIONS:
                    with self.subTest(event=event):
                        self.assertFalse(sm.transition(task(status), event)["ok"])

    def test_cannot_skip_queue(self):
        self.assertFalse(sm.transition(task(sm.BACKLOG), sm.EV_START)["ok"])

    def test_cannot_start_without_plan_approval(self):
        # start легален только из READY; READY достигается только queue_ready
        self.assertFalse(sm.transition(task(sm.BACKLOG), sm.EV_IMPL_PASSED)["ok"])
        self.assertFalse(sm.transition(task(sm.READY), sm.EV_IMPL_PASSED)["ok"])

    def test_unknown_event(self):
        res = sm.transition(task(sm.READY), "nonsense")
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "unknown_event")

    def test_review_events_only_from_review(self):
        for event in (sm.EV_REVIEW_APPROVED, sm.EV_REVIEW_CHANGES, sm.EV_REVIEW_STALLED,
                      sm.EV_FORCE_APPROVE):
            with self.subTest(event=event):
                self.assertFalse(sm.transition(task(sm.IMPLEMENTING), event)["ok"])

    def test_verify_only_from_done(self):
        self.assertFalse(sm.transition(task(sm.REVIEW), sm.EV_VERIFY_PASSED)["ok"])


class TestAllowedEvents(unittest.TestCase):
    def test_backlog_buttons(self):
        events = sm.allowed_events(task(sm.BACKLOG))
        self.assertIn(sm.EV_QUEUE_READY, events)
        self.assertIn(sm.EV_ABORT, events)
        self.assertNotIn(sm.EV_START, events)

    def test_review_buttons(self):
        events = sm.allowed_events(task(sm.REVIEW))
        for e in (sm.EV_REVIEW_APPROVED, sm.EV_REVIEW_CHANGES, sm.EV_REVIEW_STALLED,
                  sm.EV_FORCE_APPROVE, sm.EV_ABORT):
            self.assertIn(e, events)
        self.assertNotIn(sm.EV_START, events)

    def test_blocked_offers_retry(self):
        self.assertIn(sm.EV_RETRY, sm.allowed_events(task(sm.BLOCKED)))

    def test_done_offers_verify_and_request_changes(self):
        events = sm.allowed_events(task(sm.DONE))
        self.assertIn(sm.EV_VERIFY_PASSED, events)
        self.assertIn(sm.EV_REQUEST_CHANGES, events)


class TestV2Consistency(unittest.TestCase):
    def test_canonical_pairs(self):
        pairs = [
            (sm.BACKLOG, "PLANNED"), (sm.READY, "APPROVED"),
            (sm.IMPLEMENTING, "TDD_RED"), (sm.IMPLEMENTING, "TDD_GREEN"),
            (sm.IMPLEMENTING, "GATES"), (sm.IMPLEMENTING, "APPROVED"),
            (sm.REVIEW, "AGENT_REVIEW"), (sm.DONE, "DONE"),
            (sm.VERIFIED, "DONE"), (sm.NEEDS_HUMAN, "ESCALATED_BLOCKED"),
            (sm.ABORTED, "ABORTED"), (sm.BLOCKED, "TDD_GREEN"),
        ]
        for pipeline, v2 in pairs:
            with self.subTest(pipeline=pipeline, v2=v2):
                self.assertTrue(sm.consistent_v2(pipeline, v2))

    def test_inconsistent_pairs(self):
        pairs = [
            (sm.BACKLOG, "DONE"), (sm.REVIEW, "DONE"), (sm.DONE, "TDD_RED"),
            (sm.NEEDS_HUMAN, "DONE"), (sm.VERIFIED, "AGENT_REVIEW"),
            (sm.READY, "PLANNED"), (sm.ABORTED, "DONE"),
        ]
        for pipeline, v2 in pairs:
            with self.subTest(pipeline=pipeline, v2=v2):
                self.assertFalse(sm.consistent_v2(pipeline, v2))

    def test_unknown_pipeline_is_not_crash(self):
        self.assertFalse(sm.consistent_v2("WAT", "DONE"))


if __name__ == "__main__":
    unittest.main()


class TestProposed(unittest.TestCase):
    """Порция F: агентские задачи-предложения."""

    def test_accept_moves_to_backlog(self):
        res = sm.transition({"pipeline": sm.PROPOSED}, sm.EV_PROPOSE_ACCEPT)
        self.assertTrue(res["ok"])
        self.assertEqual(res["patch"]["pipeline"], sm.BACKLOG)

    def test_reject_aborts(self):
        res = sm.transition({"pipeline": sm.PROPOSED}, sm.EV_PROPOSE_REJECT)
        self.assertTrue(res["ok"])
        self.assertEqual(res["patch"]["pipeline"], sm.ABORTED)

    def test_proposed_not_startable_and_not_aborted(self):
        self.assertFalse(sm.transition({"pipeline": sm.PROPOSED}, sm.EV_START)["ok"])
        self.assertFalse(sm.transition({"pipeline": sm.PROPOSED}, sm.EV_ABORT)["ok"])

    def test_proposed_only_accept_or_reject(self):
        # из PROPOSED две двери: принять в бэклог или отклонить (abort там не нужен)
        legal = sm.allowed_events({"pipeline": sm.PROPOSED})
        self.assertEqual(sorted(legal), [sm.EV_PROPOSE_ACCEPT, sm.EV_PROPOSE_REJECT])
