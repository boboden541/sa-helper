"""Тесты чистого ядра демона: decide(), completion_events() (orchestrator.py)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import orchestrator as orch  # noqa: E402
import state_machine as sm  # noqa: E402


def task(tid: str, status: str = "APPROVED", pipeline: str | None = None,
         deps: list[str] | None = None, **extra) -> dict:
    base = {
        "id": tid, "status": status, "depends_on": deps or [],
        "retries": 0, "review_iterations": 0, "skip_review": False, "paused": False,
    }
    if pipeline:
        base["pipeline"] = pipeline
    base.update(extra)
    return base


def manifest(tasks: list[dict], status: str = "APPROVED") -> dict:
    return {"fnr_id": "FNR_1", "status": status, "tasks": tasks}


def state(**extra) -> dict:
    base = {
        "lane_free": True, "running_task_id": None, "now": 1000.0,
        "verification_report": False, "verify_attempted": False,
        "orphan_running": False, "max_retries": 3,
    }
    base.update(extra)
    return base


def events(decisions: list[tuple]) -> list[str]:
    return [d[2] for d in decisions if d[0] == "event"]


def stages(decisions: list[tuple]) -> list[str]:
    return [d[2] for d in decisions if d[0] == "stage"]


class TestPlanGate(unittest.TestCase):
    def test_awaiting_approval_without_flag_waits(self):
        decisions = orch.decide(manifest([task("T1")], status="AWAITING_APPROVAL"),
                                set(), state())
        self.assertEqual(decisions, [("wait", "план не утверждён (нет .flags/APPROVE_PLAN)")])
        self.assertEqual(stages(decisions), [])

    def test_approve_plan_consumed(self):
        decisions = orch.decide(manifest([task("T1")], status="AWAITING_APPROVAL"),
                                {"APPROVE_PLAN"}, state())
        self.assertIn(("flag", "APPROVE_PLAN"), decisions)
        self.assertIn(("approve_plan",), decisions)
        self.assertEqual(stages(decisions), [])  # старт — со следующего тика


class TestQueue(unittest.TestCase):
    def test_ready_task_starts_when_lane_free(self):
        decisions = orch.decide(manifest([task("T1", pipeline=sm.READY)]), set(), state())
        self.assertEqual(events(decisions), [sm.EV_START])
        self.assertEqual(stages(decisions), ["implementing"])

    def test_backlog_queues_when_deps_done(self):
        tasks = [task("T1", pipeline=sm.DONE),
                 task("T2", pipeline=sm.BACKLOG, status="PLANNED", deps=["T1"])]
        decisions = orch.decide(manifest(tasks), set(), state())
        self.assertIn(sm.EV_QUEUE_READY, events(decisions))
        self.assertIn(sm.EV_START, events(decisions))
        self.assertEqual(stages(decisions), ["implementing"])

    def test_backlog_waits_for_deps(self):
        tasks = [task("T1", pipeline=sm.IMPLEMENTING, status="TDD_GREEN"),
                 task("T2", pipeline=sm.BACKLOG, status="PLANNED", deps=["T1"])]
        decisions = orch.decide(manifest(tasks), set(), state(orphan_running=True))
        self.assertNotIn(sm.EV_QUEUE_READY, events(decisions))

    def test_pause_blocks_stage_but_not_queue(self):
        decisions = orch.decide(manifest([task("T1", pipeline=sm.READY)]), {"PAUSE"}, state())
        self.assertEqual(events(decisions), [])  # queue_ready был бы раньше; READY без старта
        self.assertEqual(stages(decisions), [])

    def test_verify_runs_when_all_done(self):
        tasks = [task("T1", pipeline=sm.DONE, status="DONE"),
                 task("T2", pipeline=sm.DONE, status="DONE")]
        decisions = orch.decide(manifest(tasks), set(), state())
        self.assertEqual(stages(decisions), ["verify"])

    def test_verify_not_twice(self):
        tasks = [task("T1", pipeline=sm.DONE, status="DONE")]
        decisions = orch.decide(manifest(tasks), set(), state(verify_attempted=True))
        self.assertEqual(stages(decisions), [])

    def test_verify_skipped_when_pending_tasks_exist(self):
        tasks = [task("T1", pipeline=sm.DONE, status="DONE"),
                 task("T2", pipeline=sm.READY)]
        decisions = orch.decide(manifest(tasks), set(), state())
        self.assertEqual(stages(decisions), ["implementing"])


class TestOrphanReconcile(unittest.TestCase):
    def test_implementing_finished_maps_to_review(self):
        t = task("T1", pipeline=sm.IMPLEMENTING, status="AGENT_REVIEW")
        decisions = orch.decide(manifest([t]), set(), state())
        self.assertIn(sm.EV_IMPL_PASSED, events(decisions))
        self.assertEqual(stages(decisions), [])  # ревью стартует после применения события

    def test_implementing_escalated(self):
        t = task("T1", pipeline=sm.IMPLEMENTING, status="ESCALATED_BLOCKED")
        decisions = orch.decide(manifest([t]), set(), state())
        self.assertIn(sm.EV_IMPL_ESCALATED, events(decisions))

    def test_orphan_running_is_not_touched(self):
        t = task("T1", pipeline=sm.IMPLEMENTING, status="TDD_GREEN")
        decisions = orch.decide(manifest([t]), set(), state(orphan_running=True))
        self.assertEqual(decisions, [])

    def test_interrupted_implementing_relaunched(self):
        # осиротевшая недоделанная сессия: перезапуск стадии (resume)
        t = task("T1", pipeline=sm.IMPLEMENTING, status="TDD_GREEN")
        decisions = orch.decide(manifest([t]), set(), state())
        self.assertEqual(stages(decisions), ["implementing"])

    def test_v2_manifest_migrates_pipeline(self):
        # документ v2 без pipeline: T1 DONE, T2 PLANNED — конвейер их подхватывает
        tasks = [task("T1", status="DONE"), task("T2", status="PLANNED", deps=["T1"])]
        decisions = orch.decide(manifest(tasks), set(), state())
        self.assertEqual(tasks[0]["pipeline"], sm.DONE)   # миграция DONE
        self.assertEqual(tasks[1]["pipeline"], sm.BACKLOG)  # мутаций нет: применит io-слой
        self.assertIn(sm.EV_QUEUE_READY, events(decisions))
        self.assertIn(sm.EV_START, events(decisions))
        self.assertEqual(stages(decisions), ["implementing"])


class TestReviewLoop(unittest.TestCase):
    def test_changes_requested_returns_to_rework(self):
        t = task("T1", pipeline=sm.REVIEW, status="AGENT_REVIEW",
                 review_verdict="CHANGES_REQUESTED", review_iterations=1)
        decisions = orch.decide(manifest([t]), set(), state())
        self.assertIn(sm.EV_REVIEW_CHANGES, events(decisions))

    def test_review_iterations_limit_stalls(self):
        t = task("T1", pipeline=sm.REVIEW, status="AGENT_REVIEW",
                 review_verdict="CHANGES_REQUESTED", review_iterations=3)
        decisions = orch.decide(manifest([t]), set(), state())
        self.assertIn(sm.EV_REVIEW_STALLED, events(decisions))

    def test_approved_finishes(self):
        t = task("T1", pipeline=sm.REVIEW, status="DONE", review_verdict="APPROVED")
        decisions = orch.decide(manifest([t]), set(), state())
        self.assertIn(sm.EV_REVIEW_APPROVED, events(decisions))

    def test_review_session_relaunched_when_interrupted(self):
        t = task("T1", pipeline=sm.REVIEW, status="AGENT_REVIEW", review_verdict=None)
        decisions = orch.decide(manifest([t]), set(), state())
        self.assertEqual(stages(decisions), ["review"])


class TestBlockedRetry(unittest.TestCase):
    def test_backoff_pending_waits(self):
        t = task("T1", pipeline=sm.BLOCKED, status="TDD_GREEN", blocked_from="IMPLEMENTING",
                 retry_after_ts=2000.0, retries=1)
        decisions = orch.decide(manifest([t]), set(), state(now=1000.0))
        self.assertEqual(decisions, [])

    def test_backoff_elapsed_retries(self):
        t = task("T1", pipeline=sm.BLOCKED, status="TDD_GREEN", blocked_from="IMPLEMENTING",
                 retry_after_ts=500.0, retries=1)
        decisions = orch.decide(manifest([t]), set(), state(now=1000.0))
        self.assertIn(sm.EV_RETRY, events(decisions))
        self.assertEqual(stages(decisions), ["implementing"])  # сразу перезапуск стадии

    def test_retries_exhausted_escalates(self):
        t = task("T1", pipeline=sm.BLOCKED, status="TDD_GREEN", blocked_from="IMPLEMENTING",
                 retry_after_ts=500.0, retries=3)
        decisions = orch.decide(manifest([t]), set(), state(now=1000.0))
        self.assertIn(sm.EV_BLOCKED_ESCALATED, events(decisions))
        self.assertEqual(stages(decisions), [])


class TestStateMachineBlockedEscalation(unittest.TestCase):
    def test_blocked_escalated_legal_from_blocked_only(self):
        res = sm.transition({"pipeline": sm.BLOCKED}, sm.EV_BLOCKED_ESCALATED)
        self.assertTrue(res["ok"])
        self.assertEqual(res["patch"]["pipeline"], sm.NEEDS_HUMAN)
        self.assertFalse(sm.transition({"pipeline": sm.IMPLEMENTING},
                                       sm.EV_BLOCKED_ESCALATED)["ok"])


if __name__ == "__main__":
    unittest.main()


class TestTaskFlags(unittest.TestCase):
    """Адресные флаги задач: TASK_<ID>_<ДЕЙСТВИЕ> (порция C)."""

    def flags_tick(self, tasks, flags):
        return orch.decide(manifest(tasks), flags, state(orphan_running=True))

    def test_request_changes_from_done(self):
        t = task("T1", pipeline=sm.DONE, status="DONE")
        decisions = self.flags_tick([t], {"TASK_T1_REQUEST_CHANGES"})
        self.assertIn(("flag", "TASK_T1_REQUEST_CHANGES"), decisions)
        self.assertIn(("event", "T1", sm.EV_REQUEST_CHANGES, "флаг TASK_T1_REQUEST_CHANGES"),
                      decisions)
        self.assertEqual(stages(decisions), [])  # тик флагов не запускает стадий

    def test_pause_resume_setters(self):
        tasks = [task("T1", pipeline=sm.READY), task("T2", pipeline=sm.READY)]
        decisions = self.flags_tick(tasks, {"TASK_T1_PAUSE", "TASK_T2_RESUME_WORK"})
        self.assertIn(("set", "T1", "paused", True), decisions)
        self.assertIn(("set", "T2", "paused", False), decisions)

    def test_retry_maps_by_pipeline(self):
        blocked = task("T1", pipeline=sm.BLOCKED, status="TDD_GREEN",
                       blocked_from="IMPLEMENTING", retry_after_ts=9999)
        decisions = self.flags_tick([blocked], {"TASK_T1_RETRY"})
        self.assertIn(("event", "T1", sm.EV_RETRY, "флаг TASK_T1_RETRY"), decisions)
        stalled = task("T2", pipeline=sm.NEEDS_HUMAN, status="ESCALATED_BLOCKED",
                       blocked_from="REVIEW")
        decisions = self.flags_tick([stalled], {"TASK_T2_RETRY"})
        self.assertIn(("event", "T2", sm.EV_RESUME_WORK, "флаг TASK_T2_RETRY"), decisions)

    def test_force_approve_from_review(self):
        t = task("T1", pipeline=sm.REVIEW, status="AGENT_REVIEW")
        decisions = self.flags_tick([t], {"TASK_T1_FORCE_APPROVE"})
        self.assertIn(("event", "T1", sm.EV_FORCE_APPROVE, "флаг TASK_T1_FORCE_APPROVE"),
                      decisions)

    def test_unknown_task_flag_ignored(self):
        decisions = self.flags_tick([task("T1", pipeline=sm.READY)],
                                    {"TASK_T9_ABORT", "TASK_T1_BANANA"})
        kinds = {d[0] for d in decisions}
        self.assertNotIn("flag", kinds)
        self.assertNotIn("set", kinds)  # мусорные флаги не дают решений

    def test_flag_tick_is_exclusive(self):
        # тик флагов не смешивается со стадийными решениями
        t = task("T1", pipeline=sm.READY)
        decisions = orch.decide(manifest([t]), {"TASK_T1_ABORT"}, state())
        self.assertTrue(all(d[0] in ("flag", "event", "wait") for d in decisions))
        self.assertEqual(stages(decisions), [])


class TestStateMachineBlockedFrom(unittest.TestCase):
    def test_escalation_records_origin(self):
        res = sm.transition({"pipeline": sm.IMPLEMENTING}, sm.EV_IMPL_ESCALATED)
        self.assertEqual(res["patch"]["blocked_from"], sm.IMPLEMENTING)

    def test_stall_records_origin(self):
        res = sm.transition({"pipeline": sm.REVIEW}, sm.EV_REVIEW_STALLED)
        self.assertEqual(res["patch"]["blocked_from"], sm.REVIEW)
        res = sm.transition({"pipeline": sm.BLOCKED}, sm.EV_BLOCKED_ESCALATED)
        self.assertEqual(res["patch"]["blocked_from"], sm.BLOCKED)


if __name__ == "__main__":
    unittest.main()
