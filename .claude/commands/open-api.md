---
description: Генерация машиночитаемой OpenAPI (Swagger) YAML-спецификации одного API-метода из кода
---

## Использование

```
/open-api <API + METHOD + PATH>
```

**Параметры:**

- `<API + METHOD + PATH>` — имя API/сервиса/домена, HTTP-метод и path эндпоинта.
  Например: `Catalog GET /api/shows/{id}` или `POST /search/autocompleteMore/`.

## Примеры

```
/open-api Catalog GET /api/shows/{id}
```

```
/open-api GET /api/shows/{id}
**Необходимый контекст (Файлы):**
- [ ] `routes/api.php` (Routing)
- [ ] `app/Http/Controllers/ShowController.php` (Contract)
- [ ] `app/DTO/ShowResource.php` (Model)
```

## Важно

**Приоритет:** СТРОГОЕ соблюдение навыка `openapi-spec` (`.claude/skills/openapi-spec/SKILL.md`) и эталона `examples/ideal_openapi_spec.yaml`.

**Ожидаемый результат:** **доменный** файл `sa_documentation/<сервис>-docs/api/openapi/<domain>.yaml` (например `ticketland.yaml`), в который **дописывается** рассматриваемый метод (операция в `paths` + DTO в общий `components/schemas`). Файл — валидная OpenAPI 3.0.3 спецификация, проходящая внешний линтер с 0 ошибок и рендерящаяся в IDE-плагине «OpenAPI (Swagger) Editor».

**Один файл на домен, не на метод.** DTO переиспользуются через общий `components/schemas` — но только если это **тот же класс в коде** (принцип идентичности 5а навыка). Разные классы с одинаковыми полями → разные схемы.

**Целевая версия — OpenAPI 3.0.3.** Плагин «OpenAPI (Swagger) Editor» не поддерживает union-типы 3.1 (`type: [string, "null"]`) — обнуляемость кодируется `nullable: true`. См. `openapi-spec/SKILL.md`, принцип 3.

**Универсальность:** команда не привязана к конкретному стеку, БД или фреймворку.

---

## Инструкция для LLM

### Графовый контекст (complement-модель)

Граф дополняет repomix-output.xml, а не заменяет его. Используй оба источника одновременно:

- **repomix-output.xml** — полный текст кода (DTO, контроллеры, валидаторы, конфиги роутинга)
- **MCP-инструменты** (если sa-helper-graph подключён) — структура и связи

**Графовые запросы для данной команды:**

- `graph_introspect` — реальные метки/свойства/связи графа перед запросами
- `graph_export` — подграф вокруг контроллера/метода (точки входа, связи)
- `graph_call_chain` — цепочка вызовов от обработчика эндпоинта
- `graph_impact` — зависимые компоненты (DTO, сервисы)

Если MCP-инструменты недоступны — пропусти графовые запросы, продолжай с repomix-output.xml / живым кодом.

### Этап 0: Определение сервиса и загрузка роли — ОБЯЗАТЕЛЬНО

1. **Определи сервис:**
   - **П1 (явное):** если в аргументе есть id задачи (`[T<N>]`) — найди её в едином корневом `sa_documentation/tasks.md` и возьми сервис из полей **Сервис** / **Шаблон результата** (`sa_documentation/<сервис>-docs/…`).
   - **П2 (существующие папки):** папки `sa_documentation/*-docs/` — ровно одна: используй её молча; несколько: выбери по имени API/домену из аргумента и анализируемому репозиторию, иначе спроси пользователя.
   - **П3 (вывод):** имя папки анализируемого репозитория → kebab-case (нижний регистр, не-буквоцифры → `-`; суффиксы не отрезать) → подтверди у пользователя одной строкой → при необходимости создай `sa_documentation/<сервис>-docs/`.
2. **Контекст сервиса:** анализируй `sa_documentation/<сервис>-docs/repomix-output.xml` этого сервиса (или живой код репозитория).
3. Загрузи навык `.claude/skills/openapi-spec/SKILL.md` — твоя персона и методология.
4. Открой эталон `.claude/skills/openapi-spec/examples/ideal_openapi_spec.yaml` — образец структуры (структура берётся ИЗ ЭТАЛОНА, не из соседних `.yaml`).
5. Загрузи `.claude/skills/openapi-spec/resources/openapi_field_model.md` — таблицу «код → ключ OpenAPI».
6. Загрузи `.claude/skills/openapi-spec/resources/openapi_validation_checklist.md` — критерии готовности.

### Этап 1: Разбор аргумента

1. Выдели из `<API + METHOD + PATH>`: имя API/сервиса, HTTP-метод, path.
2. Зафиксируй path-параметры (`{id}`) — они станут `parameters` с `in: path`, `required: true`.

### Этап 2: Доменный файл и operationId (детерминированно)

**Файл — на домен**: `sa_documentation/<сервис>-docs/api/openapi/<domain>.yaml` — машиночитаемая часть категории `api` сервиса, определённого на Этапе 0.

1. `<domain>` из хоста API (`servers[0].url`): `ticketland.ru` → `ticketland`. Если домен явно задан в аргументе — слугифицируй (lower-case; не-буквенно-цифровые → `_`).
2. `operationId` (уникален в файле) из метода+path: `GET /api/shows/{id}` → `getApiShowsById`. Ключ в `paths` — сам путь.

Целевой путь: `sa_documentation/<сервис>-docs/api/openapi/<domain>.yaml` (например `sa_documentation/ticketland-docs/api/openapi/ticketland.yaml`).

### Этап 3: Сбор контекста (якоря истины)

Переиспользуй правила добычи из навыка `technical-documentation` (следуй, не копируй). Найди:

- **Anchor 1 (Routing):** конфиг роутинга / аннотация контроллера — маппинг path → метод.
- **Anchor 2 (Contract):** контроллер/интерфейс/прото — сигнатура, входные параметры, тип ответа.
- **Anchor 3 (Model):** DTO/Entity/сериализатор — ПОЛНЫЙ состав полей и их ограничений.

Не приступай к генерации, пока не найдены ≥2 из 3 якорей. Недостающее → `[NEEDS_INVESTIGATION]`.

**Ветка harvest:** если фреймворк сам генерирует OpenAPI (FastAPI `/openapi.json`, Springdoc, NestJS, ASP.NET, drf-spectacular) — извлеки готовую спеку метода, а не синтезируй.

### Этап 4: Reverse-engineering схем и merge в доменный файл

1. Если папки `sa_documentation/<сервис>-docs/api/openapi/` нет — создай. **Загрузи-или-создай** `<domain>.yaml`:
   - нет файла → скелет (`openapi: 3.0.3`, `info`, `servers`, пустые `paths`, `components.schemas`);
   - есть файл → распарси текущие `paths` и `components.schemas` для мёржа.
2. Собери схемы метода:
   a. Вход: path/query/header-параметры, `requestBody` (для методов с телом).
   b. Выход: успешный ответ (`2xx`) + ошибки (`4xx`/`5xx`), явно обрабатываемые в коде.
3. Для каждого поля примени `openapi_field_model.md`: `type`(+`format`), `required`, `nullable: true`, `pattern`, `minLength`/`maxLength`, `minimum`/`maximum`, `enum`, `example` — но ТОЛЬКО то, что подтверждено кодом (принцип 2 навыка).
4. **Добавь операцию** в `paths.<path>.<method>` (если уже есть — обнови и предупреди).
5. **Мёрж DTO по идентичности (принцип 5а навыка):** перед добавлением каждой схемы ищи в `components/schemas` схему с тем же `x-source` (FQCN/файл класса):
   - совпало → переиспользуй (`$ref`), не дублируй;
   - не совпало → новая схема (имя класса; при коллизии разных классов — префикс модуля, напр. `Shows_Building`).
   - Указывай `x-source` у каждой схемы — это ключ идентичности для будущих мёржей.
6. Запиши обновлённый файл целиком. Версия — `openapi: 3.0.3`.

### Этап 5: Объективная валидация и самокоррекция — ОБЯЗАТЕЛЬНО

Прогон внешнего валидатора через Bash (порядок предпочтения):

1. **Основной:**
   ```bash
   npx --yes @redocly/cli@latest lint --extends minimal sa_documentation/<сервис>-docs/api/openapi/<file>.yaml
   ```
   Флаг `--extends minimal` проверяет структурную конформность (как плагин IDE) и не навязывает governance-правила (`security`/`license`), чтобы не выдумывать отсутствующее в коде.
2. **Фолбэк (нет Node/`npx`):**
   ```bash
   python -m openapi_spec_validator sa_documentation/<сервис>-docs/api/openapi/<file>.yaml
   ```
3. **Деградация (нет обоих):** проверка синтаксиса YAML
   ```bash
   python -c "import yaml,sys; yaml.safe_load(open(sys.argv[1])); print('YAML OK')" sa_documentation/<сервис>-docs/api/openapi/<file>.yaml
   ```
   и **явно предупреди** пользователя, что семантическая валидация пропущена (нет валидатора).

**Цикл самокоррекции:** пока валидатор возвращает ошибки — исправляй спеку и перезапускай линтер. Предел — **5 итераций**. По исчерпании файл НЕ удаляй, выдай отчёт с остаточными ошибками.

Сверься с `openapi_validation_checklist.md` (все Hard Gates 🔴 должны быть закрыты), особое внимание:
- каждый `type` — одиночная строка (нет union-типов 3.1);
- нет висячих `$ref`, каждый `array` имеет `items`;
- нет выдуманных ограничений.

### Этап 6: Завершение

**Актуализируй единый корневой `sa_documentation/tasks.md`**: если в аргументе есть id задачи (`[T<N>]`) — у задачи установи/обнови строку `> **Статус:** 🟡 Ожидает валидации` (замени существующую `> **Статус:**…` или добавь под заголовком задачи). Если `tasks.md` нет или id неизвестен — пропусти.

Выведи:
1. Путь к файлу `.yaml`.
2. Итог валидации: имя валидатора, число errors/warnings.
3. Список полей с пометкой `[NEEDS_INVESTIGATION]`, если они есть.
4. Сообщение: "Спецификация готова. Откройте `sa_documentation/<сервис>-docs/api/openapi/<file>.yaml` в плагине «OpenAPI (Swagger) Editor» для рендера."
