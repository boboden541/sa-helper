---
description: AI Harness — план реализации: досье, DAG задач, Story в БД и шлюз утверждения человеком
---
**ХРАНИЛИЩЕ (важно):** состояние Story/задач — в БД витрины (~/.sa-helper/harness.db).
Доступ ТОЛЬКО через адаптер: `python3 harness/sahelper.py <команда>` (JSON на stdout;
exit 3 — конфликт версии карточки). Файлы `harness/` (manifest.json, tasks/, comments/,
.flags/) НЕ читать и НЕ создавать. Allowlist: `Bash(python3 harness/sahelper.py:*)`.
---

## Использование

```
/impl-plan <путь к system_requirements> [workspaces.yaml]
```

**Параметры:**

- `<путь к system_requirements>` — файл СТ (например, `sa_documentation/FNR/FNR_1/system_requirements.md`).
- `[workspaces.yaml]` — путь к реестру систем; по умолчанию ищется вверх от текущего каталога и в корне воркспейса.

## Примеры

```
/impl-plan sa_documentation/FNR/FNR_1/system_requirements.md
```

```
/impl-plan ../other-workspace/sa_documentation/FNR/FNR_3/system_requirements_concept_b.md
```

## Важно

**Приоритет:** СТРОГОЕ соблюдение шлюза пробелов (`resources/legacy_fr_mapping.md`): при
недостаточном входе — gap-report и STOP; артефакты плана не создаются. План строится только
из СТ и кода — никаких выдуманных требований.

**Ожидаемый результат:** в каталоге СТ создаётся `harness/` — `dossier.md`, `execution_plan.md`,
`tasks/T*.md`, `manifest.json` (проверен `harness/manifest_check.py`), план ждёт утверждения
человека (`.flags/APPROVE_PLAN`).

**Универсальность:** команда не привязана к стеку, БД или домену. Системы и команды — из
`workspaces.yaml`; знания о подъёме — из `build_info/<система>.md` (если есть); пресеты —
`harness/presets/`. Инструмент `python3` (Windows Git Bash: `python`).

---

## Инструкция для LLM

Ты — инженер контура реализации (роль: `.claude/skills/impl-harness/SKILL.md`). Задача шага —
превратить утверждённые системные требования в исполнимый план и получить его у человека.

### Графовый контекст (complement-модель)

Граф дополняет repomix и живой код, а не заменяет их. Если MCP-инструменты `sa-helper-graph`
доступны — используй `graph_introspect`, `graph_schema`, `graph_select_files`, `graph_impact`
для структурного среза и impact-анализа. Недоступны — пропусти и работай через
`sa_documentation/<сервис>-docs/repomix-output.xml` и ripgrep по коду.

### Этап 1: Входной контракт СТ (шлюз пробелов)

1. Прочитай СТ целиком. Прогони по шлюзу из `resources/legacy_fr_mapping.md`:
   - задачи распознаваемы (`#### <номер> <название>` или эквивалент принятого канона);
   - у каждой задачи есть «Критерии приёмки» с проверяемыми условиями;
   - мульти-системность (2+ систем) покрыта разделом о затронутых системах/контрактах.
2. Есть пробелы → **gap-report**: таблица «пробел → раздел СТ → что дописать», STOP.
   Никаких `dossier.md`/`tasks/`/`manifest.json` создавать нельзя. Предложи человеку исправить
   документ и повторить команду.
3. Задачи без явных FR-ID — примени легаси-маппинг (там же) и зафиксируй в ID map досье.

### Этап 2: Реестр систем и готовность

1. Найди `workspaces.yaml`. НЕТ файла → предложи `/impl-bootstrap` (discovery + создание) и STOP.
2. Каждая система из раздела затронутых систем СТ должна быть в реестре с `bootstrap: ready*`.
   Нет системы в реестре или `bootstrap: stop` → STOP с перечнем: «сначала /impl-bootstrap <система>».
3. Для каждой системы прочитай `build_info/<система>.md` (если есть) — учти ловушки при
   планировании гейтов.

### Этап 3: Досье (`harness/dossier.md`)

Собери по шаблону `examples/ideal_dossier.md`:
1. **ID map** (если маппинг применялся) и перечень задач с их системами.
2. **Доменный срез**: по каждой системе 4–7 файлов, непосредственно относящихся к задаче
   (источник: repomix-выгрузка сервиса и/или ripgrep по ключевым сущностям СТ; граф — если
   доступен). Каждый файл — с ролью и «что смотреть».
3. **Golden Reference**: в каждом репо найди завершённый аналог реализуемого (соседний
   эндпоинт/сервис/процедура) и зафиксируй `файл:строка` для: DI, валидации, ошибок, тестов.
4. **Конвенции**: гайдлайны репо (CLAUDE.md/CONTRIBUTING/...), пресет стека; репо без тестов →
   фаза `characterization` первой задачи.
5. **Контракты**: для мульти-системной задачи — что связывает системы, владелец, где фиксируется
   (`resources/contract_first.md`). Интерфейсы не меняются → «не применимо».

### Этап 3а: Регистрация Story в БД

`python3 harness/sahelper.py story-init --title "<название Story>" --status-planned`
→ получишь FNR (адаптер генерирует номер атомарно). Дальше везде используй его.

### Этап 4: План работ

1. Разложи задачи СТ на атомарные T<номер> (одна карточка = одна система).
2. Фазы по `resources/contract_first.md`: контрактная задача — первой (никакой бизнес-логики,
   только спецификация взаимодействия); characterization — первой в репо без тестов;
   producers/consumers — после контракта.
3. Создай досье и план: `sahelper doc-set FNR --kind dossier --file <файл>` и
   `sahelper doc-set FNR --kind execution_plan --file <файл>` (по шаблонам
   `examples/ideal_dossier.md`; DAG — PlantUML в execution_plan).
4. Создай задачи: `sahelper task-create FNR '<json>'` — spec:
   `{"title", "system", "phase", "branch": "harness/FNR-<N>-<slug>-t<k>", "depends_on": [],
   "fr_ids": [], "acceptance_criteria": [{"id": "AC-...", "desc": "...", "test": "имя теста"}],
   "description": "<полная постановка: контекст → что сделать → критерии>"}`. Ответ даст id (T1, T2…).
5. Карточка каждой задачи: подготовь markdown по `examples/ideal_task_card.md` (пересказ
   требований, AC, Golden Reference из досье, границы) и сохрани:
   `sahelper card-set FNR <T<k>> --file <файл>` (конфликт версии — exit 3: перечитай
   `sahelper card FNR <T<k>>` и повтори).
6. **Комментарии задач**: `sahelper comment-add FNR <T<k>> --author agent --text
   "План принят; задача <k> (<фаза>): <суть>"`. `description` — полная постановка
   (задаётся полем `description` в task-create): человек должен понять работу по одному
   описанию (канон comment-writing применим и здесь).

### Этап 5: Валидация

`sahelper validate FNR` — `{"valid": true}` или исправь по errors (DAG, системы, канон).

### Этап 6: Шлюз утверждения

1. Покажи человеку сводку: задачи (id, система, фаза, AC), DAG, объём. Кратко, без стен текста.
2. Переведи Story на шлюз: `sahelper story-status FNR AWAITING_APPROVAL`.
   Скажите человеку: «План ждёт утверждения — кнопка «✓ План» в витрине (или команда
   `sahelper flag FNR APPROVE_PLAN`). Для правок напишите замечания, я перегенерирую план».
3. Проверять команду в цикле НЕ нужно: следующая команда (`/impl-run`) сама проверит её.

Завершение: выведи FNR и литеральную подсказку:
«План FNR_<N> готов и ждёт утверждения. Следующий шаг: /impl-run <путь к harness> (после
утверждения плана в витрине)».
