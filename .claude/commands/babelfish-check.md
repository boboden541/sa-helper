---
description: Разработка совместимых SELECT: Compass, rewrite, MSSQL-primary/Babelfish-shadow и parity-тесты; записи только документируются
---

## Использование

```text
/babelfish-check <SQL | путь | diff | метод | endpoint> [целевая версия Babelfish]
```

## Примеры

```text
/babelfish-check src/Repository.php Babelfish 5.4
```

```text
/babelfish-check проверить SQL из текущего git diff и подготовить shadow-read
```

```text
/babelfish-check GET /api/items/details — MSSQL должен остаться primary, Babelfish выполнить запросы в shadow
```

## Режимы

- **DEVELOPMENT** — основной режим для задачи на код: инвентаризация, Compass, переписывание несовместимых read-only `SELECT`, shadow-интеграция, автоматические тесты и отчёт; side-effecting SQL остаётся без изменений.
- **REVIEW** — только когда пользователь явно просит анализ без реализации: код приложения не меняется, создаётся отчёт с предложенным diff.

Даже в DEVELOPMENT изменение production routing, схемы/данных и установка инфраструктуры требуют отдельной авторизации, если они не входят явно в задачу.

## Ожидаемый результат

Изменённые совместимые read-only `SELECT`, централизованный shadow-контур, автоматические parity-тесты и отчёт `sa_documentation/babelfish/<scope>-compatibility.md`. Side-effecting SQL представлен в отчёте без изменения кода и Babelfish runtime.

MSSQL всегда остаётся источником пользовательского результата. Babelfish выполняется только как изолированный shadow; его ошибка или расхождение попадает в отчёт/телеметрию, но не влияет на primary response.

---

## Инструкция для LLM

### Этап 1. Контекст и границы

1. Найди и прочитай применимые `AGENTS.md` и миграционные документы проекта.
2. Загрузи `.../skills/babelfish-compatibility/SKILL.md`.
3. Определи scope и полный call path. Если вход — diff, анализируй изменённый SQL и затронутые вызываемые DB-объекты.
4. Зафиксируй точную целевую версию Babelfish. Если её нельзя установить из окружения/контекста и пользователь не указал — пометь результат `INCONCLUSIVE`, не подставляй latest.
5. Определи режим DEVELOPMENT для задачи на реализацию или явно запрошенный REVIEW без правок.

### Этап 2. SQL inventory

1. Используй живой код и `repomix-output.xml`; при доступном MCP-графе дополни поиск связями `QUERIES`, `CALLS_SP`, `INSERTS_INTO`, `UPDATES`, `DELETES_FROM`.
2. Найди все точки DB-доступа, включая legacy DAO/Manage, repositories, dynamic SQL и условные ветки.
3. Присвой batches идентификаторы Q-001…Q-N и собери воспроизводимый Compass input.
4. Раздели SQL на `READ_ONLY` и `SIDE_EFFECTING`. Смешанный или неясный batch считать `SIDE_EFFECTING`.
5. `SIDE_EFFECTING` (`INSERT/UPDATE/DELETE/MERGE`, DDL, пишущие процедуры) не переписывать и не выполнять на Babelfish: только Compass и подробное описание в отчёте.

### Этап 3. Compass

1. Прочитай `.../skills/babelfish-compatibility/resources/compass_workflow.md`.
2. Найди локальный официальный `BabelfishCompass.sh`/`.bat`, выполни `-help` и проверь поддержку целевой версии.
3. Запусти Compass на подготовленном SQL. Не используй `-replace` для неизвестного существующего отчёта.
4. Разбери findings по query ID. Только для несовместимого `READ_ONLY` внеси минимальную правку с сохранением MSSQL-семантики; предпочитай один общий запрос.
5. Если общий SQL невозможен, изолируй пару primary/shadow variants в dialect/query adapter и закрепи эквивалентность contract test.
6. После исправлений повторно извлеки SQL из фактического кода и перезапусти Compass.
7. Если Compass отсутствует или не поддерживает target — не выдумывай результат; отрази блокер и продолжи только разрешённые доступные проверки.

### Этап 4. Runtime и shadow

1. Прочитай `.../skills/babelfish-compatibility/resources/shadow_execution.md`.
2. Для доступной тестовой среды выполни только `READ_ONLY`: MSSQL baseline и Babelfish shadow на одинаковых typed parameters и репрезентативных данных.
3. Сравни ошибки, схему результата, значения, NULL, Unicode, числа, даты, ordering, row count и latency.
4. Не путай несовместимость с data drift.
5. В режиме DEVELOPMENT найди минимальную централизованную точку query/connection/repository boundary и реализуй:
   - MSSQL primary без изменения существующего результата;
   - Babelfish best-effort shadow только для allowlist/read-only scope;
   - отдельные timeout/pool/concurrency limit;
   - sampling, circuit breaker, feature flag и kill switch;
   - feature flag только для включения дополнительного shadow-вызова, без переключения primary target;
   - безопасную телеметрию и comparison policy;
   - rollback-тест при выключенном shadow.

### Этап 5. Автоматические тесты

1. Прочитай `.../skills/babelfish-compatibility/resources/testing_strategy.md`.
2. Используй существующий test framework проекта и добавь:
   - MSSQL regression test;
   - real-engine MSSQL/Babelfish parity test на одинаковых fixtures;
   - comparator tests для NULL/Unicode/decimal/datetime/ordering;
   - Babelfish error/timeout isolation test;
   - shadow-off/kill-switch test;
   - service/endpoint parity test, если SQL участвует в сборке DTO.
3. Для каждого Compass `Review Semantics` создай targeted case.
4. Mock-only тесты не считать доказательством SQL compatibility.
5. Для `SIDE_EFFECTING` не добавлять исполняемые Babelfish-тесты; записать в отчёт предлагаемый будущий test plan.

### Этап 6. Отчёт и проверка

1. Создай `sa_documentation/babelfish/`, если её нет.
2. Заполни отчёт строго по `.../skills/babelfish-compatibility/examples/ideal_babelfish_compatibility_report.md`.
3. Прогони `.../skills/babelfish-compatibility/resources/validation_checklist.md` и закрой Hard Gates.
4. В DEVELOPMENT-режиме запусти lint, unit, DB integration, parity и smoke checks; покажи изменённые файлы и точный rollback.
5. Заверши одним из вердиктов: `COMPATIBLE`, `COMPATIBLE WITH CHANGES`, `INCOMPATIBLE`, `INCONCLUSIVE`.
