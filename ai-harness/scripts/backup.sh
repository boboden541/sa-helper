#!/usr/bin/env bash
# Бэкап postgres в дамп (gzip). Раньше стратегии резервного копирования не
# было вовсе — named volume при порче терялся безвозвратно (анализ 11.11.2026).
# Использование: scripts/backup.sh [файл-назначения]
# Восстановление: cat <файл>.sql.gz | docker compose exec -T postgres \
#   psql -U harness -d ai_harness   (на ПУСТУЮ базу; живую не перезаписывать!)
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="${1:-backups/ai_harness_$(date +%Y%m%d_%H%M%S).sql.gz}"
mkdir -p "$(dirname "$OUT")"
docker compose exec -T postgres pg_dump -U "${POSTGRES_USER:-harness}" -d "${POSTGRES_DB:-ai_harness}" | gzip > "$OUT"
echo "дамп: $OUT ($(du -h "$OUT" | cut -f1))"
