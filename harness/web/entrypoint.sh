#!/bin/sh
# Разовая инициализация воркспейса командами конвейера + запуск сервиса.
set -e
WORK="${HARNESS_WORKSPACE:-/work}"

if [ -d "$WORK" ]; then
  mkdir -p "$WORK/.claude/commands" "$WORK/harness"
  # CLI Steward — рабочая копия в воркспейсе (allowlist-friendly путь)
  [ -f "$WORK/harness/steward_api.py" ] || cp /app/harness/steward_api.py "$WORK/harness/"
  for f in /opt/harness-commands/impl-*.md /opt/harness-commands/steward.md; do
    [ -f "$f" ] && cp -n "$f" "$WORK/.claude/commands/" 2>/dev/null || true
  done
fi

exec "$@"
