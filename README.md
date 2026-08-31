<p align="center">
  <strong>System Analyst Helper</strong><br>
  <em>Промышленный фреймворк для&nbsp;ИИ‑агентов: реверс‑инжиниринг, документация, системные требования</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.9+-3776AB?logo=python&logoColor=white" alt="Python 3.9+">
  <img src="https://img.shields.io/badge/neo4j-5-community-018BFF?logo=neo4j&logoColor=white" alt="Neo4j 5">
  <img src="https://img.shields.io/badge/languages-6-green" alt="6 Languages">
  <img src="https://img.shields.io/badge/MCP-13%20tools-purple" alt="13 MCP Tools">
</p>

---

> **Реверс‑инжиниринг** — превращайте код в C4‑диаграммы, DataFlow и API‑спецификации.<br>
> **Системные требования** — проходите путь от проблемы до формального BR/FR/NFR с Jira‑декомпозицией.<br>
> **Discovery** — превращайте размытую постановку в конкретные вопросы‑развилки для руководства и брифинг для согласования.
>
> Ключевой принцип — **нулевой допуск к галлюцинациям**: каждый факт прослеживается до строки кода (Traceability).

---

## Содержание

- [Быстрый старт (Установка)](#-быстрый-старт-установка)
- [Обновление](#-обновление)
- [Процессы и диаграммы](#-процессы-и-диаграммы)
- [Доступные команды](#-доступные-команды)
- [Стандарт Doc-Architect v3.0](#-стандарт-doc-architect-v30)
- [Структура системы](#-структура-системы)
- [Структура sa_documentation](#-структура-sa_documentation)
- [Применение на практике](#применение-на-практике)
- [Граф проекта (Neo4j)](#-граф-проекта-neo4j)

---

## ⚡ Быстрый старт (Установка)

Разверните SA-Helper в проекте одной командой:

<!-- prettier-ignore -->
| Платформа | Команда |
|-----------|---------|
| **macOS / Linux** | `curl -sSL https://raw.githubusercontent.com/boboden541/sa-helper/main/install.sh \| bash` |
| **Windows (Git Bash)** | `curl --ssl-no-revoke -sSL https://raw.githubusercontent.com/boboden541/sa-helper/main/install.sh -o /tmp/sa-install.sh && bash /tmp/sa-install.sh && rm -f /tmp/sa-install.sh` |

> **Обновление после правок эталонов и ресурсов.** Команды и навыки работают с **установленной** копией в вашем проекте. Если изменились эталоны (`examples/`) или ресурсы навыков (`resources/`) — запустите установку повторно, иначе установленная копия останется на прежней версии и команды продолжат работать по старым правилам.

### Что произойдёт

Скрипт спросит, какой IDE‑агент вы используете:

| | 1. Claude Code | 2. Antigravity | 3. Codex | 4. OpenCode | 5. Cline | 6. DevX (МТС) | 7. Universal | 8. Cursor | 9. Windsurf | 10. Roo Code | 11. Continue | 12. GitHub Copilot | 13. Aider |
|:---|:---|:---|:---|:---|:---|:---|:---|:---|:---|:---|:---|:---|:---|
| **Корень** | `.claude/` | `.agent/` | `.agents/` | `.opencode/` | `.cline/` | `.clinerules/` | `.agents/` | `.cursor/` | `.windsurf/` | `.roo/` | `.continue/` | `.github/` | `.aider/` |
| **Команды** | `commands/` | `workflows/` | `prompts/` | `commands/` | `workflows/` | `workflows/` | `commands/` | `rules/` | `rules/` | `workflows/` | `prompts/` | `prompts/` | `prompts/` |
| **Навыки** | `skills/` | `skills/` | `skills/` | `skills/` | `skills/` | `skills/` | `skills/` | `skills/` | `skills/` | `skills/` | `skills/` | `skills/` | `skills/` |



> Существующие файлы не удаляются — обновляются только управляемые подпапки.

---

### 🔧 Продвинутая настройка (Алиас `init_sa`)

#### macOS / Linux

1. Определите шелл: `echo $SHELL`
   - `/bin/zsh` → `~/.zshrc`
   - `/bin/bash` → `~/.bashrc`
2. Запишите алиас:

```bash
echo "alias init_sa='curl -sSL https://raw.githubusercontent.com/boboden541/sa-helper/main/install.sh -o /tmp/sa-install.sh && bash /tmp/sa-install.sh && rm -f /tmp/sa-install.sh'" >> ~/.zshrc
```

1. Примените: `source ~/.zshrc`
2. Проверьте: введите `init_sa` в любой папке проекта.

<details>
<summary>Обновление старого алиаса</summary>

```bash
# zsh
sed -i '' '/alias init_sa/d' ~/.zshrc
echo "alias init_sa='curl -sSL https://raw.githubusercontent.com/boboden541/sa-helper/main/install.sh -o /tmp/sa-install.sh && bash /tmp/sa-install.sh && rm -f /tmp/sa-install.sh'" >> ~/.zshrc

# bash — замените sed -i '' на sed -i
sed -i '/alias init_sa/d' ~/.bashrc
echo "alias init_sa='curl -sSL https://raw.githubusercontent.com/boboden541/sa-helper/main/install.sh -o /tmp/sa-install.sh && bash /tmp/sa-install.sh && rm -f /tmp/sa-install.sh'" >> ~/.bashrc
```

</details>

#### Windows

> Требуется Git Bash (ставится вместе с Git for Windows).

Откройте профиль PowerShell:

```powershell
notepad $PROFILE
```

Добавьте функцию:

```powershell
function init_sa {
    $tempDir = Join-Path $env:TEMP "sa-helper-$(Get-Random)"
    git clone --depth 1 https://github.com/boboden541/sa-helper.git $tempDir
    bash "$tempDir\install.sh"
    Remove-Item -Recurse -Force $tempDir -ErrorAction SilentlyContinue
}
```

> **После установки перезагрузите IDE** (Reload Window), чтобы команды появились в чате.

---

## 🔄 Обновление

Запустите команду установки повторно — скрипт обновит только управляемые файлы.

| Платформа | Действие |
|-----------|----------|
| **macOS / Linux** | `init_sa` или curl‑команда из быстрого старта |
| **Windows** | `init_sa` или git‑clone‑команда из быстрого старта |

---

## 📊 Процессы и диаграммы

### Процесс 1: Реверс‑инжиниринг и документация

```mermaid
flowchart TD
    A["/context-gen"] -->|"repomix-output.xml · naming_conventions.md · tasks.md"| B{Что нужно?}
    B -->|"Архитектура"| C["/arch-gen"]
    B -->|"DataFlow"| D["/data-trace"]
    B -->|"API / Документ"| E["/create-doc"]
    B -->|"OpenAPI 3.0"| OA["/open-api"]

    C -->|"C4 L3 диаграмма"| F["/validate-doc"]
    D -->|"DataFlow диаграмма"| F
    E -->|"Спецификация / артефакт"| F
    OA -->|"OpenAPI yaml"| F

    F -->|"Аудит пройден"| G(("Done"))
    F -->|"Ошибки найдены"| E

    style A fill:#4a9eff,color:#fff
    style F fill:#ff6b6b,color:#fff
    style G fill:#51cf66,color:#fff
```

### Процесс 2: Системные требования (FNR Pipeline)

У процесса **два входа**:

- **Задача понятна** → постановка через анализ проблемы: `/fnr-new-task` формирует `task.md`.
- **Задача от руководства размыта, требований нет** → discovery‑этапы (`/discovery` → цикл вопросов‑ответов `/discovery-answer` / `/discovery-brief`), которые закрывают развилки и готовят тот же `task.md` (детали — Процесс 4).

Дальше пути сходятся: `/fnr-concept` → `/fnr-debate` → `/fnr-system-requirements` → `/validate-doc`.

```mermaid
flowchart TD
    A["/context-gen"] -->|"Контекст проекта"| B["/fnr-new-task"]
    T["Размытая задача от руководства<br/>(требований нет)"] --> D["/discovery"]
    D -->|"Досье: развилки Decision Backlog · брифинг"| Q["Цикл «вопрос → ответ»<br/>/discovery-answer · /discovery-brief"]
    Q -->|"Все блокеры 🟢"| T2["task.md — готов к постановке"]
    B -->|"task.md"| T2

    T2 --> C["/fnr-concept"]
    C -->|"concept.md · 3–5 концептов"| DD["/fnr-debate"]
    DD -->|"Вердикт в concept.md"| E{Вердикт?}

    E -->|"Принят"| F["/fnr-system-requirements"]
    E -->|"Забраковано"| C

    F -->|"BR / FR / NFR + Jira"| G["/validate-doc"]
    G -->|"Аудит пройден"| H(("Done"))
    G -->|"Ошибки найдены"| F

    style A fill:#4a9eff,color:#fff
    style T fill:#4a9eff,color:#fff
    style D fill:#16a085,color:#fff
    style Q fill:#ffd43b,color:#000
    style B fill:#ffd43b,color:#000
    style T2 fill:#1abc9c,color:#fff
    style C fill:#ffd43b,color:#000
    style DD fill:#ffd43b,color:#000
    style F fill:#ffd43b,color:#000
    style G fill:#ff6b6b,color:#fff
    style H fill:#51cf66,color:#fff
```

### Процесс 3: Анализ требований (PRD Grooming & BFT)

```mermaid
flowchart TD
    PRD["PRD документ / ТЗ"] --> B["/prd-grooming"]
    B -->|"Отчёт о находках и дефектах"| C["/bft-build"]
    C -->|"БФТ спецификация (bft_name.md)"| D["/fnr-new-task"]

    style PRD fill:#4a9eff,color:#fff
    style B fill:#9c36b5,color:#fff
    style C fill:#2b8a3e,color:#fff
    style D fill:#ffd43b,color:#000
```

### Процесс 4: Discovery (формирование требований)

Когда задача от руководства размыта и требований нет: `/discovery` собирает контекст, находит развилки (Decision Backlog), формирует брифинг для согласования и action points. По мере ответов руководства досье обновляется, пока не будет готово к постановке (`/fnr-concept`).

```mermaid
flowchart TD
    T["Размытая задача от руководства"] --> D["/discovery"]
    D -->|"00_context · 01_decision_backlog · 03_brief · 04_action_points · task.md"| Q{Развилки открыты?}

    Q -->|"Ответ руководства"| A["/discovery-answer D-N «ответ»"]
    A -->|"02_answers · статусы D-N → 🟢"| Q
    Q -->|"Свежий брифинг"| B["/discovery-brief"]
    B -->|"03_brief.md пересобран"| Q
    Q -->|"Все блокеры 🟢 — готов к постановке"| C["/fnr-concept task.md"]

    style D fill:#16a085,color:#fff
    style A fill:#ffd43b,color:#000
    style B fill:#ffd43b,color:#000
    style C fill:#1abc9c,color:#fff
```

---

## 🛠 Доступные команды (16 команд)

### Реверс‑инжиниринг

| Команда | Описание | Результат |
|:--------|:---------|:----------|
| `/context-gen` | Подготовка контекста workspace: сканирует все склонированные репозитории и показывает план сервисов на утверждение | `sa_documentation/<сервис>-docs/` по каждому сервису (`repomix-output.xml`, `naming_conventions.md`) + единый корневой `tasks.md` |
| `/arch-gen` | Формирование архитектуры | C4 Level 3 диаграмма (PlantUML) в `<сервис>-docs/architecture/` |
| `/data-trace` | Формирование DataFlow | Диаграмма по сущности или атрибуту в `<сервис>-docs/data_trace/` |
| `/create-doc` | Генерация документа | Документ одного типа (API / интеграция / экран / ERD / процесс / DataTrace) в `<сервис>-docs/<категория>/` |
| `/open-api` | Генерация OpenAPI-спеки | `sa_documentation/<сервис>-docs/api/openapi/<domain>.yaml` (Swagger, OpenAPI 3.0.3) |
| `/validate-doc` | Тотальная проверка | Аудит на соответствие коду и стандартам (7 реверс-типов + системные требования) |
| `/prd-grooming` | Груминг PRD (понятность / валидность / реализуемость / противоречия) | `sa_documentation/prd/{file_name}.md` |
| `/bft-build` | Построение БФТ по входящему контексту (PRD / текст / отчёт груминга) | `sa_documentation/bft/{bft_name}.md` |
| `/project-map` | Сканирование и построение графа Neo4j | Графовая карта классов, функций, SQL и REST-вызовов |

### Системные требования (FNR Pipeline)

| Команда | Роль | Описание | Результат |
|:--------|:-----|:---------|:----------|
| `/fnr-new-task` | Problem Analyst | Анализ проблемы, поиск корня в коде | `FNR/FNR_N/task.md` |
| `/fnr-concept` | Solution Designer | Спектр решений: от чистой архитектуры до костыля | `FNR/FNR_N/concept.md` |
| `/fnr-debate` | Architectural Debate | Архитектор vs Адвокат Дьявола — 3 раунда | Вердикт дописан в `concept.md` |
| `/fnr-system-requirements` | System Requirements Analyst | BR / FR / NFR + Jira‑декомпозиция; двухслойное описание | `FNR/FNR_N/system_requirements.md` |

### Discovery (формирование требований)

| Команда | Роль | Описание | Результат |
|:--------|:-----|:---------|:----------|
| `/discovery` | Discovery Analyst | Из размытой задачи — контекст, развилки (Decision Backlog), брифинг для руководства, action points | Досье `FNR/FNR_N/`: `00_context`, `01_decision_backlog`, `03_brief`, `04_action_points`, `02_answers`, `task.md` |
| `/discovery-answer` | Discovery Analyst | Зафиксировать ответ руководства по развилке, пересчитать досье | Обновлённые `02_answers`, `01_decision_backlog`, `task.md` |
| `/discovery-brief` | Discovery Analyst | Пересобрать 1‑страничный брифинг из текущего бэклога | Обновлённый `03_brief.md` |


---

## 🧠 Стандарт Doc-Architect v3.0

Все генерируемые документы следуют четырём правилам:

| # | Правило | Суть |
|:--|:--------|:-----|
| 1 | **Origin Lineage** | Каждое поле таблицы имеет источник: `DB: Table.Column` / `API: Service.Method` / `Computed [Layer]: Logic` |
| 2 | **Technical Endpoints** | Вместо SEO‑алиасов — технические контракты: `METHOD /controller/action/{id}` |
| 3 | **UML Diagrams** | Обязательные Sequence и Activity диаграммы в PlantUML |
| 4 | **Deep Inspection** | Анализ не только контроллера, но и сервисов, DAO, внешних интеграций |

---

## 📂 Структура системы

<details>
<summary><strong>Claude Code</strong> — <code>.claude/</code></summary>

```
.claude/
├── commands/    ← команды (/context-gen, /fnr-new-task и др.)
└── skills/      ← навыки (роли агента)
```

</details>

<details>
<summary><strong>Antigravity</strong> — <code>.agent/</code></summary>

```
.agent/
├── workflows/   ← команды
└── skills/      ← навыки
```

</details>

<details>
<summary><strong>Codex</strong> — <code>.agents/</code></summary>

```
.agents/
├── prompts/     ← команды через /prompts:...
└── skills/      ← навыки (repo-level)
```

</details>

<details>
<summary><strong>OpenCode</strong> — <code>.opencode/</code></summary>

```
.opencode/
├── commands/    ← команды
└── skills/      ← навыки
```

</details>

<details>
<summary><strong>Universal</strong> — <code>.agents/</code></summary>

```
.agents/
├── commands/    ← команды
└── skills/      ← навыки
```

</details>

### Навыки

Каждый навык содержит **SKILL.md** (ролевая модель), **resources/** (чек‑листы, стандарты), **examples/** (шаблоны).

| Навык | Назначение |
|:------|:-----------|
| `architecture/` | Реверс‑инжиниринг архитектуры |
| `db_archeologist/` | Анализ базы данных |
| `technical-documentation/` | Генерация документации |
| `problem-analyst/` | Диагностика проблем, постановка задачи |
| `solution-designer/` | Генерация спектра решений |
| `architectural-debate/` | Дебаты: Архитектор vs Адвокат Дьявола |
| `system-analyst-sysreq/` | Формирование системных требований |
| `prd-groomer/` | Груминг PRD: диагностика требований и отчёт о находках |
| `bft-builder/` | Построение БФТ: генерация бизнес-функциональных требований из входящего контекста |
| `discovery-analyst/` | Discovery: превращение размытой задачи в требования‑развилки и брифинг для руководства |
| `doc-type-router/` | Маршрутизатор типов документации: редактируемая карта «тип ↔ папка ↔ признаки» |

---

## 🗂 Структура sa_documentation

Документация реверс‑инжиниринга раскладывается **по сервисам** (один анализируемый репозиторий = один сервис), внутри сервиса — **по назначению**:

```text
sa_documentation/
├── tasks.md                        # ЕДИНЫЙ план задач на весь workspace (корень)
├── <сервис>-docs/                  # один репозиторий = один сервис (имя из папки репо, kebab-case)
│   ├── repomix-output.xml          # контекст-снапшот этого репозитория
│   ├── naming_conventions.md       # словарь «код ↔ бизнес» этого репозитория
│   ├── api/                        # api_<нормализованный_роут>.md (+ openapi/<domain>.yaml)
│   ├── integrations/               # integration_<партнёр>_<назначение>.md
│   ├── screens/                    # screen_<название_экрана>.md
│   ├── architecture/               # architecture_<название>.md (+ .puml)
│   ├── erd/                        # erd_<домен|схема>.md
│   ├── data_trace/                 # data_trace_<название>.md
│   └── processes/                  # process_<название>.md
├── FNR/                            # кросс-сервисный задачный уровень (корень, не трогаем)
├── prd/  bft/                      # кросс-сервисный задачный уровень (корень, не трогаем)
```

**Правила:**

- **Владелец документа — сервис, о котором документ.** API сервиса Y → `y-docs/api/`; ERD репозитория БД → `data-base-docs/erd/`; интеграция X→Y → `x-docs/integrations/` (владелец — инициатор/клиент).
- Категории создаются по мере появления документов, пустые папки не создаются.
- Отдельный репозиторий БД — такой же «сервис» (`data-base-docs/`), его документы живут в `erd/` (и опционально `data_trace/`).
- **Карта типов документации** (тип ↔ папка ↔ признаки ↔ команда) — редактируемая таблица в `skills/doc-type-router/resources/type_map.md`. Хотите добавить свой тип или изменить признаки — правьте этот файл: команды сверяются с ним, а не с локальными копиями.

> **Legacy.** Документы, созданные до переезда и лежащие в плоских путях (`sa_documentation/api/…`, `sa_documentation/screens/…`), остаются рабочими: `/validate-doc` распознаёт тип по категории пути. Автоматической миграции нет — при желании перенесите файлы в `<сервис>-docs/` вручную.

---

# Применение на практике

> **Несколько репозиториев (workspace).** Откройте агента в корневой папке, где склонированы все нужные репозитории: `/context-gen` сам найдёт их, покажет план сервисов (`sa_documentation/<сервис>-docs/` по каждому) на утверждение и сложит задачи всех сервисов в один корневой `tasks.md`. Дальше команды определяют сервис по задаче из `tasks.md`.

### Я хочу описать архитектуру проекта

```text
1.  /context-gen Я, как системный аналитик, должен провести revese-engineering текущего проекта. Мне нужно полностью задокументировать проект:
- Составить C4-диаграмму (до уровня C3), описать основные компоненты сервиса, описать базу данных, 
- Описать имеющиеся API-интерфейсы, которые предоставляет сервис, (один API = одна задача = один документ)
- Описать интеграционные взаимодействия данного сервиса с другими сервисами (одна интеграция = одна задача = один документ). 
- Описать способы взаимодействия данного проекта с базой данных (если есть)

2. На выходе ты получишь файл tasks.md
3. Найди там задачу на описание архитектуры
4. Переходим к генерации:
  4.1 /create-doc {весь текст задачи} -> Markdown-файл с текстовым описанием архитектуры
  4.1 /arch-gen {Весь текст этой же задачи} -> С4-диаграмма в нотации UML
```

### Я хочу описать API

```text
1.  /context-gen Я, как системный аналитик, должен провести revese-engineering текущего проекта. Мне нужно полностью задокументировать проект:
- Составить C4-диаграмму (до уровня C3), описать основные компоненты сервиса, описать базу данных, 
- Описать имеющиеся API-интерфейсы, которые предоставляет сервис, (один API = одна задача = один документ)
- Описать интеграционные взаимодействия данного сервиса с другими сервисами (одна интеграция = одна задача = один документ). 
- Описать способы взаимодействия данного проекта с базой данных (если есть)

2. На выходе ты получишь файл tasks.md
3. Найди в этом файле задачи на описание экранов и API-методов
4. Убедись, что одна задача на описание API содержит в ожидаемом результате один файл описания (один API = один документ). Если это не так:
- Попроси ИИ исправить
- Свяжись с автором sa-helper, буду лечить

5. /create-doc {весь текст задчи}

3.  /validate-doc  {указать путь к новому файлу}
```

### Составить DataFlow объекта

```text
1.  /context-gen  Я, как системный аналитик, должен провести revese-engineering текущего проекта. Мне нужно полностью задокументировать проект:
- Составить C4-диаграмму (до уровня C3), описать основные компоненты сервиса, описать базу данных, 
- Описать имеющиеся API-интерфейсы, которые предоставляет сервис, (один API = одна задача = один документ)
- Описать интеграционные взаимодействия данного сервиса с другими сервисами (одна интеграция = одна задача = один документ). 
- Описать способы взаимодействия данного проекта с базой данных (если есть)

2. На выходе ты получишь файл naming_conventions.md (словарь код ↔ бизнес)

3. Изучи naming_conventions.md и выбери сущность, которую хочешь изучить или отдельный атрибут сущности

4.  /data-trace  {название сущности/объекта или атрибута}
```

### Пройти путь от проблемы до системных требований

> Если задача понятна — начинайте с шага 1. Если постановка размыта и требований нет — начните с Discovery (следующий раздел), а с `/fnr-concept` вернётесь на шаг 3 этого пути.

```text
1. /context-gen  Я, как системный аналитик, должен провести дорабрику текущего проекта. Мне нужен глубокий анализ проекта, доработки могут затронуть любой слой и абстракцию текущего проекта.

2. /fnr-new-task  После cron‑импорта данные, созданные вручную в web_db, пропадают. Нужно понять причину и описать проблему. -> sa_documentation/FNR/FNR_1/task.md

3. /fnr-concept  sa_documentation/FNR/FNR_1/task.md -> concept.md — 3–5 концептов (от чистой архитектуры до костыля)

4. /fnr-debate  sa_documentation/FNR/FNR_1/concept.md -> Вердикт дебатов дописан в concept.md (3 раунда, аргументы подтверждены кодом)

5. /fnr-system-requirements  sa_documentation/FNR/FNR_1/concept.md -> BR/FR/NFR + Jira‑декомпозиция + PlantUML (As‑Is / To‑Be / Migration).
   Описание каждой доработки двухуровневое: «Общее описание доработки» (обзорный уровень) + «Описание доработок» (системно‑аналитический уровень)

6. /validate-doc  sa_documentation/FNR/FNR_1/system_requirements.md
```

### Discovery: из размытой задачи в требования

```text
1. /discovery  Заказчик хочет перевести сервис X на загрузку данных в Y вместо старой базы. Требований пока нет.
   → досье FNR/FNR_N/: контекст, развилки (Decision Backlog), брифинг для руководства, action points, task.md
2. Покажи 03_brief.md руководству, собери ответы по открытым развилкам.
3. /discovery-answer D-2 "Временно пишем в обе базы 2 спринта"  → статус D-2 → 🟢, пересчёт зависимостей
4. /discovery-brief  → свежий брифинг из текущего состояния бэклога
5. Когда все блокеры 🟢:  /fnr-concept sa_documentation/FNR/FNR_N/task.md
```

> Дальше — общий путь Процесса 2: `/fnr-debate` → `/fnr-system-requirements` → `/validate-doc`.
>
> Discovery **не пишет** в `tasks.md` — он формирует `04_action_points.md`, из которого аналитик сам переносит нужное в мастер‑план.

---

# Дополнительный раздел

## 🌳 Граф проекта (Neo4j)

SA-Helper строит **граф кодовой базы** в Neo4j — карту всех классов, функций, вызовов, SQL‑запросов и DB‑объектов. Агент получает точную структуру проекта вместо угадывания по тексту файлов.

**Что даёт:**

- **Цепочки вызовов** — кто кого вызывает, на какую таблицу ссылается
- **Impact‑анализ** — что сломается при изменении функции или таблицы
- **DB‑анализ** — lineage таблиц, хранимых процедур, view; поиск orphan‑объектов
- **Архитектурный обзор** — контроллеры → сервисы → DAO → таблицы

### Настройка

> **Предварительные требования:** Docker Desktop, Python 3.9+.

#### Шаг 1: Установите SA-Helper в проект

Если ещё не установили — выполните команду из [быстрого старта](#-быстрый-старт-установка). В корне проекта появятся `indexer/` и `docker-compose.yml`.

**Временный скрипт установки для graph-tree ветки:**

<details>
<summary><strong>macOS / Linux</strong></summary>

```bash
git clone --branch graph-tree --depth 1 https://github.com/boboden541/sa-helper.git /tmp/sa-gt && \
cp -R /tmp/sa-gt/indexer . && \
mkdir -p .claude/commands .claude/skills && \
cp -R /tmp/sa-gt/.claude/commands/. .claude/commands/ && \
cp -R /tmp/sa-gt/.claude/skills/. .claude/skills/ && \
rm -rf /tmp/sa-gt
```

</details>

<details>
<summary><strong>Windows (PowerShell)</strong></summary>

```powershell
git clone --branch graph-tree --depth 1 https://github.com/boboden541/sa-helper.git $env:TEMP\sa-gt
Copy-Item -Recurse $env:TEMP\sa-gt\indexer .
New-Item -ItemType Directory -Force -Path .claude\commands, .claude\skills
Copy-Item -Recurse $env:TEMP\sa-gt\.claude\commands\* .claude\commands\
Copy-Item -Recurse $env:TEMP\sa-gt\.claude\skills\* .claude\skills\
Remove-Item -Recurse -Force $env:TEMP\sa-gt
```

</details>

Индексатор построения архитектурной карты проекта по умолчанию работает на быстром встроенном движке **Tree-sitter** (парсинг AST, поддерживает Python, JS/TS, Java, PHP, Go). Для более глубокого извлечения (фреймворк-эндпоинты, декларативные YAML-правила, C#) можно дополнительно установить Semgrep и запустить индексатор с флагом `--semgrep` (см. `indexer/semgrep_rules/`).

#### Шаг 2: Создайте окружение и установите зависимости

<details>
<summary><strong>macOS / Linux</strong></summary>

```bash
python3 -m venv .venv && .venv/bin/pip install -r indexer/requirements.txt
```

</details>

<details>
<summary><strong>Windows (PowerShell)</strong></summary>

```powershell
python -m venv .venv
.venv\Scripts\pip install -r indexer\requirements.txt
```

</details>

#### Шаг 3: Запустите базу и проиндексируйте проект


```bash
# Запустите Neo4j
docker compose -f indexer/docker-compose.yml up -d
```

```bash
# Проверить, что база работает
curl -s http://localhost:7474 > /dev/null && echo "OK — Neo4j работает" || echo "WAIT — подождите ещё немного"
```

**Индексация проекта:**

<details>
<summary><strong>macOS / Linux</strong></summary>

```bash
.venv/bin/python indexer/main.py .
```

</details>

<details>
<summary><strong>Windows (PowerShell)</strong></summary>

```powershell
.venv\Scripts\python indexer\main.py .
```

</details>

**Для проектов с DDL‑репозиториями (SQL Server, PostgreSQL):**

<details>
<summary><strong>macOS / Linux</strong></summary>

```bash
.venv/bin/python indexer/main.py . --db-schema /path/to/db_repo --default-schema dbo
```

</details>

<details>
<summary><strong>Windows (PowerShell)</strong></summary>

```powershell
.venv\Scripts\python indexer\main.py . --db-schema C:\path\to\db_repo --default-schema dbo
```

</details>

| Флаг | Описание |
|:-----|:---------|
| `--db-schema` | Путь к папке с `.sql` файлами (можно указать несколько раз) |
| `--default-schema` | Схема по умолчанию: `dbo` (MS SQL), `public` (PostgreSQL). Если не указан — определяется автоматически из DDL |

#### Шаг 4: Подключите MCP‑сервер

MCP — основной способ работы с графом. Без него агент не сможет использовать графовые данные.

<details>
<summary><strong>macOS / Linux</strong></summary>

```bash
claude mcp add sa-helper-graph -- $(pwd)/.venv/bin/python indexer/server/mcp_server.py
```

</details>

<details>
<summary><strong>Windows (PowerShell)</strong></summary>

```powershell
claude mcp add sa-helper-graph -- "$PWD\.venv\Scripts\python" indexer\server\mcp_server.py
```

</details>

После регистрации агент автоматически получит доступ к **13 графовым инструментам**:

| Инструмент | Что делает |
|:-----------|:-----------|
| `graph_schema` | Обзор структуры: классы, функции, таблицы, эндпоинты |
| `graph_call_chain` | Цепочка вызовов от функции (на N уровней вглубь) |
| `graph_impact` | Кто зависит от сущности (класс, функция, таблица) |
| `graph_arch_summary` | Архитектурный обзор: контроллеры → сервисы → DAO → таблицы |
| `graph_select_files` | Выбор файлов по описанию задачи |
| `graph_export` | Экспорт подграфа (`text` / `json` / `mermaid`) |
| `graph_query` | Произвольный read‑only Cypher запрос |
| `graph_stats` | Статистика: количество узлов и связей по типам |
| `graph_db_schema` | Все DB‑объекты: таблицы, view, хранимые процедуры, функции |
| `graph_db_lineage` | Lineage DB‑объекта: зависимости вверх и вниз |
| `graph_db_orphans` | DB‑объекты без связей к коду |
| `graph_db_unresolved` | Ссылки в коде без DDL‑определений |
| `graph_db_impact` | Транзитивный impact при изменении DB‑объекта |

### Как команды используют граф

Все команды SA-Helper автоматически используют граф, когда MCP подключён:

| Команда | Что получает из графа |
|:--------|:----------------------|
| `/context-gen` | Автофильтрация файлов через `select-files` → repomix упаковывает только нужные |
| `/arch-gen` | Структура классов, эндпоинтов, внешних сервисов |
| `/data-trace` | Точные цепочки вызовов вместо grep‑анализа |
| `/create-doc` | Подграф вокруг сущности — точки входа, связи, зависимости |
| `/validate-doc` | Сверка утверждений с рёбрами графа (`CALLS`, `QUERIES`, `EXTENDS`) |
| `/fnr-*` | Структура проекта и зависимости для диагностики проблем |
| `/discovery-*` | Blast‑radius (`impact`, `db-impact`) и gap‑finder (`call-chain`, `db-lineage`, `db-unresolved`, `db-orphans`) для поиска развилок |

> **Fallback:** если Neo4j не запущен — команды работают через `repomix-output.xml` как раньше.

### Поддерживаемые языки

| Язык | Расширения | Что извлекается |
|:-----|:-----------|:----------------|
| Python | `.py` | Классы, функции, импорты, вызовы, SQL‑таблицы, Flask/FastAPI эндпоинты, requests/httpx |
| PHP | `.php` | Классы, трейты, функции, вызовы, SQL, EXEC/CALL SP, CActiveRecord, Yii‑эндпоинты |
| Java | `.java` | Классы, интерфейсы, методы, вызовы, SQL + JPA `@Table`, Spring, RestTemplate |
| JS / TS | `.js` `.jsx` `.ts` `.tsx` | Классы, функции, import/export, вызовы, SQL, Express, fetch/axios |
| Go | `.go` | Struct, Interface, функции, вызовы, SQL, net/http/Gin эндпоинты |
| SQL DDL | `.sql` | CREATE TABLE, VIEW, PROCEDURE, FUNCTION, зависимости |

### Дополнительные возможности

<details>
<summary><strong>Инкрементальное обновление</strong> (только git‑репозитории)</summary>

Перестраивает только изменённые файлы. Fallback на полную пересборку при >30% изменений.

**macOS / Linux:**

```bash
.venv/bin/python indexer/main.py . --incremental
```

**Windows (PowerShell):**

```powershell
.venv\Scripts\python indexer\main.py . --incremental
```

</details>

<details>
<summary><strong>CLI‑запросы</strong> (альтернатива MCP для не‑Claude агентов)</summary>

**macOS / Linux:**

```bash
.venv/bin/python indexer/server/query.py schema                    # структура проекта
.venv/bin/python indexer/server/query.py call-chain "createAction" # цепочка вызовов
.venv/bin/python indexer/server/query.py impact "orders" --type table  # impact‑анализ
.venv/bin/python indexer/server/query.py db-lineage "show"         # lineage DB‑объекта
.venv/bin/python indexer/server/query.py --help                    # все команды
```

**Windows (PowerShell):**

```powershell
.venv\Scripts\python indexer\server\query.py schema                     # структура проекта
.venv\Scripts\python indexer\server\query.py call-chain "createAction"  # цепочка вызовов
.venv\Scripts\python indexer\server\query.py impact "orders" --type table # impact‑анализ
.venv\Scripts\python indexer\server\query.py db-lineage "show"          # lineage DB‑объекта
.venv\Scripts\python indexer\server\query.py --help                     # все команды
```

> Старые пути (`python indexer/query.py`, `python indexer/mcp_server.py`) тоже работают через stub‑файлы.

</details>

**Визуализация в браузере:** [http://localhost:7474](http://localhost:7474) — логин: `neo4j` / `sahelper2026`.

---
