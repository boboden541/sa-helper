"""Перечисления-словари домена (строковые значения — как в БД)."""

from __future__ import annotations

PRIORITIES = ("low", "medium", "high", "critical")
PRIORITY_RANK: dict[str, int] = {"critical": 0, "high": 1, "medium": 2, "low": 3}

AUTHOR_TAGS = ("by_human", "by_ai")

CHECKLIST_KINDS = ("developer", "reviewer", "tester", "psi")
CHECKLIST_ITEM_STATUSES = ("todo", "in_progress", "closed", "done", "failed")
# Пункты в конечных статусах засчитываются гейтом (ФТ-ah-9)
CHECKLIST_FINAL_STATUSES = ("done", "closed")

EVENT_TYPES = ("field", "transition", "force", "agent", "denied", "psi", "bug")
AUTHOR_KINDS = ("human", "agent", "eve", "auto")

RUNNERS = ("human", "agent", "auto", "auto_or_agent")

# Типы, для которых создаётся ветка/worktree (ФТ-ah-37): qa_task и analyse_task — без ветки
GIT_TASK_TYPES = ("story", "common_task", "bug")

BUILTIN_TASK_TYPES = (
    ("story", "История"),
    ("common_task", "Задача"),
    ("qa_task", "Задача на тестирование"),
    ("bug", "Баг"),
    ("analyse_task", "Задача на анализ"),
)
