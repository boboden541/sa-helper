"""Валидация flow перед публикацией (СТ §4.4.1, постановка «Валидация перед сохранением»).

Ошибки блокируют публикацию, предупреждения — нет.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re

KEY_RE = re.compile(r"^[a-z0-9_]+$")


@dataclass
class FlowDraft:
    statuses: list[dict]   # {key, label, stage_desc, checklist_gate, is_entry, is_terminal, is_blocking}
    transitions: list[dict]  # {from, to, runner, display}


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_draft(draft: FlowDraft) -> ValidationResult:
    res = ValidationResult()
    statuses = draft.statuses
    keys = [s["key"] for s in statuses]
    by_key = {s["key"]: s for s in statuses}

    # ключи уникальны и в формате
    if len(keys) != len(set(keys)):
        res.errors.append("Ключи статусов не уникальны")
    for k in keys:
        if not KEY_RE.match(k or ""):
            res.errors.append(f"Ключ статуса {k!r} не соответствует формату: строчные латиница, цифры, _")

    # ровно одна точка входа
    entries = [s["key"] for s in statuses if s.get("is_entry")]
    if len(entries) != 1:
        res.errors.append(f"Точка входа должна быть ровно одна (найдено {len(entries)})")

    # есть терминальный статус
    terminals = [s["key"] for s in statuses if s.get("is_terminal")]
    if not terminals:
        res.errors.append("Нет ни одного терминального статуса (done)")

    # у терминальных нет исходящих переходов
    for t in terminals:
        out = [tr for tr in draft.transitions if tr["from"] == t]
        if out:
            res.errors.append(f"У терминального статуса «{t}» есть исходящие переходы ({len(out)})")

    # рёбра ссылаются на существующие статусы
    for tr in draft.transitions:
        if tr["from"] not in by_key:
            res.errors.append(f"Переход из несуществующего статуса {tr['from']!r}")
        if tr["to"] not in by_key:
            res.errors.append(f"Переход в несуществующий статус {tr['to']!r}")
    if res.errors:
        return res  # дальнейшие проверки по графу бессмысленны

    adj: dict[str, list[str]] = {}
    for tr in draft.transitions:
        adj.setdefault(tr["from"], []).append(tr["to"])

    # нет тупиков: у каждого нетерминального статуса есть исходящий переход
    for s in statuses:
        if not s.get("is_terminal") and not adj.get(s["key"]):
            res.errors.append(f"Тупик: у статуса «{s['key']}» нет исходящих переходов")

    # нет недостижимых: каждый статус достижим из точки входа
    if entries:
        reachable: set[str] = set()
        stack = [entries[0]]
        while stack:
            cur = stack.pop()
            if cur in reachable:
                continue
            reachable.add(cur)
            stack.extend(adj.get(cur, []))
        for k in keys:
            if k not in reachable:
                res.errors.append(f"Статус «{k}» недостижим из точки входа")

    # из любого статуса есть путь до терминального (обратный обход от терминалов)
    rev: dict[str, list[str]] = {}
    for tr in draft.transitions:
        rev.setdefault(tr["to"], []).append(tr["from"])
    can_reach_terminal: set[str] = set(terminals)
    stack = list(terminals)
    while stack:
        cur = stack.pop()
        for prev in rev.get(cur, []):
            if prev not in can_reach_terminal:
                can_reach_terminal.add(prev)
                stack.append(prev)
    for k in keys:
        if k not in can_reach_terminal:
            res.errors.append(f"Из статуса «{k}» нет пути до терминального")

    # предупреждения: canceled и blocked есть
    if "canceled" not in keys or "blocked" not in keys:
        res.warnings.append("Нет статусов canceled и blocked — автомату некуда девать отмены и блокеры")
    # предупреждение: каждый статус замаплен на alias-колонку
    unmapped = [s["key"] for s in statuses if not s.get("alias")]
    if unmapped:
        res.warnings.append(f"Статусы без alias-колонки не видны на доске: {', '.join(unmapped)}")

    return res
