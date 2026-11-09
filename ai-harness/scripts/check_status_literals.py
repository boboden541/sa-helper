"""ФНР-16: grep-барьер — литеральные сравнения статусных ключей в коде процесса
запрещены; семантика живёт в данных (when на рёбрах, behaviors/kind на статусах).

BASELINE-механика как у check_file_length.py: перечисленные нарушения могут
уменьшаться, но не расти. Новые — ошибка.

Канонический словарь стадий — domain/mirroring/predicates.py: CHILD_*-множества
и предикаты — единственное место домена, где литеральные ключи статусов
разрешены (мост данные→код); ACTIVE_STATUSES (graph.py) — псевдоним канона.
Статусы ПУНКТОВ чеклиста (done/closed в context_bundle._OPEN) — другой
словарь: это не стадии задач, греп-барьер их не описывает."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = [ROOT / "backend/src/domain", ROOT / "daemon"]
PATTERN = re.compile(r"""status_key\s*(==|!=|in)\s*[\["']""")
# Байтовый файл baseline: "путь:строка:фрагмент" — по образцу check_file_length.
BASELINE = Path(__file__).resolve().parent / "status_literals_baseline.txt"


def violations() -> list[str]:
    found: list[str] = []
    for base in SCAN_DIRS:
        for py in base.rglob("*.py"):
            rel = py.relative_to(ROOT.parent).as_posix()
            for i, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
                if PATTERN.search(line):
                    found.append(f"{rel}:{i}:{line.strip()[:90]}")
    return found


def main() -> int:
    allowed = set(
        line.strip()
        for line in BASELINE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    )
    current = violations()
    new = [v for v in current if v not in allowed]
    stale = [v for v in allowed if v not in current]
    if new:
        print("Новые литеральные сравнения статусных ключей (ФНР-16 grep-барьер):")
        for v in new:
            print(f"  {v}")
        print("Семантика — в данные: when на рёбрах, behaviors/kind на статусах.")
        return 1
    for v in stale:
        print(f"baseline устарел (нарушение исправлено, убери из baseline): {v}")
    print(f"OK: литеральных нарушений сверх baseline ({len(allowed)}) нет")
    return 0


if __name__ == "__main__":
    sys.exit(main())
