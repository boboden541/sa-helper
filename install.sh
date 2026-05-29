#!/bin/bash

# --- Цвета для оформления ---
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# --- Настройки репозитория ---
REPO_URL="https://github.com/boboden541/sa-helper.git"
TEMP_DIR=".sa_helper_temp"
SOURCE_ROOT=".claude"

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

echo -e "${BLUE}==========================================${NC}"
echo -e "${BLUE}  System Analyst Helper: Installation${NC}"
echo -e "${BLUE}==========================================${NC}"

# 0. При запуске через pipe (curl ... | bash) stdin занят — читаем с терминала
if [ ! -t 0 ]; then
    exec 0</dev/tty
fi

# 1. Проверка наличия Git
if ! command -v git &> /dev/null; then
    echo -e "${RED}❌ Ошибка: Git не установлен. Установите Git и попробуйте снова.${NC}"
    exit 1
fi

# 2. Выбор агента
echo ""
echo -e "${CYAN}Какой IDE-агент вы используете?${NC}"
echo -e "  ${BLUE}[1]${NC} Claude Code"
echo -e "  ${BLUE}[2]${NC} Antigravity"
echo -e "  ${BLUE}[3]${NC} Codex"
echo -e "  ${BLUE}[4]${NC} OpenCode"
echo -e "  ${BLUE}[5]${NC} Cline"
echo -e "  ${BLUE}[6]${NC} DevX"
echo -e "  ${BLUE}[7]${NC} Universal (.agents)"
echo ""
read -p "Введите номер [1/7]: " AGENT_CHOICE

case "$AGENT_CHOICE" in
    1)
        AGENT_NAME="Claude Code"
        TARGET_DIR=".claude"
        COMMAND_DIR="commands"
        SKILL_DIR="skills"
        SKILL_SYNC="managed"
        ;;
    2)
        AGENT_NAME="Antigravity"
        TARGET_DIR=".agent"
        COMMAND_DIR="workflows"
        SKILL_DIR="skills"
        SKILL_SYNC="managed"
        ;;
    3)
        AGENT_NAME="Codex"
        TARGET_DIR=".agents"
        COMMAND_DIR="prompts"
        SKILL_DIR="skills"
        SKILL_SYNC="canonical"
        ;;
    4)
        AGENT_NAME="OpenCode"
        TARGET_DIR=".opencode"
        COMMAND_DIR="commands"
        SKILL_DIR="skills"
        SKILL_SYNC="canonical"
        ;;
    5)
        AGENT_NAME="Cline"
        TARGET_DIR=".cline"
        COMMAND_DIR="workflows"
        SKILL_DIR="skills"
        SKILL_SYNC="canonical"
        ;;
    6)
        AGENT_NAME="DevX"
        TARGET_DIR=".clinerules"
        COMMAND_DIR="workflows"
        SKILL_DIR="skills"
        SKILL_SYNC="canonical"
        ;;
    7)
        AGENT_NAME="Universal"
        TARGET_DIR=".agents"
        COMMAND_DIR="commands"
        SKILL_DIR="skills"
        SKILL_SYNC="canonical"
        ;;
    *)
        echo -e "${RED}❌ Некорректный выбор. Введите число от 1 до 7.${NC}"
        exit 1
        ;;
esac

echo ""
echo -e "${GREEN}Выбран агент: ${AGENT_NAME}${NC}"
if [ -n "$COMMAND_DIR" ]; then
    echo -e "  Структура: ${YELLOW}${TARGET_DIR}/${COMMAND_DIR}/${NC} + ${YELLOW}${TARGET_DIR}/${SKILL_DIR}/${NC}"
else
    echo -e "  Структура: ${YELLOW}${TARGET_DIR}/${SKILL_DIR}/${NC}"
fi

# 3. Скачивание репозитория
echo ""
echo -e "${YELLOW}📡 Получение файлов из репозитория...${NC}"
rm -rf "$TEMP_DIR"
git clone --depth 1 "$REPO_URL" "$TEMP_DIR" &> /dev/null

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Ошибка: Не удалось скачать репозиторий. Проверьте интернет или URL.${NC}"
    exit 1
fi

# 4. Проверка исходной структуры
if [ ! -d "$TEMP_DIR/$SOURCE_ROOT" ]; then
    echo -e "${RED}❌ Ошибка: В репозитории не найдена папка ${SOURCE_ROOT}/${NC}"
    rm -rf "$TEMP_DIR"
    exit 1
fi

# 5. Установка
echo -e "${YELLOW}📂 Установка компонентов для ${AGENT_NAME}...${NC}"

mkdir -p "$TARGET_DIR"

# Обновляем только управляемые подпапки выбранного агента.
if [ -n "$COMMAND_DIR" ]; then
    sync_managed_tree "$TEMP_DIR/$SOURCE_ROOT/commands" "$TARGET_DIR/$COMMAND_DIR"
fi

if [ "$SKILL_SYNC" = "canonical" ]; then
    sync_canonical_skills "$TEMP_DIR/$SOURCE_ROOT/skills" "$TARGET_DIR/$SKILL_DIR"
elif [ "$SKILL_SYNC" = "managed" ]; then
    sync_managed_tree "$TEMP_DIR/$SOURCE_ROOT/skills" "$TARGET_DIR/$SKILL_DIR"
fi

# Удаление .DS_Store
find "$TARGET_DIR" -name ".DS_Store" -delete

# 5.1 Установка индексатора графа
if [ -d "$TEMP_DIR/indexer" ]; then
    echo -e "${YELLOW}📊 Установка индексатора графа...${NC}"
    mkdir -p "indexer/parsers"
    cp -R "$TEMP_DIR/indexer/." "indexer/"
    chmod +x "indexer/main.py" 2>/dev/null
fi

# 6. Очистка временной папки
rm -rf "$TEMP_DIR"

# 7. Финальное сообщение
echo ""
echo -e "${BLUE}------------------------------------------${NC}"
echo -e "${GREEN}✨ Установка завершена успешно!${NC}"
echo ""
echo -e "Агент:        ${CYAN}${AGENT_NAME}${NC}"
echo -e "Структура:    ${YELLOW}${TARGET_DIR}/${NC}"
if [ -n "$COMMAND_DIR" ]; then
    echo -e "              ├── ${COMMAND_DIR}/  (команды)"
fi
if [ "$SKILL_SYNC" = "managed" ]; then
    echo -e "              └── ${SKILL_DIR}/     (навыки)"
else
    echo -e "              └── ${SKILL_DIR}/     (навыки с frontmatter)"
fi
echo ""
echo -e "Доступные команды:"
echo -e "  ${BLUE}/context-gen${NC}              — Подготовка контекста"
echo -e "  ${BLUE}/arch-gen${NC}                 — Генерация архитектуры (C4)"
echo -e "  ${BLUE}/data-trace${NC}               — Генерация DataFlow"
echo -e "  ${BLUE}/create-doc${NC}               — Генерация документации"
echo -e "  ${BLUE}/validate-doc${NC}             — Проверка на ошибки"
echo -e "  ${BLUE}/fnr-new-task${NC}             — Постановка задачи"
echo -e "  ${BLUE}/fnr-concept${NC}              — Генерация решений"
echo -e "  ${BLUE}/fnr-debate${NC}               — Архитектурные дебаты"
echo -e "  ${BLUE}/fnr-system-requirements${NC}  — Системные требования"
echo -e "  ${BLUE}/project-map${NC}             — Построение графа проекта (Neo4j)"
echo ""
echo -e "${YELLOW}⚠️  Важно: Перезагрузите IDE (Reload Window).${NC}"
echo -e "${BLUE}==========================================${NC}"
