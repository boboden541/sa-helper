"""Парсер отчёта агента: скобки в тексте, невалидный JSON, неизвестный статус."""

from __future__ import annotations

import json

from daemon.runner.agent_runner import parse_report


def test_valid_report_at_end_with_braces_in_prose():
    text = ('Погоди {не парси это}\nИтог: готово. Summary mentions {odd braces}\n'
            + json.dumps({"status": "success", "summary_md": "готово",
                          "proposed_transition": {"to": "review", "reason": "ok"},
                          "comments": ["коммит 1", ""]}))
    report = parse_report(text)
    assert report.status == "success"
    assert report.proposed_transition == {"to": "review", "reason": "ok"}
    assert report.comments == ["коммит 1"]


def test_nested_json_and_checklist_updates():
    raw = {"status": "failed", "summary_md": "тесты упали",
           "checklist_updates": [
               {"checklist_kind": "developer", "item_position": 1, "new_status": "failed"},
               {"checklist_kind": "developer", "text": "новый пункт", "new_status": "todo"},
               "мусор",
           ],
           "questions": ["что делать?", 42]}
    report = parse_report("до отчёта {скобка\n" + json.dumps(raw))
    assert report.status == "failed"
    assert len(report.checklist_updates) == 2
    assert report.questions == ["что делать?"]


def test_invalid_json_falls_back_to_failed():
    report = parse_report("тут нет JSON вообще")
    assert report.status == "failed"
    assert "контракт" in report.summary_md


def test_unknown_status_rejected():
    text = json.dumps({"status": "victory", "summary_md": "я молодец"})
    report = parse_report(text)
    assert report.status == "failed"


def test_bad_transition_type_dropped():
    text = json.dumps({"status": "success", "summary_md": "ok",
                       "proposed_transition": "review"})
    report = parse_report(text)
    assert report.status == "success"
    assert report.proposed_transition is None
