#!/bin/sh
# Разовая инициализация воркспейса командами конвейера + запуск сервиса.
set -e
WORK="${HARNESS_WORKSPACE:-/work}"

if [ -d "$WORK" ]; then
  mkdir -p "$WORK/.claude/commands" "$WORK/harness"
  # Адаптер агентов и его зависимости — рабочие копии в воркспейсе
  # (sahelper резолвит импорты относительно своего файла)
  for f in steward_api.py sahelper.py db.py cards.py state_machine.py review_gate.py; do
    [ -f "/app/harness/$f" ] && cp "/app/harness/$f" "$WORK/harness/" 2>/dev/null || true
  done
  # адаптер нужен и в harness-каталоге каждой Story (промпты ссылаются на него
  # относительно пути задачи)
  for hd in "$WORK"/sa_documentation/FNR/FNR_*/harness; do
    [ -d "$hd" ] || continue
    for f in sahelper.py db.py cards.py state_machine.py review_gate.py; do
      [ -f "/app/harness/$f" ] && cp "/app/harness/$f" "$hd/" 2>/dev/null || true
    done
  done
  for f in /opt/harness-commands/impl-*.md /opt/harness-commands/steward.md; do
    [ -f "$f" ] && cp "$f" "$WORK/.claude/commands/" 2>/dev/null || true
  done
  # allowlist адаптера (одна строка) в настройки воркспейса
  SETTINGS="$WORK/.claude/settings.json"
  if [ -f "$SETTINGS" ] && ! grep -q "sahelper" "$SETTINGS" 2>/dev/null; then
    python3 - "$SETTINGS" <<'PY'
import json, sys
p = sys.argv[1]
try:
    d = json.loads(open(p, encoding="utf-8").read())
except Exception:
    d = {}
allow = d.setdefault("permissions", {}).setdefault("allow", [])
line = "Bash(python3 harness/sahelper.py:*)"
if line not in allow:
    allow.append(line)
open(p, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=2))
PY
  fi
fi

exec "$@"
