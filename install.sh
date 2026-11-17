#!/bin/bash

# Если stdin — pipe (curl | bash / curl | sh), сохраняем себя во временный файл
# и перезапускаемся с терминалом, чтобы интерактивное меню могло читать нажатия клавиш.
if [ ! -t 0 ]; then
    # export обязателен: после exec новая оболочка видит только экспортированные
    # переменные — без него финальная очистка TEMP_SCRIPT не срабатывает
    # и временный файл остаётся в $TMPDIR навсегда.
    export TEMP_SCRIPT="$(mktemp)"
    cat > "$TEMP_SCRIPT"
    exec bash "$TEMP_SCRIPT" < /dev/tty
fi

# Если скрипт запустили через POSIX-шелл (sh/dash), а не через bash — перезапуск под bash.
# Иначе bash-массивы AGENT_LIST=(...) ниже вызовут: syntax error near unexpected token '('.
# (шебанг #!/bin/bash игнорируется при явном вызове `sh install.sh` или `curl ... | sh`.)
if [ -z "$BASH_VERSION" ]; then
    exec bash "$0" "$@"
fi

# --- Цвета и стилевое оформление ---
BOLD='\033[1m'
GREEN='\033[0;32m'
BRIGHT_GREEN='\033[1;32m'
BLUE='\033[0;34m'
BRIGHT_BLUE='\033[1;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
DIM='\033[2m'
NC='\033[0m' # No Color

# --- Настройки репозитория ---
REPO_URL="https://github.com/boboden541/sa-helper.git"
TEMP_DIR=".sa_helper_temp"
SOURCE_ROOT=".claude"

# --- Красивый ASCII Логотип ---
print_banner() {
    clear 2>/dev/null || true
    echo -e "${BRIGHT_BLUE}"
    echo -e "  🔮  ____    _       _   _ _____ _     ____  _____ ____  "
    echo -e "     / ___|  / \     | | | | ____| |   |  _ \| ____|  _ \ "
    echo -e "     \___ \ / _ \    | |_| |  _| | |   | |_) |  _| | |_) |"
    echo -e "      ___) / ___ \   |  _  | |___| |___|  __/| |___|  _ < "
    echo -e "     |____/_/   \_\  |_| |_|_____|_____|_|   |_____|_| \_\\"
    echo -e "${NC}"
    echo -e "       ${CYAN}${BOLD}System Analyst Helper Framework v3.0${NC} ${DIM}[Реверс-инжиниринг · FNR Pipeline · AI-Harness]${NC}"
    echo -e " ${DIM}----------------------------------------------------------------------${NC}"
    echo ""
}


sync_managed_tree() {
    local src_dir="$1"
    local dst_dir="$2"

    mkdir -p "$dst_dir"
    if [ -d "$src_dir" ]; then
        cp -R "$src_dir"/. "$dst_dir"/
    fi
}

sync_canonical_skills() {
    local src_dir="$1"
    local dst_dir="$2"
    local skill_dir
    local skill_name
    local skill_src
    local skill_dst
    local skill_description

    mkdir -p "$dst_dir"

    for skill_src in "$src_dir"/*; do
        [ -d "$skill_src" ] || continue
        [ -f "$skill_src/SKILL.md" ] || continue

        skill_dir="$(basename "$skill_src")"
        skill_name="$skill_dir"
        skill_dst="$dst_dir/$skill_dir"

        mkdir -p "$skill_dst"
        cp -R "$skill_src"/. "$skill_dst"/

        # SKILL.md уже с YAML-frontmatter (канон формата) — переносим как есть.
        if head -n 1 "$skill_src/SKILL.md" | grep -q '^---[[:space:]]*$'; then
            continue
        fi

        # Legacy-ветка (первая строка — H1-заголовок): генерируем frontmatter
        # из заголовка и срезаем его из тела.
        skill_description="$(sed -n '1s/^# *//p;q' "$skill_src/SKILL.md")"
        skill_description="${skill_description//\\/\\\\}"
        skill_description="${skill_description//\"/\\\"}"

        if [ -z "$skill_description" ]; then
            skill_description="$skill_name"
        fi

        {
            printf '%s\n' '---'
            printf 'name: %s\n' "$skill_name"
            printf 'description: "%s"\n' "$skill_description"
            printf '%s\n' '---'
            sed '1d' "$skill_src/SKILL.md"
        } > "$skill_dst/SKILL.md"
    done
}

# Команды как скилы (режим Codex). Codex не сканирует repo-локальные промты:
# custom prompts живут только в ~/.codex/prompts (домашняя папка) и признаны
# OpenAI устаревшими в пользу skills. Поэтому каждая команда превращается
# в скил <dst_dir>/<имя_команды>/SKILL.md и вызывается в Codex через $<имя>.
sync_commands_as_skills() {
    local src_dir="$1"
    local dst_dir="$2"
    local cmd_file
    local cmd_name
    local cmd_dst
    local cmd_description
    local body_start

    mkdir -p "$dst_dir"

    for cmd_file in "$src_dir"/*.md; do
        [ -f "$cmd_file" ] || continue

        cmd_name="$(basename "$cmd_file" .md)"
        cmd_dst="$dst_dir/$cmd_name"

        # Формат команды: строка 1 `---`, строка 2 `description: ...`, строка 3 `---`.
        # Если frontmatter нет — телом считается весь файл, описание = имя команды.
        if head -n 1 "$cmd_file" | grep -q '^---[[:space:]]*$'; then
            cmd_description="$(sed -n '2,10s/^description: *//p' "$cmd_file" | head -n 1)"
            cmd_description="${cmd_description//\\/\\\\}"
            cmd_description="${cmd_description//\"/\\\"}"
            body_start=4
        else
            cmd_description=""
            body_start=1
        fi
        [ -n "$cmd_description" ] || cmd_description="$cmd_name"

        mkdir -p "$cmd_dst"

        {
            printf '%s\n' '---'
            printf 'name: %s\n' "$cmd_name"
            printf 'description: "%s"\n' "$cmd_description"
            printf '%s\n' '---'
            sed -n "${body_start},\$p" "$cmd_file"
        } > "$cmd_dst/SKILL.md"
    done
}

# --- Манифест установки: версия + список файлов, которые ставит установщик ---
# Список строится из ИСТОЧНИКА (клона), а не с диска: при повторной установке
# удаляется ровно то, что ставил установщик в прошлый раз и чего нет в новой
# версии (переименования/удаления из репо доезжают до пользователя). Файлы
# пользователя в манифест не попадают и не удаляются никогда.
expected_list_files() {
    if [ -n "$COMMAND_DIR" ]; then
        (cd "$TEMP_DIR/$SOURCE_ROOT/commands" && find . -type f | sed "s|^\./|$COMMAND_DIR/|" | sort)
    fi
    (cd "$TEMP_DIR/$SOURCE_ROOT/skills" && find . -type f | sed "s|^\./|$SKILL_DIR/|" | sort)
    if [ "$COMMANDS_AS_SKILLS" = "1" ]; then
        (cd "$TEMP_DIR/$SOURCE_ROOT/commands" && find . -type f -name '*.md' \
            | sed "s|^\./|$SKILL_DIR/|" | sed 's|\.md$|/SKILL.md|' | sort)
    fi
}

write_manifest() {
    {
        echo "# sa-helper install manifest — ведётся установщиком, ручные правки затираются"
        echo "version: $1"
        echo "agent: $2"
        echo "target: $3"
        expected_list_files | sed 's/^/file: /'
    } > "$4"
}

update_install_manifest() {
    local manifest="$TARGET_DIR/sa-helper.manifest"
    local new_manifest expected
    new_manifest="$(mktemp)"
    expected="$(mktemp)"
    expected_list_files | sed 's/^/file: /' > "$expected"
    write_manifest "$INSTALLED_VERSION" "$AGENT_NAME" "$TARGET_DIR" "$new_manifest"
    if [ -f "$manifest" ]; then
        local rel
        while IFS= read -r rel; do
            [ -n "$rel" ] || continue
            case "$rel" in *..*|/*) continue ;; esac
            grep -qFx "file: $rel" "$expected" || rm -f "$TARGET_DIR/$rel"
        done < <(sed -n 's/^file: //p' "$manifest")
        local base
        for base in "$COMMAND_DIR" "$SKILL_DIR"; do
            [ -n "$base" ] && [ -d "$TARGET_DIR/$base" ] \
                && find "$TARGET_DIR/$base" -mindepth 1 -type d -empty -delete 2>/dev/null || true
        done
    fi
    mv "$new_manifest" "$manifest"
    rm -f "$expected"
}

# --- Функция интерактивного меню (Стрелочки / Цифры) ---
select_option_menu() {
    local prompt="$1"
    shift
    local options=("$@")
    local cur=0
    local count=${#options[@]}
    local key

    # Альтернативный экран: перерисовка меню не пачкает скроллбек и почти не мерцает
    trap 'printf "\e[?25h\e[?1049l"' EXIT INT TERM
    printf "\e[?1049h\e[?25l"

    while true; do
        print_banner
        echo -e "${CYAN}${BOLD}$prompt${NC} ${DIM}[используйте ↑/↓ или введите номер 1-$count]:${NC}\n"


        for i in "${!options[@]}"; do
            local num=$((i + 1))
            if [ "$i" -eq "$cur" ]; then
                echo -e "   ${BRIGHT_GREEN}❯ [$num] ${options[$i]}${NC}"
            else
                echo -e "     ${DIM}[$num] ${options[$i]}${NC}"
            fi
        done

        # Считывание нажатия клавиши. Потеря stdin (tty закрылся) — не выбор,
        # а честный отказ: иначе пустой key ложно трактуется как Enter.
        if ! read -rsn1 key 2>/dev/null; then
            printf "\e[?1049l\e[?25h"
            return 255
        fi
        if [ "$key" == $'\x1b' ]; then
            read -rsn2 key 2>/dev/null
            if [ "$key" == "[A" ]; then # Вверх
                cur=$(( (cur - 1 + count) % count ))
            elif [ "$key" == "[B" ]; then # Вниз
                cur=$(( (cur + 1) % count ))
            fi
        elif [ "$key" == "" ]; then # Enter
            break
        elif [[ "$key" =~ [0-9] ]]; then
            # Цифровой ввод. Вторую цифру ждём только для неоднозначной «1»
            # (префикс номеров 10–13): остальные цифры выбирают сразу, без задержки.
            # -t 1 (целое): дробные таймауты появились лишь в bash 4, а /bin/bash
            # на macOS — 3.2, где read -t 0.5 падал и пункт выбирался неверно.
            local full_num="$key"
            if [ "$count" -gt 9 ] && [ "$key" = "1" ]; then
                local second_digit=""
                read -t 1 -n 1 second_digit 2>/dev/null || second_digit=""
                case "$second_digit" in
                    [0-9]) full_num="${key}${second_digit}" ;;
                esac
            fi
            local idx=$((full_num - 1))
            if [ "$idx" -ge 0 ] && [ "$idx" -lt "$count" ]; then
                cur=$idx
                break
            fi
        fi
    done

    printf "\e[?1049l\e[?25h" # Вернуться на основной экран, показать курсор
    return "$cur"
}

print_banner

# 1. Проверка наличия Git
if ! command -v git &> /dev/null; then
    echo -e "${RED}❌ Ошибка: Git не установлен. Установите Git и попробуйте снова.${NC}"
    exit 1
fi

# Список агентов
AGENT_LIST=(
    "Claude Code (.claude/)"
    "Antigravity (.agent/)"
    "Codex (.agents/)"
    "OpenCode (.opencode/)"
    "Cline (.cline/)"
    "DevX (МТС) (.clinerules/)"
    "Universal (.agents/)"
    "Cursor (.cursor/)"
    "Windsurf (Cascade) (.windsurf/)"
    "Roo Code (.roo/)"
    "Continue.dev (.continue/)"
    "GitHub Copilot (.github/)"
    "Aider CLI (.aider/)"
)

# 2. Интерактивный выбор агента
select_option_menu "Какой IDE-агент вы используете?" "${AGENT_LIST[@]}"
AGENT_INDEX=$?
if [ "$AGENT_INDEX" -eq 255 ]; then
    echo -e "${RED}❌ Не удалось прочитать ввод: терминал недоступен.${NC}" >&2
    exit 1
fi
COMMANDS_AS_SKILLS=""

case "$AGENT_INDEX" in
    0)
        AGENT_NAME="Claude Code"
        TARGET_DIR=".claude"
        COMMAND_DIR="commands"
        SKILL_DIR="skills"
        SKILL_SYNC="managed"
        ;;
    1)
        AGENT_NAME="Antigravity"
        TARGET_DIR=".agent"
        COMMAND_DIR="workflows"
        SKILL_DIR="skills"
        SKILL_SYNC="managed"
        ;;
    2)
        AGENT_NAME="Codex"
        TARGET_DIR=".agents"
        COMMAND_DIR=""
        SKILL_DIR="skills"
        SKILL_SYNC="canonical"
        # Команды ставятся скилами: Codex не читает repo-локальные промты
        # (.agents/prompts/ он не сканирует вовсе).
        COMMANDS_AS_SKILLS=1
        ;;
    3)
        AGENT_NAME="OpenCode"
        TARGET_DIR=".opencode"
        COMMAND_DIR="commands"
        SKILL_DIR="skills"
        SKILL_SYNC="canonical"
        ;;
    4)
        AGENT_NAME="Cline"
        TARGET_DIR=".cline"
        COMMAND_DIR="workflows"
        SKILL_DIR="skills"
        SKILL_SYNC="canonical"
        ;;
    5)
        AGENT_NAME="DevX"
        TARGET_DIR=".clinerules"
        COMMAND_DIR="workflows"
        SKILL_DIR="skills"
        SKILL_SYNC="canonical"
        ;;
    6)
        AGENT_NAME="Universal"
        TARGET_DIR=".agents"
        COMMAND_DIR="commands"
        SKILL_DIR="skills"
        SKILL_SYNC="canonical"
        ;;
    7)
        AGENT_NAME="Cursor"
        TARGET_DIR=".cursor"
        COMMAND_DIR="rules"
        SKILL_DIR="skills"
        SKILL_SYNC="canonical"
        ;;
    8)
        AGENT_NAME="Windsurf"
        TARGET_DIR=".windsurf"
        COMMAND_DIR="rules"
        SKILL_DIR="skills"
        SKILL_SYNC="canonical"
        ;;
    9)
        AGENT_NAME="Roo Code"
        TARGET_DIR=".roo"
        COMMAND_DIR="workflows"
        SKILL_DIR="skills"
        SKILL_SYNC="canonical"
        ;;
    10)
        AGENT_NAME="Continue.dev"
        TARGET_DIR=".continue"
        COMMAND_DIR="prompts"
        SKILL_DIR="skills"
        SKILL_SYNC="canonical"
        ;;
    11)
        AGENT_NAME="GitHub Copilot"
        TARGET_DIR=".github"
        COMMAND_DIR="prompts"
        SKILL_DIR="skills"
        SKILL_SYNC="canonical"
        ;;
    12)
        AGENT_NAME="Aider"
        TARGET_DIR=".aider"
        COMMAND_DIR="prompts"
        SKILL_DIR="skills"
        SKILL_SYNC="canonical"
        ;;
    *)
        AGENT_NAME="Claude Code"
        TARGET_DIR=".claude"
        COMMAND_DIR="commands"
        SKILL_DIR="skills"
        SKILL_SYNC="managed"
        ;;
esac

print_banner
echo -e "${BRIGHT_GREEN}✔ Выбран агент:${NC} ${BOLD}${CYAN}${AGENT_NAME}${NC}"
if [ -n "$COMMAND_DIR" ]; then
    echo -e "  ${DIM}Целевая структура:${NC} ${YELLOW}${TARGET_DIR}/${COMMAND_DIR}/${NC} + ${YELLOW}${TARGET_DIR}/${SKILL_DIR}/${NC}"
else
    echo -e "  ${DIM}Целевая структура:${NC} ${YELLOW}${TARGET_DIR}/${SKILL_DIR}/${NC}"
fi

# 3. Скачивание репозитория
echo ""
echo -e "${YELLOW}📡 Клонирование шаблонов из репозитория...${NC}"
rm -rf "$TEMP_DIR" 2>/dev/null
CLONE_LOG="$(mktemp)"
if ! git clone --depth 1 "$REPO_URL" "$TEMP_DIR" >"$CLONE_LOG" 2>&1; then
    echo -e "${RED}❌ Ошибка: Не удалось скачать репозиторий. Проверьте интернет или URL.${NC}"
    echo -e "${DIM}$(tail -n 3 "$CLONE_LOG")${NC}"
    rm -f "$CLONE_LOG"
    exit 1
fi
rm -f "$CLONE_LOG"

# 4. Проверка исходной структуры
if [ ! -d "$TEMP_DIR/$SOURCE_ROOT" ]; then
    echo -e "${RED}❌ Ошибка: В репозитории не найдена папка ${SOURCE_ROOT}/${NC}"
    chmod -R 777 "$TEMP_DIR" 2>/dev/null || true
    rm -rf "$TEMP_DIR" 2>/dev/null || true
    exit 1
fi

# 5. Установка
echo -e "${YELLOW}📂 Копирование команд и навыков для ${AGENT_NAME}...${NC}"

mkdir -p "$TARGET_DIR"

if [ -n "$COMMAND_DIR" ]; then
    sync_managed_tree "$TEMP_DIR/$SOURCE_ROOT/commands" "$TARGET_DIR/$COMMAND_DIR"
fi

if [ "$SKILL_SYNC" = "canonical" ]; then
    sync_canonical_skills "$TEMP_DIR/$SOURCE_ROOT/skills" "$TARGET_DIR/$SKILL_DIR"
elif [ "$SKILL_SYNC" = "managed" ]; then
    sync_managed_tree "$TEMP_DIR/$SOURCE_ROOT/skills" "$TARGET_DIR/$SKILL_DIR"
fi

if [ "$COMMANDS_AS_SKILLS" = "1" ]; then
    # Рудимент прошлых установок: .agents/prompts/ Codex всё равно не читает.
    rm -rf "$TARGET_DIR/prompts" 2>/dev/null || true
    sync_commands_as_skills "$TEMP_DIR/$SOURCE_ROOT/commands" "$TARGET_DIR/$SKILL_DIR"
fi

INSTALLED_VERSION="$(git -C "$TEMP_DIR" rev-parse --short HEAD 2>/dev/null || echo unknown)"
update_install_manifest

# Список производственных команд генерируется из клона — одно место истины:
# описание берётся из frontmatter description каждой команды. Harness-этапы не входят.
PROD_COUNT=0
PROD_BLOCK=""
for cmd_file in "$TEMP_DIR/$SOURCE_ROOT"/commands/*.md; do
    [ -f "$cmd_file" ] || continue
    cmd_name="$(basename "$cmd_file" .md)"
    case "$cmd_name" in harness-*) continue ;; esac
    PROD_COUNT=$((PROD_COUNT + 1))
    cmd_desc="$(sed -n '2,10s/^description: *//p' "$cmd_file" | head -n 1)"
    [ -n "$cmd_desc" ] || cmd_desc="$cmd_name"
    printf -v PROD_LINE '    %b/%s%s — %s\n' "$BRIGHT_BLUE" "$cmd_name" "$NC" "$cmd_desc"
    PROD_BLOCK+="$PROD_LINE"
done

# Удаление .DS_Store
find "$TARGET_DIR" -name ".DS_Store" -delete 2>/dev/null || true

# 6. Надежная очистка временной папки (с поддержкой Windows/Git Bash)
chmod -R 777 "$TEMP_DIR" 2>/dev/null || true
rm -rf "$TEMP_DIR" 2>/dev/null || true
if [ -d "$TEMP_DIR" ]; then
    powershell.exe -Command "Remove-Item -Recurse -Force '$TEMP_DIR'" 2>/dev/null || true
fi

# 7. Финальное красивое сообщение
echo ""
echo -e "${BLUE}================================--------------------------------------${NC}"
echo -e " ${BRIGHT_GREEN}✨ Установка SA-Helper успешно завершена!${NC}"
echo -e "${BLUE}================================--------------------------------------${NC}"
echo ""
echo -e "  Агент:        ${CYAN}${BOLD}${AGENT_NAME}${NC}"
echo -e "  Версия:       ${CYAN}${INSTALLED_VERSION}${NC} ${DIM}(манифест: ${TARGET_DIR}/sa-helper.manifest)${NC}"
echo -e "  Директория:   ${YELLOW}${TARGET_DIR}/${NC}"
if [ -n "$COMMAND_DIR" ]; then
    echo -e "                ├── ${COMMAND_DIR}/  ${DIM}(команды и правила)${NC}"
fi
if [ "$COMMANDS_AS_SKILLS" = "1" ]; then
    echo -e "                └── ${SKILL_DIR}/     ${DIM}(навыки + команды как скилы)${NC}"
elif [ "$SKILL_SYNC" = "managed" ]; then
    echo -e "                └── ${SKILL_DIR}/     ${DIM}(навыки)${NC}"
else
    echo -e "                └── ${SKILL_DIR}/     ${DIM}(навыки с frontmatter)${NC}"
fi
echo ""
echo -e "  ${BOLD}Доступные производственные команды (${PROD_COUNT}):${NC}"
printf '%b' "$PROD_BLOCK"
echo ""
if [ "$COMMANDS_AS_SKILLS" = "1" ]; then
    echo -e "  ${DIM}Codex читает из репозитория только скилы: команды вызываются как${NC}"
    echo -e "  ${DIM}\$context-gen, \$fnr-new-task и т.д. (или через /skills). Перезапустите сессию Codex.${NC}"
    echo ""
fi
echo -e "${YELLOW}⚠️  Важно: Перезагрузите окно вашей IDE (Reload Window) для активации.${NC}"
echo -e "${BLUE}----------------------------------------------------------------------${NC}"

# Очистка: временная копия самого скрипта из pipe-режима (curl | bash)
[ -n "${TEMP_SCRIPT:-}" ] && [ -f "${TEMP_SCRIPT:-}" ] && rm -f "$TEMP_SCRIPT"
