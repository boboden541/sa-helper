#!/bin/bash

# Если stdin — pipe (curl | bash / curl | sh), сохраняем себя во временный файл
# и перезапускаемся с терминалом, чтобы интерактивное меню могло читать нажатия клавиш.
if [ ! -t 0 ]; then
    TEMP_SCRIPT="$(mktemp)"
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
MAGENTA='\033[0;35m'
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
    echo -e "       ${CYAN}${BOLD}System Analyst Helper Framework v3.0${NC} ${DIM}[Neo4j & Semgrep Engine]${NC}"
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
        skill_description="$(sed -n '1s/^# *//p;q' "$skill_src/SKILL.md")"
        skill_description="${skill_description//\\/\\\\}"
        skill_description="${skill_description//\"/\\\"}"

        mkdir -p "$skill_dst"
        cp -R "$skill_src"/. "$skill_dst"/

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

# --- Функция интерактивного меню (Стрелочки / Цифры) ---
select_option_menu() {
    local prompt="$1"
    shift
    local options=("$@")
    local cur=0
    local count=${#options[@]}
    local key

    # Показать курсор при выходе
    trap 'printf "\e[?25h"' EXIT INT TERM
    printf "\e[?25l" # Скрыть курсор

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

        # Считывание нажатия клавиши
        read -rsn1 key 2>/dev/null
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
            # Цифровой ввод (поддержка 2-значных чисел)
            read -t 0.5 -n 1 second_digit 2>/dev/null || second_digit=""
            local full_num="${key}${second_digit}"
            local idx=$((full_num - 1))
            if [ "$idx" -ge 0 ] && [ "$idx" -lt "$count" ]; then
                cur=$idx
                break
            fi
        fi
    done

    printf "\e[?25h" # Показать курсор обратно
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
        COMMAND_DIR="prompts"
        SKILL_DIR="skills"
        SKILL_SYNC="canonical"
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
git clone --depth 1 "$REPO_URL" "$TEMP_DIR" &> /dev/null

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Ошибка: Не удалось скачать репозиторий. Проверьте интернет или URL.${NC}"
    exit 1
fi

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

# Удаление .DS_Store
find "$TARGET_DIR" -name ".DS_Store" -delete 2>/dev/null || true

# 5.1 Установка индексатора графа (Semgrep Engine)
if [ -d "$TEMP_DIR/indexer" ]; then
    echo -e "${YELLOW}📊 Настройка индексатора кодовой базы (Semgrep Engine)...${NC}"
    
    if command -v semgrep &> /dev/null; then
        echo -e "${DIM}✔ Semgrep найден в PATH — будет использован как основной движок индексации.${NC}"
    else
        echo -e "${DIM}ℹ️ Semgrep не установлен. Граф построится на встроенном Tree-sitter; Semgrep будет установлен автоматически при первом запуске /project-map (опциональный, рекомендуемый движок).${NC}"
    fi

    mkdir -p "indexer/semgrep_rules"
    cp -R "$TEMP_DIR/indexer/." "indexer/"
    chmod +x "indexer/main.py" 2>/dev/null
fi

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
echo -e "  Директория:   ${YELLOW}${TARGET_DIR}/${NC}"
if [ -n "$COMMAND_DIR" ]; then
    echo -e "                ├── ${COMMAND_DIR}/  ${DIM}(команды и правила)${NC}"
fi
if [ "$SKILL_SYNC" = "managed" ]; then
    echo -e "                └── ${SKILL_DIR}/     ${DIM}(навыки)${NC}"
else
    echo -e "                └── ${SKILL_DIR}/     ${DIM}(навыки с frontmatter)${NC}"
fi
echo ""
echo -e "  ${BOLD}Доступные производственные команды (13):${NC}"
echo -e "    ${BRIGHT_BLUE}/context-gen${NC}              — Подготовка контекста и репрезентации"
echo -e "    ${BRIGHT_BLUE}/arch-gen${NC}                 — Генерация архитектуры C4 (PlantUML)"
echo -e "    ${BRIGHT_BLUE}/data-trace${NC}               — Генерация DataFlow диаграмм"
echo -e "    ${BRIGHT_BLUE}/create-doc${NC}               — Спецификации и документация API"
echo -e "    ${BRIGHT_BLUE}/open-api${NC}                 — Генерация OpenAPI 3.0 (Swagger) specs"
echo -e "    ${BRIGHT_BLUE}/validate-doc${NC}             — Тотальный аудит соответствия коду"
echo -e "    ${BRIGHT_BLUE}/prd-grooming${NC}             — Диагностика и груминг требований PRD"
echo -e "    ${BRIGHT_BLUE}/bft-build${NC}                — Формирование БФТ спецификаций"
echo -e "    ${BRIGHT_BLUE}/fnr-new-task${NC}             — Постановка задачи и root-cause анализ"
echo -e "    ${BRIGHT_BLUE}/fnr-concept${NC}              — Генерация спектра архитектурных решений"
echo -e "    ${BRIGHT_BLUE}/fnr-debate${NC}               — Дебаты: Архитектор vs Адвокат Дьявола"
echo -e "    ${BRIGHT_BLUE}/fnr-system-requirements${NC}  — Формирование BR/FR/NFR + Jira"
echo -e "    ${BRIGHT_BLUE}/project-map${NC}             — Построение графа проекта (Neo4j)"
echo ""
echo -e "${YELLOW}⚠️  Важно: Перезагрузите окно вашей IDE (Reload Window) для активации.${NC}"
echo -e "${BLUE}----------------------------------------------------------------------${NC}"

# Очистка возможных stale temp-файлов
rm -f /tmp/sa-helper-install.*.sh 2>/dev/null
