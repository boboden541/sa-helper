---
description: Discovery — из размытой задачи сформировать требования (Decision Backlog), брифинг для руководства и action points
---

## Использование

```
/discovery <задача | путь к 03_brief.md | путь к 04_action_points.md>
```

**Параметры:**

- `<задача>` — свободный текст задачи от руководства (режим **NEW**).
- Либо путь к существующему артефакту досье — `03_brief.md` или `04_action_points.md` (режим **CONTINUE**).

## Два режима входа (важно)

| Режим | Вход | Папка `FNR_<N>/` |
|-------|------|------------------|
| **NEW** | свободный текст задачи | **создать новую** (следующий свободный `<N>`) |
| **CONTINUE** | путь к существующему `03_brief.md` или `04_action_points.md` | **НЕ создавать новую** — работать в досье, которому принадлежит файл |

Команда сама определяет режим: аргумент — путь к существующему `03_brief.md`/`04_action_points.md` → CONTINUE; иначе → NEW.

## Примеры

```
/discovery Заказчик хочет перевести сервис building-integrations на загрузку данных в ticketscloud вместо старой базы. Требований пока нет.
```

```
/discovery sa_documentation/FNR/FNR_5/03_brief.md
```

```
/discovery sa_documentation/FNR/FNR_5/04_action_points.md
```

## Важно

**Приоритет:** СТРОГОЕ соблюдение принципов из `discovery-analyst/SKILL.md`, шаблонов из `examples/` и чек-листа `resources/decision_backlog_checklist.md`.

**Ожидаемый результат (NEW):** досье `sa_documentation/FNR/FNR_<N>/` с файлами `00_context.md`, `01_decision_backlog.md`, `03_brief.md`, `04_action_points.md`, пустой `02_answers.md` и `task.md` (постановка + раздел Requirements).

**Ожидаемый результат (CONTINUE):** обновлённое существующее досье (без создания новой папки) — доформирование/финализация `task.md` и связанных артефактов.

**Глубина:** всегда полный набор агентов для CONTEXT (параллельный сбор). Быстрого режима нет.

**Запрещено:** писать или править `sa_documentation/tasks.md`.

**Универсальность:** команда не привязана к стеку, БД или бизнес-домену.

---

## Инструкция для LLM

### Графовый контекст (complement-модель)

Граф дополняет repomix-output.xml, а не заменяет:
- **repomix-output.xml** — полный текст кода.
- **MCP-инструменты** (если sa-helper-graph подключён) — структура и связи.

Запросы для Discovery: `graph_introspect`, `graph_schema`/`graph_arch_summary`, `graph_impact`/`graph_db_impact` (blast-radius), `graph_call_chain`/`graph_db_lineage`/`graph_db_unresolved`/`graph_db_orphans` (gap-finder). Если MCP недоступен — только repomix и живой код.

### Этап 0: Определение режима и досье

1. Разбери аргумент:
   - Если это путь к существующему файлу `03_brief.md` или `04_action_points.md` → **режим CONTINUE**. Досье = родительский каталог файла (`FNR_<N>/`). **Новая папка НЕ создаётся.** Перейди к Этапу 2-CONTINUE.
   - Иначе → **режим NEW**. Определи следующий свободный `<N>` (проверь `sa_documentation/FNR/FNR_*/`; если папок нет — `FNR_1`). Создай `sa_documentation/FNR/FNR_<N>/`.
2. Запомни `<N>` — используется во всех именах артефактов.

### Этап 1: Загрузка роли и контекста проекта

1. Прочитай `discovery-analyst/SKILL.md` — твоя персона, принципы (особенно **два слоя языка**), методология.
2. Загрузи шаблоны из `discovery-analyst/examples/`: `ideal_context.md`, `ideal_decision_backlog.md`, `ideal_brief.md`, `ideal_action_points.md`, `ideal_task_handoff.md`.
3. Прочитай `discovery-analyst/resources/two_layer_language.md`, `mapping_methodology.md` и `question_coverage.md`.
4. Прочитай артефакты `sa_documentation/` (только чтение!): `naming_conventions.md`, существующие документы — не дублировать, использовать терминологию.
5. Проверь `sa_documentation/repomix-output.xml` — если нет, предупреди и работай по живому коду.

### Этап 2-NEW: CONTEXT → MAP → DECIDE → BRIEF (для режима NEW)

**CONTEXT** — собрать «что есть» (полный набор агентов, параллельно). Записать в `00_context.md` (технический слой): As-Is, зоны изменений, разрывы, белые пятна.

**MAP** — по `mapping_methodology.md`: blast-radius (`graph_impact`/`graph_db_impact`) + gap-finder (`graph_call_chain`/`graph_db_lineage`/`graph_db_unresolved`/`graph_db_orphans`). Дополнить «Зоны изменений» и «Разрывы» в `00_context.md`.

**DECIDE** — превратить разрывы в карточки-развилки в `01_decision_backlog.md` по шаблону `ideal_decision_backlog.md`. Источники развилок — не только код: (1) разрывы из MAP («миграционные» вопросы); (2) обязательный свип по `resources/question_coverage.md` — 12 измерений требований (цель, пользователи, функциональный охват, стратегия, интерфейс, права, данные, интеграции, надёжность, эксплуатация, правила игры, приёмка), каждое закрыто карточкой или явным «не применимо» с причиной; (3) два взгляда — «изнутри» (как устроено, что сломается) и «снаружи» (если бы строили с нуля): для задач замены/переезда хотя бы одна карточка с вариантом «не переносить / переосмыслить». Добавь «Карту покрытия» и «Баланс адресатов» в конец бэклога (шаблон в `ideal_decision_backlog.md`). Критерий включения: развилку нельзя закрыть чтением кода — решение за человеком. Ранжировать, пометить блокеров. Проверить по `resources/decision_backlog_checklist.md` (Hard Gates).

**BRIEF** — спроецировать бэклог в `03_brief.md` по `ideal_brief.md`: только бизнес, топ-3 для руководства, рекомендации, цена ошибки. Проверить тестом «понял бы руководитель без кода?».

**ACTION POINTS** — сформировать `04_action_points.md` по `ideal_action_points.md`: что аналитику делать дальше (investigate/meeting/request/measure), какие `[NEEDS_INVESTIGATION]` проверить, что кандидат на поднятие в `tasks.md`.

**ЗАГЛУШКИ:** создай пустой `02_answers.md` (шаблон `ideal_answers.md`) и `task.md` (шаблон `ideal_task_handoff.md`, раздел Requirements со статусами 🔴 по открытым развилкам).

### Этап 2-CONTINUE: доформировать/финализировать (для режима CONTINUE)

Работаешь **в существующем досье** (новая папка НЕ создаётся).

1. Прочитай уже существующие `00_context.md`, `01_decision_backlog.md`, `02_answers.md`, `03_brief.md`/`04_action_points.md` этого досье.
2. Прогони бэклог по карте покрытия (`resources/question_coverage.md`, 12 измерений + два взгляда). Незакрытые измерения — сформулируй новые карточки (🔴), добавь/обнови «Карту покрытия» и «Сводку бэклога». Это штатный путь дозаполнения существующего досье: существующие 🟢-ответы не трогай, новые вопросы открывай отдельными карточками.
3. Если на входе `03_brief.md`: (пере)сформируй `01_decision_backlog.md` и `04_action_points.md` из брифинга (например, после встречи брифинг обновлён) и финализируй `task.md`.
4. Если на входе `04_action_points.md`: финализируй `task.md` из текущего состояния досье (action_points + answers + backlog), проверь Definition of Ready.
5. Проверь `task.md` по Definition of Ready (SKILL.md). Дай явный ответ: готов к `/fnr-concept` или какие развилки ещё блокируют.

### Этап 3: Самопроверка

- Прогони `resources/decision_backlog_checklist.md` по `01_decision_backlog.md` — устранить нарушения Hard Gates.
- Проверь «Карту покрытия» (`resources/question_coverage.md`): все 12 измерений закрыты карточкой или «не применимо» с причиной; для задач замены есть вариант «не переносить / переосмыслить»; адресаты сбалансированы.
- Проверь два слоя языка (`resources/two_layer_language.md`): в `03_brief.md` и бизнес-полях карточек нет техники.
- Убедись, что каждая `[NEEDS_INVESTIGATION]` из бэклога отражена в `04_action_points.md`.
- Убедись, что `tasks.md` **не тронут**.

### Этап 4: Завершение

Выведи:
- Режим (NEW/CONTINUE) и путь к досье.
- Сколько развилок заведено, сколько блокеров 🔴.
- Готов ли `task.md` к `/fnr-concept` (Definition of Ready) — да/нет, и что блокирует.
- Подсказку: «Для записи ответов руководства: `/discovery-answer D-N "ответ"`. Для пересборки брифинга: `/discovery-brief`. Когда все блокеры 🟢 — `/fnr-concept sa_documentation/FNR/FNR_<N>/task.md`.»
