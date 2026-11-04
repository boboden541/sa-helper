#!/usr/bin/env python3
"""Лимит длины python-файлов (решение владельца 03.11.2026).

Правило: исходник <= 800 строк. Файлы из BASELINE (наследие до введения
правила) не могут расти — только уменьшаться; когда файл уложился в лимит,
строку из BASELINE удаляют. Проверка включена в pre-push хук и CI.
"""

from __future__ import annotations

import sys
from pathlib import Path

LIMIT = 800
# корни якорятся к каталогу скрипта (ai-harness/): проверка работает из
# любого cwd — из корня репо в CI и из ai-harness/ локально
ROOT = Path(__file__).resolve().parent.parent
ROOTS = ("backend", "daemon", "db", "tests", "scripts")

# Наследие: (путь от ai-harness, зафиксированный размер). Рост запрещён.
# 04.11.2026: scheduler.py (1597) разбит на модули — baseline пуст.
BASELINE: dict[str, int] = {}


def main() -> int:
    failures: list[str] = []
    for root in ROOTS:
        for path in (ROOT / root).rglob("*.py"):
            rel = str(path.relative_to(ROOT))
            lines = len(path.read_text(encoding="utf-8").splitlines())
            if rel in BASELINE:
                base = BASELINE[rel]
                if lines > base:
                    failures.append(
                        f"{rel}: {lines} строк — РОСТ над baseline {base}: "
                        "не добавляйте код в файл из baseline, выносите в новый модуль"
                    )
                elif lines < base:
                    print(
                        f"{rel}: {lines} < baseline {base} — уменьшился: "
                        f"обновите BASELINE (а лучше доведите до {LIMIT})"
                    )
                continue
            if lines > LIMIT:
                failures.append(f"{rel}: {lines} строк > {LIMIT} — разбейте файл")

    for f in failures:
        print("ОШИБКА:", f)
    if not failures:
        print(f"OK: все файлы <= {LIMIT} строк (baseline: {len(BASELINE)})")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
