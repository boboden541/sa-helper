#!/usr/bin/env bash
# Линт контента .claude: frontmatter скилов, формат команд, дрейф документации.
# Зеркалится в CI (.github/workflows/claude-content.yml) и в pre-push хуке.
# Локально: bash scripts/check_claude_content.sh (из корня репозитория)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SKILLS_DIR="$ROOT/.claude/skills"
COMMANDS_DIR="$ROOT/.claude/commands"
INSTALL_SH="$ROOT/install.sh"
README="$ROOT/README.md"

errors=0
fail() { echo "FAIL: $1"; errors=$((errors + 1)); }

# --- Скилы: frontmatter, name == каталогу, kebab-case, валидный description ---
for skill_dir in "$SKILLS_DIR"/*/; do
    name="$(basename "$skill_dir")"
    f="${skill_dir}SKILL.md"
    [ -f "$f" ] || { fail "skills/$name: нет SKILL.md"; continue; }

    if ! sed -n '1p' "$f" | grep -q '^---[[:space:]]*$'; then
        fail "skills/$name/SKILL.md: строка 1 не --- (нет frontmatter)"
        continue
    fi
    total="$(grep -c '^---[[:space:]]*$' "$f" || true)"
    [ "$total" -ge 2 ] || fail "skills/$name/SKILL.md: нет закрывающего --- во frontmatter"

    grep -Eq "^name:[[:space:]]*${name}[[:space:]]*$" "$f" \
        || fail "skills/$name/SKILL.md: name во frontmatter не совпадает с каталогом"
    grep -q '^description:' "$f" \
        || fail "skills/$name/SKILL.md: нет description"

    if grep -E '^description: [^"].*: ' "$f" >/dev/null 2>&1; then
        fail "skills/$name/SKILL.md: description без кавычек содержит ': ' (невалидный YAML)"
    fi

    case "$name" in
        *[!a-z0-9-]*) fail "skills/$name: имя каталога не в kebab-case" ;;
    esac
done

# --- Команды: frontmatter с непустым description ---
shopt -s nullglob
for c in "$COMMANDS_DIR"/*.md; do
    cname="$(basename "$c" .md)"
    if ! head -n 1 "$c" | grep -q '^---[[:space:]]*$'; then
        fail "commands/$cname: нет frontmatter"
        continue
    fi
    if ! sed -n '2,10s/^description: *//p' "$c" | head -n 1 | grep -q .; then
        fail "commands/$cname: пустой или отсутствующий description"
    fi
done

# --- Дрейф документации: каждая производственная команда есть в install.sh и README ---
for c in "$COMMANDS_DIR"/*.md; do
    cname="$(basename "$c" .md)"
    case "$cname" in harness-*) continue ;; esac
    grep -qE "/${cname}([^a-z0-9-]|\$)" "$INSTALL_SH" \
        || fail "install.sh: команда /${cname} отсутствует в финальном списке"
    grep -qE "/${cname}([^a-z0-9-]|\$)" "$README" \
        || fail "README.md: команда /${cname} не задокументирована"
done

declared="$(grep -oE 'производственных команд \([0-9]+\)' "$INSTALL_SH" | grep -oE '[0-9]+' || true)"
actual="$(find "$COMMANDS_DIR" -name '*.md' ! -name 'harness-*' | wc -l | tr -d ' ')"
if [ -n "$declared" ] && [ "$declared" != "$actual" ]; then
    fail "install.sh: заявлено ${declared} производственных команд, фактически ${actual}"
fi

if [ "$errors" -gt 0 ]; then
    echo "FAIL: check_claude_content: ${errors} ошибок"
    exit 1
fi
skills_n="$(find "$SKILLS_DIR" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')"
commands_n="$(find "$COMMANDS_DIR" -name '*.md' | wc -l | tr -d ' ')"
echo "OK: контент .claude в порядке (${skills_n} скилов, ${commands_n} команд, доки синхронны)"
