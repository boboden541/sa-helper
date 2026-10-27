#!/usr/bin/env python3
"""Валидатор структуры документа ПСИ (использует скилл psi-methodology).

Проверяет канон идеального ПСИ (пример — FNR_8/psi.md):
заголовок, «Назначение», «Что реализовано», «Словарик», «Правила»,
пункты «Действие → Ожидаемый результат». Выход: 0 — ок, 1 — есть блокеры.

Запуск: python3 validate_psi.py <путь к psi.md>
"""
from __future__ import annotations

import re
import sys


def main(path: str) -> int:
    try:
        text = open(path, encoding="utf-8").read()
    except OSError as err:
        print(f"FAIL: файл не читается: {err}")
        return 1
    problems: list[str] = []

    if not re.search(r"^# .*ПСИ", text, re.MULTILINE):
        problems.append("🔴 нет заголовка «Процедура ПСИ…» (H1 со словом ПСИ)")
    if "Назначение" not in text:
        problems.append("🔴 нет блока «Назначение»")
    for section, hint in [("Что реализовано", "как было → как стало"),
                          ("Словарик", "термины для читателя вне IT"),
                          ("Правила проведения", "как проводить пункты")]:
        if section not in text:
            problems.append(f"🔴 нет раздела «{section}» ({hint})")
    items = re.findall(r"^###? +П\.\d+", text, re.MULTILINE)
    if not items:
        problems.append("🔴 нет ни одного пункта «П.<номер>»")
    expected = text.count("**Ожидаемый результат:**")
    if expected < len(items):
        problems.append(f"🔴 пунктов {len(items)}, а «Ожидаемый результат» — {expected}: "
                        "у каждого пункта должен быть ожидаемый результат")
    if "Если расхождение" not in text:
        problems.append("— нет ни одного «Если расхождение» (предупреждение): у пунктов должна быть "
                        "подсказка, где искать причину")
    print(f"Пунктов: {len(items)}, «Ожидаемый результат»: {expected}")
    if problems:
        print("Проблемы:")
        for p in problems:
            print(" -", p)
        return 1
    print("OK: канон структуры соблюдён")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else ""))
